"""Basement API client for DeepAlpha CLI.

Manages interactions with the Basement API for:
- Trading signals (CRUD)
- User profile and risk settings
- Market data (candles, indicators)
- Memories and skills

Usage:
    from deepalpha.clients import basement_client
    from deepalpha.auth import get_cli_token

    token = get_cli_token()
    signals = await basement_client.get_trading_signals(token)
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when CLI session is invalid or expired.

    The user should run `deepalpha login` to re-authenticate.
    """

    pass


class MonitoringQuotaError(Exception):
    """Raised when monitoring quota is exceeded for the user's subscription tier."""

    pass


BASEMENT_API_URL = os.environ.get("BASEMENT_API", "https://basement.deepalpha.mn")


class BasementClient:
    """Client for the Basement API."""

    def __init__(self, base_url: str = BASEMENT_API_URL, timeout: float = 30.0):
        """Initialize the Basement client.

        Args:
            base_url: Base URL for the Basement API
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, token: str) -> dict:
        """Build request headers with authentication."""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # =========================================================================
    # Trading Signals
    # =========================================================================

    async def get_trading_signals(
        self,
        token: str,
        status: str | None = None,
        ticker: str | None = None,
        page: int = 1,
        limit: int = 10,
    ) -> list[dict] | None:
        """Retrieve trading signals for the authenticated user.

        Args:
            token: JWT authentication token
            status: Filter by status (active, expired, executed, cancelled)
            ticker: Filter by ticker symbol
            page: Page number for pagination
            limit: Number of items per page

        Returns:
            List of trading signal dictionaries or None on failure
        """
        try:
            params = {"page": page, "limit": limit}
            if status:
                params["status"] = status
            if ticker:
                params["ticker"] = ticker

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/trading-signals",
                    params=params,
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    result = data.get("response", {})
                    # Handle both list and dict response formats
                    if isinstance(result, list):
                        return result
                    if isinstance(result, dict):
                        return result.get("signals", [])
                    return None
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to get trading signals: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while fetching trading signals")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching trading signals: {e}")
            return None

    async def create_trading_signal(
        self,
        token: str,
        symbol: str,
        position: str,
        entry_conditions: str,
        suggestion_price: float,
        stop_loss: float,
        confidence_score: float,
        rationale: str,
        invalid_condition: str,
        take_profit_levels: list[float] | None = None,
        entry_price: float | None = None,
        quantity: float | None = None,
        leverage: float | None = None,
        capital_allocated: float | None = None,
        images: list[str] | None = None,
        thread_id: str | None = None,
        expires_at: str | None = None,
        auto_execute: bool | None = None,
    ) -> dict | None:
        """Create a new trading signal.

        Args:
            token: JWT authentication token
            symbol: Ticker symbol (e.g., "BTC/USDT")
            position: Either "BUY" or "SELL"
            entry_conditions: Description of entry conditions
            suggestion_price: AI's suggested entry price
            stop_loss: Stop loss price level
            confidence_score: Confidence 0-100
            rationale: Reasoning behind the signal
            invalid_condition: Conditions that would invalidate the signal
            take_profit_levels: Target profit levels
            entry_price: Actual entry price (when executed)
            quantity: Suggested number of units
            leverage: Leverage multiplier (1.0-125.0)
            capital_allocated: Capital/margin allocated
            images: Image URLs (chart analysis, invalidation visuals, etc.)
            thread_id: Conversation thread ID
            expires_at: ISO 8601 expiry datetime
            auto_execute: Auto-execute flag

        Returns:
            Created trading signal dictionary or None on failure
        """
        try:
            payload = {
                "symbol": symbol,
                "position": position,
                "entry_conditions": entry_conditions,
                "suggestion_price": suggestion_price,
                "stop_loss": stop_loss,
                "confidence_score": confidence_score,
                "rationale": rationale,
                "invalid_condition": invalid_condition,
            }

            # Optional fields
            optional_fields = {
                "take_profit_levels": take_profit_levels,
                "entry_price": entry_price,
                "quantity": quantity,
                "leverage": leverage,
                "capital_allocated": capital_allocated,
                "images": images,
                "thread_id": thread_id,
                "expires_at": expires_at,
                "auto_execute": auto_execute,
            }
            for key, value in optional_fields.items():
                if value is not None:
                    payload[key] = value

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/trading-signals",
                    json=payload,
                    headers=self._headers(token),
                )

                if response.status_code == 201:
                    data = response.json()
                    logger.info(f"Created trading signal for {symbol}")
                    return data.get("response")
                if response.status_code == 401:
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                if response.status_code == 403:
                    # 403 may be a monitoring quota error, not an auth error
                    data = response.json()
                    msg = data.get("message", "Forbidden")
                    raise MonitoringQuotaError(msg)
                logger.error(f"Failed to create signal: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while creating trading signal")
            return None
        except (AuthenticationError, MonitoringQuotaError):
            raise
        except Exception as e:
            logger.error(f"Error creating trading signal: {e}")
            return None

    async def update_trading_signal(
        self,
        token: str,
        signal_id: int,
        status: str | None = None,
        entry_price: float | None = None,
        exit_price: float | None = None,
        profit_loss: float | None = None,
        executed_at: str | None = None,
        expires_at: str | None = None,
        reflection: str | None = None,
        current_price: float | None = None,
        filled_quantity: float | None = None,
        invalid_condition: str | None = None,
        stop_loss: float | None = None,
        take_profit_levels: list[float] | None = None,
        entry_conditions: str | None = None,
        rationale: str | None = None,
        images: list[str] | None = None,
    ) -> dict | None:
        """Update an existing trading signal.

        Args:
            token: JWT authentication token
            signal_id: The trading signal ID to update
            status: Status (active, expired, executed, cancelled)
            entry_price: Actual entry price
            exit_price: Actual exit price
            profit_loss: Profit or loss amount
            executed_at: ISO 8601 execution datetime
            expires_at: ISO 8601 expiry datetime
            reflection: Post-trade reflection notes
            current_price: Current market price
            filled_quantity: Filled quantity
            invalid_condition: Invalidation conditions
            stop_loss: Stop loss price
            take_profit_levels: Take profit levels
            entry_conditions: Entry conditions
            rationale: Technical reasoning
            images: Image URLs

        Returns:
            Updated trading signal dictionary or None on failure
        """
        try:
            payload = {}
            fields = {
                "status": status,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "profit_loss": profit_loss,
                "executed_at": executed_at,
                "expires_at": expires_at,
                "reflection": reflection,
                "current_price": current_price,
                "filled_quantity": filled_quantity,
                "invalid_condition": invalid_condition,
                "stop_loss": stop_loss,
                "take_profit_levels": take_profit_levels,
                "entry_conditions": entry_conditions,
                "rationale": rationale,
                "images": images,
            }
            for key, value in fields.items():
                if value is not None:
                    payload[key] = value

            if not payload:
                logger.warning("No fields provided to update")
                return None

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.patch(
                    f"{self.base_url}/api/v1/trading-signals/{signal_id}",
                    json=payload,
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Updated trading signal ID {signal_id}")
                    return data.get("response")
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to update signal: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while updating trading signal")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error updating trading signal: {e}")
            return None

    # =========================================================================
    # User Profile
    # =========================================================================

    async def get_user_profile(self, token: str) -> dict | None:
        """Retrieve the current user's profile including risk settings.

        Args:
            token: JWT authentication token

        Returns:
            User profile dictionary with fields:
            - account_balance: Total account balance
            - available_balance: Available balance for trading
            - margin_used: Currently used margin
            - default_position_size: Default position size percentage
            - max_leverage: Maximum allowed leverage
            Or None on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/profiles/me",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", {})
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to fetch profile: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while fetching user profile")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching user profile: {e}")
            return None

    async def get_portfolio_summary(self, token: str) -> dict | None:
        """Retrieve portfolio summary for the authenticated user.

        Args:
            token: JWT authentication token

        Returns:
            Portfolio summary dictionary with fields:
            - account_balance: Total account balance from profile
            - available_balance: Available balance for trading
            - margin_used: Margin locked in open positions
            - open_positions: List of open position dicts
            - total_positions: Number of open positions
            - total_unrealized_pnl: Total unrealized P&L (live-calculated)
            - total_roi_percentage: Total ROI percentage
            - total_realized_pnl: Sum of realized P&L across closed trades
            - win_rate: Win rate percentage across closed trades
            - total_closed_trades: Total number of closed trades
            - avg_risk_reward: Average risk-reward ratio
            Or None on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/trading-signals/portfolio",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", {})
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to fetch portfolio summary: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while fetching portfolio summary")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching portfolio summary: {e}")
            return None

    # =========================================================================
    # Favorite Tickers
    # =========================================================================

    async def get_favorite_tickers(self, token: str) -> list[dict] | None:
        """Retrieve the user's favorite/watchlist tickers.

        Args:
            token: JWT authentication token

        Returns:
            List of ticker dicts or None on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/favorite-tickers",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", [])
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to get favorite tickers: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while fetching favorite tickers")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching favorite tickers: {e}")
            return None

    async def get_ticker_stats(self, token: str, symbol: str) -> dict | None:
        """Get price stats for a ticker symbol.

        Args:
            token: JWT authentication token
            symbol: Ticker symbol (e.g., "BTC/USD")

        Returns:
            Dict with currentPrice, priceChange, priceChangePercent, etc.
            or None on failure
        """
        try:
            from urllib.parse import quote

            encoded_symbol = quote(symbol, safe="")

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/tickers/{encoded_symbol}/stats",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", {})
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                return None

        except httpx.TimeoutException:
            return None
        except AuthenticationError:
            raise
        except Exception:
            return None

    # =========================================================================
    # Market Data
    # =========================================================================

    async def get_candles(
        self,
        token: str,
        symbol: str,
        exchange: str = "binance",
        interval: str = "4h",
        limit: int = 100,
        from_ts: int | None = None,
        to_ts: int | None = None,
    ) -> list[dict] | None:
        """Retrieve candlestick data for a symbol.

        Args:
            token: JWT authentication token
            symbol: Trading pair (e.g., "BTC/USDT")
            exchange: Exchange name (default: binance)
            interval: Candle interval (e.g., 1m, 5m, 15m, 1h, 4h, 1d)
            limit: Number of candles to fetch
            from_ts: Start of time range as Unix timestamp (inclusive)
            to_ts: End of time range as Unix timestamp (inclusive)

        Returns:
            List of candle dictionaries with OHLCV data or None on failure
        """
        try:
            # URL-encode the symbol (e.g., BTC/USDT -> BTC%2FUSDT)
            from urllib.parse import quote

            encoded_symbol = quote(symbol, safe="")

            # Build URL with path parameters
            url = f"{self.base_url}/api/v1/candles/{encoded_symbol}/{interval}"
            params: dict = {}
            if limit:
                params["limit"] = limit
            if from_ts is not None:
                params["from"] = from_ts
            if to_ts is not None:
                params["to"] = to_ts

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", [])
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")

                # Log and raise for other errors
                error_detail = response.text
                logger.error(f"Failed to fetch candles: {response.status_code} - {error_detail}")
                raise Exception(f"API returned {response.status_code}: {error_detail[:200]}")

        except httpx.TimeoutException as e:
            logger.error("Timeout while fetching candles")
            raise Exception("Request timeout while fetching candles") from e
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching candles: {e}")
            raise

    async def get_latest_candle(
        self,
        token: str,
        symbol: str,
        exchange: str = "binance",
        interval: str = "5m",
    ) -> dict | None:
        """Get the most recent candle for a symbol.

        Args:
            token: JWT authentication token
            symbol: Trading pair (e.g., "BTC/USDT")
            exchange: Exchange name (default: binance)
            interval: Candle interval (default: 5m for current price)

        Returns:
            Latest candle dictionary or None on failure
        """
        candles = await self.get_candles(token, symbol, exchange, interval, limit=1)
        if candles and len(candles) > 0:
            return candles[0]
        return None

    async def get_indicator(
        self,
        token: str,
        symbol: str,
        indicator: str,
        exchange: str = "binance",
        interval: str = "4h",
        params: dict | None = None,
    ) -> dict | None:
        """Get technical indicator value for a symbol.

        Args:
            token: JWT authentication token
            symbol: Trading pair (e.g., "BTC/USDT")
            indicator: Indicator name (rsi, macd, ema, bbands, etc.)
            exchange: Exchange name (default: binance)
            interval: Candle interval
            params: Indicator-specific parameters (period, etc.)

        Returns:
            Indicator data dictionary or None on failure
        """
        try:
            request_params = {
                "symbol": symbol,
                "interval": interval,
                "indicator_type_code": indicator,
                "exchange": exchange,
            }
            if params:
                request_params.update(params)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/indicators/latest",
                    params=request_params,
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", {})
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")

                # Log and raise for other errors
                error_detail = response.text
                logger.error(f"Failed to fetch indicator: {response.status_code} - {error_detail}")
                raise Exception(f"API returned {response.status_code}: {error_detail[:200]}")

        except httpx.TimeoutException as e:
            logger.error("Timeout while fetching indicator")
            raise Exception("Request timeout while fetching indicator") from e
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching indicator: {e}")
            raise

    # =========================================================================
    # Economics Calendar
    # =========================================================================

    async def get_economics_calendar(
        self,
        token: str,
        from_date: str | None = None,
        to_date: str | None = None,
        country: str | None = None,
        impact: str | None = None,
        event: str | None = None,
    ) -> list[dict] | None:
        """Retrieve economic calendar events.

        Args:
            token: JWT authentication token
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            country: Country filter (e.g., US, JP)
            impact: Impact level filter (High, Medium, Low)
            event: Event name keyword filter

        Returns:
            List of economic calendar event dicts or None on failure
        """
        try:
            params: dict = {}
            if from_date:
                params["from"] = from_date
            if to_date:
                params["to"] = to_date
            if country:
                params["country"] = country
            if impact:
                params["impact"] = impact
            if event:
                params["event"] = event

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/economics-calendar",
                    params=params,
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", [])
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to get economics calendar: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while fetching economics calendar")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching economics calendar: {e}")
            return None

    # =========================================================================
    # Memories and Skills
    # =========================================================================

    async def get_active_memories(self, token: str) -> list[dict]:
        """Get active memories for the authenticated user.

        Args:
            token: JWT authentication token

        Returns:
            List of {"name": str, "content": str} dicts, or empty list on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/memories/active",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", [])
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to get memories: {response.status_code} - {response.text}")
                return []

        except httpx.TimeoutException:
            logger.error("Timeout while fetching memories")
            return []
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching memories: {e}")
            return []

    async def list_memories(self, token: str) -> list[dict] | None:
        """List all memories for the authenticated user.

        Args:
            token: JWT authentication token

        Returns:
            List of full UserMemory objects (id, name, description, content, is_active),
            or None on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/memories",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", [])
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to list memories: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while listing memories")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error listing memories: {e}")
            return None

    async def create_memory(
        self,
        token: str,
        name: str,
        content: str,
        description: str | None = None,
    ) -> dict | None:
        """Create a new memory.

        Args:
            token: JWT authentication token
            name: Memory name (max 100 chars, must be unique per user)
            content: Memory content (max 50KB)
            description: Optional description

        Returns:
            Created memory dict or None on failure
        """
        try:
            payload: dict = {"name": name, "content": content}
            if description is not None:
                payload["description"] = description

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/memories",
                    json=payload,
                    headers=self._headers(token),
                )

                if response.status_code == 201:
                    data = response.json()
                    logger.info(f"Created memory: {name}")
                    return data.get("response")
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to create memory: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while creating memory")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error creating memory: {e}")
            return None

    async def update_memory(
        self,
        token: str,
        memory_id: str,
        content: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> dict | None:
        """Update an existing memory.

        Args:
            token: JWT authentication token
            memory_id: The memory ID to update
            content: New content
            name: New name
            description: New description

        Returns:
            Updated memory dict or None on failure
        """
        try:
            payload: dict = {}
            if content is not None:
                payload["content"] = content
            if name is not None:
                payload["name"] = name
            if description is not None:
                payload["description"] = description

            if not payload:
                logger.warning("No fields provided to update memory")
                return None

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.put(
                    f"{self.base_url}/api/v1/memories/{memory_id}",
                    json=payload,
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Updated memory ID {memory_id}")
                    return data.get("response")
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to update memory: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while updating memory")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error updating memory: {e}")
            return None

    async def delete_memory(self, token: str, memory_id: str) -> bool:
        """Delete a memory.

        Args:
            token: JWT authentication token
            memory_id: The memory ID to delete

        Returns:
            True if deleted, False on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(
                    f"{self.base_url}/api/v1/memories/{memory_id}",
                    headers=self._headers(token),
                )

                if response.status_code in (200, 204):
                    logger.info(f"Deleted memory ID {memory_id}")
                    return True
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to delete memory: {response.status_code} - {response.text}")
                return False

        except httpx.TimeoutException:
            logger.error("Timeout while deleting memory")
            return False
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error deleting memory: {e}")
            return False

    async def get_active_skills(self, token: str) -> list[dict]:
        """Get active skills for the authenticated user.

        Args:
            token: JWT authentication token

        Returns:
            List of skill dicts with fields:
            - name: Skill identifier
            - description: What the skill does
            - content: Full SKILL.md content
            - path: Virtual path to the skill
            - target_agents: Agent names this skill applies to
            - assets: Asset dicts with path, storage_url, type
            Returns empty list on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/skills/active",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", [])
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to get skills: {response.status_code} - {response.text}")
                return []

        except httpx.TimeoutException:
            logger.error("Timeout while fetching skills")
            return []
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error fetching skills: {e}")
            return []

    # =========================================================================
    # Position Management
    # =========================================================================

    async def close_trading_signal(
        self,
        token: str,
        signal_id: int,
        exit_price: float,
        reflection: str | None = None,
    ) -> dict | None:
        """Close a trading position via the dedicated close endpoint.

        This endpoint handles capital release, P&L calculation, balance updates,
        and monitoring cleanup — unlike the generic PATCH update.

        Args:
            token: JWT authentication token
            signal_id: The trading signal ID to close
            exit_price: The exit price for the position
            reflection: Optional post-trade reflection notes

        Returns:
            Closed trading signal dictionary or None on failure
        """
        try:
            payload: dict = {"exit_price": exit_price}
            if reflection is not None:
                payload["reflection"] = reflection

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/trading-signals/{signal_id}/close",
                    json=payload,
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Closed trading signal ID {signal_id}")
                    return data.get("response")
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to close signal: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while closing trading signal")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error closing trading signal: {e}")
            return None

    # =========================================================================
    # Notifications
    # =========================================================================

    async def send_notification(
        self,
        token: str,
        title: str,
        body: str,
        priority: int = 5,
        category: str = "system",
        data: dict | None = None,
    ) -> dict | None:
        """Enqueue a notification for the authenticated user.

        Args:
            token: JWT authentication token
            title: Notification title
            body: Notification body
            priority: Priority level 1-10
            category: Notification category
            data: Optional additional data

        Returns:
            Created notification dict or None on failure
        """
        try:
            payload: dict = {
                "title": title,
                "body": body,
                "priority": priority,
                "category": category,
                "notification_type": "both",
            }
            if data:
                payload["data"] = data

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/notifications/enqueue",
                    json=payload,
                    headers=self._headers(token),
                )

                if response.status_code in (200, 201):
                    data_resp = response.json()
                    logger.info(f"Notification enqueued: {title}")
                    return data_resp.get("response")
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to enqueue notification: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while enqueuing notification")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error enqueuing notification: {e}")
            return None

    # =========================================================================
    # Subscription / Monitoring Quota
    # =========================================================================

    async def check_monitoring_quota(self, token: str) -> dict | None:
        """Check if the user can enable monitoring on more signals.

        Args:
            token: JWT authentication token

        Returns:
            Dict with allowed, current, limit fields, or None on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/subscription/monitoring-quota",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", {})
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to check monitoring quota: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while checking monitoring quota")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error checking monitoring quota: {e}")
            return None

    async def validate_monitoring_interval(self, token: str, interval_minutes: int) -> dict | None:
        """Validate a monitoring interval against the user's subscription tier.

        Args:
            token: JWT authentication token
            interval_minutes: Proposed monitoring interval in minutes

        Returns:
            Dict with valid, min, max fields, or None on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/subscription/limits",
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    limits = data.get("response", {})
                    min_interval = limits.get("min_monitoring_interval_minutes", 30)
                    max_interval = limits.get("max_monitoring_interval_minutes", 60)
                    return {
                        "valid": min_interval <= interval_minutes <= max_interval,
                        "min": min_interval,
                        "max": max_interval,
                    }
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'deepalpha login' to re-authenticate.")
                logger.error(f"Failed to validate monitoring interval: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout while validating monitoring interval")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error validating monitoring interval: {e}")
            return None


# Singleton instance
basement_client = BasementClient()
