"""
jd_screen.py - reads the BODY of a job ad and says: wall / ask / ok (Stage A, 13.10.2026).

Plain code, no AI, no network. Rules live in jd_rules.py.
  screen(text) -> {"verdict": "wall"|"ask"|"ok"|"nojd", "hits": [{id,label,level,quote}], "chars": N, "ad_lang": ""}
  why(result)  -> one Ukrainian line for the tracker card
Python 3.9 compatible, no extra dependencies.
"""
from __future__ import annotations

import html as H
import re

import jd_rules as R

MIN_CHARS = 250          # shorter text = we did not really get the ad
MAX_STORE = 12000        # what we keep in the tracker `jd` field
_LEVEL_RANK = {"note": 1, "ask": 2, "wall": 3}


def clean_text(raw: str) -> str:
    """HTML or plain text -> readable text with one line per paragraph / bullet."""
    if not raw:
        return ""
    s = raw
    if "&lt;" in s and "<" not in s:          # escaped HTML (Greenhouse `content`)
        s = H.unescape(s)
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|h[1-6]|tr|ul|ol|section|article|table)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n• ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = H.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" ?\n ?", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _units(text: str) -> list:
    """[(sentence_or_bullet, section)] where section is must / soft / other (from the nearest heading)."""
    section, out = "other", []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        bullet = line[0] in "•-*–" and (len(line) == 1 or line[1] in " \t") or line.startswith("•")
        body = line.lstrip("•-*– \t").strip()
        if not body:
            continue
        if not bullet and len(line) <= 70:
            head = body.rstrip(":").strip()
            if R.SOFT_HEADING.match(head):
                section = "soft"
                continue
            if R.MUST_HEADING.match(head) and (line.endswith(":") or len(head) <= 40):
                section = "must"
                continue
            if R.OTHER_HEADING.match(head) and (line.endswith(":") or len(head) <= 40):
                section = "other"
                continue
        if len(body) < 140 and _LISTING.search(body):
            continue                                   # another vacancy from the page sidebar
        parts = re.split(r";\s+|\s+[·•]\s+", body)             # list items glued together with ; or ·
        if len(body) > 180:
            parts = [x for part in parts
                     for x in re.split(r"(?<=[.!?])\s+(?=[A-ZА-ЯІЇЄҐĄĆĘŁŃÓŚŹŻÄÖÜ•])", part)]
        line_sec = section
        if parts and ":" in parts[0][:45]:               # "Nice: a; b; c" -> the label covers the whole line
            lead = parts[0].split(":", 1)[0]
            if R.SOFT.search(lead + ":") or R.SOFT_HEADING.match(lead):
                line_sec = "soft"
            elif R.MUST_HEADING.match(lead) or R.MUST.search(lead):
                line_sec = "must"
        for part in parts:
            part = part.strip()
            if part:
                out.append((part, line_sec))
    return out


def _quote(unit: str, m) -> str:
    if len(unit) <= 220:
        return unit
    start = max(0, m.start() - 90)
    end = min(len(unit), m.end() + 110)
    return ("…" if start else "") + unit[start:end].strip() + ("…" if end < len(unit) else "")


_ALT = re.compile(r"\b(?:or|або)\s+(?:similar|equivalent|comparable|other|аналогічн\w*|подібн\w*)", re.I)
# a line of a "similar vacancies" list copied from a job-board page: "Title в Company , Київ" / "Title (German Speaking) New"
_LISTING = re.compile(r"\s(?:в|at)\s+[^,\n]{2,45}\s?,\s?(?:Київ|Львів|Дніпро|Харків|Одеса|Варшава|Софія|віддалено|Remote|за кордоном)|\s(?:New|Нова)$")
_RELATED = re.compile(r"^(?:Гарячі[^\n]{0,40}вакансії|Hot jobs|Схожі вакансії|Подібні вакансії|Інші вакансії|Рекомендовані вакансії|Вакансії компанії|Більше вакансій|"
                      r"Similar (?:jobs|vacancies)|Related (?:jobs|vacancies)|Other (?:jobs|vacancies|openings)|You may also like|"
                      r"More jobs|Popular jobs)\b", re.I | re.M)


def _in_parens(unit: str, pos: int) -> bool:
    return unit.count("(", 0, pos) > unit.count(")", 0, pos)


def strip_related(text: str) -> str:
    """Cut the page text where the list of OTHER vacancies starts (board pages)."""
    m = _RELATED.search(text, 400)
    return text[:m.start()] if m else text


def _level(rule: dict, unit: str, section: str, m=None):
    """wall / ask / note / None for one pattern match inside one sentence."""
    if R.NEGATE.search(unit):
        return None
    soft = bool(R.SOFT.search(unit)) or (section == "soft" and not R.MUST.search(unit))
    kind = rule["kind"]
    if kind == "always":
        return "note" if soft else rule.get("level", "wall")
    # ctx
    if soft:
        return "note"
    if m is not None and _in_parens(unit, m.start()):
        return "note"                                  # "(Looker, Tableau, Power BI)" = examples
    if R.MUST.search(unit) or section == "must":
        need = rule.get("wall_needs")
        if need and not re.search(need, unit, re.I):
            return rule.get("weak", "ask")
        if rule["id"].startswith("cert") and _ALT.search(unit):
            return "ask"                               # "PMP, PRINCE2 or similar" - an alternative list
        return "wall"
    return rule.get("default", "ask")


