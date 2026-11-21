"""Imported first by every test file: selects the example profile the expectations were written for.
Set JSE_TEST_PROFILE to run the same tests against another profile file."""
import os
from pathlib import Path

import search_profile

search_profile.use(os.environ.get("JSE_TEST_PROFILE") or str(Path(__file__).with_name("profiles") / "example_eu_remote_pm.json"))
