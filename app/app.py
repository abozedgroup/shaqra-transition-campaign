# -*- coding: utf-8 -*-
"""نظام تذاكر التواصل مع قسم العناية بالموظفين - نطاق شقراء الصحي.
Flask + SQLite. أقسام وحسابات وتصعيد ومهلة لكل قسم، وتقديم مجهول للشكاوى والملاحظات والاقتراحات.
لا يُسجَّل أي بيان شخصي في السجلات."""
import csv
import hashlib
import hmac
import io
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from functools import wraps
from datetime import datetime, timedelta, timezone

from i18n import (ERR, FACILITY_OPTS, JOB_OPTS, STATUSES as STATUSES_I18N, T, TYPES as TYPES_I18N,
                  TYPE_HELP)
from flask import (Flask, Response, abort, g, redirect, render_template,
                   request, send_from_directory, session, url_for)

# ---------------------------------------------------------------- config
DB_PATH = os.environ.get("DB_PATH", "/data/tickets.db")
SITE_DIR = os.environ.get("SITE_DIR", "/srv/site")
DATA_DIR = os.path.dirname(DB_PATH) or "."
UPLOAD_DIR = os.path.abspath(os.path.join(DATA_DIR, "uploads"))
ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")  # salt_hex:hash_hex (scrypt)
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
ADMIN_SESSION_SECONDS = 2 * 60 * 60
RIYADH = timezone(timedelta(hours=3))

FACILITIES = [
    "مستشفى شقراء العام", "مستشفى ثادق", "مستشفى مرات",
    "مراكز الرعاية الأولية – شقراء", "مراكز الرعاية الأولية – ثادق",
    "مراكز الرعاية الأولية – مرات", "أخرى",
]
JOB_CATEGORIES = [
    "طبيب", "تمريض", "صيدلة", "مختبر وأشعة وفنيون صحيون",
    "إداري", "خدمات مساندة", "تقنية معلومات", "أخرى",
]
REQ_TYPES = {"request": "استفسار أو طلب", "feedback": "شكوى أو اقتراح أو ملاحظة"}
# الأنواع القديمة (قبل الدمج) وروابط الصفحات التي ما زالت تستخدمها
LEGACY_TYPES = {"inquiry": "request", "info_request": "request",
                "complaint": "feedback", "suggestion": "feedback", "feedback": "feedback"}
# نوع يجوز تقديمه دون الإفصاح عن البيانات، ويُوجَّه مباشرة لقسم الشكاوى
ANON_TYPES = ("feedback",)
FIRST_REF = 1001
FOLLOW_CODE_LEN = 6
MAX_PHOTOS = 3
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_MAX_SIDE = 2000
STATUSES = {"new": "جديدة", "escalated": "محالة", "in_progress": "قيد المعالجة",
            "resolved": "تم الرد – بانتظار التقييم", "closed": "مغلقة"}
RATE_WINDOW_DAYS = 5  # working days the employee has to rate before the ticket closes on its own
CHANNELS = {"online": "إلكتروني", "walkin": "حضوري"}
CLOSE_REASONS = {"rated": "بعد تقييم الموظف", "auto": "تلقائيًا بعد انتهاء مهلة التقييم",
                 "staff": "أغلقها القسم دون تقييم", "": "—"}
KIOSK_COOKIE = "shq_k"
OPEN_STATUSES = ("new", "escalated", "in_progress")
ROLES = {"admin": "مشرف عام", "staff": "موظف قسم"}
INTAKE_KEY, COMPLAINTS_KEY = "care", "complaints"
SEED_DEPTS = [
    # key, Arabic, English, SLA working days, employee can choose it as a topic
    (INTAKE_KEY, "العناية بالموظفين", "Employee Care", 2, 0),
    (COMPLAINTS_KEY, "الشكاوى والملاحظات والاقتراحات", "Complaints, feedback and suggestions", 5, 0),
    ("development", "تطوير الموظفين", "Employee development", 3, 1),
    ("contracts", "العقود والترقيات", "Contracts and promotions", 3, 1),
    ("leaves", "الإجازات", "Leaves", 3, 1),
    ("payroll", "الأجور والمزايا", "Pay and benefits", 3, 1),
    ("services", "شؤون الموظفين والخدمات", "Employee affairs and services", 3, 1),
    ("transition", "الانتقال والتكليف", "Transition and assignment", 3, 1),
    ("ohs", "الصحة والسلامة المهنية", "Occupational health and safety", 3, 1),
]
GENERAL_TOPIC = "general"

EMAIL_RE = re.compile(r"^[a-z0-9][a-z0-9._%+\-]{0,63}@moh\.gov\.sa$")
MOBILE_RE = re.compile(r"^05\d{8}$")
EMPNO_RE = re.compile(r"^\d{3,10}$")
REF_RE = re.compile(r"^(SHQ-\d{6}-[A-Z0-9]{5}|\d{1,7})$")  # old long refs stay valid
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,40}$")
REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

app = Flask(__name__, static_folder=None, template_folder="templates")
app.config.update(
    MAX_CONTENT_LENGTH=(MAX_PHOTOS * MAX_PHOTO_BYTES) + 256 * 1024,
    SESSION_COOKIE_NAME="shq_s",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=ADMIN_SESSION_SECONDS),
    JSON_AS_ASCII=False,
)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
log = logging.getLogger("shq")
log.setLevel(logging.INFO)
if not log.handlers:  # show our messages next to gunicorn's in the container log
    log.handlers = logging.getLogger("gunicorn.error").handlers or [logging.StreamHandler()]


