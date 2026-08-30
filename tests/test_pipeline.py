import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import run, select_slice
from src.xapi import Post


def test_select_slice_all_users_when_users_per_run_none():
    selected, next_cursor = select_slice(["a", "b", "c"], cursor=0, users_per_run=None)
    assert selected == ["a", "b", "c"]
    assert next_cursor == 0


def test_select_slice_wraps_around_roster():
    handles = ["a", "b", "c", "d", "e"]
    selected, next_cursor = select_slice(handles, cursor=3, users_per_run=3)
    assert selected == ["d", "e", "a"]
    assert next_cursor == 1


def test_select_slice_advances_cursor_each_call():
    handles = ["a", "b", "c", "d"]
    selected1, cursor1 = select_slice(handles, cursor=0, users_per_run=2)
    selected2, cursor2 = select_slice(handles, cursor=cursor1, users_per_run=2)
    assert selected1 == ["a", "b"]
    assert selected2 == ["c", "d"]
    assert cursor2 == 0


def test_select_slice_empty_handles():
    assert select_slice([], cursor=0, users_per_run=5) == ([], 0)


def test_select_slice_users_per_run_larger_than_roster_returns_all():
    handles = ["a", "b"]
    selected, next_cursor = select_slice(handles, cursor=1, users_per_run=10)
    assert selected == ["a", "b"]
    assert next_cursor == 0


def _make_users_yaml(tmp_path, handles):
    for h in handles:
        Image.new("RGB", (1200, 675), "white").save(tmp_path / f"{h}.png")
    users_yaml = tmp_path / "users.yaml"
    users_yaml.write_text(
        yaml.safe_dump(
            {
                "defaults": {"accent": "#5eaee0", "zone": {"x": 520, "y": 120, "w": 610, "h": 400}},
                "users": [{"handle": h, "template": f"{h}.png"} for h in handles],
            }
        ),
        encoding="utf-8",
    )
    return users_yaml


def _post(id="1"):
    return Post(id=id, text="hello", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), url="https://x.com/a/status/1")


def _setup_pipeline(tmp_path, monkeypatch, handles):
    users_yaml = _make_users_yaml(tmp_path, handles)
    monkeypatch.setattr("src.pipeline.USERS_YAML", users_yaml)
    monkeypatch.setattr("src.pipeline.STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr("src.pipeline.OUT_DIR", tmp_path / "out")
    monkeypatch.setattr("src.pipeline.sync_playwright", MagicMock())
    # Identity passthrough by default -- tests that care about highlighting
    # specifically override this.
    monkeypatch.setattr("src.pipeline.annotate_highlights", lambda text: text)


def test_run_isolates_one_user_failure(tmp_path, monkeypatch):
    _setup_pipeline(tmp_path, monkeypatch, ["a", "b"])
    with patch(
        "src.pipeline.fetch_all", return_value={"a": RuntimeError("boom"), "b": _post("1")}
    ), patch("src.pipeline.render_post", return_value=[tmp_path / "out.png"]) as mock_render, patch(
        "src.pipeline.send_cards"
    ) as mock_send:
        run()

    mock_render.assert_called_once()
    mock_send.assert_called_once()
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["users"]["b"]["last_id"] == "1"
    assert "a" not in state["users"]


def test_run_posts_nothing_on_second_identical_run(tmp_path, monkeypatch):
    _setup_pipeline(tmp_path, monkeypatch, ["a"])
    with patch("src.pipeline.fetch_all", return_value={"a": _post("1")}), patch(
        "src.pipeline.render_post", return_value=[tmp_path / "out.png"]
    ), patch("src.pipeline.send_cards") as mock_send:
        run()
        mock_send.reset_mock()
        run()

    mock_send.assert_not_called()


def test_run_writes_state_after_each_user_not_once_at_the_end(tmp_path, monkeypatch):
    _setup_pipeline(tmp_path, monkeypatch, ["a", "b"])
    state_path = tmp_path / "state.json"
    seen_before_b = {}

    def fake_send_cards(handle, url, paths):
        if handle == "b":
            # if state.json is only written once at the end, "a" would not
            # be recorded yet at this point either -- proving the write
            # already happened requires seeing it mid-run.
            seen_before_b["state"] = json.loads(state_path.read_text())

    with patch("src.pipeline.fetch_all", return_value={"a": _post("1"), "b": _post("2")}), patch(
        "src.pipeline.render_post", return_value=[tmp_path / "out.png"]
    ), patch("src.pipeline.send_cards", side_effect=fake_send_cards):
        run()

    assert "a" in seen_before_b["state"]["users"]
    assert "b" not in seen_before_b["state"]["users"]


def test_run_renders_the_annotated_text_not_raw_post_text(tmp_path, monkeypatch):
    _setup_pipeline(tmp_path, monkeypatch, ["a"])
    monkeypatch.setattr("src.pipeline.annotate_highlights", lambda text: f"**{text}** marked")

    with patch("src.pipeline.fetch_all", return_value={"a": _post("1")}), patch(
        "src.pipeline.render_post", return_value=[tmp_path / "out.png"]
    ) as mock_render, patch("src.pipeline.send_cards"):
        run()

    rendered_text = mock_render.call_args.args[3]
    assert rendered_text == "**hello** marked"


def test_run_falls_back_to_raw_text_when_highlighting_fails(tmp_path, monkeypatch):
    _setup_pipeline(tmp_path, monkeypatch, ["a"])

    def boom(text):
        raise RuntimeError("both providers down")

    monkeypatch.setattr("src.pipeline.annotate_highlights", boom)

    with patch("src.pipeline.fetch_all", return_value={"a": _post("1")}), patch(
        "src.pipeline.render_post", return_value=[tmp_path / "out.png"]
    ) as mock_render, patch("src.pipeline.send_cards") as mock_send:
        run()

    # the post still goes out despite the highlighting failure
    mock_send.assert_called_once()
    rendered_text = mock_render.call_args.args[3]
    assert rendered_text == "hello"
