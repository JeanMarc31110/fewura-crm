import os
import shutil
import sqlite3
import threading
import time
import smtplib
import smtpd
import asyncore
import socket
from email import policy
from email.parser import BytesParser
from pathlib import Path
from datetime import datetime, timedelta

import pytest

TEST_ROOT = Path.cwd() / ".testdata"
os.environ["FEWURA_CRM_DATA_DIR"] = str(TEST_ROOT)

from fastapi.testclient import TestClient
from fewura_crm.db import init_db, execute, one, rows, connect, SQLITE_BUSY_TIMEOUT_MS
from fewura_crm.prospect_engine import build_overpass_query, fingerprint
import fewura_crm.prospect_engine as prospect_engine
from fewura_crm.tools import _merge_prospect_from_fewura
from fewura_crm.outreach import create_campaign, create_campaign_for_selection, run_campaign, process_due_campaigns, schedule_campaign, _send_email, save_smtp, APPROVED_EMAIL_SUBJECT, APPROVED_EMAIL_BODY, APPROVED_SMS_BODY
from fewura_crm.time_utils import local_input_to_utc_sql, utc_sql_to_local_display, local_now
import fewura_crm.gmail_oauth as gmail_oauth
import fewura_crm.outreach as outreach
import fewura_crm.web as web_module
from fewura_crm.web import app


@pytest.fixture(autouse=True)
def clean_database_before_each_test(tmp_path, monkeypatch):
    """Every test starts from a brand-new CRM, exactly like a fresh client install."""
    monkeypatch.setenv("FEWURA_CRM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(web_module, "start_scheduler", lambda *args, **kwargs: None)
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


def test_sqlite_uses_wal_and_waits_for_transient_write_lock():
    con = connect()
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == SQLITE_BUSY_TIMEOUT_MS
        assert con.isolation_level is None
    finally:
        con.close()

    locked = threading.Event()

    def hold_write_lock():
        holder = connect()
        try:
            holder.execute("BEGIN IMMEDIATE")
            locked.set()
            time.sleep(0.25)
            holder.rollback()
        finally:
            holder.close()

    thread = threading.Thread(target=hold_write_lock)
    thread.start()
    assert locked.wait(2)
    pid = execute(
        "INSERT INTO prospects(company_name,email) VALUES(?,?)",
        ("Écriture concurrente", "concurrence@example.test"),
    )
    thread.join(2)
    assert not thread.is_alive()
    assert one("SELECT company_name FROM prospects WHERE id=?", (pid,))["company_name"] == "Écriture concurrente"


def test_campaign_creation_rolls_back_and_releases_lock_on_error(monkeypatch):
    class BrokenAlias(str):
        def lower(self):
            raise RuntimeError("alias volontairement invalide")

    monkeypatch.setitem(outreach.CATEGORY_ALIASES, "categorie_test", [BrokenAlias("cassé")])
    with pytest.raises(RuntimeError, match="alias volontairement invalide"):
        create_campaign("Campagne annulée", category="categorie_test")

    assert one("SELECT id FROM campaigns WHERE name=?", ("Campagne annulée",)) is None
    pid = execute(
        "INSERT INTO prospects(company_name,email) VALUES(?,?)",
        ("Base libérée", "base-liberee@example.test"),
    )
    assert pid > 0


def test_concurrent_database_initialization_is_safe(tmp_path, monkeypatch):
    fresh_data = tmp_path / "concurrent-init"
    monkeypatch.setenv("FEWURA_CRM_DATA_DIR", str(fresh_data))
    errors = []

    def initialize():
        try:
            init_db()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=initialize) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    assert one("SELECT name FROM sqlite_master WHERE type='table' AND name='campaigns'")


def test_locked_database_error_is_translated_for_the_interface():
    assert "base clients est momentanément occupée" in web_module.friendly_error(
        sqlite3.OperationalError("database is locked")
    )


