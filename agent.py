from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from fewura_crm.db import init_db
from fewura_crm.legacy_config import migrate_legacy_smtp_settings
from fewura_crm.paths import data_dir
from fewura_crm.web import app, shutdown_requested, VERSION

HOST = os.environ.get("FEWURA_CRM_HOST", "127.0.0.1")
BASE_PORT = int(os.environ.get("FEWURA_CRM_PORT", "8020"))
NO_BROWSER = os.environ.get("FEWURA_CRM_NO_BROWSER", "0") == "1"


def _log(message: str) -> None:
    try:
        path = data_dir() / "startup.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n")
    except Exception:
        pass


def _message(title: str, text: str) -> None:
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}: {text}")


def _health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/health", timeout=1.2) as r:
            import json
            data = json.loads(r.read().decode("utf-8"))
            if data.get("ok") and data.get("app") == "FEWURA CRM":
                return data
    except Exception:
        return None
    return None


def _port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, port))
        return True
    except OSError:
        return False


def _choose_port() -> tuple[int, bool]:
    existing = _health(BASE_PORT)
    if existing:
        return BASE_PORT, True
    if _port_free(BASE_PORT):
        return BASE_PORT, False
    for port in range(BASE_PORT + 1, BASE_PORT + 21):
        existing = _health(port)
        if existing:
            return port, True
        if _port_free(port):
            return port, False
    raise RuntimeError("Aucun port local disponible entre 8020 et 8040")


def _open_browser(url: str) -> bool:
    if NO_BROWSER:
        return True
    try:
        if os.name == "nt":
            os.startfile(url)  # type: ignore[attr-defined]
            return True
    except Exception as exc:
        _log(f"os.startfile navigateur: {exc}")
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception as exc:
        _log(f"webbrowser.open: {exc}")
        return False


def _wait_and_open(port: int) -> None:
    url = f"http://{HOST}:{port}/"
    for _ in range(160):
        if _health(port):
            _log(f"Interface prête: {url}")
            if not _open_browser(url):
                _message("FEWURA CRM", f"FEWURA CRM est lancé. Ouvrez cette adresse dans votre navigateur :\n\n{url}")
            return
        time.sleep(0.25)
    _message("FEWURA CRM - erreur", f"Le serveur a démarré mais l'interface ne répond pas.\nConsultez : {data_dir() / 'startup.log'}")


def self_test() -> int:
    init_db()
    checks = {
        "database": data_dir().exists(),
        "web_interface": app is not None,
        "local_only": HOST == "127.0.0.1",
        "version": VERSION == "1.3.1",
    }
    print({"ok": all(checks.values()), "checks": checks, "version": VERSION})
    return 0 if all(checks.values()) else 2


def main() -> int:
    try:
        init_db()
        migration = migrate_legacy_smtp_settings()
        if migration.get("migrated"):
            _log("Configuration SMTP de l'ancien FEWURA migrée automatiquement")
        port, existing = _choose_port()
        url = f"http://{HOST}:{port}/"
        if existing:
            _log(f"Instance FEWURA CRM déjà active: {url}")
            if not _open_browser(url):
                _message("FEWURA CRM", f"FEWURA CRM est déjà lancé. Ouvrez :\n\n{url}")
            return 0

        _log(f"Démarrage FEWURA CRM {VERSION} sur {HOST}:{port}")
        threading.Thread(target=_wait_and_open, args=(port,), daemon=True).start()
        config = uvicorn.Config(
            app=app,
            host=HOST,
            port=port,
            log_level="warning",
            access_log=False,
            log_config=None,
            ws="none",
        )
        server = uvicorn.Server(config)

        def watch_shutdown() -> None:
            while not server.should_exit:
                if shutdown_requested():
                    server.should_exit = True
                    return
                time.sleep(0.2)

        threading.Thread(target=watch_shutdown, daemon=True).start()
        server.run()
        _log("Arrêt normal")
        return 0
    except Exception as exc:
        _log(f"ERREUR DEMARRAGE: {type(exc).__name__}: {exc}")
        _message("FEWURA CRM - erreur de démarrage", f"Impossible de lancer FEWURA CRM.\n\n{exc}\n\nJournal : {data_dir() / 'startup.log'}")
        return 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main())
