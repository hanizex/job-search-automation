"""Offline tests for priorities.py (3-level scale of 26.10.2026). Run: python3 test_priorities.py"""
import unittest

import priorities as pr


class TestPriority3(unittest.TestCase):
    def check(self, cases):
        for text, expected in cases:
            self.assertEqual(pr.priority3(text), expected, text)

    def test_sofia_and_fully_remote_are_one(self):
        self.check([
            ("Sofia, Bulgaria (Hybrid)", 1), ("Plovdiv, Bulgaria", 1), ("Remote", 1),
            ("Remote - EMEA", 1), ("Home based - EMEA", 1), ("Worldwide", 1), ("Remote (EU or US)", 1),
        ])

    def test_europe_relocation_and_temporary_protection_are_two(self):
        self.check([
            ("Warsaw, Poland", 2), ("Poland", 2), ("Remote, Ireland", 2), ("Dublin", 2),
            ("Zurich, Switzerland", 2), ("Oslo, Norway", 2),
            ("Amsterdam; Berlin, Germany; Warsaw", 2),
        ])

    def test_visa_needed_is_three(self):
        self.check([
            ("London, United Kingdom", 3), ("New York, NY, United States", 3), ("US-Remote", 3),
            ("us; Remote", 3), ("Remote - California", 3), ("Remote, Costa Rica", 3),
            ("Yerevan, Armenia", 3), ("Atlantis", 3), ("", 3),
        ])

    def test_germany_and_ukraine_only_are_dropped(self):
        self.check([("Berlin, Germany", None), ("Kyiv, Ukraine", None)])

    def test_best_priority_wins_in_a_list(self):
        self.check([("US-Remote; Sofia, Bulgaria", 1), ("London; Warsaw", 2), ("London; New York", 3)])

    def test_austria_is_not_the_us(self):
        self.assertEqual(pr.priority3("Vienna, Austria"), 2)


class TestP3Hidden(unittest.TestCase):
    def row(self, loc):
        return {"title": "Product Manager", "location": loc, "hiring_entity": "UNKNOWN",
                "source_board": "X", "apply": "https://x/" + loc}

    def test_visa_roles_are_dropped_while_p3_is_hidden(self):
        import job_filters as jf
        for loc in ("London, United Kingdom", "United Kingdom (Remote)", "Georgia - Remote (primary, from URL, 6 Locations)"):
            verdict, reason = jf.classify(self.row(loc), [])
            self.assertEqual(verdict, "drop", loc)
            self.assertIn("P3", reason)

    def test_p1_and_p2_still_pass_and_p3_returns_when_switched_on(self):
        import job_filters as jf
        self.assertEqual(jf.classify(self.row("Sofia, Bulgaria"), [])[0], "main")
        self.assertEqual(jf.classify(self.row("Warsaw, Poland"), [])[0], "main")
        pr.SHOW_P3 = True
        try:
            p = self.row("London, United Kingdom")
            self.assertEqual(jf.classify(p, [])[0], "main")
            self.assertEqual(p["priority"], 3)
        finally:
            pr.SHOW_P3 = False


if __name__ == "__main__":
    unittest.main(verbosity=1)