def _load_secret_key():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    os.makedirs(DATA_DIR, exist_ok=True)
    p = os.path.join(DATA_DIR, "secret_key")
    if os.path.exists(p):
        return open(p).read().strip()
    k = secrets.token_hex(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(k)
    return k


app.secret_key = _load_secret_key()


# ---------------------------------------------------------------- database
DB_HOOKS = []     # extra migrations registered by add-on modules (appointments.py)
SWEEP_HOOKS = []  # extra periodic jobs registered by add-on modules

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  email TEXT NOT NULL,
  mobile TEXT NOT NULL,
  emp_no TEXT NOT NULL,
  name TEXT NOT NULL,
  facility TEXT NOT NULL,
  job_cat TEXT NOT NULL,
  req_type TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  reply TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_t_status ON tickets(status);
CREATE INDEX IF NOT EXISTS ix_t_email ON tickets(email);
CREATE INDEX IF NOT EXISTS ix_t_created ON tickets(created_at);
CREATE TABLE IF NOT EXISTS departments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL UNIQUE,
  name_ar TEXT NOT NULL,
  name_en TEXT NOT NULL,
  sla_days INTEGER NOT NULL DEFAULT 3,
  selectable INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'staff',
  dept_id INTEGER REFERENCES departments(id),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  kind TEXT NOT NULL,
  from_dept INTEGER,
  to_dept INTEGER,
  text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_e_ticket ON events(ticket_id);
CREATE TABLE IF NOT EXISTS attachments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  token TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  size INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_a_ticket ON attachments(ticket_id);
CREATE TABLE IF NOT EXISTS ratings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  stars INTEGER NOT NULL,
  resolved INTEGER NOT NULL,
  comment TEXT NOT NULL DEFAULT '',
  via TEXT NOT NULL DEFAULT 'online',
  dept_id INTEGER,
  user_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_r_ticket ON ratings(ticket_id);
CREATE TABLE IF NOT EXISTS counters(
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kiosks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT '',
  last_seen TEXT NOT NULL DEFAULT ''
);
"""

TICKET_NEW_COLS = [
    ("lang", "TEXT NOT NULL DEFAULT 'ar'"),
    ("topic", "TEXT NOT NULL DEFAULT ''"),
    ("dept_id", "INTEGER"),
    ("anonymous", "INTEGER NOT NULL DEFAULT 0"),
    ("follow_hash", "TEXT NOT NULL DEFAULT ''"),
    ("due_at", "TEXT NOT NULL DEFAULT ''"),
    ("closed_at", "TEXT NOT NULL DEFAULT ''"),
    ("channel", "TEXT NOT NULL DEFAULT 'online'"),
    ("assigned_user_id", "INTEGER"),
    ("first_response_at", "TEXT NOT NULL DEFAULT ''"),
    ("resolved_at", "TEXT NOT NULL DEFAULT ''"),
    ("rate_due_at", "TEXT NOT NULL DEFAULT ''"),
    ("close_reason", "TEXT NOT NULL DEFAULT ''"),
    ("rating", "INTEGER"),
    ("kiosk_id", "INTEGER"),
    ("sla_breached", "INTEGER NOT NULL DEFAULT 0"),
]


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
    for name, decl in TICKET_NEW_COLS:
        if name not in cols:
            con.execute("ALTER TABLE tickets ADD COLUMN %s %s" % (name, decl))
    con.execute("CREATE INDEX IF NOT EXISTS ix_t_dept ON tickets(dept_id)")
    if not con.execute("SELECT 1 FROM counters WHERE name='ticket_ref'").fetchone():
        last = con.execute("SELECT MAX(CAST(ref AS INTEGER)) FROM tickets WHERE ref NOT LIKE 'SHQ-%'").fetchone()[0]
        con.execute("INSERT INTO counters(name,value) VALUES('ticket_ref',?)", (max(FIRST_REF - 1, last or 0),))
    # anonymous tickets keep nothing that could point to the person (device, language)
    con.execute("UPDATE tickets SET kiosk_id=NULL, lang='' WHERE anonymous=1 AND (kiosk_id IS NOT NULL OR lang<>'')")
    con.execute("UPDATE events SET actor='مقدّم مجهول' WHERE actor LIKE 'الموظف (جهاز الاستقبال%' "
                "AND ticket_id IN (SELECT id FROM tickets WHERE anonymous=1)")
    cols_u = [r[1] for r in con.execute("PRAGMA table_info(users)")]
    if "session_ver" not in cols_u:
        con.execute("ALTER TABLE users ADD COLUMN session_ver INTEGER NOT NULL DEFAULT 0")
    # tickets closed before the rating cycle existed: closed by the section
    con.execute("UPDATE tickets SET close_reason='staff' WHERE status='closed' AND close_reason=''")
    con.execute("UPDATE tickets SET first_response_at=updated_at WHERE first_response_at='' AND reply<>''")
    for old, new in LEGACY_TYPES.items():  # the five old request types became two
        if old != new:
            con.execute("UPDATE tickets SET req_type=? WHERE req_type=?", (new, old))
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if not con.execute("SELECT 1 FROM departments LIMIT 1").fetchone():
        for i, (k, ar, en, sla, sel) in enumerate(SEED_DEPTS):
            con.execute("INSERT INTO departments(key,name_ar,name_en,sla_days,selectable,sort) VALUES(?,?,?,?,?,?)",
                        (k, ar, en, sla, sel, (i + 1) * 10))
    # older tickets (before departments existed) belong to Employee Care
    care = con.execute("SELECT id, sla_days FROM departments WHERE key=?", (INTAKE_KEY,)).fetchone()
    for tid, created, status in con.execute(
            "SELECT id, created_at, status FROM tickets WHERE dept_id IS NULL").fetchall():
        due = add_workdays(created, care[1]) if status in OPEN_STATUSES else ""
        con.execute("UPDATE tickets SET dept_id=?, topic=?, due_at=? WHERE id=?", (care[0], GENERAL_TOPIC, due, tid))
    for hook in DB_HOOKS:
        hook(con)
    con.commit()
    con.close()
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def add_workdays(start_iso, days):
    """Deadline after `days` working days (Sunday–Thursday, Riyadh time), as a UTC ISO string."""
    try:
        d = datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(RIYADH)
    except Exception:
        d = datetime.now(RIYADH)
    left = max(0, int(days))
    while d.weekday() in (4, 5):  # submitted on Friday/Saturday: the clock starts Sunday morning
        d = (d + timedelta(days=1)).replace(hour=8, minute=0, second=0)
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() not in (4, 5):
            left -= 1
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_e):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_dt(s):
    try:
        d = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return d.astimezone(RIYADH).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s


app.jinja_env.filters["dt"] = fmt_dt
app.jinja_env.filters["day"] = lambda s: fmt_dt(s)[:10] if s else ""

# ---------------------------------------------------------------- rate limit
_rl = {}
_rl_lock = threading.Lock()


def client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[-1].strip()[:64]
    return (request.remote_addr or "?")[:64]


def rate_hit(key, limit, window):
    """يسجّل محاولة ويعيد True إن تجاوزت الحد."""
    now = time.time()
    with _rl_lock:
        arr = [t for t in _rl.get(key, []) if now - t < window]
        over = len(arr) >= limit
        if not over:
            arr.append(now)
        _rl[key] = arr
        if len(_rl) > 20000:
            for k in list(_rl)[:5000]:
                _rl.pop(k, None)
        return over


def rate_peek(key, limit, window):
    now = time.time()
    with _rl_lock:
        arr = [t for t in _rl.get(key, []) if now - t < window]
        _rl[key] = arr
        return len(arr) >= limit


def rate_add(key):
    with _rl_lock:
        _rl.setdefault(key, []).append(time.time())


# ---------------------------------------------------------------- security
def csrf_token():
    t = session.get("csrf")
    if not t:
        t = secrets.token_urlsafe(32)
        session["csrf"] = t
    return t


app.jinja_env.globals["csrf_token"] = csrf_token


def check_csrf():
    sent = request.form.get("csrf_token", "")
    want = session.get("csrf", "")
    if not want or not hmac.compare_digest(sent.encode(), want.encode()):
        abort(400, "csrf")


CSP_APP = ("default-src 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
           "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
           "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
CSP_STATIC = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
              "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
              "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


@app.after_request
def headers(resp):
    is_app = getattr(g, "is_app", False)
    resp.headers["Content-Security-Policy"] = CSP_APP if is_app else CSP_STATIC
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if is_app:
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@app.before_request
def mark():
    p = request.path
    g.is_app = p.startswith(("/ticket", "/status", "/admin", "/app-static", "/en/ticket", "/en/status",
                             "/kiosk", "/en/kiosk"))
    g.lang = "en" if (p == "/en" or p.startswith("/en/")) else "ar"


def _msg(code, status):
    g.is_app = True
    lang = getattr(g, "lang", "ar")
    title, msg = T[lang][code]
    return render_template("msg.html", title=title, msg=msg), status


@app.errorhandler(400)
def e400(_e):
    return _msg("e400", 400)


@app.errorhandler(404)
def e404(_e):
    return _msg("e404", 404)


@app.errorhandler(413)
def e413(_e):
    return _msg("e413", 413)


@app.errorhandler(429)
def e429(_e):
    return _msg("e429", 429)


@app.errorhandler(500)
def e500(_e):
    return _msg("e500", 500)


@app.context_processor
def inject_i18n():
    lang = getattr(g, "lang", "ar")
    pre = "/en" if lang == "en" else ""
    p = request.path
    # counterpart page in the other language (app pages keep their path, static pages map by name)
    if p.startswith("/en"):
        other = p[3:] or "/"
    else:
        other = "/en" + (p if p != "/" else "/")
    if other.rstrip("/").endswith("/ticket/done") or p.rstrip("/").endswith("/ticket/done"):
        other = ("/ticket" if lang == "en" else "/en/ticket")
    if p.startswith("/admin") or p.startswith("/en/admin"):
        other = None
    return dict(t=T[lang], lang=lang, dir=T[lang]["dir"], pre=pre, switch_url=other,
                u=dict(home=pre + "/", journey=pre + "/journey.html", faq=pre + "/faq.html", links=pre + "/links.html", contact=pre + "/contact.html",
                       ticket=pre + "/ticket", status=pre + "/status", done=pre + "/ticket/done"))


# ---------------------------------------------------------------- validation


# ---------------------------------------------------------------- automatic closing
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
BACKUP_KEEP = 14


def backup_daily():
    """One consistent copy of the database per day in /data/backups, keeping the last 14.
    Protects against mistakes and corruption; it is on the same disk, so copy it off-server too."""
    try:
        name = "tickets-%s.db" % datetime.now(RIYADH).strftime("%Y%m%d")
        path = os.path.join(BACKUP_DIR, name)
        if os.path.exists(path):
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
        tmp = path + ".tmp"
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        olds = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("tickets-") and f.endswith(".db"))
        for f in olds[:-BACKUP_KEEP]:
            os.remove(os.path.join(BACKUP_DIR, f))
        log.info("backup written: %s", name)
    except Exception:  # a failed backup must never break a request
        log.exception("backup failed")


_sweep = {"at": 0.0}
_sweep_lock = threading.Lock()


def auto_close(con, force=False):
    """Close tickets whose rating window passed: the reply is considered received."""
    now = time.time()
    with _sweep_lock:
        if not force and now - _sweep["at"] < 120:
            return 0
        _sweep["at"] = now
    ts = now_utc()
    rows = con.execute("SELECT id, rate_due_at FROM tickets WHERE status='resolved' AND rate_due_at<>'' "
                       "AND rate_due_at<?", (ts,)).fetchall()
    n = 0
    for tid, due in rows:
        # closed as of the end of the rating window (not the moment someone happened to open the dashboard)
        cur = con.execute("UPDATE tickets SET status='closed', closed_at=?, close_reason='auto', updated_at=? "
                          "WHERE id=? AND status='resolved'", (due, ts, tid))
        if cur.rowcount == 1:
            n += 1
            log_event(con, tid, "النظام", "autoclose",
                      "لم يقيّم الموظف خلال %d أيام عمل؛ يُعتبر الرد قد وصل." % RATE_WINDOW_DAYS)
    con.commit()
    for hook in SWEEP_HOOKS:
        try:
            hook(con)
        except Exception:
            log.exception("sweep hook failed")
    backup_daily()
    return n


@app.before_request
def _auto_close_hook():
    if request.path.startswith(("/admin", "/status", "/en/status", "/kiosk")):
        auto_close(db())


def save_rating(con, row, stars, resolved, comment, via):
    """Store the employee's rating. Resolved -> closed; not resolved -> back to the section.
    Returns False if the ticket was no longer waiting for a rating (double tap, auto-close in between)."""
    ts = now_utc()
    if con.in_transaction:
        con.commit()
    con.execute("BEGIN IMMEDIATE")
    if resolved:
        cur = con.execute("UPDATE tickets SET status='closed', closed_at=?, close_reason='rated', rating=?, "
                          "updated_at=? WHERE id=? AND status='resolved'", (ts, stars, ts, row["id"]))
    else:
        d = dept_by_id(row["dept_id"])
        cur = con.execute("UPDATE tickets SET status='in_progress', rating=?, rate_due_at='', resolved_at='', "
                          "due_at=?, updated_at=?, sla_breached=MAX(sla_breached, ?) WHERE id=? AND status='resolved'",
                          (stars, add_workdays(ts, d["sla_days"] if d else 3), ts,
                           1 if row["resolved_at"] and row["due_at"] and row["resolved_at"] > row["due_at"] else 0,
                           row["id"]))
    if cur.rowcount != 1:
        con.rollback()
        return False
    con.execute("INSERT INTO ratings(ticket_id,at,stars,resolved,comment,via,dept_id,user_id) VALUES(?,?,?,?,?,?,?,?)",
                (row["id"], ts, stars, 1 if resolved else 0, comment, via, row["dept_id"], row["assigned_user_id"]))
    who = "مقدّم مجهول" if row["anonymous"] else "الموظف"
    txt = "%d من 5 – %s%s" % (stars, "تم حل الطلب" if resolved else "لم يُحل الطلب", ("\n" + comment) if comment else "")
    log_event(con, row["id"], who + (" (جهاز الاستقبال)" if via == "kiosk" and not row["anonymous"] else ""),
              "rating", txt)
    if not resolved:
        log_event(con, row["id"], "النظام", "reopen", "أُعيدت التذكرة للقسم لأن الموظف أفاد بأن طلبه لم يُحل.")
    con.commit()
    return True


def leg_was_late(row, ts):
    """Before a deadline is reset (escalation, reopening), remember whether the current leg missed it,
    so a late ticket cannot become 'on time' in the indicators."""
    if not row["due_at"]:
        return False
    if row["status"] in OPEN_STATUSES:
        return ts > row["due_at"]
    fin = row["resolved_at"] or row["closed_at"]
    return bool(fin) and fin > row["due_at"]


def read_rating_form(form):
    try:
        stars = int(form.get("stars", "0"))
    except ValueError:
        stars = 0
    res = form.get("resolved", "")
    if stars < 1 or stars > 5 or res not in ("1", "0"):
        return None
    return stars, res == "1", clean(form.get("comment"), 1000)


# ---------------------------------------------------------------- departments
def all_depts(active_only=False):
    q = "SELECT * FROM departments" + (" WHERE active=1" if active_only else "") + " ORDER BY sort, id"
    return db().execute(q).fetchall()


def dept_by_key(key):
    return db().execute("SELECT * FROM departments WHERE key=?", (key,)).fetchone()


def dept_by_id(did):
    return db().execute("SELECT * FROM departments WHERE id=?", (did,)).fetchone()


def topic_opts(lang):
    """Topics the employee may choose: active, selectable sections, then 'general'."""
    out = [(d["key"], d["name_ar"] if lang == "ar" else d["name_en"])
           for d in all_depts(True) if d["selectable"]]
    out.append((GENERAL_TOPIC, T[lang]["topic_general"]))
    return out


def log_event(con, ticket_id, actor, kind, text="", from_dept=None, to_dept=None):
    con.execute("INSERT INTO events(ticket_id,at,actor,kind,from_dept,to_dept,text) VALUES(?,?,?,?,?,?,?)",
                (ticket_id, now_utc(), actor, kind, from_dept, to_dept, text))


def follow_hash(ref, code):
    return hashlib.sha256(("shq-follow:%s:%s" % (ref, code)).encode()).hexdigest()


def norm_code(s):
    return re.sub(r"[\s\-]", "", (s or "").translate(AR_DIGITS)).upper()


# ---------------------------------------------------------------- validation
def clean(s, maxlen):
    s = unicodedata.normalize("NFC", (s or "")).replace("\r\n", "\n").replace("\r", "\n")
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return s.strip()[:maxlen]


def _opt(opts, raw, lang):
    """Accept the option key (new form) or the stored Arabic label (older clients); return the Arabic label."""
    for key, ar, en in opts:
        if raw in (key, ar):
            return ar
    return ""


def validate_ticket(form, lang="ar", min_msg=10):
    i = 0 if lang == "ar" else 1
    errors, v = {}, {}
    v["req_type"] = clean(form.get("req_type"), 20)
    v["req_type"] = LEGACY_TYPES.get(v["req_type"], v["req_type"])
    if v["req_type"] not in REQ_TYPES:
        errors["req_type"] = ERR["req_type"][i]
    v["topic"] = clean(form.get("topic"), 40)
    if v["topic"] not in [k for k, _ in topic_opts(lang)]:
        errors["topic"] = ERR["topic"][i]
    v["anonymous"] = form.get("anonymous") == "1" and v["req_type"] in ANON_TYPES
    v["want_appt"] = form.get("want_appt") == "1"
    v["message"] = clean(form.get("message"), 3000)
    if len(v["message"]) < min_msg:
        errors["message"] = ERR["message"][i]
    raw_f = clean(form.get("facility"), 80)
    v["facility"] = _opt(FACILITY_OPTS, raw_f, lang)
    v["facility_key"] = next((k for k, ar, en in FACILITY_OPTS if raw_f in (k, ar)), "")
    raw_j = clean(form.get("job_cat"), 80)
    v["job_key"] = next((k for k, ar, en in JOB_OPTS if raw_j in (k, ar)), "")
    if v["anonymous"]:
        # nothing that identifies the employee is kept; the facility is optional
        v.update(email="", mobile="", emp_no="", name="", job_cat="")
    else:
        v["email"] = clean(form.get("email"), 120).lower()
        if not EMAIL_RE.match(v["email"]):
            errors["email"] = ERR["email"][i]
        v["mobile"] = clean(form.get("mobile"), 20).translate(AR_DIGITS).replace(" ", "")
        if not MOBILE_RE.match(v["mobile"]):
            errors["mobile"] = ERR["mobile"][i]
        v["emp_no"] = clean(form.get("emp_no"), 20).translate(AR_DIGITS).replace(" ", "")
        if not EMPNO_RE.match(v["emp_no"]):
            errors["emp_no"] = ERR["emp_no"][i]
        v["name"] = clean(form.get("name"), 80)
        if len(v["name"]) < 3 or "\n" in v["name"]:
            errors["name"] = ERR["name"][i]
        if not v["facility"]:
            errors["facility"] = ERR["facility"][i]
        v["job_cat"] = _opt(JOB_OPTS, raw_j, lang)
        if not v["job_cat"]:
            errors["job_cat"] = ERR["job_cat"][i]
    if form.get("consent") != "1":
        errors["consent"] = ERR["consent"][i]
    return v, errors


def new_ref(con):
    """Next short ticket number (1001, 1002, ...). The counter only goes up, even if tickets are deleted.
    Must run inside the caller's write transaction (BEGIN IMMEDIATE) so two requests never get the same number."""
    con.execute("UPDATE counters SET value=value+1 WHERE name='ticket_ref'")
    return str(con.execute("SELECT value FROM counters WHERE name='ticket_ref'").fetchone()[0])


def new_follow_code():
    return "".join(secrets.choice(REF_ALPHABET) for _ in range(FOLLOW_CODE_LEN))


def create_ticket(con, values, lang, photos=(), channel="online", kiosk=None):
    """Insert a ticket and return (ref, follow-up code, department row). Every new ticket gets a secret
    follow-up code: the short number alone (or with an email) is not enough to read a reply."""
    # complaints, feedback and suggestions go to their own section; everything else starts at Employee Care
    dept = dept_by_key(COMPLAINTS_KEY) if values["req_type"] in ANON_TYPES else None
    if not dept or not dept["active"]:
        dept = dept_by_key(INTAKE_KEY)
    anon = bool(values["anonymous"])
    if con.in_transaction:
        con.commit()
    con.execute("BEGIN IMMEDIATE")
    try:
        ref = new_ref(con)
        ts = now_utc()
        code = new_follow_code()
        cur = con.execute(
            "INSERT INTO tickets(ref,created_at,updated_at,email,mobile,emp_no,name,facility,job_cat,req_type,"
            "message,lang,topic,dept_id,anonymous,follow_hash,due_at,channel,kiosk_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ref, ts, ts, values["email"], values["mobile"], values["emp_no"], values["name"],
             values["facility"], values["job_cat"], values["req_type"], values["message"],
             "" if anon else lang,  # the language could point to a person: not kept for anonymous tickets
             values["topic"], dept["id"], 1 if anon else 0, follow_hash(ref, code),
             add_workdays(ts, dept["sla_days"]), channel,
             None if anon or not kiosk else kiosk["id"]))
        store_photos(con, cur.lastrowid, photos, "employee")
        if anon:
            actor = "مقدّم مجهول"
        elif kiosk:
            actor = "الموظف (جهاز الاستقبال: %s)" % kiosk["name"]
        else:
            actor = "الموظف"
        note = "طلب حضوري" if channel == "walkin" else ""
        if photos:
            note = (note + " · " if note else "") + "%d صورة مرفقة" % len(photos)
        log_event(con, cur.lastrowid, actor, "create", note, to_dept=dept["id"])
        con.commit()
    except Exception:
        con.rollback()
        raise
    return ref, code, dept


