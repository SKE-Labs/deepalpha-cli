"""Unit tests for SpawnStore — SQLite CRUD for spawns and runs."""

import asyncio
from pathlib import Path

import pytest

from deepalpha.spawns.models import SpawnRecord, SpawnRunRecord
from deepalpha.spawns.store import SpawnStore


@pytest.fixture
def store(tmp_path: Path):
    """Create an initialized SpawnStore backed by a temp SQLite file."""
    s = SpawnStore(db_path=str(tmp_path / "test.db"))
    asyncio.run(s.initialize())
    return s


def _spawn(**overrides) -> SpawnRecord:
    defaults = dict(name="test-spawn", spawn_type="task", status="active")
    defaults.update(overrides)
    return SpawnRecord(**defaults)


def _run(spawn_id: str, **overrides) -> SpawnRunRecord:
    defaults = dict(spawn_id=spawn_id, status="ok")
    defaults.update(overrides)
    return SpawnRunRecord(**defaults)


class TestInitialize:
    def test_creates_tables(self, store: SpawnStore) -> None:
        result = asyncio.run(store.list_spawns())
        assert result == []


class TestSpawnCrud:
    def test_create_and_get(self, store: SpawnStore) -> None:
        s = _spawn(name="my spawn")
        asyncio.run(store.create_spawn(s))
        got = asyncio.run(store.get_spawn(s.id))
        assert got is not None
        assert got.id == s.id
        assert got.name == "my spawn"
        assert got.spawn_type == "task"

    def test_get_not_found(self, store: SpawnStore) -> None:
        assert asyncio.run(store.get_spawn("nonexistent")) is None

    def test_list_empty(self, store: SpawnStore) -> None:
        assert asyncio.run(store.list_spawns()) == []

    def test_list_all(self, store: SpawnStore) -> None:
        for i in range(3):
            asyncio.run(store.create_spawn(_spawn(name=f"spawn-{i}")))
        result = asyncio.run(store.list_spawns())
        assert len(result) == 3

    def test_list_filter_by_status(self, store: SpawnStore) -> None:
        asyncio.run(store.create_spawn(_spawn(name="a1", status="active")))
        asyncio.run(store.create_spawn(_spawn(name="a2", status="active")))
        asyncio.run(store.create_spawn(_spawn(name="p1", status="paused")))
        active = asyncio.run(store.list_spawns(status="active"))
        assert len(active) == 2
        paused = asyncio.run(store.list_spawns(status="paused"))
        assert len(paused) == 1

    def test_update(self, store: SpawnStore) -> None:
        s = _spawn(name="old-name")
        asyncio.run(store.create_spawn(s))
        updated = asyncio.run(store.update_spawn(s.id, name="new-name"))
        assert updated is not None
        assert updated.name == "new-name"
        assert updated.updated_at != s.updated_at

    def test_update_not_found(self, store: SpawnStore) -> None:
        assert asyncio.run(store.update_spawn("nope", name="x")) is None

    def test_delete(self, store: SpawnStore) -> None:
        s = _spawn()
        asyncio.run(store.create_spawn(s))
        assert asyncio.run(store.delete_spawn(s.id)) is True
        assert asyncio.run(store.get_spawn(s.id)) is None

    def test_delete_not_found(self, store: SpawnStore) -> None:
        assert asyncio.run(store.delete_spawn("nope")) is False

    def test_payload_roundtrip(self, store: SpawnStore) -> None:
        payload = {"message": "analyze AAPL", "notification": {"title": "Done"}}
        s = _spawn(payload=payload)
        asyncio.run(store.create_spawn(s))
        got = asyncio.run(store.get_spawn(s.id))
        assert got is not None
        assert got.payload == payload


class TestRunCrud:
    def test_create_and_get_run(self, store: SpawnStore) -> None:
        s = _spawn()
        asyncio.run(store.create_spawn(s))
        r = _run(s.id, result="done")
        asyncio.run(store.create_run(r))
        runs = asyncio.run(store.get_runs(s.id))
        assert len(runs) == 1
        assert runs[0].id == r.id
        assert runs[0].result == "done"

    def test_get_runs_limit(self, store: SpawnStore) -> None:
        s = _spawn()
        asyncio.run(store.create_spawn(s))
        for i in range(5):
            asyncio.run(store.create_run(_run(s.id, result=f"run-{i}")))
        runs = asyncio.run(store.get_runs(s.id, limit=2))
        assert len(runs) == 2

    def test_prune_runs(self, store: SpawnStore) -> None:
        s = _spawn()
        asyncio.run(store.create_spawn(s))
        for _i in range(10):
            asyncio.run(store.create_run(_run(s.id)))
        pruned = asyncio.run(store.prune_runs(s.id, keep=3))
        assert pruned == 7
        remaining = asyncio.run(store.get_runs(s.id, limit=100))
        assert len(remaining) == 3
