from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from fewura_crm.db import init_db
from fewura_crm.paths import data_dir
from fewura_crm.web import app, shutdown_requested

VERSION = "1.2.0"
HOST = os.environ.get("FEWURA_CRM_HOST", "127.0.0.1")
PORT = int(os.environ.get("FEWURA_CRM_PORT", "8020"))
URL = f"http://{HOST}:{PORT}"
NO_BROWSER = os.environ.get("FEWURA_CRM_NO_BROWSER", "0") == "1"


def self_test() -> int:
    init_db()
    checks = {
        "database": data_dir().exists(),
        "web_interface": app is not None,
        "local_only": True,
        "version": VERSION == "1.2.0",
    }
    print({"ok": all(checks.values()), "checks": checks, "version": VERSION})
    return 0 if all(checks.values()) else 2


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.4):
            return True
    except OSError:
        return False


def _open_when_ready() -> None:
    if NO_BROWSER:
        return
    for _ in range(120):
        if _port_open():
            webbrowser.open(URL)
            return
        time.sleep(0.25)


def main() -> int:
    init_db()
    if _port_open():
        if not NO_BROWSER:
            webbrowser.open(URL)
        return 0

    threading.Thread(target=_open_when_ready, daemon=True).start()
    config = uvicorn.Config(app=app, host=HOST, port=PORT, log_level="warning", access_log=False, log_config=None)
    server = uvicorn.Server(config)

    def watch_shutdown() -> None:
        while not server.should_exit:
            if shutdown_requested():
                server.should_exit = True
                return
            time.sleep(0.2)

    threading.Thread(target=watch_shutdown, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main())
