"""Quick entry: register a visitor who walked straight in to a staff member, so every visit is counted.

The staff member fills one short form while the visitor is in front of them and picks what happened:
  done   – served now: the ticket is resolved at once and enters the normal rating cycle;
  follow – needs follow-up: the ticket stays open in their section, assigned to them;
  appt   – needs an appointment: the ticket opens on the appointment tab.
Tickets are recorded with channel "direct" ("مباشر عند الموظف") and belong to the staff member's section.
"""
from flask import redirect, render_template, request, session, url_for

import app as core
from app import (EMAIL_RE, EMPNO_RE, INTAKE_KEY, MOBILE_RE, RATE_WINDOW_DAYS, add_workdays, app, check_csrf, clean,
                 current_user, db, dept_by_id, dept_by_key, fmt_dt, is_admin_user, log_event, login_required,
                 new_follow_code, follow_hash, new_ref, now_utc, topic_opts)

OUTCOMES = {"done": "انتهت الخدمة الآن", "follow": "تحتاج متابعة", "appt": "تحتاج موعدًا"}


def _section(u):
    d = dept_by_id(u["dept_id"]) if u["dept_id"] else None
    return d if d and d["active"] else dept_by_key(INTAKE_KEY)


def _validate(form, u):
    v, err = {}, {}
    v["name"] = clean(form.get("name"), 80)
    if len(v["name"]) < 2 or "\n" in v["name"]:
        err["name"] = "اكتب اسم المراجع."
    v["mobile"] = clean(form.get("mobile"), 20).translate(core.AR_DIGITS).replace(" ", "")
    if v["mobile"] and not MOBILE_RE.match(v["mobile"]):
        err["mobile"] = "رقم الجوال يبدأ بـ 05 ومكوّن من 10 أرقام (أو اتركه فارغًا)."
    v["emp_no"] = clean(form.get("emp_no"), 20).translate(core.AR_DIGITS).replace(" ", "")
    if v["emp_no"] and not EMPNO_RE.match(v["emp_no"]):
        err["emp_no"] = "الرقم الوظيفي أرقام فقط (أو اتركه فارغًا)."
    v["email"] = clean(form.get("email"), 120).lower()
    if v["email"] and not EMAIL_RE.match(v["email"]):
        err["email"] = "البريد يجب أن يكون بريد الوزارة ‎@moh.gov.sa (أو اتركه فارغًا)."
    v["topic"] = clean(form.get("topic"), 40)
    if v["topic"] not in [k for k, _ in topic_opts("ar")]:
        err["topic"] = "اختر الموضوع."
    v["message"] = clean(form.get("message"), 3000)
    if len(v["message"]) < 3:
        err["message"] = "اكتب وصفًا مختصرًا لسبب الزيارة."
    v["outcome"] = form.get("outcome", "")
    if v["outcome"] not in OUTCOMES:
        err["outcome"] = "اختر ما تم مع المراجع."
    v["reply"] = clean(form.get("reply"), 3000)
    return v, err


@app.route("/admin/quick", methods=["GET", "POST"])
@login_required
def admin_quick():
    u = current_user()
    dept = _section(u)
    v, err = {}, {}
    if request.method == "POST":
        check_csrf()
        v, err = _validate(request.form, u)
        if not err:
            con = db()
            actor = "%s (%s)" % (u["display_name"], u["username"])
            if con.in_transaction:
                con.commit()
            con.execute("BEGIN IMMEDIATE")
            try:
                ref, ts, code = new_ref(con), now_utc(), new_follow_code()
                done = v["outcome"] == "done"
                reply = v["reply"] or ("تمت خدمتك حضوريًا لدى %s." % dept["name_ar"]) if done else ""
                rate_due = add_workdays(ts, RATE_WINDOW_DAYS) if done else ""
                cur = con.execute(
                    "INSERT INTO tickets(ref,created_at,updated_at,email,mobile,emp_no,name,facility,job_cat,req_type,"
                    "message,lang,topic,dept_id,anonymous,follow_hash,due_at,channel,status,reply,assigned_user_id,"
                    "first_response_at,resolved_at,rate_due_at) VALUES(?,?,?,?,?,?,?,'','','request',?,'ar',?,?,0,?,?,"
                    "'direct',?,?,?,?,?,?)",
                    (ref, ts, ts, v["email"], v["mobile"], v["emp_no"], v["name"], v["message"], v["topic"],
                     dept["id"], follow_hash(ref, code), add_workdays(ts, dept["sla_days"]),
                     "resolved" if done else "in_progress", reply, u["id"] or None, ts,
                     ts if done else "", rate_due))
                tid = cur.lastrowid
                log_event(con, tid, actor, "create", "مراجع مباشر عند الموظف – " + OUTCOMES[v["outcome"]],
                          to_dept=dept["id"])
                if done:
                    log_event(con, tid, actor, "reply", reply)
                    log_event(con, tid, actor, "resolve",
                              "خُدم حضوريًا. يمكنه تقييم الخدمة، وتُغلق تلقائيًا إن لم يقيّم حتى %s." % fmt_dt(rate_due))
                con.commit()
            except Exception:
                con.rollback()
                raise
            session["quick"] = [ref, code, v["outcome"]]
            return redirect(url_for("admin_ticket", ref=ref) + ("#appt" if v["outcome"] == "appt" else ""))
    else:
        v = {"outcome": "done"}
        if dept and dept["key"] in [k for k, _ in topic_opts("ar")]:
            v["topic"] = dept["key"]
    return render_template("admin_quick.html", v=v, err=err, dept=dept, outcomes=OUTCOMES,
                           topics=topic_opts("ar"), admin=is_admin_user(u)), (400 if err else 200)


def quick_ctx(ref):
    """One-time banner data on the ticket page right after a quick entry."""
    q = session.get("quick")
    if q and q[0] == ref:
        session.pop("quick", None)
        return {"ref": q[0], "code": q[1], "outcome": q[2]}
    return None
