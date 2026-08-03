# Hyderabad 22K Gold Price Tracker

Personal, zero-server tracker for the **Hyderabad 22K gold rate per gram (INR)**.

It answers, at a glance:

> Is 22K gold in Hyderabad relatively **cheap or expensive** compared with recent prices?

Example:

```text
₹13,150/g
🟢 NEAR 30D LOW
7% of 30-day range
```

Not merely “what is today’s price?”

## What it does

1. Fetches the Hyderabad 22K gold rate on a schedule (GitHub Actions)
2. Stores historical daily prices in `data/history.json` (no database)
3. Calculates 7D / 30D / 90D / 365D statistics and buyer-oriented range position
4. Sends **event-driven** Telegram alerts (not every run)
5. Publishes a mobile-friendly static dashboard to **GitHub Pages**
6. Costs **₹0/month** on the free GitHub tier for normal personal use

## Architecture

```text
Goodreturns Hyderabad Gold Rate page
            │
            ▼
      Python scraper (GoodReturnsProvider)
            │
            ▼
   Validate / normalize price
            │
     ┌──────┴──────┐
     ▼             ▼
data/history.json   Alert engine
     │             │
     │             ▼
     │        Telegram Bot API
     ▼
 Static dashboard (site/)
     │
     ▼
 GitHub Pages
```

Orchestration: **GitHub Actions only**. No always-on server.

## Example Telegram alerts

**New 30-day low (buyer alert):**

```text
🟢 GOLD BUY ALERT

22K Gold · Hyderabad

₹13,080/g

🔥 NEW 30-DAY LOW

↓ ₹140 today (-1.06%)

30D Range
Low: ₹13,080
High: ₹13,790

Current position: 0%
```

**Near 30-day low:**

```text
🟢 GOLD PRICE ALERT

22K Hyderabad
₹13,150/g

Near 30-Day Low

Current position: 7%
```

**New 30-day high:**

```text
🔴 GOLD PRICE ALERT

22K Hyderabad
₹13,820/g

New 30-Day High
```

## Screenshots

_Add screenshots of the dashboard and a Telegram alert here after your first successful run._

| Dashboard (phone) | Telegram alert |
| --- | --- |
| _TODO_ | _TODO_ |

## How the scraper works

