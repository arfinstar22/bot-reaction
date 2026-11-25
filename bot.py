#!/usr/bin/env python3
"""Auto-reaction bot untuk satu channel Telegram.

Setiap bot memasang satu reaction pada setiap post rich article baru. Jumlah
reaction mengikuti isi TG_TOKENS, sedangkan jumlah jenis emoji unik dibatasi
max_reaction_count channel (bisa menyisakan slot via RESERVE_SLOTS). Hanya bot
pertama yang menerima update lewat webhook atau getUpdates; semua token dipakai
untuk memanggil setMessageReaction.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
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
POLL_TIMEOUT = 30
REQUEST_TIMEOUT = 15
CONTEXT_TTL = 3600
MEDIA_GROUP_LIMIT = 1000
UPDATE_ID_LIMIT = 1000
MAX_WEBHOOK_BODY = 1024 * 1024
WEBHOOK_PATH = "/webhook"

log = logging.getLogger("reactionbot")
session = requests.Session()


class TelegramError(RuntimeError):
    def __init__(
        self,
        method: str,
        code: int,
        description: str,
        retry_after: int = 0,
    ) -> None:
        super().__init__(f"{method}: {code} {description}")
        self.method = method
        self.code = code
        self.description = description
        self.retry_after = retry_after


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
    reaction_count: int
    reserve_slots: int = 1


@dataclass
class ChatContext:
    emojis: list[str]
    limit: int
    fetched_at: float = field(default_factory=time.monotonic)


@dataclass
class WebhookState:
    secret_token: str
    post_queue: queue.Queue[dict[str, Any]] = field(default_factory=queue.Queue)
    ready: threading.Event = field(default_factory=threading.Event)
    seen_lock: threading.Lock = field(default_factory=threading.Lock)
    seen_updates: set[int] = field(default_factory=set)
    update_order: deque[int] = field(default_factory=deque)

    def accept_update(self, update: dict[str, Any]) -> bool:
        """Catat update_id agar retry webhook tidak memicu reaction ganda."""
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            with self.seen_lock:
                if update_id in self.seen_updates:
                    return False
                self.seen_updates.add(update_id)
                self.update_order.append(update_id)
                if len(self.update_order) > UPDATE_ID_LIMIT:
                    self.seen_updates.discard(self.update_order.popleft())

        post = update.get("channel_post")
        if isinstance(post, dict):
            self.post_queue.put(post)
        return True


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._respond(200, b"ok", "text/plain")

    def do_HEAD(self) -> None:
        self._respond(200, b"ok", "text/plain")

    def do_POST(self) -> None:
        state: WebhookState | None = getattr(self.server, "webhook_state", None)
        path = self.path.split("?", 1)[0]
        if state is None or path != WEBHOOK_PATH:
            self._respond(404, b'{"ok":false}', "application/json")
            return

        provided = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided, state.secret_token):
            self._respond(403, b'{"ok":false}', "application/json")
            return

        if not state.ready.wait(timeout=10):
            self._respond(503, b'{"ok":false,"error":"starting"}', "application/json")
            return

        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError:
            self._respond(400, b'{"ok":false}', "application/json")
            return
        if length < 0:
            self._respond(400, b'{"ok":false}', "application/json")
            return
        if length > MAX_WEBHOOK_BODY:
            self._respond(413, b'{"ok":false}', "application/json")
            return

        body = self.rfile.read(length)
        try:
            update = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._respond(400, b'{"ok":false}', "application/json")
            return
        if not isinstance(update, dict):
            self._respond(400, b'{"ok":false}', "application/json")
            return

        state.accept_update(update)
        self._respond(200, b'{"ok":true}', "application/json")

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("health: " + format, *args)


def start_health_server(
    webhook_state: WebhookState | None = None,
) -> ThreadingHTTPServer | None:
    """Buka port HTTP untuk health check Render, keepalive cron, dan webhook."""
    raw_port = os.getenv("PORT", "").strip()
    if not raw_port:
        return None
    try:
        port = int(raw_port)
    except ValueError:
        raise SystemExit(f"PORT tidak valid: {raw_port!r}")

    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.webhook_state = webhook_state  # type: ignore[attr-defined]
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
        params = data.get("parameters")
        raw_retry = params.get("retry_after", 0) if isinstance(params, dict) else 0
        try:
            retry_after = max(0, int(raw_retry))
        except (TypeError, ValueError):
            retry_after = 0
        raise TelegramError(
            method,
            int(data.get("error_code", 0)),
            str(data.get("description", "unknown error")),
            retry_after=retry_after,
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
    if not tokens:
        raise SystemExit(
            "TG_TOKENS kosong. Isi minimal satu token bot dari @BotFather, dipisah koma."
        )
    if len(set(tokens)) != len(tokens):
        raise SystemExit(
            f"TG_TOKENS berisi token duplikat. Pakai {len(tokens)} token bot berbeda."
        )

    channel_id = os.getenv("CHANNEL_ID", "").strip() or None
    reactions_file = Path(
        os.getenv("REACTIONS_FILE", str(DEFAULT_REACTIONS_FILE))
    ).expanduser()
    if not reactions_file.is_absolute():
        reactions_file = BASE_DIR / reactions_file

    raw_reserve = os.getenv("RESERVE_SLOTS", "1").strip() or "1"
    try:
        reserve_slots = max(0, int(raw_reserve))
    except ValueError:
        raise SystemExit(f"RESERVE_SLOTS tidak valid: {raw_reserve!r}")

    return Config(
        bots=[Bot(token=token) for token in tokens],
        channel_id=channel_id,
        reactions_file=reactions_file,
        reaction_count=len(tokens),
        reserve_slots=reserve_slots,
    )


def authenticate(bots: list[Bot]) -> None:
    for bot in bots:
        me = api_call(bot.token, "getMe")
        bot.id = int(me["id"])
        bot.username = str(me.get("username", ""))
        log.info("login %s (id=%s)", bot.label, bot.id)

    ids = [bot.id for bot in bots]
    if len(set(ids)) != len(ids):
        raise SystemExit(
            f"Ada token bot yang sama. Pakai {len(bots)} token bot berbeda."
        )


def resolve_webhook_base() -> str | None:
    """Tentukan base URL webhook dari WEBHOOK_URL atau RENDER_EXTERNAL_URL."""
    explicit = os.getenv("WEBHOOK_URL", "").strip()
    if explicit.lower() in ("off", "false", "0", "polling"):
        return None

    has_port = bool(os.getenv("PORT", "").strip())
    if explicit:
        if not has_port:
            raise SystemExit("WEBHOOK_URL butuh PORT terisi.")
        if not explicit.startswith(("https://", "http://")):
            raise SystemExit(f"WEBHOOK_URL tidak valid: {explicit!r}")
        return explicit.rstrip("/")

    if not has_port:
        return None
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if render_url.startswith(("https://", "http://")):
        return render_url.rstrip("/")
    return None


def derive_webhook_secret(controller_token: str) -> str:
    custom = os.getenv("WEBHOOK_SECRET", "").strip()
    if custom:
        return custom
    return hashlib.sha256(f"reactionbot:{controller_token}".encode("utf-8")).hexdigest()[:32]


def set_webhook(token: str, url: str, secret_token: str) -> None:
    api_call(
        token,
        "setWebhook",
        {
            "url": url,
            "secret_token": secret_token,
            "allowed_updates": ["channel_post"],
            "drop_pending_updates": False,
        },
    )
    log.info("mode webhook aktif: %s", url)


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

    channel_max = _parse_channel_max(chat, min(cfg.reaction_count, 11))
    distinct_cap = _distinct_limit(channel_max, None, cfg.reserve_slots)
    if channel_max <= 0:
        log.warning("channel menonaktifkan reaction (max_reaction_count=0)")
    elif len(cfg.bots) > distinct_cap:
        log.info(
            "%d bot terdaftar; maks %d jenis reaction/post (limit channel=%d, "
            "reserve=%d, bot selebihnya menumpuk emoji yang sama)",
            len(cfg.bots),
            distinct_cap,
            channel_max,
            cfg.reserve_slots,
        )

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


def _parse_channel_max(chat: dict[str, Any], default: int) -> int:
    """Ambil max_reaction_count channel dari respons getChat dengan fallback aman."""
    raw = chat.get("max_reaction_count")
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


def _distinct_limit(
    channel_max: int,
    available_count: int | None,
    reserve_slots: int,
) -> int:
    """Hitung batas jenis emoji unik untuk bot ini, sisakan slot untuk bot lain."""
    if channel_max <= 0 or (available_count is not None and available_count <= 0):
        return 0
    cap = max(1, channel_max - reserve_slots) if channel_max > 1 else channel_max
    return cap if available_count is None else min(cap, available_count)


def pick_reactions(
    pool: list[str],
    count: int,
    max_distinct: int | None = None,
) -> list[str]:
    if count <= 0 or not pool:
        return []
    distinct_cap = len(pool) if max_distinct is None else min(max_distinct, len(pool))
    if distinct_cap <= 0:
        return []
    allowed = random.sample(pool, k=distinct_cap)
    if count <= len(allowed):
        return random.sample(allowed, k=count)
    return random.choices(allowed, k=count)


def load_chat_context(
    token: str,
    chat_id: int | str,
    pool: list[str],
    reaction_count: int,
    reserve_slots: int = 1,
) -> ChatContext:
    chat = api_call(token, "getChat", {"chat_id": chat_id})

    max_count = _parse_channel_max(chat, min(reaction_count, 11))
    emojis = filter_pool(pool, chat.get("available_reactions"))
    limit = _distinct_limit(max_count, len(emojis), reserve_slots)
    log.info(
        "channel %s: %d emoji cocok, maks %d jenis reaction/post (channel=%d, reserve=%d)",
        chat_id,
        len(emojis),
        limit,
        max_count,
        reserve_slots,
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

    context = load_chat_context(
        cfg.bots[0].token, chat_id, pool, cfg.reaction_count, cfg.reserve_slots
    )
    cache[chat_id] = context
    return context


def _set_reaction(token: str, chat_id: int | str, message_id: int, emoji: str) -> None:
    """Pasang satu reaction emoji ke pesan channel."""
    api_call(
        token,
        "setMessageReaction",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
        },
    )


def initial_offset(token: str) -> int:
    updates = api_call(token, "getUpdates", {"offset": -1, "timeout": 0})
    if not updates:
        return 0
    return int(updates[-1]["update_id"]) + 1


def _react_with_fallback(
    bot: Bot,
    chat_id: int | str,
    message_id: int,
    emoji: str,
    succeeded: list[str],
    cache: dict[int | str, ChatContext],
) -> str | None:
    target = emoji
    try:
        _set_reaction(bot.token, chat_id, message_id, target)
        return target
    except TelegramError as exc:
        if exc.code == 429 and 0 < exc.retry_after <= 10:
            time.sleep(exc.retry_after)
            try:
                _set_reaction(bot.token, chat_id, message_id, target)
                return target
            except TelegramError as retry_exc:
                exc = retry_exc

        if "REACTION_INVALID" in exc.description:
            cache.pop(chat_id, None)

        alternatives = [item for item in succeeded if item != target]
        if alternatives and (
            "REACTIONS_TOO_MANY" in exc.description
            or "REACTION_INVALID" in exc.description
        ):
            target = random.choice(alternatives)
            try:
                _set_reaction(bot.token, chat_id, message_id, target)
                return target
            except TelegramError as retry_exc:
                exc = retry_exc

        log.error(
            "%s gagal reaction %s di post %s: %s",
            bot.label,
            target,
            message_id,
            exc,
        )
        return None


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

    chosen = pick_reactions(context.emojis, len(cfg.bots), context.limit)
    succeeded: list[str] = []
    for bot, emoji in zip(cfg.bots, chosen):
        placed = _react_with_fallback(
            bot, chat_id, post["message_id"], emoji, succeeded, cache
        )
        if placed is not None:
            succeeded.append(placed)

    if succeeded:
        log.info("post %s: %s", post.get("message_id"), " ".join(succeeded))


def serve_webhook(cfg: Config, pool: list[str], state: WebhookState) -> None:
    """Proses channel_post dari antrean webhook secara serial."""
    cache: dict[int | str, ChatContext] = {}
    seen_media_groups: set[str] = set()
    media_group_order: deque[str] = deque()
    log.info("webhook siap; menunggu post baru")

    while True:
        post = state.post_queue.get()
        try:
            handle_post(
                post,
                cfg,
                pool,
                cache,
                seen_media_groups,
                media_group_order,
            )
        except Exception:
            log.exception("gagal memproses update webhook post %s", post.get("message_id"))


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

    cfg = load_config()
    pool = load_reactions(cfg.reactions_file)
    webhook_base = resolve_webhook_base()
    webhook_state = (
        WebhookState(secret_token=derive_webhook_secret(cfg.bots[0].token))
        if webhook_base
        else None
    )
    start_health_server(webhook_state)

    log.info("memuat %d bot", len(cfg.bots))
    authenticate(cfg.bots)
    log.info("%d emoji tersedia di %s", len(pool), cfg.reactions_file)

    if webhook_state and webhook_base:
        set_webhook(
            cfg.bots[0].token,
            f"{webhook_base}{WEBHOOK_PATH}",
            webhook_state.secret_token,
        )
        webhook_state.ready.set()
        check_channel(cfg)
        try:
            serve_webhook(cfg, pool, webhook_state)
        except KeyboardInterrupt:
            log.info("berhenti")
        return

    delete_webhook(cfg.bots[0].token)
    check_channel(cfg)

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
