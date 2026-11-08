# End-to-end test of the ticketing app. Run: python3 tests/test_flow.py "$(mktemp -d)"
import os, re, sys, sqlite3, hashlib, secrets
D = sys.argv[1]
os.environ.update(DB_PATH=D + "/tickets.db", SITE_DIR=D, COOKIE_SECURE="0", ADMIN_USER="admin")
salt = secrets.token_bytes(16)
os.environ["ADMIN_PASSWORD_HASH"] = salt.hex() + ":" + hashlib.scrypt(b"adminpass123", salt=salt, n=2**14, r=8, p=1, dklen=32).hex()
# old-schema DB with one existing ticket (migration test)
con = sqlite3.connect(D + "/tickets.db")
con.executescript("""CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, email TEXT NOT NULL, mobile TEXT NOT NULL, emp_no TEXT NOT NULL, name TEXT NOT NULL, facility TEXT NOT NULL,
 job_cat TEXT NOT NULL, req_type TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', reply TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '', lang TEXT NOT NULL DEFAULT 'ar');
INSERT INTO tickets(ref,created_at,updated_at,email,mobile,emp_no,name,facility,job_cat,req_type,message,note)
 VALUES('SHQ-261101-OLD22','2026-11-01T08:00:00Z','2026-11-01T08:00:00Z','old@moh.gov.sa','0500000000','123','موظف قديم','مستشفى ثادق','إداري','inquiry','نص قديم للتجربة','ملاحظة قديمة');""")
con.commit(); con.close()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import app as A
c = A.app.test_client()
def tok(html): return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
def get(cl, u): r = cl.get(u); return r, r.get_data(as_text=True)
ok = lambda cond, msg: print(("PASS " if cond else "FAIL ") + msg) or (cond or sys.exit(1))

# migration
r = sqlite3.connect(D + "/tickets.db").execute("SELECT dept_id, topic, due_at FROM tickets WHERE ref='SHQ-261101-OLD22'").fetchone()
ok(r[0] == 1 and r[1] == "general" and r[2], "old ticket migrated to Employee Care with deadline %s" % r[2])

# public form shows topics + anon
r, h = get(c, "/ticket")
ok(r.status_code == 200 and "الإجازات" in h and "لا أريد الإفصاح" in h and 'value="general"' in h, "form shows topics and anonymous option")
ok("العناية بالموظفين</option>" not in h, "intake section is not a topic choice")
t = tok(h)
# named inquiry about leaves
base = dict(csrf_token=t, req_type="request", topic="leaves", message="أريد الاستفسار عن رصيد إجازتي", name="أحمد محمد",
            emp_no="12345", facility="shaqra_hospital", job_cat="nursing", email="ahmad@moh.gov.sa", mobile="0512345678", consent="1")
r = c.post("/ticket", data=base); ok(r.status_code == 302, "named ticket created")
r, h = get(c, "/ticket/done"); ref1 = re.search(r'<span class="ref">(\d+)</span>', h).group(1); ok(ref1 == "1001", "first short ref is 1001")
code1 = re.findall(r'<span class="ref">([^<]+)</span>', h)[1]; ok(re.match(r"^[A-Z0-9]{3}-[A-Z0-9]{3}$", code1), "named ticket also gets a follow-up code " + code1)
# missing topic
r = c.post("/ticket", data=dict(base, topic="")); ok(r.status_code == 400 and "اختر موضوع طلبك" in r.get_data(as_text=True), "topic required")
# anonymous inquiry is NOT allowed -> needs personal data
r = c.post("/ticket", data=dict(csrf_token=t, req_type="request", topic="general", message="سؤال بدون بيانات شخصية", anonymous="1", consent="1"))
ok(r.status_code == 400, "anonymous not accepted for an inquiry")
# anonymous complaint
r = c.post("/ticket", data=dict(csrf_token=t, req_type="feedback", topic="payroll", message="شكوى عن تأخر صرف البدلات", anonymous="1",
                                name="should not be stored", email="x@moh.gov.sa", consent="1"))
