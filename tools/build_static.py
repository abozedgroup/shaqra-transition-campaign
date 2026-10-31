# -*- coding: utf-8 -*-
"""Builds the bilingual static pages: Arabic at repo root, English under en/.
Run from repo root: python3 tools/build_static.py"""
import json, html, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
import links_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "https://shaqra-transition-campaign-4d8709-84-8-127-235.sslip.io"
MAIL = "R3-shqra-hrcs@moh.gov.sa"
VERIFIED = "2026-10-31"
e = html.escape

WAVE = '<svg class="wave" viewBox="0 0 1440 90" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path d="M0 40C240 -10 480 10 720 40S1200 85 1440 30V90H0z" fill="#8fc3ec" opacity=".55"/><path d="M0 55C260 10 520 30 760 58S1210 88 1440 50V90H0z" fill="#2b7fc4"/><path d="M0 70C280 40 560 55 800 72S1230 92 1440 70V90H0z" fill="#fff"/></svg>'
IC = {
 "chat": '<path d="M4 5h16v11H9l-5 4z"/>',
 "track": '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5"/>',
 "faq": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01"/>',
 "link": '<path d="M10 14a4 4 0 0 0 5.6 0l3-3a4 4 0 0 0-5.6-5.6l-1 1M14 10a4 4 0 0 0-5.6 0l-3 3a4 4 0 0 0 5.6 5.6l1-1"/>',
}
def icon(n):
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{IC[n]}</svg>'

