from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

RELEASES_URL = "https://api.github.com/repos/JeanMarc31110/fewura-crm/releases/latest"
_TIMEOUT = 4


def _version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", str(value))
    return tuple(int(x) for x in numbers[:4]) or (0,)


def _get_latest() -> dict | None:
    request = urllib.request.Request(
        RELEASES_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "FEWURA-CRM-updater"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _confirm(version: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        result = ctypes.windll.user32.MessageBoxW(
            0,
            f"Une nouvelle version FEWURA CRM ({version}) est disponible.\n\n"
            "Télécharger et installer maintenant ?",
            "Mise à jour FEWURA CRM",
            0x24,
        )
        return result == 6
    except Exception:
        return False


def _download(asset: dict) -> Path:
    target = Path(tempfile.gettempdir()) / "FEWURA_CRM_update.exe"
    request = urllib.request.Request(
        asset["browser_download_url"],
        headers={"Accept": "application/octet-stream", "User-Agent": "FEWURA-CRM-updater"},
    )
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
    expected = str(asset.get("digest") or "")
    if expected.startswith("sha256:") and digest.hexdigest().lower() != expected[7:].lower():
        target.unlink(missing_ok=True)
        raise RuntimeError("La vérification de l’installeur a échoué.")
    if target.stat().st_size < 1_000_000:
        target.unlink(missing_ok=True)
        raise RuntimeError("L’installeur téléchargé est incomplet.")
    return target


def maybe_update(current_version: str) -> bool:
    """Return True when an installer was launched and the current process must exit."""
    if os.getenv("FEWURA_DISABLE_UPDATE") == "1":
        return False
    try:
        release = _get_latest()
        latest = str(release.get("tag_name") or release.get("name") or "")
        if _version(latest) <= _version(current_version):
            return False
        assets = [
            asset for asset in release.get("assets", [])
            if str(asset.get("name", "")).lower().endswith(".exe")
            and "setup" in str(asset.get("name", "")).lower()
        ]
        if not assets or not _confirm(latest):
            return False
        installer = _download(assets[0])
        if os.name == "nt":
            subprocess.Popen(
                [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
                close_fds=True,
            )
            return True
    except Exception:
        # An unavailable update server must never prevent FEWURA from starting.
        return False
    return False
