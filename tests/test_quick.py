# Shared routing (Employee Care + topic section), claiming, and quick entry of walk-ins served directly.
# Run: python3 tests/test_quick.py "$(mktemp -d)"
import os, re, sys, sqlite3, hashlib
D = sys.argv[1]
os.environ.update(DB_PATH=D + "/tickets.db", SITE_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
                  COOKIE_SECURE="0", ADMIN_USER="admin")
salt = b"0123456789abcdef"
os.environ["ADMIN_PASSWORD_HASH"] = salt.hex() + ":" + hashlib.scrypt(b"adminpass123", salt=salt, n=2**14, r=8, p=1, dklen=32).hex()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import app as A
def tok(h):
    m = re.search(r'name="csrf_token" value="([^"]+)"', h); return m.group(1) if m else ""
def get(cl, u): r = cl.get(u); return r, r.get_data(as_text=True)
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: sys.exit(1)
def q(sql, *a): return sqlite3.connect(D + "/tickets.db").execute(sql, a).fetchall()
def dept(k): return q("SELECT id FROM departments WHERE key=?", k)[0][0]
a = A.app.test_client(); r, h = get(a, "/admin/login"); a.post("/admin/login", data=dict(csrf_token=tok(h), username="admin", password="adminpass123"))
def staff(user, key):
    r, h = get(a, "/admin/users")
    a.post("/admin/users", data=dict(csrf_token=tok(h), display_name="موظف " + user, username=user, role="staff", dept_id=str(dept(key)), password=user + "pass12345"))
    s = A.app.test_client(); r, h = get(s, "/admin/login")
    s.post("/admin/login", data=dict(csrf_token=tok(h), username=user, password=user + "pass12345")); return s
care, leaves, payroll, compl = staff("care1", "care"), staff("leave1", "leaves"), staff("pay1", "payroll"), staff("comp1", "complaints")
base = dict(req_type="request", message="أريد الاستفسار عن رصيد إجازتي", name="أحمد محمد", emp_no="1234", facility="other",
            job_cat="other", email="ahmad@moh.gov.sa", mobile="0551234567", consent="1")
def submit(**kw):
    c = A.app.test_client(); r, h = get(c, "/ticket"); c.post("/ticket", data=dict(base, csrf_token=tok(h), **kw))
    r, h = get(c, "/ticket/done"); return re.findall(r'<span class="ref">([^<]+)</span>', h)[0]