# ---------------------------------------------------------------- strings
S = {
 "ar": dict(
  lang="ar", dir="rtl", sitename="نطاق شقراء الصحي", sub="تجمع الرياض الصحي الثالث", logoalt="شعار الصحة القابضة – Health Holding",
  switch_label="English", switch_title="Switch to English", switch_lang="en",
  nav=["الرئيسية", "طلب جديد", "الأسئلة", "الروابط", "التواصل"], navaria="التنقل الرئيسي", skip="تخطَّ إلى المحتوى",
  fcare="قسم العناية بالموظفين", fext="التحويلة 671", ext="تحويلة 671",
  fnote="حملة توعية داخلية لموظفي نطاق شقراء الصحي. هذا الموقع ليس موقعًا حكوميًا رسميًا؛ المرجع الرسمي هو الصحة القابضة والجهات المختصة.",
  verified="تاريخ التحقق من الروابط: ",
  ticket_path="/ticket", status_path="/status", prefix="",
 ),
 "en": dict(
  lang="en", dir="ltr", sitename="Shaqra Health Cluster", sub="Riyadh Third Health Cluster", logoalt="Health Holding logo",
  switch_label="العربية", switch_title="التبديل إلى العربية", switch_lang="ar",
  nav=["Home", "New request", "FAQ", "Links", "Contact"], navaria="Main navigation", skip="Skip to content",
  fcare="Employee Care Department", fext="Ext. 671", ext="Ext. 671",
  fnote="Internal awareness campaign for Shaqra Health Cluster staff. This is not an official government website; the official references are Health Holding and the responsible authorities.",
  verified="Links last verified: ",
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
    navs = [("index", "./"), ("ticket", APP + t["ticket_path"]), ("faq", "faq.html"), ("links", "links.html"), ("contact", "contact.html")]
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
    <div class="fc">{e(t["verified"])}{VERIFIED}</div>
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
  tag="للسعوديين وغير السعوديين",
  h1="الانتقال إلى الصحة القابضة: كل ما يهمّك هنا",
  sub="موظفو مستشفيات شقراء وثادق ومرات ومراكزها يستعدون للانتقال إلى شركة الصحة القابضة.",
  btns=[("primary", "chat", ticket("ar"), "عندي سؤال أو طلب", "افتح تذكرة لقسم العناية بالموظفين"),
        ("", "track", APP + "/status", "متابعة طلبي", "برقم التذكرة وبريدك الوزاري"),
        ("", "faq", "faq.html", "الأسئلة الشائعة", "إجابات رسمية جاهزة"),
        ("", "link", "links.html", "الروابط الرسمية", "قوى، التأمينات، الموارد البشرية وغيرها")],
  req_h="ما المطلوب منك الآن؟",
  steps=[("حدّث بياناتك في «موارد»", "يُبنى طلب الانتقال على بياناتك المسجلة فيها."),
         ("راقب بريدك الوزاري", "يصل طلب الانتقال لمن اجتاز معايير المفاضلة وحالته «نشط» في «موارد»."),
         ("راجع عقدك في «قوى»", "ستصلك رسالة من «قوى»، ثم: قوى أفراد ← الخدمات ← العقود الوظيفية.")],
  src_note="الخطوات من الأسئلة الشائعة الرسمية للصحة القابضة. التفاصيل الكاملة في صفحة الأسئلة.",
  who_h="سعودي أم غير سعودي؟",
  who_p="بعض المعلومات تختلف حسب الجنسية (مثل التأمينات الاجتماعية). لم نجد في المصادر الرسمية صفحة مستقلة لغير السعوديين عن الانتقال؛ فإن لم تجد ما يخصّك اسأل قسم العناية بالموظفين.",
  who_btn="ما الذي يختلف؟",
  contact_h="للتواصل المباشر",
  contact_who="قسم العناية بالموظفين",
  src="المصدر: الأسئلة الشائعة الرسمية للصحة القابضة (health.sa).",
 ),
 "en": dict(
  title="Employee guide: moving to Health Holding",
  desc="Guide for Shaqra Health Cluster staff: what is happening, what you need to do, and how to reach the Employee Care Department.",
  tag="For Saudi and non-Saudi staff",
  h1="Moving to Health Holding: everything you need, here",
  sub="Staff of Shaqra, Thadiq and Marat hospitals and their health centers are getting ready to move to Health Holding Company.",
  btns=[("primary", "chat", ticket("en"), "I have a question or request", "Open a ticket to the Employee Care team"),
        ("", "track", APP + "/en/status", "Track my request", "Use your ticket number and ministry email"),
        ("", "faq", "faq.html", "Frequently asked questions", "Ready answers from official sources"),
        ("", "link", "links.html", "Official links", "Qiwa, GOSI, HRSD and more")],
  req_h="What do I need to do now?",
  steps=[("Update your data in Mawared", "Your transfer request is built from the data saved there."),
         ("Watch your ministry email", "The transfer request goes to staff who passed the selection criteria and whose status is “Active” in Mawared."),
         ("Review your contract in Qiwa", "You will get a message from Qiwa. Then go to: Qiwa Individuals → Services → Employment contracts.")],
  src_note="These steps come from the official Health Holding FAQ. See the FAQ page for details.",
  who_h="Saudi or non-Saudi?",
  who_p="Some information differs by nationality (for example, social insurance). We did not find a separate official page about the transition for non-Saudis. If you cannot find what applies to you, ask the Employee Care Department.",
  who_btn="What is different?",
  contact_h="Contact us directly",
  contact_who="Employee Care Department",
  src="Source: official Health Holding FAQ (health.sa). The FAQ is published in Arabic.",
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
<section class="s alt"><div class="wrap">
  <div class="note" style="margin-top:0"><b>{e(h["who_h"])}</b> {e(h["who_p"])} <a href="links.html#who">{e(h["who_btn"])}</a></div>
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
  search="ابحث في الأسئلة…", searchlbl="ابحث", cats_all="الكل", aud_lbl="أنا:", aud=["الكل", "سعودي", "غير سعودي"],
  banner="الأسئلة الرسمية لا تفرّق بين السعودي وغير السعودي إلا حيث وُضعت علامة. علامة «سعوديون» على بنود المعاشات التقاعدية. إن كنت غير سعودي وسؤالك يتعلق بالانتقال، اسأل قسم العناية بالموظفين.",
  count="{n} سؤال", none_h="لم نجد إجابة لسؤالك", none_p="لا تخمّن. أرسل سؤالك لقسم العناية بالموظفين.", ask="اسأل قسم العناية بالموظفين", source="المصدر:", askq="لم تجد سؤالك؟",
  nonsaudi_note="لا توجد في الأسئلة الرسمية إجابات خاصة بغير السعوديين على هذه الأسئلة. اسأل قسم العناية بالموظفين.",
  aud_saudi="سعوديون (المعاشات)", unofficial=""),
 "en": dict(title="Frequently asked questions", desc="Answers from official sources about the move to Health Holding (English translation of the Arabic official FAQ).", h1="Frequently asked questions", p="Answers from official sources only. Search by a word, or pick a topic.",
  search="Search the questions…", searchlbl="Search", cats_all="All", aud_lbl="I am:", aud=["All", "Saudi", "Non-Saudi"],
  banner="Unofficial translation. The official FAQ is published in Arabic only; this English version was translated from it and has not been reviewed by Health Holding. If in doubt, the Arabic text and the Employee Care Department decide. The official FAQ does not separate Saudi and non-Saudi staff except where marked. Items marked “Saudis” concern pension rules. Non-Saudi and your question is about the transition? Ask the Employee Care Department.",
  count="{n} questions", none_h="We did not find an answer to your question", none_p="Please do not guess. Send your question to the Employee Care Department.", ask="Ask the Employee Care Department", source="Source:", askq="Can't find your question?",
  nonsaudi_note="The official FAQ has no separate answers for non-Saudis on these questions. Please ask the Employee Care Department.",
  aud_saudi="Saudis (pension)", unofficial=""),
}
CAT_EN = {"about": "Transition & Health Holding", "salary": "Salaries & allowances", "contract": "Contract & job title",
          "qiwa": "Mawared & Qiwa platforms", "decline": "If you do not want to transfer", "retire": "Retirement & service merge",
          "benefits": "Rewards, benefits & development", "leave": "Leave", "legal": "General information from regulations"}
