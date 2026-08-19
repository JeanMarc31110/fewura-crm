import os
import sys
from pathlib import Path
import socket
import threading
import time
import webbrowser
import ctypes

import uvicorn

if os.name == "nt" and not os.getenv("FEWURA_CRM_DATA_DIR"):
    # The managed AppData folder on some machines is readable but refuses
    # SQLite sidecar creation. Keep the portable desktop build self-contained.
    os.environ["FEWURA_CRM_DATA_DIR"] = str(Path(sys.executable).resolve().parent / "data")

from fewura_crm.web import app, shutdown_requested


_INSTANCE_MUTEX = None


def acquire_single_instance() -> bool:
    """Prevent two desktop launches from writing to the same CRM database."""
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    create_mutex.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    handle = create_mutex(None, False, "Local\\FEWURA_CRM_1_4_3_SMTPFIX")
    if not handle:
        return True
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX = handle
    return True


def select_port() -> int:
    configured = os.getenv("FEWURA_PORT")
    if configured:
        return int(configured)
    for port in range(8766, 8786):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("Aucun port FEWURA disponible entre 8766 et 8785")


PORT = select_port()


def open_browser() -> None:
    time.sleep(1.5)
    url = f"http://127.0.0.1:{PORT}/"
    try:
        if os.name == "nt":
            os.startfile(url)
        else:
            webbrowser.open(url)
    except Exception as exc:
        log_path = os.path.join(os.getenv("LOCALAPPDATA", os.getcwd()), "FEWURA", "CRM", "launcher.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"Ouverture navigateur impossible: {exc}\nOuvrir manuellement: {url}\n")


if __name__ == "__main__":
    if not acquire_single_instance():
        raise SystemExit(0)
    # Chrome can crash on this PC when launched automatically. The CRM stays
    # available locally; browser opening is opt-in with FEWURA_OPEN_BROWSER=1.
    if os.getenv("FEWURA_OPEN_BROWSER", "0") == "1":
        threading.Thread(target=open_browser, daemon=True).start()
    # A windowed PyInstaller executable has no console stream; Uvicorn's
    # default logging formatter calls isatty() on that missing stream.
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_config=None, access_log=False)
    server = uvicorn.Server(config)

    def stop_when_requested() -> None:
        while not server.should_exit:
            if shutdown_requested():
                server.should_exit = True
                return
            time.sleep(0.2)

    threading.Thread(target=stop_when_requested, daemon=True).start()
    server.run()

