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

_scheduler_started = False
_scheduler_lock = threading.Lock()

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
    init_db(); row = one("SELECT value FROM settings WHERE key=?", (key,)); return row["value"] if row else default


def set_settings(values: dict[str, str]) -> None:
    init_db(); con = connect()
    for key, value in values.items():
        con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value or "")))
    con.commit(); con.close()


def smtp_status() -> dict:
    return {"configured": bool(get_setting("smtp_host") and get_setting("smtp_from_email")), "host": get_setting("smtp_host"), "port": int(get_setting("smtp_port", "587") or 587), "username": get_setting("smtp_username"), "from_email": get_setting("smtp_from_email"), "from_name": get_setting("smtp_from_name", "FEWURA CRM"), "security": get_setting("smtp_security", "starttls")}


def whatsapp_status() -> dict:
    return {"configured": bool(get_setting("whatsapp_token") and get_setting("whatsapp_phone_number_id")), "phone_number_id": get_setting("whatsapp_phone_number_id")}


def save_smtp(host: str, port: int, username: str, password: str, from_email: str, from_name: str, security: str) -> None:
    if security not in {"starttls", "ssl", "none"}: raise ValueError("Sécurité SMTP invalide")
    values={"smtp_host":host.strip(),"smtp_port":str(int(port)),"smtp_username":username.strip(),"smtp_from_email":from_email.strip(),"smtp_from_name":from_name.strip() or "FEWURA CRM","smtp_security":security}
    if password: values["smtp_password"] = password
    set_settings(values)


def save_whatsapp(phone_number_id: str, token: str) -> None:
    values={"whatsapp_phone_number_id":phone_number_id.strip()}
    if token: values["whatsapp_token"] = token.strip()
    set_settings(values)


def _render(text: str, prospect: dict) -> str:
    values={"entreprise":prospect.get("company_name") or "","contact":prospect.get("contact_name") or "","ville":prospect.get("city") or "","secteur":prospect.get("category") or "","email":prospect.get("email") or "","telephone":prospect.get("phone") or ""}
    out=text
    for key,value in values.items(): out=out.replace("{"+key+"}",str(value))
    return out


def _normalize_phone(value: str) -> str:
    digits=re.sub(r"\D","",value or "")
    if digits.startswith("00"): digits=digits[2:]
    if digits.startswith("0") and len(digits)==10: digits="33"+digits[1:]
    return digits


def create_campaign(name: str, subject: str, body: str, category: str = "", city: str = "", min_score: int = 0, mode: str = "simulation", scheduled_at: str = "") -> int:
    init_db()
    if mode not in {"simulation","reel"}: raise ValueError("Mode campagne invalide")
    con=connect(); cur=con.execute("INSERT INTO campaigns(name,subject,body,category,city,min_score,mode,scheduled_at,status) VALUES(?,?,?,?,?,?,?,?,?)",(name.strip(),subject.strip(),body.strip(),category.strip(),city.strip(),int(min_score or 0),mode,scheduled_at or None,"planifiee" if scheduled_at else "brouillon")); cid=cur.lastrowid
    where=["lead_score>=?"]; params=[int(min_score or 0)]
    if category:
        aliases=CATEGORY_ALIASES.get(category,[category])
        where.append("lower(coalesce(category,'')) IN ("+",".join("?" for _ in aliases)+")"); params.extend([x.lower() for x in aliases])
    if city: where.append("lower(coalesce(city,'')) LIKE lower(?)"); params.append(f"%{city}%")
    prospects=con.execute("SELECT * FROM prospects WHERE "+" AND ".join(where)+" ORDER BY lead_score DESC,id",tuple(params)).fetchall()
    for p in prospects:
        channel="email" if (p["email"] or "").strip() else ("whatsapp" if (p["phone"] or "").strip() else "none")
        con.execute("INSERT OR IGNORE INTO campaign_recipients(campaign_id,prospect_id,channel,status) VALUES(?,?,?,?)",(cid,p["id"],channel,"pending" if channel!="none" else "skipped"))
    con.commit(); con.close(); return int(cid)


def schedule_campaign(campaign_id: int, scheduled_at: str, mode: str) -> None:
    if mode not in {"simulation","reel"}: raise ValueError("Mode invalide")
    con=connect(); con.execute("UPDATE campaigns SET scheduled_at=?,mode=?,status='planifiee' WHERE id=?",(scheduled_at,mode,campaign_id)); con.commit(); con.close()


def _send_email(prospect: dict, subject: str, body: str) -> None:
    cfg=smtp_status()
    if not cfg["configured"]: raise RuntimeError("SMTP non configuré")
    msg=EmailMessage(); msg["From"]=formataddr((cfg["from_name"],cfg["from_email"])); msg["To"]=prospect["email"]; msg["Subject"]=subject; msg.set_content(body)
    username,password=cfg["username"],get_setting("smtp_password")
    server=smtplib.SMTP_SSL(cfg["host"],cfg["port"],timeout=30,context=ssl.create_default_context()) if cfg["security"]=="ssl" else smtplib.SMTP(cfg["host"],cfg["port"],timeout=30)
    try:
        server.ehlo()
        if cfg["security"]=="starttls": server.starttls(context=ssl.create_default_context()); server.ehlo()
        if username: server.login(username,password)
        server.send_message(msg)
    finally:
        try: server.quit()
        except Exception: pass


