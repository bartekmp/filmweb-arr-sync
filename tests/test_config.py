import pytest

from filmweb_arr_sync.config import load_config

_ALL_ENV_KEYS = [
    "FILMWEB_USERNAME",
    "RADARR_URL",
    "RADARR_API_KEY",
    "RADARR_ROOT_FOLDER",
    "RADARR_QUALITY_PROFILE_ID",
    "RADARR_ENABLED",
    "SONARR_URL",
    "SONARR_API_KEY",
    "SONARR_ROOT_FOLDER",
    "SONARR_QUALITY_PROFILE_ID",
    "SONARR_LANGUAGE_PROFILE_ID",
    "SONARR_ENABLED",
    "SYNC_INTERVAL_MINUTES",
    "SYNC_DRY_RUN",
    "STATE_FILE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in _ALL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class TestLoadConfigFromEnv:
    def test_reads_filmweb_username(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FILMWEB_USERNAME", "myuser")
        config = load_config(str(tmp_path / "missing.yaml"))
        assert config.filmweb.username == "myuser"

    def test_reads_radarr_settings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
        monkeypatch.setenv("RADARR_API_KEY", "abc123")
        monkeypatch.setenv("RADARR_ROOT_FOLDER", "/movies")
        monkeypatch.setenv("RADARR_QUALITY_PROFILE_ID", "3")
        config = load_config(str(tmp_path / "missing.yaml"))
        assert config.radarr.url == "http://radarr:7878"
        assert config.radarr.api_key == "abc123"
        assert config.radarr.quality_profile_id == 3

    def test_reads_sonarr_settings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SONARR_URL", "http://sonarr:8989")
        monkeypatch.setenv("SONARR_API_KEY", "def456")
        monkeypatch.setenv("SONARR_LANGUAGE_PROFILE_ID", "2")
        config = load_config(str(tmp_path / "missing.yaml"))
        assert config.sonarr.url == "http://sonarr:8989"
        assert config.sonarr.language_profile_id == 2

    def test_language_profile_id_is_none_when_unset(self, tmp_path):
        config = load_config(str(tmp_path / "missing.yaml"))
        assert config.sonarr.language_profile_id is None

    def test_language_profile_id_is_none_when_empty_string(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SONARR_LANGUAGE_PROFILE_ID", "")
        config = load_config(str(tmp_path / "missing.yaml"))
        assert config.sonarr.language_profile_id is None

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("0", False),
            ("no", False),
        ],
    )
    def test_dry_run_bool_parsing(self, tmp_path, monkeypatch, value, expected):
        monkeypatch.setenv("SYNC_DRY_RUN", value)
        assert load_config(str(tmp_path / "missing.yaml")).sync.dry_run is expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("false", False),
        ],
    )
    def test_enabled_bool_parsing(self, tmp_path, monkeypatch, value, expected):
        monkeypatch.setenv("RADARR_ENABLED", value)
        assert load_config(str(tmp_path / "missing.yaml")).radarr.enabled is expected


class TestLoadConfigFromYaml:
    def test_reads_all_sections(self, tmp_path):
        (tmp_path / "config.yaml").write_text("""
filmweb:
  username: yamluser
radarr:
  url: http://radarr:7878
  api_key: abc
  root_folder: /movies
  quality_profile_id: 2
sonarr:
  url: http://sonarr:8989
  api_key: def
  root_folder: /tv
sync:
  interval_minutes: 60
  dry_run: true
""")
        config = load_config(str(tmp_path / "config.yaml"))
        assert config.filmweb.username == "yamluser"
        assert config.radarr.quality_profile_id == 2
        assert config.sync.interval_minutes == 60
        assert config.sync.dry_run is True

    def test_env_var_overrides_yaml_value(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text("filmweb:\n  username: yamluser\n")
        monkeypatch.setenv("FILMWEB_USERNAME", "envuser")
        config = load_config(str(tmp_path / "config.yaml"))
        assert config.filmweb.username == "envuser"

    def test_missing_yaml_file_uses_defaults(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        assert config.sync.interval_minutes == 30
        assert config.sync.dry_run is False
        assert config.sync.add_delay_seconds == 5
        assert config.radarr.quality_profile_id == 1
        assert config.radarr.enabled is True
