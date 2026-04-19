"""Candle data tools for market analysis."""

import logging
from datetime import datetime as dt

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token

logger = logging.getLogger(__name__)


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol by removing exchange prefixes like 'BINANCE:' or 'COINBASE:'."""
    # Remove common prefixes
    prefixes = ["BINANCE:", "COINBASE:", "KRAKEN:"]
    for prefix in prefixes:
        if symbol.upper().startswith(prefix):
            symbol = symbol[len(prefix) :]
    return symbol.upper()


class LatestCandleSchema(BaseModel):
    """Arguments for get_latest_candle tool."""

    symbol: str = Field(description="Asset symbol (e.g., 'BTC/USDT')")
    exchange: str = Field(default="binance", description="Exchange name (e.g., 'binance')")


@tool(args_schema=LatestCandleSchema)
async def get_latest_candle(symbol: str, exchange: str = "binance") -> str:
    """Fetches the current price (latest 5m candle) for a symbol.

    Usage:
    - Use for quick price checks before signal creation
    - Returns close price as suggestion_price for create_trading_insight
    - Faster than analyze_chart when you only need current price

    When NOT to Use:
    - Historical price lookup → use get_candles_around_date
    - Visual chart analysis → use analyze_chart
    - Technical indicator values → use get_indicator

    Output: Returns latest 5m OHLCV — Open, High, Low, Close (use for suggestion_price), Volume, Timestamp.

    Tool references:
    - Use get_candles_around_date for historical price lookup
    - Use get_indicator for technical analysis

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    symbol = _normalize_symbol(symbol)

    logger.info(f"Fetching latest candle for {symbol} on {exchange}")

    try:
        # Call async client method directly
        candle = await basement_client.get_latest_candle(token, symbol, exchange, interval="5m")

        if not candle:
            raise ToolException(
                f"No candle data found for {symbol} on {exchange}. The symbol may not exist or have no recent data."
            )
    except ToolException:
        raise
    except Exception as e:
        # Convert API/network errors to ToolException with descriptive message
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'deepalpha login' to re-authenticate.") from e
        elif "timeout" in error_msg.lower():
            raise ToolException(f"Request timeout while fetching candle for {symbol}.") from e
        else:
            raise ToolException(f"Failed to fetch candle for {symbol}: {error_msg}") from e

    # Format output
    return (
        f"Latest candle for {symbol} on {exchange}:\n"
        f"- Open: {candle.get('open', 'N/A')}\n"
        f"- High: {candle.get('high', 'N/A')}\n"
        f"- Low: {candle.get('low', 'N/A')}\n"
        f"- Close: {candle.get('close', 'N/A')}\n"
        f"- Volume: {candle.get('volume', 'N/A')}\n"
        f"- Timestamp: {candle.get('timestamp', 'N/A')}"
    )


class CandlesAroundDateSchema(BaseModel):
    """Arguments for get_candles_around_date tool."""

    symbol: str = Field(description="Asset symbol (e.g., 'BTC/USDT')")
    interval: str = Field(description="Candle interval (e.g., '1h', '4h', '1d')")
    exchange: str = Field(default="binance", description="Exchange name (e.g., 'binance')")
    date: str = Field(description="Target date: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'")


@tool(args_schema=CandlesAroundDateSchema)
async def get_candles_around_date(
    symbol: str,
    interval: str,
    date: str,
    exchange: str = "binance",
) -> str:
    """Fetches candles around a specific date for precise price lookup.

    Usage:
    - Use after visual chart analysis to get exact prices at key levels
    - Returns ~21 candles centered on target date (10 before + target + 10 after)
    - Use for finding support/resistance levels at specific dates

    When NOT to Use:
    - Current price → use get_latest_candle (faster)
    - Visual chart analysis → use analyze_chart
    - Technical indicators → use get_indicator

    NEVER:
    - Estimate or guess dates — derive from chart analysis or known events
    - Use for current price — use get_latest_candle instead

    Parameter guidance:
    - interval: Choose based on analysis timeframe (1d for macro, 1h for swing, 15m for entries)
    - date: ISO 8601 format. Time component optional (defaults to 00:00:00)

    Output: Table with Datetime, Open, High, Low, Close (use for exact prices), Volume.

    Tool references:
    - Use get_latest_candle for current price
    - Use get_indicator for technical analysis

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    symbol = _normalize_symbol(symbol)

    # Validate date format
    try:
        normalized_date = date.replace(" ", "T")
        if "T" in normalized_date:
            dt.fromisoformat(normalized_date)
        else:
            dt.fromisoformat(f"{normalized_date}T00:00:00")
    except ValueError as e:
        raise ToolException(f"Invalid date format: {date}. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS. Error: {e}") from e

    # Compute interval in seconds and center around target date
    INTERVAL_SECONDS = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }
    interval_secs = INTERVAL_SECONDS.get(interval, 3600)
    target_ts = int(
        dt.fromisoformat(normalized_date if "T" in normalized_date else f"{normalized_date}T00:00:00").timestamp()
    )

    try:
        candles = await basement_client.get_candles(
            token,
            symbol,
            exchange,
            interval,
            limit=21,
            from_ts=target_ts - (interval_secs * 10),
            to_ts=target_ts + (interval_secs * 10),
        )

        if not candles:
            raise ToolException(f"No candle data found around {date} for {symbol} on {exchange}.")
    except ToolException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'deepalpha login' to re-authenticate.") from e
        elif "timeout" in error_msg.lower():
            raise ToolException(f"Request timeout while fetching candles for {symbol}.") from e
        else:
            raise ToolException(f"Failed to fetch candles for {symbol}: {error_msg}") from e

    # Format output as a table
    output_lines = [
        f"Candles for {symbol} on {exchange} ({interval}):",
        "",
        "| Datetime            | Open      | High      | Low       | Close     | Volume     |",
        "|---------------------|-----------|-----------|-----------|-----------|------------|",
    ]

    for candle in candles[:21]:  # Limit to 21 candles
        ts = candle.get("timestamp", 0)
        if ts:
            candle_dt = dt.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
        else:
            candle_dt = "N/A"

        output_lines.append(
            f"| {candle_dt} | {candle.get('open', 0):9.2f} | "
            f"{candle.get('high', 0):9.2f} | {candle.get('low', 0):9.2f} | "
            f"{candle.get('close', 0):9.2f} | {candle.get('volume', 0):10.2f} |"
        )

    return "\n".join(output_lines)