SRC_EN = {"health.sa": "Health Holding – FAQ (Arabic original)", "hrsd.gov.sa": "Ministry of Human Resources and Social Development (HRSD)",
          "gosi.gov.sa": "GOSI – FAQ on amending the benefit-exchange system"}
SRC_AR_SHORT = {}

def faq(lang):
    f = FQ[lang]; t = S[lang]
    d = json.load(open(os.path.join(ROOT, "kb", "faq-approved.json"), encoding="utf-8"))
    en = json.load(open(os.path.join(ROOT, "tools", "faq_en.json"), encoding="utf-8")) if lang == "en" else {}
    cats = d["categories"]
    chips = [f'<button type="button" class="chip" data-cat="" aria-pressed="true">{e(f["cats_all"])} <small>{sum(len(c["items"]) for c in cats)}</small></button>']
    total = 0; items_html = []
    for c in cats:
        nm = c["name"] if lang == "ar" else CAT_EN[c["key"]]
        chips.append(f'<button type="button" class="chip" data-cat="{c["key"]}" aria-pressed="false">{e(nm)} <small>{len(c["items"])}</small></button>')
        for it in c["items"]:
            total += 1
            q, a = (it["q"], it["a"]) if lang == "ar" else (en[str(it["id"])]["q"], en[str(it["id"])]["a"])
            aud = "saudi" if str(it["id"]).startswith("GOSI") else "all"
            badge = f'<span class="aud saudi">{e(f["aud_saudi"])}</span> ' if aud == "saudi" else ""
            host = re.sub(r"^https?://(www\.)?", "", it["src"]).split("/")[0]
            srcname = it["srcname"] if lang == "ar" else SRC_EN.get(host, host)
            paras = "".join(f"<p>{e(p)}</p>" for p in a.split("\n") if p.strip())
            items_html.append(
                f'<details class="fq" data-cat="{c["key"]}" data-aud="{aud}"><summary><span class="qt">{badge}<span class="qtext">{e(q)}</span></span></summary>'
                f'<div class="body">{paras}<p class="src">{e(f["source"])} <a href="{e(it["src"])}" rel="noopener" target="_blank">{e(srcname)}</a></p></div></details>')
    audchips = "".join(
        f'<button type="button" class="chip" data-aud="{k}" aria-pressed="{"true" if k=="all" else "false"}">{e(lbl)}</button>'
        for k, lbl in zip(["all", "saudi", "nonsaudi"], f["aud"]))
    askbase = ticket(lang, "?type=inquiry&q=")
    body = f'''<section class="page-head"><div class="wrap"><h1>{e(f["h1"])}</h1><p>{e(f["p"])}</p></div></section>
<section class="s"><div class="wrap">
  <div class="note{" warnbox" if lang=="en" else ""}" style="margin-top:0;margin-bottom:16px">{e(f["banner"])}</div>
  <div class="toolbar">
    <div class="searchbar"><input type="search" id="q" placeholder="{e(f["search"])}" aria-label="{e(f["searchlbl"])}" autocomplete="off" enterkeyhint="search"></div>
    <div class="fgroup" role="group" aria-label="{e(f["aud_lbl"])}"><span class="lbl">{e(f["aud_lbl"])}</span>{audchips}</div>
    <div class="fgroup" id="cats" role="group" aria-label="{e(f["cats_all"])}">{"".join(chips)}</div>
  </div>
  <p class="count" id="cnt" aria-live="polite" data-tpl="{e(f["count"])}">{e(f["count"].format(n=total))}</p>
  <div id="nsnote" class="note warnbox" hidden>{e(f["nonsaudi_note"])}</div>
  <div id="list">{"".join(items_html)}</div>
  <div class="empty" id="empty"><h2 style="margin-bottom:6px">{e(f["none_h"])}</h2><p>{e(f["none_p"])}</p>
    <a class="btn solid" id="ask-empty" href="{askbase}" data-base="{askbase}">{e(f["ask"])}</a></div>
  <p class="faq-note">{e(f["askq"])} <a id="ask-link" href="{askbase}" data-base="{askbase}">{e(f["ask"])}</a></p>
</div></section>'''
    write(lang, "faq", page(lang, "faq", f["title"], f["desc"], body, scripts=["common.js","faq.js"], cur="faq"))