def as_id(s):
    """A positive database id from user input, or None (never raises)."""
    s = (s or "").strip()
    if s.isascii() and s.isdigit() and 0 < len(s) <= 9:
        return int(s)
    return None


def norm_ref(s):
    return (s or "").translate(AR_DIGITS).replace("#", "").replace(" ", "").upper()


# ---------------------------------------------------------------- photos
from PIL import Image, ImageOps  # noqa: E402

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:  # HEIC support is optional
    pass
MAX_PHOTO_PIXELS = 40_000_000  # ~ a 48 MP phone photo; larger is refused before decoding
Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS  # Pillow raises above twice this; we check the size ourselves first


def read_photos(files):
    """Re-encode uploaded images as clean JPEGs (no EXIF/location, no hidden payload).
    Returns (list of jpeg bytes, error_key or None)."""
    out = []
    files = [f for f in files if f and f.filename]
    if len(files) > MAX_PHOTOS:
        return [], "photos_count"
    for f in files:
        data = f.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            return [], "photos_size"
        try:
            im = Image.open(io.BytesIO(data))
            if im.format not in ("JPEG", "PNG", "WEBP", "HEIF", "GIF", "MPO"):
                return [], "photos_type"
            w, h = im.size
            if w * h > MAX_PHOTO_PIXELS or w > 20000 or h > 20000:
                return [], "photos_size"
            if im.format in ("JPEG", "MPO"):
                im.draft("RGB", (PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))  # decode at reduced size: far less memory
            im.seek(0)
            im.load()
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            im.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85, optimize=True)
            out.append(buf.getvalue())
        except Exception:
            return [], "photos_type"
    return out, None


def store_photos(con, ticket_id, photos, source, actor=""):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    for data in photos:
        tok = secrets.token_urlsafe(18)
        with open(os.path.join(UPLOAD_DIR, tok + ".jpg"), "wb") as fh:
            fh.write(data)
        con.execute("INSERT INTO attachments(ticket_id,token,source,actor,created_at,size) VALUES(?,?,?,?,?,?)",
                    (ticket_id, tok, source, actor, now_utc(), len(data)))


def delete_photos(con, ticket_id):
    for (tok,) in con.execute("SELECT token FROM attachments WHERE ticket_id=?", (ticket_id,)).fetchall():
        try:
            os.remove(os.path.join(UPLOAD_DIR, tok + ".jpg"))
        except OSError:
            pass
    con.execute("DELETE FROM attachments WHERE ticket_id=?", (ticket_id,))


def send_photo(tok):
    return send_from_directory(UPLOAD_DIR, tok + ".jpg", mimetype="image/jpeg", max_age=0)


ERR_ORDER = ["req_type", "topic", "message", "photos", "name", "emp_no", "facility", "job_cat", "email", "mobile", "consent"]


# ---------------------------------------------------------------- public pages
@app.route("/ticket", methods=["GET", "POST"])
@app.route("/en/ticket", methods=["GET", "POST"])
def ticket_form():
    lang = g.lang
    pre = "/en" if lang == "en" else ""
    values, errors = {}, {}
    if request.method == "POST":
        check_csrf()
        ip = client_ip()
        if rate_hit("tc:" + ip, 15, 600) or rate_hit("td:" + ip, 300, 86400):
            abort(429)
        if request.form.get("website"):  # honeypot
            return redirect(pre + "/ticket/done")
        values, errors = validate_ticket(request.form, lang)
        photos, perr = read_photos(request.files.getlist("photos"))
        if perr:
            errors["photos"] = ERR[perr][0 if lang == "ar" else 1]
        elif photos and errors:
            errors["photos"] = ERR["photos_again"][0 if lang == "ar" else 1]
        if not errors:
            con = db()
            if values["anonymous"]:
                if rate_hit("ta:" + ip, 30, 86400):  # one IP is often a whole hospital (NAT)
                    abort(429)
            else:
                since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                n = con.execute("SELECT COUNT(*) FROM tickets WHERE email=? AND created_at>?",
                                (values["email"], since)).fetchone()[0]
                if n >= 5:
                    abort(429)
            ref, code, dept = create_ticket(con, values, lang, photos)
            if (request.form.get("want_appt") == "1" and not values["anonymous"]
                    and values["req_type"] == "request"):
                tk_ = con.execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone()
                appointments.create_request(con, tk_, request.form.get("appt_pref"), "employee")
                con.commit()
            session["done_ref"] = ref
            session["done_code"] = code
            session["done_anon"] = bool(values["anonymous"])
            return redirect(pre + "/ticket/done")
    else:
        t = LEGACY_TYPES.get(request.args.get("type", ""), request.args.get("type", ""))
        if t in REQ_TYPES:
            values["req_type"] = t
        tp = request.args.get("topic", "")
        if tp in [k for k, _ in topic_opts(lang)]:
            values["topic"] = tp
        qpre = clean(request.args.get("q"), 300)
        if qpre:
            values["message"] = qpre
    i = 0 if lang == "ar" else 1
    first_bad = next((f for f in ERR_ORDER if f in errors), "")
    start = 1 if first_bad in ("", "req_type", "topic", "message", "photos") else (
        2 if first_bad in ("name", "emp_no", "facility", "job_cat") else 3)
    return render_template(
        "ticket_form.html", v=values, errors=errors, start=start,
        facilities=[(k, ar if lang == "ar" else en) for k, ar, en in FACILITY_OPTS],
        jobs=[(k, ar if lang == "ar" else en) for k, ar, en in JOB_OPTS],
        types=[(k, TYPES_I18N[k][i], TYPE_HELP[k][i]) for k in REQ_TYPES],
        anon_types=ANON_TYPES, topics=topic_opts(lang), max_photos=MAX_PHOTOS,
        err_msgs={k: ERR[k][i] for k in ERR}, err_order=ERR_ORDER,
    ), (400 if errors else 200)


