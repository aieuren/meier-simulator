"""Tester för automatisk incheckning av matchloggar till loggrepet.

Testerna kör mot ett lokalt bare-repo (file://-remote), så ingen
nätverkstrafik eller riktig GitHub-token behövs.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from mejer import logrepo
from mejer.logrepo import LogRepo


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


@pytest.fixture
def log_repo(tmp_path: Path):
    """Ett bare-repo som remote och en klon av det – som loggrepet."""
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-q", str(remote))
    work = tmp_path / "work"
    _git("clone", "-q", str(remote), str(work))
    _git("config", "user.name", "Test", cwd=work)
    _git("config", "user.email", "test@example.com", cwd=work)
    (work / "README.md").write_text("loggrepo\n", encoding="utf-8")
    _git("add", "README.md", cwd=work)
    _git("commit", "-q", "-m", "init", cwd=work)
    _git("push", "-q", "origin", "HEAD", cwd=work)

    token = tmp_path / "token"
    token.write_text("dummy-token\n", encoding="utf-8")
    return LogRepo(directory=work, token_path=token), remote, work


def test_series_filename_has_date_and_minute():
    name = logrepo.series_filename(datetime(2026, 11, 12, 1, 48))
    assert name == "mejer-matcher-2026-11-12-0148.jsonl"


def test_commit_and_push_publishes_the_file(log_repo):
    repo, remote, work = log_repo
    path = work / "mejer-matcher-2026-11-12-0148.jsonl"
    path.write_text('{"game": 1}\n', encoding="utf-8")

    status = repo.commit_and_push(path, "Mejer: 1 match")

    assert "pushat" in status.lower()
    # Filen ska finnas i fjärren efter push.
    names = _git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "HEAD").stdout
    assert "mejer-matcher-2026-11-12-0148.jsonl" in names
    # Och en commit ska ha skapats.
    log = _git("--git-dir", str(remote), "log", "--oneline", "HEAD").stdout
    assert "Mejer: 1 match" in log


def test_commit_without_changes_is_a_noop(log_repo):
    repo, _remote, work = log_repo
    path = work / "tom.jsonl"
    path.write_text("x\n", encoding="utf-8")
    repo.commit_and_push(path, "första")
    status = repo.commit_and_push(path, "igen")
    assert "inga ändringar" in status.lower()


def test_push_failure_is_reported_not_raised(log_repo):
    repo, remote, work = log_repo
    # Gör fjärren oåtkomlig.
    subprocess.run(["rm", "-rf", str(remote)], check=True)
    path = work / "mejer-matcher-2026-11-12-0148.jsonl"
    path.write_text('{"game": 1}\n', encoding="utf-8")

    status = repo.commit_and_push(path, "Mejer: 1 match")

    # Felet rapporteras som en sträng – körningen får aldrig fällas av en push.
    assert "misslyckades" in status.lower()


def test_configured_requires_token(tmp_path: Path):
    repo = LogRepo(directory=tmp_path / "saknas", token_path=tmp_path / "ingen-token")
    assert repo.configured() is False
    assert repo.ready() is False


def test_ensure_clone_without_token_raises(tmp_path: Path):
    repo = LogRepo(directory=tmp_path / "ny", token_path=tmp_path / "ingen-token")
    with pytest.raises(logrepo.LogRepoError):
        repo.ensure_clone()
