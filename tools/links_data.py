# -*- coding: utf-8 -*-
"""Official links shown on the Links page. Data is in tools/links.json (all links returned HTTP 200 on 2026-10-31)."""
import os, json

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

def load():
    return json.load(open(os.path.join(os.path.dirname(__file__), "links.json"), encoding="utf-8"))