@app.route("/ticket/done")
@app.route("/en/ticket/done")
def ticket_done():
    ref = session.pop("done_ref", None)
    code = session.pop("done_code", "")
    anon = session.pop("done_anon", False)
    return render_template("ticket_done.html", ref=ref, code=code, anon=anon)


@app.route("/status", methods=["GET", "POST"])
@app.route("/en/status", methods=["GET", "POST"])
def status_lookup():
    lang = g.lang
    i = 0 if lang == "ar" else 1
    result, error, dept_name, photos, rated = None, None, "", [], None
    cols = ("SELECT id,ref,created_at,updated_at,req_type,status,reply,dept_id,anonymous,assigned_user_id,"
            "rate_due_at,close_reason,rating,resolved_at,due_at FROM tickets ")
    if request.method == "POST" and request.form.get("action") == "rate":
        # rating a ticket this visitor has just looked up (same session)
        check_csrf()
        ref = norm_ref(clean(request.form.get("ref"), 30))
        row = db().execute(cols + "WHERE ref=?", (ref,)).fetchone() if REF_RE.match(ref) else None
        if not row or row["id"] not in session.get("st_ok", []):
            abort(400)
        vals = read_rating_form(request.form)
        if row["status"] == "resolved" and vals:
            if save_rating(db(), row, *vals, via="online"):
                rated = "ok" if vals[1] else "reopened"
        elif row["status"] == "resolved":
            error = T[lang]["rt_missing"]
        result = db().execute(cols + "WHERE id=?", (row["id"],)).fetchone()
    elif request.method == "GET" and request.args.get("show") == "1":
        sid = session.get("st_show")
        if sid and sid in session.get("st_ok", []):
            result = db().execute(cols + "WHERE id=?", (sid,)).fetchone()
    elif request.method == "POST":
        check_csrf()
        ip = client_ip()
        if rate_hit("sl:" + ip, 30, 600):
            abort(429)
        ref = norm_ref(clean(request.form.get("ref"), 30))
        key = clean(request.form.get("email"), 120)
        row = None
        if REF_RE.match(ref):
            if "@" in key:
                # tickets created before follow-up codes existed (no code was ever given) keep email lookup
                if EMAIL_RE.match(key.lower()):
                    row = db().execute(cols + "WHERE ref=? AND email=? AND anonymous=0 AND follow_hash=''",
                                       (ref, key.lower())).fetchone()
            else:
                code = norm_code(key)
                if len(code) in (FOLLOW_CODE_LEN, 8):
                    row = db().execute(cols + "WHERE ref=? AND follow_hash=?",
                                       (ref, follow_hash(ref, code))).fetchone()
        if row:
            result = row
            ok_ids = [x for x in session.get("st_ok", []) if x != row["id"]][-9:] + [row["id"]]
            session["st_ok"] = ok_ids
        else:
            error = T[lang]["st_notfound"]
    if result:
        photos = db().execute("SELECT token, source FROM attachments WHERE ticket_id=? ORDER BY id",
                              (result["id"],)).fetchall()
        d = dept_by_id(result["dept_id"])
        if d:
            dept_name = d["name_ar"] if lang == "ar" else d["name_en"]
    actx = {}
    if result:
        session["st_show"] = result["id"]
        actx = appointments.status_ctx(db(), result, lang)
    return render_template("status.html", result=result, error=error, dept_name=dept_name, photos=photos, rated=rated,
                           **actx,
                           statuses={k: v[i] for k, v in STATUSES_I18N.items()},
                           types={k: v[i] for k, v in TYPES_I18N.items()})


@app.route("/status/f/<tok>")
@app.route("/en/status/f/<tok>")
def status_photo(tok):
    """Photos of a ticket the visitor has just opened on the follow-up page (same session)."""
    if not TOKEN_RE.match(tok):
        abort(404)
    r = db().execute("SELECT ticket_id FROM attachments WHERE token=?", (tok,)).fetchone()
    if not r or r[0] not in session.get("st_ok", []):
        abort(404)
    return send_photo(tok)


@app.route("/app-static/<path:name>")
def app_static(name):
    return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), name,
                               max_age=3600)


# ---------------------------------------------------------------- reception device (kiosk)
def kiosk_hash(tok):
    return hashlib.sha256(("shq-kiosk:" + tok).encode()).hexdigest()


def current_kiosk():
    tok = request.cookies.get(KIOSK_COOKIE, "")
    if not tok or len(tok) > 100:
        return None
    k = db().execute("SELECT * FROM kiosks WHERE token_hash=? AND active=1", (kiosk_hash(tok),)).fetchone()
    if k:
        db().execute("UPDATE kiosks SET last_seen=? WHERE id=?", (now_utc(), k["id"]))
        db().commit()
    return k


def kiosk_required(fn):
    @wraps(fn)
    def w(*a, **kw):
        g.kiosk = current_kiosk()
        if not g.kiosk:
            return render_template("kiosk_msg.html", title=T[g.lang]["k_off_h"], msg=T[g.lang]["k_off_p"],
                                   back=False), 403
        return fn(*a, **kw)
    return w


def _kiosk_pre():
    return "/en/kiosk" if g.lang == "en" else "/kiosk"


@app.route("/kiosk")
@app.route("/en/kiosk")
@kiosk_required
def kiosk_home():
    session.pop("k_rate", None)
    session.pop("k_walkin", None)
    return render_template("kiosk_home.html", kpre=_kiosk_pre())


K_ERR_ORDER = ["req_type", "topic", "message", "name", "emp_no", "facility", "job_cat", "email", "mobile", "consent"]


@app.route("/kiosk/new", methods=["GET", "POST"])
@app.route("/en/kiosk/new", methods=["GET", "POST"])
@kiosk_required
def kiosk_new():
    lang, i = g.lang, (0 if g.lang == "ar" else 1)
    values, errors = {}, {}
    if request.method == "POST":
        check_csrf()
        if rate_hit("kn:%d" % g.kiosk["id"], 60, 600):
            abort(429)
        values, errors = validate_ticket(request.form, lang, min_msg=5)
        if not errors:
            con = db()
            if not values["anonymous"]:
                since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                if con.execute("SELECT COUNT(*) FROM tickets WHERE email=? AND created_at>?",
                               (values["email"], since)).fetchone()[0] >= 5:
                    abort(429)
            ref, code, dept = create_ticket(con, values, lang, channel="walkin", kiosk=g.kiosk)
            session["k_done"] = [ref, code, dept["name_ar"] if lang == "ar" else dept["name_en"], bool(values["anonymous"])]
            tk_ = con.execute("SELECT id FROM tickets WHERE ref=?", (ref,)).fetchone()
            session["k_walkin"] = tk_["id"]
            return redirect(_kiosk_pre() + "/done")
    else:
        t = request.args.get("type", "")
        if t in REQ_TYPES:
            values["req_type"] = t
    first_bad = next((f for f in K_ERR_ORDER if f in errors), "")
    return render_template(
        "kiosk_new.html", v=values, errors=errors, first_bad=first_bad, kpre=_kiosk_pre(),
        facilities=[(k, ar if lang == "ar" else en) for k, ar, en in FACILITY_OPTS],
        jobs=[(k, ar if lang == "ar" else en) for k, ar, en in JOB_OPTS],
        types=[(k, TYPES_I18N[k][i], TYPE_HELP[k][i]) for k in REQ_TYPES], anon_types=ANON_TYPES,
        topics=topic_opts(lang), err_msgs={k: ERR[k][i] for k in ERR}, err_order=K_ERR_ORDER,
    ), (400 if errors else 200)


@app.route("/kiosk/done")
@app.route("/en/kiosk/done")
@kiosk_required
def kiosk_done():
    d = session.pop("k_done", None)
    if not d:
        return redirect(_kiosk_pre())
    offer = {}
    if session.get("k_walkin"):
        tk_ = db().execute("SELECT * FROM tickets WHERE id=?", (session["k_walkin"],)).fetchone()
        offer = appointments.walkin_offer(db(), tk_, g.lang) if tk_ else {}
        if not offer:
            session.pop("k_walkin", None)
    return render_template("kiosk_done.html", ref=d[0], code=d[1], dept=d[2], anon=d[3] if len(d) > 3 else False, **offer,
                           kpre=_kiosk_pre())


@app.route("/kiosk/rate", methods=["GET", "POST"])
@app.route("/en/kiosk/rate", methods=["GET", "POST"])
@kiosk_required
def kiosk_rate():
    lang = g.lang
    con = db()
    row, error, stage = None, None, "find"
    cols = "SELECT * FROM tickets "
    if request.method == "POST":
        check_csrf()
        if request.form.get("action") == "rate":
            ref = norm_ref(clean(request.form.get("ref"), 30))
            row = con.execute(cols + "WHERE ref=?", (ref,)).fetchone() if REF_RE.match(ref) else None
            if not row or session.get("k_rate") != row["id"]:
                return redirect(_kiosk_pre() + "/rate")
            vals = read_rating_form(request.form)
            if row["status"] != "resolved":
                stage = "closed"
            elif not vals:
                stage, error = "rate", T[lang]["rt_missing"]
            else:
                ok_ = save_rating(con, row, *vals, via="kiosk")
                session.pop("k_rate", None)
                stage = ("thanks" if vals[1] else "reopened") if ok_ else "closed"
        else:
            if rate_hit("kr:%d" % g.kiosk["id"], 40, 600):
                abort(429)
            ref = norm_ref(clean(request.form.get("ref"), 30))
            key = norm_code(clean(request.form.get("key"), 20))
            if REF_RE.match(ref):
                r = con.execute(cols + "WHERE ref=?", (ref,)).fetchone()
                if r and ((not r["anonymous"] and len(key) == 4 and r["mobile"].endswith(key))
                          or (r["anonymous"] and r["follow_hash"] == follow_hash(ref, key))):
                    row = r
            if not row:
                error = T[lang]["k_rate_notfound"]
            elif row["status"] == "resolved":
                session["k_rate"] = row["id"]
                stage = "rate"
            elif row["status"] == "closed":
                stage = "closed"
            else:
                stage = "open"
    reply = row["reply"] if row is not None and stage == "rate" else ""
    return render_template("kiosk_rate.html", row=row, stage=stage, error=error, reply=reply, kpre=_kiosk_pre())


