from __future__ import annotations

import re
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from .db import connect, init_db, one, rows
from . import gmail_oauth

_scheduler_started = False
_scheduler_lock = threading.Lock()

SMS_SENDER_NUMBER = "+33773547857"

CATEGORY_ALIASES = {
    "restaurants": ["restaurants", "restaurant", "fast_food", "cafe"],
    "hotels": ["hotels", "hotel", "guest_house", "motel"],
    "garages": ["garages", "car_repair", "car"],
    "immobilier": ["immobilier", "estate_agent"],
    "comptables": ["comptables", "accountant"],
    "avocats": ["avocats", "lawyer"],
    "informatique": ["informatique", "it", "computer"],
    "batiment": ["batiment", "builder", "electrician", "plumber", "carpenter", "painter"],
    "coiffure": ["coiffure", "hairdresser"],
    "sport": ["sport", "fitness_centre", "sports_centre"],
    "transport": ["transport", "logistics", "transportation"],
}


def get_setting(key: str, default: str = "") -> str:
    init_db()
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_settings(values: dict[str, str]) -> None:
    init_db()
    con = connect()
    for key, value in values.items():
        con.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value or "")),
        )
    con.commit()
    con.close()


def gmail_status() -> dict:
    return gmail_oauth.status()


def test_gmail_connection() -> dict:
    return gmail_oauth.test_connection()


def smtp_status() -> dict:
    return {
        "configured": bool(get_setting("smtp_host") and get_setting("smtp_from_email")),
        "host": get_setting("smtp_host"),
        "port": int(get_setting("smtp_port", "587") or 587),
        "username": get_setting("smtp_username"),
        "from_email": get_setting("smtp_from_email"),
        "from_name": get_setting("smtp_from_name", "FEWURA CRM"),
        "security": get_setting("smtp_security", "starttls"),
    }


def sms_status() -> dict:
    return {
        "configured": bool(get_setting("sms_gateway_url") and get_setting("sms_gateway_token")),
        "gateway_url": get_setting("sms_gateway_url"),
        "sender_number": SMS_SENDER_NUMBER,
        "daily_limit": int(get_setting("sms_daily_limit", "20") or 20),
        "delay_seconds": int(get_setting("sms_delay_seconds", "10") or 10),
    }


def save_smtp(host: str, port: int, username: str, password: str, from_email: str, from_name: str, security: str) -> None:
    if security not in {"starttls", "ssl", "none"}:
        raise ValueError("Sécurité SMTP invalide")
    values = {
        "smtp_host": host.strip(),
        "smtp_port": str(int(port)),
        "smtp_username": username.strip(),
        "smtp_from_email": from_email.strip(),
        "smtp_from_name": from_name.strip() or "FEWURA CRM",
        "smtp_security": security,
    }
    if password:
        values["smtp_password"] = password
    set_settings(values)


def save_sms(gateway_url: str, token: str, daily_limit: int = 20, delay_seconds: int = 10) -> None:
    url = gateway_url.strip().rstrip("/")
    if url and not re.match(r"^https?://", url, re.I):
        raise ValueError("L'adresse de la passerelle SMS doit commencer par http:// ou https://")
    values = {
        "sms_gateway_url": url,
        "sms_daily_limit": str(max(1, min(int(daily_limit or 20), 500))),
        "sms_delay_seconds": str(max(0, min(int(delay_seconds or 10), 300))),
    }
    if token:
        values["sms_gateway_token"] = token.strip()
    set_settings(values)