ok(r.status_code == 302, "anonymous complaint created")
r, h = get(c, "/ticket/done"); refs = re.findall(r'<span class="ref">([^<]+)</span>', h); ref2 = refs[0]
code = refs[1]; ok(ref2 == "1002", "second ref 1002"); ok(True, "anon done page shows code " + code)
row = sqlite3.connect(D + "/tickets.db").execute("SELECT name,email,mobile,emp_no,anonymous,dept_id FROM tickets WHERE ref=?", (ref2,)).fetchone()
ok(row[:4] == ("", "", "", "") and row[4] == 1 and row[5] == 2, "anonymous stores no identity and goes to complaints section")
# status lookup
r, h = get(c, "/status"); t2 = tok(h)
h = c.post("/status", data=dict(csrf_token=t2, ref=ref2, email=code.lower().replace("-", " "))).get_data(as_text=True)
ok("الشكاوى والملاحظات" in h and "جديدة" in h, "anonymous status lookup by code")
h = c.post("/status", data=dict(csrf_token=t2, ref=ref2, email="AAAA-BBBB")).get_data(as_text=True); ok("لا توجد تذكرة" in h, "wrong code rejected")
h = c.post("/status", data=dict(csrf_token=t2, ref=ref1, email="ahmad@moh.gov.sa")).get_data(as_text=True); ok("لا توجد تذكرة" in h, "new ticket: email alone no longer opens it")
h = c.post("/status", data=dict(csrf_token=t2, ref=ref1, email=code1)).get_data(as_text=True); ok("العناية بالموظفين" in h, "named lookup by code")
h = c.post("/status", data=dict(csrf_token=t2, ref="SHQ-261101-OLD22", email="old@moh.gov.sa")).get_data(as_text=True); ok("SHQ-261101-OLD22" in h and "لا توجد تذكرة" not in h, "legacy ticket still opens by email")

# admin
a = A.app.test_client(); r, h = get(a, "/admin/login")
r = a.post("/admin/login", data=dict(csrf_token=tok(h), username="admin", password="adminpass123")); ok(r.status_code == 302, "env admin login")
r, h = get(a, "/admin"); ok(ref1 in h and ref2 in h and "نظرة على الأقسام" in h, "admin sees all + per-section summary")
ok('aria-current="page">المفتوحة' in h, "default tab is open tickets")
# create staff for leaves (dept id of leaves)
leaves = sqlite3.connect(D + "/tickets.db").execute("SELECT id FROM departments WHERE key='leaves'").fetchone()[0]
care = 1
r, h = get(a, "/admin/users"); at = tok(h)
h = a.post("/admin/users", data=dict(csrf_token=at, display_name="سارة الإجازات", username="sara.leaves", role="staff", dept_id=str(leaves), password="leavespass1")).get_data(as_text=True)
ok("تم إنشاء الحساب" in h, "staff account created")
h = a.post("/admin/users", data=dict(csrf_token=at, display_name="خالد العناية", username="khaled.care", role="staff", dept_id=str(care), password="carepass123")).get_data(as_text=True)
ok("تم إنشاء الحساب" in h, "care staff account created")
h = a.post("/admin/users", data=dict(csrf_token=at, display_name="x", username="Bad User", role="staff", dept_id="1", password="short")).get_data(as_text=True)
ok("اكتب اسم الموظف" in h, "validation on bad user")
# add a department
r, h = get(a, "/admin/departments")
h = a.post("/admin/departments", data=dict(csrf_token=tok(h), name_ar="السكن والنقل", name_en="Housing and transport", sla_days="4", sort="200", selectable="1")).get_data(as_text=True)
ok("تمت إضافة القسم" in h and "السكن والنقل" in h, "department added")
r, h = get(c, "/ticket"); ok("السكن والنقل" in h, "new department appears as employee topic")
r, h = get(c, "/en/ticket"); ok("Housing and transport" in h and "Leaves" in h, "English topic names")

