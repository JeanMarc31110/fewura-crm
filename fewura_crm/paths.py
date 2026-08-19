from pathlib import Path
import os


def data_dir() -> Path:
    override = os.getenv("FEWURA_CRM_DATA_DIR", "").strip()
    if override:
        root = Path(override).expanduser()
    elif os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home())) / "FEWURA" / "CRM"
    else:
        root = Path.home() / ".local" / "share" / "fewura-crm"
    root.mkdir(parents=True, exist_ok=True)
    return root


def database_path() -> Path:
    return data_dir() / "fewura_crm.db"


def exports_dir() -> Path:
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path

