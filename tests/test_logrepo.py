"""Tester för automatisk incheckning av matchloggar till loggrepet.

Testerna kör mot ett lokalt bare-repo (file://-remote), så ingen
nätverkstrafik eller riktig GitHub-token behövs.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from meier import logrepo
from meier.logrepo import LogRepo


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


def test_series_filename_is_a_bare_timestamp_in_utc():
    """Filnamnet bär tiden i UTC, oavsett containerns tidszon.

    En stämpel utan zon gick att läsa som lokal tid, och då blev etiketten i
    gränssnittet två timmar fel. Namnet ska alltid vara UTC, då går det att
    räkna om till läsarens tid.
    """
    name = logrepo.series_filename(datetime(2026, 11, 12, 1, 48, 13))
    assert name == "2026-11-12-014813.jsonl"

    # Samma ögonblick, angivet i en annan zon, ska ge samma namn.
    stockholm = timezone(timedelta(hours=1))
    name_local = logrepo.series_filename(
        datetime(2026, 11, 12, 2, 48, 13, tzinfo=stockholm)
    )
    assert name_local == name


def test_series_time_is_utc_aware():
    """Tiden ur namnet ska bära UTC, inte vara naiv."""
    when = logrepo.parse_series_time("2026-11-12-014813.jsonl")
    assert when == datetime(2026, 11, 12, 1, 48, 13, tzinfo=timezone.utc)
    assert when.tzinfo is not None


def test_series_epoch_matches_the_stamp():
    """Epoch-värdet ska vara samma ögonblick som stämpeln, i UTC."""
    epoch = logrepo.series_epoch("2026-11-12-014813.jsonl")
    assert datetime.fromtimestamp(epoch, timezone.utc) == datetime(
        2026, 11, 12, 1, 48, 13, tzinfo=timezone.utc
    )
    assert logrepo.series_epoch("trasig.jsonl") is None


def test_series_label_is_marked_as_utc():
    label = logrepo.series_label("2026-11-12-014813.jsonl")
    assert label == "12 november 2026, 01:48:13 (UTC)"


def test_series_label_handles_legacy_prefixed_name():
    """Gamla loggar med prefixet meier-matcher- ska fortsätta läsas."""
    label = logrepo.series_label("meier-matcher-2026-11-12-014813.jsonl")
    assert label == "12 november 2026, 01:48:13 (UTC)"
    assert logrepo.parse_series_time("meier-matcher-2026-11-12-014813.jsonl") == datetime(
        2026, 11, 12, 1, 48, 13, tzinfo=timezone.utc
    )


def test_series_label_handles_minute_only_name():
    label = logrepo.series_label("2026-11-12-0148.jsonl")
    assert label == "12 november 2026, 01:48 (UTC)"


def test_series_label_falls_back_to_the_name():
    assert logrepo.series_label("nagot-annat.jsonl") == "nagot-annat.jsonl"
    assert logrepo.parse_series_time("trasig.jsonl") is None


def test_commit_and_push_publishes_the_file(log_repo):
    repo, remote, work = log_repo
    path = work / "2026-11-12-014813.jsonl"
    path.write_text('{"game": 1}\n', encoding="utf-8")

    status = repo.commit_and_push(path, "Meier: 1 match")

    assert "pushat" in status.lower()
    # Filen ska finnas i fjärren efter push.
    names = _git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "HEAD").stdout
    assert "2026-11-12-014813.jsonl" in names
    # Och en commit ska ha skapats.
    log = _git("--git-dir", str(remote), "log", "--oneline", "HEAD").stdout
    assert "Meier: 1 match" in log


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
    path = work / "2026-11-12-014813.jsonl"
    path.write_text('{"game": 1}\n', encoding="utf-8")

    status = repo.commit_and_push(path, "Meier: 1 match")

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


def test_delete_logs_removes_the_file_from_the_remote(log_repo):
    """Borttagningen ska gå till fjärren, inte bara till disk."""
    repo, remote, work = log_repo
    path = work / "2026-11-12-014813.jsonl"
    path.write_text('{"game": 1}\n', encoding="utf-8")
    repo.commit_and_push(path, "Meier: 1 match")

    status = repo.delete_logs(["2026-11-12-014813.jsonl"], "Meier: tar bort 1 logg")

    assert "pushat" in status.lower()
    assert not path.exists()
    names = _git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "HEAD").stdout
    assert "2026-11-12-014813.jsonl" not in names
    log = _git("--git-dir", str(remote), "log", "--oneline", "HEAD").stdout
    assert "tar bort 1 logg" in log


def test_delete_logs_handles_a_file_that_was_never_committed(log_repo):
    """En olokaliserad fil i klonen ska gå att ta bort utan att git klagar."""
    repo, remote, work = log_repo
    path = work / "2026-11-12-020000.jsonl"
    path.write_text('{"game": 2}\n', encoding="utf-8")

    status = repo.delete_logs(["2026-11-12-020000.jsonl"], "städar")

    assert not path.exists()
    assert "inga ändringar" in status.lower()


def test_delete_logs_rejects_names_outside_the_clone(log_repo):
    repo, _remote, work = log_repo
    with pytest.raises(logrepo.LogRepoError):
        repo.delete_logs(["../rymmer.jsonl"], "städar")
    assert not (work.parent / "rymmer.jsonl").exists()


def test_delete_logs_reports_push_failure(log_repo):
    repo, remote, work = log_repo
    path = work / "2026-11-12-030000.jsonl"
    path.write_text('{"game": 3}\n', encoding="utf-8")
    repo.commit_and_push(path, "Meier: 1 match")
    subprocess.run(["rm", "-rf", str(remote)], check=True)

    status = repo.delete_logs(["2026-11-12-030000.jsonl"], "städar")

    assert "misslyckades" in status.lower()
