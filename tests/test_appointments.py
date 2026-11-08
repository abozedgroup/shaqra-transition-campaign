# End-to-end test of in-person appointments and the walk-in queue. Run: python3 tests/test_appointments.py "$(mktemp -d)"
import os, re, sys, sqlite3, hashlib
from datetime import datetime, timedelta
D = sys.argv[1]
os.environ.update(DB_PATH=D + "/tickets.db", SITE_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
                  COOKIE_SECURE="0", ADMIN_USER="admin")
salt = b"0123456789abcdef"
os.environ["ADMIN_PASSWORD_HASH"] = salt.hex() + ":" + hashlib.scrypt(b"adminpass123", salt=salt, n=2**14, r=8, p=1, dklen=32).hex()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import app as A
AP = A.appointments
# a fixed clock: the next Sunday, 09:00 Riyadh
d0 = datetime(2026, 11, 1)
while d0.weekday() != 6:
    d0 += timedelta(days=1)
CLOCK = [d0.replace(hour=9)]
AP.now_local = lambda: CLOCK[0]
def tok(h):
    m = re.search(r'name="csrf_token" value="([^"]+)"', h); return m.group(1) if m else ""
def get(cl, u): r = cl.get(u); return r, r.get_data(as_text=True)
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: sys.exit(1)
def q(sql, *a): return sqlite3.connect(D + "/tickets.db").execute(sql, a).fetchall()
base = dict(req_type="request", topic="general", message="أحتاج مراجعة حضورية", name="سعد", emp_no="321", facility="other",
            job_cat="other", email="saad@moh.gov.sa", mobile="0551112233", consent="1")
a = A.app.test_client(); r, h = get(a, "/admin/login"); a.post("/admin/login", data=dict(csrf_token=tok(h), username="admin", password="adminpass123"))

# 1. employee asks for an appointment in the online form
c = A.app.test_client(); r, h = get(c, "/ticket")
ok("أفضّل موعدًا حضوريًا" in h, "form offers in-person appointment")
c.post("/ticket", data=dict(base, csrf_token=tok(h), want_appt="1", appt_pref="صباح الاثنين"))
r, h = get(c, "/ticket/done"); ref, code = re.findall(r'<span class="ref">([^<]+)</span>', h)[:2]
ok(q("SELECT status, emp_note FROM appointments")[0] == ("requested", "صباح الاثنين"), "appointment request stored")
r, h = get(a, "/admin/queue"); ok(ref in h and "صباح الاثنين" in h and "بانتظار الحجز" in h, "request listed on the queue page")
# anonymous / feedback tickets cannot ask
r, h = get(c, "/ticket"); c.post("/ticket", data=dict(csrf_token=tok(h), req_type="feedback", topic="general", message="ملاحظة مجهولة", anonymous="1", want_appt="1", consent="1"))
ok(len(q("SELECT id FROM appointments")) == 1, "no appointment for anonymous feedback")

# 2. the section books a slot
r, h = get(a, "/admin/t/%s?appt_day=%s" % (ref, (d0 + timedelta(days=1)).date().isoformat()))
ok("احجز موعدًا حضوريًا" in h and "ماذا تريد أن تفعل؟" in h and "الخطوة التالية" in h, "ticket page shows action tabs and booking")
slots = re.findall(r'name="slot" value="([^"]+)"', h); ok(slots and slots[0].endswith("07:30"), "slots start 07:30 next day: %s" % slots[:2])
ok(len(slots) == 21, "7:30-14:30 every 20 min = 21 slots (%d)" % len(slots))
a.post("/admin/t/%s/appt" % ref, data=dict(csrf_token=tok(h), action="book", slot=slots[3], staff_note="أحضر صورة الهوية"))
ok(q("SELECT status, slot FROM appointments")[0] == ("booked", slots[3]), "booked " + slots[3])
ok(q("SELECT status FROM tickets WHERE ref=?", ref)[0][0] == "in_progress", "ticket moved to in progress")
from urllib.parse import unquote
import html as _html
r, h = get(a, "/admin/t/" + ref)
m = re.search(r'href="(mailto:[^"]+)" data-notify', h); ok(bool(m), "email button shown after booking")
mt = unquote(_html.unescape(m.group(1)))
ok(mt.startswith("mailto:saad@moh.gov.sa?subject=") and "موعدك الحضوري – طلب رقم " + ref in mt and "أحضر صورة الهوية" in mt
   and "/status" in mt and code not in mt, "email: address, subject, note, status link, no secret code")
