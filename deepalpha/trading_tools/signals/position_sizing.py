"""Position sizing tool for calculating quantity, leverage, and capital allocation."""

import logging

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token, get_user_profile, set_user_profile

logger = logging.getLogger(__name__)


def _round_quantity(quantity: float, symbol: str) -> float:
    """Round quantity based on asset type.

    Args:
        quantity: Raw calculated quantity
        symbol: Trading symbol

    Returns:
        Rounded quantity
    """
    symbol_upper = symbol.upper()

    # Crypto assets - use 8 decimal places
    if any(crypto in symbol_upper for crypto in ["BTC", "ETH", "USDT", "USDC", "BNB", "SOL", "ADA", "XRP", "/"]):
        return round(quantity, 8)

    # Stocks - round to whole numbers or 2 decimals for fractional shares
    if quantity < 1.0:
        return round(quantity, 2)
    return round(quantity, 0)


def calculate_position_sizing(
    user_profile: dict | None,
    entry_price: float,
    stop_loss: float,
    position_size_percent: float | None = None,
    symbol: str = "",
) -> tuple[float | None, float | None, float | None]:
    """Calculate position sizing using risk-based approach.

    This calculation uses the distance between entry price and stop loss to determine
    position size, ensuring consistent risk management across all trades.

    Args:
        user_profile: User profile dictionary with:
            - available_balance: Available balance for trading
            - max_leverage: Maximum allowed leverage
            - default_position_size: Default position size percentage
        entry_price: Entry price for the trade
        stop_loss: Stop loss price level
        position_size_percent: Risk as percentage of available balance (0-100)
        symbol: Trading symbol (used to determine asset type for rounding)

    Returns:
        Tuple of (capital_allocated, leverage, quantity) or (None, None, None) if calculation fails
    """
    # Validate inputs
    if not user_profile:
        return None, None, None

    if entry_price <= 0 or stop_loss <= 0:
        return None, None, None

    available_balance = user_profile.get("available_balance", 0)
    if available_balance <= 0:
        return None, None, None

    max_leverage = user_profile.get("max_leverage", 5.0)
    default_position_size = user_profile.get("default_position_size", 2.0)

    # Use provided position_size_percent or fall back to default
    if position_size_percent is None or position_size_percent <= 0:
        position_size_percent = default_position_size

    # Step 1: Calculate risk amount (dollars at risk)
    risk_amount = available_balance * (position_size_percent / 100)

    # Step 2: Calculate position size based on stop loss distance
    price_diff = abs(entry_price - stop_loss)
    if price_diff == 0:
        return None, None, None

    quantity = risk_amount / price_diff

    # Step 3: Calculate notional value
    notional_value = quantity * entry_price

    # Step 4: Calculate actual leverage (minimum 1.0)
    leverage = max(1.0, notional_value / available_balance)

    # Step 5: Cap leverage if exceeds max
    if leverage > max_leverage:
        max_notional = available_balance * max_leverage
        quantity = max_notional / entry_price
        notional_value = max_notional
        leverage = max_leverage

    # Step 6: Round quantity based on symbol
    quantity = _round_quantity(quantity, symbol)

    # Step 7: Recalculate capital after rounding
    capital_allocated = quantity * entry_price

    return capital_allocated, leverage, quantity


class PositionSizeSchema(BaseModel):
    """Arguments for calculate_position_size tool."""

    symbol: str = Field(description="Trading symbol (e.g., 'BTC/USDT')")
    entry_price: float = Field(description="Entry price for the trade")
    stop_loss: float = Field(description="Stop loss price level")
    position_size_percent: float | None = Field(
        default=None,
        description="Risk as percentage of balance (0-100). Uses profile default if not specified.",
    )


@tool(args_schema=PositionSizeSchema)
async def calculate_position_size(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    position_size_percent: float | None = None,
) -> str:
    """Calculates position sizing (quantity, leverage, capital) based on risk management.

    ## When to Use
    - Call BEFORE create_trading_insight to determine proper sizing
    - Uses risk-based approach: position size derived from stop loss distance
    - Ensures consistent risk across all trades regardless of asset

    ## When NOT to Use
    - Analyzing existing positions → use get_user_trading_insights
    - Getting current price → use get_latest_candle
    - Creating signals → use create_trading_insight (after this tool)

    CRITICAL: create_trading_insight requires output from this tool:
    - quantity, leverage, capital_allocated are mandatory fields
    - Never manually adjust these values — re-call this tool with different inputs instead

    ## Calculation Process
    1. risk_amount = account_balance x position_size_percent
    2. quantity = risk_amount / |entry_price - stop_loss|
    3. notional_value = quantity x entry_price
    4. leverage = notional_value / account_balance (capped at user's max_leverage)

    ## Field Constraints
    - entry_price: Must be > 0 and different from stop_loss
    - stop_loss: Must be > 0 and different from entry_price
    - position_size_percent: 0-100, uses profile default if omitted
      - Recommended: 1-5% for conservative, 5-10% for aggressive
    - If leverage exceeds user's max_leverage, quantity is automatically reduced

    ## Output Fields
    - Quantity: Exact number of units to trade (rounded by asset type)
    - Leverage: Notional / balance (capped at max_leverage)
    - Capital Allocated: Quantity x entry_price (margin requirement)
    - Risk Amount: Dollars at risk if stop loss hits

    Tool references:
    - Use get_latest_candle to get current price for entry_price
    - Pass ALL three outputs (quantity, leverage, capital_allocated) to create_trading_insight

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    # Get user profile (from context or fetch from API)
    user_profile = get_user_profile()
    if not user_profile:
        # Fetch from API
        profile = await basement_client.get_user_profile(token)
        if profile:
            set_user_profile(profile)
            user_profile = profile
        else:
            raise ToolException("Could not fetch user profile. Position sizing requires account balance information.")

    # Calculate position sizing
    capital, leverage, quantity = calculate_position_sizing(
        user_profile=user_profile,
        entry_price=entry_price,
        stop_loss=stop_loss,
        position_size_percent=position_size_percent,
        symbol=symbol,
    )

    if capital is None or leverage is None or quantity is None:
        raise ToolException(
            f"Position sizing calculation failed for {symbol}. "
            "Check that entry_price and stop_loss are valid and different."
        )

    # Calculate additional context
    available_balance = user_profile.get("available_balance", 0)
    default_position_size = user_profile.get("default_position_size", 2.0)
    position_size_used = position_size_percent or default_position_size
    risk_amount = available_balance * (position_size_used / 100)

    return (
        f"Position Sizing for {symbol}:\n"
        f"- Quantity: {quantity}\n"
        f"- Leverage: {leverage:.2f}x\n"
        f"- Capital Allocated: ${capital:.2f}\n"
        f"- Risk Amount: ${risk_amount:.2f} ({position_size_used}% of balance)\n"
        f"- Available Balance: ${available_balance:.2f}\n"
        f"\n"
        f"Use these values when calling create_trading_insight:\n"
        f"  quantity={quantity}\n"
        f"  leverage={leverage:.2f}\n"
        f"  capital_allocated={capital:.2f}"
    )
