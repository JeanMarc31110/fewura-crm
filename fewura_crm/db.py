import sqlite3
import threading
from .paths import database_path


SQLITE_BUSY_TIMEOUT_MS = 30_000
_init_lock = threading.RLock()
_initialized_databases: set[str] = set()


def connect():
    # Autocommit prevents an interrupted request from silently retaining an
    # implicit write transaction. Multi-step writes explicitly BEGIN below.
    con = sqlite3.connect(
        database_path(),
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
    )
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _ensure_column(con, table: str, column: str, definition: str) -> None:
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    db_key = str(database_path().resolve())
    if db_key in _initialized_databases:
        return
    with _init_lock:
        if db_key in _initialized_databases:
            return
        con = connect()
        try:
            # WAL permet aux lectures du tableau de bord et aux écritures du
            # planificateur de cohabiter sans se bloquer mutuellement.
            try:
                con.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                # Some managed Windows folders refuse SQLite's -wal/-shm sidecars.
                # The database remains usable with the rollback journal.
                con.execute("PRAGMA journal_mode=DELETE")
            con.execute("PRAGMA synchronous=NORMAL")
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
    CREATE TABLE IF NOT EXISTS settings(
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS campaigns(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      subject TEXT NOT NULL,
      body TEXT NOT NULL,
      sms_body TEXT NOT NULL DEFAULT '',
      category TEXT,
      city TEXT,
      min_score INTEGER DEFAULT 0,
      mode TEXT NOT NULL DEFAULT 'simulation',
      scheduled_at TEXT,
      status TEXT NOT NULL DEFAULT 'brouillon',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      started_at TEXT,
      finished_at TEXT
    );
    CREATE TABLE IF NOT EXISTS campaign_recipients(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id INTEGER NOT NULL,
      prospect_id INTEGER NOT NULL,
      channel TEXT NOT NULL DEFAULT 'email',
      status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,
      last_error TEXT,
      sent_at TEXT,
      UNIQUE(campaign_id, prospect_id),
      FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
      FOREIGN KEY(prospect_id) REFERENCES prospects(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS communications(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      prospect_id INTEGER,
      campaign_id INTEGER,
      channel TEXT NOT NULL,
      direction TEXT NOT NULL DEFAULT 'sortant',
      status TEXT NOT NULL,
      recipient TEXT,
      subject TEXT,
      body TEXT,
      error TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(prospect_id) REFERENCES prospects(id) ON DELETE SET NULL,
      FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL
    );
            """)
            _ensure_column(con, "campaigns", "sms_body", "TEXT NOT NULL DEFAULT ''")
            for column, definition in [
                ("address", "TEXT"), ("postal_code", "TEXT"), ("region", "TEXT"),
                ("country", "TEXT DEFAULT 'FR'"), ("lat", "REAL"), ("lon", "REAL"),
                ("contact_form_url", "TEXT"), ("source_url", "TEXT"), ("source_type", "TEXT"),
                ("confidence", "REAL DEFAULT 0"), ("fingerprint", "TEXT"),
                ("last_checked_at", "TEXT"), ("siren", "TEXT"), ("siret", "TEXT"), ("activity_code", "TEXT"),
            ]:
                _ensure_column(con, "prospects", column, definition)
            con.execute("CREATE INDEX IF NOT EXISTS idx_prospects_fingerprint ON prospects(fingerprint)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_prospects_company_city ON prospects(company_name, city)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_schedule ON campaigns(status, scheduled_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_communications_prospect ON communications(prospect_id, created_at)")
            con.commit()
            _initialized_databases.add(db_key)
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def rows(sql: str, params=()):
    con = connect()
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def one(sql: str, params=()):
    con = connect()
    try:
        row = con.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def execute(sql: str, params=()):
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        cur = con.execute(sql, params)
        con.commit()
        return cur.lastrowid
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

