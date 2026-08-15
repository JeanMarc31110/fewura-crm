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
    hookspath=[],runtime_hooks=[],excludes=[],noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name="FEWURA_CRM",debug=False,bootloader_ignore_signals=False,strip=False,upx=True,console=True)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=True,upx_exclude=[],name="FEWURA_CRM")
