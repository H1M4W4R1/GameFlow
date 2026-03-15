"""
SensoryFlow — entry point.

Run:
    python main.py

Requirements (pip install):
    PyQt6
    pyserial          (Serial devices)
    bleak             (BLE devices)
    websockets        (WebSocket devices)
    requests          (REST devices)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QFont

from core.device_registry import DeviceRegistry
from core.graph_runtime   import GraphRuntime
from ui.main_window       import MainWindow

log = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level  = logging.DEBUG,
        format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers = [logging.StreamHandler(sys.stdout)],
    )


def main() -> None:
    setup_logging()
    log = logging.getLogger("main")

    app = QApplication(sys.argv)
    app.setApplicationName("SensoryFlow")
    app.setApplicationVersion("1.0.0")

    # ── Bootstrap ──────────────────────────────────────────────────────────────
    registry = DeviceRegistry()
    runtime  = GraphRuntime()

    # Auto-discover devices and nodes
    devices_path = PROJECT_ROOT / "devices"
    nodes_path   = PROJECT_ROOT / "nodes"

    # Seed builtin nodes so they're always available
    _seed_builtin_nodes(registry)

    # Discover third-party / user additions
    try:
        registry.discover(devices_path, nodes_path)
    except Exception as exc:
        log.warning("Discovery error (non-fatal): %s", exc)

    log.info(
        "Discovered %d device type(s), %d node type(s)",
        len(registry.device_classes),
        len(registry.node_classes),
    )

    # ── Launch UI ──────────────────────────────────────────────────────────────
    window = MainWindow(registry, runtime)
    window.show()

    sys.exit(app.exec())


def _seed_builtin_nodes(registry: DeviceRegistry) -> None:
    """Register all built-in node classes from their respective modules."""
    from nodes.flow_nodes import (
        TickNode, ConfigurableTickNode, StartNode, ConditionNode,
    )
    from nodes.utility_nodes import (
        CounterNode, TimerNode, RandomNode, LogNode, LoopNode,
    )
    from nodes.math_nodes import (
        AddNode, SubtractNode, MultiplyNode, DivideNode, ModuloNode,
        PowerNode, MinNode, MaxNode,
        AbsNode, NegateNode, SinNode, CosNode, TanNode,
        SqrtNode, FloorNode, CeilNode, RoundNode,
        ClampNode, LerpNode, MapRangeNode,
        IntToFloatNode, FloatToIntNode, BoolToFloatNode,
        AnyToStringNode, StringToFloatNode,
    )
    from nodes.constant_nodes import (
        FloatConstantNode, IntConstantNode, StringConstantNode, BoolConstantNode,
    )
    all_classes = [
        # Flow
        TickNode, ConfigurableTickNode, StartNode, ConditionNode,
        # Utility
        CounterNode, TimerNode, RandomNode, LogNode, LoopNode,
        # Math
        AddNode, SubtractNode, MultiplyNode, DivideNode, ModuloNode,
        PowerNode, MinNode, MaxNode,
        AbsNode, NegateNode, SinNode, CosNode, TanNode,
        SqrtNode, FloorNode, CeilNode, RoundNode,
        ClampNode, LerpNode, MapRangeNode,
        # Conversion
        IntToFloatNode, FloatToIntNode, BoolToFloatNode,
        AnyToStringNode, StringToFloatNode,
        # Constants
        FloatConstantNode, IntConstantNode, StringConstantNode, BoolConstantNode,
    ]
    for cls in all_classes:
        key = f"{cls.__module__}.{cls.__name__}"
        registry._node_classes[key] = cls

    # ── Lovense devices + nodes ───────────────────────────────────────────────
    try:
        from devices.lovense import ALL_DEVICE_CLASSES as _lov_dev, ALL_NODE_CLASSES as _lov_nod
        for cls in _lov_dev:
            key = f"{cls.__module__}.{cls.__name__}"
            registry._device_classes[key] = cls
        for cls in _lov_nod:
            key = f"{cls.__module__}.{cls.__name__}"
            registry._node_classes[key] = cls
        log.info("Registered %d Lovense device(s), %d node(s)",
                 len(_lov_dev), len(_lov_nod))
    except ImportError as e:
        log.warning("Lovense devices unavailable (bleak not installed?): %s", e)

    # ── H1M4W4R1 pump device + nodes ───────────────────────────────────────────
    try:
        from devices.h1m4w4r1 import ALL_DEVICE_CLASSES as _pump_dev, ALL_NODE_CLASSES as _pump_nod
        for cls in _pump_dev:
            key = f"{cls.__module__}.{cls.__name__}"
            registry._device_classes[key] = cls
        for cls in _pump_nod:
            key = f"{cls.__module__}.{cls.__name__}"
            registry._node_classes[key] = cls
        log.info("Registered %d H1M4W4R1 pump device(s), %d node(s)",
                 len(_pump_dev), len(_pump_nod))
    except ImportError as e:
        log.warning("H1M4W4R1 pump unavailable: %s", e)


if __name__ == "__main__":
    main()