# ---------------------------------------------------------------- LINKS
LK = {
 "ar": dict(title="الروابط الرسمية", desc="الروابط الرسمية المهمة للموظف مرتبة بالموضوع مع بحث وفلاتر.", h1="الروابط الرسمية", p="كل الروابط تفتح مواقع الجهات الرسمية. ابحث، أو افتح الموضوع الذي تريده.",
  search="ابحث في الروابط…", searchlbl="ابحث", aud_lbl="أنا:", aud=["الكل", "سعودي", "غير سعودي"], org_lbl="الجهة:", org_all="كل الجهات",
  eng_lbl="الصفحة بالإنجليزية فقط", expand="فتح الكل", collapse="طي الكل", count="{n} رابط", none="لا توجد روابط مطابقة. جرّب كلمة أخرى أو أزل الفلاتر.", reset="إعادة ضبط الفلاتر",
  audname={"all": "عام", "saudi": "سعوديون", "differs": "يختلف: سعودي / غير سعودي"}, legend="«عام» = الصفحة الرسمية لا تحدد جنسية. «يختلف» = الصفحة تشرح أحكامًا مختلفة للسعودي وغير السعودي.",
  en_page="النسخة الإنجليزية", en_only="الصفحة بالإنجليزية", ar_only="بالعربية فقط", opens="يفتح موقعًا رسميًا خارجيًا",
  who_h="سعودي أم غير سعودي؟ ما الذي يختلف", who_src="المصدر:", care="اسأل قسم العناية بالموظفين",
  ns_note="غير سعودي؟ نعرض لك الروابط العامة وما يخصك. إن لم تجد صفحة رسمية تخص الانتقال لغير السعوديين فاسأل قسم العناية بالموظفين.",
  ins_note="التأمين الطبي بعد الانتقال: لم نجد صفحة رسمية تشرحه. للاستفسار اسأل قسم العناية بالموظفين.",
  cmp_to="لا مصدر رسمي هنا", sa="السعودي:", ns="غير السعودي:",
 ),
 "en": dict(title="Official links", desc="Official links that matter to staff, grouped by topic, with search and filters.", h1="Official links", p="Every link opens an official website. Search, or open the topic you need.",
  search="Search the links…", searchlbl="Search", aud_lbl="I am:", aud=["All", "Saudi", "Non-Saudi"], org_lbl="Source:", org_all="All sources",
  eng_lbl="Page has an English version", expand="Open all", collapse="Close all", count="{n} links", none="No links match. Try another word or clear the filters.", reset="Clear filters",
  audname={"all": "General", "saudi": "Saudis", "differs": "Differs: Saudi / Non-Saudi"}, legend="“General” = the official page does not name a nationality. “Differs” = the page explains different rules for Saudis and non-Saudis.",
  en_page="English version", en_only="English page", ar_only="Arabic only", opens="Opens an official external website",
  who_h="Saudi or non-Saudi? What is different", who_src="Source:", care="Ask the Employee Care Department",
  ns_note="Non-Saudi? We show the general links and the ones that apply to you. If you cannot find an official page about the transition for non-Saudis, please ask the Employee Care Department.",
  ins_note="Medical insurance after the transfer: we did not find an official page explaining it. Please ask the Employee Care Department.",
  cmp_to="", sa="Saudi:", ns="Non-Saudi:",
 ),
}
ORG_ORDER = ["hhc", "r3", "moh", "hrsd", "gosi", "qiwa", "gov"]