# care staff logs in, sees ref1 but not complaint
k = A.app.test_client(); r, h = get(k, "/admin/login")
k.post("/admin/login", data=dict(csrf_token=tok(h), username="khaled.care", password="carepass123"))
r, h = get(k, "/admin"); ok(ref1 in h and ref2 not in h and "SHQ-261101-OLD22" in h, "care staff sees only care tickets")
r, h = get(k, "/admin/t/" + ref2); ok(r.status_code == 404, "care staff cannot open complaint")
r, h = get(k, "/admin/users"); ok(r.status_code == 404, "staff cannot manage users")
r, h = get(k, "/admin/t/" + ref1); kt = tok(h)
ok('selected>الإجازات' in h, "escalation target preselected from topic")
h = k.post("/admin/t/" + ref1, data=dict(csrf_token=kt, action="escalate", to_dept=str(leaves), reason="")).get_data(as_text=True)
ok("اكتب سبب التصعيد" in h, "reason required")
k.post("/admin/t/" + ref1, data=dict(csrf_token=kt, action="note", note="راجعت الطلب، يحتاج قسم الإجازات"))
r = k.post("/admin/t/" + ref1, data=dict(csrf_token=kt, action="escalate", to_dept=str(leaves), reason="يحتاج تأكيد رصيد الإجازة من النظام"))
ok(r.status_code == 302 and "moved=" in r.headers["Location"], "escalated to leaves")
r, h = get(k, "/admin/t/" + ref1); ok(r.status_code == 404, "care staff no longer sees escalated ticket")
# leaves staff
s = A.app.test_client(); r, h = get(s, "/admin/login")
s.post("/admin/login", data=dict(csrf_token=tok(h), username="sara.leaves", password="leavespass1"))
r, h = get(s, "/admin"); ok(ref1 in h and "محالة" in h, "leaves staff sees escalated ticket")
r, h = get(s, "/admin/t/" + ref1)
ok("يحتاج تأكيد رصيد" in h and "راجعت الطلب" in h and "من العناية بالموظفين إلى الإجازات" in h, "timeline shows note and escalation")
h = s.post("/admin/t/" + ref1, data=dict(csrf_token=tok(h), action="resolve", reply="رصيدك 30 يومًا"), follow_redirects=True).get_data(as_text=True)
ok("أُرسل الرد للموظف لتقييمه" in h and "رد على الموظف" in h and "بانتظار التقييم" in h, "leaves staff replies and sends for rating")
h = c.post("/status", data=dict(csrf_token=t2, ref=ref1, email=code1)).get_data(as_text=True)
ok("رصيدك 30" in h and "بانتظار تقييمك" in h and "الإجازات" in h and "قيّم الرد" in h, "employee sees reply + rating form")
# not resolved -> back to section
h = c.post("/status", data=dict(csrf_token=t2, action="rate", ref=ref1, stars="2", resolved="0", comment="ما زال الرصيد خاطئ")).get_data(as_text=True)
ok("أُعيدت تذكرتك" in h and "قيد المعالجة" in h, "not resolved -> reopened")
row = sqlite3.connect(D + "/tickets.db").execute("SELECT status, rating FROM tickets WHERE ref=?", (ref1,)).fetchone()
ok(row == ("in_progress", 2), "ticket back in progress with rating 2")
r, h = get(s, "/admin/t/" + ref1)
h = s.post("/admin/t/" + ref1, data=dict(csrf_token=tok(h), action="resolve", reply="تم تصحيح الرصيد إلى 30 يومًا"), follow_redirects=True).get_data(as_text=True)
h = c.post("/status", data=dict(csrf_token=t2, ref=ref1, email=code1)).get_data(as_text=True)
h = c.post("/status", data=dict(csrf_token=t2, action="rate", ref=ref1, stars="5", resolved="1", comment="شكرًا")).get_data(as_text=True)
ok("شكرًا لتقييمك" in h and "مغلقة" in h, "rated 5 -> closed")
h = c.post("/status", data=dict(csrf_token=t2, action="rate", ref=ref1, stars="1", resolved="1")).get_data(as_text=True)
ok(sqlite3.connect(D + "/tickets.db").execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 2, "cannot rate a closed ticket again")
r, h = get(s, "/admin/t/" + ref1); ok("لم يُحل الطلب" in h and "5/5" in h and "إعادة فتح" in h, "staff sees both ratings")
# rating someone else's ticket without lookup is refused
r = A.app.test_client().post("/status", data=dict(csrf_token="x", action="rate", ref=ref1, stars="5", resolved="1")); ok(r.status_code == 400, "rate requires session")
# overdue
sqlite3.connect(D + "/tickets.db").execute("UPDATE tickets SET due_at='2026-01-01T00:00:00Z' WHERE ref='SHQ-261101-OLD22'").connection.commit()
r, h = get(a, "/admin?late=1"); ok("SHQ-261101-OLD22" in h and ref2 not in h and "متأخرة منذ" in h, "overdue filter")
# deactivate staff -> session dies
r, h = get(a, "/admin/users"); uid = sqlite3.connect(D + "/tickets.db").execute("SELECT id FROM users WHERE username='sara.leaves'").fetchone()[0]
a.post("/admin/users", data=dict(csrf_token=tok(h), id=str(uid), display_name="سارة الإجازات", role="staff", dept_id=str(leaves)))
r = s.get("/admin"); ok(r.status_code == 302, "deactivated user is logged out")
# export + password page + delete
r = a.get("/admin/export.csv"); ok("الموضوع" in r.get_data(as_text=True) and "مجهول" in r.get_data(as_text=True), "CSV export has new columns")
r, h = get(k, "/admin/password")
h = k.post("/admin/password", data=dict(csrf_token=tok(h), current="carepass123", new="newcarepass1", new2="newcarepass1")).get_data(as_text=True)
ok("تم تغيير كلمة المرور" in h, "staff changes own password")
r = k.post("/admin/t/SHQ-261101-OLD22/delete", data=dict(csrf_token=kt)); ok(r.status_code == 404, "staff cannot delete")
r, h = get(a, "/admin/t/" + ref2)
r = a.post("/admin/t/%s/delete" % ref2, data=dict(csrf_token=tok(h))); ok(r.status_code == 302, "admin deletes")

# ---------------- types, photos
import io as _io
from PIL import Image as _I
r = sqlite3.connect(D + "/tickets.db").execute("SELECT req_type FROM tickets WHERE ref='SHQ-261101-OLD22'").fetchone()
ok(r[0] == "request", "legacy inquiry migrated to request")
r, h = get(c, "/ticket?type=complaint"); ok('value="feedback" id' not in h and re.search(r'value="feedback"\s+checked', h), "old ?type=complaint link preselects feedback")
def jpg(gps=True, size=(800, 600)):
    im = _I.new("RGB", size, (200, 30, 30)); ex = _I.Exif()
    if gps: ex[0x010F] = "SecretPhoneMaker"; ex[0x8825] = {2: (24.0, 1.0, 1.0)}
    b = _io.BytesIO(); im.save(b, "JPEG", exif=ex.tobytes()); b.seek(0); return b