_PL = {"i", "w", "z", "na", "do", "jest", "oraz", "się", "dla", "będzie", "nie", "jako", "przez", "lub", "naszym",
       "oferujemy", "wymagania", "doświadczenie", "praca", "zespole", "firmy", "projektów", "naszej", "aplikuj"}
_DE = {"und", "der", "die", "das", "wir", "sie", "mit", "für", "ihre", "aufgaben", "erfahrung", "bieten", "ist",
       "sind", "unser", "unsere", "bei", "auf", "eine", "einen"}


def ad_language(text: str) -> str:
    """'pl' / 'de' when the ad itself is written in Polish / German, else ''."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 60:
        return ""
    n = float(len(words))
    pl = sum(1 for w in words if w in _PL) / n
    de = sum(1 for w in words if w in _DE) / n
    pl_chars = len(re.findall(r"[ąęłńśźż]", text.lower())) / max(1.0, len(text))
    if pl > 0.07 and pl_chars > 0.012:
        return "pl"
    if de > 0.10:
        return "de"
    return ""


def screen(raw: str, already_clean: bool = False) -> dict:
    text = raw if already_clean else clean_text(raw)
    text = strip_related(text)
    res = {"verdict": "nojd", "hits": [], "chars": len(text), "ad_lang": ""}
    if len(text) < MIN_CHARS:
        return res
    units = _units(text)
    has_sofia = bool(R.SOFIA.search(text))
    has_remote = bool(R.REMOTE.search(text))
    best = {}                                   # group -> hit (strongest level, first quote)
    for rule in R.RULES:
        for ui, (unit, section) in enumerate(units):
            for rx in rule["rx"]:
                m = rx.search(unit)
                if not m:
                    continue
                if rule["kind"] == "office":
                    if re.search(r"\b(travel\w*|trips?|meetings?|visits?|events?|training|content|seo)\b|відрядж|зустріч", unit, re.I):
                        continue          # "onsite meetings", "on-site content" are not an office requirement
                    if re.search(r"\b(cooperation|collaboration|flexible|flexibility|schedule|working hours|work-life)\b|гнучк|графік", unit, re.I):
                        continue          # "Hybrid type of cooperation" in a perk list = flexible schedule, not an office
                    if len(unit) < 70 and not re.search(r"\b(office|офіс|\d)", unit, re.I) and re.search(
                            r"\b(flexible|working hours|schedule|work-life)\b|гнучк|графік",
                            " ".join(u for u, _ in units[max(0, ui - 3):ui + 4]), re.I):
                        continue          # short perk line next to flexible-schedule lines
                    if re.search(r"\b(agile|waterfall|scrum|kanban|methodolog\w*|pmbok|approach(es)?|framework|nearshore|offshore|delivery models?)\b", unit, re.I):
                        continue          # "Agile, Waterfall, Hybrid" is a method, not an office
                    if R.NEGATE.search(unit) or re.search(r"\b(fully remote|100% remote|remote[- ]first|optional|occasional\w*|"
                                                           r"from time to time|meet-?ups?|team events?|retreats?|за бажанням|"
                                                           r"не обов.?язков\w+)\b", unit, re.I):
                        continue
                    if R.REMOTE.search(unit) and not re.search(r"\d\s*(?:[-–]\s*\d\s*)?(?:days?|дн|dni)", unit, re.I):
                        continue          # "remote, hybrid or office" = a choice
                    level = "note" if has_sofia else ("ask" if has_remote else "wall")
                else:
                    level = _level(rule, unit, section, m)
                if level is None:
                    continue
                hit = {"id": rule["id"], "label": rule["label"], "level": level, "quote": _quote(unit, m)}
                old = best.get(rule["group"])
                if old is None or _LEVEL_RANK[level] > _LEVEL_RANK[old["level"]]:
                    best[rule["group"]] = hit
                break                           # one pattern per sentence is enough
    lang = ad_language(text)
    res["ad_lang"] = lang
    if lang == "pl":
        best["adlang"] = {"id": "ad_polish", "label": "Оголошення написане польською (мова роботи майже завжди польська)",
                          "level": "ask", "quote": text[:140].replace("\n", " ")}
    elif lang == "de":
        best["adlang"] = {"id": "ad_german", "label": "Оголошення написане німецькою (мова роботи майже завжди німецька)",
                          "level": "ask", "quote": text[:140].replace("\n", " ")}
    hits = sorted(best.values(), key=lambda h: -_LEVEL_RANK[h["level"]])
    res["hits"] = hits
    levels = {h["level"] for h in hits}
    res["verdict"] = "wall" if "wall" in levels else ("ask" if "ask" in levels else "ok")
    return res


def why(res: dict, max_items: int = 3) -> str:
    """One short Ukrainian line for the card note."""
    if res["verdict"] == "nojd":
        return "Опис не завантажено: відкрий сторінку й прочитай сам."
    items = [h for h in res["hits"] if h["level"] in ("wall", "ask")][:max_items]
    if not items:
        return ""
    tag = {"wall": "Стіна", "ask": "Перевір"}
    return "; ".join("%s: %s — «%s»" % (tag[h["level"]], h["label"], h["quote"][:160]) for h in items)
