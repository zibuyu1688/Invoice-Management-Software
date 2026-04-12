from pathlib import Path
import os
import json


BOOTSTRAP_CONFIG_PATH = Path.home() / ".invoice_manager_bootstrap.json"


def _read_bootstrap_payload() -> dict:
    if not BOOTSTRAP_CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(BOOTSTRAP_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _write_bootstrap_payload(payload: dict) -> None:
    BOOTSTRAP_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_bootstrap_home() -> str | None:
    payload = _read_bootstrap_payload()
    value = payload.get("app_home")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_bootstrap_path(key: str) -> str | None:
    payload = _read_bootstrap_payload()
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def set_custom_app_home(path_value: str) -> Path:
    target = Path(path_value).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    payload = _read_bootstrap_payload()
    payload["app_home"] = str(target)
    _write_bootstrap_payload(payload)
    return target


def set_custom_files_dir(path_value: str) -> Path:
    payload = _read_bootstrap_payload()
    cleaned = path_value.strip()
    if cleaned:
        target = Path(cleaned).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        payload["files_dir"] = str(target)
    else:
        payload.pop("files_dir", None)
        target = get_app_home() / "files"
        target.mkdir(parents=True, exist_ok=True)
    _write_bootstrap_payload(payload)
    return target


def set_custom_exports_dir(path_value: str) -> Path:
    payload = _read_bootstrap_payload()
    cleaned = path_value.strip()
    if cleaned:
        target = Path(cleaned).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        payload["exports_dir"] = str(target)
    else:
        payload.pop("exports_dir", None)
        target = get_app_home() / "exports"
        target.mkdir(parents=True, exist_ok=True)
    _write_bootstrap_payload(payload)
    return target


def get_deepseek_api_key() -> str:
    env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key

    payload = _read_bootstrap_payload()
    key = payload.get("deepseek_api_key", "")
    return key.strip() if isinstance(key, str) else ""


def set_deepseek_api_key(api_key: str) -> None:
    payload = _read_bootstrap_payload()
    payload["deepseek_api_key"] = api_key.strip()
    _write_bootstrap_payload(payload)


def get_app_home() -> Path:
    custom_home = os.getenv("INVOICE_APP_HOME")
    if custom_home:
        home = Path(custom_home).expanduser().resolve()
    else:
        bootstrap_home = _read_bootstrap_home()
        if bootstrap_home:
            home = Path(bootstrap_home).expanduser().resolve()
        else:
            home = (Path.home() / ".invoice_manager").resolve()
    home.mkdir(parents=True, exist_ok=True)
    return home


def get_files_dir(app_home: Path | None = None) -> Path:
    env_value = os.getenv("INVOICE_FILES_DIR", "").strip()
    if env_value:
        target = Path(env_value).expanduser().resolve()
    else:
        bootstrap_value = _read_bootstrap_path("files_dir")
        if bootstrap_value:
            target = Path(bootstrap_value).expanduser().resolve()
        else:
            base_home = app_home or get_app_home()
            target = base_home / "files"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_exports_dir(app_home: Path | None = None) -> Path:
    env_value = os.getenv("INVOICE_EXPORTS_DIR", "").strip()
    if env_value:
        target = Path(env_value).expanduser().resolve()
    else:
        bootstrap_value = _read_bootstrap_path("exports_dir")
        if bootstrap_value:
            target = Path(bootstrap_value).expanduser().resolve()
        else:
            base_home = app_home or get_app_home()
            target = base_home / "exports"
    target.mkdir(parents=True, exist_ok=True)
    return target


APP_HOME = get_app_home()
DATA_DIR = APP_HOME / "data"
FILES_DIR = get_files_dir(APP_HOME)
EXPORTS_DIR = get_exports_dir(APP_HOME)
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
DB_PATH = DATA_DIR / "invoice.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