a.post("/admin/t/%s/appt" % ref, data=dict(csrf_token=tok(h), action="notified"))
r, h = get(a, "/admin/t/" + ref); ok("أبلغ الموظف بموعده عبر البريد" in h, "notification recorded in the timeline")
# capacity 1: the same slot is full for another ticket
c2 = A.app.test_client(); r, h = get(c2, "/ticket"); c2.post("/ticket", data=dict(base, csrf_token=tok(h), email="b@moh.gov.sa", mobile="0559998877"))
r, h = get(c2, "/ticket/done"); ref2, code2 = re.findall(r'<span class="ref">([^<]+)</span>', h)[:2]
r, h = get(a, "/admin/t/" + ref2); ok("data-notify" not in h, "no email button without a booked appointment")
r, h = get(a, "/admin/t/%s?appt_day=%s" % (ref2, slots[3][:10]))
ok(re.search(r'value="%s" disabled' % re.escape(slots[3]), h) is not None, "booked slot shown full for others")
r = a.post("/admin/t/%s/appt" % ref2, data=dict(csrf_token=tok(h), action="book", slot=slots[3]), follow_redirects=True)
ok("لم يعد متاحًا" in r.get_data(as_text=True), "double booking refused")
# past slots / weekend never offered
r, h = get(a, "/admin/t/%s?appt_day=%s" % (ref2, d0.date().isoformat()))
today_slots = [s for s in re.findall(r'name="slot" value="([^"]+)"', h) if s.startswith(d0.date().isoformat())]
ok(today_slots and min(today_slots) > d0.strftime("%Y-%m-%d 09:00"), "today only future slots (%s)" % today_slots[:1])

# 3. employee sees it, confirms, asks to change
r, h = get(c, "/status"); h = c.post("/status", data=dict(csrf_token=tok(h), ref=ref, email=code)).get_data(as_text=True)
ok("موعدك الحضوري" in h and "أحضر صورة الهوية" in h and "تأكيد الموعد" in h, "employee sees booked appointment")
r = c.post("/status/appt", data=dict(csrf_token=tok(h), ref=ref, action="confirm")); ok(r.status_code == 302, "confirm")
r, h = get(c, "/status?show=1"); ok("مؤكد" in h and "طلب تغيير الموعد" in h, "status shows confirmed after redirect")
c.post("/status/appt", data=dict(csrf_token=tok(h), ref=ref, action="change", note="أفضل بعد الظهر"))
ok(q("SELECT status, emp_note FROM appointments WHERE slot<>''")[0] == ("change_requested", "أفضل بعد الظهر"), "change requested")
# someone else's session cannot act on it
x = A.app.test_client(); r, h = get(x, "/status"); ok(x.post("/status/appt", data=dict(csrf_token=tok(h), ref=ref, action="cancel")).status_code == 400, "other session refused")
# section re-books
r, h = get(a, "/admin/t/%s?appt_day=%s" % (ref, slots[0][:10]))
a.post("/admin/t/%s/appt" % ref, data=dict(csrf_token=tok(h), action="book", slot=slots[-1]))
ok(q("SELECT status, slot FROM appointments WHERE ticket_id=(SELECT id FROM tickets WHERE ref=?)", ref)[0] == ("booked", slots[-1]), "rebooked to " + slots[-1])

