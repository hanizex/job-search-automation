"""
Offline tests for the 25.10 patch. No network, no third-party packages.

Run from the folder that holds ats.py:   python3 test_patch.py
(do not add -I: it strips the current directory from sys.path and the imports fail)
"""

import json
import sys
import unittest
from unittest import mock

import ats
import collapse
import location_rules as lr

DROP = lr.DROP


class TestLocationPriority(unittest.TestCase):

    def test_sofia_is_one(self):
        for text in ["Sofia, Bulgaria", "Sofia, Bulgaria (Hybrid)", "Bulgaria", "BGR - Sofia"]:
            self.assertEqual(lr.priority_for(text), 1, text)

    def test_eu_and_warsaw_are_two(self):
        for text in ["Warsaw, Poland", "Amsterdam", "Spain", "Republic of Ireland (Remote)",
                     "Home based - EMEA", "Home based - Worldwide", "Paris, France (Hybrid)"]:
            self.assertEqual(lr.priority_for(text), 2, text)

    def test_protected_non_eu_is_three(self):
        for text in ["Switzerland", "Zurich", "Norway", "Reykjavik, Iceland"]:
            self.assertEqual(lr.priority_for(text), 3, text)

    def test_visa_countries_are_four(self):
        for text in ["London, United Kingdom", "Remote, United Kingdom",
                     "San Francisco, United States", "Toronto, Canada", "Yerevan, Armenia"]:
            self.assertEqual(lr.priority_for(text), 4, text)

    def test_germany_alone_is_dropped(self):
        for text in ["Berlin, Germany", "Munich", "Remote, Germany", "Walldorf"]:
            self.assertIs(lr.priority_for(text), DROP, text)

    def test_ukraine_alone_is_dropped(self):
        for text in ["Kyiv, Ukraine", "Ukraine", "Lviv"]:
            self.assertIs(lr.priority_for(text), DROP, text)

    def test_germany_inside_a_list_does_not_kill_the_row(self):
        text = ("Amsterdam, Netherlands; Belgrade, Serbia; Berlin, Germany; "
                "Limassol, Cyprus; Munich, Germany; Warsaw, Poland")
        self.assertEqual(lr.priority_for(text), 2)

    def test_best_wins_across_a_list(self):
        self.assertEqual(lr.priority_for("London, United Kingdom; Sofia, Bulgaria"), 1)
        self.assertEqual(lr.priority_for("Zurich, Switzerland; Madrid, Spain"), 2)

    def test_unknown_falls_back_not_drops(self):
        self.assertEqual(lr.priority_for("Atlantis"), 4)
        self.assertEqual(lr.priority_for(""), 4)
        self.assertEqual(lr.priority_for(None), 4)

    def test_poland_is_no_longer_dropped(self):
        """The whole point of the 25.10 change."""
        self.assertEqual(lr.priority_for("Warsaw, Poland"), 2)
        self.assertEqual(lr.priority_for("Poland (Remote)"), 2)
        self.assertIsNot(lr.priority_for("Krakow"), DROP)

    def test_entity_risk(self):
        self.assertTrue(lr.entity_risk("Home based - EMEA"))
        self.assertTrue(lr.entity_risk("Spain (Remote)"))
        self.assertFalse(lr.entity_risk("Sofia, Bulgaria (Remote)"))
        self.assertFalse(lr.entity_risk("Amsterdam"))  # not a remote row at all

    def test_explain_never_raises(self):
        for text in ["Sofia", "Berlin", "Atlantis", "", "Zurich; Kyiv"]:
            self.assertIsInstance(lr.explain(text), str)


