"""Unit tests for spawn schedule calculations — timing, backoff, active hours."""

from datetime import UTC, datetime, time as dt_time, timedelta

from embient.spawns.models import SpawnRecord
from embient.spawns.schedule import (
    _parse_time,
    compute_backoff_next_run,
    compute_initial_next_run,
    compute_next_run,
    is_within_active_hours,
    should_complete,
    should_fail,
)


def _spawn(**overrides) -> SpawnRecord:
    """Create a SpawnRecord with sensible defaults and overrides."""
    defaults = dict(
        id="test-id",
        name="test",
        spawn_type="task",
        status="active",
        schedule_type="once",
        max_runs=15,
        run_count=0,
        consecutive_errors=0,
    )
    defaults.update(overrides)
    return SpawnRecord(**defaults)


class TestComputeInitialNextRun:
    """Tests for compute_initial_next_run()."""

    def test_once_with_schedule_at(self) -> None:
        s = _spawn(schedule_type="once", schedule_at="2026-01-15T10:00:00+00:00")
        assert compute_initial_next_run(s) == "2026-01-15T10:00:00+00:00"

    def test_once_without_schedule_at(self) -> None:
        s = _spawn(schedule_type="once", schedule_at=None)
        result = compute_initial_next_run(s)
        assert result is not None
        parsed = datetime.fromisoformat(result)
        assert abs((parsed - datetime.now(UTC)).total_seconds()) < 5

    def test_interval_runs_immediately(self) -> None:
        s = _spawn(schedule_type="interval", schedule_interval_minutes=30)
        result = compute_initial_next_run(s)
        assert result is not None
        parsed = datetime.fromisoformat(result)
        assert abs((parsed - datetime.now(UTC)).total_seconds()) < 5

    def test_interval_no_minutes_returns_none(self) -> None:
        s = _spawn(schedule_type="interval", schedule_interval_minutes=None)
        assert compute_initial_next_run(s) is None

    def test_cron_returns_future_time(self) -> None:
        s = _spawn(schedule_type="cron", schedule_cron="*/5 * * * *")
        result = compute_initial_next_run(s)
        assert result is not None
        parsed = datetime.fromisoformat(result)
        assert parsed > datetime.now(UTC)

    def test_unknown_schedule_type(self) -> None:
        s = _spawn(schedule_type="unknown")
        assert compute_initial_next_run(s) is None


class TestComputeNextRun:
    """Tests for compute_next_run()."""

    def test_once_returns_none(self) -> None:
        s = _spawn(schedule_type="once")
        assert compute_next_run(s) is None

    def test_interval_returns_future(self) -> None:
        s = _spawn(schedule_type="interval", schedule_interval_minutes=10, run_count=0)
        result = compute_next_run(s)
        assert result is not None
        parsed = datetime.fromisoformat(result)
        expected_min = datetime.now(UTC) + timedelta(minutes=9)
        assert parsed > expected_min

    def test_max_runs_reached_returns_none(self) -> None:
        s = _spawn(schedule_type="interval", schedule_interval_minutes=10, run_count=14, max_runs=15)
        assert compute_next_run(s) is None

    def test_cron_returns_next_fire(self) -> None:
        s = _spawn(schedule_type="cron", schedule_cron="*/5 * * * *", run_count=0)
        result = compute_next_run(s)
        assert result is not None
        parsed = datetime.fromisoformat(result)
        assert parsed > datetime.now(UTC)


class TestComputeBackoffNextRun:
    """Tests for compute_backoff_next_run()."""

    def test_first_error_half_minute(self) -> None:
        s = _spawn(consecutive_errors=0)
        result = compute_backoff_next_run(s)
        parsed = datetime.fromisoformat(result)
        delta = (parsed - datetime.now(UTC)).total_seconds()
        assert 20 < delta < 40  # ~30 seconds (0.5 minutes)

    def test_second_error_one_minute(self) -> None:
        s = _spawn(consecutive_errors=1)
        result = compute_backoff_next_run(s)
        parsed = datetime.fromisoformat(result)
        delta = (parsed - datetime.now(UTC)).total_seconds()
        assert 50 < delta < 70  # ~60 seconds

    def test_max_errors_capped(self) -> None:
        s = _spawn(consecutive_errors=10)
        result = compute_backoff_next_run(s)
        parsed = datetime.fromisoformat(result)
        delta = (parsed - datetime.now(UTC)).total_seconds()
        assert 3500 < delta < 3700  # ~60 minutes


class TestShouldComplete:
    """Tests for should_complete()."""

    def test_once_completes(self) -> None:
        assert should_complete(_spawn(schedule_type="once")) is True

    def test_interval_not_done(self) -> None:
        assert should_complete(_spawn(schedule_type="interval", run_count=0, max_runs=15)) is False

    def test_max_runs_completes(self) -> None:
        assert should_complete(_spawn(schedule_type="interval", run_count=14, max_runs=15)) is True

    def test_well_below_max(self) -> None:
        assert should_complete(_spawn(schedule_type="interval", run_count=5, max_runs=15)) is False


class TestShouldFail:
    """Tests for should_fail()."""

    def test_below_threshold(self) -> None:
        assert should_fail(_spawn(consecutive_errors=3)) is False

    def test_at_threshold(self) -> None:
        # consecutive_errors + 1 >= 5 → 4 + 1 = 5
        assert should_fail(_spawn(consecutive_errors=4)) is True

    def test_above_threshold(self) -> None:
        assert should_fail(_spawn(consecutive_errors=10)) is True

    def test_zero_errors(self) -> None:
        assert should_fail(_spawn(consecutive_errors=0)) is False


class TestParseTime:
    """Tests for _parse_time()."""

    def test_valid_time(self) -> None:
        assert _parse_time("09:30") == dt_time(9, 30)

    def test_midnight(self) -> None:
        assert _parse_time("00:00") == dt_time(0, 0)

    def test_end_of_day(self) -> None:
        assert _parse_time("23:59") == dt_time(23, 59)

    def test_invalid_format(self) -> None:
        assert _parse_time("abc") is None

    def test_empty_string(self) -> None:
        assert _parse_time("") is None

    def test_out_of_range(self) -> None:
        assert _parse_time("25:00") is None


class TestIsWithinActiveHours:
    """Tests for is_within_active_hours()."""

    def test_no_active_hours_always_true(self) -> None:
        s = _spawn(active_hours_start=None, active_hours_end=None)
        assert is_within_active_hours(s) is True

    def test_only_start_set_returns_true(self) -> None:
        s = _spawn(active_hours_start="09:00", active_hours_end=None)
        assert is_within_active_hours(s) is True
