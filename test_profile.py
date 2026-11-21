"""Tests for the search profile and for the engine running with profiles other than the author's.
Every test restores the example profile the other test files expect."""
import testsupport  # noqa: F401  (selects the default example profile)

import copy
import json
import unittest
from pathlib import Path

import job_filters as jf
import location_rules as lr
import poll_jobs
import priorities
import search_profile as sp

HERE = Path(__file__).parent
AUTHOR = HERE / "profiles" / "example_eu_remote_pm.json"
POLAND = HERE / "profiles" / "example_pl_python_dev.json"

US = {
    "version": 1,
    "roles": {"titles": ["data analyst", "analytics engineer"], "exclude_title_words": ["intern"]},
    "languages": {"spoken": ["english", "spanish"]},
    "location": {"home_country": "united states", "relocation": ["canada"], "excluded": []},
}


def row(title, location):
    return {"title": title, "location": location, "hiring_entity": "Acme", "source_board": "X", "apply": "https://x/1"}


class ProfileLoading(unittest.TestCase):
    def tearDown(self):
        sp.use(AUTHOR)

    def test_minimal_profile_gets_defaults(self):
        p = sp.normalise({"version": 1, "roles": {"titles": ["Designer"]}, "location": {"home_country": "Poland"}})
        self.assertEqual(p["roles"]["titles"], ["designer"])
        self.assertEqual(p["location"]["home_country"], "poland")
        self.assertEqual(p["languages"]["spoken"], ["english"])
        self.assertFalse(p["location"]["show_p3"])

    def test_all_problems_are_reported_in_plain_language(self):
        with self.assertRaises(sp.ProfileError) as cm:
            sp.normalise({"version": 1, "roles": {"titles": []},
                          "location": {"home_country": "atlantis", "relocation": ["@nowhere"]},
                          "languages": {"spoken": ["klingon"]}})
        msg = str(cm.exception)
        for needle in ("roles.titles is empty", "unknown country 'atlantis'", "@nowhere", "unknown language 'klingon'"):
            self.assertIn(needle, msg)

    def test_wrong_version_and_bad_json_are_rejected(self):
        with self.assertRaises(sp.ProfileError):
            sp.normalise({"version": 99, "roles": {"titles": ["x"]}, "location": {"home_country": "poland"}})
        with self.assertRaises(sp.ProfileError):
            sp.load(HERE / "no-such-profile.json")

    def test_both_example_profiles_are_valid(self):
        for path in (AUTHOR, POLAND):
            sp.load(path)

    def test_missing_profile_gives_a_helpful_message(self):
        import os
        old = os.environ.pop(sp.ENV_VAR, None)
        sp._ACTIVE = None
        sp._COMPILED = None
        cwd = os.getcwd()
        os.chdir("/")
        try:
            with self.assertRaises(sp.ProfileError) as cm:
                sp.active()
            self.assertIn("Ask your AI assistant", str(cm.exception))
        finally:
            os.chdir(cwd)
            if old:
                os.environ[sp.ENV_VAR] = old


class PolishPythonDeveloper(unittest.TestCase):
    def setUp(self):
        sp.use(POLAND)

    def tearDown(self):
        sp.use(AUTHOR)

    def test_titles(self):
        self.assertTrue(poll_jobs.title_matches("Senior Python Developer"))
        self.assertTrue(poll_jobs.title_matches("Backend Engineer (Django)"))
        self.assertFalse(poll_jobs.title_matches("Project Manager"))

    def test_home_and_zones(self):
        self.assertEqual(priorities.priority3("Warsaw, Poland"), 1)
        self.assertEqual(priorities.priority3("Krakow"), 1)
        self.assertEqual(priorities.priority3("Remote, EMEA"), 1)
        self.assertEqual(priorities.priority3("Berlin, Germany"), 2)       # Germany is a relocation zone for this person
        self.assertEqual(priorities.priority3("London, United Kingdom"), 2)  # secondary relocation zone
        self.assertEqual(priorities.priority3("New York, NY"), 3)
        self.assertIsNone(priorities.priority3("Moscow, Russia"))           # excluded
        self.assertEqual(priorities.priority3("Moscow; Warsaw"), 1)          # one good place keeps the row

    def test_ukraine_is_not_excluded_for_this_person(self):
        self.assertEqual(priorities.priority3("Kyiv, Ukraine"), 3)

    def test_languages_follow_the_profile(self):
        self.assertEqual(jf.classify(row("Polish speaking Python Developer", "Warsaw"), [])[0], "main")
        self.assertEqual(jf.classify(row("German speaking Python Developer", "Warsaw"), [])[0], "drop")

    def test_company_exclusion_comes_from_the_profile(self):
        r = row("Python Developer", "Warsaw")
        r["hiring_entity"] = "Example Agency"
        self.assertEqual(jf.classify(r, [])[0], "drop")

    def test_off_scope_words(self):
        self.assertEqual(jf.classify(row("Junior Python Developer", "Warsaw"), [])[0], "drop")
        self.assertEqual(jf.classify(row("Senior Python Developer", "Warsaw"), [])[0], "main")


class AmericanDataAnalyst(unittest.TestCase):
    def setUp(self):
        sp.use(US)

    def tearDown(self):
        sp.use(AUTHOR)

    def test_home_remote_and_regions(self):
        self.assertEqual(priorities.priority3("Austin, TX"), 1)
        self.assertEqual(priorities.priority3("Remote - US"), 1)
        self.assertEqual(priorities.priority3("Remote, Americas"), 1)
        self.assertEqual(priorities.priority3("Toronto, Canada"), 2)
        self.assertEqual(priorities.priority3("Berlin, Germany"), 3)

    def test_remote_scoped_to_another_region_is_not_home(self):
        self.assertEqual(priorities.priority3("Remote, Europe"), 3)
        self.assertEqual(priorities.priority3("Remote - APAC"), 3)
        self.assertFalse(poll_jobs.location_matches("Remote - APAC"))
        self.assertTrue(poll_jobs.location_matches("Remote - US"))

    def test_spoken_languages(self):
        self.assertEqual(jf.classify(row("Spanish speaking Data Analyst", "Austin, TX"), [])[0], "main")
        self.assertEqual(jf.classify(row("German speaking Data Analyst", "Austin, TX"), [])[0], "drop")


class AuthorProfileStillBehavesTheSame(unittest.TestCase):
    """A few anchors from the original rules, so a change to the catalogue cannot silently move them."""

    def test_anchors(self):
        sp.use(AUTHOR)
        self.assertEqual(priorities.priority3("Sofia, Bulgaria"), 1)
        self.assertEqual(priorities.priority3("Remote, EMEA"), 1)
        self.assertEqual(priorities.priority3("Dublin, Ireland"), 2)
        self.assertEqual(priorities.priority3("Zurich, Switzerland"), 2)
        self.assertEqual(priorities.priority3("Austin, Texas"), 3)
        self.assertIsNone(priorities.priority3("Berlin, Germany"))
        self.assertIsNone(priorities.priority3("Kyiv, Ukraine"))
        self.assertEqual(priorities.priority3("Ukraine; Remote, anywhere"), 1)


if __name__ == "__main__":
    unittest.main()
