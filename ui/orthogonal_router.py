"""Incremental rectilinear routing, independent of Qt.

Coordinates are scene coordinates. Obstacles include clearance for rounded
corners and the wire's selection glow. Unchanged routes cost a dictionary lookup;
the spatial indexes limit collision checks and invalidation to nearby geometry.
Search is cooperative: a caller supplies one deadline for the entire frame.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from heapq import heappop, heappush
from math import floor
from time import perf_counter
from typing import Iterator

Point = tuple[float, float]
Rect = tuple[float, float, float, float]
Route = tuple[Point, ...]
CLEARANCE = 18.0
CORNER_RADIUS = 8.0
WIRE_SPACING = 12.0
BEND_COST = 24.0
MAX_SEARCH_STATES = 65536


def _overlaps(a: Rect, b: Rect) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _bounds(points: Route) -> Rect:
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def _simplify(points: Route) -> Route:
    result: list[Point] = []
    for point in points:
        if result and point == result[-1]:
            continue
        while len(result) >= 2:
            a, b = result[-2:]
            # Only remove a middle point, never an out-and-back port lead.
            if ((a[0] == b[0] == point[0] and (b[1]-a[1]) * (point[1]-b[1]) >= 0)
                    or (a[1] == b[1] == point[1]
                        and (b[0]-a[0]) * (point[0]-b[0]) >= 0)):
                result.pop()
            else:
                break
        result.append(point)
    return tuple(result)


class _SpatialIndex:
    """Uniform buckets, with a bounded-cost fallback for very large rectangles."""

    def __init__(self) -> None:
        self.rects: dict[str, Rect] = {}
        self.buckets: dict[tuple[int, int], set[str]] = {}
        self.large: set[str] = set()

    @staticmethod
    def _cells(rect: Rect):
        x0, y0, x1, y1 = (floor(v / 256.0) for v in rect)
        if (x1-x0+1) * (y1-y0+1) > 256:
            return None
        return [(x, y) for x in range(x0, x1+1) for y in range(y0, y1+1)]

    def remove(self, key: str) -> None:
        rect = self.rects.pop(key, None)
        if rect is None:
            return
        self.large.discard(key)
        for cell in self._cells(rect) or ():
            bucket = self.buckets[cell]
            bucket.discard(key)
            if not bucket:
                del self.buckets[cell]

    def put(self, key: str, rect: Rect) -> None:
        self.remove(key)
        self.rects[key] = rect
        cells = self._cells(rect)
        if cells is None:
            self.large.add(key)
        else:
            for cell in cells:
                self.buckets.setdefault(cell, set()).add(key)

    def query(self, rect: Rect) -> set[str]:
        cells = self._cells(rect)
        if cells is None:
            candidates = self.rects.keys()
        else:
            candidates = self.large.copy()
            for cell in cells:
                candidates.update(self.buckets.get(cell, ()))
        return {key for key in candidates if _overlaps(rect, self.rects[key])}


@dataclass
class _Entry:
    key: tuple
    search: Iterator | None
    terminals: frozenset
    points: Route | None = None


class OrthogonalRouter:
    def __init__(self) -> None:
        self._nodes: dict[str, Rect] = {}
        self._obstacles = _SpatialIndex()
        self._route_bounds = _SpatialIndex()
        self._routes: dict[str, _Entry] = {}
        self._unfinished: set[str] = set()
        self._failed: set[str] = set()
        self._lanes: tuple[list[float], list[float]] | None = None
        # Parallel wires only compete with nearby parallel coordinates. These
        # 1-D bins avoid examining all perpendicular wires at every crossing.
        self._segment_tracks: tuple[dict[int, set], dict[int, set]] = ({}, {})
        self._segment_data: dict[tuple, tuple[Point, Point, frozenset]] = {}
        self._wire_segments: dict[str, list[tuple]] = {}

    def set_nodes(self, nodes: dict[str, Rect]) -> None:
        """Synchronize actual painted bounds, including dynamic node resizing."""
        changed = {key for key in self._nodes.keys() | nodes.keys()
                   if self._nodes.get(key) != nodes.get(key)}
        if not changed:
            return
        self._lanes = None
        invalid = self._unfinished | self._failed
        for key in changed:
            old = self._obstacles.rects.get(key)
            if old is not None:
                invalid.update(self._touching_routes(old))
            self._obstacles.remove(key)
            if key in nodes:
                l, t, r, b = nodes[key]
                rect = (l-CLEARANCE, t-CLEARANCE, r+CLEARANCE, b+CLEARANCE)
                self._obstacles.put(key, rect)
                invalid.update(self._touching_routes(rect))
        for key in invalid:
            self._discard(key)
        self._nodes = nodes.copy()

    def _touching_routes(self, rect: Rect) -> set[str]:
        # Route bounding boxes are only the broad phase. A long bent wire can
        # enclose many unrelated nodes; keep it cached unless a segment is near
        # the changed obstacle. Inclusive edges also catch routes along a node
        # that was removed, allowing them to become straight again.
        result = set()
        for key in self._route_bounds.query(rect):
            points = self._routes[key].points
            for a, b in zip(points, points[1:]):
                if _overlaps((min(a[0], b[0]), min(a[1], b[1]),
                              max(a[0], b[0]), max(a[1], b[1])), rect):
                    result.add(key)
                    break
        return result

    def _discard(self, key: str) -> None:
        for segment_id in self._wire_segments.pop(key, ()):
            a, b, _ = self._segment_data.pop(segment_id)
            axis = 0 if a[1] == b[1] else 1
            lane = floor(a[1-axis] / WIRE_SPACING)
            tracks = self._segment_tracks[axis]
            tracks[lane].remove(segment_id)
            if not tracks[lane]:
                del tracks[lane]
        self._routes.pop(key, None)
        self._route_bounds.remove(key)
        self._unfinished.discard(key)
        self._failed.discard(key)

    def retain(self, wire_ids: set[str]) -> None:
        for key in self._routes.keys() - wire_ids:
            self._discard(key)

    @property
    def pending(self) -> bool:
        return bool(self._unfinished)

    def _clear(self, a: Point, b: Point, ignore: str | None = None) -> bool:
        rect = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        for key in self._obstacles.query(rect):
            if key == ignore:
                continue
            l, t, r, bottom = self._obstacles.rects[key]
            if a[1] == b[1]:
                if t < a[1] < bottom and rect[0] < r and rect[2] > l:
                    return False
            elif a[0] == b[0]:
                if l < a[0] < r and rect[1] < bottom and rect[3] > t:
                    return False
            else:
                raise ValueError("Router segments must be axis aligned")
        return True

    def stubs(self, start: Point, end: Point, source: str,
              target: str | None) -> tuple[Route, ...]:
        """Safe port markers while routing or when overlapping nodes block a wire."""
        leads = [((start, (start[0]+CLEARANCE, start[1])), source)]
        if target is not None:
            leads.append((((end[0]-CLEARANCE, end[1]), end), target))
        return tuple(points for points, owner in leads
                     if self._clear(*points, ignore=owner))

    def route(self, wire_id: str, start: Point, end: Point, source: str,
              target: str | None, deadline: float, *,
              source_pin: str | None = None, target_pin: str | None = None) -> Route | None:
        """Return a cached route, () if blocked, or None while work is pending."""
        key = (start, end, source, target, source_pin, target_pin)
        entry = self._routes.get(wire_id)
        if entry is None or entry.key != key:
            terminals = frozenset(((source, "out", source_pin if source_pin is not None else start),)
                                 + (((target, "in", target_pin if target_pin is not None else end),)
                                    if target is not None else ()))
            self._discard(wire_id)
            entry = _Entry(key, self._search(start, end, source, target, terminals), terminals)
            self._routes[wire_id] = entry
            self._unfinished.add(wire_id)
        while entry.search is not None and perf_counter() < deadline:
            try:
                next(entry.search)
            except StopIteration as done:
                entry.points = done.value
                entry.search = None
                self._unfinished.discard(wire_id)
                if entry.points:
                    self._route_bounds.put(wire_id, _bounds(entry.points))
                    # A mouse preview avoids real wires but never reserves a
                    # lane that could displace a permanent connection.
                    if wire_id != "__preview__":
                        self._reserve(wire_id, entry.points, entry.terminals)
                else:
                    self._failed.add(wire_id)
        return entry.points

    def _reserve(self, wire_id: str, points: Route, terminals: frozenset) -> None:
        ids = []
        for i, (a, b) in enumerate(zip(points, points[1:])):
            segment_id = (wire_id, i)
            axis = 0 if a[1] == b[1] else 1
            lane = floor(a[1-axis] / WIRE_SPACING)
            self._segment_tracks[axis].setdefault(lane, set()).add(segment_id)
            self._segment_data[segment_id] = (a, b, terminals)
            ids.append(segment_id)
        self._wire_segments[wire_id] = ids

    def _conflicts(self, points: Route, terminals: frozenset):
        """Parallel overlap only: perpendicular crossings do not merge traces."""
        conflicts = []
        for i, (a, b) in enumerate(zip(points, points[1:])):
            horizontal = a[1] == b[1]
            axis, fixed = (0, 1) if horizontal else (1, 0)
            lo, hi = sorted((a[axis], b[axis]))
            lane = floor(a[fixed] / WIRE_SPACING)
            tracks = self._segment_tracks[axis]
            for near_lane in (lane-1, lane, lane+1):
                for key in tracks.get(near_lane, ()):
                    c, d, owners = self._segment_data[key]
                    if not terminals.isdisjoint(owners):
                        continue
                    overlap = min(hi, max(c[axis], d[axis])) - max(lo, min(c[axis], d[axis]))
                    # Also separate end-to-end touches that would look like a
                    # junction between unrelated wires after corner rounding.
                    if overlap > -WIRE_SPACING + 1e-7 and abs(a[fixed]-c[fixed]) < WIRE_SPACING - 1e-7:
                        conflicts.append((i, max(0, overlap)+WIRE_SPACING, c[fixed]))
        return conflicts

    @staticmethod
    def _offset_segment(points: Route, index: int, offset: float) -> Route:
        a, b = points[index:index+2]
        axis, fixed = (0, 1) if a[1] == b[1] else (1, 0)
        before, after = list(points[:index]), list(points[index+2:])
        # Keep terminal positions and straight port leads fixed. Internal turns
        # move with the segment, extending or shortening their adjacent legs.
        if index == 0:
            if abs(b[axis]-a[axis]) <= CLEARANCE * 2:
                return points
            lead = list(a)
            lead[axis] += CLEARANCE if b[axis] > a[axis] else -CLEARANCE
            before.extend((a, tuple(lead)))
            a = tuple(lead)
        if index == len(points)-2:
            if abs(b[axis]-a[axis]) <= CLEARANCE * 2:
                return points
            lead = list(b)
            lead[axis] -= CLEARANCE if b[axis] > a[axis] else -CLEARANCE
            after = [tuple(lead), b]
            b = tuple(lead)
        shifted_a, shifted_b = list(a), list(b)
        shifted_a[fixed] += offset
        shifted_b[fixed] += offset
        return _simplify(tuple(before) + (tuple(shifted_a), tuple(shifted_b)) + tuple(after))

    def _valid_route(self, points: Route, source: str, target: str | None) -> bool:
        # Revalidate every segment after moving a lane, including port direction.
        for a, b, c in zip(points, points[1:], points[2:]):
            if a[0] == b[0] == c[0] or a[1] == b[1] == c[1]:
                return False  # Do not introduce retraced legs while nudging.
        first, second = points[:2]
        if first[1] != second[1] or second[0] < first[0]+CLEARANCE:
            return False
        if target is not None:
            previous, last = points[-2:]
            if previous[1] != last[1] or previous[0] > last[0]-CLEARANCE:
                return False
        for i, (a, b) in enumerate(zip(points, points[1:])):
            if a[0] != b[0] and a[1] != b[1]:
                return False
            if i == 0:
                lead = (a[0]+CLEARANCE, a[1])
                if not self._clear(a, lead, source) or not self._clear(lead, b):
                    return False
            elif i == len(points)-2 and target is not None:
                lead = (b[0]-CLEARANCE, b[1])
                if not self._clear(a, lead) or not self._clear(lead, b, target):
                    return False
            elif not self._clear(a, b):
                return False
        return True

    def _spread(self, points: Route, source: str, target: str | None, terminals: frozenset):
        # Local lane nudges keep node routing cheap and preserve already stable
        # wires. Try the nearest vacant tracks first, bounded and cooperative.
        attempts = 0
        for _ in range(16):
            conflicts = self._conflicts(points, terminals)
            if not conflicts:
                return points
            score = sum(c[1] for c in conflicts)
            best = points
            costs = {}
            for index, cost, _ in conflicts:
                costs[index] = costs.get(index, 0) + cost
            for index in sorted(costs, key=lambda i: (-costs[i], i)):
                a, b = points[index:index+2]
                fixed = 1 if a[1] == b[1] else 0
                # Prefer nested bends over introducing a crossing when both
                # equally close tracks are vacant (e.g. a multiplexer fan-in).
                preferred = b[0]-a[0] if fixed == 1 else a[1]-b[1]
                offsets = {coordinate-a[fixed]+side*WIRE_SPACING
                           for i, _, coordinate in conflicts if i == index for side in (-1, 1)}
                offsets.update(side*WIRE_SPACING*step for side in (-1, 1) for step in range(1, 9))
                for offset in sorted(offsets, key=lambda value: (abs(value), value*preferred < 0, value)):
                    attempts += 1
                    if attempts > 64:
                        return points
                    candidate = self._offset_segment(points, index, offset)
                    if candidate != points and self._valid_route(candidate, source, target):
                        candidate_score = sum(c[1] for c in self._conflicts(candidate, terminals))
                        if candidate_score == 0:
                            return candidate
                        if candidate_score < score:
                            best = candidate
                            break
                    yield
                if best != points:
                    break
            if best == points:
                # A physically crowded corridor can have no vacant lane. Keep
                # the valid node-avoiding connection rather than hiding it.
                return points
            points = best
        return points

    def _search(self, start: Point, end: Point, source: str,
                target: str | None, terminals: frozenset):
        points = yield from self._node_route(start, end, source, target)
        if not points:
            return points
        return (yield from self._spread(points, source, target, terminals))

    def _node_route(self, start: Point, end: Point, source: str,
                    target: str | None):
        a = (start[0]+CLEARANCE, start[1])
        b = (end[0]-CLEARANCE, end[1]) if target is not None else end
        if not self._clear(start, a, source) or not self._clear(b, end, target):
            return ()
        # A cursor inside an obstacle cannot be reached. Port leads may cross
        # their owner's padded bounds; no other segment gets that exemption.
        for point in (a, b):
            for key in self._obstacles.query((*point, *point)):
                l, t, r, bottom = self._obstacles.rects[key]
                if l < point[0] < r and t < point[1] < bottom:
                    return ()
        mid = (a[0]+b[0]) / 2
        candidates = [
            (a, (mid, a[1]), (mid, b[1]), b),
            (a, (b[0], a[1]), b),
            (a, (a[0], b[1]), b),
        ]
        nearby = self._obstacles.query(_bounds((a, b)))
        if nearby:
            top = min(self._obstacles.rects[k][1] for k in nearby)
            bottom = max(self._obstacles.rects[k][3] for k in nearby)
            for y in sorted((top, bottom), key=lambda y: abs(a[1]-y)+abs(b[1]-y)):
                candidates.append((a, (a[0], y), (b[0], y), b))
        for points in candidates:
            points = _simplify(points)
            if all(self._clear(p, q) for p, q in zip(points, points[1:])):
                return _simplify((start, *points, end))
            yield

        # Shared free rows/columns handle large, loosely aligned graphs without
        # exploring every intersection of their slightly different coordinates.
        # These lanes are outside ALL padded obstacles, so vertical/horizontal
        # travel along them is safe regardless of the length of the connection.
        if self._lanes is None:
            self._lanes = (self._free_lanes(0, 2), self._free_lanes(1, 3))
        x_lanes, y_lanes = self._lanes
        escapes = []
        for point in (a, b):
            escape = None
            for x in sorted(x_lanes, key=lambda x: abs(x-point[0])):
                if self._clear(point, (x, point[1])):
                    escape = x
                    break
                yield
            escapes.append(escape)
        if all(x is not None for x in escapes) and y_lanes:
            ax, bx = escapes
            y = min(y_lanes, key=lambda y: abs(y-a[1])+abs(y-b[1]))
            return _simplify((start, a, (ax, a[1]), (ax, y),
                              (bx, y), (bx, b[1]), b, end))
        yield

        # Lazy visibility grid: allocate only visited intersections, not an
        # N-by-N grid. Obstacle boundaries guarantee possible rectilinear turns.
        xs = sorted({a[0], b[0]} | {v for r in self._obstacles.rects.values() for v in (r[0], r[2])})
        ys = sorted({a[1], b[1]} | {v for r in self._obstacles.rects.values() for v in (r[1], r[3])})
        origin = (bisect_left(xs, a[0]), bisect_left(ys, a[1]), 0)
        goal = (bisect_left(xs, b[0]), bisect_left(ys, b[1]))
        costs = {origin: 0.0}
        parents = {}
        queue = [(abs(a[0]-b[0])+abs(a[1]-b[1]), 0.0, origin)]
        yield
        iterations = 0
        while queue:
            _, cost, state = heappop(queue)
            if cost != costs[state]:
                continue
            ix, iy, direction = state
            if (ix, iy) == goal:
                points = []
                while state in parents:
                    points.append((xs[state[0]], ys[state[1]]))
                    state = parents[state]
                points.append(a)
                return _simplify((start, *reversed(points), end))
            if len(costs) >= MAX_SEARCH_STATES:
                return ()
            point = (xs[ix], ys[iy])
            for nx, ny, axis in ((ix-1, iy, 0), (ix+1, iy, 0),
                                 (ix, iy-1, 1), (ix, iy+1, 1)):
                if not (0 <= nx < len(xs) and 0 <= ny < len(ys)):
                    continue
                neighbor = (xs[nx], ys[ny])
                if not self._clear(point, neighbor):
                    continue
                distance = abs(point[0]-neighbor[0])+abs(point[1]-neighbor[1])
                new_cost = cost + distance + (BEND_COST if axis != direction else 0)
                next_state = (nx, ny, axis)
                if new_cost < costs.get(next_state, float('inf')):
                    costs[next_state] = new_cost
                    parents[next_state] = state
                    # A modest heuristic weight favors quick, short routes over
                    # exhaustively proving the absolute minimum-length route.
                    remaining = 1.5 * (abs(neighbor[0]-b[0])+abs(neighbor[1]-b[1]))
                    heappush(queue, (new_cost+remaining, new_cost, next_state))
            iterations += 1
            if iterations % 16 == 0:
                yield
        return ()

    def _free_lanes(self, low: int, high: int) -> list[float]:
        intervals = sorted((rect[low], rect[high]) for rect in self._obstacles.rects.values())
        if not intervals:
            return []
        lanes = [intervals[0][0]-CLEARANCE]
        end = intervals[0][1]
        for left, right in intervals[1:]:
            if left > end:
                lanes.append((end+left) / 2)
            end = max(end, right)
        lanes.append(end+CLEARANCE)
        return lanes
