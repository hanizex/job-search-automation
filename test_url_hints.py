"""Offline tests for url_hints.py, using URLs and titles taken from live boards. Run: python3 test_url_hints.py"""
import unittest

import url_hints as uh

HPE = "https://hpe.wd5.myworkdayjobs.com/Jobsathpe/job/"


class TestWorkday(unittest.TestCase):
    def test_two_locations_row_gets_its_city_from_the_url(self):
        h = uh.hints(HPE + "Warszawa-Poland/Global-Workplace-EMEA-Technical-Infrastructure-Program-Manager_1216360-1")
        self.assertEqual(h["location"], "Warszawa Poland")
        self.assertEqual(h["req_id"], "1216360")
        self.assertEqual(h["title"], "Global Workplace EMEA Technical Infrastructure Program Manager")

    def test_city_and_region_repeats_are_collapsed(self):
        self.assertEqual(uh.hints(HPE + "Sofia-Sofia-Bulgaria/Supply-Chain-Intern_1182794-1")["location"], "Sofia Bulgaria")

    def test_triple_hyphen_is_a_separator(self):
        h = uh.hints("https://salesforce.wd12.myworkdayjobs.com/External_Career_Site/job/Ireland---Dublin/Product-Owner--Community_JR356410")
        self.assertEqual(h["location"], "Ireland - Dublin")
        self.assertEqual(h["req_id"], "JR356410")
        self.assertEqual(h["title"], "Product Owner Community")

    def test_letter_prefixed_requisition_ids(self):
        h = uh.hints("https://broadcom.wd1.myworkdayjobs.com/External_Career/job/USA-Colorado-Fort-Collins-4380-Ziegler-Road/Software-Firmware-Engineer_R027107")
        self.assertEqual(h["req_id"], "R027107")
        self.assertEqual(h["title"], "Software Firmware Engineer")

    def test_url_without_job_segment_gives_nothing(self):
        self.assertEqual(uh.hints("https://hpe.wd5.myworkdayjobs.com/Jobsathpe"), {})


class TestOtherSources(unittest.TestCase):
    def test_recruitee(self):
        h = uh.hints("https://careers.chaos.com/o/channel-marketing-enablement-manager-mfd-fixed-term-maternity-cover")
        self.assertIn("maternity cover", h["title"])

    def test_amazon_and_djinni(self):
        a = uh.hints("https://www.amazon.jobs/en/jobs/10542052/area-manager")
        self.assertEqual((a["req_id"], a["title"]), ("10542052", "area manager"))
        d = uh.hints("https://djinni.co/jobs/812345-senior-product-manager/")
        self.assertEqual((d["req_id"], d["title"]), ("812345", "senior product manager"))

    def test_smartrecruiters_only_when_a_slug_is_present(self):
        self.assertEqual(uh.hints("https://jobs.smartrecruiters.com/Experian/744000149686309"), {})
        self.assertIn("software", uh.hints("https://jobs.smartrecruiters.com/Experian/744000149686309-analista-de-desenvolvimento-de-software-ii")["title"])

    def test_unknown_hosts_and_junk(self):
        for u in ("", None, "UNKNOWN", "https://example.com/careers/42"):
            self.assertEqual(uh.hints(u), {})


class TestTitleMismatch(unittest.TestCase):
    def test_real_hpe_mismatches_are_flagged(self):
        # listed "DevOps Engineer", URL says the ad was an HPC cluster administrator for US hours
        self.assertTrue(uh.titles_differ("DevOps Engineer", "HPC Cluster Senior Administrator in US time zone"))
        self.assertTrue(uh.titles_differ("Technical support Engineer Intern", "Technical Consultant Intern"))
        self.assertTrue(uh.titles_differ("Global Logistics Contract Manager", "GLO Contracts Manager"))

    def test_matching_titles_are_not_flagged(self):
        self.assertFalse(uh.titles_differ("Global Workplace EMEA Technical Infrastructure Program Manager",
                                          "Global Workplace EMEA Technical Infrastructure Program Manager"))
        self.assertFalse(uh.titles_differ("Supply Chain Intern - Стаж", "Supply Chain Intern"))
        self.assertFalse(uh.titles_differ("Product Owner, Community", "Product Owner Community"))
        self.assertFalse(uh.titles_differ("Digital Presales Solution Architect with Italian or Spanish",
                                          "Job Posting Title Digital Presales Solution Architect with Italian or Spanish"))

    def test_empty_inputs_never_flag(self):
        self.assertFalse(uh.titles_differ("", "x y z"))
        self.assertFalse(uh.titles_differ("Product Manager", ""))


if __name__ == "__main__":
    unittest.main(verbosity=1)
