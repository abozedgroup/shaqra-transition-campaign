# -*- coding: utf-8 -*-
"""Excel (.xlsx) reports for supervisors and sections.

One workbook per download, with the sheets the user picks: a summary of the indicators, one sheet per breakdown,
the detailed ticket list, ratings, appointments and the action log. Staff only ever get their own section.
Imported at the end of app.py."""
import io
from datetime import datetime, timedelta, timezone

from flask import Response, render_template, request
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
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
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
ZEBRA = PatternFill("solid", fgColor="F6F9FD")
THIN = Border(bottom=Side(style="thin", color=LINE))
DT_FMT, D_FMT, PCT_FMT = "yyyy-mm-dd hh:mm", "yyyy-mm-dd", "0%"


# ---------------------------------------------------------------- helpers
def local_dt(iso):
    """Stored UTC ISO string -> naive Riyadh datetime for Excel (None if empty)."""
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(RIYADH) \
            .replace(tzinfo=None)
    except ValueError:
        return None


def local_slot(s):
    return ap.parse_local(s) if s else None


def put(ws, row, col, value, fmt=None, bold=False):
    c = ws.cell(row=row, column=col, value=value)
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        c.data_type = "s"  # text that looks like a formula stays text (no formula injection)
    c.font = Font(name="Arial", size=10, bold=bold)
    if fmt:
        c.number_format = fmt
    return c