r, h = get(c, "/ticket"); t = tok(h)
d = dict(base, csrf_token=t); d["photos"] = [(jpg(), "a.jpg"), (jpg(), "b.jpg")]
r = c.post("/ticket", data=d, content_type="multipart/form-data"); ok(r.status_code == 302, "ticket with 2 photos")
r, h = get(c, "/ticket/done"); ref3, code3 = re.findall(r'<span class="ref">([^<]+)</span>', h)[:2]
rows = sqlite3.connect(D + "/tickets.db").execute("SELECT token FROM attachments a JOIN tickets t ON t.id=a.ticket_id WHERE t.ref=?", (ref3,)).fetchall()
ok(len(rows) == 2, "2 attachments stored")
raw = open(D + "/uploads/" + rows[0][0] + ".jpg", "rb").read()
ok(b"SecretPhoneMaker" not in raw and not _I.open(_io.BytesIO(raw)).getexif(), "EXIF/GPS removed")
d = dict(base, csrf_token=t); d["photos"] = [(_io.BytesIO(b"<?php evil ?>"), "x.jpg")]
r = c.post("/ticket", data=d, content_type="multipart/form-data"); ok(r.status_code == 400 and "ليس صورة صالحة" in r.get_data(as_text=True), "non-image rejected")
d = dict(base, csrf_token=t); d["photos"] = [(jpg(), "%d.jpg" % k) for k in range(4)]
r = c.post("/ticket", data=d, content_type="multipart/form-data"); ok(r.status_code == 400 and "3 صور كحد أقصى" in r.get_data(as_text=True), "4 photos rejected")
png = _io.BytesIO(); _I.new("RGBA", (300, 300), (0, 0, 0, 0)).save(png, "PNG"); png.seek(0)
d = dict(base, csrf_token=t); d["photos"] = [(png, "t.png")]
r = c.post("/ticket", data=d, content_type="multipart/form-data"); ok(r.status_code == 302, "transparent PNG accepted"); get(c, "/ticket/done")
# photo access control
ph = "/admin/f/" + rows[0][0]
_r = a.get(ph); ok(_r.status_code == 200 and _r.mimetype == "image/jpeg", "admin views photo")
ok(A.app.test_client().get(ph).status_code == 302, "anonymous visitor redirected to login")
s2 = A.app.test_client(); r, h = get(s2, "/admin/login")
r2, h2 = get(a, "/admin/users"); a.post("/admin/users", data=dict(csrf_token=tok(h2), display_name="عمر الإجازات", username="omar.leaves", role="staff", dept_id=str(leaves), password="omarleaves1"))
s2.post("/admin/login", data=dict(csrf_token=tok(h), username="omar.leaves", password="omarleaves1"))
ok(s2.get(ph).status_code == 404, "leaves staff cannot see a photo of a ticket still in Employee Care")
k3 = A.app.test_client(); r, h = get(k3, "/admin/login"); k3.post("/admin/login", data=dict(csrf_token=tok(h), username="khaled.care", password="newcarepass1"))
ok(k3.get(ph).status_code == 200, "care staff can see it")
ok(c.get("/status/f/" + rows[0][0]).status_code == 404, "public photo url needs a lookup first")
# staff reply with photo -> employee sees it
r, h = get(a, "/admin/t/" + ref3)
r = a.post("/admin/t/" + ref3, data=dict(csrf_token=tok(h), action="save", reply="مرفق النموذج", photos=[(jpg(False), "form.jpg")]), content_type="multipart/form-data")
ok(r.status_code == 302, "staff reply with photo")
r, h = get(c, "/status")
h = c.post("/status", data=dict(csrf_token=tok(h), ref="#" + ref3, email=code3.lower())).get_data(as_text=True)
toks = re.findall(r'/status/f/([A-Za-z0-9_-]+)"', h)
ok("صور مرفقة من القسم" in h and len(set(toks)) == 3, "employee sees section photo and own photos")
ok(c.get("/status/f/" + toks[0]).status_code == 200, "employee can open photo after lookup")
r, h = get(a, "/admin/t/" + ref3); ok("صور أرفقها الموظف" in h and "إرفاق صور" in h and "قيد المعالجة" in h, "admin ticket shows photos + timeline; save keeps in progress")
# delete removes files
a.post("/admin/t/%s/delete" % ref3, data=dict(csrf_token=tok(h)))
ok(not os.path.exists(D + "/uploads/" + rows[0][0] + ".jpg"), "deleting ticket deletes photo files")

