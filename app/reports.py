# -*- coding: utf-8 -*-
"""Excel (.xlsx) reports for supervisors and sections.

One workbook per download, with the sheets the user picks: a summary of the indicators, one sheet per breakdown,
the detailed ticket list, ratings, appointments and the action log. Staff only ever get their own section.
Imported at the end of app.py."""
import io
import threading
from datetime import date, datetime, timedelta

from flask import Response, render_template, request
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter

import app as core
from app import (CHANNELS, CLOSE_REASONS, REQ_TYPES, RIYADH, STATUSES, all_depts, app, current_user, db,
                 is_admin_user, login_required)
import appointments as ap

SHEETS = [
    ("summary", "ملخص المؤشرات وتفصيلها حسب القسم والموظف والموضوع والقناة والمنشأة"),
    ("tickets", "قائمة التذاكر التفصيلية (كل تذكرة في سطر)"),
    ("ratings", "التقييمات وتعليقات الموظفين"),
    ("appts", "المواعيد الحضورية والانتظار"),
    ("events", "سجل الإجراءات على التذاكر"),
]
NAVY, LIGHT, LINE = "1B3A6B", "EAF2FB", "D5DDE8"
HEAD_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
BODY_FONT = Font(name="Arial", size=10)
TITLE_FONT = Font(name="Arial", bold=True, size=14, color=NAVY)
BOLD_FONT = Font(name="Arial", bold=True, size=10)
MAX_ROWS = 100000  # per sheet; beyond this the user is asked to pick a shorter period
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
ZEBRA = PatternFill("solid", fgColor="F6F9FD")
THIN = Border(bottom=Side(style="thin", color=LINE))
DT_FMT, D_FMT, PCT_FMT = "yyyy-mm-dd hh:mm", "yyyy-mm-dd", "0%"


# ---------------------------------------------------------------- helpers
def local_dt(iso):
    """Stored UTC ISO string -> naive Riyadh datetime for Excel (None if empty)."""
    t = core._ts(iso)
    return t.astimezone(RIYADH).replace(tzinfo=None) if t else None


def local_slot(s):
    return ap.parse_local(s) if s else None


# Workbooks are written in openpyxl's streaming ("write-only") mode: rows go straight to the file instead of
# building a styled object for every cell, so a two-year report takes seconds and little memory.
FORMULA_START = ("=", "+", "-", "@")


def cell(ws, value, fmt=None, bold=False, head=False):
    c = WriteOnlyCell(ws, value=value)
    if isinstance(value, str) and value[:1] in FORMULA_START:
        c.data_type = "s"  # text that looks like a formula stays text (no formula injection)
    if head:
        c.font, c.fill, c.alignment = HEAD_FONT, HEAD_FILL, Alignment(horizontal="center", vertical="center", wrap_text=True)
    elif bold:
        c.font = BOLD_FONT
    if fmt:
        c.number_format = fmt
    return c


