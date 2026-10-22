"""Shared styling for prominent values in node previews."""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter


VALUE_FONT_SIZE = 22
VALUE_HEIGHT = 36.0


def paint_value(
    painter: QPainter,
    rect: QRectF,
    text: str,
    color: str = "#f95979",
) -> None:
    """Use Counter-sized values, reducing only text that would overflow."""
    font = QFont("Courier New", VALUE_FONT_SIZE, QFont.Weight.Bold)
    width = QFontMetricsF(font).horizontalAdvance(text)
    available = max(1.0, rect.width() - 8.0)
    if width > available:
        font.setPointSizeF(VALUE_FONT_SIZE * available / width)
    painter.setPen(QColor(color))
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