# 4. appointment day: check in at the reception device, queue, call, finish
k = A.app.test_client(); r, h = get(k, "/admin/login"); k.post("/admin/login", data=dict(csrf_token=tok(h), username="admin", password="adminpass123"))
r, h = get(k, "/admin/kiosks"); k.post("/admin/kiosks", data=dict(csrf_token=tok(h), action="activate", name="آيباد"))
r, h = get(k, "/kiosk"); ok("لدي موعد" in h, "kiosk shows 'I have an appointment'")
r, h = get(k, "/kiosk/checkin"); h = k.post("/kiosk/checkin", data=dict(csrf_token=tok(h), ref=ref, key="2233")).get_data(as_text=True)
ok("لا يوجد لهذه التذكرة موعد اليوم" in h and "موعدك" in h, "check-in a day early refused, shows the date")
CLOCK[0] = datetime.strptime(slots[-1], "%Y-%m-%d %H:%M") - timedelta(minutes=10)
r, h = get(k, "/kiosk/checkin"); h = k.post("/kiosk/checkin", data=dict(csrf_token=tok(h), ref=ref, key="2233")).get_data(as_text=True)
ok("تم تسجيلك في الانتظار" in h and "ترتيبك: 1" in h, "checked in on the day, place 1")
# a walk-in arrives at the same time at the kiosk
r, h = get(k, "/kiosk/new?type=request")
k.post("/kiosk/new", data=dict(base, csrf_token=tok(h), email="walk@moh.gov.sa", mobile="0553334444", name="ماجد"))
r, h = get(k, "/kiosk/done"); wref = re.search(r'k-bignum" dir="ltr">(\d+)<', h).group(1)
ok("أمامك 1 في الانتظار" in h and "أنتظر الآن" in h, "walk-in offered to wait, 1 ahead")
r = k.post("/kiosk/walkin", data=dict(csrf_token=tok(h), choice="wait")); h = r.get_data(as_text=True)
ok("ترتيبك: 2" in h and "20 دقيقة" in h, "walk-in queued at 2, ~20 min")
r, h = get(a, "/admin/queue"); ok(h.index(ref) < h.index(wref) and "بالانتظار الآن (2)" in h, "queue page: appointment first, then walk-in")
a.post("/admin/t/%s/appt" % ref, data=dict(csrf_token=tok(h), action="call", next="queue"))
ok(q("SELECT status FROM appointments WHERE ticket_id=(SELECT id FROM tickets WHERE ref=?)", ref)[0][0] == "serving", "called")
r, h = get(c, "/status?show=1"); ok("قيد الخدمة الآن" in h, "employee page shows being served")
CLOCK[0] += timedelta(minutes=15)
r, h = get(a, "/admin/queue"); r = a.post("/admin/t/%s/appt" % ref, data=dict(csrf_token=tok(h), action="done"), follow_redirects=True)
ok("انتهت الخدمة الحضورية. اكتب الرد" in r.get_data(as_text=True), "finish -> back to ticket to write the reply")
r, h = get(a, "/admin/t/" + ref); a.post("/admin/t/" + ref, data=dict(csrf_token=tok(h), action="resolve", reply="تمت الخدمة حضوريًا"))
ok(q("SELECT status FROM tickets WHERE ref=?", ref)[0][0] == "resolved", "then resolved -> rating cycle as usual")

# 5. closed day / outside hours / busy -> the device offers an appointment
r, h = get(a, "/admin/queue")
a.post("/admin/queue/closure", data=dict(csrf_token=tok(h), action="add", day=CLOCK[0].date().isoformat(), reason="تدريب"))
r, h = get(k, "/kiosk/new?type=request"); k.post("/kiosk/new", data=dict(base, csrf_token=tok(h), email="c@moh.gov.sa", mobile="0551231234"))
r, h = get(k, "/kiosk/done"); ok("القسم مغلق اليوم" in h and "أطلب موعدًا لاحقًا" in h and "أنتظر الآن" not in h, "closed day: appointment offered")
h = k.post("/kiosk/walkin", data=dict(csrf_token=tok(h), choice="appt")).get_data(as_text=True)
ok("تم طلب موعدك" in h, "appointment requested from the device")
r, h = get(a, "/admin/queue"); xid = re.search(r'name="action" value="remove"><input type="hidden" name="id" value="(\d+)"', h).group(1)
a.post("/admin/queue/closure", data=dict(csrf_token=tok(h), action="remove", id=xid))
CLOCK[0] = CLOCK[0].replace(hour=16)
r, h = get(k, "/kiosk/new?type=request"); k.post("/kiosk/new", data=dict(base, csrf_token=tok(h), email="e@moh.gov.sa", mobile="0551231299"))
r, h = get(k, "/kiosk/done"); ok("لا يستقبل في هذا الوقت" in h, "after hours: appointment offered")
CLOCK[0] = CLOCK[0].replace(hour=10)
# make the section busy: 4 walk-ins waiting, avg 20 min -> > 60
for i in range(4):
    r, h = get(k, "/kiosk/new?type=request"); k.post("/kiosk/new", data=dict(base, csrf_token=tok(h), email="w%d@moh.gov.sa" % i, mobile="055000000%d" % i))
    r, h = get(k, "/kiosk/done"); k.post("/kiosk/walkin", data=dict(csrf_token=tok(h), choice="wait"))
