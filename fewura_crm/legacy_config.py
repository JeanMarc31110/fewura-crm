from __future__ import annotations

import os
from pathlib import Path

from .db import connect, init_db, one

SMTP_ENV_MAP = {
    "SMTP_HOST": "smtp_host",
    "SMTP_PORT": "smtp_port",
    "SMTP_USERNAME": "smtp_username",
    "SMTP_PASSWORD": "smtp_password",
    "SMTP_FROM": "smtp_from_email",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            values[key] = value
    except OSError:
        return {}
    return values


def _legacy_env_candidates() -> list[Path]:
    candidates: list[Path] = []
    local = os.getenv("LOCALAPPDATA", "").strip()
    if local:
        root = Path(local)
        # FEWURA PROSPECT chargeait prioritairement ce fichier.
        candidates.append(root / "FEWURA" / "PROSPECT" / ".env")
        candidates.append(root / "Programs" / "FEWURA" / "PROSPECT" / ".env")
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.getenv(var, "").strip()
        if value:
            candidates.append(Path(value) / "FEWURA" / "PROSPECT" / ".env")
    # Permet aussi une migration depuis un ancien dossier lancé directement.
    candidates.append(Path.cwd() / ".env")
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _crm_has_smtp() -> bool:
    init_db()
    row = one("SELECT value FROM settings WHERE key='smtp_host'")
    return bool(row and (row.get("value") or "").strip())


def migrate_legacy_smtp_settings() -> dict:
    """Importe une seule fois la configuration SMTP de l'ancien FEWURA.

    Les secrets restent uniquement dans la base locale FEWURA CRM et ne sont
    jamais copiés dans GitHub ni écrits dans les logs.
    """
    if _crm_has_smtp():
        return {"migrated": False, "reason": "already_configured"}

    legacy: dict[str, str] = {}
    source = ""

    # Les variables d'environnement ont priorité, comme dans l'ancien FEWURA.
    for key in SMTP_ENV_MAP:
        value = os.getenv(key, "").strip()
        if value:
            legacy[key] = value
    if legacy.get("SMTP_HOST"):
        source = "environment"
    else:
        for candidate in _legacy_env_candidates():
            parsed = _parse_env_file(candidate)
            if parsed.get("SMTP_HOST"):
                legacy = parsed
                source = str(candidate)
                break

    host = legacy.get("SMTP_HOST", "").strip()
    username = legacy.get("SMTP_USERNAME", "").strip()
    password = legacy.get("SMTP_PASSWORD", "")
    from_email = legacy.get("SMTP_FROM", "").strip() or username
    if not host or not from_email:
        return {"migrated": False, "reason": "legacy_not_found"}

    port = legacy.get("SMTP_PORT", "587").strip() or "587"
    use_tls = legacy.get("SMTP_USE_TLS", "true").strip().lower() == "true"
    security = "starttls" if use_tls else "none"
    values = {
        "smtp_host": host,
        "smtp_port": port,
        "smtp_username": username,
        "smtp_from_email": from_email,
        "smtp_from_name": legacy.get("SENDER_COMPANY", "FEWURA").strip() or "FEWURA",
        "smtp_security": security,
    }
    if password:
        values["smtp_password"] = password

    init_db()
    con = connect()
    try:
        for key, value in values.items():
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
        con.execute(
            "INSERT INTO settings(key,value) VALUES('smtp_migrated_from_legacy','1') "
            "ON CONFLICT(key) DO UPDATE SET value='1'"
        )
        con.commit()
    finally:
        con.close()

    return {"migrated": True, "source": source, "has_password": bool(password)}
