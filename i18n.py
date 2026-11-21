"""
i18n.py - the few texts the tools show to the user, in English and Ukrainian. Standard library only.

The language is the profile's ui_language ("en" by default). Tools that run without a profile fall back to English.
"""
from __future__ import annotations

STR = {
    "board.company_site": {"en": "company site ({name})", "uk": "сайт компанії ({name})"},

    "signals.no_company": {"en": "(see the article)", "uk": "(див. новину)"},
    "signals.title": {"en": "# Signals: who just received funding ({today})", "uk": "# Сигнали: хто отримав гроші ({today})"},
    "signals.header": {"en": "| Company | Amount, M EUR | Round | Country | Sectors | Priority | Article |",
                       "uk": "| Компанія | Сума, млн € | Раунд | Країна | Сфери | Пріоритет | Новина |"},
    "signals.grant": {"en": "grant", "uk": "грант"},
    "signals.premium": {"en": "premium", "uk": "€200/год"},
    "signals.watch": {"en": " watch", "uk": " спостереження"},

    "jd.review.wall": {"en": "Auto-skip (wall)", "uk": "Авто-skip (стіна)"},
    "jd.review.ask": {"en": "Check by hand", "uk": "Перевір сам"},
    "jd.review.nojd": {"en": "Text not loaded", "uk": "Текст не завантажено"},
    "jd.tag.wall": {"en": "wall", "uk": "стіна"},
    "jd.tag.ask": {"en": "check", "uk": "перевір"},

    "sc.greenhouse_other": {"en": "the Greenhouse board belongs to another company ('{board}')", "uk": "Greenhouse-борд належить іншій компанії ('{board}')"},
    "sc.check_board": {"en": "check by hand: the board name is not confirmed", "uk": "перевір вручну: назву борду не підтверджено"},
    "sc.check_first_word": {"en": "check by hand: matched on the first word of the name only", "uk": "перевір вручну: збіг лише за першим словом назви"},
    "sc.added": {"en": "added to the scan", "uk": "додано в сканування"},
    "sc.need_adapter": {"en": "needs an adapter for {ats}", "uk": "потрібен адаптер для {ats}"},
    "sc.own_site": {"en": "own career site: needs an adapter ({host})", "uk": "свій сайт: потрібен адаптер ({host})"},
    "sc.not_probed": {"en": "ATS not checked yet (run without --no-probe)", "uk": "ATS ще не перевірено (запусти без --no-probe)"},
    "sc.not_found": {"en": "no ATS found: find the careers page by hand", "uk": "ATS не знайдено: знайди сторінку вакансій вручну"},
    "sc.status.interview": {"en": "interview", "uk": "співбесіда"}, "sc.status.talk": {"en": "talk", "uk": "розмова"},
    "sc.status.offer": {"en": "offer", "uk": "оффер"}, "sc.status.applied": {"en": "applied", "uk": "подано"},
    "sc.status.rejected": {"en": "rejected", "uk": "відмова"}, "sc.status.todo": {"en": "queued", "uk": "у черзі"},
    "sc.status.closed": {"en": "closed", "uk": "закрита"}, "sc.status.skip": {"en": "skipped", "uk": "пропущено"},
    "sc.roles": {"en": "roles {n}", "uk": "ролей {n}"},
    "sc.fresh": {"en": "recent", "uk": "свіжа"},
}


def lang() -> str:
    try:
        import search_profile
        return search_profile.compiled().ui_language
    except Exception:
        return "en"


def t(key: str, **kw) -> str:
    entry = STR[key]
    text = entry.get(lang()) or entry["en"]
    return text.format(**kw) if kw else text


def all_forms(key: str) -> set:
    """Every language version of a text (for comparing against stored data written in either language)."""
    return set(STR[key].values())
