"""TC-670: Korean calendar dates and elapsed times for conversation history."""

from datetime import datetime, timedelta, timezone
import unittest

from marong.relative_time import relative_time


KST = timezone(timedelta(hours=9))
UTC = timezone.utc


def instant(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=KST).astimezone(UTC)


class RelativeTimeTests(unittest.TestCase):
    def test_display_boundaries(self):
        now = instant(24, 16)
        for value, label in (
            (now - timedelta(minutes=1), "방금"),
            (now - timedelta(seconds=119), "방금"),
            (now - timedelta(minutes=2), "2분 전"),
            (now - timedelta(minutes=59, seconds=59), "59분 전"),
            (instant(24, 15), "오늘 오후 3시"),
            (instant(24, 14, 59), "오늘 오후 2시 59분"),
            (instant(24, 12), "오늘 낮 12시"),
            (instant(24, 0), "오늘 오전 0시"),
            (instant(23, 23, 50), "어제 오후 11시 50분(11/23 월)"),
            (instant(22, 15), "그저께 오후 3시(11/22 일)"),
            (instant(20, 16), "4일 전(11/20 금)"),
            (instant(18, 16), "6일 전(11/18 수)"),
            (instant(17, 15), "11월 17일(화)"),
            (now + timedelta(seconds=30), "방금"),
            (None, None),
        ):
            with self.subTest(value=value):
                self.assertEqual(relative_time(value, now), label)

    def test_korean_midnight_and_first_matching_rule(self):
        self.assertEqual(relative_time(instant(23, 23, 50), instant(24, 0, 10)), "20분 전")
        self.assertEqual(relative_time(instant(23, 23), instant(24, 1, 30)), "어제 오후 11시(11/23 월)")


if __name__ == "__main__":
    unittest.main()
