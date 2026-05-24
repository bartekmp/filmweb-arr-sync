import os
from dataclasses import dataclass, field

import yaml


@dataclass
class FilmwebConfig:
    username: str


@dataclass
class RadarrConfig:
    url: str
    api_key: str
    root_folder: str
    quality_profile_id: int = 1
    enabled: bool = True
    tag: str = "filmweb"


@dataclass
class SonarrConfig:
    url: str
    api_key: str
    root_folder: str
    quality_profile_id: int = 1
    language_profile_id: int | None = None  # required for Sonarr v3, ignored by v4
    enabled: bool = True
    tag: str = "filmweb"


@dataclass
class SyncConfig:
    interval_minutes: int = 30
    dry_run: bool = False
    state_file: str = "/data/state.json"
    add_delay_seconds: int = 5


@dataclass
class Config:
    filmweb: FilmwebConfig
    radarr: RadarrConfig
    sonarr: SonarrConfig
    sync: SyncConfig = field(default_factory=SyncConfig)


def _env_bool(env_key: str, fallback: bool | str) -> bool:
    raw = os.getenv(env_key)
    value = raw if raw is not None else fallback
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes")


def _env_int(env_key: str, fallback: int | str) -> int:
    return int(os.getenv(env_key, str(fallback)))


def _env_int_or_none(env_key: str, fallback: int | str | None) -> int | None:
    raw = os.getenv(env_key)
    value = raw if raw is not None else fallback
    if value is None or value == "":
        return None
    return int(value)


def _env_str(env_key: str, fallback: str) -> str:
    return os.getenv(env_key, fallback)


def load_config(config_file: str = "config.yaml") -> Config:
    raw: dict = {}
    if os.path.exists(config_file):
        with open(config_file) as f:
            raw = yaml.safe_load(f) or {}

    fw = raw.get("filmweb", {})
    ra = raw.get("radarr", {})
    so = raw.get("sonarr", {})
    sy = raw.get("sync", {})

    return Config(
        filmweb=FilmwebConfig(
            username=_env_str("FILMWEB_USERNAME", fw.get("username", "")),
        ),
        radarr=RadarrConfig(
            url=_env_str("RADARR_URL", ra.get("url", "")),
            api_key=_env_str("RADARR_API_KEY", ra.get("api_key", "")),
            root_folder=_env_str("RADARR_ROOT_FOLDER", ra.get("root_folder", "/movies")),
            quality_profile_id=_env_int(
                "RADARR_QUALITY_PROFILE_ID", ra.get("quality_profile_id", 1)
            ),
            enabled=_env_bool("RADARR_ENABLED", ra.get("enabled", True)),
            tag=_env_str("RADARR_TAG", ra.get("tag", "filmweb")),
        ),
        sonarr=SonarrConfig(
            url=_env_str("SONARR_URL", so.get("url", "")),
            api_key=_env_str("SONARR_API_KEY", so.get("api_key", "")),
            root_folder=_env_str("SONARR_ROOT_FOLDER", so.get("root_folder", "/tv")),
            quality_profile_id=_env_int(
                "SONARR_QUALITY_PROFILE_ID", so.get("quality_profile_id", 1)
            ),
            language_profile_id=_env_int_or_none(
                "SONARR_LANGUAGE_PROFILE_ID", so.get("language_profile_id")
            ),
            enabled=_env_bool("SONARR_ENABLED", so.get("enabled", True)),
            tag=_env_str("SONARR_TAG", so.get("tag", "filmweb")),
        ),
        sync=SyncConfig(
            interval_minutes=_env_int("SYNC_INTERVAL_MINUTES", sy.get("interval_minutes", 30)),
            dry_run=_env_bool("SYNC_DRY_RUN", sy.get("dry_run", False)),
            state_file=_env_str("STATE_FILE", sy.get("state_file", "/data/state.json")),
            add_delay_seconds=_env_int("ADD_DELAY_SECONDS", sy.get("add_delay_seconds", 5)),
        ),
    )
