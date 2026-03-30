"""Unit tests for spawn data models — SpawnRecord, SpawnRunRecord."""

from embient.spawns.models import SpawnRecord, SpawnRunRecord, _new_id


class TestNewId:
    """Tests for the _new_id helper."""

    def test_length(self) -> None:
        assert len(_new_id()) == 12

    def test_hex(self) -> None:
        int(_new_id(), 16)  # Should not raise

    def test_uniqueness(self) -> None:
        ids = {_new_id() for _ in range(100)}
        assert len(ids) == 100


class TestSpawnRecord:
    """Tests for SpawnRecord dataclass."""

    def test_defaults(self) -> None:
        s = SpawnRecord()
        assert len(s.id) == 12
        assert s.status == "active"
        assert s.spawn_type == "task"
        assert s.schedule_type == "once"
        assert s.max_runs == 15
        assert s.run_count == 0
        assert s.consecutive_errors == 0
        assert "T" in s.created_at  # ISO format

    def test_custom_fields(self) -> None:
        s = SpawnRecord(
            id="custom-id",
            name="My Spawn",
            spawn_type="monitoring",
            status="paused",
            signal_id=42,
        )
        assert s.id == "custom-id"
        assert s.name == "My Spawn"
        assert s.spawn_type == "monitoring"
        assert s.status == "paused"
        assert s.signal_id == 42

    def test_schedule_display_interval(self) -> None:
        s = SpawnRecord(schedule_interval_minutes=30)
        assert s.schedule_display == "every 30m"

    def test_schedule_display_cron(self) -> None:
        s = SpawnRecord(schedule_cron="0 9 * * *")
        assert s.schedule_display == "cron: 0 9 * * *"

    def test_schedule_display_once(self) -> None:
        s = SpawnRecord(schedule_type="once")
        assert s.schedule_display == "once"

    def test_payload_json_roundtrip(self) -> None:
        payload = {"message": "hello", "notification": {"title": "test"}}
        s = SpawnRecord(payload=payload)
        restored = SpawnRecord.payload_from_json(s.payload_json)
        assert restored == payload

    def test_payload_from_json_empty(self) -> None:
        assert SpawnRecord.payload_from_json("") == {}

    def test_payload_from_json_invalid(self) -> None:
        assert SpawnRecord.payload_from_json("not json") == {}

    def test_payload_from_json_none(self) -> None:
        assert SpawnRecord.payload_from_json(None) == {}


class TestSpawnRunRecord:
    """Tests for SpawnRunRecord dataclass."""

    def test_defaults(self) -> None:
        r = SpawnRunRecord()
        assert len(r.id) == 12
        assert r.status == "ok"
        assert r.error is None
        assert r.result is None
        assert r.duration_ms is None
        assert "T" in r.started_at

    def test_custom_fields(self) -> None:
        r = SpawnRunRecord(spawn_id="sp-123", status="error", error="timeout")
        assert r.spawn_id == "sp-123"
        assert r.status == "error"
        assert r.error == "timeout"
