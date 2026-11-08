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
REQ_TYPES = {
    "inquiry": "استفسار", "info_request": "طلب معلومات",
    "complaint": "شكوى", "feedback": "ملاحظة", "suggestion": "اقتراح",
}
# أنواع يجوز تقديمها دون الإفصاح عن البيانات، وتُوجَّه مباشرة لقسم الشكاوى
ANON_TYPES = ("complaint", "feedback", "suggestion")
STATUSES = {"new": "جديدة", "escalated": "محالة", "in_progress": "قيد المعالجة", "closed": "مغلقة"}
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
REF_RE = re.compile(r"^SHQ-\d{6}-[A-Z0-9]{5}$")
REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

app = Flask(__name__, static_folder=None, template_folder="templates")
app.config.update(
    MAX_CONTENT_LENGTH=32 * 1024,
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
"""

TICKET_NEW_COLS = [
    ("lang", "TEXT NOT NULL DEFAULT 'ar'"),
    ("topic", "TEXT NOT NULL DEFAULT ''"),
    ("dept_id", "INTEGER"),
    ("anonymous", "INTEGER NOT NULL DEFAULT 0"),
    ("follow_hash", "TEXT NOT NULL DEFAULT ''"),
    ("due_at", "TEXT NOT NULL DEFAULT ''"),
    ("closed_at", "TEXT NOT NULL DEFAULT ''"),
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
    g.is_app = p.startswith(("/ticket", "/status", "/admin", "/app-static", "/en/ticket", "/en/status"))
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


def validate_ticket(form, lang="ar"):
    i = 0 if lang == "ar" else 1
    errors, v = {}, {}
    v["req_type"] = clean(form.get("req_type"), 20)
    if v["req_type"] not in REQ_TYPES:
        errors["req_type"] = ERR["req_type"][i]
    v["topic"] = clean(form.get("topic"), 40)
    if v["topic"] not in [k for k, _ in topic_opts(lang)]:
        errors["topic"] = ERR["topic"][i]
    v["anonymous"] = form.get("anonymous") == "1" and v["req_type"] in ANON_TYPES
    v["message"] = clean(form.get("message"), 3000)
    if len(v["message"]) < 10:
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
    stamp = datetime.now(RIYADH).strftime("%y%m%d")
    for _ in range(20):
        ref = "SHQ-%s-%s" % (stamp, "".join(secrets.choice(REF_ALPHABET) for _ in range(5)))
        if not con.execute("SELECT 1 FROM tickets WHERE ref=?", (ref,)).fetchone():
            return ref
    raise RuntimeError("ref")


ERR_ORDER = ["req_type", "topic", "message", "name", "emp_no", "facility", "job_cat", "email", "mobile", "consent"]


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
        if not errors:
            con = db()
            if values["anonymous"]:
                if rate_hit("ta:" + ip, 5, 86400):
                    abort(429)
            else:
                since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                n = con.execute("SELECT COUNT(*) FROM tickets WHERE email=? AND created_at>?",
                                (values["email"], since)).fetchone()[0]
                if n >= 5:
                    abort(429)
            # complaints, feedback and suggestions go to their own section; everything else starts at Employee Care
            dept = dept_by_key(COMPLAINTS_KEY) if values["req_type"] in ANON_TYPES else None
            if not dept or not dept["active"]:
                dept = dept_by_key(INTAKE_KEY)
            ref = new_ref(con)
            ts = now_utc()
            code, fh = "", ""
            if values["anonymous"]:
                code = "".join(secrets.choice(REF_ALPHABET) for _ in range(8))
                fh = follow_hash(ref, code)
            cur = con.execute(
                "INSERT INTO tickets(ref,created_at,updated_at,email,mobile,emp_no,name,facility,job_cat,req_type,"
                "message,lang,topic,dept_id,anonymous,follow_hash,due_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ref, ts, ts, values["email"], values["mobile"], values["emp_no"], values["name"],
                 values["facility"], values["job_cat"], values["req_type"], values["message"], lang,
                 values["topic"], dept["id"], 1 if values["anonymous"] else 0, fh,
                 add_workdays(ts, dept["sla_days"])))
            log_event(con, cur.lastrowid, "الموظف" if not values["anonymous"] else "مقدّم مجهول", "create",
                      to_dept=dept["id"])
            con.commit()
            session["done_ref"] = ref
            session["done_code"] = code
            return redirect(pre + "/ticket/done")
    else:
        t = request.args.get("type", "")
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
    start = 1 if first_bad in ("", "req_type", "topic", "message") else (
        2 if first_bad in ("name", "emp_no", "facility", "job_cat") else 3)
    return render_template(
        "ticket_form.html", v=values, errors=errors, start=start,
        facilities=[(k, ar if lang == "ar" else en) for k, ar, en in FACILITY_OPTS],
        jobs=[(k, ar if lang == "ar" else en) for k, ar, en in JOB_OPTS],
        types=[(k, TYPES_I18N[k][i], TYPE_HELP[k][i]) for k in REQ_TYPES],
        anon_types=ANON_TYPES, topics=topic_opts(lang),
        err_msgs={k: ERR[k][i] for k in ERR}, err_order=ERR_ORDER,
    ), (400 if errors else 200)


@app.route("/ticket/done")
@app.route("/en/ticket/done")
def ticket_done():
    ref = session.pop("done_ref", None)
    code = session.pop("done_code", "")
    return render_template("ticket_done.html", ref=ref, code=code)


@app.route("/status", methods=["GET", "POST"])
@app.route("/en/status", methods=["GET", "POST"])
def status_lookup():
    lang = g.lang
    i = 0 if lang == "ar" else 1
    result, error, dept_name = None, None, ""
    if request.method == "POST":
        check_csrf()
        ip = client_ip()
        if rate_hit("sl:" + ip, 30, 600):
            abort(429)
        ref = clean(request.form.get("ref"), 30).upper()
        key = clean(request.form.get("email"), 120)
        row = None
        if REF_RE.match(ref):
            cols = "SELECT ref,created_at,updated_at,req_type,status,reply,dept_id,anonymous FROM tickets "
            if "@" in key:
                if EMAIL_RE.match(key.lower()):
                    row = db().execute(cols + "WHERE ref=? AND email=? AND anonymous=0",
                                       (ref, key.lower())).fetchone()
            else:
                code = norm_code(key)
                if len(code) == 8:
                    row = db().execute(cols + "WHERE ref=? AND anonymous=1 AND follow_hash=?",
                                       (ref, follow_hash(ref, code))).fetchone()
        if row:
            result = row
            d = dept_by_id(row["dept_id"])
            if d:
                dept_name = d["name_ar"] if lang == "ar" else d["name_en"]
        else:
            time.sleep(0.4)
            error = T[lang]["st_notfound"]
    return render_template("status.html", result=result, error=error, dept_name=dept_name,
                           statuses={k: v[i] for k, v in STATUSES_I18N.items()},
                           types={k: v[i] for k, v in TYPES_I18N.items()})


@app.route("/app-static/<path:name>")
def app_static(name):
    return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), name,
                               max_age=3600)


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
        if ADMIN_USER and ADMIN_PASSWORD_HASH:
            g.user = dict(ENV_ADMIN)
    else:
        r = db().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
        if r:
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
        if rate_peek("al:" + ip, 5, 900):
            abort(429)
        username = clean(request.form.get("username"), 64).lower()
        pw = request.form.get("password", "")[:200]
        uid = None
        r = con.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if r:
            if check_hash(r["pw_hash"], pw):
                uid = r["id"]
                con.execute("UPDATE users SET last_login=? WHERE id=?", (now_utc(), r["id"]))
                con.commit()
        elif ADMIN_USER and ADMIN_PASSWORD_HASH and hmac.compare_digest(username.encode(), ADMIN_USER.lower().encode()):
            if check_hash(ADMIN_PASSWORD_HASH, pw):
                uid = 0
        else:
            check_hash(_DUMMY_HASH, pw)
        if uid is not None:
            session.clear()
            session.permanent = True
            session["uid"] = uid
            session["at"] = time.time()
            csrf_token()
            return redirect(url_for("admin_list"))
        rate_add("al:" + ip)
        time.sleep(0.8)
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
            db().execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new), u["id"]))
            db().commit()
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


def _filters(u):
    f = {k: clean(request.args.get(k), 60) for k in ("status", "facility", "type", "q", "topic", "dept", "late")}
    where, args = _visible(u)
    if f["status"] == "open":
        where.append("status IN ('new','escalated','in_progress')")
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
    if is_admin_user(u) and f["dept"].isdigit():
        where.append("dept_id=?"); args.append(int(f["dept"]))
    else:
        f["dept"] = ""
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


@app.route("/admin")
@login_required
def admin_list():
    u = current_user()
    f, where, args = _filters(u)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    per = 30
    con = db()
    total = con.execute("SELECT COUNT(*) FROM tickets" + where, args).fetchone()[0]
    rows = con.execute("SELECT * FROM tickets" + where +
                       " ORDER BY CASE WHEN status='closed' THEN 1 ELSE 0 END, id DESC LIMIT ? OFFSET ?",
                       args + [per, (page - 1) * per]).fetchall()
    vw, va = _visible(u)
    vsql = (" WHERE " + " AND ".join(vw)) if vw else ""
    counts = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM tickets" + vsql + " GROUP BY status", va)}
    osql, oarg = _overdue_sql()
    late = con.execute("SELECT COUNT(*) FROM tickets WHERE " + " AND ".join(vw + [osql]), va + [oarg]).fetchone()[0]
    depts = all_depts()
    summary = []
    if is_admin_user(u):
        per_dept = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT dept_id, SUM(status IN ('new','escalated','in_progress')), SUM(" + osql + ") "
            "FROM tickets GROUP BY dept_id", [oarg])}
        summary = [(d, per_dept.get(d["id"], (0, 0))) for d in depts if d["active"] or d["id"] in per_dept]
    from urllib.parse import quote
    qs = "&".join("%s=%s" % (k, quote(v)) for k, v in f.items() if v)
    my_dept = dept_by_id(u["dept_id"]) if u["dept_id"] else None
    return render_template("admin_list.html", rows=rows, f=f, total=total, page=page, per=per,
                           counts=counts, late=late, statuses=STATUSES, types=REQ_TYPES, facilities=FACILITIES,
                           qs=qs, depts=depts, dept_names={d["id"]: d["name_ar"] for d in depts},
                           topic_names=_topic_names(), summary=summary, now=now_utc(), my_dept=my_dept,
                           moved=clean(request.args.get("moved"), 30))


# ---------------------------------------------------------------- one ticket
EVENT_KINDS = {"create": "تقديم التذكرة", "status": "تغيير الحالة", "reply": "رد على الموظف",
               "note": "ملاحظة داخلية", "escalate": "تصعيد / إحالة", "topic": "تعديل التصنيف"}


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
        if action == "update":
            st = request.form.get("status", "")
            if st not in STATUSES:
                abort(400)
            reply = clean(request.form.get("reply"), 3000)
            sets, vals = ["updated_at=?"], [ts]
            if st != row["status"]:
                sets.append("status=?"); vals.append(st)
                if st == "closed":
                    sets.append("closed_at=?"); vals.append(ts)
                elif row["status"] == "closed":  # reopened: a fresh deadline
                    d = dept_by_id(row["dept_id"])
                    sets += ["closed_at=?", "due_at=?"]; vals += ["", add_workdays(ts, d["sla_days"] if d else 3)]
                log_event(con, row["id"], actor, "status",
                          "%s ← %s" % (STATUSES[st], STATUSES.get(row["status"], row["status"])))
            if reply != row["reply"]:
                sets.append("reply=?"); vals.append(reply)
                log_event(con, row["id"], actor, "reply", reply)
            con.execute("UPDATE tickets SET " + ", ".join(sets) + " WHERE id=?", vals + [row["id"]])
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
            to = request.form.get("to_dept", "")
            reason = clean(request.form.get("reason"), 2000)
            d = dept_by_id(int(to)) if to.isdigit() else None
            if not d or not d["active"] or d["id"] == row["dept_id"]:
                err = "اختر القسم الذي ستُحال إليه التذكرة."
            elif len(reason) < 5:
                err = "اكتب سبب التصعيد ليعرف القسم المستلم ما المطلوب."
            else:
                con.execute("UPDATE tickets SET dept_id=?, status='escalated', due_at=?, closed_at='', updated_at=? "
                            "WHERE id=?", (d["id"], add_workdays(ts, d["sla_days"]), ts, row["id"]))
                log_event(con, row["id"], actor, "escalate", reason, row["dept_id"], d["id"])
                con.commit()
                if is_admin_user(u):
                    return redirect(url_for("admin_ticket", ref=ref, saved=1))
                return redirect(url_for("admin_list", moved=ref))
        elif action == "topic":
            tp = request.form.get("topic", "")
            names = _topic_names()
            if tp in names and tp != row["topic"]:
                con.execute("UPDATE tickets SET topic=?, updated_at=? WHERE id=?", (tp, ts, row["id"]))
                log_event(con, row["id"], actor, "topic", "%s ← %s" % (names[tp], names.get(row["topic"], "—")))
                con.commit()
            return redirect(url_for("admin_ticket", ref=ref, saved=1))
        else:
            abort(400)
    depts = all_depts()
    dnames = {d["id"]: d["name_ar"] for d in depts}
    events = con.execute("SELECT * FROM events WHERE ticket_id=? ORDER BY id", (row["id"],)).fetchall()
    return render_template("admin_ticket.html", tk=row, statuses=STATUSES, types=REQ_TYPES,
                           saved=request.args.get("saved") == "1", err=err, events=events, kinds=EVENT_KINDS,
                           dept_names=dnames, depts=[d for d in depts if d["active"] and d["id"] != row["dept_id"]],
                           topic_names=_topic_names(), now=now_utc(),
                           can_delete=is_admin_user(u))


@app.route("/admin/t/<ref>/delete", methods=["POST"])
@admin_only
def admin_delete(ref):
    check_csrf()
    if not REF_RE.match(ref):
        abort(404)
    con = db()
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
        elif did.isdigit():
            d = dept_by_id(int(did))
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
    return render_template("admin_departments.html", depts=all_depts(), counts=counts, err=err, msg=msg,
                           system=(INTAKE_KEY, COMPLAINTS_KEY))


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
        dept_id = int(dept) if dept.isdigit() and dept_by_id(int(dept)) else None
        pw = request.form.get("password", "")[:200]
        if role not in ROLES:
            abort(400)
        if len(name) < 3:
            err = "اكتب اسم الموظف."
        elif role == "staff" and not dept_id:
            err = "اختر قسم الموظف."
        elif uid.isdigit():
            r = con.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
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
    return render_template("admin_users.html", users=users, depts=depts,
                           dept_names={d["id"]: d["name_ar"] for d in depts}, err=err, msg=msg,
                           suggested=secrets.token_urlsafe(9))


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


init_db()