r, h = get(k, "/kiosk/new?type=request"); k.post("/kiosk/new", data=dict(base, csrf_token=tok(h), email="f@moh.gov.sa", mobile="0551231200"))
r, h = get(k, "/kiosk/done"); ok("القسم مزدحم الآن" in h and "أنتظر رغم ذلك" in h, "busy: appointment offered, can still wait")
# feedback at the kiosk: no queue offer
r, h = get(k, "/kiosk/new?type=feedback"); k.post("/kiosk/new", data=dict(csrf_token=tok(h), req_type="feedback", topic="general", message="ملاحظة", anonymous="1", consent="1"))
r, h = get(k, "/kiosk/done"); ok("أنتظر الآن" not in h and "أطلب موعدًا" not in h, "feedback: no queue")

# 6. no-show sweep next day + indicators
pending = q("SELECT COUNT(*) FROM appointments WHERE status='checked_in'")[0][0]
CLOCK[0] += timedelta(days=1)
A._sweep["at"] = 0; get(a, "/admin")
ok(q("SELECT COUNT(*) FROM appointments WHERE status='checked_in'")[0][0] == 0, "yesterday's queue closed by the sweep (%d)" % pending)
r, h = get(a, "/admin/stats?from=2026-01-01&to=2026-12-31"); ok("المواعيد الحضورية والانتظار" in h and "حضوري بدون موعد" in h, "indicators section")
# settings: invalid hours refused, valid saved
r, h = get(a, "/admin/queue")
r = a.post("/admin/queue/settings", data=dict(csrf_token=tok(h), appt_start="15:00", appt_end="08:00", slot_min="15", capacity="2", appt_enabled="1"), follow_redirects=True)
ok("البداية قبل النهاية" in r.get_data(as_text=True), "invalid hours refused")
a.post("/admin/queue/settings", data=dict(csrf_token=tok(h), appt_start="08:00", appt_end="15:00", slot_min="15", capacity="2", location="مكتب 12", appt_enabled="1"))
ok(q("SELECT appt_start, appt_end, slot_min, capacity, location FROM departments WHERE key='care'")[0] == ("08:00", "15:00", 15, 2, "مكتب 12"), "settings saved")
# staff of another section cannot reach this queue's tickets
r, h = get(a, "/admin/users"); a.post("/admin/users", data=dict(csrf_token=tok(h), display_name="موظف الإجازات", username="lv1", role="staff", dept_id="5", password="leavespass1"))
s = A.app.test_client(); r, h = get(s, "/admin/login"); s.post("/admin/login", data=dict(csrf_token=tok(h), username="lv1", password="leavespass1"))
r, h = get(s, "/admin/queue"); ok(ref2 not in h and "الإجازات" in h, "staff sees only own section queue")
ok(s.post("/admin/t/%s/appt" % ref2, data=dict(csrf_token=tok(h), action="cancel")).status_code == 404, "staff cannot act on another section's appointment")
ok(s.post("/admin/queue/settings", data=dict(csrf_token=tok(h), appt_start="08:00", appt_end="09:00")).status_code == 404, "staff cannot change settings")
print("ALL OK")