def table(ws, start_row, headers, rows, widths=None, formats=None):
    """Header row + data rows, styled, with filter and frozen header. Returns next free row."""
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=start_row, column=j, value=h)
        c.font, c.fill = HEAD_FONT, HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[start_row].height = 30
    formats = formats or {}
    for i, r in enumerate(rows, 1):
        for j, v in enumerate(r, 1):
            c = put(ws, start_row + i, j, v, formats.get(j))
            c.border = THIN
            c.alignment = Alignment(vertical="top", wrap_text=isinstance(v, str) and len(v) > 40)
            if i % 2 == 0:
                c.fill = ZEBRA
    end = start_row + len(rows)
    if rows:
        ws.auto_filter.ref = "A%d:%s%d" % (start_row, get_column_letter(len(headers)), end)
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    for j, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    return end + 2


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
    ws = wb.active
    ws.title = "الملخص"
    ws.sheet_view.rightToLeft = True
    T, A = s["total"], s["appt"]
    ws["A1"] = "تقرير مؤشرات طلبات الموظفين – نطاق شقراء الصحي"
    ws["A1"].font = TITLE_FONT
    meta = [("الفترة", "%s إلى %s (%s)" % (s["f"]["from"], s["f"]["to"], core.days_ar(s["period_days"]))),
            ("النطاق", scope_label), ("أُعدّ بواسطة", u["display_name"]),
            ("تاريخ الإعداد", datetime.now(RIYADH).replace(tzinfo=None))]
    for i, (k, v) in enumerate(meta, 3):
        put(ws, i, 1, k, bold=True)
        put(ws, i, 2, v, DT_FMT if isinstance(v, datetime) else None)
    pct = lambda v: (v / 100.0) if v is not None else None
    rnd = lambda v, k=1: round(v, k) if v is not None else None
    kpis = [
        ("الطلبات المستلمة", T["n"], None), ("منها حضوري", T["walkin"], None), ("منها دون إفصاح", T["anon"], None),
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
    nxt = table(ws, 8, ["المؤشر", "القيمة"], [(k, v) for k, v, _ in kpis], widths=[34, 22])
    for i, (_, _, f) in enumerate(kpis, 9):
        if f:
            ws.cell(row=i, column=2).number_format = f
    put(ws, nxt, 1, "التذاكر المستلمة والمغلقة %s" % ("أسبوعيًا" if s["step"] == 7 else "يوميًا"), bold=True)
    table(ws, nxt + 1, ["التاريخ", "المستلمة", "المغلقة"], [(l, a, b) for l, a, b in s["series"]])
    ws.freeze_panes = None
    titles = [("dept", "حسب القسم", "القسم"), ("staff", "حسب الموظف", "الموظف المسؤول"), ("topic", "حسب الموضوع", "الموضوع"),
              ("type", "حسب النوع", "النوع"), ("channel", "حسب القناة", "القناة"), ("facility", "حسب المنشأة", "المنشأة")]
    for key, title, label in titles:
        if key == "dept" and not is_admin_user(u):
            continue
        w2 = new_sheet(wb, title)
        table(w2, 1, [label] + BREAK_HEAD[1:], [_brow(n, x) for n, x in s["by"][key]],
              widths=[30] + [13] * 15, formats=BREAK_FMT)


def sheet_tickets(wb, sql, params):
    con = db()
    rows = con.execute("SELECT * FROM tickets" + sql + " ORDER BY id", params).fetchall()
    dn = {d["id"]: d["name_ar"] for d in all_depts()}
    tn = core._topic_names()
    users = {r[0]: r[1] for r in con.execute("SELECT id, display_name FROM users")}
    esc = {r[0] for r in con.execute("SELECT DISTINCT ticket_id FROM events WHERE kind='escalate'")}
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
            CHANNELS.get(r["channel"], r["channel"]), "نعم" if anon else "", r["name"], r["emp_no"], r["mobile"],
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
    table(ws, 1, head, out, widths=[11, 17, 20, 22, 20, 22, 10, 9, 22, 12, 13, 26, 24, 16, 20, 17, 10, 17, 17, 17,
                                    20, 8, 11, 8, 60, 60], formats=fm)
    for i, r in enumerate(out, 2):  # anonymous tickets carry a date only
        if r[1] is not None and not isinstance(r[1], datetime):
            ws.cell(row=i, column=2).number_format = D_FMT
    return len(out)


def sheet_ratings(wb, sql, params):
    con = db()
    rows = con.execute("SELECT r.*, t.ref, t.anonymous, t.name, t.topic FROM ratings r JOIN tickets t ON t.id=r.ticket_id "
                       "WHERE r.ticket_id IN (SELECT id FROM tickets" + sql + ") ORDER BY r.id", params).fetchall()
    dn = {d["id"]: d["name_ar"] for d in all_depts()}
    tn = core._topic_names()
    users = {r[0]: r[1] for r in con.execute("SELECT id, display_name FROM users")}
    out = [[r["ref"], local_dt(r["at"]), r["stars"], "نعم" if r["resolved"] else "لا", r["comment"],
            "جهاز الاستقبال" if r["via"] == "kiosk" else "إلكتروني", dn.get(r["dept_id"], ""),
            users.get(r["user_id"], ""), tn.get(r["topic"], ""), "مجهول" if r["anonymous"] else r["name"]] for r in rows]
    ws = new_sheet(wb, "التقييمات")
    table(ws, 1, ["رقم التذكرة", "تاريخ التقييم", "التقييم (من 5)", "تم حل الطلب", "التعليق", "طريقة التقييم", "القسم",
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
    table(ws, 1, ["رقم التذكرة", "الاسم", "الجوال", "النوع", "الحالة", "الموعد", "القسم", "وصل", "استُدعي", "انتهت",
                  "الانتظار (دقيقة)", "مدة الخدمة (دقيقة)", "خدمه", "رغبة الموظف", "تعليمات القسم"], out,
          widths=[11, 22, 13, 11, 22, 17, 22, 17, 17, 17, 11, 11, 20, 30, 30],
          formats={6: DT_FMT, 8: DT_FMT, 9: DT_FMT, 10: DT_FMT})
    return len(out)


def sheet_events(wb, sql, params):
    con = db()
    rows = con.execute("SELECT e.*, t.ref, t.anonymous FROM events e JOIN tickets t ON t.id=e.ticket_id "
                       "WHERE e.ticket_id IN (SELECT id FROM tickets" + sql + ") ORDER BY e.ticket_id, e.id", params).fetchall()
    dn = {d["id"]: d["name_ar"] for d in all_depts()}
    out = []
    for r in rows:
        at = local_dt(r["at"])
        hide = r["anonymous"] and r["kind"] in ("create", "rating")
        out.append([r["ref"], at.date() if (hide and at) else at, r["actor"], core.EVENT_KINDS.get(r["kind"], r["kind"]),
                    dn.get(r["from_dept"], ""), dn.get(r["to_dept"], ""), r["text"]])
    ws = new_sheet(wb, "سجل الإجراءات")
    table(ws, 1, ["رقم التذكرة", "الوقت", "بواسطة", "الإجراء", "من قسم", "إلى قسم", "التفاصيل"], out,
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
    wb = Workbook()
    if "summary" in picked:
        sheet_summary(wb, s, u, scope_label)
    else:
        ws = wb.active
        ws.title = "عن التقرير"
        ws.sheet_view.rightToLeft = True
        put(ws, 1, 1, "تقرير طلبات الموظفين – %s" % scope_label, bold=True)
        put(ws, 2, 1, ("التذاكر المفتوحة حتى %s" % datetime.now(RIYADH).strftime("%Y-%m-%d %H:%M")) if open_only
            else "الفترة: %s إلى %s" % (s["f"]["from"], s["f"]["to"]))
        ws.column_dimensions["A"].width = 60
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