CMP = {  # rows: (title ar/en, saudi ar/en, nonsaudi ar/en, src label ar/en, src url)
 "ar": [
  ("التأمينات الاجتماعية (GOSI)",
   "التغطية: المعاشات (التقاعد) والأخطار المهنية.",
   "التغطية: الأخطار المهنية فقط. اشتراك 2% يتحملها صاحب العمل (لا خصم من راتبك).",
   "GOSI – التسجيل", "https://www.gosi.gov.sa/GOSIOnline/Registration", "GOSI – أسئلة أصحاب العمل", "https://www.gosi.gov.sa/GOSIOnline/FAQ_Employer"),
  ("نظام العمل وعقد العمل",
   "تنطبق أحكام نظام العمل على علاقة العمل وفق النص الرسمي.",
   "تنطبق أحكام نظام العمل، وبعض مواده تذكر غير السعودي صراحة (مثل الإشارة إلى المادة 37). راجع النص الرسمي.",
   "وزارة الموارد البشرية – علاقات العمل", "https://www.hrsd.gov.sa/%D8%B9%D9%84%D8%A7%D9%82%D8%A7%D8%AA-%D8%A7%D9%84%D8%B9%D9%85%D9%84", "", ""),
  ("مكافأة نهاية الخدمة",
   "تنطبق الصفحات الرسمية على العامل دون ذكر جنسية.",
   "الصفحات الرسمية لا تذكر جنسية؛ إن كان وضعك مختلفًا اسأل القسم.",
   "وزارة الموارد البشرية – نهاية الخدمة", "https://www.hrsd.gov.sa/en/media-center/media/leendofservice", "", ""),
  ("الانتقال إلى الصحة القابضة",
   "الأسئلة الشائعة الرسمية تخاطب الموظفين دون تمييز بالجنسية.",
   "لا توجد صفحة رسمية مستقلة لغير السعوديين. اسأل قسم العناية بالموظفين.",
   "الصحة القابضة – الأسئلة الشائعة", "https://www.health.sa/ar/faqs", "", ""),
 ],
 "en": [
  ("Social insurance (GOSI)",
   "Covered for: pension (annuities) and occupational hazards.",
   "Covered for: occupational hazards only. The 2% contribution is paid by the employer (no deduction from your pay).",
   "GOSI – Registration", "https://www.gosi.gov.sa/GOSIOnline/Registration?locale=en_US", "GOSI – Employer FAQ", "https://www.gosi.gov.sa/GOSIOnline/FAQ_Employer?locale=en_US"),
  ("Labor Law and employment contract",
   "Labor Law provisions apply to the employment relationship as written in the official text.",
   "Labor Law provisions apply. Some articles name non-Saudis directly (for example a reference to Article 37). Read the official text.",
   "HRSD – Labor relations", "https://www.hrsd.gov.sa/en/%D8%B9%D9%84%D8%A7%D9%82%D8%A7%D8%AA-%D8%A7%D9%84%D8%B9%D9%85%D9%84", "", ""),
  ("End-of-service benefit",
   "The official pages apply to “the worker” and do not name a nationality.",
   "The official pages do not name a nationality. If your case is different, ask the Care team.",
   "HRSD – End of service", "https://www.hrsd.gov.sa/en/media-center/media/leendofservice", "", ""),
  ("Move to Health Holding",
   "The official FAQ speaks to employees without separating by nationality.",
   "There is no separate official page for non-Saudis. Ask the Employee Care Department.",
   "Health Holding – FAQ (Arabic)", "https://www.health.sa/ar/faqs", "", ""),
 ],
}