# ---- 1. shared visibility
t1 = submit(topic="leaves"); t2 = submit(topic="payroll", email="x2@moh.gov.sa")
t3 = submit(req_type="feedback", topic="leaves", message="شكوى بخصوص الإجازات", email="x3@moh.gov.sa")
ok(q("SELECT dept_id FROM tickets WHERE ref=?", t1)[0][0] == dept("care"), "request starts at Employee Care")
r, h = get(leaves, "/admin"); ok(t1 in h and t2 not in h and t3 not in h, "leaves sees the leaves-topic ticket at Care only")
ok("مشتركة" in h, "shared chip in the list")
r, h = get(payroll, "/admin"); ok(t2 in h and t1 not in h, "payroll sees only its topic")
r, h = get(care, "/admin"); ok(t1 in h and t2 in h and "مشتركة" not in h, "care sees everything at Care, no shared chip")
r, h = get(compl, "/admin"); ok(t3 in h and t1 not in h, "complaints see complaints only")
ok(get(leaves, "/admin/t/" + t3)[0].status_code == 404, "complaint never shared with the topic section")
ok(get(payroll, "/admin/t/" + t1)[0].status_code == 404, "other section cannot open it")
ok(get(leaves, "/admin/open?ref=" + t1)[0].status_code == 302, "quick-open by number works for shared ticket")
r, h = get(leaves, "/admin/t/" + t1); ok(r.status_code == 200 and "تذكرة مشتركة" in h and "سحبها لقسمي" in h, "shared ticket page with claim button")
r, h = get(care, "/admin/t/" + t1); ok("سحبها لقسمي" not in h, "care has no claim button")
ok(care.post("/admin/t/" + t1, data=dict(csrf_token=tok(h), action="claim")).status_code == 400, "care cannot claim")
# the topic section can answer directly
r, h = get(leaves, "/admin/t/" + t1)
leaves.post("/admin/t/" + t1, data=dict(csrf_token=tok(h), action="save", reply="رصيدك 30 يومًا"))
ok(q("SELECT status, reply FROM tickets WHERE ref=?", t1)[0] == ("in_progress", "رصيدك 30 يومًا"), "section replies on a shared ticket")
# claim
r, h = get(leaves, "/admin/t/" + t1)
r = leaves.post("/admin/t/" + t1, data=dict(csrf_token=tok(h), action="claim")); ok(r.status_code == 302, "claim ok")
ok(q("SELECT dept_id, status FROM tickets WHERE ref=?", t1)[0] == (dept("leaves"), "in_progress"), "ticket moved to leaves")
ok(q("SELECT e.text FROM events e JOIN tickets t ON t.id=e.ticket_id WHERE t.ref=? AND kind='escalate'", t1)[0][0].startswith("سحبها القسم"), "claim logged")
r, h = get(leaves, "/admin/t/" + t1); ok("تذكرة مشتركة" not in h, "no longer shared after claim")
ok(get(care, "/admin/t/" + t1)[0].status_code == 404, "care no longer sees a claimed ticket")
ok(leaves.post("/admin/t/" + t1, data=dict(csrf_token=tok(h), action="claim")).status_code == 400, "cannot claim twice")
# care refers as before → leaves owns; general topic stays with care
t4 = submit(topic="general", email="x4@moh.gov.sa")
r, h = get(leaves, "/admin"); ok(t4 not in h, "general topic not shared")

# ---- 2. quick entry
r, h = get(leaves, "/admin"); ok('href="/admin/quick"' in h, "list has quick-entry button")
r, h = get(leaves, "/admin/quick"); ok(r.status_code == 200 and 'value="leaves" selected' in h, "form defaults topic to own section")
r = leaves.post("/admin/quick", data=dict(csrf_token=tok(h), name="", message="x", outcome="zzz", topic="leaves", mobile="123", email="a@b.c"))
hh = r.get_data(as_text=True)
ok(r.status_code == 400 and "اكتب اسم المراجع" in hh and "05" in hh and "@moh.gov.sa" in hh and "اختر ما تم" in hh, "validation errors")
n0 = q("SELECT COUNT(*) FROM tickets")[0][0]
r = leaves.post("/admin/quick", data=dict(csrf_token=tok(h), name="خالد", message="طلب تعريف بالراتب", outcome="done", topic="leaves", mobile="0550001111", reply="سُلّم التعريف"))
ok(r.status_code == 302 and q("SELECT COUNT(*) FROM tickets")[0][0] == n0 + 1, "done: created")
qr = q("SELECT ref, status, channel, dept_id, reply, resolved_at!='', rate_due_at!='', first_response_at!='', assigned_user_id IS NOT NULL, req_type, anonymous FROM tickets ORDER BY id DESC LIMIT 1")[0]
ok(qr[1:] == ("resolved", "direct", dept("leaves"), "سُلّم التعريف", 1, 1, 1, 1, "request", 0), "done: resolved, direct, own section, assigned: %s" % (qr,))
r, h = get(leaves, r.headers["Location"]); ok("سُجّل المراجع" in h and "رمز المتابعة" in h and "مباشر" in h, "banner with number + code")
code = re.search(r'class="k-code">([A-Z0-9]+)-([A-Z0-9]+)<', h); code = code.group(1) + code.group(2)
r, h = get(leaves, "/admin/t/" + qr[0]); ok("سُجّل المراجع" not in h, "banner shown once")
# the visitor can check status with the code
c = A.app.test_client(); r, h = get(c, "/status"); r = c.post("/status", data=dict(csrf_token=tok(h), ref=qr[0], email=code))
ok("سُلّم التعريف" in r.get_data(as_text=True), "status page with follow-up code shows the reply")
# follow
r, h = get(leaves, "/admin/quick")
r = leaves.post("/admin/quick", data=dict(csrf_token=tok(h), name="منى", message="تعديل رصيد", outcome="follow", topic="leaves"))
qf = q("SELECT status, reply, mobile FROM tickets ORDER BY id DESC LIMIT 1")[0]; ok(qf == ("in_progress", "", ""), "follow: in progress, no mobile ok")
# appointment
r, h = get(leaves, "/admin/quick")
r = leaves.post("/admin/quick", data=dict(csrf_token=tok(h), name="سارة", message="تحتاج مراجعة", outcome="appt", topic="leaves", mobile="0557778888"))
ok(r.headers["Location"].endswith("#appt"), "appt: goes to the appointment tab")
r, h = get(leaves, r.headers["Location"]); ok("احجز له الموعد" in h and "احجز موعدًا حضوريًا" in h, "appointment booking offered")
# admin (no section) records at Employee Care
r, h = get(a, "/admin/quick"); a.post("/admin/quick", data=dict(csrf_token=tok(h), name="زائر", message="سؤال عام", outcome="done", topic="general"))
ok(q("SELECT dept_id FROM tickets ORDER BY id DESC LIMIT 1")[0][0] == dept("care"), "admin entry goes to Employee Care")
ok(A.app.test_client().get("/admin/quick").status_code == 302, "login required")
r = A.app.test_client().post("/admin/quick", data=dict(name="x")); ok(r.status_code in (302, 400, 403), "no anonymous post")
# stats + report count the direct channel
r, h = get(a, "/admin/stats?period=all"); ok("مباشر عند الموظف" in h, "stats show the direct channel")
ok(get(a, "/admin?channel=direct&status=all")[1].count('class="badge ch-walkin" title="سُجّل') >= 3, "list filter by channel direct")
r = a.get("/admin/reports.xlsx?period=all"); ok(r.status_code == 200, "excel report builds")

