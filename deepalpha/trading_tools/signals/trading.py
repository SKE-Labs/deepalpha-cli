"""Trading signal tools for creating, updating, and listing signals."""

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token, get_thread_id


class GetSignalsSchema(BaseModel):
    """Arguments for get_user_trading_insights tool."""

    status: str | None = Field(
        default=None,
        description="Filter by status: active, expired, executed, cancelled, closed",
    )
    ticker: str | None = Field(
        default=None,
        description="Filter by ticker symbol (e.g., 'BTC/USDT')",
    )


@tool(args_schema=GetSignalsSchema)
async def get_user_trading_insights(
    status: str | None = None,
    ticker: str | None = None,
) -> str:
    """Retrieves trading signals for the authenticated user.

    Usage:
    - Check existing signals before creating new ones
    - Review signal status and performance
    - Find signals to update or close

    When NOT to Use:
    - Creating new signals → use create_trading_insight
    - Updating signals → use update_trading_insight
    - Getting current price → use get_latest_candle

    Output fields:
    - status: active (waiting for entry), executed (position open), closed (P&L realized), cancelled, expired
    - suggestion_price: Recommended entry price from analysis
    - confidence_score: 0-100 from analyst findings

    Tool references:
    - Use create_trading_insight to create new signals
    - Use update_trading_insight to modify existing signals

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    signals = await basement_client.get_trading_signals(token, status=status, ticker=ticker)

    if signals is None:
        raise ToolException("Failed to fetch trading signals from API.")

    if not signals:
        filter_desc = []
        if status:
            filter_desc.append(f"status={status}")
        if ticker:
            filter_desc.append(f"ticker={ticker}")
        filter_str = f" (filters: {', '.join(filter_desc)})" if filter_desc else ""
        return f"No trading signals found{filter_str}."

    # Format signals as a readable list
    output_lines = [f"Found {len(signals)} trading signal(s):\n"]

    for signal in signals:
        signal_id = signal.get("id", "N/A")
        symbol = signal.get("symbol", "N/A")
        position = signal.get("position", "N/A")
        sig_status = signal.get("status", "N/A")
        suggestion_price = signal.get("suggestion_price", "N/A")
        stop_loss = signal.get("stop_loss", "N/A")
        confidence = signal.get("confidence_score", "N/A")

        output_lines.append(
            f"---\n"
            f"ID: {signal_id}\n"
            f"Symbol: {symbol} | Position: {position} | Status: {sig_status}\n"
            f"Suggestion Price: {suggestion_price} | Stop Loss: {stop_loss}\n"
            f"Confidence: {confidence}\n"
        )

    return "\n".join(output_lines)


class CreateSignalSchema(BaseModel):
    """Arguments for create_trading_insight tool."""

    symbol: str = Field(description="Ticker symbol (e.g., 'BTC/USDT')")
    position: str = Field(description="Either 'BUY' or 'SELL'")
    entry_conditions: str = Field(description="Description of entry conditions")
    suggestion_price: float = Field(description="AI's suggested entry price")
    stop_loss: float = Field(description="Stop loss price level")
    confidence_score: float = Field(description="Confidence 0-100")
    rationale: str = Field(description="Reasoning behind the signal")
    invalid_condition: str = Field(description="Conditions that would invalidate the signal")
    take_profit_levels: list[float] | None = Field(default=None, description="List of take profit price levels")
    quantity: float | None = Field(default=None, description="Number of units to trade")
    leverage: float | None = Field(default=None, description="Leverage multiplier (1.0-125.0)")
    capital_allocated: float | None = Field(default=None, description="Capital/margin allocated to this trade")


@tool(args_schema=CreateSignalSchema)
async def create_trading_insight(
    symbol: str,
    position: str,
    entry_conditions: str,
    suggestion_price: float,
    stop_loss: float,
    confidence_score: float,
    rationale: str,
    invalid_condition: str,
    take_profit_levels: list[float] | None = None,
    quantity: float | None = None,
    leverage: float | None = None,
    capital_allocated: float | None = None,
) -> str:
    """Creates a new trading signal.

    CRITICAL: This tool requires prior technical analysis. Do NOT call without:
    1. get_latest_candle — current price for suggestion_price
    2. calculate_position_size — quantity, leverage, capital_allocated

    ## Field Descriptions & Quality Standards

    - symbol: Trading pair (e.g., "BTC/USDT")
    - position: "BUY" or "SELL" — must match analyst bias direction
    - entry_conditions: When to enter. Either immediate OR conditional (never mixed):
      - Immediate: "4H close above 75,200 with RSI above 50"
      - Conditional: Multi-step sequence with numbered steps
    - suggestion_price: EXACT price from get_latest_candle — never estimated or rounded
    - stop_loss: Structural break level from analyst's invalidation — must differ from entry
    - confidence_score: 0-100, must reflect timeframe confluence:
      - Never > 80 without HIGH confluence (all TF align)
      - Never > 70 without at least MEDIUM confluence
    - rationale: Must cite specific technicals from analyst (e.g., "Daily HH/HL, 1H supply zone, RSI divergence")
    - invalid_condition: EXACT price level + timeframe + what structure breaks
    - take_profit_levels: Must be ascending for BUY, descending for SELL
    - quantity/leverage/capital_allocated: Must come from calculate_position_size output

    NEVER:
    - Create without calling calculate_position_size first
    - Invent price levels not derived from analysis
    - Create with confidence_score > 70 without strong confluence
    - Set take_profit equal to stop_loss (meaningless R:R)
    - Set entry_price equal to stop_loss (zero risk)

    Tool references:
    - Use calculate_position_size before this tool
    - Use get_latest_candle for current price
    - Use get_user_trading_insights to check for existing signals on same pair

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    # Validate position
    position = position.upper()
    if position not in ("BUY", "SELL"):
        raise ToolException(f"Invalid position: {position}. Must be 'BUY' or 'SELL'.")

    # Validate confidence score
    if not 0 <= confidence_score <= 100:
        raise ToolException(f"Invalid confidence_score: {confidence_score}. Must be 0-100.")

    # Get thread_id from context if available
    thread_id = get_thread_id()

    result = await basement_client.create_trading_signal(
        token=token,
        symbol=symbol,
        position=position,
        entry_conditions=entry_conditions,
        suggestion_price=suggestion_price,
        stop_loss=stop_loss,
        confidence_score=confidence_score,
        rationale=rationale,
        invalid_condition=invalid_condition,
        take_profit_levels=take_profit_levels,
        quantity=quantity,
        leverage=leverage,
        capital_allocated=capital_allocated,
        thread_id=thread_id,
    )

    if not result:
        raise ToolException("Failed to create trading signal. Check API connection and parameters.")

    signal_id = result.get("id", "N/A")
    return (
        f"Trading signal created successfully!\n"
        f"ID: {signal_id}\n"
        f"Symbol: {symbol}\n"
        f"Position: {position}\n"
        f"Suggestion Price: {suggestion_price}\n"
        f"Stop Loss: {stop_loss}\n"
        f"Take Profit Levels: {take_profit_levels or 'Not set'}\n"
        f"Confidence: {confidence_score}%\n"
        f"Quantity: {quantity or 'Not set'}\n"
        f"Leverage: {leverage or 'Not set'}x\n"
        f"Capital Allocated: ${capital_allocated or 'Not set'}"
    )


