"""
jd_rules.py - the wall list for JD-body screening.

One rule = one kind of wall.  Each rule has:
  id, label (English) and label_uk (Ukrainian) shown on the card, group (one hit per group is kept: the strongest),
  needs   - when the wall applies to a person (checked against the search profile in jd_screen.match):
            ("always",) | ("residency", country or None) | ("language", language or None) | ("cert", family) |
            ("domain", key) | ("eu_citizen",) | ("eu_right",) | ("avoid", place) | ("office",).
            None means "detect it from the matched text".
  kind:
    always  - the phrase itself is a wall (country residency). Soft words ("preferably") make it a note.
    ctx     - the phrase is a wall only when the text says it is REQUIRED (must / requirements section);
              "nice to have" / "plus" / "preferred" -> note; no context -> `default` (wall or ask).
    office  - hybrid / on-site, a wall unless the text names Sofia/Bulgaria (see screen()).
  patterns - regexes, case-insensitive. Use (?-i:...) for a case-sensitive token, e.g. (?-i:SAP).
  level    - for kind=always: wall (default) or ask.
  default  - for kind=ctx: level without context (default ask; domain rules use note: only "required" makes a wall).
  wall_needs - for kind=ctx: extra regex that must also be in the same sentence for a wall,
               otherwise the hit is only an ask (e.g. "PRINCE2" alone is a method, "PRINCE2 certification" is a gate).
Verdicts: wall (auto-skip) / ask (open the page and check) / ok.
"""
import re

# ------------------------------------------------------------------ context words
MUST = re.compile(
    r"\b(must|required|mandatory|obligatory|essential|necessary|need to|needs to|has to|have to|"
    r"is a must|should have|must[- ]have|minimum qualifications?|"
    r"wymagan\w*|obowi[aą]zkow\w*|konieczn\w*|musisz|"
    r"erforderlich|zwingend|vorausgesetzt|muss|"
    r"обов.?язков\w*|необхідн\w*|потрібн\w*|"
    r"обязательн\w*|требуется|необходим\w*)\b", re.I)
SOFT = re.compile(
    r"\b(nice[- ]to[- ]have|preferred|preferably|a plus|is a plus|plus|advantage|an asset|bonus|desirable|"
    r"ideally|beneficial|welcome|would be (great|nice|an advantage|a plus)|not required|optional|"
    r"опціонально|за наявності|"
    r"бажано|буде плюсом|перевага|плюсом|бажан\w*|"
    r"mile widziane|po[zż][aą]dane|atut|"
    r"w[uü]nschenswert|von vorteil|ein plus|"
    r"желательно|будет плюсом|преимуществ\w*)\b", re.I)
SOFT = re.compile(SOFT.pattern + r"|\bnice\s*:|\bbonus\s*:|\bplus\s*:|\be\.g\.|\bfor example\b|\bsuch as\b|наприклад", re.I)
NEGATE = re.compile(
    r"\b(no need|not required|not necessary|don.?t need|do not need|no .{0,20} required|without|regardless|"
    r"не обов.?язков\w*|не потрібн\w*|без обмежень|nie wymagamy|nie jest wymagan\w*)\b", re.I)
MUST_HEADING = re.compile(
    r"^(requirements?|qualifications?|what you.?ll bring|what we.?re looking for|what we expect|you have|you bring|"
    r"must[- ]haves?|who you are|your profile|skills and experience|"
    r"вимоги|ми очікуємо|очікуємо від вас|від вас|що потрібно|"
    r"wymagania|oczekiwania|nasze oczekiwania|"
    r"anforderungen|ihr profil|dein profil|"
    r"требования|мы ожидаем)\b", re.I)
SOFT_HEADING = re.compile(
    r"^(nice[- ]to[- ]haves?|preferred( qualifications)?|bonus( points)?|a plus|pluses|plus|desirable|"
    r"(will|would) be (a )?(plus|nice|an advantage|great)|good to have|extra points|additional (skills|qualifications)|"
    r"будемо раді|буде плюсом|бажано|буде перевагою|"
    r"mile widziane|dodatkowym atutem|"
    r"von vorteil|w[uü]nschenswert|"
    r"будет плюсом|желательно)\b", re.I)
OTHER_HEADING = re.compile(
    r"^(responsibilities|what you.?ll do|your role|the role|about us|about the (role|company|team)|benefits|"
    r"we offer|what we offer|our offer|perks|why join|how to apply|"
    r"обов.?язки|ваші завдання|ми пропонуємо|про нас|про компанію|умови|"
    r"zakres obowi[aą]zk[oó]w|oferujemy|o nas|"
    r"aufgaben|wir bieten|[uü]ber uns|"
    r"обязанности|мы предлагаем)\b", re.I)