# ---------------- auto close after 5 working days
AREF = sqlite3.connect(D + "/tickets.db").execute("SELECT ref FROM tickets WHERE status IN ('new','in_progress','escalated') AND ref NOT LIKE 'SHQ%' ORDER BY id LIMIT 1").fetchone()[0]
r, h = get(a, "/admin/t/" + AREF)
a.post("/admin/t/" + AREF, data=dict(csrf_token=tok(h), action="resolve", reply="تم"))
due = sqlite3.connect(D + "/tickets.db").execute("SELECT rate_due_at, resolved_at FROM tickets WHERE ref=?", (AREF,)).fetchone()
ok(due[0] > due[1], "rate due set: %s (resolved %s)" % (due[0], due[1]))
con = sqlite3.connect(D + "/tickets.db"); con.execute("UPDATE tickets SET rate_due_at='2026-01-01T00:00:00Z' WHERE ref=?", (AREF,)); con.commit()
A._sweep["at"] = 0
r, h = get(a, "/admin/t/" + AREF); ok("تلقائيًا بعد انتهاء" in h and "إغلاق تلقائي" in h, "auto-closed after rating window")
ok(sqlite3.connect(D + "/tickets.db").execute("SELECT close_reason FROM tickets WHERE ref=?", (AREF,)).fetchone()[0] == "auto", "close_reason auto")
# staff close without rating + reopen
r, h = get(a, "/admin/t/SHQ-261101-OLD22")
h = a.post("/admin/t/SHQ-261101-OLD22", data=dict(csrf_token=tok(h), action="close", close_note=""), follow_redirects=True).get_data(as_text=True)
ok("اكتب سبب الإغلاق" in h, "close needs reason")
a.post("/admin/t/SHQ-261101-OLD22", data=dict(csrf_token=tok(h), action="close", close_note="مكررة"))
h = get(a, "/admin/t/SHQ-261101-OLD22")[1]; ok("أغلقها القسم دون تقييم" in h, "closed by staff")
a.post("/admin/t/SHQ-261101-OLD22", data=dict(csrf_token=tok(h), action="reopen", reopen_note="خطأ"))
ok(sqlite3.connect(D + "/tickets.db").execute("SELECT status FROM tickets WHERE ref='SHQ-261101-OLD22'").fetchone()[0] == "in_progress", "reopened")
# quick open + list filters
r = a.get("/admin/open?ref=%D9%A1%D9%A0%D9%A0%D9%A1"); ok(r.status_code == 302 and r.headers["Location"].endswith("/admin/t/1001"), "quick open with Arabic digits")
r, h = get(a, "/admin?status=resolved"); ok(r.status_code == 200, "resolved filter")

# ---------------- kiosk
kk = A.app.test_client()
r, h = get(kk, "/kiosk"); ok(r.status_code == 403 and "غير مفعّل" in h, "kiosk blocked before activation")
r, h = get(kk, "/admin/login"); kk.post("/admin/login", data=dict(csrf_token=tok(h), username="admin", password="adminpass123"))
r, h = get(kk, "/admin/kiosks")
r = kk.post("/admin/kiosks", data=dict(csrf_token=tok(h), action="activate", name="آيباد المدخل"))
ok(r.status_code == 302 and "shq_k=" in r.headers.get("Set-Cookie", ""), "kiosk activated, cookie set")
ok(kk.get("/admin").status_code == 302, "admin logged out on the kiosk device")
r, h = get(kk, "/kiosk"); ok(r.status_code == 200 and "قيّم خدمتك" in h, "kiosk home")
r, h = get(kk, "/kiosk/new?type=request")
kd = dict(csrf_token=tok(h), req_type="request", topic="payroll", message="شهادة راتب", name="فهد علي", emp_no="5555",
          facility="marat_hospital", job_cat="admin", email="fahad@moh.gov.sa", mobile="0551234567", consent="1")