def test_sms_gateway() -> dict:
    cfg = sms_status()
    if not cfg["configured"]:
        raise RuntimeError("Passerelle SMS non configurée")
    headers = {"Authorization": f"Bearer {get_setting('sms_gateway_token')}"}
    r = httpx.get(f"{cfg['gateway_url']}/health", headers=headers, timeout=5)
    if r.status_code >= 300:
        raise RuntimeError(f"Passerelle SMS HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError("La passerelle SMS ne répond pas correctement")
    return data


def _render(text: str, prospect: dict) -> str:
    values = {
        "entreprise": prospect.get("company_name") or "",
        "contact": prospect.get("contact_name") or "",
        "ville": prospect.get("city") or "",
        "secteur": prospect.get("category") or "",
        "email": prospect.get("email") or "",
        "telephone": prospect.get("phone") or "",
    }
    out = text
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _normalize_phone(value: str) -> str:
    raw = (value or "").strip()
    plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "33" + digits[1:]
    if not digits or len(digits) < 8:
        return ""
    return "+" + digits if plus or digits.startswith("33") else "+" + digits


def create_campaign(name: str, subject: str, body: str, category: str = "", city: str = "", min_score: int = 0, mode: str = "simulation", scheduled_at: str = "") -> int:
    init_db()
    if mode not in {"simulation", "reel"}:
        raise ValueError("Mode campagne invalide")
    con = connect()
    cur = con.execute(
        "INSERT INTO campaigns(name,subject,body,category,city,min_score,mode,scheduled_at,status) VALUES(?,?,?,?,?,?,?,?,?)",
        (name.strip(), subject.strip(), body.strip(), category.strip(), city.strip(), int(min_score or 0), mode, scheduled_at or None, "planifiee" if scheduled_at else "brouillon"),
    )
    cid = cur.lastrowid
    where = ["lead_score>=?"]
    params = [int(min_score or 0)]
    if category:
        aliases = CATEGORY_ALIASES.get(category, [category])
        where.append("lower(coalesce(category,'')) IN (" + ",".join("?" for _ in aliases) + ")")
        params.extend([x.lower() for x in aliases])
    if city:
        where.append("lower(coalesce(city,'')) LIKE lower(?)")
        params.append(f"%{city}%")
    prospects = con.execute(
        "SELECT * FROM prospects WHERE " + " AND ".join(where) + " ORDER BY lead_score DESC,id",
        tuple(params),
    ).fetchall()
    for p in prospects:
        channel = "email" if (p["email"] or "").strip() else ("sms" if (p["phone"] or "").strip() else "none")
        con.execute(
            "INSERT OR IGNORE INTO campaign_recipients(campaign_id,prospect_id,channel,status) VALUES(?,?,?,?)",
            (cid, p["id"], channel, "pending" if channel != "none" else "skipped"),
        )
    con.commit()
    con.close()
    return int(cid)


def create_campaign_for_selection(
    name: str,
    subject: str,
    body: str,
    prospect_ids: list[int],
    channel: str = "auto",
    mode: str = "simulation",
    scheduled_at: str = "",
) -> int:
    init_db()
    if mode not in {"simulation", "reel"}:
        raise ValueError("Mode campagne invalide")
    if channel not in {"auto", "email", "sms"}:
        raise ValueError("Canal invalide")
    ids = list(dict.fromkeys(int(pid) for pid in prospect_ids if int(pid) > 0))[:500]
    if not ids:
        raise ValueError("Aucun prospect sélectionné")
    con = connect()
    cur = con.execute(
        "INSERT INTO campaigns(name,subject,body,category,city,min_score,mode,scheduled_at,status) VALUES(?,?,?,?,?,?,?,?,?)",
        (name.strip(), subject.strip(), body.strip(), "", "", 0, mode, scheduled_at or None, "planifiee" if scheduled_at else "brouillon"),
    )
    cid = int(cur.lastrowid)
    marks = ",".join("?" for _ in ids)
    prospects = con.execute(f"SELECT * FROM prospects WHERE id IN ({marks}) ORDER BY id", tuple(ids)).fetchall()
    for p in prospects:
        selected = channel
        if selected == "auto":
            selected = "email" if (p["email"] or "").strip() else ("sms" if (p["phone"] or "").strip() else "none")
        available = bool((p["email"] if selected == "email" else p["phone"] if selected == "sms" else "").strip())
        status = "pending" if available else "skipped"
        con.execute(
            "INSERT OR IGNORE INTO campaign_recipients(campaign_id,prospect_id,channel,status) VALUES(?,?,?,?)",
            (cid, p["id"], selected, status),
        )
    con.commit()
    con.close()
    return cid


def schedule_campaign(campaign_id: int, scheduled_at: str, mode: str) -> None:
    if mode not in {"simulation", "reel"}:
        raise ValueError("Mode invalide")
    con = connect()
    con.execute("UPDATE campaigns SET scheduled_at=?,mode=?,status='planifiee' WHERE id=?", (scheduled_at, mode, campaign_id))
    con.commit()
    con.close()


def _send_email(prospect: dict, subject: str, body: str) -> None:
    cfg = smtp_status()
    oauth_cfg = gmail_status()
    if oauth_cfg["configured"]:
        try:
            gmail_oauth.send_email(
                to=prospect["email"],
                subject=subject,
                body=body,
                from_email=cfg["from_email"] or oauth_cfg["account"],
                from_name=cfg["from_name"],
            )
            return
        except Exception as oauth_error:
            if not cfg["configured"]:
                raise RuntimeError(f"Échec Gmail OAuth : {oauth_error}") from oauth_error

    if not cfg["configured"]:
        raise RuntimeError("Email non configuré : Gmail OAuth et SMTP sont indisponibles")
    msg = EmailMessage()
    msg["From"] = formataddr((cfg["from_name"], cfg["from_email"]))
    msg["To"] = prospect["email"]
    msg["Subject"] = subject
    msg.set_content(body)
    username, password = cfg["username"], get_setting("smtp_password")
    server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30, context=ssl.create_default_context()) if cfg["security"] == "ssl" else smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
    try:
        server.ehlo()
        if cfg["security"] == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if username:
            server.login(username, password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _sms_sent_today(con) -> int:
    row = con.execute("SELECT count(*) FROM communications WHERE channel='sms' AND status='sent' AND date(created_at,'localtime')=date('now','localtime')").fetchone()
    return int(row[0] if row else 0)


def _send_sms(prospect: dict, body: str) -> None:
    cfg = sms_status()
    if not cfg["configured"]:
        raise RuntimeError("Passerelle SMS du téléphone non configurée")
    phone = _normalize_phone(prospect.get("phone") or "")
    if not phone:
        raise RuntimeError("Téléphone invalide")
    token = get_setting("sms_gateway_token")
    r = httpx.post(
        f"{cfg['gateway_url']}/sms",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"to": phone, "message": body, "sender": SMS_SENDER_NUMBER},
        timeout=30,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Passerelle SMS HTTP {r.status_code}: {r.text[:300]}")
    try:
        data = r.json()
    except Exception:
        data = {}
    if data and not data.get("ok", True):
        raise RuntimeError(str(data.get("error") or "Échec d'envoi SMS"))


def _log(con, prospect_id: int, campaign_id: int, channel: str, status: str, recipient: str, subject: str, body: str, error: str = ""):
    con.execute(
        "INSERT INTO communications(prospect_id,campaign_id,channel,status,recipient,subject,body,error) VALUES(?,?,?,?,?,?,?,?)",
        (prospect_id, campaign_id, channel, status, recipient, subject, body, error),
    )


def run_campaign(campaign_id: int, force_mode: str | None = None, max_items: int = 500) -> dict:
    init_db()
    con = connect()
    camp = con.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    if not camp:
        con.close()
        raise ValueError("Campagne introuvable")
    camp = dict(camp)
    mode = force_mode or camp["mode"]
    if mode not in {"simulation", "reel"}:
        con.close()
        raise ValueError("Mode invalide")
    con.execute("UPDATE campaigns SET status='en_cours',started_at=coalesce(started_at,CURRENT_TIMESTAMP) WHERE id=?", (campaign_id,))
    con.commit()
    recips = con.execute(
        "SELECT cr.*,p.* FROM campaign_recipients cr JOIN prospects p ON p.id=cr.prospect_id WHERE cr.campaign_id=? AND cr.status='pending' ORDER BY cr.id LIMIT ?",
        (campaign_id, max_items),
    ).fetchall()
    stats = {"processed": 0, "sent": 0, "simulated": 0, "errors": 0, "skipped": 0, "email": 0, "sms": 0}
    sms_cfg = sms_status()
    for row in recips:
        p = dict(row)
        rid = row["id"]
        channel = row["channel"]
        subject, body = _render(camp["subject"], p), _render(camp["body"], p)
        recipient = p.get("email") if channel == "email" else p.get("phone")
        stats["processed"] += 1
        try:
            if channel not in {"email", "sms"}:
                raise RuntimeError("Aucun canal disponible")
            if mode == "simulation":
                status = "simulated"
                stats["simulated"] += 1
            else:
                if channel == "email":
                    _send_email(p, subject, body)
                else:
                    if _sms_sent_today(con) >= sms_cfg["daily_limit"]:
                        raise RuntimeError(f"Limite SMS quotidienne atteinte ({sms_cfg['daily_limit']})")
                    _send_sms(p, body)
                status = "sent"
                stats["sent"] += 1
            stats[channel] += 1
            con.execute(
                "UPDATE campaign_recipients SET status=?,attempts=attempts+1,last_error=NULL,sent_at=CASE WHEN ?='sent' THEN CURRENT_TIMESTAMP ELSE sent_at END WHERE id=?",
                (status, status, rid),
            )
            _log(con, p["prospect_id"], campaign_id, channel, status, recipient or "", subject, body)
            con.commit()
            if mode == "reel" and channel == "sms" and sms_cfg["delay_seconds"] > 0:
                time.sleep(sms_cfg["delay_seconds"])
        except Exception as exc:
            err = str(exc)[:800]
            con.execute("UPDATE campaign_recipients SET status='error',attempts=attempts+1,last_error=? WHERE id=?", (err, rid))
            _log(con, p["prospect_id"], campaign_id, channel, "error", recipient or "", subject, body, err)
            con.commit()
            stats["errors"] += 1
    pending = con.execute("SELECT count(*) FROM campaign_recipients WHERE campaign_id=? AND status='pending'", (campaign_id,)).fetchone()[0]
    if pending == 0:
        con.execute("UPDATE campaigns SET status='terminee',finished_at=CURRENT_TIMESTAMP WHERE id=?", (campaign_id,))
    con.commit()
    con.close()
    return stats | {"campaign_id": campaign_id, "mode": mode, "pending": pending}


def retry_errors(campaign_id: int) -> int:
    con = connect()
    cur = con.execute("UPDATE campaign_recipients SET status='pending',last_error=NULL WHERE campaign_id=? AND status='error'", (campaign_id,))
    con.execute("UPDATE campaigns SET status='brouillon',finished_at=NULL WHERE id=?", (campaign_id,))
    con.commit()
    n = cur.rowcount
    con.close()
    return n


def process_due_campaigns() -> list[dict]:
    init_db()
    due = rows("SELECT id FROM campaigns WHERE status='planifiee' AND scheduled_at IS NOT NULL AND datetime(scheduled_at)<=datetime('now','localtime') ORDER BY scheduled_at")
    results = []
    for c in due:
        try:
            results.append(run_campaign(c["id"]))
        except Exception as exc:
            results.append({"campaign_id": c["id"], "error": str(exc)})
    return results


def outreach_summary() -> dict:
    init_db()
    def count(where="1=1"):
        r = one(f"SELECT count(*) n FROM communications WHERE {where}")
        return r["n"] if r else 0
    return {
        "campaigns": one("SELECT count(*) n FROM campaigns")["n"],
        "scheduled": one("SELECT count(*) n FROM campaigns WHERE status='planifiee'")["n"],
        "sent": count("status='sent'"),
        "simulated": count("status='simulated'"),
        "errors": count("status='error'"),
    }


def start_scheduler(stop_predicate=lambda: False, interval_seconds: int = 15) -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    def loop():
        while not stop_predicate():
            try:
                process_due_campaigns()
            except Exception:
                pass
            for _ in range(max(1, interval_seconds)):
                if stop_predicate():
                    return
                time.sleep(1)
    threading.Thread(target=loop, name="fewura-outreach-scheduler", daemon=True).start()
