import csv
from pathlib import Path
from .db import init_db, rows, one, execute, connect
from .paths import exports_dir
from .prospect_engine import search_businesses, fingerprint, lead_score


def function_tool(fn):
    return fn


def _merge_prospect_from_fewura(p: dict) -> tuple[int, bool]:
    init_db()
    p = dict(p)
    p["fingerprint"] = p.get("fingerprint") or fingerprint(p)
    p["lead_score"] = int(p.get("lead_score") or lead_score(p))
    p["confidence"] = float(p.get("confidence") or round(p["lead_score"] / 100, 2))
    con = connect()
    old = con.execute("SELECT * FROM prospects WHERE fingerprint=?", (p["fingerprint"],)).fetchone()
    if old is None:
        old = con.execute(
            "SELECT * FROM prospects WHERE lower(trim(company_name))=lower(trim(?)) AND lower(trim(coalesce(city,'')))=lower(trim(?)) ORDER BY id LIMIT 1",
            (p.get("company_name") or "", p.get("city") or ""),
        ).fetchone()
    fields = ["company_name", "email", "phone", "website", "city", "category", "lead_score", "address", "postal_code", "region", "country", "lat", "lon", "contact_form_url", "source_url", "source_type", "confidence", "fingerprint", "siren", "siret", "activity_code"]
    if old:
        old = dict(old)
        values = []
        for field in fields:
            fresh = p.get(field)
            current = old.get(field)
            value = max(int(current or 0), int(fresh or 0)) if field == "lead_score" else (fresh if fresh not in (None, "") else current)
            values.append(value)
        assignments = ",".join(f"{field}=?" for field in fields)
        con.execute(f"UPDATE prospects SET {assignments}, source='fewura-prospect', last_checked_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?", values + [old["id"]])
        pid, created = old["id"], False
    else:
        columns = fields + ["source", "status"]
        values = [p.get(field) for field in fields] + ["fewura-prospect", "nouveau"]
        con.execute(f"INSERT INTO prospects({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", values)
        pid, created = con.execute("SELECT last_insert_rowid()").fetchone()[0], True
    con.commit(); con.close()
    return int(pid), created


@function_tool
def prospect_search_import(zone: str, category: str = "all", radius_km: int = 20, max_results: int = 50, enrich: bool = True, contact_mode: str = "either") -> dict:
    found = search_businesses(zone, category, radius_km, max_results, enrich=enrich, contact_mode=contact_mode)
    created = updated = 0; ids = []
    for prospect in found:
        pid, is_created = _merge_prospect_from_fewura(prospect)
        ids.append(pid); created += int(is_created); updated += int(not is_created)
    return {"ok": True, "engine": "FEWURA PROSPECT", "zone": zone, "category": category, "found": len(found), "created": created, "updated": updated, "prospect_ids": ids}


@function_tool
def list_prospects(limit: int = 50) -> list[dict]:
    init_db(); limit = max(1, min(limit, 200)); return rows("SELECT * FROM prospects WHERE coalesce(email,'')<>'' OR coalesce(phone,'')<>'' ORDER BY id DESC LIMIT ?", (limit,))


@function_tool
def search_prospects(query: str, limit: int = 50) -> list[dict]:
    init_db(); q = f"%{query.strip()}%"; limit = max(1, min(limit, 200))
    return rows("SELECT * FROM prospects WHERE (coalesce(email,'')<>'' OR coalesce(phone,'')<>'') AND (company_name LIKE ? OR contact_name LIKE ? OR email LIKE ? OR phone LIKE ? OR city LIKE ? OR category LIKE ?) ORDER BY lead_score DESC, id DESC LIMIT ?", (q,q,q,q,q,q,limit))


@function_tool
def create_prospect(company_name: str, contact_name: str = "", email: str = "", phone: str = "", website: str = "", city: str = "", category: str = "", source: str = "local") -> dict:
    init_db()
    if not company_name.strip(): return {"ok": False, "error": "company_name requis"}
    candidate = {"company_name": company_name.strip(), "email": email.strip(), "phone": phone.strip(), "website": website.strip(), "city": city.strip(), "category": category.strip()}
    fp = fingerprint(candidate); existing = one("SELECT * FROM prospects WHERE fingerprint=?", (fp,))
    if existing: return {"ok": False, "error": "Prospect déjà présent", "prospect": existing}
    pid = execute("INSERT INTO prospects(company_name,contact_name,email,phone,website,city,category,source,fingerprint,lead_score) VALUES(?,?,?,?,?,?,?,?,?,?)", (company_name.strip(), contact_name.strip(), email.strip(), phone.strip(), website.strip(), city.strip(), category.strip(), source.strip(), fp, lead_score(candidate)))
    return {"ok": True, "prospect": one("SELECT * FROM prospects WHERE id=?", (pid,))}