# ---- 3. bulk actions
b1 = submit(topic="general", email="b1@moh.gov.sa"); b2 = submit(topic="general", email="b2@moh.gov.sa"); b3 = submit(topic="general", email="b3@moh.gov.sa")
r, h = get(care, "/admin?status=open"); ok('id="bulk"' in h and 'name="ids" value="%s"' % b1 in h, "list offers selection")
r = care.post("/admin/bulk", data=dict(csrf_token=tok(h), ids=[b1, b2], action="take", back="status=open"))
ok(r.status_code == 302 and r.headers["Location"].endswith("/admin?status=open"), "bulk take redirects back")
ok(q("SELECT COUNT(*) FROM tickets WHERE ref IN (?,?) AND status='in_progress' AND assigned_user_id IS NOT NULL", b1, b2)[0][0] == 2, "bulk take assigned 2")
r, h = get(care, "/admin?status=open"); ok("استلمت 2 تذكرة" in h, "bulk message shown")
r = care.post("/admin/bulk", data=dict(csrf_token=tok(h), ids=[b1, b2], action="refer", to_dept=str(dept("payroll")), reason="ab"))
ok(q("SELECT COUNT(*) FROM tickets WHERE ref IN (?,?) AND dept_id=?", b1, b2, dept("care"))[0][0] == 2, "refer needs a reason")
care.post("/admin/bulk", data=dict(csrf_token=tok(h), ids=[b1, b2], action="refer", to_dept=str(dept("payroll")), reason="من اختصاص الرواتب"))
ok(q("SELECT COUNT(*) FROM tickets WHERE ref IN (?,?) AND dept_id=? AND status='escalated'", b1, b2, dept("payroll"))[0][0] == 2, "bulk refer")
# a section cannot act on tickets it cannot see
r, h = get(leaves, "/admin"); leaves.post("/admin/bulk", data=dict(csrf_token=tok(h), ids=[b3], action="close", close_note="مكررة"))
ok(q("SELECT status FROM tickets WHERE ref=?", b3)[0][0] == "new", "bulk ignores tickets outside scope")
r, h = get(care, "/admin"); care.post("/admin/bulk", data=dict(csrf_token=tok(h), ids=[b3], action="close", close_note=""))
ok(q("SELECT status FROM tickets WHERE ref=?", b3)[0][0] == "new", "bulk close needs a reason")
care.post("/admin/bulk", data=dict(csrf_token=tok(h), ids=[b3, "ZZZ", "1"], action="close", close_note="مكررة"))
ok(q("SELECT status, close_reason FROM tickets WHERE ref=?", b3)[0] == ("closed", "staff"), "bulk close")
ok(care.post("/admin/bulk", data=dict(ids=[b1], action="take")).status_code in (400, 403), "bulk needs CSRF")
r = care.post("/admin/bulk", data=dict(csrf_token=tok(h), ids=[b1], action="take", back="//evil.com"))
ok(r.headers["Location"].endswith("/admin"), "back cannot leave the admin")