def links(lang):
    L = LK[lang]; t = S[lang]
    data = links_data.load()
    cats = links_data.CATS
    orgs_used = [o for o in ORG_ORDER if any(x["org"] == o for x in data)]
    oidx = 0 if lang == "ar" else 1
    org_opts = f'<option value="">{e(L["org_all"])}</option>' + "".join(f'<option value="{o}">{e(links_data.ORGS[o][oidx])}</option>' for o in orgs_used)
    audchips = "".join(
        f'<button type="button" class="chip" data-aud="{k}" aria-pressed="{"true" if k=="all" else "false"}">{e(lbl)}</button>'
        for k, lbl in zip(["all", "saudi", "nonsaudi"], L["aud"]))
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
                f'<div class="lrow" data-aud="{x["aud"]}" data-org="{x["org"]}" data-en="{has_en}">'
                f'<a class="t" href="{e(main)}" rel="noopener" target="_blank">{e(ttl)}</a>'
                f'<p>{e(desc)}</p>'
                f'<div class="meta"><span class="aud {x["aud"]}">{e(L["audname"][x["aud"]])}</span>{lang_badge}<span>{e(org)}</span>{alt}</div></div>')
        extra = f'<div class="note-card">{e(L["ins_note"])} <a href="mailto:{MAIL}" class="ltr">{MAIL}</a></div>' if key == "ins" else ""
        sections.append(
            f'<details class="lcat" data-cat="{key}"><summary><span>{e(car if lang=="ar" else cen)}<span class="cat-count">{len(rows)}</span></span></summary>'
            f'<div class="body"><p class="cat-sub">{e(sar if lang=="ar" else sen)}</p>{"".join(rh)}{extra}</div></details>')
    cmp_rows = []
    for tt, sa, ns, l1, u1, l2, u2 in CMP[lang]:
        srcs = f'<a href="{u1}" rel="noopener" target="_blank">{e(l1)}</a>' + (f' · <a href="{u2}" rel="noopener" target="_blank">{e(l2)}</a>' if u2 else "")
        cmp_rows.append(f'<div class="row"><h3>{e(tt)}</h3><dl><dt>{e(L["sa"])}</dt><dd>{e(sa)}</dd><dt>{e(L["ns"])}</dt><dd>{e(ns)}</dd></dl><p class="src" style="margin:6px 0 0">{e(L["who_src"])} {srcs}</p></div>')
    askm = f'mailto:{MAIL}'
    body = f'''<section class="page-head"><div class="wrap"><h1>{e(L["h1"])}</h1><p>{e(L["p"])}</p></div></section>
<section class="s"><div class="wrap">
  <div class="toolbar">
    <div class="searchbar"><input type="search" id="q" placeholder="{e(L["search"])}" aria-label="{e(L["searchlbl"])}" autocomplete="off" enterkeyhint="search"></div>
    <div class="fgroup" role="group" aria-label="{e(L["aud_lbl"])}"><span class="lbl">{e(L["aud_lbl"])}</span>{audchips}</div>
    <div class="fgroup"><label for="org" class="lbl">{e(L["org_lbl"])}</label><select id="org">{org_opts}</select>
      <label class="tcheck"><input type="checkbox" id="en-only"> {e(L["eng_lbl"])}</label>
      <button type="button" class="chip" id="reset">{e(L["reset"])}</button></div>
    <p class="srcline" style="margin:0">{e(L["legend"])}</p>
  </div>
  <div id="nsnote" class="note warnbox" hidden style="margin:0 0 12px">{e(L["ns_note"])} <a href="{askm}" class="ltr">{MAIL}</a></div>
  <div class="fgroup" style="justify-content:space-between;margin-bottom:8px"><p class="count" id="cnt" aria-live="polite" data-tpl="{e(L["count"])}" style="margin:0">{e(L["count"].format(n=len(data)))}</p>
    <span><button type="button" class="chip" id="expand">{e(L["expand"])}</button> <button type="button" class="chip" id="collapse">{e(L["collapse"])}</button></span></div>
  <div id="list">{"".join(sections)}</div>
  <div class="empty" id="empty">{e(L["none"])}</div>
</div></section>
<section class="s alt" id="who"><div class="wrap">
  <h2 class="u">{e(L["who_h"])}</h2>
  <div class="cmp">{"".join(cmp_rows)}</div>
  <p style="margin-top:14px"><a class="btn solid" href="{askm}">{e(L["care"])}</a></p>
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
  after=[("رقم التذكرة", "يظهر لك مباشرة بعد الإرسال. احتفظ به لأنه لا يُرسل لك بالبريد حاليًا."),
         ("مراجعة القسم", "تصل التذكرة إلى لوحة القسم، وقد يتواصل معك على بريدك الوزاري أو جوالك."),
         ("حالة الطلب", "تتغير بين: جديدة، قيد المعالجة، مغلقة."),
         ("الرد", "يظهر لك في صفحة المتابعة برقم التذكرة وبريدك الوزاري.")],
  noreply="لم يُعلن موعد محدد للرد، فلا نعدك بمدة. للأمور العاجلة اتصل على التحويلة 671.",
  types_h="أنواع الطلبات",
  types=[("استفسار", "سؤال عن إجراء أو حالتك الوظيفية. جرّب أولًا الأسئلة الشائعة."), ("شكوى", "ملاحظة على إجراء أو تعامل تحتاج متابعة."),
         ("اقتراح", "فكرة لتحسين تجربة الانتقال أو خدمات الموظفين."), ("طلب معلومات", "طلب بيان أو معلومة محددة.")],
  need_h="ما الذي تحتاجه لفتح تذكرة؟",
  need="بريدك الوزاري المنتهي بـ moh.gov.sa، ورقم جوالك (05XXXXXXXX)، ورقمك الوظيفي. هذه البيانات إلزامية لنتمكن من التواصل معك.",
  priv="الخصوصية: تُستخدم بيانات التذكرة للتواصل معك بخصوص طلبك فقط، ويطّلع عليها قسم العناية بالموظفين. لا تُرسل كلمات مرور أو بيانات بنكية أو أرقام هوية. تفاصيل مدة الاحتفاظ بالبيانات تُحدَّد بالاتفاق مع القسم.",
  faq_link="الأسئلة الشائعة"),
 "en": dict(title="Contact the Employee Care Department", desc="How to contact the Employee Care Department: ticket, email, phone.", h1="How do I contact the Employee Care Department?",
  p="Three ways. We recommend a ticket because it gives you a number to track your request.",
  ch=[("1. Online ticket (best)", "Fill in the form in three steps and get a number to track your request.", "Open a ticket", ticket("en")),
      ("2. Email", "Send from your ministry email. Include your name, employee number, mobile, facility and request type.", "Write an email", "mailto:" + MAIL),
      ("3. Phone", "Call the Employee Care Department on extension 671. Best for urgent matters.", "", "")],
  copy="Copy email", copied="Copied", track="Track a ticket",
  after_h="What happens after you submit?",
  after=[("Ticket number", "Shown right after you submit. Keep it: it is not sent by email at the moment."),
         ("Review", "The ticket goes to the department's dashboard. They may contact you on your ministry email or mobile."),
         ("Status", "It changes between: New, In progress, Closed."),
         ("Reply", "It appears on the Track page when you enter your ticket number and ministry email.")],
  noreply="No reply time has been announced, so we cannot promise one. For urgent matters call extension 671.",
  types_h="Request types",
  types=[("Inquiry", "A question about a procedure or your job status. Try the FAQ first."), ("Complaint", "A comment on a procedure or treatment that needs follow-up."),
         ("Suggestion", "An idea to improve the transition or staff services."), ("Information request", "A request for a specific statement or piece of information.")],
  need_h="What you need to open a ticket",
  need="Your ministry email ending in moh.gov.sa, your mobile number (05XXXXXXXX) and your employee number. These are required so the team can reach you.",
  priv="Privacy: ticket data is used only to contact you about your request, and is seen by the Employee Care Department. Do not send passwords, bank details or ID numbers. How long data is kept will be agreed with the department.",
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

if __name__ == "__main__":
    for lg in ("ar", "en"):
        home(lg); faq(lg); links(lg); contact(lg)
    print("built")