r = kk.post("/kiosk/new", data=dict(kd, email="")); ok(r.status_code == 400, "kiosk requires email")
r = kk.post("/kiosk/new", data=kd); ok(r.status_code == 302, "kiosk ticket created")
r, h = get(kk, "/kiosk/done"); kref = re.search(r'k-bignum" dir="ltr">(\d+)<', h).group(1); ok("العناية بالموظفين" in h, "kiosk done shows number %s and where to go" % kref)
row = sqlite3.connect(D + "/tickets.db").execute("SELECT channel, kiosk_id FROM tickets WHERE ref=?", (kref,)).fetchone()
ok(row[0] == "walkin" and row[1], "ticket marked walk-in")
r, h = get(kk, "/kiosk/rate")
h = kk.post("/kiosk/rate", data=dict(csrf_token=tok(h), ref=kref, key="4567")).get_data(as_text=True); ok("لم تنتهِ الخدمة" in h, "cannot rate before staff finishes")
r, h2 = get(a, "/admin/t/" + kref); ok("حضوري" in h2 and "جهاز الاستقبال" in h2, "staff sees walk-in")
a.post("/admin/t/" + kref, data=dict(csrf_token=tok(h2), action="resolve", reply="سُلّمت الشهادة"))
r, h = get(kk, "/kiosk/rate"); h = kk.post("/kiosk/rate", data=dict(csrf_token=tok(h), ref=kref, key="9999")).get_data(as_text=True); ok("لم نجد" in h, "wrong last-4 rejected")
h = kk.post("/kiosk/rate", data=dict(csrf_token=tok(h), ref=kref, key="٤٥٦٧")).get_data(as_text=True); ok("هل تم حل طلبك" in h, "rating form after last-4 (Arabic digits)")
h = kk.post("/kiosk/rate", data=dict(csrf_token=tok(h), action="rate", ref=kref, stars="4", resolved="1")).get_data(as_text=True)
ok("شكرًا لك" in h, "kiosk rating saved")
ok(sqlite3.connect(D + "/tickets.db").execute("SELECT via FROM ratings ORDER BY id DESC").fetchone()[0] == "kiosk", "rating via kiosk")
# disable kiosk
r, h = get(a, "/admin/kiosks"); kid = sqlite3.connect(D + "/tickets.db").execute("SELECT id FROM kiosks").fetchone()[0]
a.post("/admin/kiosks", data=dict(csrf_token=tok(h), action="disable", id=str(kid)))
ok(kk.get("/kiosk").status_code == 403, "disabled kiosk blocked")

# ---------------- indicators
r, h = get(a, "/admin/stats"); ok(r.status_code == 200 and "نسبة الرضا" in h and "<svg" in h and "حسب القسم" in h and "الخلاصة" in h, "stats page renders")
ok("4.0 / 5" in h or "/ 5" in h, "average rating shown")
r, h = get(a, "/admin/stats?from=2025-01-01&to=2026-12-31&channel=walkin"); ok(r.status_code == 200 and "<svg" in h, "long range weekly + channel filter")
r = a.get("/admin/stats.csv"); ok("حسب الموظف المسؤول" in r.get_data(as_text=True), "stats csv")
r, h = get(s2, "/admin/stats"); ok(r.status_code == 200 and "حسب القسم" not in h, "staff sees own section stats only")
# ---------------- maintenance fixes
import threading as _th
con = sqlite3.connect(D + "/tickets.db")
open_ref = con.execute("SELECT ref FROM tickets WHERE status='closed' LIMIT 1").fetchone()[0]
r, h = get(a, "/admin/t/" + open_ref)
r = a.post("/admin/t/" + open_ref, data=dict(csrf_token=tok(h), action="escalate", to_dept="3", reason="محاولة على مغلقة"))
ok(r.status_code == 400, "cannot escalate a closed ticket")
r = a.post("/admin/t/" + open_ref, data=dict(csrf_token=tok(h), action="take")); ok(r.status_code == 400, "cannot take a closed ticket")
for u_ in ("/admin?dept=99999999999999999999&page=99999999999999999999", "/admin/stats?dept=99999999999999999999&from=0001-01-01&to=9999-12-31",
           "/admin/stats?dept=%C2%B2"):
    ok(a.get(u_).status_code == 200, "no crash: " + u_[:40])
r, h = get(a, "/admin/users")
ok(a.post("/admin/users", data=dict(csrf_token=tok(h), id="99999999999999999999", display_name="xxx", role="staff", dept_id="99999999999999999999")).status_code in (200, 400, 404), "users huge id no crash")
bomb = _io.BytesIO(); _I.new("1", (9000, 9000)).save(bomb, "PNG"); bomb_n = len(bomb.getvalue()); bomb.seek(0)
r, h = get(c, "/ticket"); d = dict(base, csrf_token=tok(h)); d["photos"] = [(bomb, "b.png")]
r = c.post("/ticket", data=d, content_type="multipart/form-data"); ok(r.status_code == 400 and "8 ميجابايت" in r.get_data(as_text=True), "decompression bomb refused (%d bytes)" % bomb_n)
before = con.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
errs_ = []
def mk(i):
    try:
        cl = A.app.test_client(); hh = cl.get("/ticket").get_data(as_text=True)
        rr = cl.post("/ticket", data=dict(base, csrf_token=tok(hh), email="u%d@moh.gov.sa" % i))
        if rr.status_code != 302: errs_.append(rr.status_code)
    except Exception as e: errs_.append(repr(e))
