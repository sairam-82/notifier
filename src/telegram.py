"""Telegram Bot API client."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from src import config

logger = logging.getLogger(__name__)


def send_telegram_message(
    message: str,
    *,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    disable_web_page_preview: bool = True,
    session: Optional[requests.Session] = None,
) -> bool:
    """
    Send a Telegram message via Bot API.

    Returns True on success, False on failure.
    Never raises for API/network errors (caller decides).
    Never logs the bot token.
    """
    token = bot_token if bot_token is not None else config.TELEGRAM_BOT_TOKEN
    chat = chat_id if chat_id is not None else config.TELEGRAM_CHAT_ID

    if not token or not chat:
        logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return False

    url = f"{config.TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": message,
        "disable_web_page_preview": disable_web_page_preview,
    }
    http = session or requests.Session()
    try:
        logger.info("Sending Telegram message (chat configured, len=%d)", len(message))
        resp = http.post(url, json=payload, timeout=config.HTTP_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.error(
                "Telegram API error: status=%s body=%s",
                resp.status_code,
                resp.text[:300],
            )
            return False
        data = resp.json()
        if not data.get("ok"):
            logger.error("Telegram API returned ok=false: %s", str(data)[:300])
            return False
        logger.info("Telegram message sent successfully")
        return True
    except requests.RequestException as exc:
        logger.error("Telegram request failed: %s", exc)
        return False
