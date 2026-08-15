import os
from pathlib import Path

os.environ["FEWURA_CRM_DATA_DIR"] = str(Path.cwd() / ".testdata")

from fewura_crm.db import init_db, execute, one


def test_schema_and_crud():
    init_db()
    pid = execute(
        "INSERT INTO prospects(company_name,email,city) VALUES(?,?,?)",
        ("Test Toulouse", "contact@test.fr", "Toulouse"),
    )
    p = one("SELECT * FROM prospects WHERE id=?", (pid,))
    assert p["company_name"] == "Test Toulouse"
    assert p["email"] == "contact@test.fr"
    execute("UPDATE prospects SET status='qualifie' WHERE id=?", (pid,))
    assert one("SELECT status FROM prospects WHERE id=?", (pid,))["status"] == "qualifie"


def test_notes_and_tasks():
    init_db()
    pid = execute("INSERT INTO prospects(company_name) VALUES(?)", ("Test Notes",))
    nid = execute("INSERT INTO notes(prospect_id,body) VALUES(?,?)", (pid, "Rappeler lundi"))
    tid = execute("INSERT INTO tasks(prospect_id,title) VALUES(?,?)", (pid, "Relance"))
    assert one("SELECT body FROM notes WHERE id=?", (nid,))["body"] == "Rappeler lundi"
    assert one("SELECT title FROM tasks WHERE id=?", (tid,))["title"] == "Relance"