class TestCollapse(unittest.TestCase):

    def _elastic_rows(self):
        countries = ["Spain", "Ireland", "Portugal", "Poland", "Greece", "Switzerland"]
        return [
            {"company": "Elastic", "role": "Senior Product Manager (XDR) - Security Solutions",
             "url": f"https://jobs.elastic.co/jobs?gh_jid=819413{i}", "location": c,
             "posted": "", "board": "Greenhouse"}
            for i, c in enumerate(countries)
        ]

    def test_six_country_rows_become_one(self):
        rows = self._elastic_rows()
        out = collapse.collapse(rows, priority_of=lr.priority_for)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["variants"], 6)
        self.assertEqual(out[0]["priority"], 2)
        for c in ["Spain", "Poland", "Switzerland"]:
            self.assertIn(c, out[0]["location"])

    def test_surviving_row_keeps_the_best_priority_url(self):
        rows = [
            {"company": "Acme", "role": "Delivery Manager", "url": "u-london",
             "location": "London, United Kingdom", "posted": ""},
            {"company": "Acme", "role": "Delivery Manager", "url": "u-sofia",
             "location": "Sofia, Bulgaria", "posted": ""},
        ]
        out = collapse.collapse(rows, priority_of=lr.priority_for)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["priority"], 1)
        self.assertEqual(out[0]["url"], "u-sofia")

    def test_different_jobs_are_not_merged(self):
        rows = [
            {"company": "Canonical", "role": "Product Manager - Cloud",
             "url": "a", "location": "Home based - EMEA", "posted": ""},
            {"company": "Canonical", "role": "Product Manager - Security",
             "url": "b", "location": "Home based - EMEA", "posted": ""},
        ]
        out = collapse.collapse(rows, priority_of=lr.priority_for)
        self.assertEqual(len(out), 2)

    def test_different_requisition_ids_are_never_merged(self):
        rows = [
            {"company": "Visa", "role": "Product Manager REF082383W",
             "url": "x/REF082383W", "location": "London", "posted": ""},
            {"company": "Visa", "role": "Product Manager REF087384W",
             "url": "x/REF087384W", "location": "London", "posted": ""},
        ]
        out = collapse.collapse(rows, priority_of=lr.priority_for)
        self.assertEqual(len(out), 2)

    def test_earliest_posted_date_survives(self):
        rows = [
            {"company": "Mozilla", "role": "Senior Product Manager, Mobile",
             "url": "a", "location": "Remote Spain", "posted": "2026-10-02"},
            {"company": "Mozilla", "role": "Senior Product Manager, Mobile",
             "url": "b", "location": "Remote France", "posted": "2026-09-30"},
        ]
        out = collapse.collapse(rows, priority_of=lr.priority_for)
        self.assertEqual(out[0]["posted"], "2026-09-30")

    def test_order_is_stable_and_singles_get_a_priority(self):
        rows = [
            {"company": "A", "role": "PM", "url": "1", "location": "Sofia", "posted": ""},
            {"company": "B", "role": "PM", "url": "2", "location": "Madrid", "posted": ""},
        ]
        out = collapse.collapse(rows, priority_of=lr.priority_for)
        self.assertEqual([r["company"] for r in out], ["A", "B"])
        self.assertEqual(out[0]["priority"], 1)
        self.assertEqual(out[1]["priority"], 2)

    def test_report_line(self):
        rows = self._elastic_rows()
        out = collapse.collapse(rows, priority_of=lr.priority_for)
        line = collapse.report(rows, out)
        self.assertIn("6 -> 1", line)
        self.assertIn("x6", line)


