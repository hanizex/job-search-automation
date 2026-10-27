"""
Offline tests for the Workday repeat-page retry in ats_fetch.py. No network.

Run from the folder that holds ats_fetch.py:   python3 test_workday_retry.py
"""

import unittest
from unittest import mock

import ats_fetch


def _id(job):
    return job["id"]


def _pages(items, size):
    """Fake server: offset -> slice of items, like a plain paged list."""
    def page(offset):
        chunk = items[offset:offset + size]
        return chunk, len(items)
    return page


class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class PaginateRepeatRetryTests(unittest.TestCase):
    def setUp(self):
        # Keep the tests fast: no real sleeps.
        patcher_a = mock.patch.object(ats_fetch, "PAGE_SLEEP_SECONDS", 0)
        patcher_b = mock.patch.object(ats_fetch, "PAGE_RETRY_SLEEP_SECONDS", 0)
        patcher_a.start()
        patcher_b.start()
        self.addCleanup(patcher_a.stop)
        self.addCleanup(patcher_b.stop)

    def test_repeated_page_is_cleared_by_retry(self):
        items = [{"id": f"j{i}"} for i in range(6)]
        good = _pages(items, 2)
        calls = {"n": 0}

        def flaky(offset):
            calls["n"] += 1
            if offset == 2 and calls.get("glitched") is None:
                calls["glitched"] = True
                return items[0:2], 6  # repeats page 1 once
            return good(offset)

        result = ats_fetch._paginate(flaky, page_size=2, id_key=_id, repeat_retries=2)
        self.assertFalse(result.capped)
        self.assertEqual([j["id"] for j in result.jobs], [f"j{i}" for i in range(6)])
        self.assertTrue(any("repeated" in w for w in result.warnings))

    def test_persistent_repeat_still_counts_as_wraparound(self):
        items = [{"id": f"j{i}"} for i in range(6)]

        def wrapping(offset):
            if offset >= 2:
                return items[0:2], 6  # always serves page 1 again
            return items[0:2], 6

        result = ats_fetch._paginate(wrapping, page_size=2, id_key=_id, repeat_retries=2)
        self.assertTrue(result.capped)
        self.assertEqual([j["id"] for j in result.jobs], ["j0", "j1"])

    def test_no_retry_when_disabled(self):
        items = [{"id": f"j{i}"} for i in range(4)]
        requests = []

        def wrapping(offset):
            requests.append(offset)
            if offset >= 2:
                return items[0:2], 4
            return items[0:2], 4

        result = ats_fetch._paginate(wrapping, page_size=2, id_key=_id)
        self.assertTrue(result.capped)
        self.assertEqual(requests.count(2), 1)


class WorkdayFetchTests(unittest.TestCase):
    def setUp(self):
        patcher_a = mock.patch.object(ats_fetch, "PAGE_SLEEP_SECONDS", 0)
        patcher_b = mock.patch.object(ats_fetch, "PAGE_RETRY_SLEEP_SECONDS", 0)
        patcher_a.start()
        patcher_b.start()
        self.addCleanup(patcher_a.stop)
        self.addCleanup(patcher_b.stop)

    def test_workday_fetch_survives_one_glitched_page(self):
        postings = [{"externalPath": f"/job/{i}"} for i in range(45)]
        seen_offsets = []
        glitched = {"done": False}

        def fake_post(url, body):
            offset = body["offset"]
            seen_offsets.append(offset)
            if offset == 20 and not glitched["done"]:
                glitched["done"] = True
                # Server answers the second page with the first one.
                return _FakeResponse({"jobPostings": postings[0:20], "total": 45})
            chunk = postings[offset:offset + body["limit"]]
            return _FakeResponse({"jobPostings": chunk, "total": 45})

        with mock.patch.object(ats_fetch, "_post", side_effect=fake_post):
            result = ats_fetch.fetch_workday_all("https://example.invalid/wday/cxs/x/y/jobs")

        self.assertFalse(result.capped)
        self.assertEqual(result.true_total, 45)
        self.assertEqual(seen_offsets.count(20), 2)  # the glitched page was asked again

    def test_workday_persistent_glitch_is_reported_as_capped(self):
        postings = [{"externalPath": f"/job/{i}"} for i in range(45)]

        def fake_post(url, body):
            offset = body["offset"]
            if offset >= 20:
                return _FakeResponse({"jobPostings": postings[0:20], "total": 45})
            return _FakeResponse({"jobPostings": postings[offset:offset + body["limit"]], "total": 45})

        with mock.patch.object(ats_fetch, "_post", side_effect=fake_post):
            result = ats_fetch.fetch_workday_all("https://example.invalid/wday/cxs/x/y/jobs")

        self.assertTrue(result.capped)
        self.assertEqual(result.true_total, 20)


if __name__ == "__main__":
    unittest.main()