def plain(ws, value, fmt=None):
    """Cheap path for the bulk of the data: only wrap values that need it."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return cell(ws, value, D_FMT)  # anonymous tickets carry a date only
    if fmt or (isinstance(value, str) and value[:1] in FORMULA_START):
        return cell(ws, value, fmt)
    return value


def table(ws, headers, rows, widths=None, formats=None, first=True):
    """Header + rows, with a filter and a frozen header when the table starts the sheet."""
    formats = formats or {}
    if first:
        for j, w in enumerate(widths or [], 1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = "A2"
    start = getattr(ws, "_shq_row", 0) + 1
    ws.append([cell(ws, h, head=True) for h in headers])
    n = 0
    for r in rows:
        ws.append([plain(ws, v, formats.get(j)) for j, v in enumerate(r, 1)])
        n += 1
    if first and n:
        ws.auto_filter.ref = "A%d:%s%d" % (start, get_column_letter(len(headers)), start + n)
    ws._shq_row = start + n
    return n


def line(ws, *values, bold=False):
    ws.append([cell(ws, v, DT_FMT if isinstance(v, datetime) else None, bold=bold and i == 0) if v is not None else None
               for i, v in enumerate(values)])
    ws._shq_row = getattr(ws, "_shq_row", 0) + 1


def new_sheet(wb, title):
    ws = wb.create_sheet(title=title[:31])
    ws.sheet_view.rightToLeft = True
    return ws


def scope(u, args):
    """Period and filters, shared with the indicators page."""
    s = core.compute_stats(u, args)
    d_from = datetime.strptime(s["f"]["from"], "%Y-%m-%d").date()
    d_to = datetime.strptime(s["f"]["to"], "%Y-%m-%d").date()
    lo, hi = core._utc_of_day(d_from), core._utc_of_day(d_to + timedelta(days=1))
    where, params = core._visible(u)
    where = list(where)
    if s["f"]["dept"]:
        where.append("dept_id=?"); params.append(int(s["f"]["dept"]))
    if s["f"]["channel"]:
        where.append("channel=?"); params.append(s["f"]["channel"])
    open_only = args.get("open") == "1"
    if open_only:
        where.append("status IN ('new','escalated','in_progress','resolved')")
    else:
        where = ["created_at>=? AND created_at<?"] + where
        params = [lo, hi] + params
    sql = (" WHERE " + " AND ".join(where)) if where else ""
    return s, sql, params, open_only


# ---------------------------------------------------------------- sheets
BREAK_HEAD = ["", "المستلمة", "المغلقة", "المفتوحة", "بانتظار التقييم", "المتأخرة", "الالتزام بالمهلة",
              "متوسط أول رد (ساعة)", "متوسط الإنجاز (ساعة)", "المصعّدة", "عدد التقييمات", "متوسط التقييم (من 5)",
              "نسبة الرضا", "لم يُحل", "نسبة من قيّم", "أُغلقت تلقائيًا"]


def _brow(name, x):
    pct = lambda v: (v / 100.0) if v is not None else None
    rnd = lambda v, k=1: round(v, k) if v is not None else None
    return [name, x["n"], x["closed"], x["open"], x["waiting"], x["late"], pct(x["sla"]), rnd(x["first"]),
            rnd(x["resolve"]), x["esc"], x["nrat"], rnd(x["stars"], 2), pct(x["csat"]), x["unresolved"],
            pct(x["resp"]), x["auto"]]


BREAK_FMT = {7: PCT_FMT, 13: PCT_FMT, 15: PCT_FMT, 8: "0.0", 9: "0.0", 12: "0.00"}


def sheet_summary(wb, s, u, scope_label):
    ws = new_sheet(wb, "الملخص")
    T, A = s["total"], s["appt"]
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width, ws.column_dimensions["C"].width = 34, 24, 12
    t = WriteOnlyCell(ws, value="تقرير مؤشرات طلبات الموظفين – نطاق شقراء الصحي")
    t.font = TITLE_FONT
    ws.append([t])
    ws.append([])
    line(ws, "الفترة", "%s إلى %s (%s)" % (s["f"]["from"], s["f"]["to"], core.days_ar(s["period_days"])), bold=True)
    line(ws, "النطاق", scope_label, bold=True)
    line(ws, "أُعدّ بواسطة", u["display_name"], bold=True)
    line(ws, "تاريخ الإعداد", datetime.now(RIYADH).replace(tzinfo=None, microsecond=0), bold=True)
    ws.append([])
    pct = lambda v: (v / 100.0) if v is not None else None
    rnd = lambda v, k=1: round(v, k) if v is not None else None
    kpis = [
        ("الطلبات المستلمة", T["n"], None), ("منها عبر جهاز الاستقبال", T["walkin"], None), ("منها مباشر عند الموظف", T["direct"], None), ("منها دون إفصاح", T["anon"], None),
        ("المغلقة", T["closed"], None), ("المفتوحة الآن", T["open"], None), ("بانتظار تقييم الموظف", T["waiting"], None),
        ("المتأخرة عن المهلة الآن", T["late"], None), ("الالتزام بالمهلة", pct(T["sla"]), PCT_FMT),
        ("متوسط زمن أول رد (ساعة)", rnd(T["first"]), "0.0"), ("متوسط زمن الإنجاز (ساعة)", rnd(T["resolve"]), "0.0"),
        ("الوسيط لزمن الإنجاز (ساعة)", rnd(T["resolve_med"]), "0.0"), ("نسبة التصعيد", pct(T["esc_pct"]), PCT_FMT),
        ("عدد التقييمات", T["nrat"], None), ("متوسط التقييم (من 5)", rnd(T["stars"], 2), "0.00"),
        ("نسبة الرضا (4 أو 5)", pct(T["csat"]), PCT_FMT), ("نسبة من قيّم", pct(T["resp"]), PCT_FMT),
        ("أفاد بأن طلبه لم يُحل", T["unresolved"], None), ("أُغلقت تلقائيًا (لم يقيّم)", T["auto"], None),
        ("أُغلقت دون تقييم (القسم)", T["staff_closed"], None),
        ("مواعيد محجوزة", A["booked"], None), ("حضروا وخُدموا", A["done"], None), ("لم يحضروا", A["no_show"], None),
        ("نسبة عدم الحضور", pct(A["no_show_pct"]), PCT_FMT), ("حضوري بدون موعد", A["walkins"], None),
        ("متوسط الانتظار (دقيقة)", A["wait"], None), ("متوسط مدة الخدمة (دقيقة)", A["service"], None),
    ]
    ws.append([cell(ws, "المؤشر", head=True), cell(ws, "القيمة", head=True)])
    for k, v, f in kpis:
        ws.append([k, cell(ws, v, f) if f else v])
    ws.append([])
    ws.append([cell(ws, "التذاكر المستلمة والمغلقة %s" % ("أسبوعيًا" if s["step"] == 7 else "يوميًا"), bold=True)])
    ws.append([cell(ws, h, head=True) for h in ("التاريخ", "المستلمة", "المغلقة")])
    for l, a, b in s["series"]:
        ws.append([l, a, b])
    titles = [("dept", "حسب القسم", "القسم"), ("staff", "حسب الموظف", "الموظف المسؤول"), ("topic", "حسب الموضوع", "الموضوع"),
              ("type", "حسب النوع", "النوع"), ("channel", "حسب القناة", "القناة"), ("facility", "حسب المنشأة", "المنشأة")]
    for key, title, label in titles:
        if key == "dept" and not is_admin_user(u):
            continue
        w2 = new_sheet(wb, title)
        table(w2, [label] + BREAK_HEAD[1:], [_brow(n, x) for n, x in s["by"][key]], widths=[30] + [13] * 15,
              formats=BREAK_FMT)


def sheet_tickets(wb, sql, params):
    con = db()
    rows = con.execute("SELECT * FROM tickets" + sql + " ORDER BY id LIMIT ?", params + [MAX_ROWS]).fetchall()
    dn = {d["id"]: d["name_ar"] for d in all_depts()}
    tn = core._topic_names()
    users = {r[0]: r[1] for r in con.execute("SELECT id, display_name FROM users")}
    esc = {r[0] for r in con.execute("SELECT DISTINCT ticket_id FROM events WHERE kind='escalate' AND ticket_id IN "
                                     "(SELECT id FROM tickets" + sql + ")", params)}
    now = core.now_utc()
    out = []
    for r in rows:
        fin = r["resolved_at"] or r["closed_at"]
        hrs = core._hours(r["created_at"], fin) if fin else None
        late = r["status"] in core.OPEN_STATUSES and r["due_at"] and r["due_at"] < now
        anon = bool(r["anonymous"])
        created = local_dt(r["created_at"])
        out.append([
            r["ref"], created.date() if (anon and created) else created, STATUSES.get(r["status"], r["status"]),
            REQ_TYPES.get(r["req_type"], r["req_type"]), tn.get(r["topic"], r["topic"]), dn.get(r["dept_id"], ""),
            "" if anon else CHANNELS.get(r["channel"], r["channel"]), "نعم" if anon else "", r["name"], r["emp_no"], r["mobile"],
            r["email"], r["facility"], r["job_cat"], users.get(r["assigned_user_id"], ""), local_dt(r["due_at"]),
            "نعم" if late or r["sla_breached"] else "", local_dt(r["first_response_at"]), local_dt(r["resolved_at"]),
            local_dt(r["closed_at"]), CLOSE_REASONS.get(r["close_reason"], "") if r["status"] == "closed" else "",
            r["rating"], round(hrs, 1) if hrs is not None else None, "نعم" if r["id"] in esc else "",
            r["message"], r["reply"]])
    ws = new_sheet(wb, "التذاكر")
    head = ["رقم التذكرة", "تاريخ التقديم", "الحالة", "النوع", "الموضوع", "القسم الحالي", "القناة", "دون إفصاح",
            "الاسم", "الرقم الوظيفي", "الجوال", "البريد", "المنشأة", "الفئة الوظيفية", "الموظف المسؤول", "المهلة",
            "تأخرت عن المهلة", "أول رد", "تاريخ الرد النهائي", "تاريخ الإغلاق", "طريقة الإغلاق", "التقييم",
            "مدة الإنجاز (ساعة)", "صُعّدت", "نص الطلب", "الرد"]
    fm = {2: DT_FMT, 16: DT_FMT, 18: DT_FMT, 19: DT_FMT, 20: DT_FMT, 23: "0.0"}
    table(ws, head, out, widths=[11, 17, 20, 22, 20, 22, 10, 9, 22, 12, 13, 26, 24, 16, 20, 17, 10, 17, 17, 17,
                                 20, 8, 11, 8, 60, 60], formats=fm)
    return len(out)


def sheet_ratings(wb, sql, params):
    con = db()
    rows = con.execute("SELECT r.*, t.ref, t.anonymous, t.name, t.topic FROM ratings r JOIN tickets t ON t.id=r.ticket_id "
                       "WHERE r.ticket_id IN (SELECT id FROM tickets" + sql + ") ORDER BY r.id", params).fetchall()
    dn = {d["id"]: d["name_ar"] for d in all_depts()}
    tn = core._topic_names()
    users = {r[0]: r[1] for r in con.execute("SELECT id, display_name FROM users")}
    def when(r):
        t = local_dt(r["at"])
        return t.date() if (t and r["anonymous"]) else t  # anonymous: date only, no device
    out = [[r["ref"], when(r), r["stars"], "نعم" if r["resolved"] else "لا", r["comment"],
            "" if r["anonymous"] else ("جهاز الاستقبال" if r["via"] == "kiosk" else "إلكتروني"), dn.get(r["dept_id"], ""),
            users.get(r["user_id"], ""), tn.get(r["topic"], ""), "مجهول" if r["anonymous"] else r["name"]] for r in rows]
    ws = new_sheet(wb, "التقييمات")
    table(ws, ["رقم التذكرة", "تاريخ التقييم", "التقييم (من 5)", "تم حل الطلب", "التعليق", "طريقة التقييم", "القسم",
                  "الموظف المسؤول", "الموضوع", "مقدّم الطلب"], out, widths=[11, 17, 11, 11, 50, 14, 22, 20, 20, 22],
          formats={2: DT_FMT})
    return len(out)


def sheet_appts(wb, sql, params):
    con = db()
    rows = con.execute("SELECT a.*, t.ref, t.name, t.mobile FROM appointments a JOIN tickets t ON t.id=a.ticket_id "
                       "WHERE a.ticket_id IN (SELECT id FROM tickets" + sql + ") ORDER BY a.id", params).fetchall()
    dn = {d["id"]: d["name_ar"] for d in all_depts()}
    users = {r[0]: r[1] for r in con.execute("SELECT id, display_name FROM users")}

    def mins(a, b):
        ta, tb = ap.parse_local(a), ap.parse_local(b)
        return round((tb - ta).total_seconds() / 60) if ta and tb and tb >= ta else None
    out = [[r["ref"], r["name"], r["mobile"], "بموعد" if r["kind"] == "appointment" else "بدون موعد",
            ap.STATUSES.get(r["status"], r["status"]), local_slot(r["slot"]) if r["kind"] == "appointment" else None,
            dn.get(r["dept_id"], ""), local_slot(r["checked_in_at"]), local_slot(r["called_at"]), local_slot(r["done_at"]),
            mins(r["checked_in_at"], r["called_at"]), mins(r["called_at"], r["done_at"]), users.get(r["served_by"], ""),
            r["emp_note"], r["staff_note"]] for r in rows]
    ws = new_sheet(wb, "المواعيد")
    table(ws, ["رقم التذكرة", "الاسم", "الجوال", "النوع", "الحالة", "الموعد", "القسم", "وصل", "استُدعي", "انتهت",
                  "الانتظار (دقيقة)", "مدة الخدمة (دقيقة)", "خدمه", "رغبة الموظف", "تعليمات القسم"], out,
          widths=[11, 22, 13, 11, 22, 17, 22, 17, 17, 17, 11, 11, 20, 30, 30],
          formats={6: DT_FMT, 8: DT_FMT, 9: DT_FMT, 10: DT_FMT})
    return len(out)


def sheet_events(wb, sql, params):
    con = db()
    rows = con.execute("SELECT e.*, t.ref, t.anonymous FROM events e JOIN tickets t ON t.id=e.ticket_id "
                       "WHERE e.ticket_id IN (SELECT id FROM tickets" + sql + ") ORDER BY e.ticket_id, e.id LIMIT ?",
                       params + [MAX_ROWS * 4]).fetchall()
    dn = {d["id"]: d["name_ar"] for d in all_depts()}
    out = []
    for r in rows:
        at = local_dt(r["at"])
        hide = r["anonymous"] and r["kind"] in ("create", "rating")
        out.append([r["ref"], at.date() if (hide and at) else at, r["actor"], core.EVENT_KINDS.get(r["kind"], r["kind"]),
                    dn.get(r["from_dept"], ""), dn.get(r["to_dept"], ""), r["text"]])
    ws = new_sheet(wb, "سجل الإجراءات")
    table(ws, ["رقم التذكرة", "الوقت", "بواسطة", "الإجراء", "من قسم", "إلى قسم", "التفاصيل"], out,
          widths=[11, 17, 28, 20, 22, 22, 70], formats={2: DT_FMT})
    return len(out)


# ---------------------------------------------------------------- routes
@app.route("/admin/reports")
@login_required
def admin_reports():
    u = current_user()
    s = core.compute_stats(u, request.args)
    my_dept = core.dept_by_id(u["dept_id"]) if u["dept_id"] else None
    return render_template("admin_reports.html", s=s, sheets=SHEETS, presets=core._stat_presets(), my_dept=my_dept)


@app.route("/admin/reports.xlsx")
@login_required
def admin_reports_xlsx():
    u = current_user()
    s, sql, params, open_only = scope(u, request.args)
    picked = [k for k, _ in SHEETS if request.args.get(k) == "1"] or ["summary", "tickets"]
    dept_name = ""
    if s["f"]["dept"]:
        d = core.dept_by_id(int(s["f"]["dept"]))
        dept_name = d["name_ar"] if d else ""
    elif not is_admin_user(u):
        d = core.dept_by_id(u["dept_id"]) if u["dept_id"] else None
        dept_name = d["name_ar"] if d else ""
    scope_label = (dept_name or "كل الأقسام") + ((" – " + CHANNELS[s["f"]["channel"]]) if s["f"]["channel"] else "")
    if not _report_lock.acquire(blocking=False):
        return render_template("msg.html", title="يُجهَّز تقرير آخر الآن",
                               msg="يُعدّ النظام تقريرًا آخر في هذه اللحظة. انتظر دقيقة ثم أعد المحاولة."), 429
    try:
        return _build(u, s, sql, params, open_only, picked, scope_label)
    finally:
        _report_lock.release()


_report_lock = threading.Lock()  # one report at a time: building one is CPU work that would slow everyone else


def _build(u, s, sql, params, open_only, picked, scope_label):
    wb = Workbook(write_only=True)
    if "summary" in picked:
        sheet_summary(wb, s, u, scope_label)
    else:
        ws = new_sheet(wb, "عن التقرير")
        ws.column_dimensions["A"].width = 70
        line(ws, "تقرير طلبات الموظفين – %s" % scope_label, bold=True)
        line(ws, ("التذاكر المفتوحة حتى %s" % datetime.now(RIYADH).strftime("%Y-%m-%d %H:%M")) if open_only
             else "الفترة: %s إلى %s" % (s["f"]["from"], s["f"]["to"]))
    if "tickets" in picked:
        sheet_tickets(wb, sql, params)
    if "ratings" in picked:
        sheet_ratings(wb, sql, params)
    if "appts" in picked:
        sheet_appts(wb, sql, params)
    if "events" in picked:
        sheet_events(wb, sql, params)
    wb.properties.title = "تقرير طلبات الموظفين"
    wb.properties.creator = "نطاق شقراء الصحي"
    buf = io.BytesIO()
    wb.save(buf)
    name = ("open-tickets-%s.xlsx" % datetime.now(RIYADH).strftime("%Y%m%d")) if open_only else \
        "report-%s-%s.xlsx" % (s["f"]["from"], s["f"]["to"])
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name, "Cache-Control": "no-store"})
