from pathlib import Path

from fewura_crm.db import one
from fewura_crm.legacy_config import migrate_legacy_smtp_settings


def test_migrates_legacy_fewura_smtp(monkeypatch, tmp_path):
    local = tmp_path / "local"
    crm = tmp_path / "crm"
    legacy = local / "FEWURA" / "PROSPECT"
    legacy.mkdir(parents=True)
    (legacy / ".env").write_text(
        "SMTP_HOST=smtp.example.test\n"
        "SMTP_PORT=587\n"
        "SMTP_USERNAME=contact@example.test\n"
        "SMTP_PASSWORD=secret-test\n"
        "SMTP_FROM=contact@example.test\n"
        "SMTP_USE_TLS=true\n"
        "SENDER_COMPANY=FEWURA\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("FEWURA_CRM_DATA_DIR", str(crm))
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS"):
        monkeypatch.delenv(key, raising=False)

    result = migrate_legacy_smtp_settings()

    assert result["migrated"] is True
    assert one("SELECT value FROM settings WHERE key='smtp_host'")["value"] == "smtp.example.test"
    assert one("SELECT value FROM settings WHERE key='smtp_username'")["value"] == "contact@example.test"
    assert one("SELECT value FROM settings WHERE key='smtp_password'")["value"] == "secret-test"
    assert one("SELECT value FROM settings WHERE key='smtp_security'")["value"] == "starttls"


def test_does_not_overwrite_existing_crm_smtp(monkeypatch, tmp_path):
    from fewura_crm.db import connect, init_db

    crm = tmp_path / "crm-existing"
    monkeypatch.setenv("FEWURA_CRM_DATA_DIR", str(crm))
    init_db()
    con = connect()
    con.execute("INSERT INTO settings(key,value) VALUES('smtp_host','smtp.crm.test')")
    con.commit()
    con.close()

    result = migrate_legacy_smtp_settings()

    assert result == {"migrated": False, "reason": "already_configured"}
    assert one("SELECT value FROM settings WHERE key='smtp_host'")["value"] == "smtp.crm.test"
