"""Render the existing SVG logo into a multi-resolution Windows ICO file."""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


def generate_icon(source: Path, destination: Path) -> None:
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG icon: {source}")

    sizes = (16, 24, 32, 48, 64, 128, 256)
    images: list[bytes] = []
    for size in sizes:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            renderer.render(painter)
        finally:
            painter.end()

        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError(f"Could not encode the {size}px icon")
        images.append(bytes(data))
        buffer.close()

    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(header) + 16 * len(sizes)
    entries: list[bytes] = []
    for size, image in zip(sizes, images):
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256,
                                   0, 0, 1, 32, len(image), offset))
        offset += len(image)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(header + b"".join(entries) + b"".join(images))
    print(f"Generated Windows icon: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    generate_icon(args.source, args.destination)
