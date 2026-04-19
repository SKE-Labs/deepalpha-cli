"""Technical indicator tools for market analysis."""

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token


class IndicatorSchema(BaseModel):
    """Arguments for get_indicator tool."""

    symbol: str = Field(description="Asset symbol (e.g., 'BTC/USDT')")
    indicator: str = Field(description="Indicator name: rsi, macd, ema, sma, bbands, stoch, mfi, dmi, supertrend")
    exchange: str = Field(default="binance", description="Exchange name")
    interval: str = Field(default="4h", description="Candle interval (e.g., '1h', '4h', '1d')")
    period: int | None = Field(default=None, description="Indicator period (e.g., 14 for RSI)")


@tool(args_schema=IndicatorSchema)
async def get_indicator(
    symbol: str,
    indicator: str,
    exchange: str = "binance",
    interval: str = "4h",
    period: int | None = None,
) -> str:
    """Fetches technical indicator values for a symbol.

    Indicator categories:
    - Momentum: rsi, stoch, mfi
    - Trend: ema, sma, macd, supertrend, dmi
    - Volatility: bbands (Bollinger Bands)

    Common periods:
    - RSI: 14 (default)
    - EMA/SMA: 20, 50, 200
    - MACD: 12/26/9 (default)
    - Bollinger Bands: 20 (default)

    Usage:
    - Use for confirming chart analysis with numerical data
    - Combine multiple indicators for confluence
    - Check divergences between price and momentum

    Tool references:
    - Use get_latest_candle for current price
    - Use get_candles_around_date for historical data

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    # Normalize symbol
    prefixes = ["BINANCE:", "COINBASE:"]
    for prefix in prefixes:
        if symbol.upper().startswith(prefix):
            symbol = symbol[len(prefix) :]
    symbol = symbol.upper()

    # Build params
    params = {}
    if period:
        params["period"] = period

    # Get indicator data
    try:
        data = await basement_client.get_indicator(token, symbol, indicator, exchange, interval, params)

        if not data:
            raise ToolException(
                f"No {indicator} data found for {symbol} on {exchange}. "
                f"The indicator may not be available for this symbol."
            )
    except ToolException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'deepalpha login' to re-authenticate.") from e
        elif "404" in error_msg:
            raise ToolException(
                f"No {indicator} data found for {symbol} on {exchange}. The indicator may not be calculated yet."
            ) from e
        elif "timeout" in error_msg.lower():
            raise ToolException(f"Request timeout while fetching {indicator} for {symbol}.") from e
        else:
            raise ToolException(f"Failed to fetch {indicator} for {symbol}: {error_msg}") from e

    # Format output based on indicator type
    indicator_lower = indicator.lower()

    if indicator_lower == "rsi":
        value = data.get("value", data.get("rsi", "N/A"))
        return f"RSI ({interval}) for {symbol}: {value}"

    if indicator_lower == "macd":
        macd = data.get("macd", data.get("value", "N/A"))
        signal = data.get("signal", data.get("macd_signal", "N/A"))
        histogram = data.get("histogram", data.get("macd_histogram", "N/A"))
        return (
            f"MACD ({interval}) for {symbol}:\n- MACD Line: {macd}\n- Signal Line: {signal}\n- Histogram: {histogram}"
        )

    if indicator_lower in ("ema", "sma"):
        value = data.get("value", "N/A")
        p = period or 20
        return f"{indicator.upper()}({p}) ({interval}) for {symbol}: {value}"

    if indicator_lower == "bbands":
        upper = data.get("upper", data.get("valueUpperBand", "N/A"))
        middle = data.get("middle", data.get("valueMiddleBand", "N/A"))
        lower = data.get("lower", data.get("valueLowerBand", "N/A"))
        return f"Bollinger Bands ({interval}) for {symbol}:\n- Upper: {upper}\n- Middle: {middle}\n- Lower: {lower}"

    if indicator_lower == "stoch":
        k = data.get("k", data.get("value_k", "N/A"))
        d = data.get("d", data.get("value_d", "N/A"))
        return f"Stochastic ({interval}) for {symbol}:\n- %K: {k}\n- %D: {d}"

    if indicator_lower == "dmi":
        plus_di = data.get("plus_di", data.get("adx_plus_di", "N/A"))
        minus_di = data.get("minus_di", data.get("adx_minus_di", "N/A"))
        adx = data.get("adx", "N/A")
        return f"DMI ({interval}) for {symbol}:\n- +DI: {plus_di}\n- -DI: {minus_di}\n- ADX: {adx}"

    if indicator_lower == "supertrend":
        value = data.get("value", data.get("supertrend", "N/A"))
        direction = data.get("direction", data.get("supertrend_direction", "N/A"))
        return f"Supertrend ({interval}) for {symbol}:\n- Value: {value}\n- Direction: {direction}"

    # Generic format for other indicators
    return f"{indicator.upper()} ({interval}) for {symbol}: {data}"