- Provider abstraction: `GoldPriceProvider`
- Implementation: `GoodReturnsProvider` (`src/providers/goodreturns.py`)
- Target page: [Goodreturns Hyderabad gold rates](https://www.goodreturns.in/gold-rates/hyderabad.html)
- Libraries: `requests` + `BeautifulSoup` (no browser automation)

**Current extraction strategies** (verified against live HTML on 2026-08-03):

1. `span#22K-price` price card (preferred)
2. JS `currentMetalPrices['22']`
3. Today’s per-gram table (`Gram=1`, `22K` column)
4. Latest row of the last-10-days table (`22K` column)

Every extraction logs **source + strategy**.

### Robots / terms note

As of 2026-08-03, `User-agent: *` in Goodreturns `robots.txt` does **not** disallow `/gold-rates/`. The `/*-rate*` disallow applies to **Googlebot-News**, not general crawlers. This project uses a polite user-agent, low frequency (2 runs/day), and personal non-commercial use. If Goodreturns blocks automated access later, swap providers (see below)—do not bypass anti-bot protections.

## Validation

Before saving a price:

- must be numeric and positive
- must fall within configurable INR/gram bounds (`MIN_PRICE_INR` / `MAX_PRICE_INR`)
- must not jump more than `MAX_DAILY_CHANGE_PERCENT` vs the last stored price

Suspicious values are **not** saved. The previous valid history is kept. An optional Telegram validation-failure notice can be sent (deduped per day).

## Historical data

File: `data/history.json`

```json
[
  {
    "date": "2026-08-01",
    "price": 13220,
    "source": "goodreturns",
    "fetched_at": "2026-08-01T09:30:00+05:30"
  }
]
```

- Timezone for calendar dates: **Asia/Kolkata**
- One canonical price per calendar day
- Same-day re-runs **update** that day’s record (no duplicates)
- On first run, the provider imports the public **last 10 days** table when available
- No invented / interpolated prices
- Older data is retained as history grows

Dashboard clearly notes when fewer than 30 days of history exist.

## Statistics & buyer classification

Computed metrics include today’s price, yesterday, daily change, and period low/high/average where applicable.

**30-day range position:**

```text
position = (today - 30d_low) / (30d_high - 30d_low) × 100
```

If high == low → position = 50%.

**Buyer classification** (green = relatively cheap for a buyer):

| Position | Label |
| --- | --- |
| 0% | 30D LOW |
| 0–10% | NEAR 30D LOW |
| 10–25% | LOW RANGE |
| 25–75% | NORMAL RANGE |
| 75–90% | HIGH RANGE |
| 90–100% | NEAR 30D HIGH |
| 100% | 30D HIGH |

Daily movement (▲/▼) is shown **separately** and is not confused with buyer status.

## Alerts

Event-driven only (`SEND_DAILY_SUMMARY` defaults to `false`).

Important alerts:

1. New 30-day low
2. Near 30-day low (bottom 10%)
3. New 30-day high
4. Large daily move (`DAILY_MOVE_ALERT_PERCENT`, default 1.0%)

Deduplication state: `data/alert_state.json`

Same alert + same price on the same day is suppressed. **Escalation is allowed**, e.g.:

- morning: `NEAR_30D_LOW`
- afternoon: `NEW_30D_LOW` ← still sent

Priority (higher wins):

`NEW_30D_LOW / NEW_30D_HIGH` > `NEAR_*` > `LARGE_DAILY_MOVE` > summary

Telegram failures never block history updates.

## Configuration

Edit `src/config.py` or set environment variables / GitHub Actions variables:

| Setting | Default | Meaning |
| --- | --- | --- |
| `CITY` | Hyderabad | Display city |
| `KARAT` | 22K | Target purity |
| `NEAR_LOW_PERCENT` | 10 | Near-low band |
| `LOW_RANGE_PERCENT` | 25 | Low-range upper bound |
| `HIGH_RANGE_PERCENT` | 75 | High-range lower bound |
| `NEAR_HIGH_PERCENT` | 90 | Near-high band |
| `DAILY_MOVE_ALERT_PERCENT` | 1.0 | Large-move alert |
| `MAX_DAILY_CHANGE_PERCENT` | 10 | Validation guardrail |
| `SEND_DAILY_SUMMARY` | false | Optional daily digest |
| `TIMEZONE` | Asia/Kolkata | Calendar timezone |

## Telegram setup (beginner-friendly)

You do **not** need to install development tools on your computer.

1. Open **Telegram** on your phone
2. Search for **@BotFather**
3. Send `/newbot`
4. Follow prompts (name + username ending in `bot`)
5. Copy the **bot token** BotFather gives you (looks like `123456:ABC-DEF...`)
6. Open a chat with **your new bot** and press **Start** / send any message (e.g. `hello`)
7. Get your **chat ID** safely:
   - Search Telegram for `@userinfobot` or `@getidsbot`, start it, and copy your numeric ID  
   - Or open (in a browser, after messaging your bot):  
     `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`  
     and find `"chat":{"id": ##########}`
8. Add both values as GitHub Secrets (next section)
9. Run the **Update Gold Price** workflow manually (`workflow_dispatch`)
10. Confirm a Telegram message arrives (or that a real alert condition / failure notice fires)

**Never commit the bot token.** Never put it in the website files.

## GitHub Secrets

Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Yes (for alerts) | Bot API token from BotFather |
| `TELEGRAM_CHAT_ID` | Yes (for alerts) | Your numeric chat ID |

Optional repository **Variables** (not secrets):

- `SEND_DAILY_SUMMARY` = `true` / `false`
- `DAILY_MOVE_ALERT_PERCENT` = `1.0`
- `MAX_DAILY_CHANGE_PERCENT` = `10`

## GitHub Actions

### `update-gold.yml`

Schedule (UTC → IST):

| Cron (UTC) | IST |
| --- | --- |
| `0 4 * * *` | ~09:30 AM |
| `30 9 * * *` | ~03:00 PM |

Also supports **Run workflow** (manual).

Pipeline:

checkout → setup Python → install deps → scrape → validate → update history → stats → alerts → regenerate `site/data/*` → commit data if changed → push

Concurrency: only one gold-price update at a time (`concurrency.group: gold-price-update`).

The update workflow is triggered by schedule / manual dispatch only (not by push), so committing refreshed JSON will not loop the scraper. The Pages deploy workflow still runs when `site/` or `data/` changes.

### `deploy-pages.yml`

Deploys the `site/` folder to GitHub Pages on pushes that touch the site/data.

## GitHub Pages setup

1. Push this repository to GitHub
2. Settings → **Pages**
3. Build and deployment → Source: **GitHub Actions**
4. Run **Deploy GitHub Pages** (or push a change under `site/`)
5. Open: `https://<USERNAME>.github.io/<REPOSITORY>/`

The dashboard loads `./data/history.json` and `./data/stats.json` relative to the site, so project Pages URLs work (not only root domains).

## Manual workflow execution (first run)

1. Open the repo on GitHub
2. **Actions** → **Update Gold Price** → **Run workflow**
3. Wait for the green check
4. Confirm `data/history.json` and `site/data/*` updated in the repo
5. Check Telegram (if secrets are set)
6. Open the Pages URL after deploy

## Running locally (optional)

Not required for normal use.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/update.py --skip-telegram
# or offline:
python scripts/update.py --html tests/fixtures/goodreturns_sample.html --skip-telegram
pytest
python scripts/live_smoke.py   # hits live site
```

## Testing

```bash
pip install -r requirements.txt
pytest -q
```

Unit tests use a **saved HTML fixture** and never call the live website.

Covered areas include:

- 22K extraction, historical table, invalid/unexpected HTML
- duplicate day handling / same-day updates
- 30D low/high/average, range position, equal high/low
- NEW / NEAR low & high alerts, large move, dedupe, escalation

## Troubleshooting

| Problem | What to check |
| --- | --- |
| No Telegram message | Secrets set? Did you Start the bot? Is an alert condition actually met? (`SEND_DAILY_SUMMARY=true` for a daily ping) |
| Workflow fails on scrape | Goodreturns HTML changed — check Actions logs for strategy errors; update `goodreturns.py` / fixture |
| Suspicious price rejected | Large jump vs previous day; adjust `MAX_DAILY_CHANGE_PERCENT` only if intentional |
| Dashboard empty | Run update workflow; ensure Pages deployed from `site/` |
| Wrong karat/city | Confirm strategies still target `#22K-price` / 22K columns for Hyderabad URL |
| Pages 404 on assets | Confirm site is served from `/<repo>/` and relative `data/` paths |

## Replacing Goodreturns with another provider

1. Create `src/providers/your_source.py` implementing `GoldPriceProvider`
2. Implement `fetch_current_price()` and optional `fetch_historical_prices()`
3. Switch the provider in `scripts/update.py`
4. Keep validation, history, stats, alerts, and dashboard unchanged

The app is intentionally **not** coupled to Goodreturns HTML outside the provider module.

## Repository layout

```text
.
├── .github/workflows/
│   ├── update-gold.yml
│   └── deploy-pages.yml
├── src/
│   ├── config.py
│   ├── scraper.py
│   ├── history.py
│   ├── statistics.py
│   ├── alerts.py
│   ├── telegram.py
│   └── providers/
│       ├── base.py
│       └── goodreturns.py
├── data/
│   ├── history.json
│   └── alert_state.json
├── site/
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── data/
├── tests/
├── scripts/
│   ├── update.py
│   └── live_smoke.py
├── requirements.txt
└── README.md
```

## Cost / free-tier notes

Typically **₹0/month**:

- GitHub Actions public-repo minutes / private free allowance (2 short runs/day is tiny)
- GitHub Pages free hosting
- Telegram Bot API free

**Not free / not unlimited forever (be aware):**

- GitHub free-tier **Action minute** quotas (private repos have monthly limits; public is more generous)
- If you later add a paid gold API, SMS gateway, or custom domain DNS extras, those can cost money
- Goodreturns is a third-party website—availability is outside your control

## Disclaimer

Indicative **22K** gold rate for **Hyderabad**. Jewellery retail prices may vary by retailer and may exclude GST, making charges, wastage, and other applicable charges. This project is for personal informational use only—not financial advice.
