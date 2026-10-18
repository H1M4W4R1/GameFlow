"""Run: python -B -m unittest discover -s tests -p test_wire_routing.py"""
import os
import random
import statistics
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QImage, QPainter, QPainterPathStroker
from PyQt6.QtWidgets import QApplication

from core.graph_runtime import GraphRuntime
from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType, WireDescriptor
from ui.node_editor_canvas import NodeEditorCanvas
from ui.orthogonal_router import OrthogonalRouter


def complete(router, start, end, source="s", target="t", wire_id="w", **pins):
    limit = time.perf_counter() + 5
    while time.perf_counter() < limit:
        route = router.route(wire_id, start, end, source, target,
                             time.perf_counter() + 0.004, **pins)
        if route is not None:
            return route
    raise AssertionError("Route did not finish")


def assert_clear(test, points, nodes):
    test.assertTrue(points, "Expected a complete route")
    for a, b in zip(points, points[1:]):
        test.assertTrue(a[0] == b[0] or a[1] == b[1])
        # Independent segment/rectangle intersection, without router helpers.
        for key, (l, t, r, bottom) in nodes.items():
            if a[1] == b[1]:
                intersects = t < a[1] < bottom and min(a[0], b[0]) < r and max(a[0], b[0]) > l
            else:
                intersects = l < a[0] < r and min(a[1], b[1]) < bottom and max(a[1], b[1]) > t
            test.assertFalse(intersects, (key, a, b))
    path = NodeEditorCanvas._rounded_wire_path(points)
    # QPainterPath.intersects treats an open path as an implicitly closed fill.
    # Test the visible curve's thin stroke instead of that enclosed area.
    stroker = QPainterPathStroker()
    stroker.setWidth(.1)
    stroke = stroker.createStroke(path)
    for key, (l, t, r, bottom) in nodes.items():
        test.assertFalse(stroke.intersects(QRectF(l+.1, t+.1, r-l-.2, bottom-t-.2)), key)


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.router = OrthogonalRouter()
        self.nodes = {"s": (0, 0, 190, 120), "t": (800, 0, 990, 120)}
        self.router.set_nodes(self.nodes)

    def route(self):
        points = complete(self.router, (190, 60), (800, 60))
        assert_clear(self, points, self.nodes)
        return points

    def test_direct_and_cached(self):
        points = self.route()
        self.assertEqual(points, ((190, 60), (800, 60)))
        with patch.object(self.router, "_search", side_effect=AssertionError("Cache miss")):
            self.router.set_nodes(dict(self.nodes))
            self.assertIs(self.route(), points)

    def test_obstacle_and_selected_wire_clearance(self):
        self.nodes["obstacle"] = (350, -50, 540, 170)
        self.router.set_nodes(self.nodes)
        path = NodeEditorCanvas._rounded_wire_path(self.route())
        stroke = QPainterPathStroker()
        stroke.setWidth(9.5)  # Maximum selected-wire glow.
        self.assertFalse(stroke.createStroke(path).intersects(QRectF(350, -50, 190, 220)))

    def test_self_loop(self):
        points = complete(self.router, (190, 40), (0, 80), target="s")
        assert_clear(self, points, self.nodes)
        self.assertEqual(points[0], (190, 40))
        self.assertEqual(points[-1], (0, 80))

    def test_backward_connection(self):
        points = complete(self.router, (990, 40), (0, 80), source="t", target="s")
        assert_clear(self, points, self.nodes)

    def test_vertical_connection(self):
        self.nodes["t"] = (0, 350, 190, 470)
        self.router.set_nodes(self.nodes)
        points = complete(self.router, (190, 60), (0, 410))
        assert_clear(self, points, self.nodes)

    def test_move_unconnected_node_into_wire_then_remove(self):
        direct = self.route()
        self.nodes["obstacle"] = (350, 300, 540, 420)
        self.router.set_nodes(self.nodes)
        self.assertIs(self.route(), direct)
        self.nodes["obstacle"] = (350, 0, 540, 120)
        self.router.set_nodes(self.nodes)
        self.assertNotEqual(self.route(), direct)
        del self.nodes["obstacle"]
        self.router.set_nodes(self.nodes)
        self.assertEqual(self.route(), direct)

    def test_moving_inside_empty_route_bounds_preserves_cache(self):
        self.nodes["obstacle"] = (350, -50, 540, 170)
        self.router.set_nodes(self.nodes)
        points = self.route()
        # Inside the enclosing rectangle, but away from every routed segment.
        self.nodes["unrelated"] = (600, -20, 680, 20)
        self.router.set_nodes(self.nodes)
        self.assertIs(self.route(), points)

    def test_resize_and_move_endpoint(self):
        self.route()
        self.nodes["s"] = (0, 0, 250, 200)
        self.nodes["t"] = (600, 300, 790, 420)
        self.router.set_nodes(self.nodes)
        points = complete(self.router, (250, 60), (600, 360))
        assert_clear(self, points, self.nodes)

    def test_overlap_does_not_fall_back_to_crossing(self):
        self.nodes["obstacle"] = (185, 0, 400, 120)
        self.router.set_nodes(self.nodes)
        self.assertEqual(complete(self.router, (190, 60), (800, 60)), ())
        for stub in self.router.stubs((190, 60), (800, 60), "s", "t"):
            assert_clear(self, stub, self.nodes)
        del self.nodes["obstacle"]
        self.router.set_nodes(self.nodes)
        self.route()

    def test_preview(self):
        points = complete(self.router, (190, 60), (500, 220), target=None)
        assert_clear(self, points, self.nodes)
        self.assertEqual(points[-1], (500, 220))
        self.assertEqual(complete(self.router, (190, 60), (850, 60), target=None), ())

    def test_deferred_work_and_pruning(self):
        self.assertIsNone(self.router.route("w", (190, 60), (800, 60), "s", "t", 0))
        self.assertTrue(self.router.pending)
        self.route()
        self.assertFalse(self.router.pending)
        self.router.retain(set())
        self.assertFalse(self.router._routes)
        self.assertFalse(self.router._route_bounds.rects)

    def test_astar_resumes_between_frames(self):
        self.nodes = {
            "s": (0, 0, 100, 100), "t": (800, 0, 900, 100),
            "wall1": (300, -200, 350, 150), "wall2": (500, 0, 550, 300),
            "top": (110, -200, 250, -50), "bottom": (600, 100, 800, 250),
        }
        self.router.set_nodes(self.nodes)
        points = None
        frames = 0
        # Exercise the general search even when global free lanes are available.
        with patch.object(self.router, "_free_lanes", return_value=[]):
            while points is None and frames < 1000:
                points = self.router.route("w", (100, 50), (800, 50), "s", "t",
                                           time.perf_counter() + 0.00001)
                frames += 1
        self.assertGreater(frames, 1)
        assert_clear(self, points, self.nodes)

    def test_negative_and_large_coordinates(self):
        self.nodes = {"s": (-10000, -100, -9810, 20), "t": (10000, -100, 10190, 20),
                      "huge": (-9000, -1000, 9000, 1000)}
        self.router.set_nodes(self.nodes)
        points = complete(self.router, (-9810, -50), (10000, -50))
        assert_clear(self, points, self.nodes)

    def test_randomized_nonoverlapping_layouts(self):
        rng = random.Random(574)
        nodes = {str(i): (x*300, y*230, x*300+190, y*230+120)
                 for i, (x, y) in enumerate((x, y) for x in range(8) for y in range(6))}
        self.router.set_nodes(nodes)
        for i in range(200):
            source, target = rng.choices(list(nodes), k=2)
            sr, tr = nodes[source], nodes[target]
            start, end = (sr[2], sr[1]+60), (tr[0], tr[1]+60)
            points = complete(self.router, start, end, source, target, str(i))
            assert_clear(self, points, nodes)

    def test_irregular_layout_free_lanes(self):
        rng = random.Random(582)
        nodes = {}
        for i in range(150):
            x, y = (i % 15)*340+rng.randrange(50), (i//15)*240+rng.randrange(50)
            nodes[str(i)] = (x, y, x+190, y+120)
        self.router.set_nodes(nodes)
        for i in range(300):
            source, target = rng.choices(list(nodes), k=2)
            sr, tr = nodes[source], nodes[target]
            points = complete(self.router, (sr[2], sr[1]+60), (tr[0], tr[1]+60),
                              source, target, str(i))
            assert_clear(self, points, nodes)


def parallel_overlaps(first, second, spacing=11.99):
    overlaps = []
    for a, b in zip(first, first[1:]):
        for c, d in zip(second, second[1:]):
            if a[1] == b[1] and c[1] == d[1]:
                if abs(a[1]-c[1]) < spacing and max(min(a[0], b[0]), min(c[0], d[0])) < min(max(a[0], b[0]), max(c[0], d[0])):
                    overlaps.append((a, b, c, d))
            elif a[0] == b[0] and c[0] == d[0]:
                if abs(a[0]-c[0]) < spacing and max(min(a[1], b[1]), min(c[1], d[1])) < min(max(a[1], b[1]), max(c[1], d[1])):
                    overlaps.append((a, b, c, d))
    return overlaps


class SeparationTests(unittest.TestCase):
    def test_four_sources_to_distinct_multiplexer_pins(self):
        nodes = {f"s{i}": (0, i*100, 190, i*100+80) for i in range(4)}
        nodes["mux"] = (1000, 100, 1190, 350)
        router = OrthogonalRouter()
        router.set_nodes(nodes)
        routes = []
        for i in range(4):
            points = complete(router, (190, i*100+40), (1000, 140+i*24),
                              f"s{i}", "mux", str(i), source_pin="out", target_pin=f"in_{i}")
            assert_clear(self, points, nodes)
            for previous in routes:
                self.assertFalse(parallel_overlaps(points, previous))
            routes.append(points)
        cached = list(routes)
        for i in range(4):
            self.assertIs(complete(router, (190, i*100+40), (1000, 140+i*24),
                                   f"s{i}", "mux", str(i), source_pin="out", target_pin=f"in_{i}"), cached[i])

    def test_different_pins_on_same_nodes_do_not_bundle(self):
        router = OrthogonalRouter()
        nodes = {"s": (0, 0, 190, 160), "t": (800, 120, 990, 280)}
        router.set_nodes(nodes)
        first = complete(router, (190, 40), (800, 160), wire_id="1", source_pin="a", target_pin="a")
        second = complete(router, (190, 64), (800, 184), wire_id="2", source_pin="b", target_pin="b")
        assert_clear(self, second, nodes)
        self.assertFalse(parallel_overlaps(first, second))

    def test_shared_source_pin_can_bundle(self):
        router = OrthogonalRouter()
        router.set_nodes({"s": (0, 0, 190, 120), "t": (800, 100, 990, 350)})
        first = complete(router, (190, 60), (800, 160), wire_id="1", source_pin="out", target_pin="a")
        second = complete(router, (190, 60), (800, 280), wire_id="2", source_pin="out", target_pin="b")
        self.assertTrue(parallel_overlaps(first, second, spacing=.01))

    def test_horizontal_detours_stay_separate_and_clear_of_obstacles(self):
        router = OrthogonalRouter()
        nodes = {"s": (0, 0, 190, 160), "t": (800, 0, 990, 160),
                 "obstacle": (350, -20, 540, 220)}
        router.set_nodes(nodes)
        first = complete(router, (190, 40), (800, 40), wire_id="1", source_pin="a", target_pin="a")
        second = complete(router, (190, 64), (800, 64), wire_id="2", source_pin="b", target_pin="b")
        assert_clear(self, first, nodes)
        assert_clear(self, second, nodes)
        self.assertFalse(parallel_overlaps(first, second))

    def test_deletion_releases_reserved_segments(self):
        router = OrthogonalRouter()
        router.set_nodes({"s": (0, 0, 190, 160), "t": (800, 120, 990, 280)})
        complete(router, (190, 40), (800, 160), wire_id="1")
        router.retain(set())
        self.assertFalse(router._segment_data)
        self.assertFalse(any(router._segment_tracks))
        second = complete(router, (190, 64), (800, 184), wire_id="2")
        self.assertIn((495.0, 64), second)

    def test_preview_does_not_reserve_tracks(self):
        router = OrthogonalRouter()
        router.set_nodes({"s": (0, 0, 190, 160), "t": (800, 120, 990, 280)})
        complete(router, (190, 40), (800, 160), wire_id="__preview__")
        self.assertFalse(router._segment_data)

    def test_moving_endpoint_releases_old_track_and_avoids_existing_wire(self):
        router = OrthogonalRouter()
        nodes = {"s": (0, 0, 190, 160), "t": (800, 120, 990, 280),
                 "other": (0, 300, 190, 420)}
        router.set_nodes(nodes)
        first = complete(router, (190, 40), (800, 160), wire_id="1")
        complete(router, (190, 340), (800, 184), source="other", wire_id="2")
        nodes["other"] = (0, 200, 190, 280)
        router.set_nodes(nodes)
        second = complete(router, (190, 240), (800, 184), source="other", wire_id="2")
        assert_clear(self, second, nodes)
        self.assertFalse(parallel_overlaps(first, second))
        self.assertEqual(len(router._wire_segments['2']), len(second)-1)

    def test_reconnecting_pin_invalidates_bundle_exemption(self):
        router = OrthogonalRouter()
        router.set_nodes({"s": (0, 0, 190, 160), "t": (800, 120, 990, 280)})
        first = complete(router, (190, 40), (800, 160), wire_id="1", source_pin="a", target_pin="a")
        bundled = complete(router, (190, 64), (800, 184), wire_id="2", source_pin="a", target_pin="b")
        separated = complete(router, (190, 64), (800, 184), wire_id="2", source_pin="b", target_pin="b")
        self.assertTrue(parallel_overlaps(first, bundled))
        self.assertFalse(parallel_overlaps(first, separated))


class _TestNode(NodeBase):
    PINS = [PinDescriptor("out", PinDirection.OUTPUT, PinType.FLOAT),
            PinDescriptor("in", PinDirection.INPUT, PinType.FLOAT)]

    def execute(self, trigger_pin):
        pass


class CanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.runtime = GraphRuntime()
        for key, x, y in (("s", 40, 150), ("t", 800, 150), ("obstacle", 400, 130)):
            node = _TestNode(key)
            node.x, node.y = x, y
            self.runtime.add_node(node)
        self.runtime.add_wire(WireDescriptor("w", "s", "out", "t", "in"))
        self.canvas = NodeEditorCanvas(self.runtime, lambda: {})
        self.canvas.resize(1100, 650)

    def tearDown(self):
        self.canvas.close()
        self.canvas.deleteLater()
        self.app.processEvents()

    def render(self):
        image = QImage(self.canvas.size(), QImage.Format.Format_ARGB32)
        for _ in range(100):
            painter = QPainter(image)
            self.canvas.render(painter)
            painter.end()
            if not self.canvas._wire_router.pending:
                return image
        self.fail("Canvas did not finish routing")

    def test_render_select_pan_zoom_move_delete(self):
        self.render()
        points = self.canvas._wire_router._routes["w"].points
        assert_clear(self, points, self.canvas._routing_node_rects)
        path = self.canvas._wire_paths["w"][1]
        self.assertEqual(self.canvas._hit_wire(path.pointAtPercent(.5)), "w")
        self.assertIsNone(self.canvas._hit_wire(QPointF(-100, -100)))
        self.canvas._offset = QPointF(20, 30)
        self.canvas._zoom = 1.5
        self.canvas._selected_wire = "w"
        self.render()
        self.assertIs(self.canvas._wire_paths["w"][1], path)
        # Move an unrelated node onto the existing horizontal wire segment.
        self.runtime.get_node("obstacle").y = 200
        self.render()
        self.assertNotEqual(self.canvas._wire_router._routes["w"].points, points)
        assert_clear(self, self.canvas._wire_router._routes["w"].points,
                     self.canvas._routing_node_rects)
        self.runtime.remove_wire("w")
        self.render()
        self.assertFalse(self.canvas._wire_paths)

    def test_preview_and_self_loop_render(self):
        self.render()
        self.canvas._wire_src = self.canvas._find_pin_pos("s", "out")
        self.canvas._wire_mouse = self.canvas._find_pin_pos("t", "in").scene_pos
        self.render()
        self.assertTrue(self.canvas._wire_router._routes["__preview__"].points)
        self.canvas._wire_src = None
        self.runtime.add_wire(WireDescriptor("loop", "s", "out", "s", "in"))
        self.render()
        assert_clear(self, self.canvas._wire_router._routes["loop"].points,
                     self.canvas._routing_node_rects)
        self.assertNotIn("__preview__", self.canvas._wire_paths)


def benchmark(jitter=0):
    """Print measured routing times; do not impose machine-dependent assertions."""
    rng = random.Random(574)
    nodes = {}
    for i in range(300):
        x, y = (i % 20)*340, (i//20)*240
        if jitter:
            x, y = x+rng.randrange(jitter), y+rng.randrange(jitter)
        nodes[str(i)] = (x, y, x+190, y+120)
    wires = []
    for i in range(600):
        source, target = rng.choices(list(nodes), k=2)
        sr, tr = nodes[source], nodes[target]
        wires.append((str(i), (sr[2], sr[1]+60), (tr[0], tr[1]+60), source, target))
    router = OrthogonalRouter()
    router.set_nodes(nodes)
    times = []
    results = []
    started = time.perf_counter()
    for frame in range(10000):
        before = time.perf_counter()
        deadline = before + .004
        results = [router.route(*wire, deadline) for wire in wires]
        times.append((time.perf_counter()-before)*1000)
        if not router.pending:
            break
    print(f"300 nodes / 600 wires (jitter={jitter}): {sum(bool(r) for r in results)} complete; "
          f"cold total {(time.perf_counter()-started)*1000:.2f} ms in {len(times)} batches; "
          f"max batch {max(times):.2f} ms")
    warm = []
    for _ in range(100):
        before = time.perf_counter()
        router.set_nodes(nodes)
        for wire in wires:
            router.route(*wire, before+.004)
        warm.append((time.perf_counter()-before)*1000)
    print(f"Cached geometry + all 600 route lookups: median {statistics.median(warm):.3f} ms; "
          f"max {max(warm):.3f} ms (excludes painting)")
    before = time.perf_counter()
    moved = dict(nodes)
    l, t, r, b = moved['150']
    moved['150'] = (l+35, t+30, r+35, b+30)
    router.set_nodes(moved)
    print(f"Move one obstacle: invalidates {600-len(router._routes)} of 600 routes "
          f"in {(time.perf_counter()-before)*1000:.3f} ms")
    started = time.perf_counter()
    batches = 0
    while True:
        deadline = time.perf_counter()+.004
        results = [router.route(*wire, deadline) for wire in wires]
        batches += 1
        if not router.pending:
            break
    print(f"Reroute after move: {(time.perf_counter()-started)*1000:.3f} ms "
          f"in {batches} batches; {sum(bool(r) for r in results)} complete")


if __name__ == "__main__":
    unittest.main()
