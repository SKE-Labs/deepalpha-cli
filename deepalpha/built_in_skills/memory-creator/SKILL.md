---
name: memory-creator
description: "Guide for creating and managing trading memories that persist across sessions.
  Use when the user wants to: (1) save their trading style or preferences, (2) record risk
  management rules, (3) store preferred indicators or timeframes, (4) remember market-specific
  strategies, (5) capture position sizing rules, (6) update existing trading preferences, or
  (7) review what the system knows about them. Trigger on phrases like 'remember my style',
  'save my preferences', 'I always use...', 'my risk tolerance is...', 'update my trading rules',
  'what do you know about my trading'."
---

# Memory Creator

Create and manage trading memories that persist across all future sessions.

## Suggested Categories

| Category | Example Name | Example Content |
|----------|-------------|-----------------|
| Trading Style | Trading Style | Swing trader, primarily 4H timeframe. Focus on crypto majors (BTC, ETH, SOL). Prefer trend-following with pullback entries. |
| Risk Management | Risk Management | Max 2% risk per trade. Never risk more than 5% total portfolio. Always use stop losses. Scale out at TP1/TP2. |
| Preferred Indicators | Preferred Indicators | Primary: EMA 21/55/200, RSI 14, MACD. Secondary: Volume profile, Bollinger Bands. Confirm entries with RSI divergence. |
| Position Sizing | Position Sizing | Base position: 2% of account. High conviction (>80 confidence): up to 3%. Max leverage: 5x for crypto, 2x for stocks. |
| Market Preferences | Market Preferences | Trade BTC/USDT and ETH/USDT on Binance. Watch SOL and AVAX for setups. Avoid low-cap altcoins. Prefer 4H and 1D timeframes. |
| Analysis Framework | Analysis Framework | Top-down: start with 1D for trend, 4H for setup, 1H for entry. Require min 2 timeframe confluence. Weight technical 70%, fundamental 30%. |

## Workflow

1. **List existing**: Call `list_memories` to see current memories
2. **Identify category**: Match the user's request to a suggested category, or create a custom one
3. **Create or update**: Use `create_memory` for new, `update_memory` if one exists for that topic
4. **Confirm**: Summarize what was saved and how it will be used

## Content Guidelines

- Write in the user's own words — preserve their terminology and style
- Keep content concise and actionable (rules, not essays)
- One memory per logical category (don't mix risk rules with indicator preferences)
- Use specific numbers and thresholds, not vague descriptions
- Categories are suggestions — create any name/content that fits the user's needs

## Constraints

- Max 20 memories per user
- Max 50KB content per memory
- Max 100 characters for name
- Names must be unique per user
