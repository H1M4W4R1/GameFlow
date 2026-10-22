"""Python syntax colours for the node script editor, including partial source."""
from __future__ import annotations

import keyword
import re

from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from core.expression_engine import CONSTANTS, FUNCTIONS


_TOKENS = re.compile(
    r"(?P<comment>\#.*)"
    r"|(?P<triple>(?i:[rubf]{0,2})(?:'{3}|\"{3}))"
    r"|(?P<string>(?i:[rubf]{0,2})(?:'(?:\\.|[^'\\])*'?|\"(?:\\.|[^\"\\])*\"?))"
    r"|(?P<number>(?<!\w)(?:0[xX][\da-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|"
    r"(?:\d[\d_]*(?:\.[\d_]*)?|\.[\d_]+)(?:[eE][+-]?[\d_]+)?))"
    r"|(?P<name>\b[^\W\d]\w*\b)"
    r"|(?P<operator>\*\*|//|==|!=|<=|>=|[-+*/%=<>:(),\[\]{}])"
)


class PythonHighlighter(QSyntaxHighlighter):
    """Highlight keywords, helpers, handlers, numbers, comments and strings."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._formats: dict[str, QTextCharFormat] = {}
        for name, color in {
            "keyword": "#c792ea", "helper": "#82aaff", "handler": "#ffcb6b",
            "number": "#f78c6c", "string": "#c3e88d", "comment": "#8292a2",
            "operator": "#89ddff",
        }.items():
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            if name in ("keyword", "helper", "handler"):
                style.setFontWeight(QFont.Weight.DemiBold)
            if name == "comment":
                style.setFontItalic(True)
            self._formats[name] = style
        self._helpers = {*FUNCTIONS, *CONSTANTS, "read", "write", "emit", "range", "pow", "math"}

    @staticmethod
    def _closing_quote(text: str, delimiter: str, start: int) -> int:
        while True:
            position = text.find(delimiter, start)
            if position < 0:
                return -1
            previous = position - 1
            while previous >= 0 and text[previous] == "\\":
                previous -= 1
            if (position - previous - 1) % 2 == 0:
                return position
            start = position + 1

    def _format(self, text: str, start: int, end: int, kind: str) -> None:
        # QTextDocument uses UTF-16 positions; Python indices count code points.
        qt_start = len(text[:start].encode("utf-16-le")) // 2
        qt_length = len(text[start:end].encode("utf-16-le")) // 2
        self.setFormat(qt_start, qt_length, self._formats[kind])

    def highlightBlock(self, text: str) -> None:
        self.setCurrentBlockState(0)
        offset = 0
        previous_state = self.previousBlockState()
        if previous_state in (1, 2):
            delimiter = "'''" if previous_state == 1 else '"""'
            end = self._closing_quote(text, delimiter, 0)
            if end < 0:
                self._format(text, 0, len(text), "string")
                self.setCurrentBlockState(previous_state)
                return
            offset = end + 3
            self._format(text, 0, offset, "string")
        while match := _TOKENS.search(text, offset):
            kind = match.lastgroup
            start, end = match.span()
            token = match.group()
            if kind == "triple":
                delimiter = token[-3:]
                closing = self._closing_quote(text, delimiter, end)
                if closing < 0:
                    self._format(text, start, len(text), "string")
                    self.setCurrentBlockState(1 if delimiter == "'''" else 2)
                    return
                end = closing + 3
                kind = "string"
            elif kind == "name":
                if keyword.iskeyword(token):
                    kind = "keyword"
                elif token in self._helpers:
                    kind = "helper"
                elif token.startswith("on_"):
                    kind = "handler"
                else:
                    kind = None
            if kind is not None:
                self._format(text, start, end, kind)
            offset = end