# ---------------------------------------------------------------- staff accounts
def hash_password(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "%s:%s" % (salt.hex(), h.hex())


def check_hash(stored, pw):
    try:
        salt_hex, hash_hex = stored.split(":")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), hash_hex)
    except Exception:
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # equal timing for unknown usernames
ENV_ADMIN = {"id": 0, "username": ADMIN_USER, "display_name": "المشرف العام", "role": "admin", "dept_id": None}


def _env_admin_ver():
    return hashlib.sha256(ADMIN_PASSWORD_HASH.encode()).hexdigest()[:16]


def current_user():
    if "user" in g:
        return g.user
    g.user = None
    uid = session.get("uid")
    if uid is None or time.time() - session.get("at", 0) > ADMIN_SESSION_SECONDS:
        if uid is not None:
            session.clear()
        return None
    if uid == 0:
        if ADMIN_USER and ADMIN_PASSWORD_HASH and session.get("ver") == _env_admin_ver():
            g.user = dict(ENV_ADMIN)
    else:
        r = db().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
        # a password change or suspension bumps session_ver and ends every open session of that account
        if r and session.get("ver") == r["session_ver"]:
            g.user = dict(r)
    if g.user is None:
        session.clear()
    return g.user


def is_admin_user(u):
    return bool(u) and u["role"] == "admin"


def login_required(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not current_user():
            return redirect(url_for("admin_login"))
        return fn(*a, **kw)
    return w


def admin_only(fn):
    @wraps(fn)
    def w(*a, **kw):
        u = current_user()
        if not u:
            return redirect(url_for("admin_login"))
        if not is_admin_user(u):
            abort(404)
        return fn(*a, **kw)
    return w


@app.context_processor
def inject_staff():
    if not request.path.startswith("/admin"):
        return {}
    u = current_user()
    return dict(me=u, me_admin=is_admin_user(u), roles=ROLES)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    con = db()
    configured = bool(ADMIN_USER and ADMIN_PASSWORD_HASH) or bool(
        con.execute("SELECT 1 FROM users WHERE active=1 LIMIT 1").fetchone())
    if request.method == "POST":
        check_csrf()
        ip = client_ip()
        username = clean(request.form.get("username"), 64).lower()
        # 5 wrong passwords per account per 15 min; a generous per-IP cap because a hospital shares one IP
        if rate_peek("alu:" + username, 5, 900) or rate_peek("al:" + ip, 40, 900):
            abort(429)
        pw = request.form.get("password", "")[:200]
        uid = None
        ver = None
        r = con.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if r:
            if check_hash(r["pw_hash"], pw):
                uid, ver = r["id"], r["session_ver"]
                con.execute("UPDATE users SET last_login=? WHERE id=?", (now_utc(), r["id"]))
                con.commit()
        elif ADMIN_USER and ADMIN_PASSWORD_HASH and hmac.compare_digest(username.encode(), ADMIN_USER.lower().encode()):
            if check_hash(ADMIN_PASSWORD_HASH, pw):
                uid, ver = 0, _env_admin_ver()
        else:
            check_hash(_DUMMY_HASH, pw)
        if uid is not None:
            session.clear()
            session.permanent = True
            session["uid"] = uid
            session["ver"] = ver
            session["at"] = time.time()
            csrf_token()
            return redirect(url_for("admin_list"))
        rate_add("al:" + ip)
        rate_add("alu:" + username)
        error = "بيانات الدخول غير صحيحة."
    return render_template("admin_login.html", error=error, configured=configured)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    check_csrf()
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin/password", methods=["GET", "POST"])
@login_required
def admin_password():
    u = current_user()
    msg, err = None, None
    if request.method == "POST" and u["id"] != 0:
        check_csrf()
        cur = request.form.get("current", "")[:200]
        new = request.form.get("new", "")[:200]
        r = db().execute("SELECT pw_hash FROM users WHERE id=?", (u["id"],)).fetchone()
        if not check_hash(r["pw_hash"], cur):
            err = "كلمة المرور الحالية غير صحيحة."
        elif len(new) < 10:
            err = "كلمة المرور الجديدة يجب ألا تقل عن 10 خانات."
        elif new != request.form.get("new2", ""):
            err = "تأكيد كلمة المرور غير مطابق."
        else:
            db().execute("UPDATE users SET pw_hash=?, session_ver=session_ver+1 WHERE id=?",
                         (hash_password(new), u["id"]))
            db().commit()
            session["ver"] = u["session_ver"] + 1  # keep this session, end the others
            msg = "تم تغيير كلمة المرور."
    return render_template("admin_password.html", msg=msg, err=err)


# ---------------------------------------------------------------- ticket list
def _visible(u):
    """SQL restriction to the tickets this staff member may see."""
    if is_admin_user(u):
        return [], []
    return ["dept_id=?"], [u["dept_id"] or -1]


def _overdue_sql():
    return ("(status IN ('new','escalated','in_progress') AND due_at<>'' AND due_at<?)", now_utc())


def _filters(u, default_status=""):
    f = {k: clean(request.args.get(k), 60) for k in ("status", "facility", "type", "q", "topic", "dept", "late",
                                                        "channel", "mine")}
    f["status"] = f["status"] or default_status
    where, args = _visible(u)
    if f["status"] == "open":
        where.append("status IN ('new','escalated','in_progress')")
    elif f["status"] == "act":
        where.append("status IN ('new','escalated')")
    elif f["status"] == "all":
        pass
    elif f["status"] in STATUSES:
        where.append("status=?"); args.append(f["status"])
    else:
        f["status"] = ""
    if f["facility"] in FACILITIES:
        where.append("facility=?"); args.append(f["facility"])
    else:
        f["facility"] = ""
    if f["type"] in REQ_TYPES:
        where.append("req_type=?"); args.append(f["type"])
    else:
        f["type"] = ""
    if f["topic"]:
        where.append("topic=?"); args.append(f["topic"])
    if is_admin_user(u) and as_id(f["dept"]):
        where.append("dept_id=?"); args.append(as_id(f["dept"]))
    else:
        f["dept"] = ""
    if f["channel"] in CHANNELS:
        where.append("channel=?"); args.append(f["channel"])
    else:
        f["channel"] = ""
    if f["mine"] == "1" and u["id"]:
        where.append("assigned_user_id=?"); args.append(u["id"])
    else:
        f["mine"] = ""
    if f["late"] == "1":
        s, a = _overdue_sql()
        where.append(s); args.append(a)
    else:
        f["late"] = ""
    if f["q"]:
        like = "%" + f["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(ref LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' OR emp_no LIKE ? ESCAPE '\\' "
                     "OR email LIKE ? ESCAPE '\\' OR mobile LIKE ? ESCAPE '\\' OR message LIKE ? ESCAPE '\\')")
        args += [like] * 6
    return f, (" WHERE " + " AND ".join(where)) if where else "", args


def _topic_names():
    names = {d["key"]: d["name_ar"] for d in all_depts()}
    names[GENERAL_TOPIC] = "عام / أخرى"
    return names


@app.route("/admin/open")
@login_required
def admin_open():
    """Quick jump: type a ticket number (e.g. the one a walk-in employee shows you)."""
    ref = norm_ref(clean(request.args.get("ref"), 30))
    if REF_RE.match(ref):
        r = db().execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone()
        u = current_user()
        if r and (is_admin_user(u) or r["dept_id"] == u["dept_id"]):
            return redirect(url_for("admin_ticket", ref=ref))
    return redirect(url_for("admin_list", notfound=ref[:20]))


@app.route("/admin")
@login_required
def admin_list():
    u = current_user()
    # with no filter at all, staff land on the work that is still open
    no_filter = not any(request.args.get(k) for k in ("status", "late", "q", "dept", "topic", "type", "channel",
                                                      "facility", "mine", "page"))
    f, where, args = _filters(u, "open" if no_filter else "")
    try:
        page = min(100000, max(1, int(request.args.get("page", "1"))))
    except ValueError:
        page = 1
    per = 30
    con = db()
    now = now_utc()
    total = con.execute("SELECT COUNT(*) FROM tickets" + where, args).fetchone()[0]
    # most urgent first: open (late first, then nearest deadline), then waiting for rating, then closed (newest)
    rows = con.execute(
        "SELECT * FROM tickets" + where +
        " ORDER BY CASE WHEN status IN ('new','escalated','in_progress') THEN 0 WHEN status='resolved' THEN 1 ELSE 2 END,"
        " CASE WHEN status IN ('new','escalated','in_progress') AND due_at<>'' AND due_at<? THEN 0 ELSE 1 END,"
        " CASE WHEN status IN ('new','escalated','in_progress') THEN due_at ELSE '' END, id DESC LIMIT ? OFFSET ?",
        args + [now, per, (page - 1) * per]).fetchall()
    vw, va = _visible(u)
    vsql = (" WHERE " + " AND ".join(vw)) if vw else ""
    counts = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM tickets" + vsql + " GROUP BY status", va)}
    osql, oarg = _overdue_sql()
    late = con.execute("SELECT COUNT(*) FROM tickets WHERE " + " AND ".join(vw + [osql]), va + [oarg]).fetchone()[0]
    mine = 0
    if u["id"]:
        mine = con.execute("SELECT COUNT(*) FROM tickets WHERE assigned_user_id=? AND status IN "
                           "('new','escalated','in_progress')", (u["id"],)).fetchone()[0]
    # live appointment per listed ticket, for the "what it needs" column
    appts = {}
    ids = [r["id"] for r in rows]
    if ids:
        for a in con.execute("SELECT ticket_id, status, slot, kind FROM appointments WHERE ticket_id IN (%s) AND "
                             "status NOT IN ('done','no_show','cancelled') ORDER BY id" % ",".join("?" * len(ids)), ids):
            appts[a["ticket_id"]] = a
    users = {r[0]: r[1] for r in con.execute("SELECT id, display_name FROM users")}
    depts = all_depts()
    summary = []
    if is_admin_user(u):
        per_dept = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT dept_id, SUM(status IN ('new','escalated','in_progress')), SUM(" + osql + ") "
            "FROM tickets GROUP BY dept_id", [oarg])}
        summary = [(d, per_dept.get(d["id"], (0, 0))) for d in depts if d["active"] or d["id"] in per_dept]
    from urllib.parse import quote
    qs = "&".join("%s=%s" % (k, quote(v)) for k, v in f.items() if v)
    adv = "&".join("%s=%s" % (k, quote(v)) for k, v in f.items() if v and k not in ("status", "late"))
    my_dept = dept_by_id(u["dept_id"]) if u["dept_id"] else None
    return render_template("admin_list.html", rows=rows, f=f, total=total, page=page, per=per,
                           counts=counts, late=late, mine=mine, statuses=STATUSES, types=REQ_TYPES,
                           facilities=FACILITIES, qs=qs, adv=adv, depts=depts,
                           dept_names={d["id"]: d["name_ar"] for d in depts}, users=users, appts=appts,
                           topic_names=_topic_names(), summary=summary, now=now, my_dept=my_dept,
                           moved=clean(request.args.get("moved"), 30), channels=CHANNELS,
                           notfound=clean(request.args.get("notfound"), 20),
                           adv_open=any(f[k] for k in ("dept", "topic", "type", "channel", "facility", "mine")))


