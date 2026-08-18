# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPEC).resolve().parent.parent

a = Analysis(
    [str(ROOT / "agent.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "httpx","bs4","lxml","ddgs","dns","dns.resolver","fastapi","uvicorn","multipart",
        "fewura_crm","fewura_crm.db","fewura_crm.paths","fewura_crm.tools","fewura_crm.prospect_engine","fewura_crm.web","fewura_crm.outreach",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Le CRM ne possède aucune route WebSocket. Ne pas embarquer ce paquet évite
    # les collisions/collectes partielles de websockets dans l'EXE PyInstaller.
    excludes=["websockets"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,
    name="FEWURA_CRM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