class TestAdapters(unittest.TestCase):
    """Parsing only. The network is mocked; shapes come from real 25.10 responses."""

    def _run(self, payload, fn, cfg):
        with mock.patch.object(ats, "_request", return_value=payload):
            return fn(cfg)

    def test_greenhouse(self):
        payload = {"jobs": [{
            "id": 5029257, "title": "Product Manager",
            "absolute_url": "https://job-boards.greenhouse.io/canonical/jobs/5029257",
            "location": {"name": "Home based - EMEA"},
            "first_published": "2026-08-05T12:00:00-04:00",
            "updated_at": "2026-10-19T09:00:00-04:00",
        }]}
        rows = self._run(payload, ats.fetch_greenhouse, {"name": "Canonical", "token": "canonical"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "Product Manager")
        self.assertEqual(rows[0]["location"], "Home based - EMEA")
        self.assertEqual(rows[0]["posted"], "2026-08-05")
        self.assertEqual(rows[0]["board"], "Greenhouse")
        self.assertEqual(rows[0]["company"], "Canonical")

    def test_ashby_skips_unlisted(self):
        payload = {"jobs": [
            {"title": "Product Manager", "location": "Remote", "jobUrl": "https://x/1",
             "publishedAt": "2026-10-15T00:00:00Z", "isListed": True,
             "secondaryLocations": [{"location": "London"}]},
            {"title": "Hidden", "location": "Remote", "jobUrl": "https://x/2",
             "isListed": False},
        ]}
        rows = self._run(payload, ats.fetch_ashby, {"name": "Docker", "slug": "docker"})
        self.assertEqual(len(rows), 1)
        self.assertIn("London", rows[0]["location"])
        self.assertEqual(rows[0]["posted"], "2026-10-15")

    def test_lever_epoch_millis(self):
        payload = [{"text": "Product Manager", "hostedUrl": "https://jobs.lever.co/palantir/1",
                    "categories": {"location": "London"}, "createdAt": 1760000000000}]
        rows = self._run(payload, ats.fetch_lever, {"name": "Palantir", "slug": "palantir"})
        self.assertEqual(rows[0]["role"], "Product Manager")
        self.assertRegex(rows[0]["posted"], r"^\d{4}-\d{2}-\d{2}$")

    def test_smartrecruiters_paginates(self):
        pages = [
            {"totalFound": 2, "content": [
                {"id": "a1", "name": "Delivery Manager",
                 "location": {"city": "Amsterdam", "country": "nl", "remote": False},
                 "releasedDate": "2026-10-01T00:00:00.000Z"}]},
            {"totalFound": 2, "content": [
                {"id": "b2", "name": "Program Manager",
                 "location": {"city": "Dublin", "country": "ie", "remote": True},
                 "releasedDate": "2026-10-02T00:00:00.000Z"}]},
        ]
        with mock.patch.object(ats, "_request", side_effect=pages):
            rows = ats.fetch_smartrecruiters({"name": "ServiceNow", "slug": "ServiceNow"})
        self.assertEqual(len(rows), 2)
        self.assertIn("Remote", rows[1]["location"])
        self.assertTrue(rows[0]["url"].endswith("/ServiceNow/a1"))

    def test_recruitee(self):
        payload = {"offers": [{"title": "Senior PM", "careers_url": "https://careers.chaos.com/o/1",
                               "location": "Sofia, Bulgaria (remote)", "city": "Sofia",
                               "published_at": "2026-10-10T08:00:00.000+02:00"}]}
        rows = self._run(payload, ats.fetch_recruitee,
                         {"name": "Chaos", "url": "https://careers.chaos.com/api/offers/"})
        self.assertEqual(rows[0]["posted"], "2026-10-10")
        self.assertEqual(lr.priority_for(rows[0]["location"]), 1)

    def test_workday_paginates_and_builds_url(self):
        pages = [
            {"total": 2, "jobPostings": [
                {"title": "Product Manager", "externalPath": "/job/Sofia/Product-Manager_R1",
                 "locationsText": "Sofia, Bulgaria"}]},
            {"total": 2, "jobPostings": [
                {"title": "Delivery Manager", "externalPath": "/job/Paris/Delivery_R2",
                 "locationsText": "Paris, France"}]},
        ]
        with mock.patch.object(ats, "_request", side_effect=pages):
            rows = ats.fetch_workday({"name": "Broadcom", "tenant": "broadcom",
                                      "wd": "wd1", "site": "External_Career"})
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows[0]["url"],
            "https://broadcom.wd1.myworkdayjobs.com/en-US/External_Career"
            "/job/Sofia/Product-Manager_R1")
        self.assertEqual(lr.priority_for(rows[0]["location"]), 1)

    def test_one_dead_board_does_not_stop_the_run(self):
        companies = [
            {"name": "Good", "ats": "greenhouse", "token": "good"},
            {"name": "Bad", "ats": "greenhouse", "token": "bad"},
            {"name": "Skipped", "ats": "greenhouse", "token": "x", "status": "down"},
            {"name": "NotAts", "dou": "something"},
        ]

        def fake(cfg):
            if cfg["token"] == "bad":
                raise OSError("connection reset")
            return [{"company": cfg["name"], "role": "PM", "url": "u",
                     "location": "Sofia", "pay": "", "board": "Greenhouse",
                     "posted": "", "found": "2026-10-25"}]

        with mock.patch.dict(ats.ADAPTERS, {"greenhouse": fake}):
            rows, errors = ats.fetch_all(companies)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0], "Bad")

    def test_row_shape_matches_poll_jobs(self):
        payload = {"jobs": [{"title": "PM", "absolute_url": "u",
                             "location": {"name": "Sofia"}, "updated_at": "2026-10-01"}]}
        rows = self._run(payload, ats.fetch_greenhouse, {"name": "X", "token": "x"})
        self.assertEqual(
            set(rows[0]),
            {"company", "role", "url", "location", "pay", "board", "posted", "found"})


class TestEndToEnd(unittest.TestCase):

    def test_elastic_import_produces_one_card_with_priority_two(self):
        """The whole point of the patch, in one test."""
        payload = {"jobs": [
            {"title": "Senior Product Manager (XDR) - Security Solutions",
             "absolute_url": f"https://jobs.elastic.co/jobs?gh_jid={jid}",
             "location": {"name": loc}, "updated_at": "2026-10-20"}
            for jid, loc in [(1, "Spain"), (2, "Ireland"), (3, "Poland"),
                             (4, "Greece"), (5, "Switzerland"), (6, "Germany")]
        ]}
        with mock.patch.object(ats, "_request", return_value=payload):
            rows = ats.fetch_greenhouse({"name": "Elastic", "token": "elastic"})
        self.assertEqual(len(rows), 6)
        out = collapse.collapse(rows, priority_of=lr.priority_for)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["priority"], 2)
        self.assertEqual(out[0]["variants"], 6)
        # Germany was one of the six and must not have dropped the row
        self.assertIn("Germany", out[0]["location"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
