"""Local chart generation tool using Basement API candle data and Plotly."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from langchain_core.tools import ToolException, tool
from plotly.subplots import make_subplots
from pydantic import BaseModel, Field

from deepalpha.clients import basement_client
from deepalpha.config import settings
from deepalpha.context import get_jwt_token

logger = logging.getLogger(__name__)

# Optimal candle counts per interval for chart readability
CANDLE_LIMITS = {
    "1m": 240,
    "5m": 288,
    "15m": 384,
    "30m": 480,
    "1h": 336,
    "4h": 450,
    "1d": 365,
}


def _build_data_summary(symbol: str, df: pd.DataFrame) -> str:
    latest = df.iloc[-1]
    close = latest["close"]
    open_price = latest["open"]
    high = latest["high"]
    low = latest["low"]
    volume = latest["volume"]

    change = close - open_price
    change_pct = (change / open_price) * 100 if open_price else 0

    lines = [
        f"<b>{symbol}</b>",
        f"Price: ${close:,.2f}",
        f"Change: {change:+.2f} ({change_pct:+.2f}%)",
        f"H: ${high:,.2f}  L: ${low:,.2f}",
        f"Vol: {volume:,.0f}",
    ]

    return "<br>".join(lines)


def _render_chart(symbol: str, interval: str, exchange: str, df: pd.DataFrame) -> str:
    """Render a candlestick chart locally and return the file path."""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.8, 0.2],
        subplot_titles=[f"{symbol} - {interval} ({exchange})", "Volume"],
    )

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#00ff88",
            decreasing_line_color="#ff3860",
            increasing_fillcolor="#00ff88",
            decreasing_fillcolor="#ff3860",
            line=dict(width=2),
        ),
        row=1,
        col=1,
    )

    # Volume
    vol_colors = ["#00ff88" if r["close"] >= r["open"] else "#ff3860" for _, r in df.iterrows()]
    fig.add_trace(
        go.Bar(x=df.index, y=df["volume"], name="Volume", marker_color=vol_colors, opacity=0.5, showlegend=False),
        row=2,
        col=1,
    )

    # Data summary annotation
    data_summary = _build_data_summary(symbol, df)
    fig.add_annotation(
        text=data_summary,
        xref="paper",
        yref="paper",
        x=0.98,
        y=0.98,
        xanchor="right",
        yanchor="top",
        showarrow=False,
        bgcolor="rgba(20, 20, 20, 0.9)",
        bordercolor="#00ff88",
        borderwidth=2,
        borderpad=10,
        font=dict(size=13, color="#ffffff", family="monospace"),
        align="left",
    )

    # Layout
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0a0a0a",
        plot_bgcolor="#0a0a0a",
        font=dict(size=14, color="#ffffff", family="Arial"),
        title=dict(text=f"<b>{symbol} - {interval} ({exchange})</b>", font=dict(size=18), x=0.5, xanchor="center"),
        showlegend=False,
        xaxis_rangeslider_visible=False,
        height=800,
        margin=dict(l=80, r=80, t=100, b=80),
        hovermode="x unified",
    )

    tick_fmt = "%Y-%m-%d\n%H:%M" if interval in ("1m", "5m", "15m", "30m", "1h") else "%Y-%m-%d"
    for i in range(1, 3):
        fig.update_xaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor="#2a2a2a",
            showline=True,
            linewidth=2,
            linecolor="#444444",
            showticklabels=True,
            tickfont=dict(size=12, color="#ffffff"),
            tickformat=tick_fmt,
            tickangle=-45,
            row=i,
            col=1,
        )
        fig.update_yaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor="#2a2a2a",
            showline=True,
            linewidth=2,
            linecolor="#444444",
            row=i,
            col=1,
        )

    # Save to local file
    charts_dir = Path(settings.user_deepalpha_dir) / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    safe_symbol = symbol.replace("/", "-")
    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_symbol}_{interval}_{ts}.png"
    image_path = str(charts_dir / filename)

    fig.write_image(image_path, width=1600, height=800, scale=2)
    logger.info(f"Chart saved to {image_path}")

    return image_path


class GenerateChartSchema(BaseModel):
    """Arguments for analyze_chart tool."""

    symbol: str = Field(description="Asset symbol (e.g., 'BTC/USDT'). Must match exchange format.")
    interval: str = Field(description="Candle interval: 1d, 4h, 1h, 30m, 15m, 5m")
    exchange: str = Field(default="binance", description="Data source (e.g., 'binance')")
    from_date: str | None = Field(
        default=None,
        description="Start date/time for the chart range (ISO 8601, e.g., '2025-01-01' or '2025-01-01T08:00:00'). If omitted, uses default candle limit.",
    )
    to_date: str | None = Field(
        default=None,
        description="End date/time for the chart range (ISO 8601, e.g., '2025-02-01' or '2025-02-01T16:00:00'). If omitted, defaults to now.",
    )


@tool(args_schema=GenerateChartSchema)
async def analyze_chart(
    symbol: str,
    interval: str,
    exchange: str = "binance",
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Generates a candlestick chart image for visual analysis.

    Usage:
    - Call with symbol, interval, and exchange to generate a chart image
    - Optionally pass from_date and/or to_date to render a specific date range
    - Charts show candlesticks and volume
    - STRONGLY recommended: Call multiple charts in parallel for multi-timeframe analysis

    When NOT to Use:
    - Just need current price → use get_latest_candle (much faster)
    - Need exact price at a specific date → use get_candles_around_date
    - Need indicator values → use get_indicator

    Parameter constraints:
    - interval: One of [1d, 4h, 1h, 30m, 15m, 5m]
    - from_date/to_date: ISO 8601 format. Keep ranges reasonable:
      - 1d: up to 2 years. 1h-4h: up to 6 months. 15m-30m: up to 2 weeks. 5m: up to 1 week

    Tool references:
    - Use get_latest_candle for current price only (faster)
    - Use get_candles_around_date for exact historical data points
    - Use get_indicator for technical indicator values

    Returns: Dictionary with {"type": "image_url", "image_url": "file://path.png"}.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    limit = CANDLE_LIMITS.get(interval, 180)

    # Convert ISO date strings to Unix timestamps for the API
    from_ts = int(pd.to_datetime(from_date, utc=True).timestamp()) if from_date else None
    to_ts = int(pd.to_datetime(to_date, utc=True).timestamp()) if to_date else None

    logger.info(f"Generating chart for {symbol} {interval} on {exchange} (limit={limit})")

    try:
        candles = await basement_client.get_candles(
            token, symbol, exchange, interval, limit=limit, from_ts=from_ts, to_ts=to_ts
        )
        if not candles:
            raise ToolException(f"No candle data found for {symbol} on {exchange} ({interval})")

        df = pd.DataFrame(candles)

        # Ensure required columns
        required = {"open", "high", "low", "close", "volume", "timestamp"}
        missing = required - set(df.columns)
        if missing:
            raise ToolException(f"Candle data missing columns: {missing}")

        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("datetime", inplace=True)
        df.sort_index(inplace=True)

        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        image_path = _render_chart(symbol, interval, exchange, df)

        return {
            "type": "image_url",
            "image_url": f"file://{image_path}",
        }

    except ToolException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'deepalpha login' to re-authenticate.") from e
        raise ToolException(f"Failed to generate chart for {symbol}: {error_msg}") from e
