from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / "scripts/local.py"
    spec = importlib.util.spec_from_file_location("local_services", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA", tmp_path)
    return module


def save_processes(launcher, revision):
    for index, name in enumerate(launcher.BACKEND_SERVICES, start=101):
        (launcher.DATA / f"{name}.pid").write_text(str(index))
    launcher.record_backend_revision(revision)


def test_backend_revision_tracks_source_and_config_not_file_timestamp(launcher):
    app = launcher.ROOT / "backend/app"
    app.mkdir(parents=True)
    source = app / "routes.py"
    source.write_text("old_route = True")
    original = launcher.backend_revision()
    source.touch()
    assert launcher.backend_revision() == original
    source.write_text("new_route = True")
    changed = launcher.backend_revision()
    assert changed != original
    (launcher.ROOT / ".env").write_text("RAG_ENVIRONMENT=development")
    assert launcher.backend_revision() != changed
    extra = app / "new_routes.py"
    before_add = launcher.backend_revision()
    extra.write_text("another_route = True")
    assert launcher.backend_revision() != before_add
    extra.unlink()
    assert launcher.backend_revision() == before_add


def test_start_reuses_backend_only_when_source_and_processes_match(launcher, monkeypatch):
    save_processes(launcher, "current")
    monkeypatch.setattr(launcher, "alive", lambda _: True)
    signal_process = Mock()
    monkeypatch.setattr(launcher.os, "killpg", signal_process)
    launcher.refresh_backend_if_needed("current")
    signal_process.assert_not_called()


@pytest.mark.parametrize("old_state", ["outdated", "missing", "invalid", "different_pid"])
def test_start_refreshes_stale_backend_together_without_stopping_database(
    launcher, monkeypatch, old_state,
):
    save_processes(launcher, "old" if old_state == "outdated" else "current")
    state = launcher.DATA / "backend-processes.json"
    if old_state == "missing":
        state.unlink()
    elif old_state == "invalid":
        state.write_text("invalid json")
    elif old_state == "different_pid":
        (launcher.DATA / "api.pid").write_text("201")
    running = set(launcher.BACKEND_SERVICES)
    stopped = []

    def terminate(pid, sig):
        assert sig == launcher.signal.SIGTERM
        name = next(
            name for name in running
            if (launcher.DATA / f"{name}.pid").read_text() == str(pid)
        )
        stopped.append(name)
        running.remove(name)

    monkeypatch.setattr(launcher, "alive", running.__contains__)
    monkeypatch.setattr(launcher.os, "killpg", terminate)
    launcher.refresh_backend_if_needed("current")
    assert stopped == ["api", "beat", "worker"]
    assert not list(launcher.DATA.glob("*.pid"))


def test_busy_worker_is_not_killed_or_forgotten_on_timeout(launcher, monkeypatch):
    save_processes(launcher, "old")
    worker_pid = (launcher.DATA / "worker.pid").read_text()
    monkeypatch.setattr(launcher, "alive", lambda name: name == "worker")
    signal_process = Mock()
    monkeypatch.setattr(launcher.os, "killpg", signal_process)
    monkeypatch.setattr(launcher.time, "monotonic", Mock(side_effect=[0, 61]))
    with pytest.raises(RuntimeError, match="未强制终止"):
        launcher.refresh_backend_if_needed("current")
    signal_process.assert_called_once_with(int(worker_pid), launcher.signal.SIGTERM)
    assert (launcher.DATA / "worker.pid").read_text() == worker_pid
    assert json.loads((launcher.DATA / "backend-processes.json").read_text())["revision"] == "old"
