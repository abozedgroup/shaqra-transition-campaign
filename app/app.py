# -*- coding: utf-8 -*-
"""نظام تذاكر التواصل مع قسم العناية بالموظفين - نطاق شقراء الصحي.
Flask + SQLite. لا يُسجَّل أي بيان شخصي في السجلات."""
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
from datetime import datetime, timedelta, timezone

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
    "inquiry": "استفسار", "complaint": "شكوى",
    "suggestion": "اقتراح", "info_request": "طلب معلومات",
}
STATUSES = {"new": "جديدة", "in_progress": "قيد المعالجة", "closed": "مغلقة"}

EMAIL_RE = re.compile(r"^[a-z0-9][a-z0-9._%+\-]{0,63}@moh\.gov\.sa$")
MOBILE_RE = re.compile(r"^05\d{8}$")
EMPNO_RE = re.compile(r"^\d{3,10}$")
REF_RE = re.compile(r"^SHQ-\d{6}-[A-Z0-9]{5}$")
REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
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
"""


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


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
    g.is_app = p.startswith(("/ticket", "/status", "/admin", "/app-static"))


@app.errorhandler(400)
def e400(_e):
    g.is_app = True
    return render_template("msg.html", title="طلب غير صالح",
                           msg="انتهت صلاحية الصفحة أو الطلب غير صالح. ارجع للصفحة السابقة وحدّثها ثم أعد المحاولة."), 400


@app.errorhandler(404)
def e404(_e):
    g.is_app = True
    return render_template("msg.html", title="الصفحة غير موجودة", msg="لم نجد الصفحة المطلوبة."), 404


@app.errorhandler(413)
def e413(_e):
    g.is_app = True
    return render_template("msg.html", title="الطلب كبير", msg="حجم الطلب أكبر من المسموح."), 413


@app.errorhandler(429)
def e429(_e):
    g.is_app = True
    return render_template("msg.html", title="محاولات كثيرة",
                           msg="تجاوزت عدد المحاولات المسموح. انتظر بضع دقائق ثم أعد المحاولة."), 429


@app.errorhandler(500)
def e500(_e):
    g.is_app = True
    return render_template("msg.html", title="خطأ", msg="حدث خطأ غير متوقع. حاول لاحقًا أو راسل قسم العناية بالموظفين مباشرة."), 500


# ---------------------------------------------------------------- validation
def clean(s, maxlen):
    s = unicodedata.normalize("NFC", (s or "")).replace("\r\n", "\n").replace("\r", "\n")
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return s.strip()[:maxlen]


def validate_ticket(form):
    errors, v = {}, {}
    v["email"] = clean(form.get("email"), 120).lower()
    if not EMAIL_RE.match(v["email"]):
        errors["email"] = "البريد يجب أن يكون وزاريًا وينتهي بـ moh.gov.sa"
    v["mobile"] = clean(form.get("mobile"), 20).translate(AR_DIGITS).replace(" ", "")
    if not MOBILE_RE.match(v["mobile"]):
        errors["mobile"] = "رقم الجوال يجب أن يكون سعوديًا بصيغة 05XXXXXXXX"
    v["emp_no"] = clean(form.get("emp_no"), 20).translate(AR_DIGITS).replace(" ", "")
    if not EMPNO_RE.match(v["emp_no"]):
        errors["emp_no"] = "الرقم الوظيفي أرقام فقط (من 3 إلى 10 خانات)"
    v["name"] = clean(form.get("name"), 80)
    if len(v["name"]) < 3 or "\n" in v["name"]:
        errors["name"] = "اكتب الاسم (3 أحرف على الأقل)"
    v["facility"] = clean(form.get("facility"), 80)
    if v["facility"] not in FACILITIES:
        errors["facility"] = "اختر المنشأة"
    v["job_cat"] = clean(form.get("job_cat"), 80)
    if v["job_cat"] not in JOB_CATEGORIES:
        errors["job_cat"] = "اختر الفئة الوظيفية"
    v["req_type"] = clean(form.get("req_type"), 20)
    if v["req_type"] not in REQ_TYPES:
        errors["req_type"] = "اختر نوع الطلب"
    v["message"] = clean(form.get("message"), 3000)
    if len(v["message"]) < 10:
        errors["message"] = "اكتب نص الطلب (10 أحرف على الأقل)"
    if form.get("consent") != "1":
        errors["consent"] = "الموافقة على إشعار الخصوصية مطلوبة"
    return v, errors


def new_ref(con):
    stamp = datetime.now(RIYADH).strftime("%y%m%d")
    for _ in range(20):
        ref = "SHQ-%s-%s" % (stamp, "".join(secrets.choice(REF_ALPHABET) for _ in range(5)))
        if not con.execute("SELECT 1 FROM tickets WHERE ref=?", (ref,)).fetchone():
            return ref
    raise RuntimeError("ref")


# ---------------------------------------------------------------- public pages
@app.route("/ticket", methods=["GET", "POST"])
def ticket_form():
    values, errors = {}, {}
    if request.method == "POST":
        check_csrf()
        ip = client_ip()
        if rate_hit("tc:" + ip, 5, 600) or rate_hit("td:" + ip, 20, 86400):
            abort(429)
        if request.form.get("website"):  # honeypot
            return redirect(url_for("ticket_done"))
        values, errors = validate_ticket(request.form)
        if not errors:
            con = db()
            since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            n = con.execute("SELECT COUNT(*) FROM tickets WHERE email=? AND created_at>?",
                            (values["email"], since)).fetchone()[0]
            if n >= 5:
                abort(429)
            ref = new_ref(con)
            ts = now_utc()
            con.execute(
                "INSERT INTO tickets(ref,created_at,updated_at,email,mobile,emp_no,name,facility,job_cat,req_type,message)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (ref, ts, ts, values["email"], values["mobile"], values["emp_no"], values["name"],
                 values["facility"], values["job_cat"], values["req_type"], values["message"]))
            con.commit()
            session["done_ref"] = ref
            return redirect(url_for("ticket_done"))
    else:
        t = request.args.get("type", "")
        if t in REQ_TYPES:
            values["req_type"] = t
    return render_template("ticket_form.html", v=values, errors=errors, facilities=FACILITIES,
                           jobs=JOB_CATEGORIES, types=REQ_TYPES), (400 if errors else 200)


@app.route("/ticket/done")
def ticket_done():
    ref = session.pop("done_ref", None)
    return render_template("ticket_done.html", ref=ref)


@app.route("/status", methods=["GET", "POST"])
def status_lookup():
    result, error = None, None
    if request.method == "POST":
        check_csrf()
        ip = client_ip()
        if rate_hit("sl:" + ip, 10, 600):
            abort(429)
        ref = clean(request.form.get("ref"), 30).upper()
        email = clean(request.form.get("email"), 120).lower()
        row = None
        if REF_RE.match(ref) and EMAIL_RE.match(email):
            row = db().execute(
                "SELECT ref,created_at,updated_at,req_type,status,reply FROM tickets WHERE ref=? AND email=?",
                (ref, email)).fetchone()
        if row:
            result = row
        else:
            time.sleep(0.4)
            error = "لا توجد تذكرة مطابقة. تأكد من رقم التذكرة والبريد الوزاري المستخدم عند التقديم."
    return render_template("status.html", result=result, error=error, statuses=STATUSES, types=REQ_TYPES)


@app.route("/app-static/<path:name>")
def app_static(name):
    return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), name,
                               max_age=3600)


# ---------------------------------------------------------------- admin
def verify_password(pw):
    try:
        salt_hex, hash_hex = ADMIN_PASSWORD_HASH.split(":")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), hash_hex)
    except Exception:
        return False


def is_admin():
    if not session.get("admin"):
        return False
    if time.time() - session.get("admin_at", 0) > ADMIN_SESSION_SECONDS:
        session.clear()
        return False
    return True


def admin_required(fn):
    from functools import wraps

    @wraps(fn)
    def w(*a, **kw):
        if not is_admin():
            return redirect(url_for("admin_login"))
        return fn(*a, **kw)
    return w


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    configured = bool(ADMIN_USER and ADMIN_PASSWORD_HASH)
    if request.method == "POST":
        check_csrf()
        ip = client_ip()
        if rate_peek("al:" + ip, 5, 900):
            abort(429)
        user = request.form.get("username", "")
        pw = request.form.get("password", "")
        ok = configured and hmac.compare_digest(user.encode(), ADMIN_USER.encode()) and verify_password(pw[:200])
        if ok:
            session.clear()
            session.permanent = True
            session["admin"] = True
            session["admin_at"] = time.time()
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


def _filters():
    f = {k: clean(request.args.get(k), 60) for k in ("status", "facility", "type", "q")}
    where, args = [], []
    if f["status"] in STATUSES:
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
    if f["q"]:
        like = "%" + f["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(ref LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' OR emp_no LIKE ? ESCAPE '\\' "
                     "OR email LIKE ? ESCAPE '\\' OR mobile LIKE ? ESCAPE '\\' OR message LIKE ? ESCAPE '\\')")
        args += [like] * 6
    return f, (" WHERE " + " AND ".join(where)) if where else "", args


@app.route("/admin")
@admin_required
def admin_list():
    f, where, args = _filters()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    per = 30
    con = db()
    total = con.execute("SELECT COUNT(*) FROM tickets" + where, args).fetchone()[0]
    rows = con.execute("SELECT * FROM tickets" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                       args + [per, (page - 1) * per]).fetchall()
    counts = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM tickets GROUP BY status")}
    qs = "&".join("%s=%s" % (k, v) for k, v in f.items() if v)
    from urllib.parse import quote
    qs = "&".join("%s=%s" % (k, quote(v)) for k, v in f.items() if v)
    return render_template("admin_list.html", rows=rows, f=f, total=total, page=page, per=per,
                           counts=counts, statuses=STATUSES, types=REQ_TYPES, facilities=FACILITIES, qs=qs)


@app.route("/admin/t/<ref>", methods=["GET", "POST"])
@admin_required
def admin_ticket(ref):
    if not REF_RE.match(ref):
        abort(404)
    con = db()
    row = con.execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone()
    if not row:
        abort(404)
    saved = False
    if request.method == "POST":
        check_csrf()
        st = request.form.get("status", "")
        if st not in STATUSES:
            abort(400)
        reply = clean(request.form.get("reply"), 3000)
        note = clean(request.form.get("note"), 3000)
        con.execute("UPDATE tickets SET status=?, reply=?, note=?, updated_at=? WHERE ref=?",
                    (st, reply, note, now_utc(), ref))
        con.commit()
        row = con.execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone()
        saved = True
    return render_template("admin_ticket.html", t=row, statuses=STATUSES, types=REQ_TYPES, saved=saved)


@app.route("/admin/t/<ref>/delete", methods=["POST"])
@admin_required
def admin_delete(ref):
    check_csrf()
    if not REF_RE.match(ref):
        abort(404)
    con = db()
    con.execute("DELETE FROM tickets WHERE ref=?", (ref,))
    con.commit()
    return redirect(url_for("admin_list"))


def _csv_safe(v):
    v = "" if v is None else str(v)
    if v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        v = "'" + v
    return v


@app.route("/admin/export.csv")
@admin_required
def admin_export():
    f, where, args = _filters()
    rows = db().execute("SELECT * FROM tickets" + where + " ORDER BY id DESC", args).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["رقم التذكرة", "تاريخ الإنشاء (توقيت الرياض)", "آخر تحديث", "الحالة", "نوع الطلب", "الاسم",
                "الرقم الوظيفي", "البريد", "الجوال", "المنشأة", "الفئة الوظيفية", "النص", "الرد", "ملاحظة داخلية"])
    for r in rows:
        w.writerow([_csv_safe(x) for x in (
            r["ref"], fmt_dt(r["created_at"]), fmt_dt(r["updated_at"]), STATUSES.get(r["status"], r["status"]),
            REQ_TYPES.get(r["req_type"], r["req_type"]), r["name"], r["emp_no"], r["email"], r["mobile"],
            r["facility"], r["job_cat"], r["message"], r["reply"], r["note"])])
    out = "\ufeff" + buf.getvalue()
    name = "tickets-%s.csv" % datetime.now(RIYADH).strftime("%Y%m%d-%H%M")
    return Response(out, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})


# ---------------------------------------------------------------- static site
STATIC_PAGES = {"index.html", "faq.html", "contact.html"}
STATIC_DIRS = {"assets", "infographics", "kb"}


@app.route("/health")
def health():
    if request.args.get("dbg") == "1":
        import hashlib
        x = request.headers.get("X-Forwarded-For", "")
        return "pid=%s ip=%s hops=%d ra=%s" % (os.getpid(), hashlib.sha256(client_ip().encode()).hexdigest()[:8], len(x.split(",")) if x else 0, hashlib.sha256((request.remote_addr or "").encode()).hexdigest()[:6]), 200, {"Content-Type": "text/plain"}
    return "ok", 200, {"Content-Type": "text/plain"}


@app.route("/", defaults={"p": "index.html"})
@app.route("/<path:p>")
def static_site(p):
    top = p.split("/", 1)[0]
    if p in STATIC_PAGES or (top in STATIC_DIRS and "/" in p):
        return send_from_directory(SITE_DIR, p, max_age=300)
    abort(404)


init_db()
