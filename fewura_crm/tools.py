import csv
from pathlib import Path
from agents import function_tool
from .db import init_db, rows, one, execute, connect
from .paths import exports_dir


@function_tool
def list_prospects(limit: int = 50) -> list[dict]:
    """Liste les prospects CRM les plus récents."""
    init_db()
    limit = max(1, min(limit, 200))
    return rows("SELECT * FROM prospects ORDER BY id DESC LIMIT ?", (limit,))


@function_tool
def search_prospects(query: str, limit: int = 50) -> list[dict]:
    """Recherche des prospects par entreprise, contact, email, téléphone, ville ou catégorie."""
    init_db()
    q = f"%{query.strip()}%"
    limit = max(1, min(limit, 200))
    return rows(
        """SELECT * FROM prospects WHERE
        company_name LIKE ? OR contact_name LIKE ? OR email LIKE ? OR phone LIKE ?
        OR city LIKE ? OR category LIKE ? ORDER BY lead_score DESC, id DESC LIMIT ?""",
        (q, q, q, q, q, q, limit),
    )


@function_tool
def create_prospect(company_name: str, contact_name: str = "", email: str = "", phone: str = "", website: str = "", city: str = "", category: str = "", source: str = "agent") -> dict:
    """Crée un prospect CRM."""
    init_db()
    if not company_name.strip():
        return {"ok": False, "error": "company_name requis"}
    pid = execute(
        "INSERT INTO prospects(company_name,contact_name,email,phone,website,city,category,source) VALUES(?,?,?,?,?,?,?,?)",
        (company_name.strip(), contact_name.strip(), email.strip(), phone.strip(), website.strip(), city.strip(), category.strip(), source.strip()),
    )
    return {"ok": True, "prospect": one("SELECT * FROM prospects WHERE id=?", (pid,))}


@function_tool
def update_prospect_status(prospect_id: int, status: str) -> dict:
    """Met à jour le statut commercial d'un prospect."""
    init_db()
    allowed = {"nouveau", "a_contacter", "contacte", "qualifie", "proposition", "gagne", "perdu", "archive"}
    if status not in allowed:
        return {"ok": False, "error": f"Statut invalide. Valeurs: {sorted(allowed)}"}
    if not one("SELECT id FROM prospects WHERE id=?", (prospect_id,)):
        return {"ok": False, "error": "Prospect introuvable"}
    execute("UPDATE prospects SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, prospect_id))
    return {"ok": True, "prospect": one("SELECT * FROM prospects WHERE id=?", (prospect_id,))}


@function_tool
def add_note(prospect_id: int, body: str) -> dict:
    """Ajoute une note à un prospect."""
    init_db()
    if not one("SELECT id FROM prospects WHERE id=?", (prospect_id,)):
        return {"ok": False, "error": "Prospect introuvable"}
    nid = execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)", (prospect_id, body.strip()))
    return {"ok": True, "note": one("SELECT * FROM notes WHERE id=?", (nid,))}


@function_tool
def add_task(title: str, prospect_id: int | None = None, due_at: str = "") -> dict:
    """Crée une tâche CRM, éventuellement liée à un prospect."""
    init_db()
    if prospect_id is not None and not one("SELECT id FROM prospects WHERE id=?", (prospect_id,)):
        return {"ok": False, "error": "Prospect introuvable"}
    tid = execute("INSERT INTO tasks(prospect_id,title,due_at) VALUES(?,?,?)", (prospect_id, title.strip(), due_at.strip() or None))
    return {"ok": True, "task": one("SELECT * FROM tasks WHERE id=?", (tid,))}


@function_tool
def complete_task(task_id: int) -> dict:
    """Marque une tâche CRM comme terminée."""
    init_db()
    if not one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        return {"ok": False, "error": "Tâche introuvable"}
    execute("UPDATE tasks SET status='terminee' WHERE id=?", (task_id,))
    return {"ok": True, "task": one("SELECT * FROM tasks WHERE id=?", (task_id,))}


@function_tool
def crm_summary() -> dict:
    """Retourne les indicateurs principaux du CRM."""
    init_db()
    total = one("SELECT count(*) n FROM prospects")["n"]
    with_email = one("SELECT count(*) n FROM prospects WHERE email IS NOT NULL AND trim(email)<>''")["n"]
    with_phone = one("SELECT count(*) n FROM prospects WHERE phone IS NOT NULL AND trim(phone)<>''")["n"]
    open_tasks = one("SELECT count(*) n FROM tasks WHERE status<>'terminee'")["n"]
    statuses = rows("SELECT status, count(*) n FROM prospects GROUP BY status ORDER BY n DESC")
    return {"prospects": total, "emails": with_email, "phones": with_phone, "open_tasks": open_tasks, "statuses": statuses}


@function_tool
def export_prospects_csv() -> dict:
    """Exporte tous les prospects dans un CSV local et retourne son chemin."""
    init_db()
    data = rows("SELECT * FROM prospects ORDER BY id")
    path: Path = exports_dir() / "prospects.csv"
    fields = ["id", "company_name", "contact_name", "email", "phone", "website", "city", "category", "status", "lead_score", "source", "created_at", "updated_at"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
    return {"ok": True, "count": len(data), "path": str(path)}


@function_tool
def delete_prospect(prospect_id: int, confirmation: str) -> dict:
    """Supprime un prospect uniquement si confirmation vaut exactement SUPPRIMER."""
    init_db()
    if confirmation != "SUPPRIMER":
        return {"ok": False, "error": "Confirmation explicite requise: SUPPRIMER"}
    prospect = one("SELECT * FROM prospects WHERE id=?", (prospect_id,))
    if not prospect:
        return {"ok": False, "error": "Prospect introuvable"}
    con = connect()
    con.execute("DELETE FROM prospects WHERE id=?", (prospect_id,))
    con.commit()
    con.close()
    return {"ok": True, "deleted": {"id": prospect_id, "company_name": prospect["company_name"]}}


TOOLS = [
    list_prospects,
    search_prospects,
    create_prospect,
    update_prospect_status,
    add_note,
    add_task,
    complete_task,
    crm_summary,
    export_prospects_csv,
    delete_prospect,
]
