"""Load and validate users.yaml (BUILD.md §3)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image

TEMPLATE_W = 1200
TEMPLATE_H = 675
MIN_ZONE_W = 200
MIN_ZONE_H = 150
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ConfigError(Exception):
    """Raised when users.yaml fails validation. Message names the offending handle."""


@dataclass(frozen=True)
class Zone:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class UserConfig:
    handle: str
    template: Path
    accent: str
    zone: Zone
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    users: list[UserConfig]

    def enabled_users(self) -> list[UserConfig]:
        return [u for u in self.users if u.enabled]

    def get(self, handle: str) -> UserConfig | None:
        for u in self.users:
            if u.handle == handle:
                return u
        return None


def _merge_zone(raw: dict, defaults: dict, handle: str) -> Zone:
    merged = {**defaults.get("zone", {}), **raw.get("zone", {})}
    for field in ("x", "y", "w", "h"):
        if field not in merged:
            raise ConfigError(f"user '{handle}': zone.{field} is missing and has no default")
    return Zone(x=merged["x"], y=merged["y"], w=merged["w"], h=merged["h"])


def _validate_zone(zone: Zone, handle: str) -> None:
    if zone.w < MIN_ZONE_W or zone.h < MIN_ZONE_H:
        raise ConfigError(
            f"user '{handle}': zone {zone.w}x{zone.h} is smaller than the "
            f"minimum {MIN_ZONE_W}x{MIN_ZONE_H}"
        )
    if zone.x < 0 or zone.y < 0 or zone.x + zone.w > TEMPLATE_W or zone.y + zone.h > TEMPLATE_H:
        raise ConfigError(
            f"user '{handle}': zone {zone.x},{zone.y} {zone.w}x{zone.h} falls outside "
            f"the {TEMPLATE_W}x{TEMPLATE_H} canvas"
        )


def _validate_template(template: Path, handle: str) -> None:
    if not template.exists():
        raise ConfigError(f"user '{handle}': template file not found: {template}")
    with Image.open(template) as img:
        if img.size != (TEMPLATE_W, TEMPLATE_H):
            raise ConfigError(
                f"user '{handle}': template {template} is {img.size[0]}x{img.size[1]}, "
                f"expected {TEMPLATE_W}x{TEMPLATE_H}"
            )


def _validate_accent(accent: str, handle: str) -> None:
    if not HEX_RE.match(accent):
        raise ConfigError(f"user '{handle}': accent '{accent}' is not a #rrggbb hex string")


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults", {}) or {}
    raw_users = raw.get("users", []) or []

    seen_handles: set[str] = set()
    users: list[UserConfig] = []

    for raw_user in raw_users:
        handle = raw_user.get("handle")
        if not handle:
            raise ConfigError("a user entry is missing 'handle'")
        if handle in seen_handles:
            raise ConfigError(f"duplicate handle: '{handle}'")
        seen_handles.add(handle)

        template_str = raw_user.get("template") or defaults.get("template")
        if not template_str:
            raise ConfigError(f"user '{handle}': no template configured")
        template = path.parent / template_str

        accent = raw_user.get("accent", defaults.get("accent"))
        if not accent:
            raise ConfigError(f"user '{handle}': no accent configured")

        zone = _merge_zone(raw_user, defaults, handle)
        enabled = raw_user.get("enabled", True)

        _validate_template(template, handle)
        _validate_zone(zone, handle)
        _validate_accent(accent, handle)

        users.append(
            UserConfig(handle=handle, template=template, accent=accent, zone=zone, enabled=enabled)
        )

    return Config(users=users)
