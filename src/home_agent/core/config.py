from __future__ import annotations

"""Typed application configuration."""

import json
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HOME_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: Path = Path("./data")
    config_file: Path | None = Path("./home-agent.config.json")

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    max_agent_iterations: int = Field(default=5, ge=1, le=10)
    request_timeout_seconds: float = Field(default=45, ge=5, le=120)
    max_tool_output_chars: int = Field(default=12_000, ge=1_000, le=50_000)

    proxmox_url: str = "https://192.168.1.232:8006"
    proxmox_token_id: str = ""
    proxmox_token_secret: str = ""
    proxmox_ca_file: Path | None = None
    proxmox_insecure_tls: bool = False
    proxmox_allowed_nodes: Annotated[tuple[str, ...], NoDecode] = ()
    proxmox_allowed_guests: Annotated[tuple[int, ...], NoDecode] = ()

    crafty_url: str = ""
    crafty_read_token: str = ""
    crafty_action_token: str = ""
    crafty_ca_file: Path | None = None
    crafty_insecure_tls: bool = False
    crafty_allowed_servers: Annotated[tuple[str, ...], NoDecode] = ()

    ssh_username: str = "diagnostic-agent"
    ssh_key_file: Path | None = None
    ssh_hosts_json: str = "{}"
    ssh_timeout_seconds: float = Field(default=8, ge=1, le=30)
    ssh_log_lines: int = Field(default=100, ge=10, le=500)

    approval_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    audit_max_output_chars: int = Field(default=8_000, ge=500, le=50_000)
    whisper_model_size: str = "tiny"

    @field_validator("proxmox_allowed_nodes", mode="before")
    @classmethod
    def parse_nodes(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("proxmox_allowed_guests", mode="before")
    @classmethod
    def parse_guests(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(int(item.strip()) for item in value.split(",") if item.strip())
        return value

    @field_validator("crafty_allowed_servers", mode="before")
    @classmethod
    def parse_crafty_servers(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "audit.sqlite3"

    @property
    def ssh_hosts(self) -> dict[str, dict[str, Any]]:
        try:
            parsed = json.loads(self.ssh_hosts_json)
        except json.JSONDecodeError as exc:
            raise ValueError("HOME_AGENT_SSH_HOSTS_JSON must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("HOME_AGENT_SSH_HOSTS_JSON must be a JSON object")
        return parsed

    @classmethod
    def load(cls) -> "Settings":
        bootstrap = cls()
        if not bootstrap.config_file:
            return bootstrap
        path = bootstrap.config_file.expanduser()
        if not path.exists():
            return bootstrap
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not load config file {path}: {exc}") from exc
        if not isinstance(values, dict):
            raise RuntimeError(f"Config file {path} must contain a JSON object")
        for field_name in cls.model_fields:
            if f"HOME_AGENT_{field_name.upper()}" in os.environ:
                values.pop(field_name, None)
        return cls(**values)
