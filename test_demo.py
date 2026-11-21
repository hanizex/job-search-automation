"""The offline demo gives the expected digest for both example profiles, and the output language follows the profile."""
import testsupport  # noqa: F401

import copy
import json
import unittest
from pathlib import Path

import demo_offline as demo
import i18n
import search_profile as sp

HERE = Path(__file__).parent
AUTHOR = HERE / "profiles" / "example_eu_remote_pm.json"
POLAND = HERE / "profiles" / "example_pl_python_dev.json"


def run_with(path):
    sp.use(path)
    postings = json.loads((HERE / "fixtures" / "mock_postings.json").read_text(encoding="utf-8"))
    return demo.run(postings)


class OfflineDemo(unittest.TestCase):
    def tearDown(self):
        sp.use(AUTHOR)

    def kept(self, res):
        return sorted((r["hiring_entity"], r["title"], r["priority"]) for r in res["kept"])

    def test_python_developer_digest(self):
        res = run_with(POLAND)
        names = [(c, p) for c, _t, p in self.kept(res)]
        self.assertEqual(names, [("Acme Cloud", 1), ("Bluefin Systems", 1), ("Harbor Logistics", 1), ("Orbit Payments", 2), ("Quill Analytics", 1)])
        reasons = {r["hiring_entity"] + "/" + r["title"]: why for r, why in res["dropped"]}
        self.assertIn("language in title", reasons["Kestrel Games/German speaking Python Developer"])
        self.assertIn("ad wall", reasons["Pixel Forge/Python Developer"])

    def test_project_manager_digest(self):
        res = run_with(AUTHOR)
        kept = {(r["hiring_entity"], r["title"]): r["priority"] for r in res["kept"]}
        self.assertEqual(kept, {("Acme Cloud", "Delivery Manager"): 1, ("Orbit Payments", "Product Manager"): 2,
                                ("Kestrel Games", "Product Owner"): 2})
        reasons = {r["hiring_entity"] + "/" + r["title"]: why for r, why in res["dropped"]}
        self.assertIn("PMP", reasons["Bluefin Systems/Senior Project Manager"])           # the author has no PMP
        self.assertIn("German", reasons["Lumen Health/Scrum Master"])

    def test_same_postings_different_people_different_digests(self):
        a, p = self.kept(run_with(AUTHOR)), self.kept(run_with(POLAND))
        self.assertTrue(set(a).isdisjoint(set(p)))

    def test_checked_in_samples_match_the_current_output(self):
        for path, name in ((AUTHOR, "sample_digest_eu_pm.md"), (POLAND, "sample_digest_pl_python_dev.md")):
            res = run_with(path)
            text = demo.digest(res, sp.active().get("name") or "unnamed")
            self.assertEqual((HERE / "examples" / name).read_text(encoding="utf-8"), text, name)


class OutputLanguage(unittest.TestCase):
    def tearDown(self):
        sp.use(AUTHOR)

    def test_texts_follow_ui_language(self):
        base = json.loads(AUTHOR.read_text(encoding="utf-8"))
        sp.use(dict(copy.deepcopy(base), ui_language="uk"))
        self.assertEqual(i18n.t("signals.grant"), "грант")
        sp.use(base)
        self.assertEqual(i18n.t("signals.grant"), "grant")

    def test_placeholder_is_recognised_in_both_languages(self):
        self.assertEqual(i18n.all_forms("signals.no_company"), {"(see the article)", "(див. новину)"})


class ProfileFeatures(unittest.TestCase):
    def tearDown(self):
        sp.use(AUTHOR)

    def test_features_default_off_and_are_validated(self):
        p = sp.normalise({"version": 1, "roles": {"titles": ["x"]}, "location": {"home_country": "poland"}})
        self.assertEqual(p["features"], {"signals": False, "replies": False})
        with self.assertRaises(sp.ProfileError):
            sp.normalise({"version": 1, "roles": {"titles": ["x"]}, "location": {"home_country": "poland"}, "features": {"signals": "yes"}})
        sp.use(POLAND)
        self.assertEqual(sp.compiled().features, {"signals": False, "replies": False})
        sp.use(AUTHOR)
        self.assertEqual(sp.compiled().features, {"signals": True, "replies": True})


if __name__ == "__main__":
    unittest.main()
