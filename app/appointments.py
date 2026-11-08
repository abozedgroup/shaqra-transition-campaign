# -*- coding: utf-8 -*-
"""In-person appointments and the walk-in queue (per section).

- A section books a time for the employee (the employee asks; the section decides; the employee confirms).
- Walk-ins at the reception device join today's queue with an expected wait; when the section is closed,
  busy or outside working hours the device offers to request an appointment instead.
- Section staff run "today's queue": call the next person, finish, or mark a no-show.

Times are stored as Riyadh local time "YYYY-MM-DD HH:MM" (appointments are a local, wall-clock concept).
Imported at the end of app.py, so `app` (the module) is fully defined here."""
import math
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import abort, g, redirect, render_template, request, session, url_for

import app as core
from app import (RIYADH, T, app, check_csrf, clean, current_user, db, dept_by_id, is_admin_user, log_event,
                 login_required, now_utc)

# ---------------------------------------------------------------- settings & schema
DEFAULT_START, DEFAULT_END, DEFAULT_SLOT, DEFAULT_CAP = "07:30", "14:30", 20, 1
BOOK_DAYS_AHEAD = 21          # how far ahead a section can book
BUSY_WAIT_MIN = 60            # above this expected wait the reception device offers an appointment instead
LIVE = ("booked", "confirmed", "change_requested", "checked_in", "serving")  # occupy a slot / the queue
STATUSES = {
    "requested": "طلب موعد – بانتظار الحجز",
    "booked": "محجوز – بانتظار تأكيد الموظف",
    "confirmed": "مؤكد",
    "change_requested": "طلب الموظف تغيير الموعد",
    "checked_in": "حاضر – بالانتظار",
    "serving": "قيد الخدمة الآن",
    "done": "انتهت الخدمة",
    "no_show": "لم يحضر",
    "cancelled": "ملغى",
}
STATUSES_EN = {
    "requested": "Requested – waiting for a time", "booked": "Booked – please confirm", "confirmed": "Confirmed",
    "change_requested": "Change requested", "checked_in": "Checked in – waiting", "serving": "Being served now",
    "done": "Done", "no_show": "Did not attend", "cancelled": "Cancelled",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS appointments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  dept_id INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'appointment',       -- appointment | walkin
  status TEXT NOT NULL,
  slot TEXT NOT NULL DEFAULT '',                    -- 'YYYY-MM-DD HH:MM' Riyadh time ('' while requested)
  emp_note TEXT NOT NULL DEFAULT '',                -- the employee's preference / reason for change
  staff_note TEXT NOT NULL DEFAULT '',              -- instructions for the employee (bring ID, room ...)
  requested_by TEXT NOT NULL DEFAULT '',            -- employee | staff | kiosk
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  checked_in_at TEXT NOT NULL DEFAULT '',
  called_at TEXT NOT NULL DEFAULT '',
  done_at TEXT NOT NULL DEFAULT '',
  served_by INTEGER
);
CREATE INDEX IF NOT EXISTS ix_ap_ticket ON appointments(ticket_id);
CREATE INDEX IF NOT EXISTS ix_ap_dept_slot ON appointments(dept_id, slot);
CREATE TABLE IF NOT EXISTS dept_closures(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dept_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  UNIQUE(dept_id, day)
);
"""
DEPT_COLS = [("appt_enabled", "INTEGER NOT NULL DEFAULT 1"), ("appt_start", "TEXT NOT NULL DEFAULT '%s'" % DEFAULT_START),
             ("appt_end", "TEXT NOT NULL DEFAULT '%s'" % DEFAULT_END), ("slot_min", "INTEGER NOT NULL DEFAULT %d" % DEFAULT_SLOT),
             ("capacity", "INTEGER NOT NULL DEFAULT %d" % DEFAULT_CAP), ("location", "TEXT NOT NULL DEFAULT ''")]


def migrate(con):
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute("PRAGMA table_info(departments)")]
    for name, decl in DEPT_COLS:
        if name not in cols:
            con.execute("ALTER TABLE departments ADD COLUMN %s %s" % (name, decl))


core.DB_HOOKS.append(migrate)


# ---------------------------------------------------------------- time helpers
def now_local():
    return datetime.now(RIYADH).replace(tzinfo=None, second=0, microsecond=0)


def fmt_local(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def parse_local(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def parse_hm(s, default):
    try:
        h, m = (int(x) for x in (s or "").split(":"))
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except ValueError:
        pass
    return default


def valid_hm(s):
    return parse_hm(s, None) is not None


def is_workday(d):
    return not core.is_off(d)  # Friday, Saturday and official holidays


AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_label(d, lang="ar"):
    return "%s %s" % ((AR_DAYS if lang == "ar" else EN_DAYS)[d.weekday()], d.strftime("%Y-%m-%d"))


def slot_label(s, lang="ar"):
    dt = parse_local(s)
    if not dt:
        return ""
    h = dt.hour % 12 or 12
    ampm = ("ص" if dt.hour < 12 else "م") if lang == "ar" else ("AM" if dt.hour < 12 else "PM")
    return "%s – %d:%02d %s" % (day_label(dt.date(), lang), h, dt.minute, ampm)


app.jinja_env.filters["slot"] = slot_label


def time_label(s):
    dt = parse_local(s)
    if not dt:
        return ""
    return "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "ص" if dt.hour < 12 else "م")


app.jinja_env.filters["slot_time"] = time_label


# ---------------------------------------------------------------- availability
def cfg(dept):
    return {
        "enabled": bool(dept["appt_enabled"]),
        "start": parse_hm(dept["appt_start"], (7, 30)),
        "end": parse_hm(dept["appt_end"], (14, 30)),
        "slot": max(5, min(240, dept["slot_min"] or DEFAULT_SLOT)),
        "cap": max(1, min(50, dept["capacity"] or DEFAULT_CAP)),
        "location": dept["location"] or "",
    }


def closure(con, dept_id, d):
    return con.execute("SELECT * FROM dept_closures WHERE dept_id=? AND day=?", (dept_id, d.isoformat())).fetchone()


def day_slots(con, dept, d, include_past=False, ignore_id=None):
    """[(slot 'YYYY-MM-DD HH:MM', free places)] for one day; [] on weekends and closure days.
    ignore_id: an appointment not counted as taking its slot (the one being rescheduled)."""
    c = cfg(dept)
    if not c["enabled"] or not is_workday(d) or closure(con, dept["id"], d):
        return []
    start = datetime(d.year, d.month, d.day, *c["start"])
    end = datetime(d.year, d.month, d.day, *c["end"])
    taken = {}
    for (s,) in con.execute("SELECT slot FROM appointments WHERE dept_id=? AND kind='appointment' AND slot LIKE ? "
                            "AND id<>? AND status IN (%s)" % ",".join("?" * len(LIVE)),
                            [dept["id"], d.isoformat() + "%", ignore_id or -1] + list(LIVE)):
        taken[s] = taken.get(s, 0) + 1
    now = now_local()
    out, t = [], start
    while t + timedelta(minutes=c["slot"]) <= end:
        s = fmt_local(t)
        if include_past or t > now:
            out.append((s, c["cap"] - taken.get(s, 0)))
        t += timedelta(minutes=c["slot"])
    return out


def bookable_days(con, dept, lang="ar"):
    """Next working days with at least one free place: [(iso day, label, free count)]."""
    out, d = [], now_local().date()
    for _ in range(BOOK_DAYS_AHEAD + 10):
        if len(out) >= BOOK_DAYS_AHEAD:
            break
        if is_workday(d):
            free = sum(max(0, f) for _, f in day_slots(con, dept, d))
            cl = closure(con, dept["id"], d)
            out.append((d.isoformat(), day_label(d, lang) + (" – مغلق: %s" % (cl["reason"] or "") if cl else ""), free))
        d += timedelta(days=1)
    return out


def next_free(con, dept, n=3):
    out, d = [], now_local().date()
    for _ in range(BOOK_DAYS_AHEAD + 10):
        for s, f in day_slots(con, dept, d):
            if f > 0:
                out.append(s)
                if len(out) >= n:
                    return out
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- queue
def avg_service_min(con, dept):
    """Average minutes per person over the last 30 days (called -> done); the slot length until there is data."""
    since = fmt_local(now_local() - timedelta(days=30))
    rows = con.execute("SELECT called_at, done_at FROM appointments WHERE dept_id=? AND status='done' "
                       "AND called_at<>'' AND done_at<>'' AND done_at>=?", (dept["id"], since)).fetchall()
    mins = []
    for a, b in rows:
        ta, tb = parse_local(a), parse_local(b)
        if ta and tb and tb >= ta:
            mins.append((tb - ta).total_seconds() / 60)
    if len(mins) >= 5:
        return max(3, min(120, sum(mins) / len(mins)))
    return cfg(dept)["slot"]


def queue_today(con, dept_id):
    """Waiting people today in calling order: appointments whose time has come first, then walk-ins by arrival."""
    today = now_local().date().isoformat()
    now = fmt_local(now_local())
    rows = con.execute("SELECT a.*, t.ref, t.name, t.anonymous FROM appointments a JOIN tickets t ON t.id=a.ticket_id "
                       "WHERE a.dept_id=? AND a.status='checked_in' AND a.checked_in_at LIKE ?",
                       (dept_id, today + "%")).fetchall()

    def key(r):
        due = r["kind"] == "appointment" and r["slot"] and r["slot"] <= now
        return (0 if due else 1, r["slot"] if due else r["checked_in_at"], r["id"])
    return sorted(rows, key=key)


def open_now(con, dept):
    """(is the section receiving people now?, reason code when not)."""
    c = cfg(dept)
    n = now_local()
    if not c["enabled"]:
        return False, "off"
    if not is_workday(n.date()):
        return False, "weekend"
    if closure(con, dept["id"], n.date()):
        return False, "closed"
    start = n.replace(hour=c["start"][0], minute=c["start"][1])
    end = n.replace(hour=c["end"][0], minute=c["end"][1])
    if n < start or n >= end:
        return False, "hours"
    return True, ""


def expected_wait(con, dept, position, avg=None):
    """Minutes until the person at `position` (1 = next) is called. Pass `avg` when computing many."""
    c = cfg(dept)
    serving = con.execute("SELECT COUNT(*) FROM appointments WHERE dept_id=? AND status='serving'", (dept["id"],)).fetchone()[0]
    units = position - 1 + serving          # people who must be served (or finish) before this person
    if units < c["cap"]:
        return 0                            # a counter is free
    return int(math.ceil((units - c["cap"] + 1) / c["cap"]) * (avg if avg is not None else avg_service_min(con, dept)))


def queue_position(con, appt):
    q = queue_today(con, appt["dept_id"])
    for i, r in enumerate(q):
        if r["id"] == appt["id"]:
            return i + 1
    return 0


# ---------------------------------------------------------------- lifecycle helpers
def latest(con, ticket_id):
    return con.execute("SELECT * FROM appointments WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (ticket_id,)).fetchone()


def active(con, ticket_id):
    return con.execute("SELECT * FROM appointments WHERE ticket_id=? AND status NOT IN ('done','no_show','cancelled') "
                       "ORDER BY id DESC LIMIT 1", (ticket_id,)).fetchone()


def follow_ticket(con, ticket_id, event, to_dept=None, actor="النظام"):
    """Keep a ticket's live appointment consistent with the ticket.
    event='escalate': the appointment moves with the ticket to the new section (a booked time is released and
                      becomes a request, because the new section has its own calendar);
    event='close':    any live appointment or queue entry is cancelled."""
    ap = active(con, ticket_id)
    if not ap:
        return
    ts = now_utc()
    if event == "escalate" and to_dept:
        if ap["status"] in ("checked_in", "serving"):
            con.execute("UPDATE appointments SET status='cancelled', updated_at=? WHERE id=?", (ts, ap["id"]))
            log_event(con, ticket_id, actor, "appt", "أُلغي دوره في الانتظار لأن التذكرة أُحيلت لقسم آخر.")
        else:
            had = ap["slot"] if ap["status"] in ("booked", "confirmed", "change_requested") else ""
            con.execute("UPDATE appointments SET dept_id=?, status='requested', slot='', emp_note=?, updated_at=? "
                        "WHERE id=?", (to_dept, (ap["emp_note"] + (" – كان محجوزًا " + slot_label(had) if had else "")).strip(" –"),
                                       ts, ap["id"]))
            log_event(con, ticket_id, actor, "appt", "انتقل طلب الموعد مع التذكرة إلى القسم الجديد ليحدد وقتًا"
                      + ((" (أُلغي الموعد السابق " + slot_label(had) + ")") if had else "") + ".")
    elif event == "close":
        con.execute("UPDATE appointments SET status='cancelled', updated_at=? WHERE id=?", (ts, ap["id"]))
        log_event(con, ticket_id, actor, "appt", "أُلغي الموعد لأن التذكرة أُغلقت.")


core.APPT_FOLLOW = follow_ticket


def create_request(con, ticket, note, by):
    """The employee, the reception device or a staff member asks for an in-person appointment.
    Takes the write lock so a double tap cannot create two requests; the caller commits."""
    d = dept_by_id(ticket["dept_id"])
    if ticket["anonymous"] or not d or not cfg(d)["enabled"]:
        return None
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    if active(con, ticket["id"]):
        return None
    ts = now_utc()
    cur = con.execute("INSERT INTO appointments(ticket_id,dept_id,kind,status,emp_note,requested_by,created_at,updated_at) "
                      "VALUES(?,?,?,?,?,?,?,?)", (ticket["id"], ticket["dept_id"], "appointment", "requested",
                                                  clean(note, 500), by, ts, ts))
    log_event(con, ticket["id"], {"kiosk": "الموظف (جهاز الاستقبال)", "staff": "القسم"}.get(by, "الموظف"), "appt",
              "طلب موعدًا حضوريًا" + ((": " + clean(note, 500)) if note else ""))
    return cur.lastrowid


def join_queue(con, ticket):
    """A walk-in joins today's queue at the reception device."""
    ts = now_utc()
    loc = fmt_local(now_local())
    cur = con.execute("INSERT INTO appointments(ticket_id,dept_id,kind,status,slot,requested_by,created_at,updated_at,"
                      "checked_in_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (ticket["id"], ticket["dept_id"], "walkin", "checked_in", loc, "kiosk", ts, ts, loc))
    log_event(con, ticket["id"], "الموظف (جهاز الاستقبال)", "appt", "انضم إلى طابور الانتظار (حضوري)")
    return cur.lastrowid


def sweep(con):
    """Past days: booked/confirmed appointments nobody came to become no-shows; a queue left open is closed."""
    today = now_local().date().isoformat()
    ts = now_utc()
    rows = con.execute("SELECT id, ticket_id, status FROM appointments WHERE status IN "
                       "('booked','confirmed','change_requested','checked_in','serving') AND slot<>'' AND slot<?",
                       (today,)).fetchall()
    if not rows:
        return
    for r in rows:
        if r["status"] in ("booked", "confirmed", "change_requested"):
            new, why = "no_show", "لم يحضر الموظف في موعده."
        elif r["status"] == "checked_in":
            new, why = "no_show", "حضر ولم يُستدعَ حتى نهاية اليوم (غادر)."
        else:
            new, why = "done", ""
        con.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?", (new, ts, r["id"]))
        if why:
            log_event(con, r["ticket_id"], "النظام", "appt", why)
    con.commit()


core.SWEEP_HOOKS.append(sweep)


# ---------------------------------------------------------------- staff: ticket page panel
def ticket_panel_ctx(con, tk, lang="ar"):
    """Data for the appointment panel on the staff ticket page."""
    d = dept_by_id(tk["dept_id"])
    ap = latest(con, tk["id"])
    day = request.args.get("appt_day", "")
    days = bookable_days(con, d) if d else []
    if not day or day not in [x[0] for x in days]:
        day = next((x[0] for x in days if x[2] > 0), days[0][0] if days else "")
    slots = day_slots(con, d, datetime.strptime(day, "%Y-%m-%d").date()) if day else []
    return dict(appt=ap, appt_days=days, appt_day=day, appt_slots=slots, appt_statuses=STATUSES,
                appt_cfg=cfg(d) if d else None, appt_dept=d, appt_mail=appt_mailto(tk, ap, d))


def appt_mailto(tk, ap, d):
    """A ready-made email for the staff member's own mail program (Outlook) to tell the employee
    the appointment. Nothing is sent by the server."""
    if not ap or ap["kind"] != "appointment" or not ap["slot"] or not tk["email"] or tk["anonymous"] \
            or ap["status"] not in ("booked", "confirmed", "change_requested"):
        return ""
    loc = cfg(d)["location"] if d else ""
    # behind the TLS proxy the app sees plain http; the public address is https
    status_url = ("https://%s/status" % request.host) if core.COOKIE_SECURE else request.host_url.rstrip("/") + "/status"
    lines = [
        "السلام عليكم %s،" % tk["name"],
        "",
        "حُجز لك موعد حضوري بخصوص طلبك رقم %s:" % tk["ref"],
        "",
        "الموعد: %s" % slot_label(ap["slot"]),
        "الجهة: %s" % (d["name_ar"] if d else ""),
    ]
    if loc:
        lines.append("المكان: %s" % loc)
    if ap["staff_note"]:
        lines.append("ملاحظة: %s" % ap["staff_note"])
    lines += [
        "",
        "يُرجى تأكيد الموعد أو طلب تغييره من صفحة «متابعة طلبي»:",
        status_url,
        "برقم التذكرة %s ورمز المتابعة الذي ظهر لك عند تقديم الطلب." % tk["ref"],
        "",
        "عند وصولك سجّل حضورك من جهاز الاستقبال عند المدخل («لدي موعد») برقم التذكرة وآخر 4 أرقام من جوالك.",
        "",
        "قسم العناية بالموظفين – نطاق شقراء الصحي",
    ]
    subject = "موعدك الحضوري – طلب رقم %s – %s" % (tk["ref"], slot_label(ap["slot"]))
    return "mailto:%s?subject=%s&body=%s" % (quote(tk["email"], safe="@"), quote(subject), quote("\r\n".join(lines)))


@app.route("/admin/t/<ref>/appt", methods=["POST"])
@login_required
def appt_staff_action(ref):
    check_csrf()
    u = current_user()
    tk = core._load_ticket(ref, u)
    con = db()
    actor = "%s (%s)" % (u["display_name"], u["username"])
    action = request.form.get("action", "")
    ap = active(con, tk["id"])
    ts = now_utc()
    back = url_for("admin_ticket", ref=ref, saved=1) + "#appt"  # opens the appointment tab
    if tk["anonymous"]:
        abort(400)
    if core.is_shared_view(u, tk):
        # the ticket is still at Employee Care: a booking would land in Care's calendar, so claim it first
        session["appt_err"] = "اسحب التذكرة لقسمك أولًا، ثم احجز الموعد في جدول قسمك."
        return redirect(back)
    if action == "book":
        if tk["status"] not in core.OPEN_STATUSES:
            abort(400)
        reschedulable = ("requested", "booked", "confirmed", "change_requested")
        if ap and not (ap["kind"] == "appointment" and ap["status"] in reschedulable):
            abort(400)  # checked in / being served / walk-in: not bookable from here
        d = dept_by_id(tk["dept_id"])
        slot = request.form.get("slot", "")
        dt = parse_local(slot)
        note = clean(request.form.get("staff_note"), 500)
        # check and write in one transaction so two people cannot take the last place of a slot
        if con.in_transaction:
            con.commit()
        con.execute("BEGIN IMMEDIATE")
        ap = active(con, tk["id"])  # again, inside the lock: a parallel booking may have just created one
        if ap and not (ap["kind"] == "appointment" and ap["status"] in reschedulable):
            con.rollback()
            return redirect(back)
        free = dict(day_slots(con, d, dt.date(), ignore_id=ap["id"] if ap else None)) if dt else {}
        if not dt or free.get(slot, 0) <= 0:
            con.rollback()
            session["appt_err"] = "هذا الوقت لم يعد متاحًا. اختر وقتًا آخر."
            return redirect(back)
        if ap:
            con.execute("UPDATE appointments SET status='booked', slot=?, staff_note=?, dept_id=?, updated_at=? "
                        "WHERE id=?", (slot, note, tk["dept_id"], ts, ap["id"]))
        else:
            con.execute("INSERT INTO appointments(ticket_id,dept_id,kind,status,slot,staff_note,requested_by,created_at,"
                        "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (tk["id"], tk["dept_id"], "appointment", "booked", slot, note, "staff", ts, ts))
        sets = "status='in_progress', " if tk["status"] in ("new", "escalated") else ""
        con.execute("UPDATE tickets SET " + sets + "updated_at=? WHERE id=?", (ts, tk["id"]))
        log_event(con, tk["id"], actor, "appt", "حجز موعدًا حضوريًا: %s%s" % (slot_label(slot), ("\n" + note) if note else ""))
        con.commit()
        return redirect(back)
    if not ap:
        abort(400)
    if action == "cancel":
        con.execute("UPDATE appointments SET status='cancelled', updated_at=? WHERE id=?", (ts, ap["id"]))
        log_event(con, tk["id"], actor, "appt", "ألغى الموعد. " + clean(request.form.get("why"), 300))
    elif action == "checkin" and ap["status"] in ("booked", "confirmed", "change_requested"):
        loc = fmt_local(now_local())
        con.execute("UPDATE appointments SET status='checked_in', checked_in_at=?, updated_at=? WHERE id=?", (loc, ts, ap["id"]))
        log_event(con, tk["id"], actor, "appt", "سجّل حضور الموظف.")
    elif action == "call" and ap["status"] in ("checked_in", "booked", "confirmed"):
        loc = fmt_local(now_local())
        con.execute("UPDATE appointments SET status='serving', called_at=?, checked_in_at=CASE WHEN checked_in_at='' "
                    "THEN ? ELSE checked_in_at END, served_by=?, updated_at=? WHERE id=?",
                    (loc, loc, u["id"] or None, ts, ap["id"]))
        con.execute("UPDATE tickets SET assigned_user_id=COALESCE(assigned_user_id, ?), status=CASE WHEN status IN "
                    "('new','escalated') THEN 'in_progress' ELSE status END, updated_at=? WHERE id=?",
                    (u["id"] or None, ts, tk["id"]))
        log_event(con, tk["id"], actor, "appt", "استدعى الموظف وبدأ الخدمة.")
    elif action == "done" and ap["status"] == "serving":
        con.execute("UPDATE appointments SET status='done', done_at=?, updated_at=? WHERE id=?",
                    (fmt_local(now_local()), ts, ap["id"]))
        log_event(con, tk["id"], actor, "appt", "انتهت الخدمة الحضورية.")
        con.commit()
        session["appt_done"] = 1
        return redirect(url_for("admin_ticket", ref=ref, saved=1))
    elif action == "notified" and ap["status"] in ("booked", "confirmed", "change_requested"):
        log_event(con, tk["id"], actor, "appt", "أبلغ الموظف بموعده عبر البريد.")
    elif action == "noshow" and ap["status"] in ("booked", "confirmed", "change_requested", "checked_in"):
        con.execute("UPDATE appointments SET status='no_show', updated_at=? WHERE id=?", (ts, ap["id"]))
        log_event(con, tk["id"], actor, "appt", "لم يحضر الموظف.")
    else:
        abort(400)
    con.commit()
    nxt = request.form.get("next", "")
    return redirect(url_for("appt_queue") if nxt == "queue" else back)


# ---------------------------------------------------------------- staff: today's queue and upcoming appointments
def _queue_dept(u):
    if is_admin_user(u):
        did = core.as_id(request.args.get("dept") or request.form.get("dept"))
        d = dept_by_id(did) if did else None
        if not d:
            d = core.dept_by_key(core.INTAKE_KEY)
        return d
    return dept_by_id(u["dept_id"]) if u["dept_id"] else None


@app.route("/admin/queue")
@login_required
def appt_queue():
    u = current_user()
    con = db()
    d = _queue_dept(u)
    if not d:
        return render_template("admin_queue.html", d=None, depts=[])
    today = now_local().date()
    q = queue_today(con, d["id"])
    base = ("SELECT a.*, t.ref, t.name, t.mobile, t.emp_no, t.anonymous FROM appointments a "
            "JOIN tickets t ON t.id=a.ticket_id WHERE a.dept_id=? ")
    serving = con.execute(base + "AND a.status='serving' ORDER BY a.called_at", (d["id"],)).fetchall()
    sched = con.execute(base + "AND a.kind='appointment' AND a.slot LIKE ? AND a.status IN "
                        "('booked','confirmed','change_requested') ORDER BY a.slot", (d["id"], today.isoformat() + "%")).fetchall()
    upcoming = con.execute(base + "AND a.kind='appointment' AND a.slot>? AND a.status IN "
                           "('booked','confirmed','change_requested') ORDER BY a.slot LIMIT 200",
                           (d["id"], (today + timedelta(days=1)).isoformat())).fetchall()
    requests_ = con.execute(base + "AND a.status IN ('requested','change_requested') ORDER BY a.created_at",
                            (d["id"],)).fetchall()
    finished = con.execute(base + "AND a.status IN ('done','no_show') AND (a.done_at LIKE ? OR (a.status='no_show' AND "
                           "a.slot LIKE ?)) ORDER BY a.updated_at DESC", (d["id"], today.isoformat() + "%",
                                                                           today.isoformat() + "%")).fetchall()
    closures = con.execute("SELECT * FROM dept_closures WHERE dept_id=? AND day>=? ORDER BY day",
                           (d["id"], today.isoformat())).fetchall()
    is_open, why = open_now(con, d)
    avg = avg_service_min(con, d)
    waits = [expected_wait(con, d, i + 1, avg) for i in range(len(q))]
    return render_template("admin_queue.html", d=d, c=cfg(d), q=list(zip(q, waits)), serving=serving, sched=sched,
                           upcoming=upcoming, requests=requests_, finished=finished, closures=closures,
                           is_open=is_open, why=why, avg=avg, statuses=STATUSES,
                           depts=core.all_depts(True) if is_admin_user(u) else [], today=today.isoformat(),
                           err=session.pop("appt_err", None))


@app.route("/admin/queue/closure", methods=["POST"])
@login_required
def appt_closure():
    check_csrf()
    u = current_user()
    d = _queue_dept(u)
    if not d:
        abort(404)
    con = db()
    action = request.form.get("action", "")
    if action == "add":
        try:
            day = datetime.strptime(request.form.get("day", ""), "%Y-%m-%d").date()
        except ValueError:
            session["appt_err"] = "اختر تاريخًا صحيحًا."
            return redirect(url_for("appt_queue", dept=d["id"]))
        reason = clean(request.form.get("reason"), 120)
        n_booked = con.execute("SELECT COUNT(*) FROM appointments WHERE dept_id=? AND slot LIKE ? AND status IN "
                               "('booked','confirmed','change_requested')", (d["id"], day.isoformat() + "%")).fetchone()[0]
        con.execute("INSERT OR REPLACE INTO dept_closures(dept_id,day,reason,created_by) VALUES(?,?,?,?)",
                    (d["id"], day.isoformat(), reason, u["username"]))
        con.commit()
        if n_booked:
            session["appt_err"] = ("تنبيه: يوجد %d موعد محجوز في هذا اليوم. أعد جدولتها من قائمة «المواعيد القادمة»."
                                   % n_booked)
    elif action == "remove":
        cid = core.as_id(request.form.get("id"))
        if cid:
            con.execute("DELETE FROM dept_closures WHERE id=? AND dept_id=?", (cid, d["id"]))
            con.commit()
    return redirect(url_for("appt_queue", dept=d["id"]) + "#closures")


@app.route("/admin/queue/settings", methods=["POST"])
@core.admin_only
def appt_settings():
    check_csrf()
    d = _queue_dept(current_user())
    if not d:
        abort(404)
    f = request.form
    start, end = f.get("appt_start", ""), f.get("appt_end", "")
    if not (valid_hm(start) and valid_hm(end)) or parse_hm(start, (0, 0)) >= parse_hm(end, (0, 0)):
        session["appt_err"] = "اكتب بداية ونهاية صحيحتين بصيغة 07:30 و 14:30، والبداية قبل النهاية."
        return redirect(url_for("appt_queue", dept=d["id"]) + "#settings")
    slot = core.as_id(f.get("slot_min")) or DEFAULT_SLOT
    cap = core.as_id(f.get("capacity")) or 1
    db().execute("UPDATE departments SET appt_enabled=?, appt_start=?, appt_end=?, slot_min=?, capacity=?, location=? "
                 "WHERE id=?", (1 if f.get("appt_enabled") == "1" else 0, "%02d:%02d" % parse_hm(start, (7, 30)),
                                "%02d:%02d" % parse_hm(end, (14, 30)), max(5, min(240, slot)), max(1, min(50, cap)),
                                clean(f.get("location"), 120), d["id"]))
    db().commit()
    session["appt_err"] = None
    return redirect(url_for("appt_queue", dept=d["id"], saved=1) + "#settings")


# ---------------------------------------------------------------- employee: follow-up page actions
@app.route("/status/appt", methods=["POST"])
@app.route("/en/status/appt", methods=["POST"])
def appt_employee_action():
    check_csrf()
    con = db()
    ref = core.norm_ref(clean(request.form.get("ref"), 30))
    tk = con.execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone() if core.REF_RE.match(ref) else None
    if not tk or tk["id"] not in session.get("st_ok", []) or tk["anonymous"]:
        abort(400)
    action = request.form.get("action", "")
    ap = active(con, tk["id"])
    ts = now_utc()
    note = clean(request.form.get("note"), 500)
    if action == "request" and not ap and tk["status"] in core.OPEN_STATUSES:
        create_request(con, tk, note, "employee")
    elif tk["status"] not in core.OPEN_STATUSES and action != "cancel":
        pass  # the ticket is finished: nothing to confirm or change
    elif action == "confirm" and ap and ap["status"] == "booked":
        con.execute("UPDATE appointments SET status='confirmed', updated_at=? WHERE id=?", (ts, ap["id"]))
        log_event(con, tk["id"], "الموظف", "appt", "أكّد الموعد.")
    elif action == "change" and ap and ap["status"] in ("booked", "confirmed"):
        con.execute("UPDATE appointments SET status='change_requested', emp_note=?, updated_at=? WHERE id=?",
                    (note, ts, ap["id"]))
        log_event(con, tk["id"], "الموظف", "appt", "طلب تغيير الموعد" + ((": " + note) if note else ""))
    elif action == "cancel" and ap and ap["status"] in ("requested", "booked", "confirmed", "change_requested"):
        con.execute("UPDATE appointments SET status='cancelled', updated_at=? WHERE id=?", (ts, ap["id"]))
        log_event(con, tk["id"], "الموظف", "appt", "ألغى الموعد." + ((" " + note) if note else ""))
    con.commit()
    session["st_show"] = tk["id"]
    return redirect(("/en" if g.lang == "en" else "") + "/status?show=1#appt")


def status_ctx(con, tk, lang):
    if not tk or tk["anonymous"]:
        return {}
    ap = latest(con, tk["id"])
    d = dept_by_id(ap["dept_id"]) if ap else None
    pos = wait = 0
    if ap and ap["status"] == "checked_in" and d:
        pos = queue_position(con, ap)
        wait = expected_wait(con, d, pos) if pos else 0
    return dict(appt=ap, appt_loc=cfg(d)["location"] if d else "", appt_st=(STATUSES if lang == "ar" else STATUSES_EN),
                appt_pos=pos, appt_wait=wait, can_request=(not ap or ap["status"] in ("done", "no_show", "cancelled"))
                and tk["status"] in core.OPEN_STATUSES)


# ---------------------------------------------------------------- reception device
def walkin_offer(con, tk, lang):
    """After a walk-in creates a request at the device: join the queue, or (closed / busy) request an appointment."""
    d = dept_by_id(tk["dept_id"])
    if not d or tk["anonymous"] or tk["req_type"] != "request" or not cfg(d)["enabled"]:
        return {}
    is_open, why = open_now(con, d)
    waiting = len(queue_today(con, d["id"]))
    wait = expected_wait(con, d, waiting + 1) if is_open else None
    busy = is_open and wait is not None and wait > BUSY_WAIT_MIN
    return dict(w_open=is_open, w_why=why, w_wait=wait, w_ahead=waiting, w_busy=busy,
                w_next=[slot_label(s, lang) for s in next_free(con, d, 2)])


@app.route("/kiosk/walkin", methods=["POST"])
@app.route("/en/kiosk/walkin", methods=["POST"])
@core.kiosk_required
def kiosk_walkin():
    """The walk-in chooses: wait in today's queue, or ask for an appointment."""
    check_csrf()
    con = db()
    st = session.get("k_walkin")
    if not st:
        return redirect(core._kiosk_pre())
    tk = con.execute("SELECT * FROM tickets WHERE id=?", (st,)).fetchone()
    if not tk:
        return redirect(core._kiosk_pre())
    if tk["anonymous"] or tk["req_type"] != "request" or tk["status"] not in core.OPEN_STATUSES:
        session.pop("k_walkin", None)
        return redirect(core._kiosk_pre())
    choice = request.form.get("choice", "")
    d = dept_by_id(tk["dept_id"])
    lang = g.lang
    if con.in_transaction:
        con.commit()
    con.execute("BEGIN IMMEDIATE")  # a double tap must not queue the person twice
    if choice == "wait" and not active(con, tk["id"]) and open_now(con, d)[0]:
        aid = join_queue(con, tk)
        con.commit()
        ap = con.execute("SELECT * FROM appointments WHERE id=?", (aid,)).fetchone()
        pos = queue_position(con, ap)
        session.pop("k_walkin", None)
        return render_template("kiosk_queue.html", kpre=core._kiosk_pre(), ref=tk["ref"], pos=pos,
                               wait=expected_wait(con, d, pos), dept=d["name_ar"] if lang == "ar" else d["name_en"],
                               loc=cfg(d)["location"])
    con.rollback()
    if choice == "appt":
        create_request(con, tk, clean(request.form.get("note"), 300), "kiosk")
        con.commit()
        session.pop("k_walkin", None)
        return render_template("kiosk_msg.html", kpre=core._kiosk_pre(), title=T[lang]["k_appt_req_h"],
                               msg=T[lang]["k_appt_req_p"] % tk["ref"], back=True)
    return redirect(core._kiosk_pre())


@app.route("/kiosk/checkin", methods=["GET", "POST"])
@app.route("/en/kiosk/checkin", methods=["GET", "POST"])
@core.kiosk_required
def kiosk_checkin():
    """'I have an appointment': ticket number + last 4 digits of the mobile -> checked in, with expected wait."""
    lang = g.lang
    con = db()
    err = None
    if request.method == "POST":
        check_csrf()
        if core.rate_hit("kr:%d" % g.kiosk["id"], 40, 600):  # same budget as the rating lookup
            abort(429)
        ref = core.norm_ref(clean(request.form.get("ref"), 30))
        key = core.norm_code(clean(request.form.get("key"), 20))
        tk = con.execute("SELECT * FROM tickets WHERE ref=?", (ref,)).fetchone() if core.REF_RE.match(ref) else None
        if not tk or tk["anonymous"] or len(key) != 4 or not tk["mobile"].endswith(key):
            err = T[lang]["k_rate_notfound"]
        else:
            ap = active(con, tk["id"])
            today = now_local().date().isoformat()
            if tk["status"] not in core.OPEN_STATUSES or not ap or ap["kind"] != "appointment" \
                    or not ap["slot"].startswith(today):
                err = T[lang]["k_ci_none"]
            elif ap["status"] in ("checked_in", "serving"):
                pass
            elif ap["status"] in ("booked", "confirmed", "change_requested"):
                loc = fmt_local(now_local())
                con.execute("UPDATE appointments SET status='checked_in', checked_in_at=?, updated_at=? WHERE id=?",
                            (loc, now_utc(), ap["id"]))
                log_event(con, tk["id"], "الموظف (جهاز الاستقبال)", "appt", "سجّل وصوله لموعده.")
                con.commit()
            else:
                err = T[lang]["k_ci_none"]
            if not err:
                ap = con.execute("SELECT * FROM appointments WHERE id=?", (ap["id"],)).fetchone()
                d = dept_by_id(ap["dept_id"])
                pos = queue_position(con, ap)
                return render_template("kiosk_queue.html", kpre=core._kiosk_pre(), ref=tk["ref"], pos=pos,
                                       wait=expected_wait(con, d, pos) if pos else 0, serving=ap["status"] == "serving",
                                       dept=d["name_ar"] if lang == "ar" else d["name_en"], loc=cfg(d)["location"],
                                       slot=ap["slot"])
    return render_template("kiosk_checkin.html", kpre=core._kiosk_pre(), error=err)


# ---------------------------------------------------------------- indicators
def stats(con, lo, hi, ticket_sql="", ticket_params=()):
    """Appointment and queue figures for appointments created in [lo, hi) (UTC strings, like tickets),
    for the tickets selected by ticket_sql (" WHERE ..." on tickets) – the same tickets as the rest of the page."""
    w, a = ["a.created_at>=? AND a.created_at<?"], [lo, hi]
    if ticket_sql:
        w.append("a.ticket_id IN (SELECT id FROM tickets" + ticket_sql + ")"); a.extend(ticket_params)
    rows = con.execute("SELECT a.* FROM appointments a WHERE " + " AND ".join(w), a).fetchall()
    appts = [r for r in rows if r["kind"] == "appointment"]
    walk = [r for r in rows if r["kind"] == "walkin"]
    booked = [r for r in appts if r["slot"]]
    finished = [r for r in booked if r["status"] in ("done", "no_show")]

    def minutes(x, y):
        ta, tb = parse_local(x), parse_local(y)
        return (tb - ta).total_seconds() / 60 if ta and tb and tb >= ta else None

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs)) if xs else None
    served = [r for r in rows if r["called_at"]]
    return {
        "requested": sum(1 for r in appts if r["requested_by"] in ("employee", "kiosk")),
        "booked": len(booked),
        "done": sum(1 for r in booked if r["status"] == "done"),
        "no_show": sum(1 for r in booked if r["status"] == "no_show"),
        "no_show_pct": round(100 * sum(1 for r in finished if r["status"] == "no_show") / len(finished)) if finished else None,
        "cancelled": sum(1 for r in appts if r["status"] == "cancelled"),
        "walkins": len(walk),
        "wait": avg([minutes(r["checked_in_at"], r["called_at"]) for r in served]),
        "service": avg([minutes(r["called_at"], r["done_at"]) for r in rows if r["status"] == "done"]),
        "pending": sum(1 for r in appts if r["status"] in ("requested", "change_requested")),
    }
