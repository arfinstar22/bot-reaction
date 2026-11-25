import http.client
import os
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from bot import (
    Bot,
    ChatContext,
    Config,
    TelegramError,
    check_channel,
    filter_pool,
    handle_post,
    is_article_post,
    load_chat_context,
    load_config,
    normalize_emoji,
    pick_reactions,
    start_health_server,
)


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

    def test_pick_repeats_when_count_exceeds_distinct_pool(self):
        picked = pick_reactions(["a", "b"], 5)
        self.assertEqual(len(picked), 5)
        self.assertTrue(set(picked).issubset({"a", "b"}))
        self.assertEqual(pick_reactions(["a"], 0), [])

    def test_pick_respects_max_distinct_for_twenty_bots(self):
        pool = [chr(0x1F600 + i) for i in range(30)]
        picked = pick_reactions(pool, 20, max_distinct=10)
        self.assertEqual(len(picked), 20)
        self.assertLessEqual(len(set(picked)), 10)
        self.assertTrue(set(picked).issubset(set(pool)))

    def test_health_server_returns_ok(self):
        with patch.dict(os.environ, {"PORT": "0"}):
            server = start_health_server()
        self.assertIsNotNone(server)
        try:
            port = server.server_address[1]
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"ok")
            conn.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_only_rich_article_gets_reaction(self):
        self.assertTrue(
            is_article_post(
                {"rich_message": {"blocks": [{"type": "paragraph"}]}}
            )
        )
        self.assertFalse(is_article_post({"rich_message": {}}))
        self.assertFalse(is_article_post({"text": "post biasa"}))
        self.assertFalse(is_article_post({"sticker": {"file_id": "abc"}}))
        self.assertFalse(
            is_article_post(
                {
                    "sticker": {"file_id": "abc"},
                    "rich_message": {"blocks": [{"type": "paragraph"}]},
                }
            )
        )

    def _config(self, count: int = 5):
        return Config(
            bots=[Bot(token=f"token{i}") for i in range(count)],
            channel_id="-1001",
            reactions_file=Path("reactions.txt"),
            reaction_count=count,
        )

    def test_numeric_channel_id_requires_minus_100_prefix(self):
        cfg = self._config()
        cfg.channel_id = "3955448047"
        with self.assertRaises(SystemExit):
            check_channel(cfg)

    def test_sticker_skipped_before_api_call(self):
        post = {
            "chat": {"id": -1001},
            "message_id": 7,
            "sticker": {"file_id": "abc"},
        }
        with patch("bot.get_chat_context") as context, patch("bot.api_call") as api:
            handle_post(post, self._config(), ["❤"], {}, set(), deque())
        context.assert_not_called()
        api.assert_not_called()

    def test_rich_article_sends_five_reactions(self):
        post = {
            "chat": {"id": -1001},
            "message_id": 8,
            "rich_message": {"blocks": [{"type": "paragraph"}]},
        }
        context = ChatContext(emojis=["❤", "🔥", "👍", "🎉", "😁"], limit=5)
        with patch("bot.get_chat_context", return_value=context), patch(
            "bot.api_call"
        ) as api:
            handle_post(post, self._config(), ["❤"], {}, set(), deque())
        self.assertEqual(api.call_count, 5)
        chosen = [
            call.args[2]["reaction"][0]["emoji"] for call in api.call_args_list
        ]
        self.assertEqual(sorted(chosen), sorted(context.emojis))

    def test_ten_tokens_accepted(self):
        tokens = ",".join(f"{i}:token{i}" for i in range(1, 11))
        with patch.dict(os.environ, {"TG_TOKENS": tokens}):
            cfg = load_config()
        self.assertEqual(len(cfg.bots), 10)
        self.assertEqual(cfg.reaction_count, 10)

    def test_duplicate_tokens_rejected(self):
        with patch.dict(os.environ, {"TG_TOKENS": "1:aaa,1:aaa"}):
            with self.assertRaises(SystemExit):
                load_config()

    def test_twenty_tokens_and_reserve_slots_loaded(self):
        tokens = ",".join(f"{i}:token{i}" for i in range(1, 21))
        with patch.dict(
            os.environ, {"TG_TOKENS": tokens, "RESERVE_SLOTS": "0"}, clear=False
        ):
            cfg = load_config()
        self.assertEqual(len(cfg.bots), 20)
        self.assertEqual(cfg.reaction_count, 20)
        self.assertEqual(cfg.reserve_slots, 0)

    def test_invalid_reserve_slots_rejected(self):
        with patch.dict(
            os.environ, {"TG_TOKENS": "1:aaa", "RESERVE_SLOTS": "abc"}, clear=False
        ):
            with self.assertRaises(SystemExit):
                load_config()

    def test_ten_bots_send_ten_reactions(self):
        post = {
            "chat": {"id": -1001},
            "message_id": 9,
            "rich_message": {"blocks": [{"type": "paragraph"}]},
        }
        emojis = list("😀😁😂🤣😃😄😅😆😉😊")
        context = ChatContext(emojis=emojis, limit=10)
        with patch("bot.get_chat_context", return_value=context), patch(
            "bot.api_call"
        ) as api:
            handle_post(post, self._config(10), ["😀"], {}, set(), deque())
        self.assertEqual(api.call_count, 10)
        chosen = {
            call.args[2]["reaction"][0]["emoji"] for call in api.call_args_list
        }
        self.assertEqual(chosen, set(emojis))

    def test_channel_max_reserves_slot_by_default(self):
        chat = {"max_reaction_count": 11, "available_reactions": None}
        pool = list("😀😁😂🤣😃😄😅😆😉😊😋😎")
        with patch("bot.api_call", return_value=chat):
            reserved = load_chat_context("token", -1001, pool, 20)
            unreserved = load_chat_context("token", -1001, pool, 20, reserve_slots=0)
        self.assertEqual(reserved.limit, 10)
        self.assertEqual(unreserved.limit, 11)

    def test_twenty_bots_all_react_within_ten_distinct_types(self):
        post = {
            "chat": {"id": -1001},
            "message_id": 10,
            "rich_message": {"blocks": [{"type": "paragraph"}]},
        }
        emojis = list("😀😁😂🤣😃😄😅😆😉😊😋😎😍😘")
        context = ChatContext(emojis=emojis, limit=10)
        with patch("bot.get_chat_context", return_value=context), patch(
            "bot.api_call"
        ) as api:
            handle_post(post, self._config(20), emojis, {}, set(), deque())
        self.assertEqual(api.call_count, 20)
        chosen = [call.args[2]["reaction"][0]["emoji"] for call in api.call_args_list]
        self.assertEqual(len(chosen), 20)
        self.assertLessEqual(len(set(chosen)), 10)

    def test_reactions_too_many_retries_with_existing_emoji(self):
        post = {
            "chat": {"id": -1001},
            "message_id": 11,
            "rich_message": {"blocks": [{"type": "paragraph"}]},
        }
        context = ChatContext(emojis=["🔥", "👍"], limit=2)
        calls = []

        def fake_api(token, method, payload, **kwargs):
            calls.append((token, payload["reaction"][0]["emoji"]))
            if len(calls) == 2:
                raise TelegramError(method, 400, "Bad Request: REACTIONS_TOO_MANY")
            return True

        with patch("bot.get_chat_context", return_value=context), patch(
            "bot.api_call", side_effect=fake_api
        ):
            handle_post(post, self._config(2), ["🔥", "👍"], {}, set(), deque())

        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][1], calls[2][1])


if __name__ == "__main__":
    unittest.main()
