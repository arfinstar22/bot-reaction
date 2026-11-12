import unittest

from bot import filter_pool, normalize_emoji, pick_reactions


class ReactionBotTest(unittest.TestCase):
    def test_variation_selector_normalized(self):
        self.assertEqual(normalize_emoji("❤️"), normalize_emoji("❤"))
        self.assertEqual(normalize_emoji("☃️"), normalize_emoji("☃"))

    def test_allowed_pool_uses_canonical_emoji(self):
        pool = ["❤", "🔥", "👍"]
        available = [
            {"type": "emoji", "emoji": "❤️"},
            {"type": "emoji", "emoji": "🔥"},
            {"type": "custom_emoji", "custom_emoji_id": "1"},
        ]
        self.assertEqual(filter_pool(pool, available), ["❤️", "🔥"])

    def test_missing_available_reactions_means_all(self):
        pool = ["👍", "🔥"]
        self.assertEqual(filter_pool(pool, None), pool)

    def test_pick_distinct(self):
        picked = pick_reactions(["a", "b", "c", "d", "e"], 5)
        self.assertEqual(len(picked), 5)
        self.assertEqual(len(set(picked)), 5)

    def test_pick_never_more_than_pool(self):
        self.assertEqual(len(pick_reactions(["a", "b"], 5)), 2)
        self.assertEqual(pick_reactions(["a"], 0), [])


if __name__ == "__main__":
    unittest.main()
