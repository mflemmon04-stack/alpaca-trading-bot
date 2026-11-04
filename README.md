# Alpaca competition bot — experimental paper-only starter

**Not deployed, backtested, or proven profitable.** This bot trades **US stocks/ETFs only**, and does **not** manage the existing option orders/positions in your account. It must not be used with live brokerage credentials.

## Strategy

Every 3 minutes, during regular US market hours, rank a configured watchlist using 5-minute EMA trend (9/26), 20-bar breakout, six-bar momentum and relative volume. Buy up to two qualifying tickers per cycle, with maximum 12% of equity per position and 60% aggregate stock exposure. Sell when unrealized P&L reaches -5.5% or +12%. Pause and attempt to liquidate stocks after a 15% peak-to-current-equity drawdown. On Nov 18, 2026 it cancels open stock orders and attempts to close all stock positions; **the current implementation stops stock entries all day on Nov 18**. Options must be separately closed manually before the competition deadline. This is a prototype, not an optimized strategy.

## Deploy to Railway

1. Create a **private GitHub repository** containing these files; never commit `.env` or API keys.
2. Create a Railway project, choose **Deploy from GitHub repo**, and select that private repository.
3. Add environment variables from `.env.example` under Railway Variables. Use **paper** Alpaca API credentials, obtained from Alpaca paper trading. Keep `DRY_RUN=true` initially.
4. Railway builds the `Dockerfile`. Inspect deployment logs for market data access, rate limits, signals and errors.
5. After testing, explicitly set `DRY_RUN=false` to permit autonomous **paper** stock orders. There is no in-chat approval step once enabled.
6. Configure Railway to keep one worker instance only; two instances could duplicate orders. A paid/always-on plan may be required.

## Critical limitations before enabling

- The bot has **not** been backtested or tested against a live Alpaca paper connection here.
- It cannot trade options. Existing options, including short-dated contracts, require separate supervision and manual closing.
- It does not persist a dedicated bot-ownership registry; it can close stock positions in the account during drawdown/deadline events, including pre-existing positions. **Use a separate paper account if you need isolation.**
- A restart loses the high-water mark because Railway's local `/tmp` storage is ephemeral. Use persistent storage/database for reliable drawdown tracking.
- Stop/take-profit exits are **software-triggered**, not exchange-native protective orders. Outages, overnight gaps, thin liquidity, slippage and market closures can cause materially worse fills.
- Relative volume is not normalized for time of day; the data feed uses IEX, which may differ from consolidated volume.
- Market order entries may fill at worse prices. No transaction-cost/slippage simulation or rigorous backtest is included.
- No dynamic optimization or AI model is present; signals use fixed, configurable parameters.
- The Nov 18 close logic only affects stocks and does not automatically exit options; verify all holdings and close manually before 4 PM ET.
- Trading high-risk instruments can rapidly lose the entire paper account. A 10x target in two weeks is extremely unlikely.

## Next steps before using autonomous execution

Run a historical walk-forward backtest including spreads, fees, slippage and survivorship bias; use a separate paper account; add persistent state, an order reconciliation/idempotency layer, broker-native protective orders, options execution/expiration safeguards, and reliable alerts.