@function_tool
def update_prospect_status(prospect_id: int, status: str) -> dict:
    init_db(); allowed = {"nouveau","a_contacter","contacte","qualifie","proposition","gagne","perdu","archive"}
    if status not in allowed: return {"ok": False, "error": f"Statut invalide. Valeurs: {sorted(allowed)}"}
    if not one("SELECT id FROM prospects WHERE id=?", (prospect_id,)): return {"ok": False, "error": "Prospect introuvable"}
    execute("UPDATE prospects SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, prospect_id)); return {"ok": True, "prospect": one("SELECT * FROM prospects WHERE id=?", (prospect_id,))}


@function_tool
def add_note(prospect_id: int, body: str) -> dict:
    init_db()
    if not one("SELECT id FROM prospects WHERE id=?", (prospect_id,)): return {"ok": False, "error": "Prospect introuvable"}
    nid = execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)", (prospect_id, body.strip())); return {"ok": True, "note": one("SELECT * FROM notes WHERE id=?", (nid,))}


@function_tool
def add_task(title: str, prospect_id: int | None = None, due_at: str = "") -> dict:
    init_db()
    if prospect_id is not None and not one("SELECT id FROM prospects WHERE id=?", (prospect_id,)): return {"ok": False, "error": "Prospect introuvable"}
    tid = execute("INSERT INTO tasks(prospect_id,title,due_at) VALUES(?,?,?)", (prospect_id, title.strip(), due_at.strip() or None)); return {"ok": True, "task": one("SELECT * FROM tasks WHERE id=?", (tid,))}


@function_tool
def complete_task(task_id: int) -> dict:
    init_db()
    if not one("SELECT id FROM tasks WHERE id=?", (task_id,)): return {"ok": False, "error": "Tâche introuvable"}
    execute("UPDATE tasks SET status='terminee' WHERE id=?", (task_id,)); return {"ok": True, "task": one("SELECT * FROM tasks WHERE id=?", (task_id,))}


@function_tool
def crm_summary() -> dict:
    init_db(); total = one("SELECT count(*) n FROM prospects")["n"]; with_email = one("SELECT count(*) n FROM prospects WHERE email IS NOT NULL AND trim(email)<>''")["n"]; with_phone = one("SELECT count(*) n FROM prospects WHERE phone IS NOT NULL AND trim(phone)<>''")["n"]; open_tasks = one("SELECT count(*) n FROM tasks WHERE status<>'terminee'")["n"]; statuses = rows("SELECT status, count(*) n FROM prospects GROUP BY status ORDER BY n DESC"); sourced = one("SELECT count(*) n FROM prospects WHERE source='fewura-prospect'")["n"]
    return {"prospects": total, "fewura_prospect": sourced, "emails": with_email, "phones": with_phone, "open_tasks": open_tasks, "statuses": statuses}


@function_tool
def export_prospects_csv() -> dict:
    init_db(); data = rows("SELECT * FROM prospects ORDER BY id"); path: Path = exports_dir() / "prospects.csv"; fields = ["id","company_name","contact_name","email","phone","website","address","postal_code","city","category","status","lead_score","confidence","source","source_url","source_type","created_at","updated_at","last_checked_at"]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(data)
    return {"ok": True, "count": len(data), "path": str(path)}


@function_tool
def delete_prospect(prospect_id: int, confirmation: str) -> dict:
    init_db()
    if confirmation != "SUPPRIMER": return {"ok": False, "error": "Confirmation explicite requise: SUPPRIMER"}
    prospect = one("SELECT * FROM prospects WHERE id=?", (prospect_id,))
    if not prospect: return {"ok": False, "error": "Prospect introuvable"}
    con = connect(); con.execute("DELETE FROM prospects WHERE id=?", (prospect_id,)); con.commit(); con.close(); return {"ok": True, "deleted": {"id": prospect_id, "company_name": prospect["company_name"]}}


TOOLS = [prospect_search_import,list_prospects,search_prospects,create_prospect,update_prospect_status,add_note,add_task,complete_task,crm_summary,export_prospects_csv,delete_prospect]

