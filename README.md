# filmweb-arr-sync

Watches a [Filmweb.pl](https://www.filmweb.pl) user's **"Want to See"** list and automatically adds new entries to [Radarr](https://radarr.video) (movies) and [Sonarr](https://sonarr.tv) (TV series).

Runs as a daemon on a configurable interval or cron schedule, or as a one-shot CLI command. Designed for homelab Docker Compose stacks.

Optionally runs a [**Telegram bot**](#telegram-bot) so you can add titles on demand by sending a Filmweb or IMDb link.

---

## How it works

```
Filmweb "Want to See"
  └── /api/v1/user/{username}/want2see/film    → Radarr
  └── /api/v1/user/{username}/want2see/serial  → Sonarr
```

Each sync cycle:

1. Fetch the full watchlist from Filmweb (public API, no login required)
2. Skip entries already recorded in the local state file
3. **Phase 1 — lookups:** query Radarr/Sonarr for every new entry by title + year; collect the ones that need adding
4. **Phase 2 — adds:** add collected entries one by one, with a configurable delay between each, to avoid overloading Radarr/Sonarr while they are searching for previously added items
5. Record each successfully added Filmweb ID in the state file so it is never processed again

Items that fail to match or fail to add are **not** recorded, so they are retried on the next sync.

Title matching tries `originalTitle` first (better for TMDb/TVDb), then falls back to the localized `title` — which helps with Japanese films whose romanized original title does not appear in Western databases.

---

## Requirements

- Python 3.12+ (for local use)
- Docker + Docker Compose (for container deployment)
- A Filmweb account with a public username
- Radarr and/or Sonarr running and reachable with an API key

---

## Quick start (Docker Compose)

Add the service to your existing stack:

```yaml
services:
  filmweb-arr-sync:
    build: .
    restart: unless-stopped
    volumes:
      - filmweb_sync_data:/data
    environment:
      FILMWEB_USERNAME: your_filmweb_username

      RADARR_URL: http://radarr:7878
      RADARR_API_KEY: your_radarr_api_key
      RADARR_ROOT_FOLDER: /movies
      RADARR_QUALITY_PROFILE_ID: 1

      SONARR_URL: http://sonarr:8989
      SONARR_API_KEY: your_sonarr_api_key
      SONARR_ROOT_FOLDER: /tv
      SONARR_QUALITY_PROFILE_ID: 1

      SYNC_INTERVAL_MINUTES: 30
      ADD_DELAY_SECONDS: 5

volumes:
  filmweb_sync_data:
```

Then:

```sh
docker compose up -d filmweb-arr-sync
```

> **First run tip:** if you have a large watchlist (100+ items), consider enabling batch queue mode (`BATCH_QUEUE_ENABLED=true`) so Radarr/Sonarr are not overwhelmed during the initial import. See [Batch queue](#batch-queue) below.

---

## Configuration

Configuration can be provided via **environment variables** (recommended for Docker) or a **`config.yaml`** file (see `config.yaml.example`). Environment variables take precedence over the file.

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILMWEB_USERNAME` | Yes | — | Your public Filmweb username |
| `RADARR_URL` | Yes* | — | Radarr base URL, e.g. `http://radarr:7878` |
| `RADARR_API_KEY` | Yes* | — | Radarr API key (Settings → General) |
| `RADARR_ROOT_FOLDER` | Yes* | `/movies` | Root folder path configured in Radarr |
| `RADARR_QUALITY_PROFILE_ID` | No | `1` | Radarr quality profile ID |
| `RADARR_ENABLED` | No | `true` | Set to `false` to disable Radarr sync |
| `RADARR_TAG` | No | `filmweb` | Tag applied to every added movie; set to `""` to disable |
| `SONARR_URL` | Yes* | — | Sonarr base URL, e.g. `http://sonarr:8989` |
| `SONARR_API_KEY` | Yes* | — | Sonarr API key (Settings → General) |
| `SONARR_ROOT_FOLDER` | Yes* | `/tv` | Root folder path configured in Sonarr |
| `SONARR_QUALITY_PROFILE_ID` | No | `1` | Sonarr quality profile ID |
| `SONARR_LANGUAGE_PROFILE_ID` | No | — | Sonarr v3 only; omit for Sonarr v4 |
| `SONARR_ENABLED` | No | `true` | Set to `false` to disable Sonarr sync |
| `SONARR_TAG` | No | `filmweb` | Tag applied to every added show; set to `""` to disable |
| `SYNC_INTERVAL_MINUTES` | No | `30` | How often to poll Filmweb; ignored when `SYNC_CRON` is set |
| `SYNC_CRON` | No | — | Cron expression for sync schedule, e.g. `0 4 * * *` (takes precedence over `SYNC_INTERVAL_MINUTES`) |
| `SYNC_DRY_RUN` | No | `false` | Log what would be added without making changes |
| `ADD_DELAY_SECONDS` | No | `5` | Seconds to wait between adding items (non-batch mode only) |
| `STATE_FILE` | No | `/data/state.json` | Path to the state file |
| `BATCH_QUEUE_ENABLED` | No | `false` | Enable batch queue mode (see below) |
| `BATCH_SIZE` | No | `5` | Items added per batch (batch mode only) |
| `BATCH_INTERVAL_MINUTES` | No | `10` | Minutes to wait between batches (batch mode only) |
| `TELEGRAM_BOT_ENABLED` | No | `false` | Enable the Telegram bot (daemon mode only) |
| `TELEGRAM_BOT_TOKEN` | Yes** | — | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_ALLOWED_USER_IDS` | No | — | Comma-separated numeric user IDs allowed to use the bot; empty = everyone |
| `TELEGRAM_SEARCH_ON_ADD` | No | `true` | Trigger a Radarr/Sonarr search immediately after a bot add |
| `TELEGRAM_POLL_TIMEOUT_SECONDS` | No | `30` | Long-poll timeout for fetching Telegram updates |

*Required only if the respective service is enabled.
**Required only if the Telegram bot is enabled.

### Tagging

By default every movie and show added by this tool is tagged `filmweb` in Radarr/Sonarr. The tag is created automatically if it doesn't exist. This lets you filter, manage, or bulk-delete the items later using Radarr/Sonarr's built-in tag filters.

To use a different tag name:
```
RADARR_TAG: my-watchlist
SONARR_TAG: my-watchlist
```

To disable tagging entirely, set the variable to an empty string:
```
RADARR_TAG: ""
SONARR_TAG: ""
```

---

### Batch queue

By default the sync adds every new item immediately, one by one, with `ADD_DELAY_SECONDS` between each. On a large watchlist this can still send dozens of requests in a short window and cause Radarr/Sonarr to queue a lot of searches at once.

Batch queue mode spreads additions out over time. Enable it with:

```
BATCH_QUEUE_ENABLED=true
BATCH_SIZE=5           # how many items to add per batch (default: 5)
BATCH_INTERVAL_MINUTES=10  # minutes to wait between batches (default: 10)
```

How it works:

- Each sync cycle only does the **lookup** phase and puts new matches into a persistent queue in the state file
- A background thread processes the queue: adds `BATCH_SIZE` items, sleeps `BATCH_INTERVAL_MINUTES`, then repeats until the queue is empty
- The sync interval (`SYNC_INTERVAL_MINUTES`) is completely unaffected — the background thread runs independently
- The queue is persisted to disk, so a container restart picks up where it left off
- Items that fail to add are **not** marked as processed and will be re-queued on the next sync (same behaviour as the default mode)

---

### Telegram bot

In addition to the scheduled watchlist sync, the daemon can run a Telegram bot so you can add titles **on demand** by sending a link. Paste a Filmweb or IMDb link and the bot adds the movie to Radarr or the series to Sonarr.

**Setup:**

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`, and copy the token it gives you.
2. Find your numeric Telegram user ID (e.g. message [@userinfobot](https://t.me/userinfobot)).
3. Enable the bot in your config:

```
TELEGRAM_BOT_ENABLED: "true"
TELEGRAM_BOT_TOKEN: "123456:ABC-your-bot-token"
TELEGRAM_ALLOWED_USER_IDS: "11111111"   # restrict to your own user ID
```

> **Restrict access.** Anyone who finds your bot can message it. Set `TELEGRAM_ALLOWED_USER_IDS` to your own ID (comma-separate multiple IDs) so only you can add titles. If left empty, the bot responds to everyone.

**Usage:**

Send the bot a link, for example:

```
https://www.filmweb.pl/film/Incepcja-2010-468741      → added to Radarr
https://www.filmweb.pl/serial/Wiedzmin-2019-668941    → added to Sonarr
https://www.imdb.com/title/tt1375666/                 → resolved and added
```

- **Filmweb links** carry the type (`/film/` → Radarr, `/serial/` → Sonarr); details are fetched from Filmweb's public API and matched the same way the scheduled sync does. Successfully added Filmweb IDs are recorded in the state file, so the scheduler won't add them again.
- **IMDb links** don't say whether a title is a movie or a series, so the bot looks it up in Radarr first, then Sonarr.
- Anything that isn't a recognised Filmweb or IMDb link is **rejected**.

**Commands:**

| Command | Description |
|---|---|
| `/help`, `/start` | Show usage |
| `/last_sync` | When the scheduled watchlist sync last completed |
| `/stats` | How many movies/series have been processed |

> **Note:** The bot uses Telegram long-polling and only runs in daemon mode (not with `--run-once`). No inbound ports or webhooks are required.

> **Filmweb watchlist write-back.** Adding a title back to your Filmweb "Want to see" list is **not yet implemented** — Filmweb has no official write API, so it requires an authenticated, undocumented endpoint. The bot has a pluggable hook (`filmweb_arr_sync/bot/watchlist.py`) where an authenticated implementation can be dropped in later; for now the bot adds to Radarr/Sonarr only.

---

### Health check

The daemon exposes a lightweight HTTP endpoint on port **8080**:

```
GET http://localhost:8080/health
```

Response (always `200 OK`):
```json
{"status": "ok", "last_sync_at": "2026-05-24T19:00:47+00:00"}
```

`last_sync_at` is `null` until the first sync completes. The Docker image includes a `HEALTHCHECK` directive that polls this endpoint every 60 seconds, so container orchestration tools (Compose, Portainer, Uptime Kuma) will report the container as healthy once it is running.

To expose the port externally, uncomment the `ports` entry in `docker-compose.yml`.

> **Note:** The health endpoint is only started in daemon mode. It is not available when using `--run-once`.

---

### Finding quality profile IDs

In Radarr/Sonarr, go to **Settings → Quality Profiles** and count the ordinal number of a profile, or use the API:

```sh
curl http://radarr:7878/api/v3/qualityprofile?apikey=YOUR_KEY
```

---

## Local development

```sh
# Install dependencies
pip install -r requirements-dev.txt

# Copy and fill in the example env file
cp .env.example .env
# edit .env — set STATE_FILE=./data/state.json for a local path

# Preview what would be synced (no changes made)
python main.py --run-once --dry-run

# Run one real sync pass and exit
python main.py --run-once

# Run as a daemon (syncs every SYNC_INTERVAL_MINUTES)
python main.py

# Use a config file instead of env vars
python main.py --config config.yaml --run-once --dry-run
```

### Running tests

```sh
pytest tests/ -v
```

---

## State file

The state file (`/data/state.json` by default) records every Filmweb ID that has been successfully processed. On each sync, already-processed IDs are skipped entirely — no Filmweb `/info` call, no Radarr/Sonarr lookup.

**Resetting the state** (e.g. after reinstalling Radarr/Sonarr):

```sh
# Docker
docker compose run --rm filmweb-arr-sync sh -c "rm /data/state.json"

# Local
rm data/state.json
```

---

## Known limitations

- **Title matching is fuzzy** — the sync uses Radarr/Sonarr's own search, so a very obscure or ambiguously-titled entry may match the wrong result. Use `--dry-run` to review matches before committing.
- **Upcoming films** — entries added to your Filmweb watchlist before a film is indexed in TMDb/TVDb will not match and will be retried each sync until the entry appears in the database.
- **Duplicate editions** — if two separate Filmweb entries (e.g. a 2001 series and a 2006 OVA) resolve to the same TVDb entry, only one will be added; the other is silently skipped as a duplicate.
- **No removal sync** — removing an entry from your Filmweb list does not remove it from Radarr/Sonarr.

---

## Project structure

```
filmweb_arr_sync/
├── __main__.py         — CLI entry point (also enables python -m filmweb_arr_sync)
├── config.py           — loads config from YAML and environment variables
├── state.py            — JSON state file (tracks processed and pending Filmweb IDs)
├── sync.py             — two-phase sync orchestration (lookup → add / enqueue)
├── batch_processor.py  — background thread for batch queue mode
├── scheduler.py        — daemon loop with graceful SIGTERM/SIGINT shutdown
├── health.py           — HTTP health check server (:8080/health)
├── filmweb/
│   ├── client.py  — Filmweb public API client
│   └── models.py  — FilmwebItem dataclass
├── arr/
│   ├── radarr.py  — Radarr REST API client
│   └── sonarr.py  — Sonarr REST API client
└── bot/
    ├── runner.py     — Telegram long-polling loop (background thread)
    ├── telegram.py   — minimal Telegram Bot API client
    ├── handler.py    — message/command handling → Radarr/Sonarr adds
    ├── links.py      — Filmweb/IMDb link parsing and validation
    └── watchlist.py  — pluggable Filmweb watchlist write-back hook
tests/             — pytest unit tests (no network required)
```
