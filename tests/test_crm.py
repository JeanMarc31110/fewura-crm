import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta

import pytest

TEST_ROOT = Path.cwd() / ".testdata"
os.environ["FEWURA_CRM_DATA_DIR"] = str(TEST_ROOT)

from fastapi.testclient import TestClient
from fewura_crm.db import init_db, execute, one, rows
from fewura_crm.prospect_engine import build_overpass_query, fingerprint
import fewura_crm.prospect_engine as prospect_engine
from fewura_crm.tools import _merge_prospect_from_fewura
from fewura_crm.outreach import create_campaign, create_campaign_for_selection, run_campaign, process_due_campaigns, schedule_campaign, _send_email
import fewura_crm.gmail_oauth as gmail_oauth
from fewura_crm.web import app


@pytest.fixture(autouse=True)
def clean_database_before_each_test():
    """Every test starts from a brand-new CRM, exactly like a fresh client install."""
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    init_db()
    yield


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
    assert {r["channel"] for r in recips} == {"email","sms"}
    result = run_campaign(cid)
    assert result["processed"] == 2 and result["simulated"] == 2 and result["errors"] == 0
    assert result["sms"] == 1 and result["email"] == 1
    logs = rows("SELECT * FROM communications WHERE campaign_id=? ORDER BY id", (cid,))
    assert len(logs) == 2 and all(x["status"] == "simulated" for x in logs)
    assert any("Alpha Hôtel" in (x["subject"] or "") for x in logs)
    again = run_campaign(cid)
    assert again["processed"] == 0
    assert one("SELECT count(*) n FROM communications WHERE campaign_id=?", (cid,))["n"] == 2


def test_campaign_category_aliases_match_fewura_prospect_values():
    init_db()
    pid = execute("INSERT INTO prospects(company_name,email,city,category,lead_score) VALUES(?,?,?,?,?)", ("Alias Hôtel","alias@hotel.test","Toulouse","hotel",88))
    cid = create_campaign("Alias hôtels","Objet","Message","hotels","Toulouse",50,"simulation","")
    recipient = one("SELECT * FROM campaign_recipients WHERE campaign_id=? AND prospect_id=?", (cid,pid))
    assert recipient is not None
    assert recipient["channel"] == "email"


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
        assert client.get("/health").json()["version"] == "1.3.1"
        home = client.get("/").text
        assert "Campagnes" in home and "Emails / SMS / historique" in home
        campaigns = client.get("/campaigns").text
        assert "Nouvelle campagne" in campaigns and "Simulation" in campaigns and "SMS" in campaigns
        settings = client.get("/settings").text
        assert "Email SMTP" in settings and "SMS via votre téléphone Android" in settings
        assert "WhatsApp" not in settings


def test_overpass_reduces_heavy_query_after_all_relays_fail(monkeypatch):
    calls = []

    monkeypatch.setattr(
        prospect_engine,
        "geocode",
        lambda zone: {"lat": 43.6045, "lon": 1.4442, "display_name": zone},
    )

    def fake_fetch(query):
        calls.append(query)
        if len(calls) == 1:
            raise RuntimeError("all public relays failed")
        return {"elements": []}

    monkeypatch.setattr(prospect_engine, "_fetch_overpass", fake_fetch)
    result = prospect_engine.search_businesses("Toulouse", radius_km=20, enrich=False)

    assert result == []
    assert len(calls) == 2
    assert "around:20000" in calls[0]
    assert "around:10000" in calls[1]


def test_campaign_targets_only_selected_prospects_and_channel():
    init_db()
    email_id = execute(
        "INSERT INTO prospects(company_name,email,phone,lead_score) VALUES(?,?,?,?)",
        ("Selected Email", "contact@example.test", "0612345678", 80),
    )
    other_id = execute(
        "INSERT INTO prospects(company_name,email,lead_score) VALUES(?,?,?)",
        ("Not Selected", "other@example.test", 80),
    )
    cid = create_campaign_for_selection(
        "Sélection test", "Bonjour {entreprise}", "Message pour {entreprise}",
        [email_id], channel="email", mode="simulation",
    )
    recipients = rows(
        "SELECT prospect_id,channel,status FROM campaign_recipients WHERE campaign_id=?",
        (cid,),
    )
    assert recipients == [{"prospect_id": email_id, "channel": "email", "status": "pending"}]
    assert all(row["prospect_id"] != other_id for row in recipients)


def test_gmail_oauth_builds_message_without_exposing_credentials():
    raw = gmail_oauth._raw_message(
        "dest@example.test", "Objet", "Bonjour", "softwareinnovatech@gmail.com",
    )
    assert "dest@example.test" in __import__("base64").urlsafe_b64decode(raw + "==").decode("utf-8")
    assert "refresh_token" not in raw
    assert "client_secret" not in raw


def test_email_prefers_gmail_oauth_over_smtp(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "fewura_crm.outreach.gmail_status",
        lambda: {"configured": True, "account": "softwareinnovatech@gmail.com"},
    )
    monkeypatch.setattr(
        "fewura_crm.outreach.smtp_status",
        lambda: {"configured": False, "from_email": "softwareinnovatech@gmail.com", "from_name": "FEWURA CRM"},
    )
    monkeypatch.setattr(
        "fewura_crm.outreach.gmail_oauth.send_email",
        lambda **kwargs: calls.append(kwargs),
    )
    _send_email({"email": "dest@example.test"}, "Objet", "Message")
    assert len(calls) == 1
    assert calls[0]["to"] == "dest@example.test"
