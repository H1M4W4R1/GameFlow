"""
GameFlow — entry point.

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
import os
import sys
import ctypes
from pathlib import Path

from bleak.backends.winrt.util import allow_sta
allow_sta()

os.environ.setdefault("QT_FFMPEG_DEBUG", "0")

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent
APP_ICON_PATH = PROJECT_ROOT / "assets" / "icons" / "app.svg"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.localization import load_language, load_language_pref
load_language(load_language_pref())

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QFont, QIcon

from core.device_registry import DeviceRegistry
from core.graph_runtime   import GraphRuntime
from ui.debug_console     import configure_file_logging
from ui.main_window       import MainWindow

log = logging.getLogger(__name__)


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SensoryFlow.GameFlow")


def setup_logging() -> None:
    log_path = configure_file_logging()
    logging.basicConfig(
        level  = logging.DEBUG,
        format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers = [
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )


def main() -> None:
    setup_logging()
    log = logging.getLogger("main")

    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("GameFlow")
    app.setApplicationVersion("1.0.0")
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    # ── Bootstrap ──────────────────────────────────────────────────────────────
    registry = DeviceRegistry()
    runtime  = GraphRuntime()

    # Auto-discover devices and nodes
    devices_path = PROJECT_ROOT / "devices"
    nodes_path   = PROJECT_ROOT / "nodes"
    plugins_path = PROJECT_ROOT / "plugins"

    # Seed nodes so they're always available
    _seed_nodes(registry)

    # Discover third-party / user additions
    try:
        registry.discover(devices_path, nodes_path, plugins_path)
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


def _seed_nodes(registry: DeviceRegistry) -> None:
    """
    Walk /nodes/, /devices/, and /plugins/ and register all concrete NodeBase
    and DeviceBase subclasses.
    """
    from core.node_base   import NodeBase
    from core.device_base import DeviceBase
    from core.device_registry import _import_module_from_file, _iter_module_files, _module_name_for_file

    def _walk_and_register(root: Path, base: type, store: dict) -> int:
        if not root.exists():
            return 0
        parent = str(root.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        count = 0
        for file_path in _iter_module_files(root):
            module_name = _module_name_for_file(root, file_path)
            try:
                mod = _import_module_from_file(module_name, file_path)
            except Exception as exc:
                log.warning("Skipping %s: %s", module_name, exc)
                continue
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                # Unwrap lists of classes (e.g. ALL_NODE_CLASSES from factory modules)
                candidates = obj if isinstance(obj, list) else [obj]
                for candidate in candidates:
                    if (
                        isinstance(candidate, type)
                        and issubclass(candidate, base)
                        and candidate is not base
                        and not getattr(candidate, "__abstractmethods__", None)
                        and not candidate.__name__.startswith("_")
                    ):
                        key = f"{candidate.__module__}.{candidate.__name__}"
                        if key not in store:
                            store[key] = candidate
                            count += 1
        return count

    n = _walk_and_register(PROJECT_ROOT / "nodes",   NodeBase,   registry._node_classes)
    log.info("Seeded %d node(s) from /nodes/", n)

    # Device classes live under /devices/
    d = _walk_and_register(PROJECT_ROOT / "devices", DeviceBase, registry._device_classes)
    log.info("Seeded %d device class(es) from /devices/", d)

    # Device-specific nodes (DeviceNodeBase subclasses) also live under /devices/
    dn = _walk_and_register(PROJECT_ROOT / "devices", NodeBase, registry._node_classes)
    log.info("Seeded %d device node(s) from /devices/", dn)

    # Plugins can contain devices, nodes, or both at any folder depth.
    pd = _walk_and_register(PROJECT_ROOT / "plugins", DeviceBase, registry._device_classes)
    log.info("Seeded %d plugin device class(es) from /plugins/", pd)

    pn = _walk_and_register(PROJECT_ROOT / "plugins", NodeBase, registry._node_classes)
    log.info("Seeded %d plugin node(s) from /plugins/", pn)


if __name__ == "__main__":
    main()
