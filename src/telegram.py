"""Telegram Bot API client."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from src import config

logger = logging.getLogger(__name__)


def parse_chat_ids(raw: Optional[str] = None) -> list[str]:
    """Split TELEGRAM_CHAT_ID into one or more chat IDs (comma/whitespace separated)."""
    value = raw if raw is not None else config.TELEGRAM_CHAT_ID
    if not value:
        return []
    parts = [p.strip() for p in value.replace(";", ",").split(",")]
    return [p for p in parts if p]


def send_telegram_message(
    message: str,
    *,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    disable_web_page_preview: bool = True,
    session: Optional[requests.Session] = None,
) -> bool:
    """
    Send a Telegram message via Bot API to one or more chats.

    ``chat_id`` may be a single ID or a comma-separated list.
    Returns True if at least one chat succeeded.
    Never raises for API/network errors (caller decides).
    Never logs the bot token.
    """
    token = bot_token if bot_token is not None else config.TELEGRAM_BOT_TOKEN
    chats = parse_chat_ids(chat_id if chat_id is not None else config.TELEGRAM_CHAT_ID)

    if not token or not chats:
        logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return False

    url = f"{config.TELEGRAM_API_BASE}/bot{token}/sendMessage"
    http = session or requests.Session()
    any_ok = False

    for chat in chats:
        payload = {
            "chat_id": chat,
            "text": message,
            "disable_web_page_preview": disable_web_page_preview,
        }
        try:
            logger.info("Sending Telegram message (chat configured, len=%d)", len(message))
            resp = http.post(url, json=payload, timeout=config.HTTP_TIMEOUT_SECONDS)
            if resp.status_code != 200:
                logger.error(
                    "Telegram API error: status=%s body=%s",
                    resp.status_code,
                    resp.text[:300],
                )
                continue
            data = resp.json()
            if not data.get("ok"):
                logger.error("Telegram API returned ok=false: %s", str(data)[:300])
                continue
            logger.info("Telegram message sent successfully")
            any_ok = True
        except requests.RequestException as exc:
            logger.error("Telegram request failed: %s", exc)

    return any_ok