# ---------------------------------------------------------------- one ticket
EVENT_KINDS = {"create": "تقديم التذكرة", "status": "تغيير الحالة", "reply": "رد على الموظف",
               "note": "ملاحظة داخلية", "escalate": "تصعيد / إحالة", "topic": "تعديل التصنيف",
               "photo": "إرفاق صور", "resolve": "إنهاء وإرسال للتقييم", "rating": "تقييم الموظف",
               "autoclose": "إغلاق تلقائي", "close": "إغلاق دون تقييم", "reopen": "إعادة فتح",
               "assign": "استلام", "newcode": "رمز متابعة جديد", "appt": "موعد حضوري"}


def _load_ticket(ref, u):
    if not REF_RE.match(ref):
        abort(404)
    row = db().execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone()
    if not row or not (is_admin_user(u) or (u["dept_id"] and row["dept_id"] == u["dept_id"])):
        abort(404)
    return row


@app.route("/admin/t/<ref>", methods=["GET", "POST"])
@login_required
def admin_ticket(ref):
    u = current_user()
    con = db()
    row = _load_ticket(ref, u)
    actor = "%s (%s)" % (u["display_name"], u["username"])
    err = None
    if request.method == "POST":
        check_csrf()
        action = request.form.get("action", "")
        ts = now_utc()
        if action in ("save", "resolve"):
            reply = clean(request.form.get("reply"), 3000)
            photos, perr = read_photos(request.files.getlist("photos"))
            if perr:
                return _render_ticket(row, u, ERR[perr][0])
            if row["status"] not in OPEN_STATUSES and not (row["status"] == "resolved" and action == "save"):
                abort(400)
            if action == "resolve" and len(reply) < 2:
                return _render_ticket(row, u, "اكتب الرد على الموظف قبل إنهاء التذكرة وإرسالها للتقييم.")
            sets, vals = ["updated_at=?"], [ts]
            if u["id"] and (row["assigned_user_id"] is None or action == "resolve"):
                sets.append("assigned_user_id=?"); vals.append(u["id"])
            if reply != row["reply"]:
                sets.append("reply=?"); vals.append(reply)
                log_event(con, row["id"], actor, "reply", reply)
                if reply and not row["first_response_at"]:
                    sets.append("first_response_at=?"); vals.append(ts)
            if photos:
                store_photos(con, row["id"], photos, "staff", actor)
                log_event(con, row["id"], actor, "photo", "%d صورة مرفقة مع الرد (يراها الموظف)" % len(photos))
            if action == "resolve" and row["status"] != "resolved":
                rate_due = add_workdays(ts, RATE_WINDOW_DAYS)
                sets += ["status=?", "resolved_at=?", "rate_due_at=?"]; vals += ["resolved", ts, rate_due]
                if not row["first_response_at"] and "first_response_at=?" not in sets:
                    sets.append("first_response_at=?"); vals.append(ts)
                log_event(con, row["id"], actor, "resolve",
                          "أُرسل الرد للموظف لتقييمه. تُغلق تلقائيًا إن لم يقيّم حتى %s." % fmt_dt(rate_due))
            elif action == "save" and row["status"] in ("new", "escalated"):
                sets.append("status=?"); vals.append("in_progress")
                log_event(con, row["id"], actor, "status", "قيد المعالجة")
            con.execute("UPDATE tickets SET " + ", ".join(sets) + " WHERE id=?", vals + [row["id"]])
            con.commit()
            return redirect(url_for("admin_ticket", ref=ref, saved=1))
        if action == "close":
            reason = clean(request.form.get("close_note"), 1000)
            if row["status"] == "closed":
                abort(400)
            if len(reason) < 3:
                return _render_ticket(row, u, "اكتب سبب الإغلاق دون تقييم (مثل: مكررة، أو لا تخص الإدارة).")
            con.execute("UPDATE tickets SET status='closed', closed_at=?, close_reason='staff', updated_at=?, "
                        "assigned_user_id=COALESCE(assigned_user_id, ?) WHERE id=?",
                        (ts, ts, u["id"] or None, row["id"]))
            log_event(con, row["id"], actor, "close", reason)
            con.commit()
            return redirect(url_for("admin_ticket", ref=ref, saved=1))
        if action == "reopen":
            if row["status"] not in ("resolved", "closed"):
                abort(400)
            d = dept_by_id(row["dept_id"])
            con.execute("UPDATE tickets SET status='in_progress', closed_at='', close_reason='', rate_due_at='', "
                        "resolved_at='', due_at=?, updated_at=?, sla_breached=MAX(sla_breached, ?) WHERE id=?",
                        (add_workdays(ts, d["sla_days"] if d else 3), ts, 1 if leg_was_late(row, ts) else 0,
                         row["id"]))
            log_event(con, row["id"], actor, "reopen", clean(request.form.get("reopen_note"), 1000))
            con.commit()
            return redirect(url_for("admin_ticket", ref=ref, saved=1))
        if action == "newcode":
            # the employee lost the follow-up code: issue a new one and read it to them by phone
            code = new_follow_code()
            con.execute("UPDATE tickets SET follow_hash=?, updated_at=? WHERE id=?",
                        (follow_hash(row["ref"], code), ts, row["id"]))
            log_event(con, row["id"], actor, "newcode", "أُصدر رمز متابعة جديد وأُلغي الرمز السابق.")
            con.commit()
            session["new_code"] = [row["ref"], code]
            return redirect(url_for("admin_ticket", ref=ref, saved=1))
        if action == "take":
            if row["status"] not in OPEN_STATUSES:
                abort(400)
            if u["id"]:
                con.execute("UPDATE tickets SET assigned_user_id=?, updated_at=? WHERE id=?", (u["id"], ts, row["id"]))
                log_event(con, row["id"], actor, "assign", "استلم التذكرة")
                con.commit()
            return redirect(url_for("admin_ticket", ref=ref, saved=1))
        if action == "note":
            text = clean(request.form.get("note"), 3000)
            if len(text) < 2:
                err = "اكتب نص الملاحظة."
            else:
                log_event(con, row["id"], actor, "note", text)
                con.execute("UPDATE tickets SET updated_at=? WHERE id=?", (ts, row["id"]))
                con.commit()
                return redirect(url_for("admin_ticket", ref=ref, saved=1) + "#timeline")
        elif action == "escalate":
            if row["status"] not in OPEN_STATUSES:
                abort(400)
            to = as_id(request.form.get("to_dept"))
            reason = clean(request.form.get("reason"), 2000)
            d = dept_by_id(to) if to else None
            if not d or not d["active"] or d["id"] == row["dept_id"]:
                err = "اختر القسم الذي ستُحال إليه التذكرة."
            elif len(reason) < 5:
                err = "اكتب سبب التصعيد ليعرف القسم المستلم ما المطلوب."
            else:
                con.execute("UPDATE tickets SET dept_id=?, status='escalated', due_at=?, assigned_user_id=NULL, "
                            "updated_at=?, sla_breached=MAX(sla_breached, ?) WHERE id=?",
                            (d["id"], add_workdays(ts, d["sla_days"]), ts, 1 if leg_was_late(row, ts) else 0,
                             row["id"]))
                log_event(con, row["id"], actor, "escalate", reason, row["dept_id"], d["id"])
                con.commit()
                if is_admin_user(u):
                    return redirect(url_for("admin_ticket", ref=ref, saved=1))
                return redirect(url_for("admin_list", moved=ref))
        elif action == "topic":
            if row["status"] == "closed":
                abort(400)
            tp = request.form.get("topic", "")
            names = _topic_names()
            if tp in names and tp != row["topic"]:
                con.execute("UPDATE tickets SET topic=?, updated_at=? WHERE id=?", (tp, ts, row["id"]))
                log_event(con, row["id"], actor, "topic", "%s ← %s" % (names[tp], names.get(row["topic"], "—")))
                con.commit()
            return redirect(url_for("admin_ticket", ref=ref, saved=1))
        else:
            abort(400)
    return _render_ticket(row, u, err)


def _render_ticket(row, u, err=None):
    con = db()
    depts = all_depts()
    dnames = {d["id"]: d["name_ar"] for d in depts}
    events = con.execute("SELECT * FROM events WHERE ticket_id=? ORDER BY id", (row["id"],)).fetchall()
    photos = con.execute("SELECT * FROM attachments WHERE ticket_id=? ORDER BY id", (row["id"],)).fetchall()
    ratings = con.execute("SELECT * FROM ratings WHERE ticket_id=? ORDER BY id", (row["id"],)).fetchall()
    assignee = con.execute("SELECT display_name FROM users WHERE id=?", (row["assigned_user_id"],)).fetchone() \
        if row["assigned_user_id"] else None
    actx = appointments.ticket_panel_ctx(con, row)
    actx["appt_err"] = session.pop("appt_err", None)
    actx["appt_done"] = session.pop("appt_done", None)
    nc = session.pop("new_code", None)
    new_code = nc[1] if nc and nc[0] == row["ref"] else ""
    return render_template("admin_ticket.html", ratings=ratings, new_code=new_code, **actx, assignee=assignee, channels=CHANNELS,
                           close_reasons=CLOSE_REASONS, rate_days=RATE_WINDOW_DAYS, open_statuses=OPEN_STATUSES, tk=row, statuses=STATUSES, types=REQ_TYPES,
                           saved=request.args.get("saved") == "1", err=err, events=events, kinds=EVENT_KINDS,
                           dept_names=dnames, depts=[d for d in depts if d["active"] and d["id"] != row["dept_id"]],
                           topic_names=_topic_names(), now=now_utc(), photos=photos, max_photos=MAX_PHOTOS,
                           can_delete=is_admin_user(u))


@app.route("/admin/f/<tok>")
@login_required
def admin_photo(tok):
    if not TOKEN_RE.match(tok):
        abort(404)
    r = db().execute("SELECT t.ref FROM attachments a JOIN tickets t ON t.id=a.ticket_id WHERE a.token=?",
                     (tok,)).fetchone()
    if not r:
        abort(404)
    _load_ticket(r[0], current_user())  # 404 unless this user may see the ticket
    return send_photo(tok)


@app.route("/admin/t/<ref>/delete", methods=["POST"])
@admin_only
def admin_delete(ref):
    check_csrf()
    if not REF_RE.match(ref):
        abort(404)
    con = db()
    r = con.execute("SELECT id FROM tickets WHERE ref=?", (ref,)).fetchone()
    if r:
        delete_photos(con, r[0])
    con.execute("DELETE FROM events WHERE ticket_id=(SELECT id FROM tickets WHERE ref=?)", (ref,))
    con.execute("DELETE FROM tickets WHERE ref=?", (ref,))
    con.commit()
    return redirect(url_for("admin_list"))


