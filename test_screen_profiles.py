"""One ad, read once, judged for different people (extract_signals + match)."""
import testsupport  # noqa: F401

import copy
import json
import unittest
from pathlib import Path

import jd_screen as S
import search_profile as sp

HERE = Path(__file__).parent
AUTHOR = HERE / "profiles" / "example_eu_remote_pm.json"
POLAND = HERE / "profiles" / "example_pl_python_dev.json"
PAD = " We build software for clients across Europe and value clear communication and ownership of results. " * 3


def cfg_of(path_or_dict, **bg):
    if isinstance(path_or_dict, dict):
        p = copy.deepcopy(path_or_dict)
    else:
        p = json.loads(Path(path_or_dict).read_text(encoding="utf-8"))
    p.setdefault("background", {}).update(bg)
    sp.use(p)
    c = sp.compiled()
    sp.use(AUTHOR)
    return c


def verdict(text, cfg):
    return S.match(S.extract_signals(text), cfg)


class OneAdManyPeople(unittest.TestCase):
    def setUp(self):
        self.author = cfg_of(AUTHOR)
        self.pole = cfg_of(POLAND)

    def tearDown(self):
        sp.use(AUTHOR)

    def both(self, text):
        ex = S.extract_signals(text)
        return S.match(ex, self.author), S.match(ex, self.pole), ex

    def test_residency_in_the_persons_own_country_is_fine(self):
        a, p, _ = self.both("Technical Product Manager. Requirements:\n• Candidates must be based in Poland\n" + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("wall", "ok"))

    def test_residency_elsewhere_blocks(self):
        a, p, _ = self.both("Requirements:\n• You must be based in Germany\n" + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("wall", "wall"))

    def test_language_the_person_speaks_is_fine(self):
        a, p, _ = self.both("Requirements:\n• Fluent Polish and English\n" + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("wall", "ok"))
        a, p, _ = self.both("Requirements:\n• Verhandlungssicheres Deutsch und Englisch\n" + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("wall", "wall"))

    def test_ukrainian_is_a_language_to_check_for_a_pole_but_not_for_the_author(self):
        a, p, _ = self.both("Requirements:\n• Fluent Ukrainian is required\n" + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("ok", "wall"))

    def test_domain_and_certificate_follow_the_background(self):
        a, p, _ = self.both("Requirements:\n• Strong SAP experience\n" + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("wall", "ok"))       # the Pole listed erp
        pmp = cfg_of(AUTHOR, certificates=["pmp"])
        ex = S.extract_signals("Requirements:\n• PMP certification\n" + PAD)
        self.assertEqual(S.match(ex, self.author)["verdict"], "wall")
        self.assertEqual(S.match(ex, pmp)["verdict"], "ok")

    def test_eu_citizenship(self):
        a, p, _ = self.both("Project Manager. Only EU citizens can apply for this position. " + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("wall", "ok"))

    def test_office_is_fine_when_the_ad_names_the_home_place(self):
        a, p, _ = self.both("Hybrid model: 3 days per week in our Warsaw office. " + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("wall", "ok"))
        a, p, _ = self.both("Hybrid model: 2 days per week in our Sofia office. " + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("ok", "wall"))

    def test_russia_ties_only_for_people_who_ask_for_it(self):
        a, p, _ = self.both("We have offices in Moscow and Warsaw. Fully remote PM wanted. " + PAD)
        self.assertEqual((a["verdict"], p["verdict"]), ("ask", "ok"))

    def test_ad_written_in_the_persons_own_language(self):
        polish_ad = ("Szukamy doświadczonego kierownika projektu do pracy w naszym zespole. Oferujemy pracę w dobrej atmosferze oraz "
                     "stabilne zatrudnienie dla osób z doświadczeniem w projektach IT. Wymagania: doświadczenie w zarządzaniu zespołem, "
                     "znajomość metodyk zwinnych, praca w zespole firmy i dla naszej klienta. Aplikuj już dziś i dołącz do zespołu, "
                     "który jest nastawiony na wynik, jakość oraz rozwój. Nasza firma jest liderem rynku, a praca jest zdalna dla "
                     "wszystkich członków zespołu projektowego, którzy chcą się rozwijać.")
        a, p, _ = self.both(polish_ad)
        self.assertEqual(a["verdict"], "ask")
        self.assertNotIn("ad_polish", [h["id"] for h in p["hits"]])

    def test_extraction_is_reusable_and_not_changed_by_matching(self):
        ex = S.extract_signals("Requirements:\n• Fluent Polish\n• SAP experience\n" + PAD)
        before = json.dumps(ex, sort_keys=True)
        S.match(ex, self.author)
        S.match(ex, self.pole)
        self.assertEqual(json.dumps(ex, sort_keys=True), before)

    def test_output_language_follows_the_profile(self):
        uk = cfg_of(AUTHOR)
        sp.use(dict(json.loads(AUTHOR.read_text(encoding="utf-8")), ui_language="uk"))
        ukc = sp.compiled()
        ex = S.extract_signals("Requirements:\n• Fluent Polish and English\n" + PAD)
        r_uk = S.match(ex, ukc)
        r_en = S.match(ex, self.author)
        self.assertIn("польськ", r_uk["hits"][0]["label"])
        self.assertIn("Polish", r_en["hits"][0]["label"])
        self.assertTrue(S.why(r_uk, lang="uk").startswith("Стіна"))
        self.assertTrue(S.why(r_en, lang="en").startswith("Wall"))


if __name__ == "__main__":
    unittest.main()
