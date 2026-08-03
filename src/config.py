"""Central configuration for the gold price tracker."""

from __future__ import annotations

import os
from pathlib import Path

# --- Identity ---
CITY = "Hyderabad"
KARAT = "22K"
CURRENCY = "INR"
UNIT = "gram"
SOURCE_NAME = "goodreturns"
SOURCE_URL = "https://www.goodreturns.in/gold-rates/hyderabad.html"
TIMEZONE = "Asia/Kolkata"

# --- Paths (repo root relative) ---
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
HISTORY_PATH = DATA_DIR / "history.json"
ALERT_STATE_PATH = DATA_DIR / "alert_state.json"
SITE_DIR = REPO_ROOT / "site"
SITE_DATA_DIR = SITE_DIR / "data"
SITE_HISTORY_PATH = SITE_DATA_DIR / "history.json"
SITE_STATS_PATH = SITE_DATA_DIR / "stats.json"

# --- Price validation (INR per gram, 22K) ---
# Configurable bounds; adjust if market levels shift substantially.
MIN_PRICE_INR = float(os.getenv("MIN_PRICE_INR", "5000"))
MAX_PRICE_INR = float(os.getenv("MAX_PRICE_INR", "50000"))
MAX_DAILY_CHANGE_PERCENT = float(os.getenv("MAX_DAILY_CHANGE_PERCENT", "10"))

# --- Buyer classification thresholds (position % in 30-day range) ---
NEAR_LOW_PERCENT = float(os.getenv("NEAR_LOW_PERCENT", "10"))
LOW_RANGE_PERCENT = float(os.getenv("LOW_RANGE_PERCENT", "25"))
HIGH_RANGE_PERCENT = float(os.getenv("HIGH_RANGE_PERCENT", "75"))
NEAR_HIGH_PERCENT = float(os.getenv("NEAR_HIGH_PERCENT", "90"))
EXACT_BOUND_TOLERANCE = float(os.getenv("EXACT_BOUND_TOLERANCE", "0.05"))

# --- Alerts ---
DAILY_MOVE_ALERT_PERCENT = float(os.getenv("DAILY_MOVE_ALERT_PERCENT", "1.0"))
SEND_DAILY_SUMMARY = os.getenv("SEND_DAILY_SUMMARY", "false").lower() in {
    "1",
    "true",
    "yes",
}

# --- Telegram (from environment / GitHub Secrets) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_BASE = "https://api.telegram.org"

# --- HTTP ---
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
HTTP_USER_AGENT = os.getenv(
    "HTTP_USER_AGENT",
    "Mozilla/5.0 (compatible; PersonalGoldTracker/1.0; +https://github.com/)",
)

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