# ---------------------------------------------------------------- sections (departments)
def _dept_form(form):
    v = {
        "name_ar": clean(form.get("name_ar"), 60),
        "name_en": clean(form.get("name_en"), 80),
        "selectable": 1 if form.get("selectable") == "1" else 0,
        "active": 1 if form.get("active") == "1" else 0,
    }
    try:
        v["sla_days"] = min(30, max(1, int(form.get("sla_days", "3"))))
    except ValueError:
        v["sla_days"] = 3
    try:
        v["sort"] = min(9999, max(0, int(form.get("sort", "100"))))
    except ValueError:
        v["sort"] = 100
    if not v["name_en"]:
        v["name_en"] = v["name_ar"]
    return v


@app.route("/admin/departments", methods=["GET", "POST"])
@admin_only
def admin_departments():
    con = db()
    err, msg = None, None
    if request.method == "POST":
        check_csrf()
        v = _dept_form(request.form)
        did = request.form.get("id", "")
        if len(v["name_ar"]) < 2:
            err = "اكتب اسم القسم."
        elif as_id(did):
            d = dept_by_id(as_id(did))
            if not d:
                abort(404)
            if d["key"] in (INTAKE_KEY, COMPLAINTS_KEY):
                v["active"] = 1  # the two routing sections cannot be switched off
                v["selectable"] = 0
            con.execute("UPDATE departments SET name_ar=?, name_en=?, sla_days=?, selectable=?, active=?, sort=? "
                        "WHERE id=?", (v["name_ar"], v["name_en"], v["sla_days"], v["selectable"], v["active"],
                                       v["sort"], d["id"]))
            con.commit()
            msg = "تم حفظ القسم."
        else:
            key = "d%s" % secrets.token_hex(3)
            con.execute("INSERT INTO departments(key,name_ar,name_en,sla_days,selectable,active,sort) "
                        "VALUES(?,?,?,?,?,1,?)", (key, v["name_ar"], v["name_en"], v["sla_days"],
                                                  v["selectable"], v["sort"]))
            con.commit()
            msg = "تمت إضافة القسم."
    counts = {r[0]: r[1] for r in con.execute("SELECT dept_id, COUNT(*) FROM users WHERE active=1 GROUP BY dept_id")}
    staff = {}
    for r in con.execute("SELECT dept_id, display_name FROM users WHERE active=1 AND role='staff' ORDER BY display_name"):
        staff.setdefault(r[0], []).append(r[1])
    osql, oarg = _overdue_sql()
    opens = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT dept_id, SUM(status IN ('new','escalated','in_progress')), SUM(" + osql + ") FROM tickets GROUP BY dept_id",
        [oarg])}
    depts = all_depts()
    no_staff = [d for d in depts if d["active"] and not staff.get(d["id"])]
    return render_template("admin_departments.html", depts=depts, counts=counts, staff=staff, opens=opens,
                           no_staff=no_staff, err=err, msg=msg, system=(INTAKE_KEY, COMPLAINTS_KEY),
                           add_open=bool(err) and not request.form.get("id"))