# ---- 4. pulse (alerts)
r = payroll.get("/admin/pulse"); p = r.get_json()
ok(r.status_code == 200 and p["act"] >= 2 and p["t"] > 0 and "wait" in p, "pulse JSON: %s" % p)
ok("Set-Cookie" not in r.headers, "polling does not extend the session")
ok(A.app.test_client().get("/admin/pulse").status_code == 401, "pulse needs login")
r, h = get(payroll, "/admin"); ok("data-pulse=" in h and 'data-nb="act"' in h and "data-sound-toggle" in h, "nav carries pulse data + sound toggle")

# ---- 5. official holidays
from datetime import date, timedelta
r, h = get(a, "/admin/departments"); ok('id="holidays"' in h, "holidays card on departments page")
# a Sunday with 3 working days ahead
sun = date(2027, 1, 3)
assert sun.weekday() == 6
ts = sun.isoformat() + "T06:00:00Z"
before = A.add_workdays(ts, 3)
a.post("/admin/holidays", data=dict(csrf_token=tok(h), name="عطلة تجريبية", **{"from": (sun + timedelta(days=1)).isoformat(), "to": (sun + timedelta(days=2)).isoformat()}))
ok(q("SELECT COUNT(*) FROM holidays")[0][0] == 2, "two holiday days stored")
after = A.add_workdays(ts, 3)
ok(before[:10] == "2027-01-06" and after[:10] == "2027-01-10", "SLA skips holidays: %s → %s" % (before, after))
ok(A.add_workdays((sun + timedelta(days=1)).isoformat() + "T06:00:00Z", 1)[:10] == "2027-01-07", "submitted on a holiday: clock starts next working day")
ok(A.appointments.is_workday(sun + timedelta(days=1)) is False, "no appointments on a holiday")
r, h = get(a, "/admin/departments"); ok("عطلة تجريبية" in h and "أُضيفت" in h, "listed with message")
a.post("/admin/holidays", data=dict(csrf_token=tok(h), name="x", **{"from": "2027-02-01", "to": "2027-04-01"}))
ok(q("SELECT COUNT(*) FROM holidays")[0][0] == 2, "range over 30 days refused")
a.post("/admin/holidays", data=dict(csrf_token=tok(h), action="delete", day=(sun + timedelta(days=1)).isoformat()))
ok(q("SELECT COUNT(*) FROM holidays")[0][0] == 1 and A.add_workdays(ts, 3)[:10] == "2027-01-07", "delete reloads")
r, h = get(care, "/admin"); ok(care.post("/admin/holidays", data=dict(csrf_token=tok(h), name="xx", **{"from": "2027-03-01"})).status_code == 404, "staff cannot edit holidays")

# ---- 6. regressions from the full review
def x(sql, *p):
    c = sqlite3.connect(D + "/tickets.db"); c.execute(sql, p); c.commit(); c.close()
