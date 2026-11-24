"""Continuity mode, number-only diagnostics, and selection tests."""

from contextlib import redirect_stdout
import importlib
from io import StringIO
import os
import unittest
from unittest.mock import patch

from marong import continuity


class ContinuityModeTests(unittest.TestCase):
    def tearDown(self):
        importlib.reload(continuity)

    def test_mode_is_read_once_and_requires_exact_value(self):
        with patch.dict(os.environ):
            for value, expected in (("", "off"), ("ON", "off"), ("yes", "off"), ("off", "off"),
                                    ("shadow", "shadow"), ("on", "on")):
                with self.subTest(value=value):
                    os.environ["MARONG_CONTINUITY"] = value
                    importlib.reload(continuity)
                    os.environ["MARONG_CONTINUITY"] = "on" if expected != "on" else "off"
                    self.assertEqual(continuity.MODE, expected)

    def test_diagnostics_contain_only_mode_counts_and_result(self):
        with patch.dict(os.environ, MARONG_CONTINUITY="shadow"):
            importlib.reload(continuity)
            output = StringIO()
            with redirect_stdout(output):
                diagnostic = continuity.record_pick("start", turns=2, chars=42, conversations=1, ms=70, result="ok")
            self.assertEqual(diagnostic, {
                "mode": "shadow", "segment": "start", "turns": 2, "chars": 42,
                "conversations": 1, "ms": 70, "result": "ok",
            })
            self.assertEqual(output.getvalue(),
                             "continuity_pick mode=shadow segment=start turns=2 chars=42 conversations=1 ms=70 result=ok\n")


if __name__ == "__main__":
    unittest.main()
