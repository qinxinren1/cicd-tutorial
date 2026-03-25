"""Tests for loading API keys from ``~/.jobpilot/.env``."""

import os
from pathlib import Path


def test_load_jobpilot_dotenv_reads_home_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    jp = tmp_path / ".jobpilot"
    jp.mkdir()
    (jp / ".env").write_text("OPENAI_API_KEY=sk-from-jobpilot-env\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from jobpilot_core.paths import load_jobpilot_dotenv

    load_jobpilot_dotenv()
    assert os.environ.get("OPENAI_API_KEY") == "sk-from-jobpilot-env"


def test_cwd_dotenv_overrides_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    jp = tmp_path / ".jobpilot"
    jp.mkdir()
    (jp / ".env").write_text("OPENAI_API_KEY=sk-home\n", encoding="utf-8")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    (cwd / ".env").write_text("OPENAI_API_KEY=sk-cwd\n", encoding="utf-8")
    monkeypatch.chdir(cwd)

    from jobpilot_core.paths import load_jobpilot_dotenv

    load_jobpilot_dotenv()
    assert os.environ.get("OPENAI_API_KEY") == "sk-cwd"
