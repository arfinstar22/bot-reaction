#!/usr/bin/env python3
"""Auto-reaction bot untuk satu channel Telegram.

Lima bot memasang satu reaction pada setiap post rich article baru. Hanya bot
pertama yang menerima update lewat getUpdates; kelima token dipakai untuk
memanggil setMessageReaction.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
API_URL = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_REACTIONS_FILE = BASE_DIR / "reactions.txt"
REACTION_COUNT = 5
POLL_TIMEOUT = 30
REQUEST_TIMEOUT = 15
CONTEXT_TTL = 3600
MEDIA_GROUP_LIMIT = 1000

log = logging.getLogger("reactionbot")
session = requests.Session()


class TelegramError(RuntimeError):
    def __init__(self, method: str, code: int, description: str) -> None:
        super().__init__(f"{method}: {code} {description}")
        self.method = method
        self.code = code
        self.description = description


@dataclass
class Bot:
    token: str
    id: int = 0
    username: str = ""

    @property
    def label(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.token.split(":", 1)[0]


@dataclass
class Config:
    bots: list[Bot]
    channel_id: str | None
    reactions_file: Path


@dataclass
class ChatContext:
    emojis: list[str]
    limit: int
    fetched_at: float = field(default_factory=time.monotonic)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._respond()

    def do_HEAD(self) -> None:
        self._respond()

    def _respond(self) -> None:
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("health: " + format, *args)


def start_health_server() -> ThreadingHTTPServer | None:
    """Buka port HTTP untuk health check Render dan keepalive cron."""
    raw_port = os.getenv("PORT", "").strip()
    if not raw_port:
        return None
    try:
        port = int(raw_port)
    except ValueError:
        raise SystemExit(f"PORT tidak valid: {raw_port!r}")

    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, name="health", daemon=True)
    thread.start()
    log.info("health server di port %d", port)
    return server


def api_call(
    token: str,
    method: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = REQUEST_TIMEOUT,
) -> Any:
    url = API_URL.format(token=token, method=method)
    try:
        response = session.post(url, json=payload or {}, timeout=timeout)
    except requests.RequestException as exc:
        raise TelegramError(method, 0, f"network error: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise TelegramError(method, response.status_code, "respons bukan JSON") from exc

    if not data.get("ok"):
        raise TelegramError(
            method,
            int(data.get("error_code", 0)),
            str(data.get("description", "unknown error")),
        )
    return data.get("result")


def normalize_emoji(emoji: str) -> str:
    return emoji.replace("\ufe0f", "").replace("\ufe0e", "").strip()


def load_reactions(path: Path) -> list[str]:
    if not path.is_file():
        raise SystemExit(f"File reaction tidak ditemukan: {path}")

    emojis: list[str] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        emoji = raw_line.strip()
        if not emoji or emoji.startswith("#"):
            continue
        key = normalize_emoji(emoji)
        if not key or key in seen:
            continue
        seen.add(key)
        emojis.append(emoji)

    if not emojis:
        raise SystemExit(f"Tidak ada emoji di {path}")
    return emojis


def load_config() -> Config:
    load_dotenv(BASE_DIR / ".env")

    raw_tokens = os.getenv("TG_TOKENS", "")
    tokens = [token.strip() for token in raw_tokens.split(",") if token.strip()]
    if len(tokens) != REACTION_COUNT:
        raise SystemExit(
            f"TG_TOKENS harus berisi {REACTION_COUNT} token bot, dipisah koma. "
            f"Sekarang: {len(tokens)}."
        )
    if len(set(tokens)) != len(tokens):
        raise SystemExit("TG_TOKENS berisi token duplikat. Pakai 5 bot berbeda.")

    channel_id = os.getenv("CHANNEL_ID", "").strip() or None
    reactions_file = Path(
        os.getenv("REACTIONS_FILE", str(DEFAULT_REACTIONS_FILE))
    ).expanduser()
    if not reactions_file.is_absolute():
        reactions_file = BASE_DIR / reactions_file

    return Config(
        bots=[Bot(token=token) for token in tokens],
        channel_id=channel_id,
        reactions_file=reactions_file,
    )


def authenticate(bots: list[Bot]) -> None:
    for bot in bots:
        me = api_call(bot.token, "getMe")
        bot.id = int(me["id"])
        bot.username = str(me.get("username", ""))
        log.info("login %s (id=%s)", bot.label, bot.id)

    ids = [bot.id for bot in bots]
    if len(set(ids)) != len(ids):
        raise SystemExit("Ada token bot yang sama. Pakai 5 bot berbeda.")


def delete_webhook(token: str) -> None:
    api_call(token, "deleteWebhook", {"drop_pending_updates": False})
    log.info("mode polling aktif; webhook bot controller dihapus")


def matches_channel(channel_id: str | None, chat: dict[str, Any]) -> bool:
    if not channel_id:
        return True
    target = channel_id.strip()
    if target.startswith("@"):
        return str(chat.get("username", "")).lower() == target[1:].lower()
    return str(chat.get("id", "")) == target


def is_article_post(post: dict[str, Any]) -> bool:
    """True hanya untuk rich message, bukan stiker atau post biasa."""
    if post.get("sticker") is not None:
        return False
    rich_message = post.get("rich_message")
    return isinstance(rich_message, dict) and bool(rich_message)


def check_channel(cfg: Config) -> None:
    if not cfg.channel_id:
        log.info("CHANNEL_ID kosong; cek admin channel dilewati")
        return

    target = cfg.channel_id.strip()
    if target.lstrip("-").isdigit() and not target.startswith("-100"):
        raise SystemExit(
            "CHANNEL_ID numerik harus diawali -100, contoh -1003955448047. "
            "Jangan pakai angka tanpa prefix -100."
        )

    chat = api_call(cfg.bots[0].token, "getChat", {"chat_id": cfg.channel_id})
    log.info("channel: %s (id=%s)", chat.get("title"), chat.get("id"))

    available = chat.get("available_reactions")
    if available is None:
        log.info("reaction channel: semua emoji standar")
    else:
        log.info("reaction channel: %d tipe dipilih", len(available))
    log.info("max reaction types: %s", chat.get("max_reaction_count"))

    missing: list[str] = []
    for bot in cfg.bots:
        try:
            member = api_call(
                cfg.bots[0].token,
                "getChatMember",
                {"chat_id": cfg.channel_id, "user_id": bot.id},
            )
        except TelegramError as exc:
            log.error("%s: cek admin gagal: %s", bot.label, exc)
            missing.append(bot.label)
            continue

        status = member.get("status")
        if status not in ("administrator", "creator"):
            log.error("%s bukan admin channel (status=%s)", bot.label, status)
            missing.append(bot.label)
        else:
            log.info("%s admin ok", bot.label)

    if missing:
        log.error(
            "bot belum admin: %s. Tambahkan lewat Channel > Administrators.",
            ", ".join(missing),
        )


def filter_pool(
    pool: list[str],
    available_reactions: list[dict[str, Any]] | None,
) -> list[str]:
    if available_reactions is None:
        return list(pool)

    by_key: dict[str, str] = {}
    for reaction in available_reactions:
        if reaction.get("type") != "emoji":
            continue
        emoji = reaction.get("emoji", "")
        if isinstance(emoji, str) and emoji:
            by_key[normalize_emoji(emoji)] = emoji

    result: list[str] = []
    seen: set[str] = set()
    for emoji in pool:
        key = normalize_emoji(emoji)
        canonical = by_key.get(key)
        if canonical is None or key in seen:
            continue
        seen.add(key)
        result.append(canonical)
    return result


def pick_reactions(pool: list[str], count: int) -> list[str]:
    if count <= 0 or not pool:
        return []
    return random.sample(pool, k=min(count, len(pool)))


def load_chat_context(
    token: str,
    chat_id: int | str,
    pool: list[str],
) -> ChatContext:
    chat = api_call(token, "getChat", {"chat_id": chat_id})

    max_count = chat.get("max_reaction_count", REACTION_COUNT)
    try:
        max_count = int(max_count)
    except (TypeError, ValueError):
        max_count = REACTION_COUNT

    emojis = filter_pool(pool, chat.get("available_reactions"))
    limit = max(0, min(REACTION_COUNT, max_count, len(emojis)))
    log.info(
        "channel %s: %d emoji cocok, limit %d reaction/post",
        chat_id,
        len(emojis),
        limit,
    )
    return ChatContext(emojis=emojis, limit=limit)


def get_chat_context(
    chat_id: int | str,
    cfg: Config,
    pool: list[str],
    cache: dict[int | str, ChatContext],
) -> ChatContext:
    cached = cache.get(chat_id)
    if cached and time.monotonic() - cached.fetched_at < CONTEXT_TTL:
        return cached

    context = load_chat_context(cfg.bots[0].token, chat_id, pool)
    cache[chat_id] = context
    return context


def initial_offset(token: str) -> int:
    updates = api_call(token, "getUpdates", {"offset": -1, "timeout": 0})
    if not updates:
        return 0
    return int(updates[-1]["update_id"]) + 1


def handle_post(
    post: dict[str, Any],
    cfg: Config,
    pool: list[str],
    cache: dict[int | str, ChatContext],
    seen_media_groups: set[str],
    media_group_order: deque[str],
) -> None:
    chat = post.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None or not matches_channel(cfg.channel_id, chat):
        return

    if not is_article_post(post):
        log.debug(
            "skip post %s: bukan rich article",
            post.get("message_id"),
        )
        return

    media_group_id = post.get("media_group_id")
    if media_group_id:
        if media_group_id in seen_media_groups:
            return
        seen_media_groups.add(media_group_id)
        media_group_order.append(media_group_id)
        if len(media_group_order) > MEDIA_GROUP_LIMIT:
            seen_media_groups.discard(media_group_order.popleft())

    try:
        context = get_chat_context(chat_id, cfg, pool, cache)
    except TelegramError as exc:
        log.error("gagal ambil info channel %s: %s", chat_id, exc)
        return

    if context.limit <= 0:
        log.warning(
            "channel %s: reaction nonaktif, limit 0, atau tidak ada emoji yang cocok",
            chat_id,
        )
        return

    chosen = pick_reactions(context.emojis, context.limit)
    if len(chosen) < REACTION_COUNT:
        log.warning(
            "channel %s: hanya bisa pasang %d reaction (limit channel)",
            chat_id,
            len(chosen),
        )

    for bot, emoji in zip(cfg.bots, chosen):
        try:
            api_call(
                bot.token,
                "setMessageReaction",
                {
                    "chat_id": chat_id,
                    "message_id": post["message_id"],
                    "reaction": [{"type": "emoji", "emoji": emoji}],
                },
            )
        except TelegramError as exc:
            log.error(
                "%s gagal reaction %s di post %s: %s",
                bot.label,
                emoji,
                post.get("message_id"),
                exc,
            )

    log.info("post %s: %s", post.get("message_id"), " ".join(chosen))


def poll(cfg: Config, pool: list[str]) -> None:
    controller = cfg.bots[0]
    offset = initial_offset(controller.token)
    log.info("offset awal %s; menunggu post baru", offset)

    cache: dict[int | str, ChatContext] = {}
    seen_media_groups: set[str] = set()
    media_group_order: deque[str] = deque()

    while True:
        try:
            updates = api_call(
                controller.token,
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": POLL_TIMEOUT,
                    "allowed_updates": ["channel_post"],
                },
                timeout=POLL_TIMEOUT + 10,
            )
        except TelegramError as exc:
            log.error("polling gagal: %s", exc)
            time.sleep(5)
            continue

        if not isinstance(updates, list):
            log.error("respons getUpdates tidak valid")
            time.sleep(5)
            continue

        for update in updates:
            offset = int(update["update_id"]) + 1
            post = update.get("channel_post")
            if post:
                handle_post(
                    post,
                    cfg,
                    pool,
                    cache,
                    seen_media_groups,
                    media_group_order,
                )


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    start_health_server()

    cfg = load_config()
    log.info("memuat %d bot", len(cfg.bots))
    authenticate(cfg.bots)
    delete_webhook(cfg.bots[0].token)
    check_channel(cfg)

    pool = load_reactions(cfg.reactions_file)
    log.info("%d emoji tersedia di %s", len(pool), cfg.reactions_file)

    try:
        poll(cfg, pool)
    except KeyboardInterrupt:
        log.info("berhenti")


if __name__ == "__main__":
    try:
        main()
    except TelegramError as exc:
        log.error("fatal: %s", exc)
        raise SystemExit(1)
