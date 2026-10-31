# -*- coding: utf-8 -*-
"""Official links (all verified HTTP 200 on 2026-10-31). Arabic text comes from
linkwork/final_status.tsv; English text written for this guide.
aud: 'all' = official page does not distinguish by nationality; 'saudi' = applies to Saudis (per GOSI text);
     'differs' = the official page explains different rules for Saudis and non-Saudis."""
import os
TSV = os.environ.get("LINKS_TSV", "/workspace/linkwork/final_status.tsv")

CATS = [
 ("start", "ابدأ من هنا", "Start here", "المصادر الرسمية عن الانتقال إلى الصحة القابضة.", "Official sources about the move to Health Holding."),
 ("contract", "العقد ومنصة قوى", "Contract & Qiwa", "مراجعة العقد وتوثيقه وحقوقك في علاقة العمل.", "Reviewing and documenting your contract, and your rights at work."),
 ("salary", "الراتب والأجور", "Salary & wages", "الراتب، المكافآت، حماية الأجور وساعات العمل.", "Salary, bonuses, wage protection and working hours."),
 ("eos", "نهاية الخدمة والإجازات", "End of service & leave", "مكافأة نهاية الخدمة والإجازة السنوية.", "End-of-service benefit and annual leave."),
 ("ins", "التأمينات الاجتماعية", "Social insurance (GOSI)", "الاشتراك، التغطية، والمعاش.", "Registration, coverage and pension."),
 ("plat", "المنصات الإلكترونية", "Online platforms", "بوابات الخدمات التي قد تحتاجها.", "Portals you may need."),
]
ORGS = {
 "hhc": ("الصحة القابضة", "Health Holding"), "r3": ("تجمع الرياض الصحي الثالث", "Riyadh Third Health Cluster"),
 "moh": ("وزارة الصحة", "Ministry of Health"), "hrsd": ("وزارة الموارد البشرية", "HRSD (Ministry of Human Resources)"),
 "gosi": ("التأمينات الاجتماعية", "GOSI"), "qiwa": ("منصة قوى", "Qiwa"), "gov": ("المنصة الوطنية", "National Platform"),
}
# per row of the tsv (1-based): (org, aud, en_title, en_desc, en_url or None, en_only)
EN = {
 1: ("hhc","all","Health Holding – transition FAQ","Official questions and answers about moving employees. (Arabic only; an English translation is on this site's FAQ page.)",None,False),
 2: ("hhc","all","Health Holding – official website","Company home page, news and health clusters.","https://www.health.sa/en",False),
 3: ("hhc","all","Riyadh Third Health Cluster on the Health Holding site","Our cluster's page on the Health Holding website.","https://www.health.sa/en/clusters/riyadh_third_health_cluster_v2",False),
 4: ("hhc","all","Health Holding news","News and announcements published officially by the company.","https://www.health.sa/en/news",False),
 5: ("hhc","all","The Saudi Model of Care","Health Holding's explanation of the model of care and the roles of each body.","https://www.health.sa/en/model-of-care",False),
 6: ("hhc","all","Contact Health Holding","The general contact page on the Health Holding website.","https://www.health.sa/en/contact-us",False),
 7: ("r3","all","Riyadh Third Health Cluster – official website","The cluster's official site and its facilities. (English version not confirmed.)",None,False),
 8: ("moh","all","Ministry of Health FAQ: rules and arrangements for employees","Rules and arrangements based on Council of Ministers decision No. 616.","https://www.moh.gov.sa/en/support/faq/pages/faq20.aspx",False),
 9: ("moh","all","Ministry of Health news: phase 2 of the transition completed","Official announcement that phase 2 of moving Ministry employees to seven health clusters is complete.",None,True),
 10: ("qiwa","all","Qiwa platform","Where you review your employment contract after the Qiwa message (per the Health Holding FAQ).","https://www.qiwa.sa/en",False),
 11: ("hrsd","all","Contract documentation service","Ministry page for contract documentation (aimed at employers). It includes FAQs on contract start date and previous service.","https://www.hrsd.gov.sa/en/ministry-services/services/%D8%A5%D8%AF%D8%A7%D8%B1%D8%A9-%D8%A7%D9%84%D8%B9%D9%82%D9%88%D8%AF",False),
 12: ("hrsd","all","Procedure guide for contract documentation (PDF)","The official published guide to contract documentation steps.",None,False),
 13: ("hrsd","all","Contract documentation guide (Knowledge Centre page)","The guide and its related ministerial decision in the Ministry's Knowledge Centre.",None,False),
 14: ("hrsd","differs","Labor Law: labor relations","Labor Law articles on labor relations and the employment contract. Some articles address non-Saudis separately (for example, a reference to Article 37).","https://www.hrsd.gov.sa/en/%D8%B9%D9%84%D8%A7%D9%82%D8%A7%D8%AA-%D8%A7%D9%84%D8%B9%D9%85%D9%84",False),
 15: ("hrsd","all","HRSD client page: complaints, requests and reports","The Ministry's official channel for complaints, requests and reports.","https://www.hrsd.gov.sa/en/ministry-services/services/client-page",False),
 16: ("hrsd","all","HRSD services for individuals","The Ministry's services page for individuals.","https://www.hrsd.gov.sa/en/individuals",False),
 17: ("moh","all","Ministry of Health news: transition bonuses being paid","Official announcement that transition bonuses have started for transferred civil-service employees, under Council of Ministers decision 616.",None,True),
 18: ("gov","all","Wage certificate (contributory wage) – GOSI service","Electronic service that issues a certificate of the wage subject to GOSI contributions.","https://my.gov.sa/en/services/20435",False),
 19: ("hrsd","all","Wage Protection Program","Official description of wage protection. It covers private-sector workers, Saudi and expatriate.","https://www.hrsd.gov.sa/en/knowledge-centre/initiatives/national-transformation-initiatives-bank/108808",False),
 20: ("hrsd","all","Labor Law: working conditions","Labor Law articles on working hours and overtime pay.",None,False),
 21: ("hrsd","all","Rights at the end of an employment contract","The Ministry's explanation of the end-of-service benefit and how it is calculated under the Labor Law.","https://www.hrsd.gov.sa/en/media-center/media/lerightseocontract",False),
 22: ("hrsd","all","End of service","The Ministry's page on how and when the benefit is calculated and due.","https://www.hrsd.gov.sa/en/media-center/media/leendofservice",False),
 23: ("qiwa","all","How to calculate your end-of-service benefits (Qiwa)","Qiwa page explaining how the benefit is calculated from your account.",None,True),
 24: ("hrsd","all","Labor Law: working conditions (includes annual leave)","Labor Law articles on annual leave and working hours.",None,False),
 25: ("gosi","all","GOSI – official website","The General Organization for Social Insurance portal.","https://www.gosi.gov.sa/en",False),
 26: ("gosi","saudi","GOSI FAQ: amendment of the benefit-exchange system","Official FAQ on the decision amending the exchange of benefits between retirement and insurance systems (pension systems).","https://www.gosi.gov.sa/GOSIOnline/benefitexchange_faq?locale=en_US",False),
 27: ("gosi","saudi","GOSI services for retirees","Pension services and early-retirement conditions.",None,False),
 28: ("qiwa","all","Qiwa platform (for individuals)","Review employment contracts and employee services.","https://www.qiwa.sa/en",False),
 29: ("gov","all","National Platform (my.gov.sa)","The unified government services portal.","https://my.gov.sa/en",False),
 30: ("hrsd","all","HRSD e-services","The Ministry's electronic services portal.",None,False),
 31: ("moh","all","Mawared: Ministry of Health employee portal","Login page. It may not apply after the transfer; ask the Care team if unsure.",None,False),
}
EXTRA = [  # (cat, org, aud, ar_title, ar_desc, ar_url, en_title, en_desc, en_url)
 ("ins","gosi","differs","التأمينات: من يشمله النظام ومتى يبدأ الاشتراك","صفحة التسجيل الرسمية: فرع المعاشات للسعوديين فقط، وفرع الأخطار المهنية على جميع العاملين دون تمييز في الجنسية.",
  "https://www.gosi.gov.sa/GOSIOnline/Registration","GOSI: who is covered and how registration works","Official registration page: the pension (annuities) branch covers Saudis only; the occupational-hazards branch covers all workers regardless of nationality.","https://www.gosi.gov.sa/GOSIOnline/Registration?locale=en_US"),
 ("ins","gosi","differs","التأمينات: أسئلة أصحاب العمل","أسئلة شائعة رسمية؛ تذكر أن تغطية غير السعودي في فرع الأخطار المهنية فقط، وأن اشتراكه 2% يتحملها صاحب العمل.",
  "https://www.gosi.gov.sa/GOSIOnline/FAQ_Employer","GOSI: employer FAQ","Official FAQ: a non-Saudi contributor is covered under the occupational-hazards branch only; the 2% contribution is paid by the employer.","https://www.gosi.gov.sa/GOSIOnline/FAQ_Employer?locale=en_US"),
]

def load():
    rows = [l.rstrip("\n").split("|") for l in open(TSV, encoding="utf-8") if l.strip()]
    out = []
    for i, r in enumerate(rows, 1):
        code, cat, ar_title, url, ar_desc, _org = r[:6]
        org, aud, en_title, en_desc, en_url, en_only = EN[i]
        ar_url = None if en_only else url
        if en_only:
            en_url = url
        out.append(dict(cat=cat, org=org, aud=aud, ar_title=ar_title, ar_desc=ar_desc.replace(" (الصفحة بالإنجليزية)", ""),
                        ar_url=ar_url, en_title=en_title, en_desc=en_desc, en_url=en_url, en_only=en_only, code=code))
    for cat, org, aud, at, ad, au, et, ed, eu in EXTRA:
        out.append(dict(cat=cat, org=org, aud=aud, ar_title=at, ar_desc=ad, ar_url=au, en_title=et, en_desc=ed,
                        en_url=eu, en_only=False, code="200"))
    return out
