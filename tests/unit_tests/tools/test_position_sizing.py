"""Unit tests for position sizing — pure calculation logic."""

from deepalpha.trading_tools.signals.position_sizing import (
    _round_quantity,
    calculate_position_sizing,
)

_DEFAULT_PROFILE = {
    "available_balance": 10_000.0,
    "max_leverage": 10.0,
    "default_position_size": 2.0,
}


class TestRoundQuantity:
    def test_crypto_8_decimals(self) -> None:
        result = _round_quantity(0.123456789, "BTC/USDT")
        assert result == 0.12345679  # rounded to 8

    def test_crypto_detected_by_slash(self) -> None:
        result = _round_quantity(1.123456789, "UNKNOWN/USD")
        assert result == round(1.123456789, 8)

    def test_stock_whole_number(self) -> None:
        result = _round_quantity(15.7, "AAPL")
        assert result == 16.0

    def test_stock_fractional(self) -> None:
        result = _round_quantity(0.456, "AAPL")
        assert result == 0.46


class TestCalculatePositionSizing:
    def test_basic_long_position(self) -> None:
        capital, leverage, quantity = calculate_position_sizing(
            _DEFAULT_PROFILE, entry_price=100.0, stop_loss=95.0, symbol="AAPL"
        )
        assert capital is not None and leverage is not None and quantity is not None
        assert capital > 0
        assert leverage >= 1.0
        assert quantity > 0

    def test_basic_short_position(self) -> None:
        capital, leverage, quantity = calculate_position_sizing(
            _DEFAULT_PROFILE, entry_price=95.0, stop_loss=100.0, symbol="AAPL"
        )
        assert capital is not None
        assert capital > 0

    def test_risk_amount_matches_position_size(self) -> None:
        # 2% of $10,000 = $200 at risk, SL distance = $5
        # quantity = $200 / $5 = 40 shares
        capital, leverage, quantity = calculate_position_sizing(
            _DEFAULT_PROFILE, entry_price=100.0, stop_loss=95.0, symbol="AAPL"
        )
        assert quantity == 40.0
        assert capital == 4000.0  # 40 * $100

    def test_no_profile_returns_nones(self) -> None:
        result = calculate_position_sizing(None, 100.0, 95.0)
        assert result == (None, None, None)

    def test_zero_balance_returns_nones(self) -> None:
        profile = {**_DEFAULT_PROFILE, "available_balance": 0}
        result = calculate_position_sizing(profile, 100.0, 95.0)
        assert result == (None, None, None)

    def test_negative_price_returns_nones(self) -> None:
        result = calculate_position_sizing(_DEFAULT_PROFILE, -10.0, 95.0)
        assert result == (None, None, None)

    def test_same_entry_and_sl_returns_nones(self) -> None:
        result = calculate_position_sizing(_DEFAULT_PROFILE, 100.0, 100.0)
        assert result == (None, None, None)

    def test_leverage_capped_at_max(self) -> None:
        # Tight SL → big quantity → high leverage → should cap
        profile = {**_DEFAULT_PROFILE, "max_leverage": 2.0}
        capital, leverage, quantity = calculate_position_sizing(
            profile, entry_price=100.0, stop_loss=99.99, symbol="AAPL"
        )
        assert leverage is not None
        assert leverage <= 2.0

    def test_custom_position_size_percent(self) -> None:
        # 5% vs default 2% → 2.5x more risk
        cap_default, _, _ = calculate_position_sizing(_DEFAULT_PROFILE, 100.0, 95.0, symbol="AAPL")
        cap_custom, _, _ = calculate_position_sizing(
            _DEFAULT_PROFILE, 100.0, 95.0, position_size_percent=5.0, symbol="AAPL"
        )
        assert cap_custom is not None and cap_default is not None
        assert cap_custom > cap_default

    def test_crypto_quantity_precision(self) -> None:
        _, _, quantity = calculate_position_sizing(
            _DEFAULT_PROFILE, entry_price=50000.0, stop_loss=49000.0, symbol="BTC/USDT"
        )
        assert quantity is not None
        # Should have up to 8 decimal places
        parts = str(quantity).split(".")
        if len(parts) > 1:
            assert len(parts[1]) <= 8
