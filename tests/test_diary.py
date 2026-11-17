"""Diary rules with synthetic scenes (TC-163)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marong.diary import scene_error


class SceneRules(unittest.TestCase):
    def test_valid_scenes(self):
        for scene in (
            "The little white character carries a basket.",
            "Under the stars, a chestnut rolls! A basket tips. The sky is clear?",
            "A " + "x" * 397 + ".",
        ):
            with self.subTest(scene=scene):
                self.assertIsNone(scene_error(scene))

    def test_look_card_only_allows_the_friend(self):
        scene = "The friend holds a basket. The little white character sits near the friend."
        self.assertEqual(scene_error(scene), "person")
        self.assertIsNone(scene_error(scene, has_look=True))
        self.assertEqual(scene_error("A friend holds a basket.", has_look=True), "person")
        self.assertEqual(scene_error("The friend holds a basket for a child.", has_look=True), "person")

    def test_rejection_codes(self):
        cases = {
            "A " + "x" * 398 + ".": "too_long",
            "The 하늘 is clear.": "korean",
            "A 2nd basket tips.": "digits",
            "The phone rings at 010-0000-0000.": "digits",
            "On a plaque is test@example.com.": "contact",
            "The www.example.test address is visible.": "contact",
            "A sign says HTTP.": "contact",
            "": "first_word",
            "The sky is clear": "first_word",
            "A basket tips. The rain falls. A light shines. A cloud drifts.": "first_word",
            "Clouds roll past the window.": "first_word",
            "The чужое is clear.": "first_word",
            "A toy called Example is outside.": "capital",
            "The student carries a basket.": "person",
        }
        for scene, code in cases.items():
            with self.subTest(code=code, scene=scene):
                self.assertEqual(scene_error(scene, has_look=True), code)


if __name__ == "__main__":
    unittest.main()
