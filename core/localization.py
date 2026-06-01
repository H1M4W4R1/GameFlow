"""Simple CSV-based localization. Load once at startup via load_language()."""
import csv
import json
from pathlib import Path

_strings: dict[str, str] = {}
_current_lang: str = "EN"
_language_cache: dict[str, dict[str, str]] = {}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CORE_LOCALES_DIR = _PROJECT_ROOT / "locales"
_PLUGINS_DIR = _PROJECT_ROOT / "plugins"
_SETTINGS_PATH = Path.home() / ".gameflow" / "settings.json"


def load_language(lang_code: str = "EN") -> None:
    """Load core and plugin strings for the selected language."""
    global _strings, _current_lang
    lang_code = lang_code.upper()
    if lang_code in _language_cache:
        _strings = _language_cache[lang_code]
        _current_lang = lang_code
        return

    files = _locale_files_for_language(lang_code)
    if not files:
        return

    merged: dict[str, str] = {}
    for path in files:
        merged.update(_load_locale_file(path))

    _language_cache[lang_code] = merged
    _strings = merged
    _current_lang = lang_code


def get_current_language() -> str:
    """Return the currently loaded language code."""
    return _current_lang


def get_available_languages() -> list[str]:
    """Return language codes found in core or plugin locale folders."""
    codes: set[str] = set()
    for path in _iter_locale_files():
        codes.add(path.stem.upper())
    return sorted(codes)


def save_language_pref(lang_code: str) -> None:
    """Persist the selected language to ~/.gameflow/settings.json."""
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


def _locale_files_for_language(lang_code: str) -> list[Path]:
    filename = f"{lang_code.upper()}.csv"
    files: list[Path] = []
    core_path = _CORE_LOCALES_DIR / filename
    if core_path.exists():
        files.append(core_path)
    files.extend(
        sorted(
            path
            for path in _PLUGINS_DIR.rglob(filename)
            if path.parent.name == "locales"
        )
    )
    return files


def _iter_locale_files() -> list[Path]:
    files = list(_CORE_LOCALES_DIR.glob("*.csv"))
    if _PLUGINS_DIR.exists():
        files.extend(
            path
            for path in _PLUGINS_DIR.rglob("*.csv")
            if path.parent.name == "locales"
        )
    return sorted(files)


def _load_locale_file(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        return {row[0]: row[1] for row in csv.reader(f) if len(row) >= 2}