def _send_whatsapp(prospect: dict, body: str) -> None:
    cfg=whatsapp_status()
    if not cfg["configured"]: raise RuntimeError("WhatsApp Cloud non configuré")
    phone=_normalize_phone(prospect.get("phone") or "")
    if not phone: raise RuntimeError("Téléphone invalide")
    url=f"https://graph.facebook.com/v23.0/{cfg['phone_number_id']}/messages"
    payload={"messaging_product":"whatsapp","to":phone,"type":"text","text":{"preview_url":False,"body":body}}
    r=httpx.post(url,headers={"Authorization":f"Bearer {get_setting('whatsapp_token')}","Content-Type":"application/json"},json=payload,timeout=30)
    if r.status_code>=300: raise RuntimeError(f"WhatsApp HTTP {r.status_code}: {r.text[:300]}")


def _log(con, prospect_id: int, campaign_id: int, channel: str, status: str, recipient: str, subject: str, body: str, error: str = ""):
    con.execute("INSERT INTO communications(prospect_id,campaign_id,channel,status,recipient,subject,body,error) VALUES(?,?,?,?,?,?,?,?)",(prospect_id,campaign_id,channel,status,recipient,subject,body,error))


def run_campaign(campaign_id: int, force_mode: str | None = None, max_items: int = 500) -> dict:
    init_db(); con=connect(); camp=con.execute("SELECT * FROM campaigns WHERE id=?",(campaign_id,)).fetchone()
    if not camp: con.close(); raise ValueError("Campagne introuvable")
    camp=dict(camp); mode=force_mode or camp["mode"]
    if mode not in {"simulation","reel"}: con.close(); raise ValueError("Mode invalide")
    con.execute("UPDATE campaigns SET status='en_cours',started_at=coalesce(started_at,CURRENT_TIMESTAMP) WHERE id=?",(campaign_id,)); con.commit()
    recips=con.execute("SELECT cr.*,p.* FROM campaign_recipients cr JOIN prospects p ON p.id=cr.prospect_id WHERE cr.campaign_id=? AND cr.status='pending' ORDER BY cr.id LIMIT ?",(campaign_id,max_items)).fetchall()
    stats={"processed":0,"sent":0,"simulated":0,"errors":0,"skipped":0,"email":0,"whatsapp":0}
    for row in recips:
        p=dict(row); rid=row["id"]; channel=row["channel"]; subject,body=_render(camp["subject"],p),_render(camp["body"],p); recipient=p.get("email") if channel=="email" else p.get("phone"); stats["processed"]+=1
        try:
            if channel not in {"email","whatsapp"}: raise RuntimeError("Aucun canal disponible")
            if mode=="simulation": status="simulated"; stats["simulated"]+=1
            else:
                if channel=="email": _send_email(p,subject,body)
                else: _send_whatsapp(p,body)
                status="sent"; stats["sent"]+=1
            stats[channel]+=1
            con.execute("UPDATE campaign_recipients SET status=?,attempts=attempts+1,last_error=NULL,sent_at=CASE WHEN ?='sent' THEN CURRENT_TIMESTAMP ELSE sent_at END WHERE id=?",(status,status,rid)); _log(con,p["prospect_id"],campaign_id,channel,status,recipient or "",subject,body)
        except Exception as exc:
            err=str(exc)[:800]; con.execute("UPDATE campaign_recipients SET status='error',attempts=attempts+1,last_error=? WHERE id=?",(err,rid)); _log(con,p["prospect_id"],campaign_id,channel,"error",recipient or "",subject,body,err); stats["errors"]+=1
        con.commit()
    pending=con.execute("SELECT count(*) FROM campaign_recipients WHERE campaign_id=? AND status='pending'",(campaign_id,)).fetchone()[0]
    if pending==0: con.execute("UPDATE campaigns SET status='terminee',finished_at=CURRENT_TIMESTAMP WHERE id=?",(campaign_id,))
    con.commit(); con.close(); return stats|{"campaign_id":campaign_id,"mode":mode,"pending":pending}


def retry_errors(campaign_id: int) -> int:
    con=connect(); cur=con.execute("UPDATE campaign_recipients SET status='pending',last_error=NULL WHERE campaign_id=? AND status='error'",(campaign_id,)); con.execute("UPDATE campaigns SET status='brouillon',finished_at=NULL WHERE id=?",(campaign_id,)); con.commit(); n=cur.rowcount; con.close(); return n


def process_due_campaigns() -> list[dict]:
    init_db(); due=rows("SELECT id FROM campaigns WHERE status='planifiee' AND scheduled_at IS NOT NULL AND datetime(scheduled_at)<=datetime('now','localtime') ORDER BY scheduled_at"); results=[]
    for c in due:
        try: results.append(run_campaign(c["id"]))
        except Exception as exc: results.append({"campaign_id":c["id"],"error":str(exc)})
    return results


def outreach_summary() -> dict:
    init_db()
    def count(where="1=1"):
        r=one(f"SELECT count(*) n FROM communications WHERE {where}"); return r["n"] if r else 0
    return {"campaigns":one("SELECT count(*) n FROM campaigns")["n"],"scheduled":one("SELECT count(*) n FROM campaigns WHERE status='planifiee'")["n"],"sent":count("status='sent'"),"simulated":count("status='simulated'"),"errors":count("status='error'")}


def start_scheduler(stop_predicate=lambda: False, interval_seconds: int = 15) -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started: return
        _scheduler_started=True
    def loop():
        while not stop_predicate():
            try: process_due_campaigns()
            except Exception: pass
            for _ in range(max(1,interval_seconds)):
                if stop_predicate(): return
                time.sleep(1)
    threading.Thread(target=loop,name="fewura-outreach-scheduler",daemon=True).start()
