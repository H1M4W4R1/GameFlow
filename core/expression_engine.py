"""Bounded Python AST interpreter shared by Script and Formula nodes.

Source is never passed to eval/exec. Only the syntax and functions below are
available; imports, arbitrary attributes and access to engine objects are absent.
"""
from __future__ import annotations

import ast
import math
import operator
import time
from dataclasses import dataclass
from typing import Any, Callable


MAX_SOURCE = 32_000
MAX_ITEMS = 2_000
MAX_INTEGER_BITS = 4096
MATH_FUNCTIONS = {
    name: getattr(math, name) for name in (
        "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sinh", "cosh",
        "tanh", "sqrt", "exp", "log", "log2", "log10", "floor", "ceil", "trunc",
        "fabs", "fmod", "hypot", "degrees", "radians", "isfinite", "isinf", "isnan",
    )
}
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
FUNCTIONS = {**MATH_FUNCTIONS, "abs": abs, "min": min, "max": max,
             "round": round, "int": int, "float": float, "bool": bool,
             "str": str, "len": len, "sum": sum}
FORMULA_FUNCTIONS = {**MATH_FUNCTIONS, "abs": abs, "min": min, "max": max,
                     "round": round, "pow": pow}
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
           ast.Mod: operator.mod, ast.Pow: operator.pow}
_COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
            ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
            ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
            ast.Is: operator.is_, ast.IsNot: operator.is_not}
_EXPRESSIONS = (ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp, ast.BoolOp,
                ast.Compare, ast.IfExp, ast.Call, ast.Attribute, ast.Subscript,
                ast.Slice, ast.List, ast.Tuple, ast.Dict)
_STATEMENTS = (ast.Assign, ast.AugAssign, ast.Expr, ast.If, ast.For, ast.While,
               ast.Break, ast.Continue, ast.Pass, ast.FunctionDef, ast.Return)
_OPERATORS = tuple(_BINARY) + tuple(_COMPARE) + (
    ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or, ast.Load, ast.Store,
)


class ExpressionError(ValueError):
    """A source error with an optional source line."""


def _io_arguments(call: ast.Call) -> list[ast.AST]:
    """Bind read/emit(name) or write(name, value), including keywords."""
    fields = ["name", "value"] if call.func.id == "write" else ["name"]
    if len(call.args) > len(fields):
        raise ExpressionError(f"{call.func.id} expects {len(fields)} arguments")
    bound = dict(zip(fields, call.args))
    for keyword in call.keywords:
        if keyword.arg not in fields or keyword.arg in bound:
            raise ExpressionError(f"Invalid argument to {call.func.id}")
        bound[keyword.arg] = keyword.value
    if set(bound) != set(fields):
        raise ExpressionError(f"{call.func.id} expects {', '.join(fields)}")
    return [bound[field] for field in fields]


@dataclass(frozen=True)
class Program:
    tree: ast.Module | ast.Expression
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    event_inputs: tuple[str, ...] = ()
    event_outputs: tuple[str, ...] = ()
    handlers: tuple[ast.FunctionDef, ...] = ()