REMOTE = re.compile(r"\b(remote|work from home|work from anywhere|home office)\b|віддален|дистанцій|удален", re.I)

# ------------------------------------------------------------------ the rules
import geo as _geo

# Every country name the catalogue knows (longest first), escaped, for "based in <country>" style patterns.
_COUNTRIES = "|".join(re.escape(n) for n in _geo.all_country_names())
_FRAME = r"(?:candidates?|applicants?|you|must|should|need to|required to|have to|only|resident|residents)"

RULES = [
    # ---- G1: country / residency (answer 13.10: wall)
    dict(id="poland_based", label="Only residents of Poland", label_uk="Тільки з Польщі (резидентство)", needs=("residency", "poland"), group="residency", kind="always", patterns=[
        _FRAME + r"[^.\n]{0,50}(?:based|located|resid\w+|living|live|reside)\s+(?:in|within)\s+(?:the\s+)?(?:Republic of\s+)?Poland",
        r"Poland[- ](?:based|resident)s?\s+(?:candidates?|only|required|applicants?)",
        r"(?:right|permit|authori[sz]ation)\s+to\s+work\s+in\s+Poland",
        r"Polish\s+(?:work\s+permit|residen\w+|citizen\w+|tax resident)",
        r"(?:mieszkaj[aą]c\w+|zamieszka\w+|rezydent\w*)\s+(?:w|na terenie)\s+Polsce",
        r"(?:резидент\w*|проживан\w+|проживає\w*|проживаєте)\s+(?:в|у|на території)\s+Польщ",
        r"(?:кандидат\w*|претендент\w*)[^.\n]{0,30}(?:з|із|в|у)\s+Польщ"]),
    dict(id="poland_anywhere", label="Remote only within Poland (check whether they accept your country)", label_uk="«Work from anywhere in Poland» (перевір, чи приймають з Болгарії)", needs=("residency", "poland"), group="residency", kind="always",
         level="ask", patterns=[r"(?:work|working)\s+from\s+anywhere\s+in\s+Poland", r"(?:remote|fully remote)\s+(?:in|within|from)\s+Poland"]),
    dict(id="ukraine_only", label="Only residents of Ukraine", label_uk="Тільки з України", needs=("residency", "ukraine"), group="residency", kind="always", patterns=[
        r"only\s+(?:candidates?\s+|applicants?\s+)?(?:from|in|based in|living in|residing in)\s+Ukraine",
        r"Ukraine[- ]only", r"Ukraine[- ]based\s+(?:candidates?|only|required)",
        _FRAME + r"[^.\n]{0,50}(?:based|located|resid\w+|living|live|reside)\s+(?:in|within)\s+Ukraine",
        r"(?:лише|тільки|виключно)\s+(?:кандидат\w*\s+|для кандидатів\s+)?(?:з|із|в|у)\s+Україн",
        r"кандидат\w*\s+(?:лише|тільки|виключно)\s+(?:з|із)\s+Україн",
        r"резидент\w*\s+Україн", r"проживаєте?\s+(?:в|на території)\s+Україн"]),
    dict(id="eu_citizens", label="EU citizens only", label_uk="Тільки громадяни ЄС", needs=("eu_citizen",), group="residency", kind="always", patterns=[
        r"EU\s+(?:citizens?|citizenship|passport)\s+(?:only|required|is required|mandatory)",
        r"(?:only|must be)\s+(?:an?\s+)?(?:EU|European)\s+(?:citizens?|nationals?)",
        r"citizens?\s+of\s+(?:the\s+)?(?:EU|European Union|EEA)\s+(?:only|required)",
        r"громадянств\w+\s+(?:ЄС|країн ЄС)"]),
    dict(id="eu_work_right", label="Right to work in the EU required (check your status)", label_uk="«Право на роботу в ЄС» (перевір: у тебе тимчасовий захист у Болгарії)", needs=("eu_right",), group="residency", kind="always",
         level="ask", patterns=[r"(?:right|authori[sz]ed?|eligible)\s+to\s+work\s+in\s+the\s+(?:EU|European Union|EEA)",
                                r"valid\s+(?:EU\s+)?work\s+(?:permit|authori[sz]ation)"]),
    dict(id="other_country", label="Only residents of another country, or work authorisation elsewhere", label_uk="Тільки резиденти іншої країни / США", needs=("residency", None), group="residency", kind="always", patterns=[
        _FRAME + r"[^.\n]{0,50}(?:based|located|resid\w+|living|live|reside)\s+(?:in|within)\s+(?:the\s+)?(?:" + _COUNTRIES + r")\b",
        r"(?:authori[sz]ed|eligible|right|legally)\s+to\s+work\s+in\s+the\s+(?:US|USA|U\.S\.|United States|UK|United Kingdom|Canada)",
        r"(?:US|U\.S\.)\s+(?:citizens?|work authori[sz]ation|persons?)",
        r"security\s+clearance"]),
    dict(id="country_anywhere", label="Remote only within one country (check whether they accept your country)", label_uk="Віддалено лише в межах однієї країни (перевір, чи приймають з твоєї)",
         needs=("residency", None), group="residency", kind="always", level="ask", patterns=[
        r"(?:work|working)\s+from\s+anywhere\s+in\s+(?:the\s+)?(?:" + _COUNTRIES + r")\b",
        r"(?:remote|fully remote)\s+(?:in|within)\s+(?:the\s+)?(?:" + _COUNTRIES + r")\b"]),
    # ---- G1: relocation (answer 13.10: office only in Sofia; do not count on paid relocation)
    dict(id="relocation_required", label="Relocation required", label_uk="Потрібен переїзд / релокація", needs=("always",), group="reloc", kind="always", patterns=[
        r"(?:must|required|willing|ready|able|need)\s+(?:to\s+)?relocat\w+", r"relocation\s+(?:is\s+)?(?:required|mandatory|necessary|expected)",
        r"(?:необхідн\w+|обов.?язков\w+)\s+переїзд", r"готов\w+\s+до\s+переїзду"]),
    dict(id="relocation_offered", label="Relocation offered (company perk)", label_uk="Пропонують релокацію (перк компанії)", needs=("always",), group="reloc", kind="always", level="note",
         patterns=[r"relocation\s+(?:package|assistance|support|bonus|allowance|budget)", r"допомога\s+з\s+переїздом"]),
    dict(id="office_not_sofia", label="Office or hybrid outside your home place", label_uk="Офіс / гібрид не в Софії", needs=("office",), group="office", kind="office", patterns=[
        r"\bhybrid\b", r"\bon[- ]?site\b", r"\bin[- ]office\b", r"\boffice[- ]based\b",
        r"\d(?:\s*[-–]\s*\d)?\s+days?\s+(?:a|per|each|in|at)?\s*(?:week\s+)?(?:in|at|from)\s+(?:the\s+)?office",
        r"гібрид\w*", r"\d(?:\s*[-–]\s*\d)?\s+дн\w+\s+(?:на тиждень\s+)?(?:в|у|з)\s+офіс\w*",
        r"hybrydow\w+", r"\d\s+dni\s+w\s+biurze", r"\bvor\s+Ort\b" ]),
    # ---- G1: languages (answer 13.10: Polish / German = wall; others from own scan prompt)
    dict(id="lang_polish", label="Polish required", label_uk="Потрібна польська", needs=("language", "polish"), group="lang", kind="ctx", default="wall", patterns=[
        r"(?:fluent|proficien\w*|advanced|native|business|working|good|strong|excellent|professional|communicative|conversational)\s+(?:level\s+of\s+)?(?:in\s+)?Polish",
        r"Polish\s+(?:language\s+)?(?:\(|at\s+|level\s+|[-–:]\s*)?(?:B2|C1|C2|fluent|proficien\w*|native|advanced)",
        r"Polish\s+(?:language\s+)?(?:is\s+)?(?:required|mandatory|a must|must)",
        r"(?:knowledge|command)\s+of\s+(?:the\s+)?Polish", r"Polish\s+(?:language\s+)?(?:skills|speaker)",
        r"(?:wolny|biegł\w*|komunikatywn\w*|bardzo dobr\w*)\s+(?:znajomość\s+)?(?:język\w*\s+)?polski\w*",
        r"znajomo[sś][cć]\s+j[eę]zyka\s+polskiego", r"j[eę]zyk\s+polski",
        r"знання\s+польськ\w+", r"польськ\w+\s+мов\w+", r"польськ\w+\s+(?:на\s+рівні|B2|C1)"]),
    dict(id="lang_german", label="German required", label_uk="Потрібна німецька", needs=("language", "german"), group="lang2", kind="ctx", default="wall", patterns=[
        r"(?:fluent|proficien\w*|advanced|native|business|working|good|strong|excellent|professional|conversational)\s+(?:level\s+of\s+)?(?:in\s+)?German",
        r"German\s+(?:language\s+)?(?:\(|at\s+|level\s+|[-–:]\s*)?(?:B2|C1|C2|fluent|proficien\w*|native|advanced)",
        r"German\s+(?:language\s+)?(?:is\s+)?(?:required|mandatory|a must|must)", r"German\s+(?:speaker|speaking)\b",
        r"(?:knowledge|command)\s+of\s+(?:the\s+)?German", r"Deutsch(?:kenntnisse|\s+(?:fließend|verhandlungssicher|auf\s+C\d))",
        r"verhandlungssicher\w*\s+Deutsch", r"flie[sß]end\w*\s+Deutsch",
        r"знання\s+німецьк\w+", r"німецьк\w+\s+мов\w+", r"німецьк\w+\s+(?:на\s+рівні|B2|C1)"]),
    dict(id="lang_other", label="Another language required (Bulgarian, Czech, Greek, French, Ukrainian...)", label_uk="Потрібна інша мова (болгарська, чеська, грецька, французька тощо)", needs=("language", None), group="lang3", kind="ctx", default="wall", patterns=[
        r"(?:fluent|proficien\w*|advanced|native|business|working|excellent|professional)\s+(?:level\s+of\s+)?(?:in\s+)?(?:French|Dutch|Spanish|Italian|Portuguese|Czech|Slovak|Hungarian|Romanian|Swedish|Danish|Norwegian|Finnish|Bulgarian|Greek|Turkish|Arabic|Hebrew|Japanese|Chinese|Korean|Ukrainian|Russian)",
        r"(?:French|Dutch|Spanish|Italian|Portuguese|Czech|Slovak|Hungarian|Romanian|Swedish|Danish|Norwegian|Finnish|Bulgarian|Greek|Turkish|Arabic|Hebrew|Ukrainian|Russian)\s+(?:language\s+)?(?:\(|at\s+|level\s+|[-–:]\s*)?(?:B2|C1|C2|fluent|proficien\w*|native|advanced)",
        r"(?:French|Dutch|Spanish|Italian|Portuguese|Czech|Slovak|Hungarian|Romanian|Bulgarian|Greek|Ukrainian|Russian)\s+(?:language\s+)?(?:is\s+)?(?:required|mandatory|a must)",
        r"(?:владеене|знание)\s+на\s+(?:български|чешки|гръцки)", r"български\s+език",
        r"знання\s+(?:болгарськ|чеськ|грецьк|французьк)\w+"]),
    # ---- G1: certificates (answer 13.10: wall when required)
    dict(id="cert_pmp", label="PMP certificate required", label_uk="Потрібен сертифікат PMP", needs=("cert", "pmp"), group="cert", kind="ctx", default="ask", patterns=[r"(?-i:\bPMP\b)", r"Project Management Professional"]),
    dict(id="cert_other", label="Certificate required (PRINCE2 / PM2 / AgilePM / Scrum ...)", label_uk="Потрібен сертифікат (PRINCE2 / SAFe / PM2 / AgilePM / Scrum тощо)", needs=("cert", "pm_certificates"), group="cert", kind="ctx", default="ask",
         wall_needs=r"certif\w*|сертифік\w*|practitioner|foundation|exam|licen[cs]e|certyfikat\w*|zertifi\w*|obligatoryjn\w*|accredit\w*",
         patterns=[r"PRINCE\s?2", r"(?-i:\bPM2\b)", r"AgilePM", r"IPMA", r"PMI-ACP", r"(?-i:\bCAPM\b)",
                   r"(?:Scrum|Agile|PM|PMI|project management|Kanban|SAFe)\s+(?:certif\w+|certificate)",
                   r"certified\s+(?:Scrum|project manager|agile|SAFe)", r"сертифікат\w*\s+(?:Scrum|Agile|PMP|PRINCE|PMI)"]),
    dict(id="cert_agile", label="Agile certificate (SAFe / CSM / PSM)", label_uk="Потрібен Agile-сертифікат (SAFe / CSM / PSM)", needs=("cert", "agile_certificates"), group="cert", kind="ctx", default="note", weak="note",
         wall_needs=r"certif\w*|сертифік\w*|practitioner|exam|licen[cs]e|certyfikat\w*|zertifi\w*|obligatoryjn\w*|accredit\w*",
         patterns=[r"(?-i:\bPSM\s?I{1,3}\b)", r"(?-i:\bCSM\b)", r"(?-i:\bSAFe\b)", r"(?-i:\bPSPO\b)", r"(?-i:\bCSPO\b)"]),
    # ---- G2: domains (answer 13.10: wall when required)
    dict(id="dom_pharma", label="Domain: pharma / GxP / healthcare", label_uk="Домен pharma / GxP / медицина", needs=("domain", "pharma"), group="dom_pharma", kind="ctx", default="note", patterns=[
        r"pharma\w*", r"(?-i:\bGxP\b|\bGMP\b)", r"\bFDA\b", r"21\s*CFR", r"clinical\s+(?:trial|stud|research|data)\w*",
        r"life[- ]sciences?", r"(?-i:\bEHR\b|\bEMR\b|\bHL7\b|\bDICOM\b)", r"\bFHIR\b", r"medical\s+devices?", r"healthcare\s+(?:software|IT|domain|industry)",
        r"фармацевт\w+", r"біофарм\w*", r"clinical\s+operations"]),
    dict(id="dom_itsm", label="Domain: ServiceNow / ITSM / CMDB", label_uk="Домен ServiceNow / ITSM / CMDB", needs=("domain", "itsm"), group="dom_itsm", kind="ctx", default="note", patterns=[
        r"ServiceNow", r"(?-i:\bITSM\b|\bCMDB\b|\bITOM\b|\bITIL\b)", r"BMC\s+Remedy", r"IT\s+service\s+management"]),
    dict(id="dom_erp", label="Domain: SAP / Oracle ERP / Salesforce", label_uk="Домен SAP / Oracle ERP / Salesforce", needs=("domain", "erp"), group="dom_erp", kind="ctx", default="note", patterns=[
        r"(?-i:\bSAP\b)", r"Oracle\s+(?:ERP|EBS|E-Business|Fusion|Cloud ERP|NetSuite)", r"Salesforce", r"Dynamics\s*(?:365|AX|NAV|CRM)",
        r"NetSuite", r"ERP\s+(?:implement\w+|project|system|roll-?out)", r"впровадження\s+ERP"]),
    dict(id="dom_infra", label="Domain: infrastructure / cloud migration / Power BI / Synapse", label_uk="Домен інфраструктура / хмарна міграція / Power BI / Synapse", needs=("domain", "infra"), group="dom_infra", kind="ctx", default="note", patterns=[
        r"data\s?cent(?:er|re)s?", r"cloud\s+migrations?", r"migrat\w+\s+to\s+(?:the\s+)?(?:cloud|Azure|AWS|GCP)", r"lift[- ]and[- ]shift",
        r"infrastructure\s+(?:project|migration|transformation|delivery|program)\w*", r"(?-i:\bEUC\b)", r"network(?:ing)?\s+infrastructure",
        r"Power\s?BI", r"Synapse", r"server\s+(?:migration|infrastructure)", r"інфраструктурн\w+\s+проєкт\w*"]),
    dict(id="dom_bank", label="Domain: banking experience", label_uk="Домен банкінг (досвід у банках)", needs=("domain", "banking"), group="dom_bank", kind="ctx", default="note", patterns=[
        r"(?:experience|background|knowledge|years)[^.\n]{0,40}(?:in|of|within)\s+(?:the\s+)?(?:banking|bank|financial institutions?|capital markets)\b",
        r"banking\s+(?:domain|sector|industry)\s+(?:experience|knowledge)", r"досвід[^.\n]{0,30}(?:банківськ\w+|в банк\w*)"]),
    dict(id="dom_gov", label="Domain: GovTech / public sector", label_uk="Домен GovTech / державні проєкти", needs=("domain", "govtech"), group="dom_gov", kind="ctx", default="note", patterns=[
        r"GovTech", r"public[- ]sector", r"government(?:al)?\s+(?:projects?|clients?|agenc\w+|sector)", r"державн\w+\s+(?:проєкт\w*|сектор\w*|замовник\w*)"]),
    # ---- Russia ties inside the text (company ties, not language) - only a question
    dict(id="russia_ties", label="Ties to Russia in the text (check)", label_uk="Зв'язки з росією в тексті (перевір)", needs=("avoid", "russia"), group="russia", kind="always", level="ask", patterns=[
        r"\b(?:Moscow|Saint[- ]Petersburg|St\.?\s+Petersburg|Russian Federation)\b", r"offices?\s+in\s+Russia", r"clients?\s+in\s+Russia",
        r"Москв\w+", r"Санкт-Петербург\w*", r"Російськ\w+\s+Федерац\w+", r"российск\w+\s+рынк\w+"]),
]

for _r in RULES:
    _r["rx"] = [re.compile(p, re.I) for p in _r["patterns"]]
