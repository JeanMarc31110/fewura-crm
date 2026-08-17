from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path


GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
PROFILE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
SEND_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))


def _legacy_root() -> Path:
    return _local_appdata() / "FÉWURA – Agent commercial"


def _token_candidates() -> list[Path]:
    return [
        Path(os.environ["GMAIL_TOKEN_FILE"]) if os.environ.get("GMAIL_TOKEN_FILE") else Path(),
        _legacy_root() / "data" / "gmail-token.json",
        _local_appdata() / "FEWURA" / "CRM" / "gmail-token.json",
    ]


def _env_file_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def _legacy_env() -> dict[str, str]:
    return _env_file_values(_legacy_root() / ".env")


def _tokens() -> tuple[dict, Path | None]:
    for path in _token_candidates():
        if not str(path) or not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("refresh_token"):
            return data, path
    return {}, None


def _config() -> dict[str, str | Path | None]:
    legacy = _legacy_env()
    tokens, token_path = _tokens()
    return {
        "account": (os.environ.get("GMAIL_ACCOUNT") or legacy.get("GMAIL_ACCOUNT") or "softwareinnovatech@gmail.com").strip(),
        "client_id": (os.environ.get("GMAIL_CLIENT_ID") or legacy.get("GMAIL_CLIENT_ID") or "").strip(),
        "client_secret": (os.environ.get("GMAIL_CLIENT_SECRET") or legacy.get("GMAIL_CLIENT_SECRET") or "").strip(),
        "refresh_token": (os.environ.get("GMAIL_REFRESH_TOKEN") or tokens.get("refresh_token") or "").strip(),
        "token_path": token_path,
    }


def status() -> dict:
    config = _config()
    return {
        "configured": bool(config["client_id"] and config["client_secret"] and config["refresh_token"]),
        "account": config["account"],
        "source": "ancien agent FÉWURA" if config["token_path"] and _legacy_root() in Path(config["token_path"]).parents else "configuration locale",
        "token_file_found": bool(config["token_path"]),
        "client_id_found": bool(config["client_id"]),
        "client_secret_found": bool(config["client_secret"]),
        "refresh_token_found": bool(config["refresh_token"]),
    }


def _request(url: str, data: dict | None = None, headers: dict[str, str] | None = None) -> dict:
    encoded = None if data is None else urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Gmail OAuth HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gmail OAuth réseau indisponible: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("Réponse Gmail OAuth invalide") from exc


def _access_token() -> str:
    config = _config()
    if not status()["configured"]:
        raise RuntimeError("Gmail OAuth non configuré : jeton ou identifiants OAuth manquants")
    response = _request(TOKEN_ENDPOINT, {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "refresh_token": config["refresh_token"],
        "grant_type": "refresh_token",
    })
    token = str(response.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Gmail OAuth n'a pas fourni de jeton d'accès")
    return token


def test_connection() -> dict:
    token = _access_token()
    request = urllib.request.Request(PROFILE_ENDPOINT, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Connexion Gmail HTTP {exc.code}: {detail}") from exc
    email = str(data.get("emailAddress") or "").strip()
    return {"ok": True, "account": email or _config()["account"], "messages_total": data.get("messagesTotal", 0)}


def _raw_message(to: str, subject: str, body: str, from_email: str, from_name: str = "FEWURA CRM", html: str = "") -> str:
    message = EmailMessage()
    message["From"] = formataddr((from_name, from_email))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


def send_email(to: str, subject: str, body: str, from_email: str, from_name: str = "FEWURA CRM", html: str = "") -> dict:
    token = _access_token()
    payload = json.dumps({"raw": _raw_message(to, subject, body, from_email, from_name, html)}).encode("utf-8")
    request = urllib.request.Request(
        SEND_ENDPOINT,
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Envoi Gmail HTTP {exc.code}: {detail}") from exc
    return {"ok": True, "id": data.get("id", "")}