class UpdateSignalSchema(BaseModel):
    """Arguments for update_trading_insight tool."""

    signal_id: int = Field(description="The trading signal ID to update")
    status: str | None = Field(
        default=None,
        description="New status: active, expired, executed, cancelled, closed",
    )
    entry_price: float | None = Field(default=None, description="Actual entry price")
    exit_price: float | None = Field(default=None, description="Actual exit price")
    stop_loss: float | None = Field(default=None, description="Updated stop loss")
    take_profit_levels: list[float] | None = Field(default=None, description="Updated take profit levels")
    reflection: str | None = Field(default=None, description="Post-trade reflection notes")


@tool(args_schema=UpdateSignalSchema)
async def update_trading_insight(
    signal_id: int,
    status: str | None = None,
    entry_price: float | None = None,
    exit_price: float | None = None,
    stop_loss: float | None = None,
    take_profit_levels: list[float] | None = None,
    reflection: str | None = None,
) -> str:
    """Updates an existing trading signal.

    Usage:
    - Update signal when trade is entered (set entry_price, status='executed')
    - Close a position (set exit_price, status='closed')
    - Adjust stop loss or take profit levels
    - Add reflection notes after trade closes

    When NOT to Use:
    - Creating new signals → use create_trading_insight
    - Checking signal status → use get_user_trading_insights
    - Position sizing → use calculate_position_size

    Status values:
    - active: Signal is live, waiting for entry
    - executed: Trade entered, position is OPEN
    - closed: Position exited, P&L realized
    - cancelled: Signal invalidated
    - expired: Signal expired without execution

    Field constraints:
    - entry_price: Must be > 0 and reasonable vs suggestion_price
    - exit_price: If set, status should be 'closed'
    - stop_loss: For BUY positions, new SL should be >= current SL (never worse). For SELL, new SL <= current SL
    - take_profit_levels: Must maintain order (ascending for BUY, descending for SELL)
    - reflection: Post-trade notes should cite entry execution vs plan, whether thesis held, and improvements

    NEVER:
    - Update a signal you haven't retrieved with get_user_trading_insights
    - Set status to 'executed' without entry_price
    - Modify signals created by other users
    - Adjust SL to a worse level (applies to ALL update mechanisms)

    Tool references:
    - Use get_user_trading_insights to find signal IDs first

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    # Validate status if provided
    if status:
        status = status.lower()
        valid_statuses = ["active", "expired", "executed", "cancelled", "closed"]
        if status not in valid_statuses:
            raise ToolException(f"Invalid status: {status}. Must be one of: {', '.join(valid_statuses)}")

    result = await basement_client.update_trading_signal(
        token=token,
        signal_id=signal_id,
        status=status,
        entry_price=entry_price,
        exit_price=exit_price,
        stop_loss=stop_loss,
        take_profit_levels=take_profit_levels,
        reflection=reflection,
    )

    if not result:
        raise ToolException(f"Failed to update trading signal ID {signal_id}.")

    # Build update summary
    updates = []
    if status:
        updates.append(f"status={status}")
    if entry_price:
        updates.append(f"entry_price={entry_price}")
    if exit_price:
        updates.append(f"exit_price={exit_price}")
    if stop_loss:
        updates.append(f"stop_loss={stop_loss}")
    if take_profit_levels:
        updates.append(f"take_profit_levels={take_profit_levels}")
    if reflection:
        updates.append("reflection added")

    update_str = ", ".join(updates) if updates else "no changes"
    return f"Trading signal ID {signal_id} updated successfully.\nChanges: {update_str}"