def test_notes_and_tasks():
    init_db(); pid = execute("INSERT INTO prospects(company_name) VALUES(?)", ("Test Notes",))
    nid = execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)", (pid, "Rappeler lundi"))
    tid = execute("INSERT INTO tasks(prospect_id,title) VALUES(?,?)", (pid, "Relance"))
    assert one("SELECT body FROM notes WHERE id=?", (nid,))["body"] == "Rappeler lundi"
    assert one("SELECT title FROM tasks WHERE id=?", (tid,))["title"] == "Relance"


def test_fewura_prospect_hotel_query():
    query = build_overpass_query(43.6045, 1.4442, 20000, "hotels")
    assert '["tourism"="hotel"]' in query and '["tourism"="guest_house"]' in query and "out tags center" in query


def test_transport_query_covers_common_osm_business_tags():
    query = build_overpass_query(43.6045, 1.4442, 20000, "transport")
    assert '["office"="logistics"]' in query
    assert '["office"="transport"]' in query
    assert '["office"="courier"]' in query
    assert '["craft"="transportation"]' in query
    assert '["industrial"="logistics"]' in query


def test_private_filter_excludes_public_organizations_but_keeps_private_companies():
    assert prospect_engine.is_private_business("Tisséo", {"operator:type": "public"}) is False
    assert prospect_engine.is_private_business("Mairie de Toulouse", {}) is False
    assert prospect_engine.is_private_business("Transport Exemple", {"operator:type": "private"}) is True


def test_overpass_query_is_not_artificially_limited_to_one_hundred_results():
    query = build_overpass_query(43.6045, 1.4442, 20000, "transport")
    assert "out tags center;" in query
    assert "out tags center 100;" not in query


def test_website_discovery_has_search_fallback_when_ddgs_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        prospect_engine,
        "_search_web_results",
        lambda query, max_results=8: [{
            "href": "https://transport-exemple.fr/",
            "title": "Transport Exemple Toulouse — Contact",
            "body": "Site officiel et contact",
        }],
    )
    assert prospect_engine.discover_official_website("Transport Exemple", "Toulouse") == "https://transport-exemple.fr/"


def test_search_discards_results_without_email_or_phone(monkeypatch):
    monkeypatch.setattr(prospect_engine, "geocode", lambda zone: {"lat": 43.6, "lon": 1.4})
    monkeypatch.setattr(
        prospect_engine,
        "_fetch_overpass",
        lambda query: {"elements": [
            {"type": "node", "id": 1, "lat": 43.6, "lon": 1.4, "tags": {"name": "Avec téléphone", "office": "transport", "phone": "0612345678"}},
            {"type": "node", "id": 2, "lat": 43.6, "lon": 1.4, "tags": {"name": "Sans contact", "office": "transport"}},
            {"type": "node", "id": 3, "lat": 43.6, "lon": 1.4, "tags": {"name": "Avec email", "office": "transport", "email": "contact@transport.test"}},
        ]},
    )
    found = prospect_engine.search_businesses("Toulouse", "transport", 20, 50, enrich=False)
    assert [p["company_name"] for p in found] == ["Avec téléphone", "Avec email"]


def test_contacts_page_hides_empty_prospects_and_rejects_empty_selection():
    init_db()
    empty_id = execute("INSERT INTO prospects(company_name) VALUES(?)", ("Sans contact",))
    usable_id = execute("INSERT INTO prospects(company_name,phone) VALUES(?,?)", ("Avec téléphone", "0612345678"))
    with TestClient(app) as client:
        page = client.get("/prospects")
        assert "Sans contact" not in page.text
        assert "Avec téléphone" in page.text
        rejected = client.post("/campaigns/from-selection", data={"ids": [str(empty_id)]})
        assert rejected.status_code == 200
        assert "Aucun prospect exploitable" in rejected.text
        accepted = client.post("/campaigns/from-selection", data={"ids": [str(usable_id)]})
        assert accepted.status_code == 200
        assert "Envoi direct" in accepted.text


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
        assert client.get("/health").json()["version"] == "1.4.4"
        home = client.get("/").text
        assert "Campagnes" in home and "Emails / SMS / historique" in home
        campaigns = client.get("/campaigns").text
        assert "Nouvelle campagne" in campaigns and "Simulation" in campaigns and "SMS" in campaigns
        assert "Simuler" in campaigns and "Envoyer réellement" in campaigns
        settings = client.get("/settings").text
        assert "Email SMTP" in settings and "SMS via votre téléphone Android" in settings
        assert "WhatsApp" not in settings


