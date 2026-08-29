import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ConfigError, load_config


def _make_png(path, size=(1200, 675)):
    Image.new("RGB", size, "white").save(path)


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_valid_config_loads(tmp_path):
    _make_png(tmp_path / "naval.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [{"handle": "naval", "template": "naval.png"}],
        },
    )

    config = load_config(users_yaml)

    assert len(config.users) == 1
    user = config.users[0]
    assert user.handle == "naval"
    assert user.accent == "#5eaee0"
    assert user.zone.x == 520
    assert user.enabled is True


def test_defaults_inheritance(tmp_path):
    _make_png(tmp_path / "paulg.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [
                {
                    "handle": "paulg",
                    "template": "paulg.png",
                    "accent": "#e88d5c",
                    "zone": {"x": 70},
                }
            ],
        },
    )

    config = load_config(users_yaml)
    user = config.get("paulg")

    assert user.accent == "#e88d5c"  # overridden
    assert user.zone.x == 70  # overridden
    assert user.zone.y == 120  # inherited
    assert user.zone.w == 610  # inherited


def test_zone_outside_canvas_rejected(tmp_path):
    _make_png(tmp_path / "bad.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {"accent": "#5eaee0"},
            "users": [
                {
                    "handle": "toowide",
                    "template": "bad.png",
                    "zone": {"x": 700, "y": 120, "w": 610, "h": 400},
                }
            ],
        },
    )

    with pytest.raises(ConfigError, match="toowide"):
        load_config(users_yaml)


def test_zone_too_small_rejected(tmp_path):
    _make_png(tmp_path / "tiny.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {"accent": "#5eaee0"},
            "users": [
                {
                    "handle": "tinyzone",
                    "template": "tiny.png",
                    "zone": {"x": 10, "y": 10, "w": 100, "h": 100},
                }
            ],
        },
    )

    with pytest.raises(ConfigError, match="tinyzone"):
        load_config(users_yaml)


def test_wrong_size_template_rejected(tmp_path):
    _make_png(tmp_path / "small.png", size=(800, 600))
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [{"handle": "smallcard", "template": "small.png"}],
        },
    )

    with pytest.raises(ConfigError, match="smallcard"):
        load_config(users_yaml)


def test_duplicate_handles_rejected(tmp_path):
    _make_png(tmp_path / "dup.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [
                {"handle": "dup", "template": "dup.png"},
                {"handle": "dup", "template": "dup.png"},
            ],
        },
    )

    with pytest.raises(ConfigError, match="duplicate"):
        load_config(users_yaml)


def test_bad_accent_rejected(tmp_path):
    _make_png(tmp_path / "badaccent.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {"zone": {"x": 520, "y": 120, "w": 610, "h": 400}},
            "users": [
                {
                    "handle": "badaccent",
                    "template": "badaccent.png",
                    "accent": "blue",
                }
            ],
        },
    )

    with pytest.raises(ConfigError, match="badaccent"):
        load_config(users_yaml)


def test_enabled_defaults_true_and_can_be_disabled(tmp_path):
    _make_png(tmp_path / "x.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [
                {"handle": "a", "template": "x.png"},
                {"handle": "b", "template": "x.png", "enabled": False},
            ],
        },
    )

    config = load_config(users_yaml)

    assert config.get("a").enabled is True
    assert config.get("b").enabled is False
    assert [u.handle for u in config.enabled_users()] == ["a"]
