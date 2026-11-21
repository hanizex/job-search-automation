"""Job-board searches follow the profile: DOU terms, Djinni keywords, which boards are read."""
import testsupport  # noqa: F401

import unittest
import urllib.parse
from pathlib import Path

import boards
import search_profile as sp
import sources

HERE = Path(__file__).parent
AUTHOR = HERE / "profiles" / "example_eu_remote_pm.json"
POLAND = HERE / "profiles" / "example_pl_python_dev.json"


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class Catalogue(unittest.TestCase):
    def test_every_role_rule_uses_known_djinni_keywords_and_dou_terms(self):
        cat = sources.catalogue()
        for rule in cat["role_map"]:
            for k in rule["djinni"]:
                self.assertIn(k, cat["djinni_keywords"], rule)
            for t in rule["dou"]:
                self.assertTrue(t, rule)

    def test_suggest_maps_titles_and_keeps_unknown_titles_for_dou_only(self):
        s = sources.suggest(["Python Developer", "Backend Engineer", "Product Owner"])
        self.assertEqual(s["djinni"], ["Python", "Product Manager", "Product Owner"])
        self.assertIn("Python", s["dou"])
        self.assertIn("Backend Engineer", s["dou"])
        self.assertEqual(s["unmatched"], ["Backend Engineer"])

    def test_short_tokens_do_not_match_inside_words(self):
        s = sources.suggest(["guide builder"])       # contains "ui" inside words, must not become Design
        self.assertEqual(s["unmatched"], ["guide builder"])


class ProfileSources(unittest.TestCase):
    def tearDown(self):
        sp.use(AUTHOR)

    def test_author_profile_keeps_its_explicit_searches(self):
        sp.use(AUTHOR)
        urls = boards.dou_feeds()
        self.assertEqual(urls, ["https://jobs.dou.ua/vacancies/feeds/?category=Project%20Manager",
                                "https://jobs.dou.ua/vacancies/feeds/?category=Product%20Manager"])
        self.assertIn("https://djinni.co/jobs/?primary_keyword=Delivery+Manager", boards.djinni_lists())

    def test_derived_searches_for_another_role(self):
        sp.use(POLAND)
        terms = [urllib.parse.unquote(u.split("category=")[1]) for u in boards.dou_feeds()]
        self.assertIn("Python", terms)
        self.assertEqual(boards.djinni_lists(), ["https://djinni.co/jobs/?primary_keyword=Python"])

    def test_unknown_djinni_keyword_is_rejected(self):
        with self.assertRaises(sp.ProfileError) as cm:
            sp.normalise({"version": 1, "roles": {"titles": ["x"]}, "location": {"home_country": "poland"},
                          "sources": {"djinni": ["Python Developer"]}})
        self.assertIn("not a Djinni keyword", str(cm.exception))

    def test_unknown_board_is_rejected_and_keyword_case_is_fixed(self):
        with self.assertRaises(sp.ProfileError):
            sp.normalise({"version": 1, "roles": {"titles": ["x"]}, "location": {"home_country": "poland"},
                          "sources": {"boards": ["monster"]}})
        p = sp.normalise({"version": 1, "roles": {"titles": ["x"]}, "location": {"home_country": "poland"},
                          "sources": {"djinni": ["python", "QA AUTOMATION"]}})
        self.assertEqual(p["sources"]["djinni"], ["Python", "QA Automation"])

    def test_only_the_boards_in_the_profile_are_read(self):
        calls = []
        real = [(n, k, f) for n, k, f in boards.BOARD_FETCHERS]
        try:
            boards.BOARD_FETCHERS = tuple((n, k, (lambda log, k=k: calls.append(k) or [])) for n, k, f in real)
            sp.use(POLAND)
            boards.fetch_all(lambda m: None)
            self.assertEqual(calls, ["dou", "djinni"])
        finally:
            boards.BOARD_FETCHERS = tuple(real)


class OfflineFetch(unittest.TestCase):
    """The real fetch code on saved pages: no network."""

    def setUp(self):
        sp.use(POLAND)
        self.dou = (HERE / "fixtures" / "dou_sample.xml").read_text(encoding="utf-8")
        self.djinni = (HERE / "fixtures" / "djinni_sample.html").read_text(encoding="utf-8")
        self.urls = []
        self._get = boards._get
        self._sleep = boards.time.sleep

    def tearDown(self):
        boards._get = self._get
        sp.use(AUTHOR)

    def fake_get(self, url):
        self.urls.append(url)
        if "dou.ua" in url:
            return Resp(self.dou)
        return Resp(self.djinni if "page=" not in url else "<html></html>")

    def test_dou_feed_is_parsed_and_duplicates_across_feeds_are_dropped(self):
        boards._get = self.fake_get
        rows = boards.fetch_dou(lambda m: None)
        titles = sorted(r["title"] for r in rows)
        self.assertEqual(titles, ["Middle Python Developer", "Senior Backend Engineer"])
        self.assertTrue(all(r["source_board"] == "DOU" for r in rows))
        self.assertGreater(len(self.urls), 1)               # several terms were requested
        self.assertEqual(len(rows), 2)                      # each posting appears once, not once per term

    def test_djinni_list_is_parsed_and_pagination_stops_when_nothing_is_new(self):
        boards._get = self.fake_get
        rows = boards.fetch_djinni(lambda m: None)
        self.assertEqual(sorted(r["title"] for r in rows), ["Data Engineer", "Python Developer"])
        remote = next(r for r in rows if r["title"] == "Python Developer")
        self.assertIn("Remote", remote["location"])
        self.assertEqual(remote["hiring_entity"], "Gamma Corp")
        pages = [u for u in self.urls if "page=" in u]
        self.assertEqual(len(pages), 1)                     # page 2 was empty, so page 3 was never requested


if __name__ == "__main__":
    unittest.main()
