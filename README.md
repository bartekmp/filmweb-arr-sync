# filmweb-arr-sync

Watches a [Filmweb.pl](https://www.filmweb.pl) user's **"Want to See"** list and automatically adds new entries to [Radarr](https://radarr.video) (movies) and [Sonarr](https://sonarr.tv) (TV series).

Runs as a daemon on a configurable interval, or as a one-shot CLI command. Designed for homelab Docker Compose stacks.

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

> **First run tip:** if you have a large watchlist (100+ items), set `ADD_DELAY_SECONDS` to `10`–`15` for the initial import so Radarr/Sonarr are not overwhelmed. You can lower it once the bulk import is done.

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
| `SYNC_INTERVAL_MINUTES` | No | `30` | How often to poll Filmweb (daemon mode) |
| `SYNC_DRY_RUN` | No | `false` | Log what would be added without making changes |
| `ADD_DELAY_SECONDS` | No | `5` | Seconds to wait between adding items to Radarr/Sonarr |
| `STATE_FILE` | No | `/data/state.json` | Path to the state file |

*Required only if the respective service is enabled.

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
├── __main__.py    — CLI entry point (also enables python -m filmweb_arr_sync)
├── config.py      — loads config from YAML and environment variables
├── state.py       — JSON state file (tracks processed Filmweb IDs)
├── sync.py        — two-phase sync orchestration (lookup → add)
├── scheduler.py   — daemon loop with graceful SIGTERM/SIGINT shutdown
├── health.py      — HTTP health check server (:8080/health)
├── filmweb/
│   ├── client.py  — Filmweb public API client
│   └── models.py  — FilmwebItem dataclass
└── arr/
    ├── radarr.py  — Radarr REST API client
    └── sonarr.py  — Sonarr REST API client
tests/             — pytest unit tests (no network required)
```