def test_selected_send_hides_message_editors_and_uses_approved_templates():
    init_db()
    pid = execute(
        "INSERT INTO prospects(company_name,email,phone) VALUES(?,?,?)",
        ("Contact modèle", "contact@modele.test", "0612345678"),
    )
    with TestClient(app) as client:
        form = client.post("/campaigns/from-selection", data={"ids": [str(pid)]})
        assert form.status_code == 200
        assert "Message email" not in form.text
        assert "Message SMS" not in form.text
        assert "Les modèles e-mail et SMS approuvés sont utilisés automatiquement" in form.text
        assert "Programmer date/heure" not in form.text
        assert "Créer l’envoi" not in form.text
        assert "Tester sans envoyer" in form.text
        assert "Envoyer maintenant" in form.text

        tested = client.post(
            "/campaigns/from-selection/send",
            data={"ids": [str(pid)], "channel": "auto", "action": "simulate"},
            follow_redirects=True,
        )
        assert tested.status_code == 200
        assert "Test terminé sans envoi : 1 message(s) préparé(s), 0 contact(s) sans coordonnée adaptée" in tested.text

    campaign = one("SELECT * FROM campaigns WHERE name LIKE 'Envoi direct %'")
    assert campaign["body"] == APPROVED_EMAIL_BODY
    assert campaign["sms_body"] == APPROVED_SMS_BODY
    assert one("SELECT status FROM communications WHERE campaign_id=?", (campaign["id"],))["status"] == "simulated"


def test_direct_real_send_requires_confirmation_and_sends_immediately(monkeypatch):
    pid = execute(
        "INSERT INTO prospects(company_name,email) VALUES(?,?)",
        ("Envoi direct réel", "direct@example.test"),
    )
    sent_calls = []
    monkeypatch.setattr(outreach, "_send_email", lambda *args, **kwargs: sent_calls.append((args, kwargs)))

    with TestClient(app) as client:
        refused = client.post(
            "/campaigns/from-selection/send",
            data={"ids": [str(pid)], "channel": "email", "action": "send"},
        )
        assert refused.status_code == 200
        assert "Confirmation requise" in refused.text
        assert "Aucun message n’a été envoyé" in refused.text
        assert sent_calls == []
        assert one("SELECT count(*) n FROM campaigns")["n"] == 0

        sent = client.post(
            "/campaigns/from-selection/send",
            data={
                "ids": [str(pid)], "channel": "email", "action": "send",
                "confirm_real": "OUI", "subject": "Objet direct",
            },
            follow_redirects=True,
        )
        assert sent.status_code == 200
        assert "Envoi direct terminé : 1 envoyé(s), 0 contact(s) sans coordonnée adaptée, 0 erreur(s)" in sent.text
        assert len(sent_calls) == 1

    communication = one("SELECT status,recipient,subject FROM communications")
    assert communication == {
        "status": "sent", "recipient": "direct@example.test", "subject": "Objet direct"
    }


