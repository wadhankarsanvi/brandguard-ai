"""Persistence layer. Supports PostgreSQL (via psycopg) when DATABASE_URL is set,
otherwise defaults to local SQLite. One connection per request."""
import re
import sqlite3
from flask import g
from backend import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('creator','manager','legal')), team TEXT, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, doc_type TEXT NOT NULL DEFAULT 'guideline',
  filename TEXT, uploaded_by INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL, heading TEXT, text TEXT NOT NULL, embedding TEXT);
CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
  kind TEXT NOT NULL, pattern TEXT NOT NULL, preferred TEXT DEFAULT '', severity TEXT NOT NULL DEFAULT 'medium',
  description TEXT DEFAULT '', source TEXT DEFAULT '', case_sensitive INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS submissions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, kind TEXT NOT NULL, content_text TEXT DEFAULT '',
  filename TEXT, image_path TEXT, alt_text TEXT DEFAULT '', creator_id INTEGER NOT NULL, team TEXT,
  status TEXT NOT NULL DEFAULT 'draft', stage TEXT NOT NULL DEFAULT 'creator', score INTEGER, current_version INTEGER DEFAULT 1,
  requires_legal INTEGER DEFAULT 0, badge TEXT, page_map TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS revisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id INTEGER NOT NULL, version INTEGER NOT NULL,
  content_text TEXT, author_id INTEGER, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS issues(
  id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id INTEGER NOT NULL, version INTEGER NOT NULL,
  category TEXT, rule_key TEXT, severity TEXT, message TEXT, start INTEGER, end INTEGER, match TEXT, excerpt TEXT,
  suggestion TEXT, auto_fix INTEGER DEFAULT 0, citation TEXT, bbox TEXT, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id INTEGER NOT NULL, issue_id INTEGER, parent_id INTEGER,
  author_id INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id INTEGER NOT NULL, stage TEXT NOT NULL, reviewer_id INTEGER NOT NULL,
  decision TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  submission_id INTEGER REFERENCES submissions(id) ON DELETE CASCADE,
  message TEXT NOT NULL, read INTEGER DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor_id INTEGER, actor_name TEXT, action TEXT NOT NULL,
  entity TEXT, entity_id INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_issues_sub ON issues(submission_id, version);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(document_id);
"""


def _prepare_sql(sql):
    if config.DATABASE_URL:
        sql = sql.replace("?", "%s")
        # Replace SQLite group_concat if any with PostgreSQL string_agg
        sql = re.sub(r'\bgroup_concat\(([^,\)]+)\)', r"string_agg(\1, ',')", sql, flags=re.IGNORECASE)
        sql = re.sub(r'\bgroup_concat\(([^,]+),\s*([^)]+)\)', r'string_agg(\1, \2)', sql, flags=re.IGNORECASE)
    return sql


def connect():
    if config.DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        db_url = config.DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[len("postgres://"):]
        return psycopg.connect(db_url, row_factory=dict_row)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = connect()
    if config.DATABASE_URL:
        schema = SCHEMA
        schema = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', schema, flags=re.IGNORECASE)
        schema = schema.replace("AUTOINCREMENT", "SERIAL")
        with conn.cursor() as cur:
            for statement in schema.split(";"):
                stmt = statement.strip()
                if stmt:
                    cur.execute(stmt)
            try:
                cur.execute("ALTER TABLE submissions ADD COLUMN IF NOT EXISTS page_map TEXT")
            except Exception:
                pass
            try:
                cur.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding TEXT")
            except Exception:
                pass
            try:
                cur.execute("""CREATE TABLE IF NOT EXISTS notifications(
  id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  submission_id INTEGER REFERENCES submissions(id) ON DELETE CASCADE,
  message TEXT NOT NULL, read INTEGER DEFAULT 0, created_at TEXT NOT NULL)""")
            except Exception:
                pass
        conn.commit()
    else:
        conn.executescript(SCHEMA)
        try:
            conn.execute("ALTER TABLE submissions ADD COLUMN page_map TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE chunks ADD COLUMN embedding TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  submission_id INTEGER REFERENCES submissions(id) ON DELETE CASCADE,
  message TEXT NOT NULL, read INTEGER DEFAULT 0, created_at TEXT NOT NULL)""")
        except sqlite3.OperationalError:
            pass
        conn.commit()
    conn.close()


def query(sql, args=(), one=False):
    db = get_db()
    if config.DATABASE_URL:
        sql = _prepare_sql(sql)
        with db.cursor() as cur:
            cur.execute(sql, args if args else None)
            rows = cur.fetchall()
            rows = [dict(r) for r in rows]
            return (rows[0] if rows else None) if one else rows
    else:
        rows = db.execute(sql, args).fetchall()
        rows = [dict(r) for r in rows]
        return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    stripped = sql.strip()
    is_insert = stripped.upper().startswith("INSERT INTO")
    if config.DATABASE_URL:
        sql = _prepare_sql(sql)
        has_returning = False
        if is_insert and not re.search(r'\binto\s+settings\b', stripped, re.IGNORECASE) and not re.search(r'\breturning\b', stripped, re.IGNORECASE):
            sql = stripped.rstrip(";") + " RETURNING id"
            has_returning = True

        with db.cursor() as cur:
            cur.execute(sql, args if args else None)
            last_id = None
            if has_returning:
                row = cur.fetchone()
                if row:
                    last_id = row["id"] if isinstance(row, dict) else row[0]
        db.commit()
        if is_insert and "INTO COMMENTS" in stripped.upper() and len(args) >= 5:
            try:
                from backend.common import handle_comment_mentions
                handle_comment_mentions(args[0], args[3], args[4])
            except Exception:
                pass
        return last_id
    else:
        cur = db.execute(sql, args)
        db.commit()
        if is_insert and "INTO COMMENTS" in stripped.upper() and len(args) >= 5:
            try:
                from backend.common import handle_comment_mentions
                handle_comment_mentions(args[0], args[3], args[4])
            except Exception:
                pass
        return cur.lastrowid