def parse_program(source: str, *, formula: bool = False) -> Program:
    if len(source) > MAX_SOURCE:
        raise ExpressionError(f"Source exceeds {MAX_SOURCE} characters")
    # Formula syntax uses ^ for exponentiation with the usual power precedence.
    tree = ast.parse(source.replace("^", "**") if formula else source,
                     filename="<formula>" if formula else "<script>",
                     mode="eval" if formula else "exec")
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_ITEMS:
        raise ExpressionError("Source is too complex")
    inputs: dict[str, None] = {}
    outputs: dict[str, None] = {}
    functions = FORMULA_FUNCTIONS if formula else {**FUNCTIONS, "range": range,
                                                   "pow": pow, "read": None, "write": None, "emit": None}
    parents = {child: parent for parent in nodes for child in ast.iter_child_nodes(parent)}
    handlers: dict[str, ast.FunctionDef] = {}
    for node in nodes:
        if not isinstance(node, _EXPRESSIONS + _OPERATORS + (ast.Module, ast.Expression,
                                                            ast.keyword) + (() if formula else _STATEMENTS + (ast.arguments,))):
            raise ExpressionError(f"Line {getattr(node, 'lineno', 1)}: {type(node).__name__} is not supported")
        if formula and isinstance(node, (ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Slice)):
            raise ExpressionError("Formulas accept numeric expressions only")
        if isinstance(node, ast.Constant):
            if formula and type(node.value) not in (int, float):
                raise ExpressionError("Formula constants must be numbers")
            if type(node.value) not in (int, float, bool, str, type(None)):
                raise ExpressionError("Unsupported constant")
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise ExpressionError("Private names are not available")
            if isinstance(node.ctx, ast.Store) and node.id in {*functions, *CONSTANTS, "math"}:
                raise ExpressionError(f"'{node.id}' is reserved")
            if formula and isinstance(node.ctx, ast.Load):
                parent = parents.get(node)
                is_function = isinstance(parent, ast.Call) and parent.func is node
                is_math = isinstance(parent, ast.Attribute) and parent.value is node
                if not is_function and not is_math and node.id not in CONSTANTS:
                    inputs.setdefault(node.id, None)
        if isinstance(node, ast.Attribute):
            if not (isinstance(node.value, ast.Name) and node.value.id == "math"
                    and node.attr in {*MATH_FUNCTIONS, *CONSTANTS}):
                raise ExpressionError("Only documented math attributes are available")
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name not in functions and not (
                isinstance(node.func, ast.Attribute) and node.func.attr in MATH_FUNCTIONS
            ):
                raise ExpressionError(f"Unsupported function: {name or ast.unparse(node.func)}")
            if any(keyword.arg is None for keyword in node.keywords):
                raise ExpressionError("Expanded keyword arguments are not supported")
            if name in ("read", "write", "emit"):
                args = _io_arguments(node)
                pin = args[0]
                if not (isinstance(pin, ast.Constant) and isinstance(pin.value, str)
                        and pin.value.strip() and len(pin.value) <= 80):
                    raise ExpressionError("read/write/emit names must be literal nonempty strings (up to 80 characters)")
                if name in ("read", "write"):
                    (inputs if name == "read" else outputs).setdefault(pin.value, None)
        if isinstance(node, ast.FunctionDef):
            args = node.args
            if (parents.get(node) is not tree or not node.name.startswith("on_")
                    or not node.name[3:] or len(node.name[3:]) > 80):
                raise ExpressionError("Event handlers must be top-level functions named on_<event>()")
            if (args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg
                    or args.defaults or args.kw_defaults or node.decorator_list or node.returns
                    or getattr(node, "type_params", ())):
                raise ExpressionError("Event handlers take no arguments, decorators or annotations")
            event_name = node.name[3:]
            if event_name in handlers:
                raise ExpressionError(f"Duplicate event handler: {node.name}")
            handlers[event_name] = node
        if isinstance(node, ast.Return):
            parent = parents.get(node)
            while parent is not None and not isinstance(parent, ast.FunctionDef):
                parent = parents.get(parent)
            if parent is None:
                raise ExpressionError("return requires an event handler")
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.For)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(not isinstance(target, ast.Name) for target in targets):
                raise ExpressionError("Assign to a simple variable name")
        if isinstance(node, ast.Dict) and any(key is None for key in node.keys):
            raise ExpressionError("Expanded dictionaries are not supported")
        if isinstance(node, (ast.Break, ast.Continue)):
            parent = parents.get(node)
            while parent is not None and not isinstance(parent, (ast.For, ast.While)):
                parent = parents.get(parent)
            if parent is None:
                raise ExpressionError("break/continue requires a loop")
    # ast.walk is breadth-first; keep pin order in source order instead.
    ordered_names = sorted((n for n in nodes if isinstance(n, ast.Name)),
                           key=lambda n: (n.lineno, n.col_offset))
    calls = sorted((n for n in nodes if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id in ("read", "write", "emit")), key=lambda n: (n.lineno, n.col_offset))
    if formula:
        inputs = dict.fromkeys(n.id for n in ordered_names if n.id in inputs)
    else:
        inputs = dict.fromkeys(_io_arguments(n)[0].value for n in calls if n.func.id == "read")
        outputs = dict.fromkeys(_io_arguments(n)[0].value for n in calls if n.func.id == "write")
    event_outputs = tuple(dict.fromkeys(_io_arguments(n)[0].value for n in calls if n.func.id == "emit"))
    ordered_handlers = sorted(handlers.items(), key=lambda item: item[1].lineno)
    return Program(tree, tuple(inputs), tuple(outputs), tuple(name for name, _ in ordered_handlers),
                   event_outputs, tuple(handler for _, handler in ordered_handlers))


