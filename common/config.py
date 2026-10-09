"""Shared, bounded configuration schema. No network or shell side effects."""

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def validate_host(value: str) -> str:
    if len(value) > 253 or not value or any(c.isspace() for c in value):
        raise ValueError("invalid host length/whitespace")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
        raise ValueError("host must be an IP or ASCII DNS name, without options or URL")
    if any(
        not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", x)
        for x in value.split(".")
    ):
        raise ValueError("invalid DNS label")
    return value


class Node(Strict):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[\w .-]+$")
    host: str
    region: str = Field(default="Unknown", max_length=64)
    location: str = Field(default="", max_length=64)
    enabled: bool = True
    tcp_ports: list[int] = Field(default_factory=list, max_length=8)
    https_url: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=12)
    provider: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=512)

    _host = field_validator("host")(validate_host)

    @field_validator("tags")
    @classmethod
    def tags_bounded(cls, values):
        if any(len(x) > 64 for x in values):
            raise ValueError("tag too long")
        return values

    @field_validator("tcp_ports")
    @classmethod
    def ports(cls, values):
        if len(set(values)) != len(values) or any(x < 1 or x > 65535 for x in values):
            raise ValueError("ports must be unique integers 1..65535")
        return values

    @field_validator("https_url")
    @classmethod
    def url(cls, value):
        if value is None:
            return value
        if len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("URL too long or contains whitespace/control characters")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("URL must be http(s), without credentials or fragments")
        validate_host(parsed.hostname)
        _ = parsed.port  # validates port syntax and bounds
        return value


class Intervals(Strict):
    ping: int = Field(default=10, ge=5, le=3600)
    tcp: int = Field(default=30, ge=10, le=3600)
    https: int = Field(default=30, ge=10, le=3600)
    dns: int = Field(default=60, ge=30, le=3600)
    mtr: int = Field(default=300, ge=300, le=86400)


class Thresholds(Strict):
    warning_rtt_ms: float = Field(default=120, gt=0, le=10000)
    critical_rtt_ms: float = Field(default=200, gt=0, le=10000)
    warning_loss_percent: float = Field(default=2, ge=0, le=100)
    critical_loss_percent: float = Field(default=10, ge=0, le=100)
    warning_jitter_ms: float = Field(default=30, gt=0, le=10000)
    critical_jitter_ms: float = Field(default=60, gt=0, le=10000)
    debounce_samples: int = Field(default=3, ge=1, le=30)
    cooldown_seconds: int = Field(default=300, ge=10, le=86400)

    @model_validator(mode="after")
    def order(self):
        for key in ("rtt_ms", "loss_percent", "jitter_ms"):
            if getattr(self, "critical_" + key) < getattr(self, "warning_" + key):
                raise ValueError("critical threshold must be >= warning")
        return self


class Settings(Strict):
    intervals: Intervals = Field(default_factory=Intervals)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    ping_count: int = Field(default=5, ge=2, le=10)
    concurrency: int = Field(default=8, ge=1, le=32)
    event_retention_days: int = Field(default=30, ge=1, le=365)
    event_max_rows: int = Field(default=50000, ge=100, le=500000)
    mtr_enabled: bool = True
    blackbox_enabled: bool = True


class Configuration(Strict):
    settings: Settings = Field(default_factory=Settings)
    nodes: list[Node] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique(self):
        if len({n.name for n in self.nodes}) != len(self.nodes):
            raise ValueError("node names must be unique and stable history identifiers")
        return self


def load_config(path: str | Path) -> Configuration:
    raw = Path(path).read_bytes()
    if len(raw) > 262144:
        raise ValueError("nodes.yaml exceeds 256 KiB")
    return Configuration.model_validate(yaml.safe_load(raw))