def test_direct_email_send_skips_selected_prospect_without_email():
    email_id = execute(
        "INSERT INTO prospects(company_name,email) VALUES(?,?)",
        ("Avec email", "avec-email@example.test"),
    )
    phone_only_id = execute(
        "INSERT INTO prospects(company_name,phone) VALUES(?,?)",
        ("Téléphone uniquement", "0612345678"),
    )

    with TestClient(app) as client:
        response = client.post(
            "/campaigns/from-selection/send",
            data={
                "ids": [str(email_id), str(phone_only_id)],
                "channel": "email", "action": "simulate",
            },
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "1 message(s) préparé(s), 1 contact(s) sans coordonnée adaptée, 0 erreur(s)" in response.text
    statuses = rows("SELECT prospect_id,status FROM campaign_recipients ORDER BY prospect_id")
    assert statuses == [
        {"prospect_id": email_id, "status": "simulated"},
        {"prospect_id": phone_only_id, "status": "skipped"},
    ]


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


def test_smtp_security_normalizes_standard_ports():
    save_smtp("smtp.example.test", 587, "user", "secret", "from@example.test", "FEWURA", "ssl")
    assert outreach.smtp_status()["port"] == 465
    save_smtp("smtp.example.test", 465, "user", "secret", "from@example.test", "FEWURA", "starttls")
    assert outreach.smtp_status()["port"] == 587


def test_smtp_error_identifies_protocol_stage_without_leaking_password(monkeypatch):
    class ClosedConnection:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr(outreach, "gmail_status", lambda: {"configured": False})
    monkeypatch.setattr(outreach, "smtp_status", lambda: {
        "configured": True, "host": "smtp.test", "port": 587, "username": "user",
        "from_email": "from@example.test", "from_name": "FEWURA", "security": "starttls",
    })
    monkeypatch.setattr(outreach.smtplib, "SMTP", ClosedConnection)
    monkeypatch.setattr(outreach, "get_setting", lambda key, default="": "super-secret" if key == "smtp_password" else default)
    with pytest.raises(RuntimeError, match=r"Échec SMTP smtp\.test:587 \(starttls\) pendant connexion") as exc:
        _send_email({"email": "dest@example.test"}, "Objet", "Message")
    assert "super-secret" not in str(exc.value)


def test_real_email_path_delivers_to_local_debug_smtp_without_external_recipient(monkeypatch):
    received = []

    class CaptureServer(smtpd.SMTPServer):
        def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
            received.append((mailfrom, tuple(rcpttos), data))

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = CaptureServer(("127.0.0.1", port), None)
    thread = threading.Thread(target=asyncore.loop, kwargs={"timeout": 0.05}, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(outreach, "gmail_status", lambda: {"configured": False})
        save_smtp("127.0.0.1", port, "", "", "sender@example.test", "FEWURA", "none")
        _send_email({"email": "local-only@example.test"}, "Objet contrôlé", "Message contrôlé")
        deadline = time.time() + 2
        while not received and time.time() < deadline:
            time.sleep(0.02)
        assert received and received[0][1] == ("local-only@example.test",)
        parsed = BytesParser(policy=policy.default).parsebytes(received[0][2])
        assert parsed["Subject"] == "Objet contrôlé"
    finally:
        server.close()


def test_campaign_schedule_stores_utc_and_displays_local_consistently():
    local_value = (local_now() + timedelta(days=1)).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    utc_value = local_input_to_utc_sql(local_value)
    assert utc_value.endswith(":00")
    expected_display = f"{local_value[8:10]}/{local_value[5:7]}/{local_value[0:4]} {local_value[11:]}"
    assert utc_sql_to_local_display(utc_value).startswith(expected_display)
    execute("INSERT INTO prospects(company_name,email) VALUES(?,?)", ("Horodatage", "local-only@example.test"))
    cid = create_campaign("Fuseau", "Objet", "Message", "", "", 0, "simulation", local_value)
    stored = one("SELECT scheduled_at FROM campaigns WHERE id=?", (cid,))["scheduled_at"]
    assert stored == utc_value
    assert process_due_campaigns() == []


def test_campaign_web_routes_show_errors_instead_of_internal_server_error(monkeypatch):
    pid = execute(
        "INSERT INTO prospects(company_name,email) VALUES(?,?)",
        ("Test erreur contrôlée", "contact@example.test"),
    )
    cid = create_campaign_for_selection(
        "Test erreur", APPROVED_EMAIL_SUBJECT, APPROVED_EMAIL_BODY,
        [pid], channel="email", mode="reel",
    )
    monkeypatch.setattr(outreach, "_send_email", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Gmail indisponible pour le test")))

    with TestClient(app) as client:
        missing_selection = client.post(
            "/campaigns/from-selection/create",
            data={"name": "Sans sélection", "mode": "simulation"},
            follow_redirects=True,
        )
        assert missing_selection.status_code == 200
        assert "Création impossible" in missing_selection.text
        assert "Internal Server Error" not in missing_selection.text

        missing_campaign = client.post("/campaigns/999999/run", follow_redirects=True)
        assert missing_campaign.status_code == 200
        assert "Campagne introuvable" in missing_campaign.text
        assert "Internal Server Error" not in missing_campaign.text

        failed_send = client.post(
            f"/campaigns/{cid}/run",
            data={"confirm_real": "OUI"},
            follow_redirects=True,
        )
        assert failed_send.status_code == 200
        assert "1 erreur(s)" in failed_send.text
        assert "Internal Server Error" not in failed_send.text
        logged = one("SELECT status,error FROM communications WHERE campaign_id=?", (cid,))
        assert logged["status"] == "error"
        assert "Gmail indisponible" in logged["error"]


def test_simulated_campaign_can_be_sent_for_real_once_without_duplicate(monkeypatch):
    pid = execute(
        "INSERT INTO prospects(company_name,email) VALUES(?,?)",
        ("Conversion simulation", "conversion@example.test"),
    )
    cid = create_campaign_for_selection(
        "Simulation puis réel", APPROVED_EMAIL_SUBJECT, APPROVED_EMAIL_BODY,
        [pid], channel="email", mode="simulation",
    )
    sent_calls = []
    monkeypatch.setattr(outreach, "_send_email", lambda *args, **kwargs: sent_calls.append((args, kwargs)))

    simulated = run_campaign(cid)
    assert simulated["simulated"] == 1
    assert simulated["sent"] == 0
    assert sent_calls == []

    real = run_campaign(cid, force_mode="reel")
    assert real["sent"] == 1
    assert real["errors"] == 0
    assert len(sent_calls) == 1
    assert one("SELECT mode FROM campaigns WHERE id=?", (cid,))["mode"] == "reel"
    assert one("SELECT status FROM campaign_recipients WHERE campaign_id=?", (cid,))["status"] == "sent"

    repeated = run_campaign(cid, force_mode="reel")
    assert repeated["sent"] == 0
    assert len(sent_calls) == 1


def test_real_send_from_web_requires_confirmation_even_after_simulation(monkeypatch):
    pid = execute(
        "INSERT INTO prospects(company_name,email) VALUES(?,?)",
        ("Confirmation réelle", "confirmation@example.test"),
    )
    cid = create_campaign_for_selection(
        "Confirmation web", APPROVED_EMAIL_SUBJECT, APPROVED_EMAIL_BODY,
        [pid], channel="email", mode="simulation",
    )
    sent_calls = []
    monkeypatch.setattr(outreach, "_send_email", lambda *args, **kwargs: sent_calls.append((args, kwargs)))

    with TestClient(app) as client:
        simulation = client.post(
            f"/campaigns/{cid}/run",
            data={"force_mode": "simulation"},
            follow_redirects=True,
        )
        assert simulation.status_code == 200
        assert "mode simulation" in simulation.text
        assert sent_calls == []

        refused = client.post(
            f"/campaigns/{cid}/run",
            data={"force_mode": "reel"},
        )
        assert refused.status_code == 200
        assert "Confirmation requise" in refused.text
        assert "n’a pas été lancé" in refused.text
        assert sent_calls == []

        accepted = client.post(
            f"/campaigns/{cid}/run",
            data={"force_mode": "reel", "confirm_real": "OUI"},
            follow_redirects=True,
        )
        assert accepted.status_code == 200
        assert "mode réel" in accepted.text
        assert len(sent_calls) == 1


def test_approved_email_and_sms_templates_are_selected_by_channel():
    init_db()
    email_id = execute("INSERT INTO prospects(company_name,email) VALUES(?,?)", ("Email cible", "email@example.test"))
    sms_id = execute("INSERT INTO prospects(company_name,phone) VALUES(?,?)", ("SMS cible", "0612345678"))
    cid = create_campaign_for_selection("Modèles validés", "", "", [email_id, sms_id], channel="auto", mode="simulation")
    result = run_campaign(cid)
    assert result["simulated"] == 2 and result["errors"] == 0
    email_log = one("SELECT body FROM communications WHERE campaign_id=? AND channel='email'", (cid,))
    sms_log = one("SELECT body FROM communications WHERE campaign_id=? AND channel='sms'", (cid,))
    assert email_log["body"] == APPROVED_EMAIL_BODY
    assert sms_log["body"] == APPROVED_SMS_BODY
    assert "https://innovatechsoftware.eu" in sms_log["body"]



def test_prospect_contact_mode_filters_email_and_phone(monkeypatch):
    monkeypatch.setattr(prospect_engine, "geocode", lambda zone: {"lat": 43.6, "lon": 1.4})
    monkeypatch.setattr(
        prospect_engine,
        "_fetch_overpass",
        lambda query: {"elements": [
            {"type": "node", "id": 1, "lat": 43.6, "lon": 1.4, "tags": {"name": "Email et téléphone", "office": "transport", "email": "contact@both.test", "phone": "0611223344"}},
            {"type": "node", "id": 2, "lat": 43.6, "lon": 1.4, "tags": {"name": "Email seul", "office": "transport", "email": "contact@email.test"}},
            {"type": "node", "id": 3, "lat": 43.6, "lon": 1.4, "tags": {"name": "Téléphone seul", "office": "transport", "phone": "0611225566"}},
        ]},
    )
    assert [p["company_name"] for p in prospect_engine.search_businesses("Toulouse", "transport", 20, 50, enrich=False, contact_mode="email")] == ["Email et téléphone", "Email seul"]
    assert [p["company_name"] for p in prospect_engine.search_businesses("Toulouse", "transport", 20, 50, enrich=False, contact_mode="phone")] == ["Email et téléphone", "Téléphone seul"]
    assert len(prospect_engine.search_businesses("Toulouse", "transport", 20, 50, enrich=False, contact_mode="either")) == 3


def test_prospect_page_exposes_contact_modes_and_expanded_activity_choices():
    with TestClient(app) as client:
        page = client.get("/prospect")
        assert page.status_code == 200
        assert "Email ou téléphone" in page.text
        assert "Email uniquement" in page.text
        assert "Téléphone uniquement" in page.text
        assert "Santé" in page.text
        assert "Événementiel" in page.text



def test_real_campaign_uses_batches_of_50_and_schedules_next_batch(monkeypatch):
    ids = [execute("INSERT INTO prospects(company_name,email) VALUES(?,?)", (f"Lot {i}", f"lot{i}@example.test")) for i in range(55)]
    cid = create_campaign_for_selection(
        "Lots de 50", APPROVED_EMAIL_SUBJECT, APPROVED_EMAIL_BODY, ids,
        channel="email", mode="simulation",
    )
    sent = []
    monkeypatch.setattr(outreach, "_send_email", lambda *args, **kwargs: sent.append(args))
    assert run_campaign(cid)["simulated"] == 50
    result = run_campaign(cid, force_mode="reel")
    assert result["sent"] == 50
    assert len(sent) == 50
    assert result["pending"] == 5
    campaign = one("SELECT status,scheduled_at FROM campaigns WHERE id=?", (cid,))
    assert campaign["status"] == "planifiee"
    assert campaign["scheduled_at"]


def test_global_email_limit_pauses_all_campaigns(monkeypatch):
    pid = execute("INSERT INTO prospects(company_name,email) VALUES(?,?)", ("Quota", "quota@example.test"))
    cid = create_campaign_for_selection(
        "Quota global", APPROVED_EMAIL_SUBJECT, APPROVED_EMAIL_BODY, [pid],
        channel="email", mode="reel",
    )
    for index in range(400):
        execute(
            "INSERT INTO communications(channel,direction,status,recipient,subject,body) VALUES(?,?,?,?,?,?)",
            ("email", "sortant", "sent", f"old{index}@example.test", "old", "old"),
        )
    sent = []
    monkeypatch.setattr(outreach, "_send_email", lambda *args, **kwargs: sent.append(args))
    result = run_campaign(cid, force_mode="reel")
    assert result["sent"] == 0
    assert result["paused"] is True
    assert result["pending"] == 1
    assert sent == []
    assert one("SELECT status FROM campaigns WHERE id=?", (cid,))["status"] == "planifiee"