A._rl.clear()
ths = [_th.Thread(target=mk, args=(i,)) for i in range(12)]; [t_.start() for t_ in ths]; [t_.join() for t_ in ths]
refs_ = [r_[0] for r_ in sqlite3.connect(D + "/tickets.db").execute("SELECT ref FROM tickets WHERE ref NOT LIKE 'SHQ%'")]
ok(not errs_ and len(refs_) == len(set(refs_)) and sqlite3.connect(D + "/tickets.db").execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == before + 12, "12 concurrent tickets, unique numbers %s" % errs_[:3])
mx = max(int(x) for x in refs_); r, h = get(a, "/admin/t/%d" % mx); a.post("/admin/t/%d/delete" % mx, data=dict(csrf_token=tok(h)))
r, h = get(c, "/ticket"); c.post("/ticket", data=dict(base, csrf_token=tok(h), email="z@moh.gov.sa"))
r, h = get(c, "/ticket/done"); ok(re.findall(r'<span class="ref">([^<]+)</span>', h)[0] == str(mx + 1), "number after delete is %d (not reused)" % (mx + 1))
r, h = get(c, "/ticket"); c.post("/ticket", data=dict(base, csrf_token=tok(h), email="dbl@moh.gov.sa"))
r, h = get(c, "/ticket/done"); dref, dcode = re.findall(r'<span class="ref">([^<]+)</span>', h)[:2]
r, h = get(a, "/admin/t/" + dref); a.post("/admin/t/" + dref, data=dict(csrf_token=tok(h), action="resolve", reply="تم"))
okn = []
def rate_():
    try:
        with A.app.app_context():
            con_ = A.db(); rr = con_.execute("SELECT * FROM tickets WHERE ref=?", (dref,)).fetchone(); okn.append(A.save_rating(con_, rr, 5, True, "", "online"))
    except Exception as e: okn.append(repr(e))
ths = [_th.Thread(target=rate_) for _ in range(5)]; [t_.start() for t_ in ths]; [t_.join() for t_ in ths]
n_r = sqlite3.connect(D + "/tickets.db").execute("SELECT COUNT(*) FROM ratings r JOIN tickets t ON t.id=r.ticket_id WHERE t.ref=?", (dref,)).fetchone()[0]
ok(n_r == 1 and okn.count(True) == 1, "5 simultaneous ratings -> stored once %s" % okn)
r, h = get(c, "/ticket"); c.post("/ticket", data=dict(base, csrf_token=tok(h), email="late@moh.gov.sa"))
r, h = get(c, "/ticket/done"); lref = re.findall(r'<span class="ref">([^<]+)</span>', h)[0]
con = sqlite3.connect(D + "/tickets.db"); con.execute("UPDATE tickets SET due_at='2026-01-01T00:00:00Z' WHERE ref=?", (lref,)); con.commit()
r, h = get(a, "/admin/t/" + lref); a.post("/admin/t/" + lref, data=dict(csrf_token=tok(h), action="escalate", to_dept="3", reason="تحويل بعد التأخر"))
ok(sqlite3.connect(D + "/tickets.db").execute("SELECT sla_breached FROM tickets WHERE ref=?", (lref,)).fetchone()[0] == 1, "late leg remembered after escalation")
r, h = get(a, "/admin/t/" + lref)
h = a.post("/admin/t/" + lref, data=dict(csrf_token=tok(h), action="newcode"), follow_redirects=True).get_data(as_text=True)
nc = re.search(r'رمز المتابعة الجديد: <b dir="ltr" class="k-code">([A-Z0-9]{3}-[A-Z0-9]{3})</b>', h); ok(bool(nc), "new code shown once to staff")
r, h = get(c, "/status"); h = c.post("/status", data=dict(csrf_token=tok(h), ref=lref, email=nc.group(1))).get_data(as_text=True); ok("لا توجد تذكرة" not in h, "new code works")
x1 = A.app.test_client(); x2 = A.app.test_client()
for x_ in (x1, x2):
    r, h = get(x_, "/admin/login"); x_.post("/admin/login", data=dict(csrf_token=tok(h), username="khaled.care", password="newcarepass1"))
ok(x2.get("/admin").status_code == 200, "second session active")
r, h = get(x1, "/admin/password"); x1.post("/admin/password", data=dict(csrf_token=tok(h), current="newcarepass1", new="anotherpass12", new2="anotherpass12"))
ok(x1.get("/admin").status_code == 200 and x2.get("/admin").status_code == 302, "password change logs out other sessions only")
y = A.app.test_client(); A._rl.clear()
for _ in range(5):
    r, h = get(y, "/admin/login"); y.post("/admin/login", data=dict(csrf_token=tok(h), username="khaled.care", password="wrong"))
r, h = get(y, "/admin/login"); ok(y.post("/admin/login", data=dict(csrf_token=tok(h), username="khaled.care", password="anotherpass12")).status_code == 429, "account locked after 5 wrong passwords")
r, h = get(y, "/admin/login"); ok(y.post("/admin/login", data=dict(csrf_token=tok(h), username="admin", password="adminpass123")).status_code == 302, "other accounts from the same IP still log in")
r, h = get(c, "/en/ticket"); c.post("/en/ticket", data=dict(csrf_token=tok(h), req_type="feedback", topic="general", message="anonymous english note", anonymous="1", consent="1"))
r, h = get(c, "/en/ticket/done"); aref = re.findall(r'<span class="ref">([^<]+)</span>', h)[0]
ok(sqlite3.connect(D + "/tickets.db").execute("SELECT lang, kiosk_id FROM tickets WHERE ref=?", (aref,)).fetchone() == ("", None), "anonymous: language not stored")
r, h = get(a, "/admin/t/" + aref); ok("لغة التقديم" not in h and "الوقت مخفي" in h, "anonymous: no language, date only")
A.backup_daily(); ok(any(f_.startswith("tickets-") for f_ in os.listdir(D + "/backups")), "daily backup file written")

