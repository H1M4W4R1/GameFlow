"""Simple CSV-based localization. Load once at startup via load_language()."""
import csv
import os

_strings: dict[str, str] = {}


def load_language(lang_code: str = "EN") -> None:
    """Load strings from locales/{lang_code}.csv."""
    global _strings
    path = os.path.join(os.path.dirname(__file__), "..", "locales", f"{lang_code}.csv")
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return
    with open(path, newline="", encoding="utf-8") as f:
        _strings = {row[0]: row[1] for row in csv.reader(f) if len(row) >= 2}


def tr(key: str, default: str | None = None) -> str:
    """Return the localized string for key, or default/key if not found."""
    return _strings.get(key, default if default is not None else key)
