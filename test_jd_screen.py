"""python3 test_jd_screen.py  - checks the wall rules on real and synthetic ad texts."""
import sys
import jd_screen as S

PAD = " We build software for clients across Europe and value clear communication and ownership of results. " * 3

CASES = [
    # (name, text, expected verdict, expected rule id or None)
    ("PL based must", "Technical Product Manager. Requirements:\n• 5+ years as PM\n• Candidates must be based in Poland\n" + PAD, "wall", "poland_based"),
    ("PL based soft", "Product Manager role.\n• Poland-based candidates preferred, but we are open to the EU.\n" + PAD, "ok", None),
    ("UA only EN", "Senior PM\nOnly candidates from Ukraine will be considered.\n" + PAD, "wall", "ukraine_only"),
    ("UA only UA", "Вимоги:\n• Тільки кандидати з України\n• Досвід роботи від 5 років\n" + PAD, "wall", "ukraine_only"),
    ("EU citizens only", "Project Manager. Only EU citizens can apply for this position because of the client contract. " + PAD, "wall", "eu_citizens"),
    ("US auth", "You must be authorized to work in the US. Delivery Manager for our American clients. " + PAD, "wall", "other_country"),
    ("Work anywhere in Poland", "Remote role. Work from anywhere in Poland. English is the working language. " + PAD, "ask", "poland_anywhere"),
    ("Polish required", "Requirements:\n• Fluent Polish and English\n• PMO experience\n" + PAD, "wall", "lang_polish"),
    ("Polish plus", "Nice to have:\n• Polish language\n• Jira Align\n" + PAD, "ok", None),
    ("No need Polish", "You do not need to speak Polish. All communication in English. " + PAD, "ok", None),
    ("German required UA", "Вимоги:\n• Знання німецької мови на рівні B2 обов'язково\n" + PAD, "wall", "lang_german"),
    ("German verhandlungssicher", "Anforderungen:\n• Verhandlungssicheres Deutsch und Englisch\n" + PAD, "wall", "lang_german"),
    ("Bulgarian required", "Requirements: Bulgarian language is required, English fluent. Project manager in Sofia. " + PAD, "wall", "lang_other"),
    ("PMP required", "Requirements:\n• PMP certification\n• 5 years of PM experience\n" + PAD, "wall", "cert_pmp"),
    ("PMP preferred", "Qualifications:\n• PMP preferred\n• Jira\n" + PAD, "ok", None),
    ("PRINCE2 method only", "Requirements:\n• Knowledge of Agile, Waterfall, PMBOK, PRINCE2 methodologies\n" + PAD, "ask", "cert_other"),
    ("PRINCE2 cert required", "Requirements:\n• PRINCE2 Practitioner certification is mandatory\n" + PAD, "wall", "cert_other"),
    ("SAFe cert plus", "Nice to have:\n• SAFe SSM certification\n" + PAD, "ok", None),
    ("ServiceNow must", "Requirements:\n• Strong ServiceNow experience (architecture, CMDB)\n" + PAD, "wall", "dom_itsm"),
    ("ServiceNow plus", "Nice to have: ServiceNow or ITSM tools. " + PAD, "ok", None),
    ("SAP in about", "About us:\nWe work with large enterprises, many run SAP landscapes.\n" + PAD, "ok", None),
    ("Pharma must", "Requirements:\n• Pharma / GxP project delivery experience\n" + PAD, "wall", "dom_pharma"),
    ("Infra must", "Requirements:\n• Experience leading data center migration projects\n" + PAD, "wall", "dom_infra"),
    ("Power BI plus", "Preferred:\n• Power BI dashboards\n" + PAD, "ok", None),
    ("Bank experience must", "Requirements:\n• 3+ years of experience in banking\n" + PAD, "wall", "dom_bank"),
    ("Hybrid Warsaw", "Hybrid model: 3 days per week in our Warsaw office. " + PAD, "wall", "office_not_sofia"),
    ("Hybrid Sofia", "Hybrid model: 2 days per week in our Sofia office. " + PAD, "ok", None),
    ("Fully remote + meetups", "100% remote. Optional meetups twice a year in the office. " + PAD, "ok", None),
    ("Relocation required", "Requirements:\n• Must be willing to relocate to Berlin within 3 months\n" + PAD, "wall", "relocation_required"),
    ("US overlap is fine", "Fully remote. Overlap with US East Coast hours is required (EST mornings). " + PAD, "ok", None),
    ("Russia ties", "We have offices in Moscow and Warsaw. Fully remote PM wanted. " + PAD, "ask", "russia_ties"),
    ("Clean ad", "Delivery Manager. You will lead delivery of B2B iGaming platform integrations: payments, KYC providers, content. Requirements: 5+ years delivery management, Jira, stakeholder management, English C1. Nice to have: iGaming experience. We offer fully remote work, flexible hours and a competitive salary. " * 2, "ok", None),
    ("Too short", "Product Manager. Remote.", "nojd", None),
]