class _LoopControl(Exception):
    def __init__(self, is_break: bool) -> None:
        self.is_break = is_break


class _ReturnControl(Exception):
    """Return from an event handler without escaping the interpreter."""


class Interpreter:
    """One invocation, with fresh locals, staged outputs and bounded work."""

    def __init__(self, variables: dict[str, Any], read: Callable[[str], Any] | None = None) -> None:
        self.remaining = 20_000
        self.deadline = time.monotonic() + 0.05
        self.line = 1
        self.variables = variables
        self.read = read
        self.outputs: dict[str, Any] = {}
        self.events: list[str] = []

    def _step(self) -> None:
        self.remaining -= 1
        if self.remaining < 0 or time.monotonic() > self.deadline:
            raise ExpressionError("Execution limit exceeded (20,000 steps / 50 ms)")

    def value(self, value: Any, depth: int = 0) -> Any:
        """Copy incoming data so scripts cannot mutate upstream engine values."""
        self._step()
        if depth > 32:
            raise ExpressionError("Value nesting limit exceeded")
        kind = type(value)
        if kind is int and value.bit_length() > MAX_INTEGER_BITS:
            raise ExpressionError("Integer size limit exceeded")
        if kind in (str, list, tuple, dict, range) and len(value) > MAX_ITEMS:
            raise ExpressionError(f"Value exceeds {MAX_ITEMS} items/characters")
        if kind in (int, float, bool, str, type(None)):
            return value
        if kind is range:
            return [self.value(item, depth + 1) for item in value]
        if kind in (tuple, list):
            return kind(self.value(item, depth + 1) for item in value)
        if kind is dict:
            return {self.value(k, depth + 1): self.value(v, depth + 1) for k, v in value.items()}
        raise ExpressionError(f"Unsupported value type: {kind.__name__}")

    def binary(self, op: ast.operator, left: Any, right: Any) -> Any:
        if isinstance(op, ast.Pow):
            if type(left) not in (int, float, bool) or type(right) not in (int, float, bool):
                raise ExpressionError("Power requires numbers")
            if abs(right) > 1024 or (type(left) is int and left.bit_length() * max(right, 0) > MAX_INTEGER_BITS):
                raise ExpressionError("Power exceeds numeric limits")
        if isinstance(op, ast.Mult):
            for sequence, count in ((left, right), (right, left)):
                if type(sequence) in (str, list, tuple) and type(count) is int:
                    if len(sequence) * max(count, 0) > MAX_ITEMS:
                        raise ExpressionError("Repeated value is too large")
        if isinstance(op, ast.Mod) and (type(left) not in (int, float, bool)
                                        or type(right) not in (int, float, bool)):
            raise ExpressionError("Modulo requires numbers")
        return self.value(_BINARY[type(op)](left, right))

    def expression(self, node: ast.AST) -> Any:
        self._step()
        self.line = getattr(node, "lineno", self.line)
        if isinstance(node, ast.Constant):
            return self.value(node.value)
        if isinstance(node, ast.Name):
            if node.id in self.variables:
                return self.value(self.variables[node.id])
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise ExpressionError(f"Unknown variable: {node.id}")
        if isinstance(node, ast.Attribute):
            if node.attr in CONSTANTS:
                return CONSTANTS[node.attr]
            raise ExpressionError("Math functions must be called")
        if isinstance(node, ast.BinOp):
            return self.binary(node.op, self.expression(node.left), self.expression(node.right))
        if isinstance(node, ast.UnaryOp):
            value = self.expression(node.operand)
            return self.value({ast.UAdd: operator.pos, ast.USub: operator.neg,
                               ast.Not: operator.not_}[type(node.op)](value))
        if isinstance(node, ast.BoolOp):
            for item in node.values:
                result = self.expression(item)
                if (isinstance(node.op, ast.And) and not result) or (isinstance(node.op, ast.Or) and result):
                    break
            return result
        if isinstance(node, ast.Compare):
            left = self.expression(node.left)
            for op, item in zip(node.ops, node.comparators):
                right = self.expression(item)
                if not _COMPARE[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return self.expression(node.body if self.expression(node.test) else node.orelse)
        if isinstance(node, (ast.List, ast.Tuple)):
            return self.value([self.expression(item) for item in node.elts] if isinstance(node, ast.List)
                              else tuple(self.expression(item) for item in node.elts))
        if isinstance(node, ast.Dict):
            return self.value({self.expression(k): self.expression(v) for k, v in zip(node.keys, node.values)})
        if isinstance(node, ast.Slice):
            return slice(*(self.expression(item) if item else None
                           for item in (node.lower, node.upper, node.step)))
        if isinstance(node, ast.Subscript):
            return self.value(self.expression(node.value)[self.expression(node.slice)])
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if name in ("read", "write", "emit"):
                args = [self.expression(arg) for arg in _io_arguments(node)]
                if name == "read":
                    return self.value(self.read(args[0]))
                if name == "emit":
                    if len(self.events) >= MAX_ITEMS:
                        raise ExpressionError("Event emission limit exceeded")
                    self.events.append(args[0])
                    return None
                self.outputs[args[0]] = self.value(args[1])
                return None
            args = [self.expression(arg) for arg in node.args]
            kwargs = {keyword.arg: self.expression(keyword.value) for keyword in node.keywords}
            if name == "pow":
                if kwargs or len(args) != 2:
                    raise ExpressionError("pow expects two positional arguments")
                return self.binary(ast.Pow(), *args)
            if name == "range":
                return self.value(range(*args, **kwargs))
            return self.value(FUNCTIONS[name](*args, **kwargs))
        raise ExpressionError(f"Unsupported expression: {type(node).__name__}")

    def statements(self, body: list[ast.stmt]) -> None:
        for node in body:
            self._step()
            self.line = node.lineno
            if isinstance(node, ast.Assign):
                value = self.expression(node.value)
                for target in node.targets:
                    self.variables[target.id] = value
            elif isinstance(node, ast.AugAssign):
                self.variables[node.target.id] = self.binary(node.op, self.expression(node.target),
                                                            self.expression(node.value))
            elif isinstance(node, ast.Expr):
                self.expression(node.value)
            elif isinstance(node, ast.If):
                self.statements(node.body if self.expression(node.test) else node.orelse)
            elif isinstance(node, (ast.For, ast.While)):
                iterator = iter(self.expression(node.iter)) if isinstance(node, ast.For) else None
                while True:
                    self._step()
                    if iterator is not None:
                        try:
                            self.variables[node.target.id] = next(iterator)
                        except StopIteration:
                            self.statements(node.orelse)
                            break
                    elif not self.expression(node.test):
                        self.statements(node.orelse)
                        break
                    try:
                        self.statements(node.body)
                    except _LoopControl as control:
                        if control.is_break:
                            break
            elif isinstance(node, (ast.Break, ast.Continue)):
                raise _LoopControl(isinstance(node, ast.Break))
            elif isinstance(node, ast.Return):
                if node.value is not None:
                    self.expression(node.value)
                raise _ReturnControl()
            elif isinstance(node, (ast.FunctionDef, ast.Pass)):
                continue  # handlers run only when their event input receives a TICK

    def run(self, program: Program, event: str | None = None) -> Any:
        try:
            if isinstance(program.tree, ast.Expression):
                return self.expression(program.tree.body)
            if event is None:
                self.statements(program.tree.body)
            else:
                handler = next((handler for handler in program.handlers if handler.name == f"on_{event}"), None)
                if handler is None:
                    raise ExpressionError(f"Unknown event: {event}")
                try:
                    self.statements(handler.body)
                except _ReturnControl:
                    pass
            return self.outputs
        except Exception as exc:
            raise ExpressionError(f"Line {self.line}: {type(exc).__name__}: {exc}") from exc