# ---------------------------------------------------------------- user accounts
@app.route("/admin/users", methods=["GET", "POST"])
@admin_only
def admin_users():
    me = current_user()
    con = db()
    err, msg = None, None
    if request.method == "POST":
        check_csrf()
        uid = request.form.get("id", "")
        name = clean(request.form.get("display_name"), 60)
        role = request.form.get("role", "staff")
        dept = request.form.get("dept_id", "")
        dept_id = as_id(dept) if as_id(dept) and dept_by_id(as_id(dept)) else None
        pw = request.form.get("password", "")[:200]
        if role not in ROLES:
            abort(400)
        if len(name) < 3:
            err = "اكتب اسم الموظف."
        elif role == "staff" and not dept_id:
            err = "اختر قسم الموظف."
        elif as_id(uid):
            r = con.execute("SELECT * FROM users WHERE id=?", (as_id(uid),)).fetchone()
            if not r:
                abort(404)
            active = 1 if request.form.get("active") == "1" else 0
            if r["id"] == me["id"] and (not active or role != "admin"):
                err = "لا يمكنك إيقاف حسابك أو سحب صلاحية الإشراف منه."
            elif pw and len(pw) < 10:
                err = "كلمة المرور يجب ألا تقل عن 10 خانات."
            else:
                con.execute("UPDATE users SET display_name=?, role=?, dept_id=?, active=? WHERE id=?",
                            (name, role, dept_id, active, r["id"]))
                if pw:
                    con.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(pw), r["id"]))
                if pw or not active:
                    con.execute("UPDATE users SET session_ver=session_ver+1 WHERE id=?", (r["id"],))
                con.commit()
                msg = "تم حفظ الحساب%s." % (" وتغيير كلمة المرور" if pw else "")
        else:
            username = clean(request.form.get("username"), 32).lower()
            if not USERNAME_RE.match(username):
                err = "اسم المستخدم: أحرف إنجليزية صغيرة وأرقام و . _ - فقط (3 إلى 32 خانة)."
            elif username == ADMIN_USER.lower() or con.execute(
                    "SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                err = "اسم المستخدم مستخدم من قبل."
            elif len(pw) < 10:
                err = "كلمة المرور يجب ألا تقل عن 10 خانات."
            else:
                con.execute("INSERT INTO users(username,display_name,pw_hash,role,dept_id,created_at) "
                            "VALUES(?,?,?,?,?,?)", (username, name, hash_password(pw), role, dept_id, now_utc()))
                con.commit()
                msg = "تم إنشاء الحساب. أعطِ الموظف اسم المستخدم وكلمة المرور، ويستطيع تغييرها بعد الدخول."
    users = con.execute("SELECT * FROM users ORDER BY active DESC, role, dept_id, display_name").fetchall()
    depts = all_depts()
    active = [x for x in users if x["active"]]
    groups = [("المشرفون العامّون", None, [x for x in active if x["role"] == "admin"])]
    for d in depts:
        members = [x for x in active if x["role"] == "staff" and x["dept_id"] == d["id"]]
        if members or d["active"]:
            groups.append((d["name_ar"], d, members))
    orphan = [x for x in active if x["role"] == "staff" and not any(x["dept_id"] == d["id"] for d in depts)]
    if orphan:
        groups.append(("بلا قسم", None, orphan))
    never = [x for x in active if not x["last_login"]]
    return render_template("admin_users.html", users=users, depts=depts, groups=groups,
                           suspended=[x for x in users if not x["active"]], never=never,
                           empty_depts=[g for g in groups if g[1] and g[1]["active"] and not g[2]],
                           dept_names={d["id"]: d["name_ar"] for d in depts}, err=err, msg=msg,
                           suggested=secrets.token_urlsafe(9), pre_dept=as_id(request.args.get("dept")),
                           add_open=(bool(err) and not request.form.get("id")) or bool(request.args.get("dept")))


@app.route("/admin/kiosks", methods=["GET", "POST"])
@admin_only
def admin_kiosks():
    con = db()
    msg, err = None, None
    if request.method == "POST":
        check_csrf()
        action = request.form.get("action", "")
        if action == "activate":
            name = clean(request.form.get("name"), 60)
            if len(name) < 2:
                err = "اكتب اسمًا للجهاز (مثل: آيباد مدخل الإدارة)."
            else:
                tok = secrets.token_urlsafe(32)
                u = current_user()
                con.execute("INSERT INTO kiosks(name,token_hash,created_at,created_by) VALUES(?,?,?,?)",
                            (name, kiosk_hash(tok), now_utc(), u["username"]))
                con.commit()
                session.clear()  # the supervisor is logged out; the device now only shows the reception screens
                resp = redirect("/kiosk")
                resp.set_cookie(KIOSK_COOKIE, tok, max_age=400 * 86400, secure=COOKIE_SECURE, httponly=True,
                                samesite="Lax", path="/")
                return resp
        elif action in ("disable", "enable"):
            kid = request.form.get("id", "")
            if as_id(kid):
                con.execute("UPDATE kiosks SET active=? WHERE id=?", (1 if action == "enable" else 0, as_id(kid)))
                con.commit()
                msg = "تم تحديث الجهاز."
    today = _utc_of_day(datetime.now(RIYADH).date())
    kiosks = con.execute("SELECT k.*, (SELECT COUNT(*) FROM tickets t WHERE t.kiosk_id=k.id) AS n, "
                         "(SELECT COUNT(*) FROM tickets t WHERE t.kiosk_id=k.id AND t.created_at>=?) AS n_today "
                         "FROM kiosks k ORDER BY active DESC, id DESC", (today,)).fetchall()
    stale = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    active = [k for k in kiosks if k["active"]]
    return render_template("admin_kiosks.html", kiosks=kiosks, msg=msg, err=err, active=active,
                           quiet=[k for k in active if not k["last_seen"] or k["last_seen"] < stale],
                           add_open=bool(err) or not active)


# ---------------------------------------------------------------- indicators
def _parse_day(s, default):
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default
    return d if 2020 <= d.year <= 2100 else default


def _utc_of_day(d):
    """Start of a Riyadh calendar day, as the stored UTC string."""
    return datetime(d.year, d.month, d.day, tzinfo=RIYADH).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _hours(a, b):
    ta, tb = _ts(a), _ts(b)
    return (tb - ta).total_seconds() / 3600 if ta and tb and tb >= ta else None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _pct(a, b):
    return round(100.0 * a / b) if b else None


def _dur(h):
    if h is None:
        return "—"
    if h < 24:
        return "%s ساعة" % (max(1, round(h)) if h >= 1 else "أقل من 1")
    return "%.1f يوم" % (h / 24)


app.jinja_env.filters["dur"] = _dur


def days_ar(n):
    """Arabic number agreement: 1 يوم، 2 يومان، 3–10 أيام، 11+ يومًا."""
    n = int(n)
    return "يوم واحد" if n == 1 else "يومان" if n == 2 else "%d أيام" % n if 3 <= n <= 10 else "%d يومًا" % n


app.jinja_env.filters["days_ar"] = days_ar


def compute_stats(u, args):
    today = datetime.now(RIYADH).date()
    d_to = _parse_day(args.get("to"), today)
    d_from = _parse_day(args.get("from"), d_to - timedelta(days=29))
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    if (d_to - d_from).days > 730:
        d_from = d_to - timedelta(days=730)
    f = {"from": d_from.isoformat(), "to": d_to.isoformat(), "dept": "", "channel": ""}
    where, params = _visible(u)
    where = list(where)
    if is_admin_user(u) and as_id(args.get("dept")):
        f["dept"] = str(as_id(args.get("dept")))
        where.append("dept_id=?"); params.append(int(f["dept"]))
    if args.get("channel") in CHANNELS:
        f["channel"] = args.get("channel")
        where.append("channel=?"); params.append(f["channel"])
    lo, hi = _utc_of_day(d_from), _utc_of_day(d_to + timedelta(days=1))
    con = db()
    base = (" AND " + " AND ".join(where)) if where else ""
    rows = con.execute("SELECT * FROM tickets WHERE created_at>=? AND created_at<?" + base, [lo, hi] + params).fetchall()
    now = now_utc()
    rat = {}
    sub = "SELECT id FROM tickets WHERE created_at>=? AND created_at<?" + base
    esc = {r[0] for r in con.execute("SELECT DISTINCT ticket_id FROM events WHERE kind='escalate' AND ticket_id IN ("
                                     + sub + ")", [lo, hi] + params)}
    for r in con.execute("SELECT * FROM ratings WHERE ticket_id IN (" + sub + ") ORDER BY id", [lo, hi] + params):
        rat.setdefault(r["ticket_id"], []).append(r)
    users = {r["id"]: r["display_name"] for r in con.execute("SELECT id, display_name FROM users")}
    dnames = {d["id"]: d["name_ar"] for d in all_depts()}
    tnames = _topic_names()

    def finish(r):
        return r["resolved_at"] or r["closed_at"] or ""

    def summarize(rs):
        n = len(rs)
        closed = [r for r in rs if r["status"] == "closed"]
        done = [r for r in rs if finish(r)]
        on_time = [r for r in done if r["due_at"] and not r["sla_breached"] and finish(r) <= r["due_at"]]
        allr = [x for r in rs for x in rat.get(r["id"], [])]
        reached = [r for r in rs if r["resolved_at"] or r["close_reason"] in ("rated", "auto")]
        rated_t = [r for r in reached if rat.get(r["id"])]
        return {
            "n": n, "closed": len(closed),
            "open": sum(1 for r in rs if r["status"] in OPEN_STATUSES),
            "waiting": sum(1 for r in rs if r["status"] == "resolved"),
            "late": sum(1 for r in rs if r["status"] in OPEN_STATUSES and r["due_at"] and r["due_at"] < now),
            "sla": _pct(len(on_time), len(done)), "done": len(done),
            "first": _avg([_hours(r["created_at"], r["first_response_at"]) for r in rs if r["first_response_at"]]),
            "resolve": _avg([_hours(r["created_at"], finish(r)) for r in done]),
            "resolve_med": _median([_hours(r["created_at"], finish(r)) for r in done]),
            "esc": sum(1 for r in rs if r["id"] in esc),
            "esc_pct": _pct(sum(1 for r in rs if r["id"] in esc), n),
            "nrat": len(allr), "stars": _avg([x["stars"] for x in allr]),
            "csat": _pct(sum(1 for x in allr if x["stars"] >= 4), len(allr)),
            "unresolved": sum(1 for x in allr if not x["resolved"]),
            "resp": _pct(len(rated_t), len(reached)),
            "auto": sum(1 for r in rs if r["close_reason"] == "auto"),
            "staff_closed": sum(1 for r in rs if r["close_reason"] == "staff"),
            "walkin": sum(1 for r in rs if r["channel"] == "walkin"),
            "anon": sum(1 for r in rs if r["anonymous"]),
        }

    def group(keyf, namef):
        g_ = {}
        for r in rows:
            g_.setdefault(keyf(r), []).append(r)
        out = [(namef(k), summarize(v)) for k, v in g_.items()]
        return sorted(out, key=lambda x: -x[1]["n"])

    total = summarize(rows)
    by = {
        "dept": group(lambda r: r["dept_id"], lambda k: dnames.get(k, "—")),
        "topic": group(lambda r: r["topic"], lambda k: tnames.get(k, "—")),
        "type": group(lambda r: r["req_type"], lambda k: REQ_TYPES.get(k, k)),
        "channel": group(lambda r: r["channel"], lambda k: CHANNELS.get(k, k)),
        "facility": group(lambda r: r["facility"], lambda k: k or "لم تُذكر"),
        "staff": group(lambda r: r["assigned_user_id"],
                       lambda k: users.get(k, "غير مستلمة") if k else "غير مستلمة"),
    }
    # daily (or weekly for long ranges) received vs closed
    days = (d_to - d_from).days + 1
    step = 7 if days > 62 else 1
    buckets = []
    d = d_from
    while d <= d_to:
        buckets.append(d)
        d += timedelta(days=step)
    def bucket_of(iso):
        t = _ts(iso)
        if not t:
            return None
        dd = t.astimezone(RIYADH).date()
        k = (dd - d_from).days // step
        return k if 0 <= k < len(buckets) else None
    rec = [0] * len(buckets)
    clo = [0] * len(buckets)
    for r in rows:
        k = bucket_of(r["created_at"])
        if k is not None:
            rec[k] += 1
    cw = (" AND " + " AND ".join(where)) if where else ""
    for (c_at,) in con.execute("SELECT closed_at FROM tickets WHERE closed_at>=? AND closed_at<?" + cw,
                               [lo, hi] + params):
        k = bucket_of(c_at)
        if k is not None:
            clo[k] += 1
    series = [(b.strftime("%m-%d"), rec[i], clo[i]) for i, b in enumerate(buckets)]
    low = []
    for r in rows:
        for x in rat.get(r["id"], []):
            if x["stars"] <= 2 or not x["resolved"]:
                low.append((r, x))
    low.sort(key=lambda t: t[1]["at"], reverse=True)
    appt = appointments.stats(con, lo, hi, int(f["dept"]) if f["dept"] else (None if is_admin_user(u) else (u["dept_id"] or -1)))
    return dict(f=f, total=total, by=by, series=series, step=step, low=low[:50], appt=appt,
                depts=all_depts(), channels=CHANNELS, period_days=days)


@app.route("/admin/stats")
@login_required
def admin_stats():
    u = current_user()
    s = compute_stats(u, request.args)
    my_dept = dept_by_id(u["dept_id"]) if u["dept_id"] else None
    return render_template("admin_stats.html", s=s, my_dept=my_dept,
                           presets=_stat_presets())


def _stat_presets():
    t = datetime.now(RIYADH).date()
    m0 = t.replace(day=1)
    prev_end = m0 - timedelta(days=1)
    return [("آخر 7 أيام", t - timedelta(days=6), t), ("آخر 30 يومًا", t - timedelta(days=29), t),
            ("هذا الشهر", m0, t), ("الشهر الماضي", prev_end.replace(day=1), prev_end),
            ("آخر 90 يومًا", t - timedelta(days=89), t), ("هذه السنة", t.replace(month=1, day=1), t)]


@app.route("/admin/stats.csv")
@login_required
def admin_stats_csv():
    s = compute_stats(current_user(), request.args)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["الفترة", s["f"]["from"], s["f"]["to"]])
    head = ["", "المستلمة", "المغلقة", "المفتوحة", "بانتظار التقييم", "المتأخرة", "الالتزام بالمهلة %",
            "متوسط أول رد (ساعة)", "متوسط زمن الإنجاز (ساعة)", "المصعّدة", "عدد التقييمات", "متوسط التقييم",
            "نسبة الرضا %", "لم يُحل", "نسبة من قيّم %", "أُغلقت تلقائيًا"]

    def line(name, x):
        return [_csv_safe(v) for v in (name, x["n"], x["closed"], x["open"], x["waiting"], x["late"], x["sla"],
                round(x["first"], 1) if x["first"] is not None else "",
                round(x["resolve"], 1) if x["resolve"] is not None else "", x["esc"], x["nrat"],
                round(x["stars"], 2) if x["stars"] is not None else "", x["csat"], x["unresolved"], x["resp"],
                x["auto"])]
    w.writerow([]); w.writerow(head); w.writerow(line("الإجمالي", s["total"]))
    titles = {"dept": "حسب القسم", "topic": "حسب الموضوع", "type": "حسب النوع", "channel": "حسب القناة",
              "facility": "حسب المنشأة", "staff": "حسب الموظف المسؤول"}
    for k, title in titles.items():
        w.writerow([]); w.writerow([title]); w.writerow(head)
        for name, x in s["by"][k]:
            w.writerow(line(name, x))
    name = "indicators-%s-%s.csv" % (s["f"]["from"], s["f"]["to"])
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})


# ---------------------------------------------------------------- export
def _csv_safe(v):
    v = "" if v is None else str(v)
    if v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        v = "'" + v
    return v


@app.route("/admin/export.csv")
@login_required
def admin_export():
    u = current_user()
    f, where, args = _filters(u)
    rows = db().execute("SELECT * FROM tickets" + where + " ORDER BY id DESC", args).fetchall()
    dn = {d["id"]: d["name_ar"] for d in all_depts()}
    tn = _topic_names()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["رقم التذكرة", "تاريخ الإنشاء (توقيت الرياض)", "آخر تحديث", "الحالة", "نوع الطلب", "الموضوع",
                "القسم الحالي", "المهلة", "مجهول", "الاسم", "الرقم الوظيفي", "البريد", "الجوال", "المنشأة",
                "الفئة الوظيفية", "النص", "الرد", "لغة التقديم"])
    for r in rows:
        w.writerow([_csv_safe(x) for x in (
            r["ref"], fmt_dt(r["created_at"]), fmt_dt(r["updated_at"]), STATUSES.get(r["status"], r["status"]),
            REQ_TYPES.get(r["req_type"], r["req_type"]), tn.get(r["topic"], r["topic"]), dn.get(r["dept_id"], ""),
            fmt_dt(r["due_at"]) if r["due_at"] else "", "نعم" if r["anonymous"] else "", r["name"], r["emp_no"],
            r["email"], r["mobile"], r["facility"], r["job_cat"], r["message"], r["reply"], r["lang"])])
    out = "﻿" + buf.getvalue()
    name = "tickets-%s.csv" % datetime.now(RIYADH).strftime("%Y%m%d-%H%M")
    return Response(out, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})


# ---------------------------------------------------------------- static site
STATIC_PAGES = {"index.html", "faq.html", "contact.html", "links.html", "journey.html",
                "en/index.html", "en/faq.html", "en/contact.html", "en/links.html", "en/journey.html"}
STATIC_DIRS = {"assets", "infographics"}


@app.route("/health")
def health():
    return "ok", 200, {"Content-Type": "text/plain"}


@app.route("/", defaults={"p": "index.html"})
@app.route("/<path:p>")
def static_site(p):
    if p == "en":
        return redirect("/en/", 308)
    if p == "en/":
        p = "en/index.html"
    top = p.split("/", 1)[0]
    if p in STATIC_PAGES or (top in STATIC_DIRS and "/" in p):
        return send_from_directory(SITE_DIR, p, max_age=300)
    abort(404)


import appointments  # noqa: E402,F401  (registers its routes and hooks; needs everything above)
import reports  # noqa: E402,F401  (Excel reports)

init_db()
