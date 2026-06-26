import argparse
import logging
import sys

from dotenv import load_dotenv

from .config import Config, load_config
from .scheduler import run_scheduler
from .state import State
from .sync import Syncer

_ICON_OK = "\033[32m✓\033[0m "
_ICON_SKIP = "\033[34m●\033[0m "
_ICON_FAIL = "\033[31m✗\033[0m "


class _TtyFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if sys.stdout.isatty():
            if record.levelno >= logging.WARNING:
                icon = _ICON_FAIL
            elif getattr(record, "status", None) == "ok":
                icon = _ICON_OK
            elif getattr(record, "status", None) == "skip":
                icon = _ICON_SKIP
            else:
                icon = ""
            if icon:
                record = logging.makeLogRecord(record.__dict__)
                record.msg = icon + str(record.msg)
        return super().format(record)


_startup_logger = logging.getLogger(__name__)


def _log_startup_config(config: Config, run_once: bool) -> None:
    lines = [
        "\n",
        "=" * 60,
        "Starting filmweb-arr-sync with configuration:",
        f"  Filmweb user    : {config.filmweb.username}",
        f"  State file      : {config.sync.state_file}",
        f"  Add delay       : {config.sync.add_delay_seconds}s",
    ]
    if not run_once:
        if config.sync.cron:
            lines.append(f"  Sync schedule   : {config.sync.cron} (cron)")
        else:
            lines.append(f"  Sync interval   : {config.sync.interval_minutes} min")
    if config.sync.batch_queue_enabled:
        lines.append(
            f"  Batch queue     : enabled"
            f" ({config.sync.batch_size} items / {config.sync.batch_interval_minutes} min)"
        )
    if config.sync.dry_run:
        lines.append("  Dry run         : yes")

    if config.radarr.enabled and config.radarr.url:
        lines.append(
            f"  Radarr          : {config.radarr.url}"
            f"  (root={config.radarr.root_folder}, quality={config.radarr.quality_profile_id})"
        )
    else:
        lines.append("  Radarr          : disabled")

    if config.sonarr.enabled and config.sonarr.url:
        lang = (
            f", lang={config.sonarr.language_profile_id}"
            if config.sonarr.language_profile_id is not None
            else ""
        )
        lines.append(
            f"  Sonarr          : {config.sonarr.url}"
            f"  (root={config.sonarr.root_folder},"
            f" quality={config.sonarr.quality_profile_id}{lang})"
        )
    else:
        lines.append("  Sonarr          : disabled")

    if config.telegram.enabled and config.telegram.bot_token:
        scope = (
            f"{len(config.telegram.allowed_user_ids)} allowed user(s)"
            if config.telegram.allowed_user_ids
            else "open to all users"
        )
        lines.append(f"  Telegram bot    : enabled ({scope})")
    else:
        lines.append("  Telegram bot    : disabled")

    lines.append("=" * 60)
    _startup_logger.info("\n".join(lines))


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _TtyFormatter(
            fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Filmweb watchlist to Radarr and Sonarr")
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument("--run-once", action="store_true", help="Run one sync pass and exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="Log what would be added without making changes"
    )
    args = parser.parse_args()

    setup_logging()
    load_dotenv()

    config = load_config(args.config)
    if args.dry_run:
        config.sync.dry_run = True

    if not config.filmweb.username:
        logging.critical(
            "Filmweb username is required — set FILMWEB_USERNAME or filmweb.username in config.yaml"
        )
        sys.exit(1)

    state = State(config.sync.state_file)
    syncer = Syncer(config, state)
    _log_startup_config(config, args.run_once)

    if args.run_once:
        syncer.run()
    else:
        run_scheduler(syncer, config)


if __name__ == "__main__":
    main()
