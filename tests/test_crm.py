import os
import shutil
from pathlib import Path

TEST_ROOT = Path.cwd() / ".testdata"
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
os.environ["FEWURA_CRM_DATA_DIR"] = str(TEST_ROOT)

from fewura_crm.db import init_db, execute, one
from fewura_crm.prospect_engine import build_overpass_query, fingerprint
from fewura_crm.tools import _merge_prospect_from_fewura


def test_schema_and_crud():
    init_db()
    pid = execute(
        "INSERT INTO prospects(company_name,email,city) VALUES(?,?,?)",
        ("Test Toulouse", "contact@test.fr", "Toulouse"),
    )
    p = one("SELECT * FROM prospects WHERE id=?", (pid,))
    assert p["company_name"] == "Test Toulouse"
    assert p["email"] == "contact@test.fr"
    assert "fingerprint" in p
    assert "source_url" in p
    execute("UPDATE prospects SET status='qualifie' WHERE id=?", (pid,))
    assert one("SELECT status FROM prospects WHERE id=?", (pid,))["status"] == "qualifie"


def test_notes_and_tasks():
    init_db()
    pid = execute("INSERT INTO prospects(company_name) VALUES(?)", ("Test Notes",))
    nid = execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)", (pid, "Rappeler lundi"))
    tid = execute("INSERT INTO tasks(prospect_id,title) VALUES(?,?)", (pid, "Relance"))
    assert one("SELECT body FROM notes WHERE id=?", (nid,))["body"] == "Rappeler lundi"
    assert one("SELECT title FROM tasks WHERE id=?", (tid,))["title"] == "Relance"


def test_fewura_prospect_hotel_query():
    query = build_overpass_query(43.6045, 1.4442, 20000, "hotels")
    assert '["tourism"="hotel"]' in query
    assert '["tourism"="guest_house"]' in query
    assert "out tags center" in query


def test_import_preserves_crm_pipeline_and_enriches_contact():
    init_db()
    initial = {
        "company_name": "Hotel CRM Test",
        "city": "Toulouse",
        "phone": "01 02 03 04 05",
        "website": "https://hotel-crm-test.fr",
        "address": "1 rue Test",
    }
    fp = fingerprint(initial)
    pid = execute(
        "INSERT INTO prospects(company_name,city,phone,website,address,status,fingerprint,source) VALUES(?,?,?,?,?,?,?,?)",
        (initial["company_name"], initial["city"], initial["phone"], initial["website"], initial["address"], "qualifie", fp, "manuel"),
    )
    execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)", (pid, "Client intéressé"))
    execute("INSERT INTO tasks(prospect_id,title) VALUES(?,?)", (pid, "Envoyer proposition"))

    fresh = dict(initial)
    fresh.update({
        "email": "contact@hotel-crm-test.fr",
        "category": "hotel",
        "postal_code": "31000",
        "source_url": "https://www.openstreetmap.org/node/123",
        "source_type": "FEWURA Prospect / OpenStreetMap",
        "lead_score": 95,
        "confidence": 0.95,
        "fingerprint": fp,
    })
    merged_id, created = _merge_prospect_from_fewura(fresh)
    assert merged_id == pid
    assert created is False
    merged = one("SELECT * FROM prospects WHERE id=?", (pid,))
    assert merged["status"] == "qualifie"
    assert merged["email"] == "contact@hotel-crm-test.fr"
    assert merged["lead_score"] == 95
    assert merged["source"] == "fewura-prospect"
    assert one("SELECT count(*) n FROM notes WHERE prospect_id=?", (pid,))["n"] == 1
    assert one("SELECT count(*) n FROM tasks WHERE prospect_id=?", (pid,))["n"] == 1
