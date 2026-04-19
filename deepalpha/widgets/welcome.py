"""Welcome banner widget for deepalpha-cli."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from deepalpha._version import __version__
from deepalpha.config import settings

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class WelcomeBanner(Vertical):
    """Welcome banner displayed at startup with two-column layout."""

    DEFAULT_CSS = """
    WelcomeBanner {
        height: auto;
        border: round #333333;
        border-title-color: #e2e8f0;
        border-title-style: bold;
        padding: 1 2;
        margin: 0 0 1 0;
    }

    WelcomeBanner .welcome-columns {
        height: auto;
    }

    WelcomeBanner .welcome-left {
        width: 1fr;
        height: auto;
        padding-right: 2;
    }

    WelcomeBanner .welcome-right {
        width: 1fr;
        height: auto;
        padding-left: 2;
    }

    WelcomeBanner .welcome-greeting {
        color: white;
        text-style: bold;
        margin-bottom: 1;
    }

    WelcomeBanner .welcome-detail {
        color: $text-muted;
    }

    WelcomeBanner .welcome-context {
        color: $text-muted;
        margin-top: 1;
    }

    WelcomeBanner .welcome-section-title {
        color: #e2e8f0;
        text-style: bold;
        margin-bottom: 1;
    }

    WelcomeBanner .welcome-config-table {
        color: $text-muted;
    }

    WelcomeBanner .welcome-tips-section {
        color: $text-muted;
        margin-top: 1;
    }

    WelcomeBanner .welcome-tip-line {
        color: $text-muted;
    }

    WelcomeBanner .welcome-row-2 {
        height: auto;
        border-top: solid #333333;
        margin-top: 1;
        padding-top: 1;
    }

    WelcomeBanner .portfolio-section {
        width: 1fr;
        height: auto;
        padding-right: 2;
    }

    WelcomeBanner .trades-section {
        width: 1fr;
        height: auto;
        padding-left: 2;
    }

    WelcomeBanner .watchlist-section {
        width: 1fr;
        height: auto;
        padding-left: 2;
    }

    WelcomeBanner .welcome-prompt {
        color: white;
        margin-top: 1;
        text-align: center;
    }
    """

    def __init__(
        self,
        model_name: str | None = None,
        agent_info: dict[str, int] | None = None,
        cwd: str | None = None,
        user_email: str | None = None,
        auth_token: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._model_name = model_name or settings.model_name
        self._agent_info = agent_info or {}
        self._cwd = cwd or str(Path.cwd())
        self._user_email = user_email
        self._auth_token = auth_token
        self.border_title = f"DeepAlpha v{__version__}"

    def _format_cwd(self) -> str:
        """Format cwd relative to home directory."""
        home = str(Path.home())
        if self._cwd.startswith(home):
            return "~" + self._cwd[len(home) :]
        return self._cwd

    def _get_greeting(self) -> str:
        """Get greeting from email or fallback."""
        if self._user_email:
            name = self._user_email.split("@")[0]
            return f"Welcome back, {name}!"
        return "Welcome!"

    def _get_context_line(self) -> str | None:
        """Build context line from agent info."""
        agents_md = self._agent_info.get("agents_md_count", 0)
        skills = self._agent_info.get("skills_count", 0)
        parts = []
        if agents_md:
            label = "AGENTS.md" if agents_md == 1 else "AGENTS.md files"
            parts.append(f"{agents_md} {label}")
        if skills:
            label = "skill" if skills == 1 else "skills"
            parts.append(f"{skills} {label}")
        if parts:
            return " | ".join(parts)
        return None

    def compose(self) -> ComposeResult:
        """Compose the two-column welcome layout."""
        with Horizontal(classes="welcome-columns"):
            # Left column
            with Vertical(classes="welcome-left"):
                yield Static(self._get_greeting(), classes="welcome-greeting")

                if self._model_name:
                    yield Static(f"[dim]{self._model_name}[/dim]", classes="welcome-detail")

                yield Static(f"[dim]{self._format_cwd()}[/dim]", classes="welcome-detail")

                # LangSmith status
                langsmith_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
                langsmith_tracing = os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2")
                if langsmith_key and langsmith_tracing:
                    project = settings.deepalpha_langchain_project or os.environ.get("LANGSMITH_PROJECT") or "default"
                    yield Static(
                        f"[green]\u2713[/green] [dim]LangSmith: '{project}'[/dim]",
                        classes="welcome-detail",
                    )

                context_line = self._get_context_line()
                if context_line:
                    yield Static(f"[dim]{context_line}[/dim]", classes="welcome-context")

            # Right column
            with Vertical(classes="welcome-right"):
                yield Static(
                    "[bold]Tips[/bold]",
                    classes="welcome-tips-section",
                )
                yield Static(
                    "  [dim]@[/dim] files  [dim]/[/dim] commands  [dim]![/dim] bash\n"
                    "  [dim]Shift+Tab[/dim] auto-approve",
                    classes="welcome-tip-line",
                )

        # Row 2: Portfolio + Watchlist + Open Trades (only when authenticated)
        if self._auth_token:
            with Horizontal(classes="welcome-row-2"):
                with Vertical(classes="portfolio-section"):
                    yield Static("Portfolio", classes="welcome-section-title")
                    yield Static("[dim]Loading...[/dim]", id="portfolio-summary")
                with Vertical(classes="watchlist-section"):
                    yield Static("Watchlist", classes="welcome-section-title")
                    yield Static("[dim]Loading...[/dim]", id="watchlist")
                with Vertical(classes="trades-section"):
                    yield Static("Open Trades", classes="welcome-section-title")
                    yield Static("[dim]Loading...[/dim]", id="trades-list")

        yield Static("What would you like to analyze?", classes="welcome-prompt")

    async def on_mount(self) -> None:
        """Fetch portfolio, trades, and watchlist data asynchronously after render."""
        if not self._auth_token:
            return

        try:
            from deepalpha.clients.basement import basement_client

            portfolio, signals, favorites = await asyncio.gather(
                basement_client.get_portfolio_summary(self._auth_token),
                basement_client.get_trading_signals(self._auth_token, status="active", limit=5),
                basement_client.get_favorite_tickers(self._auth_token),
                return_exceptions=True,
            )

            # Handle exceptions from gather
            if isinstance(portfolio, Exception):
                logger.error(f"Failed to fetch portfolio: {portfolio}")
                portfolio = None
            if isinstance(signals, Exception):
                logger.error(f"Failed to fetch signals: {signals}")
                signals = None
            if isinstance(favorites, Exception):
                logger.error(f"Failed to fetch favorites: {favorites}")
                favorites = None

            self._update_portfolio_display(portfolio)
            self._update_trades_display(portfolio, signals)

            # Fetch stats for favorite tickers in parallel
            if favorites:
                stats_results = await asyncio.gather(
                    *[basement_client.get_ticker_stats(self._auth_token, t.get("ticker", "")) for t in favorites[:8]],
                    return_exceptions=True,
                )
                stats_map = {}
                for i, t in enumerate(favorites[:8]):
                    result = stats_results[i]
                    if not isinstance(result, Exception) and result:
                        stats_map[t.get("ticker", "")] = result
                self._update_watchlist_display(favorites, stats_map)
            else:
                self._update_watchlist_display(None, {})

        except Exception as e:
            logger.error(f"Error loading portfolio data: {e}")
            self._update_portfolio_display(None)
            self._update_trades_display(None, None)
            self._update_watchlist_display(None, {})

    def _update_portfolio_display(self, portfolio: dict | None) -> None:
        """Update the portfolio summary Static widget."""
        try:
            widget = self.query_one("#portfolio-summary", Static)
        except Exception:
            return

        if portfolio is None:
            widget.update("[dim]Could not load portfolio[/dim]")
            return

        capital = portfolio.get("account_balance", 0)
        available = portfolio.get("available_balance", 0)
        margin = portfolio.get("margin_used", 0)
        total_positions = portfolio.get("total_positions", 0)
        pnl = portfolio.get("total_unrealized_pnl", 0)
        roi = portfolio.get("total_roi_percentage", 0)

        # Color P&L and ROI
        pnl_sign = "+" if pnl >= 0 else ""
        pnl_color = "green" if pnl >= 0 else "red"
        roi_sign = "+" if roi >= 0 else ""
        roi_color = "green" if roi >= 0 else "red"

        lines = (
            f"  Capital     ${capital:,.2f}\n"
            f"  Available   ${available:,.2f}\n"
            f"  Margin      ${margin:,.2f}\n"
            f"  Positions   {total_positions}\n"
            f"  Unrl. P&L   [{pnl_color}]{pnl_sign}${pnl:,.2f}[/{pnl_color}]\n"
            f"  ROI         [{roi_color}]{roi_sign}{roi:.2f}%[/{roi_color}]"
        )
        widget.update(lines)

    def _update_trades_display(
        self,
        portfolio: dict | None,
        active_signals: list[dict] | None,
    ) -> None:
        """Update the trades list Static widget."""
        try:
            widget = self.query_one("#trades-list", Static)
        except Exception:
            return

        if portfolio is None and active_signals is None:
            widget.update("[dim]Could not load trades[/dim]")
            return

        trades: list[str] = []

        # Add open positions from portfolio (executed, no exit yet)
        open_positions = []
        if portfolio:
            open_positions = portfolio.get("open_positions", [])
        for pos in open_positions:
            symbol = pos.get("symbol", "???")
            pnl = pos.get("current_unrealized_pnl", 0)
            position = pos.get("position", "BUY")

            arrow = "[green]\u25b2[/green]" if position == "BUY" else "[red]\u25bc[/red]"
            pnl_sign = "+" if pnl >= 0 else ""
            pnl_color = "green" if pnl >= 0 else "red"
            pnl_str = f"[{pnl_color}]{pnl_sign}${pnl:,.2f}[/{pnl_color}]"

            trades.append(f"  {arrow} {symbol:<14}executed   {pnl_str}")

        # Add active signals (pending entry)
        if active_signals:
            for sig in active_signals:
                # Skip if already shown as an open position
                sig_id = sig.get("id")
                if sig_id and any(p.get("id") == sig_id for p in open_positions):
                    continue

                symbol = sig.get("symbol", "???")
                position = sig.get("position", "BUY")
                entry = sig.get("entry_price")
                arrow = "[green]\u25b2[/green]" if position == "BUY" else "[red]\u25bc[/red]"

                if entry:
                    # Entered trade: show unrealized PnL like executed trades
                    pnl = sig.get("current_unrealized_pnl", 0)
                    pnl_sign = "+" if pnl >= 0 else ""
                    pnl_color = "green" if pnl >= 0 else "red"
                    pnl_str = f"[{pnl_color}]{pnl_sign}${pnl:,.2f}[/{pnl_color}]"
                    trades.append(f"  {arrow} {symbol:<14}entered    {pnl_str}")
                else:
                    # Pending entry: show suggestion price
                    suggestion = sig.get("suggestion_price", 0)
                    current = sig.get("current_price", 0)
                    price = suggestion or current
                    price_str = f"[dim]@${price:,.2f}[/dim]" if price else ""
                    trades.append(f"  {arrow} {symbol:<14}active     {price_str}")

        # Limit to 5 trades
        trades = trades[:5]

        if not trades:
            widget.update("[dim]No open trades[/dim]")
        else:
            widget.update("\n".join(trades))

    def _update_watchlist_display(
        self,
        favorites: list[dict] | None,
        stats_map: dict[str, dict],
    ) -> None:
        """Update the watchlist Static widget."""
        try:
            widget = self.query_one("#watchlist", Static)
        except Exception:
            return

        if favorites is None:
            widget.update("[dim]Could not load watchlist[/dim]")
            return

        if not favorites:
            widget.update("[dim]Watchlist has not been configured yet[/dim]")
            return

        lines: list[str] = []
        for t in favorites[:8]:
            symbol = t.get("ticker", "???")
            stats = stats_map.get(symbol)

            if stats:
                price = stats.get("currentPrice", 0)
                change = stats.get("priceChangePercent", 0)
                sign = "+" if change >= 0 else ""
                color = "green" if change >= 0 else "red"
                lines.append(f"  {symbol:<14}${price:,.2f}  [{color}]{sign}{change:.2f}%[/{color}]")
            else:
                lines.append(f"  {symbol:<14}[dim]--[/dim]")

        widget.update("\n".join(lines))
