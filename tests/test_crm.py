import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta

TEST_ROOT = Path.cwd() / ".testdata"
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
os.environ["FEWURA_CRM_DATA_DIR"] = str(TEST_ROOT)

from fastapi.testclient import TestClient
from fewura_crm.db import init_db, execute, one, rows
from fewura_crm.prospect_engine import build_overpass_query, fingerprint
from fewura_crm.tools import _merge_prospect_from_fewura
from fewura_crm.outreach import create_campaign, run_campaign, process_due_campaigns, schedule_campaign
from fewura_crm.web import app


def test_schema_and_crud():
    init_db()
    pid = execute("INSERT INTO prospects(company_name,email,city) VALUES(?,?,?)", ("Test Toulouse", "contact@test.fr", "Toulouse"))
    p = one("SELECT * FROM prospects WHERE id=?", (pid,))
    assert p["company_name"] == "Test Toulouse"
    assert "fingerprint" in p and "source_url" in p
    assert one("SELECT name FROM sqlite_master WHERE type='table' AND name='campaigns'")
    assert one("SELECT name FROM sqlite_master WHERE type='table' AND name='communications'")
    execute("UPDATE prospects SET status='qualifie' WHERE id=?", (pid,))
    assert one("SELECT status FROM prospects WHERE id=?", (pid,))["status"] == "qualifie"


def test_notes_and_tasks():
    init_db(); pid = execute("INSERT INTO prospects(company_name) VALUES(?)", ("Test Notes",))
    nid = execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)", (pid, "Rappeler lundi"))
    tid = execute("INSERT INTO tasks(prospect_id,title) VALUES(?,?)", (pid, "Relance"))
    assert one("SELECT body FROM notes WHERE id=?", (nid,))["body"] == "Rappeler lundi"
    assert one("SELECT title FROM tasks WHERE id=?", (tid,))["title"] == "Relance"


def test_fewura_prospect_hotel_query():
    query = build_overpass_query(43.6045, 1.4442, 20000, "hotels")
    assert '["tourism"="hotel"]' in query and '["tourism"="guest_house"]' in query and "out tags center" in query


def test_import_preserves_crm_pipeline_and_enriches_contact():
    init_db()
    initial = {"company_name":"Hotel CRM Test","city":"Toulouse","phone":"01 02 03 04 05","website":"https://hotel-crm-test.fr","address":"1 rue Test"}
    fp = fingerprint(initial)
    pid = execute("INSERT INTO prospects(company_name,city,phone,website,address,status,fingerprint,source) VALUES(?,?,?,?,?,?,?,?)", (initial["company_name"],initial["city"],initial["phone"],initial["website"],initial["address"],"qualifie",fp,"manuel"))
    execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)", (pid, "Client intéressé")); execute("INSERT INTO tasks(prospect_id,title) VALUES(?,?)", (pid, "Envoyer proposition"))
    fresh = dict(initial); fresh.update({"email":"contact@hotel-crm-test.fr","category":"hotel","postal_code":"31000","source_url":"https://www.openstreetmap.org/node/123","source_type":"FEWURA Prospect / OpenStreetMap","lead_score":95,"confidence":0.95,"fingerprint":fp})
    merged_id, created = _merge_prospect_from_fewura(fresh)
    merged = one("SELECT * FROM prospects WHERE id=?", (pid,))
    assert merged_id == pid and created is False and merged["status"] == "qualifie" and merged["email"] == "contact@hotel-crm-test.fr" and merged["lead_score"] == 95
    assert one("SELECT count(*) n FROM notes WHERE prospect_id=?", (pid,))["n"] == 1


def test_campaign_simulation_personalization_and_antiduplicate():
    init_db()
    execute("INSERT INTO prospects(company_name,contact_name,email,city,category,lead_score) VALUES(?,?,?,?,?,?)", ("Alpha Hôtel","Mme Martin","contact@alpha.test","Toulouse","hotels",90))
    execute("INSERT INTO prospects(company_name,phone,city,category,lead_score) VALUES(?,?,?,?,?)", ("Beta Hôtel","06 12 34 56 78","Toulouse","hotels",80))
    cid = create_campaign("Test hôtels","Bonjour {entreprise}","Bonjour {contact}, société {entreprise} à {ville}","hotels","Toulouse",50,"simulation","")
    recips = rows("SELECT * FROM campaign_recipients WHERE campaign_id=? ORDER BY prospect_id", (cid,))
    assert len(recips) == 2
    assert {r["channel"] for r in recips} == {"email","whatsapp"}
    result = run_campaign(cid)
    assert result["processed"] == 2 and result["simulated"] == 2 and result["errors"] == 0
    logs = rows("SELECT * FROM communications WHERE campaign_id=? ORDER BY id", (cid,))
    assert len(logs) == 2 and all(x["status"] == "simulated" for x in logs)
    assert any("Alpha Hôtel" in (x["subject"] or "") for x in logs)
    again = run_campaign(cid)
    assert again["processed"] == 0
    assert one("SELECT count(*) n FROM communications WHERE campaign_id=?", (cid,))["n"] == 2


def test_due_scheduler_executes_simulation():
    init_db()
    execute("INSERT INTO prospects(company_name,email,lead_score) VALUES(?,?,?)", ("Gamma","gamma@test.fr",70))
    cid = create_campaign("Planifiée","Sujet {entreprise}","Message","","",0,"simulation","")
    past = (datetime.now() - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M")
    schedule_campaign(cid,past,"simulation")
    results = process_due_campaigns()
    assert any(x.get("campaign_id") == cid for x in results)
    assert one("SELECT status FROM campaigns WHERE id=?", (cid,))["status"] == "terminee"


def test_management_web_interface_contains_outreach_sections():
    init_db()
    with TestClient(app) as client:
        assert client.get("/health").json()["version"] == "1.3.0"
        home = client.get("/").text
        assert "Campagnes" in home and "Emails / historique" in home
        campaigns = client.get("/campaigns").text
        assert "Nouvelle campagne" in campaigns and "Simulation" in campaigns
        settings = client.get("/settings").text
        assert "Email SMTP" in settings and "Meta WhatsApp Business Cloud" in settings
