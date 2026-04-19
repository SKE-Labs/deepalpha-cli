"""Economics calendar tool via Basement API."""

import logging

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token

logger = logging.getLogger(__name__)


class EconomicsCalendarSchema(BaseModel):
    """Arguments for get_economics_calendar tool."""

    from_date: str = Field(description="Start date (YYYY-MM-DD)")
    to_date: str = Field(description="End date (YYYY-MM-DD)")
    country: str = Field(default="", description="Country filter (e.g., US, JP), or empty for all")
    impact: str = Field(default="", description="Impact level filter: 'High', 'Medium', 'Low', or empty for all")
    event: str = Field(default="", description="Event name keyword filter, or empty for all")


@tool(args_schema=EconomicsCalendarSchema)
async def get_economics_calendar(
    from_date: str,
    to_date: str,
    country: str = "",
    impact: str = "",
    event: str = "",
) -> str:
    """Fetches economic calendar events for a date range.

    Usage:
    - Check upcoming high-impact events that may affect markets
    - Filter by country, impact level, or event name
    - Use before trading decisions to assess macro risks

    Impact levels: High, Medium, Low
    Countries: US, JP, GB, EU, AU, CA, etc.

    IMPORTANT:
    - Combine with technical and fundamental analysis
    - High-impact events can cause significant volatility
    - Check events before and after planned trade entries

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    logger.info(f"Fetching economics calendar: {from_date} to {to_date}")

    try:
        events = await basement_client.get_economics_calendar(
            token, from_date, to_date, country or None, impact or None, event or None
        )

        if events is None:
            raise ToolException("Failed to fetch economics calendar")

        if not events:
            filters = [f"{from_date} to {to_date}"]
            if country:
                filters.append(f"country={country}")
            if impact:
                filters.append(f"impact={impact}")
            if event:
                filters.append(f"event={event}")
            return f"No economic events found for: {', '.join(filters)}"

    except ToolException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'deepalpha login' to re-authenticate.") from e
        raise ToolException(f"Failed to fetch economics calendar: {error_msg}") from e

    # Format output as table
    lines = [
        f"Economic Calendar: {from_date} to {to_date}\n",
        "| Date | Time | Country | Impact | Event | Actual | Forecast | Previous |",
        "|------|------|---------|--------|-------|--------|----------|----------|",
    ]

    for evt in events:
        date = evt.get("date", "N/A")
        # Extract just the date and time parts
        if "T" in str(date):
            date_part = str(date).split("T")[0]
            time_part = str(date).split("T")[1][:5] if "T" in str(date) else ""
        else:
            date_part = str(date)[:10]
            time_part = str(date)[11:16] if len(str(date)) > 10 else ""

        lines.append(
            f"| {date_part} | {time_part} "
            f"| {evt.get('country', 'N/A')} "
            f"| {evt.get('impact', 'N/A')} "
            f"| {evt.get('event', 'N/A')} "
            f"| {evt.get('actual', 'N/A')} "
            f"| {evt.get('forecast', 'N/A')} "
            f"| {evt.get('previous', 'N/A')} |"
        )

    lines.append(f"\nTotal events: {len(events)}")

    return "\n".join(lines)
