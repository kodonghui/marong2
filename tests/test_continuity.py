"""Continuity mode, number-only diagnostics, and selection tests."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
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


class SelectionTests(unittest.TestCase):
    now = datetime(2026, 11, 24, 7, tzinfo=timezone.utc)

    def turn(self, minutes, origin="text", role="user", text="합성 대화"):
        return continuity.Turn("1", origin, self.now - timedelta(minutes=minutes), role, text)

    def test_recent_crosses_channels_and_applies_both_limits(self):
        rows = [self.turn(i, text="가" * 500) for i in range(12, 0, -1)]
        rows.append(self.turn(0, "call", "assistant", "이번 주말 기차표는 샀어?"))
        recent = continuity.recent_turns(rows, self.now)
        self.assertEqual(recent[-1], rows[-1])
        self.assertTrue(all(len(row.text) <= 300 for row in recent))
        self.assertTrue(all(row.text.endswith("…") for row in recent[:-1]))
        self.assertLessEqual(sum(len(row.text) for row in recent), 2000)
        self.assertFalse(continuity.unanswered(recent[-1]))
        self.assertTrue(continuity.unanswered(self.turn(2, role="assistant", text="준비는 잘 돼?")))
        self.assertEqual(len(continuity.recent_turns([self.turn(0) for _ in range(30)], self.now)), 20)
        self.assertTrue(continuity.recent_turns([self.turn(30)], self.now))
        self.assertFalse(continuity.recent_turns([self.turn(31)], self.now))
        self.assertEqual(continuity.recent_turns([self.turn(35), self.turn(4)], self.now), [self.turn(4)])

    def test_older_spans_merge_and_select_after_merging(self):
        def span(start, end, origin, key):
            return continuity.Span(
                self.now - timedelta(minutes=start), self.now - timedelta(minutes=end), origin, key,
            )

        topics = [span(100, 99, "text", None), span(80, 76, "call", "1"),
                  span(1500, 1494, "call", "2"), span(6000, 5995, "text", None),
                  span(11000, 10999, "text", None)]
        older = continuity.older_conversations(topics, self.now)
        self.assertEqual(older, [topics[:2], [topics[2]], [topics[3]]])
        topics.append(span(70, 1, "call", "3"))
        self.assertEqual(continuity.older_conversations(topics, self.now), [[topics[2]], [topics[3]]])


if __name__ == "__main__":
    unittest.main()
