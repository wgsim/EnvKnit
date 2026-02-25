"""
Tests for the configuration schema module.

Tests Config, EnvironmentConfig, and BackendConfig dataclasses
including creation, serialization, file I/O, and validation.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from envknit.config.schema import BackendConfig, Config, EnvironmentConfig


# ---------------------------------------------------------------------------
# EnvironmentConfig
# ---------------------------------------------------------------------------

class TestEnvironmentConfig:
    """Tests for EnvironmentConfig dataclass."""

    def test_defaults(self):
        env = EnvironmentConfig()
        assert env.python == "3.11"
        assert env.packages == []
        assert env.channels == []

    def test_custom_values(self):
        env = EnvironmentConfig(
            python="3.10",
            packages=["numpy", "pandas"],
            channels=["conda-forge"],
        )
        assert env.python == "3.10"
        assert env.packages == ["numpy", "pandas"]

    def test_from_dict_full(self):
        data = {
            "python": "3.9",
            "packages": ["scipy"],
            "channels": ["defaults"],
        }
        env = EnvironmentConfig.from_dict(data)
        assert env.python == "3.9"
        assert env.packages == ["scipy"]
        assert env.channels == ["defaults"]

    def test_from_dict_minimal(self):
        env = EnvironmentConfig.from_dict({})
        assert env.python == "3.11"
        assert env.packages == []

    def test_to_dict_with_packages(self):
        env = EnvironmentConfig(python="3.11", packages=["numpy"], channels=["conda-forge"])
        d = env.to_dict()
        assert d["python"] == "3.11"
        assert d["packages"] == ["numpy"]
        assert d["channels"] == ["conda-forge"]

    def test_to_dict_empty_packages_omitted(self):
        env = EnvironmentConfig(python="3.11")
        d = env.to_dict()
        assert "packages" not in d
        assert "channels" not in d

    def test_round_trip(self):
        env = EnvironmentConfig(python="3.10", packages=["a", "b"], channels=["c"])
        env2 = EnvironmentConfig.from_dict(env.to_dict())
        assert env2.python == env.python
        assert env2.packages == env.packages
        assert env2.channels == env.channels


# ---------------------------------------------------------------------------
# BackendConfig
# ---------------------------------------------------------------------------

class TestBackendConfig:
    """Tests for BackendConfig dataclass."""

    def test_defaults(self):
        bc = BackendConfig()
        assert bc.type == "conda"
        assert bc.channels == ["conda-forge", "defaults"]
        assert bc.options == {}

    def test_custom(self):
        bc = BackendConfig(type="pip", channels=[], options={"index-url": "https://pypi.org"})
        assert bc.type == "pip"
        assert bc.channels == []
        assert bc.options["index-url"] == "https://pypi.org"

    def test_from_dict(self):
        data = {"type": "mamba", "channels": ["bioconda"], "options": {"strict": True}}
        bc = BackendConfig.from_dict(data)
        assert bc.type == "mamba"
        assert bc.channels == ["bioconda"]
        assert bc.options["strict"] is True

    def test_from_dict_defaults(self):
        bc = BackendConfig.from_dict({})
        assert bc.type == "conda"
        assert bc.channels == ["conda-forge", "defaults"]

    def test_to_dict(self):
        bc = BackendConfig(type="conda", channels=["conda-forge"])
        d = bc.to_dict()
        assert d["type"] == "conda"
        assert d["channels"] == ["conda-forge"]

    def test_to_dict_options_merged(self):
        bc = BackendConfig(options={"solver": "libmamba"})
        d = bc.to_dict()
        assert d["solver"] == "libmamba"


# ---------------------------------------------------------------------------
# Config — creation & dict conversion
# ---------------------------------------------------------------------------

class TestConfigCreation:
    """Tests for Config creation and dict conversion."""

    def test_defaults(self):
        cfg = Config()
        assert cfg.name == "my-project"
        assert cfg.version == "1.0.0"
        assert cfg.environments == {}
        assert cfg.backends == {}

    def test_from_dict(self):
        data = {
            "name": "test",
            "version": "2.0.0",
            "environments": {
                "dev": {"python": "3.10", "packages": ["pytest"]},
            },
            "backends": {
                "conda": {"type": "conda", "channels": ["defaults"]},
            },
        }
        cfg = Config.from_dict(data)
        assert cfg.name == "test"
        assert cfg.version == "2.0.0"
        assert "dev" in cfg.environments
        assert cfg.environments["dev"].packages == ["pytest"]
        assert cfg.backends["conda"].type == "conda"

    def test_from_dict_empty(self):
        cfg = Config.from_dict({})
        assert cfg.name == "my-project"
        assert cfg.environments == {}

    def test_to_dict(self):
        cfg = Config(name="proj", version="0.1.0")
        cfg.add_environment("dev", EnvironmentConfig(packages=["black"]))
        d = cfg.to_dict()
        assert d["name"] == "proj"
        assert "dev" in d["environments"]
        assert d["environments"]["dev"]["packages"] == ["black"]

    def test_round_trip(self):
        cfg = Config(name="rt", version="3.0")
        cfg.add_environment("prod", EnvironmentConfig(python="3.12", packages=["flask"]))
        cfg2 = Config.from_dict(cfg.to_dict())
        assert cfg2.name == cfg.name
        assert cfg2.environments["prod"].python == "3.12"


# ---------------------------------------------------------------------------
# Config — environment management
# ---------------------------------------------------------------------------

class TestConfigEnvironments:
    """Tests for add/get/remove environment."""

    def test_get_environment_exists(self):
        cfg = Config()
        env = EnvironmentConfig(packages=["numpy"])
        cfg.add_environment("ml", env)
        assert cfg.get_environment("ml") is env

    def test_get_environment_missing(self):
        cfg = Config()
        assert cfg.get_environment("nope") is None

    def test_add_environment_overwrite(self):
        cfg = Config()
        cfg.add_environment("dev", EnvironmentConfig(packages=["a"]))
        cfg.add_environment("dev", EnvironmentConfig(packages=["b"]))
        assert cfg.get_environment("dev").packages == ["b"]

    def test_remove_environment(self):
        cfg = Config()
        cfg.add_environment("dev", EnvironmentConfig())
        assert cfg.remove_environment("dev") is True
        assert cfg.get_environment("dev") is None

    def test_remove_environment_missing(self):
        cfg = Config()
        assert cfg.remove_environment("nope") is False


# ---------------------------------------------------------------------------
# Config — validation
# ---------------------------------------------------------------------------

class TestConfigValidation:
    """Tests for Config.validate."""

    def test_valid_config(self):
        cfg = Config(name="ok", version="1.0")
        assert cfg.validate() == []

    def test_missing_name(self):
        cfg = Config(name="", version="1.0")
        errors = cfg.validate()
        assert any("name" in e.lower() for e in errors)

    def test_missing_version(self):
        cfg = Config(name="ok", version="")
        errors = cfg.validate()
        assert any("version" in e.lower() for e in errors)

    def test_missing_python_in_env(self):
        cfg = Config(name="ok", version="1.0")
        cfg.add_environment("bad", EnvironmentConfig(python=""))
        errors = cfg.validate()
        assert any("python" in e.lower() for e in errors)

    def test_multiple_errors(self):
        cfg = Config(name="", version="")
        cfg.add_environment("bad", EnvironmentConfig(python=""))
        errors = cfg.validate()
        assert len(errors) == 3


# ---------------------------------------------------------------------------
# Config — file I/O
# ---------------------------------------------------------------------------

class TestConfigFileIO:
    """Tests for file-based save/load."""

    def test_to_file_and_from_file(self, tmp_path):
        cfg = Config(name="filetest", version="1.0")
        cfg.add_environment("dev", EnvironmentConfig(packages=["pytest"]))
        path = tmp_path / "envknit.yaml"
        cfg.to_file(path)

        loaded = Config.from_file(path)
        assert loaded.name == "filetest"
        assert loaded.environments["dev"].packages == ["pytest"]

    def test_from_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Config.from_file(tmp_path / "missing.yaml")

    def test_from_file_empty(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        with pytest.raises(ValueError, match="Empty"):
            Config.from_file(path)

    def test_yaml_content(self, tmp_path):
        cfg = Config(name="yamltest", version="2.0")
        cfg.add_environment("prod", EnvironmentConfig(python="3.12"))
        path = tmp_path / "envknit.yaml"
        cfg.to_file(path)

        raw = yaml.safe_load(path.read_text())
        assert raw["name"] == "yamltest"
        assert raw["environments"]["prod"]["python"] == "3.12"