CASES += [
    ("onsite meetings", "Location: based in the European Union. Available to travel for onsite meetings with teams as needed. " + PAD, "ok", None),
    ("on-site content", "We are a fast-growing crypto IGaming company with a high volume of on-site content. Remote role. " + PAD, "ok", None),
    ("requirements for SAP systems", "Responsibilities: Gathers and analyses requirements for SAP ERP information systems. " + PAD, "ok", None),
    ("example tools", "Hands-on experience with BI tools (e.g., Tableau, Looker, Power BI) to track health. " + PAD, "ok", None),
    ("semicolon list", "Requirements:\n• fintech product experience (must); banking experience (optional); Jira. " + PAD, "ok", None),
]
CASES += [
    ("GCP is not pharma", "Requirements:\n• Practical experience with Google Cloud Platform (GCP) and cloud-native technologies\n" + PAD, "ok", None),
    ("related list cut", "Project Manager. " + PAD * 2 + "\nСхожі вакансії\nSenior Azure DevOps Engineer (German Speaking) New\nПовна німецька обов'язкова" , "ok", None),
    ("sidebar listing line", "Requirements:\n• Jira\nHealthcare Project Manager (hybrid, Kyiv) в CHI Software , віддалено\n" + PAD, "ok", None),
    ("parens examples", "Requirements:\n• Strong data visualization tools (Looker, Tableau, Power BI) skills\n" + PAD, "ok", None),
    ("remote or hybrid choice", "Choose your format: remote, hybrid or office in Kyiv. " + PAD, "ok", None),
    ("hybrid 3 days, no remote", "Hybrid format: 3 days per week in the Kyiv office. " + PAD, "wall", "office_not_sofia"),
    ("relocation perk", "Benefits: relocation support for team members who want to move. Remote role. " + PAD, "ok", None),
    ("SAFe exposure", "Requirements:\n• SAFe or other scaled-agile exposure\n" + PAD, "ok", None),
    ("PMP or similar", "Requirements:\n• PMP, Agile, Scrum, SAFe, or similar project management certification\n" + PAD, "ask", "cert_pmp"),
]
CASES += [
    ("WILL BE A PLUS caps", "REQUIREMENTS\n• Jira\nWILL BE A PLUS\n• Certifications such as PMP, PRINCE2, PMI-ACP\nPERSONAL PROFILE\n• Team player\n" + PAD, "ok", None),
    ("Will be a plus colon", "Requirements:\n• Jira\nWill be a plus:\n• Experience working on Salesforce projects.\nResponsibilities:\n• Plan\n" + PAD, "ok", None),
    ("hot vacancies cut", "Project Manager. " + PAD * 2 + "\nГарячі Project Manager вакансії\nSAP Consultant в X , Київ\nPMP обов'язково", "ok", None),
]
POLISH_AD = ("Szukamy doświadczonego Project Managera do naszego zespołu. Oferujemy pracę w międzynarodowym zespole, "
             "elastyczne godziny oraz pracę zdalną. Wymagania: doświadczenie w zarządzaniu projektami IT, znajomość Jira, "
             "umiejętność pracy z klientem i zespołem. Będziesz odpowiedzialny za planowanie projektów, kontakt z klientami "
             "oraz raportowanie postępów. Dla nas ważne jest, aby kandydat dobrze czuł się w pracy zespołowej. " * 2)
CASES.append(("Ad in Polish", POLISH_AD, "ask", "ad_polish"))
CASES.append(("Hybrid cooperation = perk (Devart)", "We offer:\nManage your own working hours with our flexible schedule\n19 days of annual vacation granted on a pro-rata basis\nNo overtimes required\n* Hybrid type of cooperation\n" + PAD + " Remote work possible.", "ok", None))
CASES.append(("Onsite nearshore offshore model (HCLTech)", "Requirements:\n• Experience working in global delivery models (onsite, nearshore, offshore)\n" + PAD, "ok", None))
CASES.append(("Broken Build SAFe exposure", "Requirements:\n• 3+ years as PM\n• SAFe or other scaled-agile exposure\n" + PAD, "ok", None))


bad = 0
for name, text, exp_v, exp_id in CASES:
    r = S.screen(text)
    ids = [h["id"] for h in r["hits"] if h["level"] in ("wall", "ask")]
    ok = r["verdict"] == exp_v and (exp_id is None or exp_id in ids)
    if not ok:
        bad += 1
    print(("OK   " if ok else "FAIL ") + name.ljust(28), "->", r["verdict"], ids, "" if ok else "| expected %s %s" % (exp_v, exp_id))
    if not ok:
        for h in r["hits"]:
            print("       ", h["level"], h["id"], "«%s»" % h["quote"][:100])

for path, exp_v in (("/home/claude/optiveum_jd.txt", "wall"), ("/home/claude/om-defence/jd.txt", "ok|ask")):
    try:
        r = S.screen(open(path, encoding="utf-8").read())
    except FileNotFoundError:
        continue
    print("REAL", path.split("/")[-1].ljust(20), "->", r["verdict"], [(h["level"], h["id"]) for h in r["hits"]], "(expected %s)" % exp_v)
    print("     ", S.why(r)[:300])

print("\n%d/%d passed" % (len(CASES) - bad, len(CASES)))
sys.exit(1 if bad else 0)
