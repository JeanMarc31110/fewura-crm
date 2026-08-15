import sqlite3
from .paths import database_path


def connect():
    con = sqlite3.connect(database_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _ensure_column(con, table: str, column: str, definition: str) -> None:
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    con = connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS prospects(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company_name TEXT NOT NULL,
      contact_name TEXT,
      email TEXT,
      phone TEXT,
      website TEXT,
      city TEXT,
      category TEXT,
      status TEXT DEFAULT 'nouveau',
      lead_score INTEGER DEFAULT 0,
      source TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS notes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      prospect_id INTEGER NOT NULL,
      body TEXT NOT NULL,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(prospect_id) REFERENCES prospects(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS tasks(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      prospect_id INTEGER,
      title TEXT NOT NULL,
      due_at TEXT,
      status TEXT DEFAULT 'a_faire',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(prospect_id) REFERENCES prospects(id) ON DELETE SET NULL
    );
    """)
    for column, definition in [
        ("address", "TEXT"), ("postal_code", "TEXT"), ("region", "TEXT"),
        ("country", "TEXT DEFAULT 'FR'"), ("lat", "REAL"), ("lon", "REAL"),
        ("contact_form_url", "TEXT"), ("source_url", "TEXT"), ("source_type", "TEXT"),
        ("confidence", "REAL DEFAULT 0"), ("fingerprint", "TEXT"),
        ("last_checked_at", "TEXT"),
    ]:
        _ensure_column(con, "prospects", column, definition)
    con.execute("CREATE INDEX IF NOT EXISTS idx_prospects_fingerprint ON prospects(fingerprint)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_prospects_company_city ON prospects(company_name, city)")
    con.commit()
    con.close()


def rows(sql: str, params=()):
    con = connect()
    out = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    return out


def one(sql: str, params=()):
    con = connect()
    row = con.execute(sql, params).fetchone()
    con.close()
    return dict(row) if row else None


def execute(sql: str, params=()):
    con = connect()
    cur = con.execute(sql, params)
    con.commit()
    rid = cur.lastrowid
    con.close()
    return rid