# shared ticket: no appointment booking from the topic section (it would land in Care's calendar)
t5 = submit(topic="leaves", email="x5@moh.gov.sa")
r, h = get(leaves, "/admin/t/" + t5); ok('id="tab-appt"' not in h and "لحجز موعد" in h, "no appointment tab on a shared ticket")
leaves.post("/admin/t/%s/appt" % t5, data=dict(csrf_token=tok(h), action="book", slot="2030-01-06 07:30"))
ok(q("SELECT COUNT(*) FROM appointments a JOIN tickets t ON t.id=a.ticket_id WHERE t.ref=?", t5)[0][0] == 0, "booking on a shared view refused")
# complaints are never shared, even when one ends up at Employee Care
t6 = submit(req_type="feedback", topic="leaves", message="شكوى وصلت للعناية", email="x6@moh.gov.sa")
x("UPDATE tickets SET dept_id=? WHERE ref=?", dept("care"), t6)
ok(get(leaves, "/admin/t/" + t6)[0].status_code == 404 and t6 not in get(leaves, "/admin?status=all")[1], "feedback at Care not shared")
# duplicate ids in a bulk action are handled once
t7 = submit(topic="general", email="x7@moh.gov.sa")
r, h = get(care, "/admin"); care.post("/admin/bulk", data=dict(csrf_token=tok(h), ids=[t7, t7, t7], action="close", close_note="مكررة"))
ok(q("SELECT COUNT(*) FROM events e JOIN tickets t ON t.id=e.ticket_id WHERE t.ref=? AND kind='close'", t7)[0][0] == 1, "bulk de-duplicates")
# quick entry 'appointment' records a request in the queue page
r, h = get(leaves, "/admin/quick"); ok('value="appt"' in h, "appointment outcome offered while appointments are on")
leaves.post("/admin/quick", data=dict(csrf_token=tok(h), name="هند", message="تحتاج موعد", outcome="appt", topic="leaves", mobile="0551231231"))
ok(q("SELECT a.status, a.requested_by, a.dept_id FROM appointments a ORDER BY a.id DESC LIMIT 1")[0] == ("requested", "staff", dept("leaves")), "quick appt creates a request")
r, h = get(leaves, "/admin/queue"); ok("هند" in h, "request visible on the queue page")
# appointments switched off: no outcome, no booking
x("UPDATE departments SET appt_enabled=0 WHERE key='leaves'")
r, h = get(leaves, "/admin/quick"); ok('value="appt"' not in h, "appointment outcome hidden when appointments are off")
r = leaves.post("/admin/quick", data=dict(csrf_token=tok(h), name="هند", message="تحتاج موعد", outcome="appt", topic="leaves"))
ok(r.status_code == 400, "appointment outcome refused when off")
lt = q("SELECT ref FROM tickets WHERE dept_id=? AND status='in_progress' AND anonymous=0 ORDER BY id DESC LIMIT 1", dept("leaves"))[0][0]
r, h = get(leaves, "/admin/t/" + lt); n0 = q("SELECT COUNT(*) FROM appointments")[0][0]
leaves.post("/admin/t/%s/appt" % lt, data=dict(csrf_token=tok(h), action="book", slot="2030-01-06 07:30"))
ok(q("SELECT COUNT(*) FROM appointments WHERE status='booked' AND slot='2030-01-06 07:30'")[0][0] == 0, "server refuses booking when appointments are off")
x("UPDATE departments SET appt_enabled=1 WHERE key='leaves'")
# section suspended: quick entry blocked, shared tickets and claim gone
t8 = submit(topic="payroll", email="x8@moh.gov.sa")
x("UPDATE departments SET active=0 WHERE key='payroll'")
r = payroll.get("/admin/quick"); ok(r.status_code == 409 and "قسمك موقوف" in r.get_data(as_text=True), "quick entry blocked for a suspended section")
ok(payroll.get("/admin/t/" + t8).status_code == 404, "suspended section loses shared tickets")
r, h = get(payroll, "/admin"); ok(payroll.post("/admin/t/" + t8, data=dict(csrf_token=tok(h), action="claim")).status_code == 404, "no claim into a suspended section")
x("UPDATE departments SET active=1 WHERE key='payroll'")
# two simultaneous bookings of one ticket leave one live appointment
import threading
r, h = get(leaves, "/admin/t/" + lt + "?appt_day=")
slots = re.findall(r'name="slot" value="([^"]+)"', h)
ok(len(slots) >= 2, "slots offered")
def book(sl):
    leaves.post("/admin/t/%s/appt" % lt, data=dict(csrf_token=tok(h), action="book", slot=sl))
