# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

ROOT = Path(SPEC).resolve().parent.parent

runtime_datas = []
for dist_name in [
    "mcp",
    "openai-agents",
    "openai",
    "pydantic",
    "ddgs",
    "fake-useragent",
    "primp",
    "httpx",
    "httpx2",
]:
    try:
        runtime_datas += copy_metadata(dist_name)
    except Exception:
        pass

try:
    runtime_datas += collect_data_files("agents")
except Exception:
    pass

a = Analysis(
    [str(ROOT / "agent.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=runtime_datas,
    hiddenimports=[
        "agents",
        "openai",
        "httpx",
        "bs4",
        "lxml",
        "ddgs",
        "dns",
        "dns.resolver",
        "fewura_crm",
        "fewura_crm.db",
        "fewura_crm.paths",
        "fewura_crm.tools",
        "fewura_crm.prospect_engine",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FEWURA_CRM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FEWURA_CRM",
)
