# -*- coding: utf-8 -*-
"""Builds the bilingual static pages: Arabic at repo root, English under en/.
Run from repo root: python3 tools/build_static.py"""
import json, html, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
import links_data, faq_plain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "https://shaqra-transition-campaign-4d8709-84-8-127-235.sslip.io"
MAIL = "R3-shqra-hrcs@moh.gov.sa"
e = html.escape

WAVE = '<svg class="wave" viewBox="0 0 1440 90" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path d="M0 40C240 -10 480 10 720 40S1200 85 1440 30V90H0z" fill="#8fc3ec" opacity=".55"/><path d="M0 55C260 10 520 30 760 58S1210 88 1440 50V90H0z" fill="#2b7fc4"/><path d="M0 70C280 40 560 55 800 72S1230 92 1440 70V90H0z" fill="#fff"/></svg>'
IC = {
 "chat": '<path d="M4 5h16v11H9l-5 4z"/>',
 "track": '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5"/>',
 "faq": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01"/>',
  "path": '<circle cx="5" cy="18" r="2"/><circle cx="19" cy="6" r="2"/><path d="M7 18h6a4 4 0 0 0 0-8h-2a4 4 0 0 1 0-8h6" transform="translate(0 2)"/>',
 "link": '<path d="M10 14a4 4 0 0 0 5.6 0l3-3a4 4 0 0 0-5.6-5.6l-1 1M14 10a4 4 0 0 0-5.6 0l-3 3a4 4 0 0 0 5.6 5.6l1-1"/>',
}
def icon(n):
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{IC[n]}</svg>'

# ---------------------------------------------------------------- strings
S = {
 "ar": dict(
  lang="ar", dir="rtl", sitename="نطاق شقراء الصحي", sub="تجمع الرياض الصحي الثالث", logoalt="شعار الصحة القابضة – Health Holding",
  switch_label="English", switch_title="Switch to English", switch_lang="en",
  nav=["الرئيسية", "مسار الموظف", "طلب جديد", "الأسئلة", "الروابط", "التواصل"], navaria="التنقل الرئيسي", skip="تخطَّ إلى المحتوى",
  fcare="قسم العناية بالموظفين", fext="التحويلة 671", ext="تحويلة 671",
  fnote="دليل توعوي لموظفي نطاق شقراء الصحي. المرجع الرسمي هو الصحة القابضة والجهات المختصة.",
  ticket_path="/ticket", status_path="/status", prefix="",
 ),
 "en": dict(
  lang="en", dir="ltr", sitename="Shaqra Health Cluster", sub="Riyadh Third Health Cluster", logoalt="Health Holding logo",
  switch_label="العربية", switch_title="التبديل إلى العربية", switch_lang="ar",
  nav=["Home", "My journey", "New request", "FAQ", "Links", "Contact"], navaria="Main navigation", skip="Skip to content",
  fcare="Employee Care Department", fext="Ext. 671", ext="Ext. 671",
  fnote="An awareness guide for Shaqra Health Cluster staff. The official references are Health Holding and the responsible authorities.",
  ticket_path="/en/ticket", status_path="/en/status", prefix="en/",
 ),
}