th = [threading.Thread(target=book, args=(sl,)) for sl in slots[:4]]; [t.start() for t in th]; [t.join() for t in th]
ok(q("SELECT COUNT(*) FROM appointments a JOIN tickets t ON t.id=a.ticket_id WHERE t.ref=? AND a.status NOT IN ('done','no_show','cancelled')", lt)[0][0] == 1, "parallel bookings: one live appointment")
# appointment indicators follow the page filters (channel): the direct-channel visitor's request counts
# only under that channel
with A.app.test_request_context("/admin/stats"):
    sa = A.appointments.stats(A.db(), "2000-01-01T00:00:00Z", "2100-01-01T00:00:00Z", " WHERE channel=?", ["walkin"])
    sd = A.appointments.stats(A.db(), "2000-01-01T00:00:00Z", "2100-01-01T00:00:00Z", " WHERE channel=?", ["direct"])
ok(sa["booked"] + sa["pending"] == 0 and sd["booked"] + sd["pending"] >= 1, "appointment figures follow the ticket filters")
# holiday on a booked day warns
bk = q("SELECT substr(slot,1,10) FROM appointments WHERE status='booked' LIMIT 1")
if bk:
    r, h = get(a, "/admin/departments")
    a.post("/admin/holidays", data=dict(csrf_token=tok(h), name="عطلة طارئة", **{"from": bk[0][0]}))
    r, h = get(a, "/admin/departments"); ok("يوجد 1 موعد محجوز" in h, "holiday warns about booked appointments")
# a successful login gives its attempt back (5 tries per account)
A._rl.clear()
def try_login(pw):
    c = A.app.test_client(); r, h = get(c, "/admin/login"); return c.post("/admin/login", data=dict(csrf_token=tok(h), username="care1", password=pw)).status_code
codes = [try_login("wrong-password") for _ in range(4)] + [try_login("care1pass12345")] + [try_login("wrong-password")]
ok(codes == [200, 200, 200, 200, 302, 200], "throttle counts failures only: %s" % codes)
ok(try_login("wrong-password") == 429, "6th failure blocked")
A._rl.clear()
# anonymous rows in Excel: dates only, no duration
import openpyxl, io
ta = submit(req_type="feedback", topic="general", anonymous="1", message="ملاحظة دون إفصاح للتقرير", email="")
r, h = get(compl, "/admin/t/" + ta); compl.post("/admin/t/" + ta, data=dict(csrf_token=tok(h), action="resolve", reply="شكرًا لملاحظتك"))
ok(q("SELECT status, anonymous FROM tickets WHERE ref=?", ta)[0] == ("resolved", 1), "anonymous ticket resolved")
r = a.get("/admin/reports.xlsx?period=all&tickets=1&events=1")
wb = openpyxl.load_workbook(io.BytesIO(r.data))
ws = wb["التذاكر"]; hdr = [c.value for c in ws[1]]
iy, ih = hdr.index("دون إفصاح"), hdr.index("مدة الإنجاز (ساعة)")
anon_rows = [row for row in ws.iter_rows(min_row=2, values_only=True) if row[iy] == "نعم"]
from datetime import datetime as _dt
ok(anon_rows and all(row[ih] is None and not any(isinstance(v, _dt) and (v.hour or v.minute) for v in row) for row in anon_rows),
   "anonymous Excel rows: no clock time, no duration (%d rows)" % len(anon_rows))
print("ALL OK")
