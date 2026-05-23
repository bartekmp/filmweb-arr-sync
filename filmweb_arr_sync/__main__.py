import argparse
import logging
import sys

from dotenv import load_dotenv

from .config import load_config
from .scheduler import run_scheduler
from .state import State
from .sync import Syncer


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )
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

    if args.run_once:
        syncer.run()
    else:
        run_scheduler(syncer, config.sync.interval_minutes)


if __name__ == "__main__":
    main()
