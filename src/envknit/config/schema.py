"""
Configuration schema and parsing.

Defines the structure of envknit.yaml and provides validation.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# yaml imported lazily inside methods that need it (optional dep)


@dataclass
class EnvironmentConfig:
    """Configuration for a single environment."""

    python: str = "3.11"
    packages: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "EnvironmentConfig":
        """Create EnvironmentConfig from dictionary."""
        return cls(
            python=data.get("python", "3.11"),
            packages=data.get("packages", []),
            channels=data.get("channels", []),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result: dict[str, Any] = {"python": self.python}

        if self.packages:
            result["packages"] = self.packages

        if self.channels:
            result["channels"] = self.channels

        return result


@dataclass
class BackendConfig:
    """Configuration for a package manager backend."""

    type: str = "conda"
    channels: list[str] = field(default_factory=lambda: ["conda-forge", "defaults"])
    options: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "BackendConfig":
        """Create BackendConfig from dictionary."""
        return cls(
            type=data.get("type", "conda"),
            channels=data.get("channels", ["conda-forge", "defaults"]),
            options=data.get("options", {}),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "channels": self.channels,
            **self.options,
        }


@dataclass
class Config:
    """
    Main configuration for an envknit project.

    This represents the structure of envknit.yaml.
    """

    name: str = "my-project"
    version: str = "1.0.0"
    environments: dict[str, EnvironmentConfig] = field(default_factory=dict)
    backends: dict[str, BackendConfig] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        """
        Load configuration from a file.

        Args:
            path: Path to envknit.yaml

        Returns:
            Config instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If configuration is invalid
        """
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError("Empty configuration file")

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary."""
        environments = {}

        for name, env_data in data.get("environments", {}).items():
            environments[name] = EnvironmentConfig.from_dict(env_data)

        backends = {}

        for name, backend_data in data.get("backends", {}).items():
            backends[name] = BackendConfig.from_dict(backend_data)

        return cls(
            name=data.get("name", "my-project"),
            version=data.get("version", "1.0.0"),
            environments=environments,
            backends=backends,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "environments": {
                name: env.to_dict()
                for name, env in self.environments.items()
            },
            "backends": {
                name: backend.to_dict()
                for name, backend in self.backends.items()
            },
        }

    def to_file(self, path: Path) -> None:
        """
        Save configuration to a file.

        Args:
            path: Path where to save envknit.yaml
        """
        import yaml
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)

    def get_environment(self, name: str) -> EnvironmentConfig | None:
        """
        Get an environment configuration.

        Args:
            name: Environment name

        Returns:
            EnvironmentConfig if found, None otherwise
        """
        return self.environments.get(name)

    def add_environment(self, name: str, config: EnvironmentConfig) -> None:
        """
        Add or update an environment.

        Args:
            name: Environment name
            config: Environment configuration
        """
        self.environments[name] = config

    def remove_environment(self, name: str) -> bool:
        """
        Remove an environment.

        Args:
            name: Environment name

        Returns:
            True if removed, False if not found
        """
        if name in self.environments:
            del self.environments[name]
            return True
        return False

    def validate(self) -> list[str]:
        """
        Validate the configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.name:
            errors.append("Project name is required")

        if not self.version:
            errors.append("Project version is required")

        for env_name, env_config in self.environments.items():
            if not env_config.python:
                errors.append(f"Environment '{env_name}': Python version is required")

        return errors