def page(lang, name, title, desc, body, scripts=(), cur=None, extra_head=""):
    t = S[lang]
    up = "../" if lang == "en" else ""
    # language switch target
    if lang == "ar":
        sw = "en/" if name == "index" else f"en/{name}.html"
    else:
        sw = "../" if name == "index" else f"../{name}.html"
    navs = [("index", "./"), ("journey", "journey.html"), ("ticket", APP + t["ticket_path"]), ("faq", "faq.html"), ("links", "links.html"), ("contact", "contact.html")]
    nav_html = "".join(
        f'<a href="{href}"{" class=cur aria-current=page" if key == cur else ""}>{e(lbl)}</a>'
        for (key, href), lbl in zip(navs, t["nav"]))
    sc = "".join(f'<script src="{up}assets/{s}" defer></script>' for s in scripts)
    return f'''<!DOCTYPE html>
<html lang="{t["lang"]}" dir="{t["dir"]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} | {e(t["sitename"])}</title>
<meta name="description" content="{e(desc)}">
<link rel="alternate" hreflang="{t["switch_lang"]}" href="{sw}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{up}assets/site.css">
<script src="{up}assets/site.js"></script>
{extra_head}</head>
<body>
<a class="skip" href="#main">{e(t["skip"])}</a>
<header class="top">
  <div class="wrap top-row">
    <a class="brand" href="./" aria-label="{e(t["sitename"])} – {e(t["sub"])}">
      <img src="{up}assets/health-holding-logo-color.svg" alt="{e(t["logoalt"])}">
      <span class="sep" aria-hidden="true"></span>
      <span class="name">{e(t["sitename"])}<small>{e(t["sub"])}</small></span>
    </a>
    <a class="lang" href="{sw}" hreflang="{t["switch_lang"]}" lang="{t["switch_lang"]}" title="{e(t["switch_title"])}">{e(t["switch_label"])}</a>
  </div>
  <div class="wrap"><nav class="main" aria-label="{e(t["navaria"])}">{nav_html}</nav></div>
</header>
<main id="main">
{body}
</main>
<footer>
  <div class="wrap">
    <b>{e(t["sitename"])} – {e(t["sub"])}</b>
    <p style="margin:6px 0 0">{e(t["fnote"])}</p>
    <div class="fc"><b>{e(t["fcare"])}:</b> <a href="mailto:{MAIL}" class="ltr">{MAIL}</a> · {e(t["fext"])}</div>
  </div>
</footer>
{sc}
</body>
</html>
'''

