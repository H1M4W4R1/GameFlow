"""Simple CSV-based localization. Load once at startup via load_language()."""
import csv
import json
import os
from pathlib import Path

_strings: dict[str, str] = {}
_current_lang: str = "EN"

_SETTINGS_PATH = Path.home() / ".sensoryflow" / "settings.json"


def load_language(lang_code: str = "EN") -> None:
    """Load strings from locales/{lang_code}.csv."""
    global _strings, _current_lang
    path = os.path.join(os.path.dirname(__file__), "..", "locales", f"{lang_code}.csv")
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return
    with open(path, newline="", encoding="utf-8") as f:
        _strings = {row[0]: row[1] for row in csv.reader(f) if len(row) >= 2}
    _current_lang = lang_code


def get_current_language() -> str:
    """Return the currently loaded language code."""
    return _current_lang


def save_language_pref(lang_code: str) -> None:
    """Persist the selected language to ~/.sensoryflow/settings.json."""
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if _SETTINGS_PATH.exists():
            try:
                data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        data["language"] = lang_code
        _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_language_pref() -> str:
    """Return the saved language code, defaulting to 'EN'."""
    try:
        if _SETTINGS_PATH.exists():
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            return data.get("language", "EN")
    except Exception:
        pass
    return "EN"


def tr(key: str, default: str | None = None) -> str:
    """Return the localized string for key, or default/key if not found."""
    return _strings.get(key, default if default is not None else key)