# ---------------- ticket list layout
con = sqlite3.connect(D + "/tickets.db")
r, h = get(a, "/admin"); ok('aria-current="page">المفتوحة' in h and "تحتاج إجراء" in h and "تصفية متقدمة" in h, "list: tabs, open by default, advanced filters folded")
closed_ref = con.execute("SELECT ref FROM tickets WHERE status='closed' LIMIT 1").fetchone()[0]
ok('href="/admin/t/%s"' % closed_ref not in h, "closed tickets not in the default (open) view")
r, h = get(a, "/admin?status=all"); ok('href="/admin/t/%s"' % closed_ref in h, "all tab includes closed")
lr = con.execute("SELECT ref FROM tickets WHERE status IN ('new','escalated','in_progress') ORDER BY id LIMIT 1").fetchone()[0]
con.execute("UPDATE tickets SET due_at='2026-01-02T00:00:00Z' WHERE ref=?", (lr,)); con.commit()
r, h = get(a, "/admin"); first = re.search(r'class="tl-row[^"]*" href="/admin/t/([^"]+)"', h).group(1)
ok(first == lr, "late ticket listed first (%s)" % first)
r, h = get(a, "/admin?status=act"); ok(r.status_code == 200, "needs-action tab")
r, h = get(a, "/admin?late=1&q=" + lr); ok(lr in h, "search inside late tab")

# ---------------- staff speed-ups
r, h = get(a, "/admin"); ok('class="nb"' in h, "menu shows a needs-action counter")
r, h = get(a, "/admin/templates"); ok("استلام الطلب وجارٍ العمل عليه" in h and "{الاسم}" in h, "seeded ready-made replies")
# a section adds its own reply; another section does not see it
leaves_staff = A.app.test_client(); r, h = get(leaves_staff, "/admin/login")
r, h = get(a, "/admin/users"); a.post("/admin/users", data=dict(csrf_token=tok(h), display_name="ليلى", username="layla.lv", role="staff", dept_id=str(leaves), password="laylapass12"))
leaves_staff.post("/admin/login", data=dict(csrf_token=tok(get(leaves_staff, "/admin/login")[1]), username="layla.lv", password="laylapass12"))
r, h = get(leaves_staff, "/admin/templates")
leaves_staff.post("/admin/templates", data=dict(csrf_token=tok(h), title="رصيد الإجازة", body="السلام عليكم {الاسم}، رصيدك هو ..."))
tid_ = sqlite3.connect(D + "/tickets.db").execute("SELECT id, dept_id FROM reply_templates WHERE title='رصيد الإجازة'").fetchone()
ok(tid_ and tid_[1] == leaves, "staff reply saved for their own section")
A._rl.clear(); care2 = A.app.test_client(); r, h = get(care2, "/admin/login"); care2.post("/admin/login", data=dict(csrf_token=tok(h), username="khaled.care", password="anotherpass12"))
r, h = get(care2, "/admin/templates"); ok("رصيد الإجازة" not in h, "other sections don't see it")
ok(care2.post("/admin/templates", data=dict(csrf_token=tok(h), id=str(tid_[0]), title="x", body="xxxxxx")).status_code == 404, "and cannot edit it")
# ticket page: template picker, next ticket button
con = sqlite3.connect(D + "/tickets.db")
open_refs = [r_[0] for r_ in con.execute("SELECT ref FROM tickets WHERE status IN ('new','escalated','in_progress') AND anonymous=0 ORDER BY id")]
r, h = get(a, "/admin/t/" + open_refs[0])
ok('id="tpl"' in h and "استلام الطلب" in h and "data-draft=" in h, "reply tab has ready-made replies and draft saving")
nx = re.search(r'التالية: <b dir="ltr">([^<]+)</b>', h); ok(nx and nx.group(1) != open_refs[0], "next-ticket button points elsewhere (%s)" % (nx.group(1) if nx else None))
h = a.post("/admin/t/" + open_refs[0], data=dict(csrf_token=tok(h), action="resolve", reply="تم", tpl_used=str(tid_[0])), follow_redirects=True).get_data(as_text=True)
ok("انتقل للتذكرة التالية" in h, "after sending: offer the next ticket")
ok(con.execute("SELECT uses FROM reply_templates WHERE id=?", (tid_[0],)).fetchone()[0] == 1, "template use counted")
print("ALL OK")