def write(lang, name, content):
    path = os.path.join(ROOT, "en" if lang == "en" else "", f"{name}.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(content)

def ticket(lang, q=""):
    return APP + S[lang]["ticket_path"] + q

# ---------------------------------------------------------------- HOME
H = {
 "ar": dict(
  title="دليل الموظف: الانتقال إلى الصحة القابضة",
  desc="دليل موظفي نطاق شقراء الصحي: ماذا يحدث، ما المطلوب منك، وكيف تتواصل مع قسم العناية بالموظفين.",
  tag="دليل الموظف",
  h1="الانتقال إلى الصحة القابضة: كل ما يهمّك هنا",
  sub="موظفو مستشفيات شقراء وثادق ومرات ومراكزها يستعدون للانتقال إلى شركة الصحة القابضة.",
  btns=[("primary", "path", "journey.html", "مسار الموظف", "حقوقك وما عليك، مرحلة بمرحلة"),
        ("", "chat", ticket("ar"), "عندي سؤال أو طلب", "افتح تذكرة لقسم العناية بالموظفين"),
        ("", "track", APP + "/status", "متابعة طلبي", "برقم التذكرة وبريدك الوزاري"),
        ("", "faq", "faq.html", "الأسئلة الشائعة", "إجابات رسمية جاهزة"),
        ("", "link", "links.html", "الروابط الرسمية", "قوى، التأمينات، الموارد البشرية وغيرها")],
  req_h="ما المطلوب منك الآن؟",
  steps=[("حدّث بياناتك في «موارد»", "يُبنى طلب الانتقال على بياناتك المسجلة فيها."),
         ("راقب بريدك الوزاري", "يصل طلب الانتقال لمن اجتاز معايير المفاضلة وحالته «نشط» في «موارد»."),
         ("راجع عقدك في «قوى»", "ستصلك رسالة من «قوى»، ثم: قوى أفراد ← الخدمات ← العقود الوظيفية.")],
  src_note="التفاصيل الكاملة في صفحة الأسئلة الشائعة.",
  contact_h="للتواصل المباشر",
  contact_who="قسم العناية بالموظفين",
  src="المصدر: الأسئلة الشائعة للصحة القابضة (health.sa).",
 ),
 "en": dict(
  title="Employee guide: moving to Health Holding",
  desc="Guide for Shaqra Health Cluster staff: what is happening, what you need to do, and how to reach the Employee Care Department.",
  tag="Employee guide",
  h1="Moving to Health Holding: everything you need, here",
  sub="Staff of Shaqra, Thadiq and Marat hospitals and their health centers are getting ready to move to Health Holding Company.",
  btns=[("primary", "path", "journey.html", "My journey", "Your rights and what to do, stage by stage"),
        ("", "chat", ticket("en"), "I have a question or request", "Open a ticket to the Employee Care team"),
        ("", "track", APP + "/en/status", "Track my request", "Use your ticket number and ministry email"),
        ("", "faq", "faq.html", "Frequently asked questions", "Ready answers from official sources"),
        ("", "link", "links.html", "Official links", "Qiwa, GOSI, HRSD and more")],
  req_h="What do I need to do now?",
  steps=[("Update your data in Mawared", "Your transfer request is built from the data saved there."),
         ("Watch your ministry email", "The transfer request goes to staff who passed the selection criteria and whose status is “Active” in Mawared."),
         ("Review your contract in Qiwa", "You will get a message from Qiwa. Then go to: Qiwa Individuals → Services → Employment contracts.")],
  src_note="See the FAQ page for full details.",
  contact_h="Contact us directly",
  contact_who="Employee Care Department",
  src="Source: Health Holding FAQ (health.sa).",
 ),
}

def home(lang):
    h = H[lang]; t = S[lang]
    bigs = "".join(
        f'<a class="big {cls}" href="{href}">{icon(ic)}<b>{e(tt)}</b><span>{e(sb)}</span></a>'
        for cls, ic, href, tt, sb in h["btns"])
    steps = "".join(f"<li><b>{e(a)}</b>{e(b)}</li>" for a, b in h["steps"])
    body = f'''<section class="hero">
  <div class="wrap">
    <span class="tag">{e(h["tag"])}</span>
    <h1>{e(h["h1"])}</h1>
    <p class="sub">{e(h["sub"])}</p>
  </div>
</section>
<section class="main-actions"><div class="wrap"><div class="bigbtns">{bigs}</div></div></section>
<section class="s"><div class="wrap">
  <h2 class="u">{e(h["req_h"])}</h2>
  <ol class="steps row">{steps}</ol>
  <p class="srcline">{e(h["src_note"])}</p>
</div></section>
<section class="s"><div class="wrap">
  <div class="cstrip">
    <div><b>{e(h["contact_h"])}</b><br>{e(h["contact_who"])}</div>
    <div class="ways"><a href="mailto:{MAIL}" class="ltr">{MAIL}</a><span>{e(t["ext"])}</span></div>
  </div>
  <p class="srcline">{e(h["src"])}</p>
</div></section>'''
    write(lang, "index", page(lang, "index", h["title"], h["desc"], body, cur="index"))

# ---------------------------------------------------------------- FAQ
FQ = {
 "ar": dict(title="الأسئلة الشائعة", desc="إجابات من المصادر الرسمية عن الانتقال إلى الصحة القابضة.", h1="الأسئلة الشائعة", p="إجابات من المصادر الرسمية فقط. ابحث بكلمة، أو اختر موضوعًا.",
  search="ابحث في الأسئلة…", searchlbl="ابحث", cats_all="الكل", journey_p="تريد معرفة حقوقك وما عليك بحسب وضعك؟", journey_a="افتح مسار الموظف",
  banner="",
  count="{n} سؤال", none_h="لم نجد إجابة لسؤالك", none_p="أرسل سؤالك لقسم العناية بالموظفين.", ask="اسأل قسم العناية بالموظفين", source="المصدر:", askq="لم تجد سؤالك؟",
  unofficial=""),
 "en": dict(title="Frequently asked questions", desc="Answers from official sources about the move to Health Holding.", h1="Frequently asked questions", p="Answers from official sources only. Search by a word, or pick a topic.",
  search="Search the questions…", searchlbl="Search", cats_all="All", journey_p="Want to know your rights and what you must do, based on your situation?", journey_a="Open My journey",
  banner="",
  count="{n} questions", none_h="We did not find an answer to your question", none_p="Send your question to the Employee Care Department.", ask="Ask the Employee Care Department", source="Source:", askq="Can't find your question?",
  unofficial=""),
}
CAT_EN = {"about": "Transition & Health Holding", "salary": "Salaries & allowances", "contract": "Contract & job title",
          "qiwa": "Mawared & Qiwa platforms", "decline": "If you do not want to transfer", "retire": "Retirement & service merge",
          "benefits": "Rewards, benefits & development", "leave": "Leave", "legal": "General information from regulations"}
SRC_EN = {"health.sa": "Health Holding – FAQ", "hrsd.gov.sa": "Ministry of Human Resources and Social Development (HRSD)",
          "gosi.gov.sa": "GOSI – FAQ on amending the benefit-exchange system"}
SRC_AR_SHORT = {}

def faq(lang):
    f = FQ[lang]; t = S[lang]
    meta = json.load(open(os.path.join(ROOT, "tools", "faq_sources.json"), encoding="utf-8"))
    items = faq_plain.ITEMS
    chips = [f'<button type="button" class="chip" data-cat="" aria-pressed="true">{e(f["cats_all"])} <small>{len(items)}</small></button>']
    total = 0; items_html = []
    for key, car, cen in faq_plain.CATS:
        rows = [x for x in items if x[1] == key]
        if not rows: continue
        chips.append(f'<button type="button" class="chip" data-cat="{key}" aria-pressed="false">{e(car if lang == "ar" else cen)} <small>{len(rows)}</small></button>')
        for iid, _c, qa, aa, qe, ae in rows:
            total += 1
            q, a = (qa, aa) if lang == "ar" else (qe, ae)
            m = meta[str(iid)]
            host = re.sub(r"^https?://(www\.)?", "", m["src"]).split("/")[0]
            srcname = m["srcname"] if lang == "ar" else SRC_EN.get(host, host)
            paras = "".join(f"<p>{e(p)}</p>" for p in a.split("\n") if p.strip())
            items_html.append(
                f'<details class="fq" id="q{iid}" data-cat="{key}"><summary><span class="qt"><span class="qtext">{e(q)}</span></span></summary>'
                f'<div class="body">{paras}<p class="src">{e(f["source"])} <a href="{e(m["src"])}" rel="noopener" target="_blank">{e(srcname)}</a></p></div></details>')
    askbase = ticket(lang, "?type=inquiry&q=")
    banner = f'<div class="note warnbox" style="margin-top:0;margin-bottom:16px">{e(f["banner"])}</div>' if f["banner"] else ""
    body = f'''<section class="page-head"><div class="wrap"><h1>{e(f["h1"])}</h1><p>{e(f["p"])}</p></div></section>
<section class="s"><div class="wrap">
  {banner}
  <p class="jhint"><a href="journey.html">{e(f["journey_a"])}</a> · {e(f["journey_p"])}</p>
  <div class="toolbar">
    <div class="searchbar"><input type="search" id="q" placeholder="{e(f["search"])}" aria-label="{e(f["searchlbl"])}" autocomplete="off" enterkeyhint="search"></div>
    <div class="fgroup" id="cats" role="group" aria-label="{e(f["cats_all"])}">{"".join(chips)}</div>
  </div>
  <p class="count" id="cnt" aria-live="polite" data-tpl="{e(f["count"])}">{e(f["count"].format(n=total))}</p>
  <div id="list">{"".join(items_html)}</div>
  <div class="empty" id="empty"><h2 style="margin-bottom:6px">{e(f["none_h"])}</h2><p>{e(f["none_p"])}</p>
    <a class="btn solid" id="ask-empty" href="{askbase}" data-base="{askbase}">{e(f["ask"])}</a></div>
  <p class="faq-note">{e(f["askq"])} <a id="ask-link" href="{askbase}" data-base="{askbase}">{e(f["ask"])}</a></p>
</div></section>'''
    write(lang, "faq", page(lang, "faq", f["title"], f["desc"], body, scripts=["common.js","faq.js"], cur="faq"))

# ---------------------------------------------------------------- LINKS
LK = {
 "ar": dict(title="الروابط الرسمية", desc="الروابط الرسمية المهمة للموظف مرتبة بالموضوع مع بحث وفلاتر.", h1="الروابط الرسمية", p="كل الروابط تفتح مواقع الجهات الرسمية. ابحث، أو افتح الموضوع الذي تريده.",
  search="ابحث في الروابط…", searchlbl="ابحث", org_lbl="الجهة:", org_all="كل الجهات",
  eng_lbl="الصفحة بالإنجليزية فقط", expand="فتح الكل", collapse="طي الكل", count="{n} رابط", none="لا توجد روابط مطابقة. جرّب كلمة أخرى أو أزل الفلاتر.", reset="إعادة ضبط الفلاتر",
  en_page="النسخة الإنجليزية", en_only="الصفحة بالإنجليزية", ar_only="بالعربية فقط", opens="يفتح موقعًا رسميًا خارجيًا",
 ),
 "en": dict(title="Official links", desc="Official links that matter to staff, grouped by topic, with search and filters.", h1="Official links", p="Every link opens an official website. Search, or open the topic you need.",
  search="Search the links…", searchlbl="Search", org_lbl="Source:", org_all="All sources",
  eng_lbl="Page has an English version", expand="Open all", collapse="Close all", count="{n} links", none="No links match. Try another word or clear the filters.", reset="Clear filters",
  en_page="English version", en_only="English page", ar_only="Arabic only", opens="Opens an official external website",
 ),
}
ORG_ORDER = ["hhc", "r3", "moh", "hrsd", "gosi", "qiwa", "gov"]

def links(lang):
    L = LK[lang]; t = S[lang]
    data = links_data.load()
    cats = links_data.CATS
    orgs_used = [o for o in ORG_ORDER if any(x["org"] == o for x in data)]
    oidx = 0 if lang == "ar" else 1
    org_opts = f'<option value="">{e(L["org_all"])}</option>' + "".join(f'<option value="{o}">{e(links_data.ORGS[o][oidx])}</option>' for o in orgs_used)
    sections = []
    for key, car, cen, sar, sen in cats:
        rows = [x for x in data if x["cat"] == key]
        rh = []
        for x in rows:
            ttl = x[f"{lang}_title"]; desc = x[f"{lang}_desc"]
            if lang == "ar":
                main = x["ar_url"] or x["en_url"]
                lang_badge = f'<span class="aud lang">{e(L["en_only"])}</span>' if x["ar_url"] is None else ""
                alt = f' <a class="alt" href="{e(x["en_url"])}" rel="noopener" target="_blank" hreflang="en">{e(L["en_page"])}</a>' if (x["ar_url"] and x["en_url"] and x["en_url"] != x["ar_url"]) else ""
            else:
                main = x["en_url"] or x["ar_url"]
                lang_badge = "" if x["en_url"] else f'<span class="aud lang">{e(L["ar_only"])}</span>'
                alt = ""
            has_en = "1" if x["en_url"] else "0"
            org = links_data.ORGS[x["org"]][oidx]
            rh.append(
                f'<div class="lrow" data-org="{x["org"]}" data-en="{has_en}">'
                f'<a class="t" href="{e(main)}" rel="noopener" target="_blank">{e(ttl)}</a>'
                f'<p>{e(desc)}</p>'
                f'<div class="meta">{lang_badge}<span>{e(org)}</span>{alt}</div></div>')
        extra = ""
        sections.append(
            f'<details class="lcat" data-cat="{key}"><summary><span>{e(car if lang=="ar" else cen)}<span class="cat-count">{len(rows)}</span></span></summary>'
            f'<div class="body"><p class="cat-sub">{e(sar if lang=="ar" else sen)}</p>{"".join(rh)}{extra}</div></details>')
    askm = f'mailto:{MAIL}'
    body = f'''<section class="page-head"><div class="wrap"><h1>{e(L["h1"])}</h1><p>{e(L["p"])}</p></div></section>
<section class="s"><div class="wrap">
  <div class="toolbar">
    <div class="searchbar"><input type="search" id="q" placeholder="{e(L["search"])}" aria-label="{e(L["searchlbl"])}" autocomplete="off" enterkeyhint="search"></div>
    <div class="fgroup"><label for="org" class="lbl">{e(L["org_lbl"])}</label><select id="org">{org_opts}</select>
      <label class="tcheck"><input type="checkbox" id="en-only"> {e(L["eng_lbl"])}</label>
      <button type="button" class="chip" id="reset">{e(L["reset"])}</button></div>
  </div>
  <div class="fgroup" style="justify-content:space-between;margin-bottom:8px"><p class="count" id="cnt" aria-live="polite" data-tpl="{e(L["count"])}" style="margin:0">{e(L["count"].format(n=len(data)))}</p>
    <span><button type="button" class="chip" id="expand">{e(L["expand"])}</button> <button type="button" class="chip" id="collapse">{e(L["collapse"])}</button></span></div>
  <div id="list">{"".join(sections)}</div>
  <div class="empty" id="empty">{e(L["none"])}</div>
</div></section>'''
    write(lang, "links", page(lang, "links", L["title"], L["desc"], body, scripts=["common.js","links.js"], cur="links"))

# ---------------------------------------------------------------- CONTACT
C = {
 "ar": dict(title="التواصل مع قسم العناية بالموظفين", desc="طرق التواصل مع قسم العناية بالموظفين: تذكرة، بريد، هاتف.", h1="كيف أتواصل مع قسم العناية بالموظفين؟",
  p="ثلاث طرق. نوصي بفتح تذكرة لأنها تعطيك رقمًا لمتابعة طلبك.",
  ch=[("١. تذكرة إلكترونية (الأفضل)", "عبّئ النموذج في ثلاث خطوات واستلم رقمًا لمتابعة طلبك.", "فتح تذكرة", ticket("ar")),
      ("٢. البريد الإلكتروني", "أرسل من بريدك الوزاري. اذكر اسمك ورقمك الوظيفي وجوالك والمنشأة ونوع الطلب.", "كتابة بريد", "mailto:" + MAIL),
      ("٣. الهاتف", "اتصل بقسم العناية بالموظفين على التحويلة 671. للأمور العاجلة.", "", "")],
  copy="نسخ البريد", copied="تم النسخ", track="متابعة تذكرة",
  after_h="ماذا يحدث بعد الإرسال؟",
  after=[("رقم التذكرة", "يظهر لك مباشرة بعد الإرسال. احتفظ به لمتابعة طلبك."),
         ("مراجعة القسم", "تصل التذكرة إلى العناية بالموظفين أو القسم المختص بموضوعها، وقد يتواصل معك على بريدك الوزاري أو جوالك."),
         ("حالة الطلب", "تتغير بين: جديدة، محالة إلى القسم المختص، قيد المعالجة، مغلقة."),
         ("الرد", "يظهر لك في صفحة المتابعة برقم التذكرة وبريدك الوزاري، أو برمز المتابعة إن أرسلت دون الإفصاح عن هويتك.")],
  noreply="للأمور العاجلة اتصل بقسم العناية بالموظفين على التحويلة 671.",
  types_h="أنواع الطلبات",
  types=[("استفسار أو طلب", "سؤال عن إجراء أو حالتك الوظيفية، أو طلب بيان أو معلومة. بياناتك مطلوبة لنرد عليك. جرّب أولًا الأسئلة الشائعة."),
         ("شكوى أو اقتراح أو ملاحظة", "ملاحظة على إجراء أو تعامل، أو فكرة للتحسين. بياناتك اختيارية: يمكنك الإرسال دون الإفصاح عن هويتك ومتابعة الرد برمز سري.")],
  need_h="ما الذي تحتاجه لفتح تذكرة؟",
  need="للاستفسارات والطلبات: بريدك الوزاري المنتهي بـ moh.gov.sa، ورقم جوالك (05XXXXXXXX)، ورقمك الوظيفي، لنتمكن من التواصل معك. يمكنك أيضًا إرفاق حتى 3 صور.",
  priv="الخصوصية: تُستخدم بيانات التذكرة للتواصل معك بخصوص طلبك فقط، ويطّلع عليها القسم المختص بطلبك. لا تُرسل كلمات مرور أو بيانات بنكية أو أرقام هوية.",
  faq_link="الأسئلة الشائعة"),
 "en": dict(title="Contact the Employee Care Department", desc="How to contact the Employee Care Department: ticket, email, phone.", h1="How do I contact the Employee Care Department?",
  p="Three ways. We recommend a ticket because it gives you a number to track your request.",
  ch=[("1. Online ticket (best)", "Fill in the form in three steps and get a number to track your request.", "Open a ticket", ticket("en")),
      ("2. Email", "Send from your ministry email. Include your name, employee number, mobile, facility and request type.", "Write an email", "mailto:" + MAIL),
      ("3. Phone", "Call the Employee Care Department on extension 671. Best for urgent matters.", "", "")],
  copy="Copy email", copied="Copied", track="Track a ticket",
  after_h="What happens after you submit?",
  after=[("Ticket number", "Shown right after you submit. Keep it to track your request."),
         ("Review", "The ticket goes to Employee Care or the section responsible for its topic. They may contact you on your ministry email or mobile."),
         ("Status", "It changes between: New, Referred to the responsible section, In progress, Closed."),
         ("Reply", "It appears on the Track page with your ticket number and ministry email, or your follow-up code if you sent it without revealing who you are.")],
  noreply="For urgent matters, call the Employee Care Department on extension 671.",
  types_h="Request types",
  types=[("Question or request", "A question about a procedure or your job status, or a request for a document or information. Your details are needed so we can reply. Try the FAQ first."),
         ("Complaint, suggestion or feedback", "A comment on a procedure or treatment, or an idea to improve things. Your details are optional: you can send it without revealing who you are and follow the reply with a secret code.")],
  need_h="What you need to open a ticket",
  need="For questions and requests: your ministry email ending in moh.gov.sa, your mobile number (05XXXXXXXX) and your employee number, so the team can reach you. You can also attach up to 3 photos.",
  priv="Privacy: ticket data is used only to contact you about your request, and is seen by the section responsible for it. Do not send passwords, bank details or ID numbers.",
  faq_link="FAQ"),
}

def contact(lang):
    c = C[lang]; t = S[lang]
    chs = []
    for i, (h, p, bt, href) in enumerate(c["ch"]):
        if i == 0:
            act = f'<a class="btn solid block" href="{href}">{e(bt)}</a><a class="btn block sm" href="{APP}{t["status_path"]}">{e(c["track"])}</a>'
            ex = ""
        elif i == 1:
            act = f'<a class="btn solid block" href="{href}">{e(bt)}</a><button type="button" class="btn block sm" id="copy" data-mail="{MAIL}">{e(c["copy"])}</button><span id="copied" role="status">{e(c["copied"])}</span>'
            ex = f'<p><b class="ltr">{MAIL}</b></p>'
        else:
            act = ""
            ex = f'<p style="font-size:24px;font-weight:800;color:var(--navy)">{e(t["ext"])}</p>'
        chs.append(f'<div class="chan"><h3>{e(h)}</h3>{ex}<p>{e(p)}</p>{act}</div>')
    after = "".join(f"<li><b>{e(a)}</b>{e(b)}</li>" for a, b in c["after"])
    types = "".join(f"<li><b>{e(a)}</b> {e(b)}</li>" for a, b in c["types"])
    body = f'''<section class="page-head"><div class="wrap"><h1>{e(c["h1"])}</h1><p>{e(c["p"])}</p></div></section>
<section class="s"><div class="wrap">
  <div class="channels">{"".join(chs)}</div>
  <div class="note">{e(c["need_h"])}: {e(c["need"])}</div>
</div></section>
<section class="s alt"><div class="wrap">
  <h2 class="u">{e(c["after_h"])}</h2>
  <ol class="steps" style="margin-bottom:12px">{after}</ol>
  <div class="note warnbox" style="margin-top:0">{e(c["noreply"])}</div>
</div></section>
<section class="s"><div class="wrap">
  <h2 class="u">{e(c["types_h"])}</h2>
  <ul>{types}</ul>
  <div class="note"><a href="faq.html">{e(c["faq_link"])}</a> · {e(c["priv"])}</div>
</div></section>'''
    write(lang, "contact", page(lang, "contact", c["title"], c["desc"], body, scripts=["contact.js"], cur="contact"))

# ---------------------------------------------------------------- JOURNEY
import journey_data as JD
J = {
 "ar": dict(title="مسار الموظف: حقوقك وما عليك", desc="مسار الموظف في الانتقال إلى الصحة القابضة: حقوقك وما عليك في كل مرحلة.",
  h1="مسار الموظف", p="من قبل الانتقال إلى ما بعده: ما الذي تحصل عليه، وما الذي عليك فعله.",
  right="حقّك", todo="عليك", src="المصدر:", faq="التفاصيل في الأسئلة الشائعة", unk_ask="اسأل قسم العناية بالموظفين",
  empty="لا بنود في هذه المرحلة لوضعك المختار. راجع قسم العناية بالموظفين.",
  rule="هذا الدليل للتوضيح فقط، ولا يحلّ محل العقد المرسل إليك.",
  jump="المراحل", note_lbl="ملاحظة", ns_lbl="لغير السعوديين:"),
 "en": dict(title="My journey: your rights and what to do", desc="The employee journey for the move to Health Holding: your rights and what you must do at each stage.",
  h1="My journey", p="From before the transfer to after it: what you get, and what you need to do.",
  right="Your right", todo="You do", src="Source:", faq="More in the FAQ", unk_ask="Ask the Employee Care Department",
  empty="No items in this stage for your selection. Ask the Employee Care Department.",
  rule="This guide is for explanation only and does not replace the contract sent to you.",
  jump="Stages", note_lbl="Note", ns_lbl="For non-Saudis:"),
}

def journey(lang):
    j = J[lang]; i = 0 if lang == "ar" else 1; sel = JD.SEL[lang]; un = JD.UNKNOWN[lang]
    def opts(lst): return "".join(f'<option value="{e(v)}">{e(l)}</option>' for v, l in lst)
    stages = []; jump = []; n_items = 0
    for st in JD.STAGES:
        its = []
        for it in st["items"]:
            n_items += 1
            srcs = " · ".join(f'<a href="{e(JD.SRC[k][2])}" rel="noopener" target="_blank">{e(JD.SRC[k][i])}</a>' for k in it["src"])
            fq = f'<a class="fqref" href="faq.html#q{it["faq"][0]}">{e(j["faq"])}</a>' if it["faq"] else ""
            ns = ""
            if it.get("ns"):
                ns = f'<p class="nsn"><b>{e(j["ns_lbl"])}</b> {e(it["ns"][i])} <a href="{e(JD.SRC[it["ns"][2]][2])}" rel="noopener" target="_blank">{e(JD.SRC[it["ns"][2]][i])}</a></p>'
            parts = ([f'{e(j["src"])} {srcs}'] if srcs else []) + ([fq] if fq else [])
            cite = f'<p class="cite">{" · ".join(parts)}</p>' if parts else ""
            kind = j["right"] if it["k"] == "r" else j["todo"]
            its.append(f'<li class="ji {it["k"]}" data-emp="{it["emp"]}" data-svc="{it["svc"]}"><span class="kind">{e(kind)}</span>'
                       f'<p>{e(it["ar" if lang == "ar" else "en"])}</p>{ns}{cite}</li>')
        sid = st["id"]
        stages.append(f'<section class="stage" id="{sid}" data-stage="{sid}"><h2><span class="num"></span>{e(st["t"][i])}</h2><p class="sd">{e(st["d"][i])}</p>'
                      f'<ul class="jl">{"".join(its)}</ul><p class="empty-st" hidden>{e(j["empty"])}</p></section>')
        jump.append(f'<a href="#{sid}">{e(st["t"][i])}</a>')
    unk = "".join(f"<li>{e(x)}</li>" for x in un["items"])
    selhtml = (f'<div class="jsel" id="jsel"><h2>{e(sel["h"])}</h2><p>{e(sel["p"])}</p>'
               f'<div class="jrow"><label for="s-emp">{e(sel["emp_l"])}</label><select id="s-emp">{opts(sel["emp"])}</select></div>'
               f'<div class="jrow"><label for="s-svc">{e(sel["svc_l"])}</label><select id="s-svc">{opts(sel["svc"])}</select></div>'
               f'<div class="jrow"><button type="button" class="chip" id="s-reset">{e(sel["reset"])}</button>'
               f'<span id="s-count" aria-live="polite" data-tpl="{e(sel["shown"])}"></span></div>'
               f'<p class="srcline">{e(sel["how"])}</p></div>')
    body = f'''<section class="page-head"><div class="wrap"><h1>{e(j["h1"])}</h1><p>{e(j["p"])}</p></div></section>
<section class="s"><div class="wrap">
  {selhtml}
  <nav class="jump" aria-label="{e(j["jump"])}">{"".join(jump)}</nav>
  <div id="journey">{"".join(stages)}</div>
  <div class="unk" id="unknowns"><h2>{e(un["h"])}</h2><p>{e(un["p"])}</p>{"<ul>" + unk + "</ul>" if unk else ""}
    <p><a class="btn solid" href="mailto:{MAIL}">{e(j["unk_ask"])}</a> <span class="ltr">{MAIL}</span> · {e(t_ext(lang))}</p></div>
  <div class="note warnbox">{e(j["rule"])}</div>
</div></section>'''
    write(lang, "journey", page(lang, "journey", j["title"], j["desc"], body, scripts=["journey.js"], cur="journey"))

def t_ext(lang): return S[lang]["ext"]

if __name__ == "__main__":
    for lg in ("ar", "en"):
        home(lg); journey(lg); faq(lg); links(lg); contact(lg)
    print("built")
