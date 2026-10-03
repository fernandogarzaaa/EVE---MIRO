Implementation: `src/eve_miro/providers`. Live public HTTP adapters with recorded fixtures. Live mode fail-closes on HTTP/parse/missing-key errors.

## Market data fabric (Phase 1)

Five providers grounding market state as OBSERVED events:

- `markets_bars`: yfinance OHLCV per ticker (daily 3mo plus 1h intraday 5d). Tickers via `MARKETS_TICKERS`, default SPY/QQQ/AAPL/MSFT. Live with `MARKETS_BARS_LIVE=1`.
- `markets_options`: yfinance options chains (nearest 4 expiries). Live chains only; free sources carry no history, so IV history accumulates in the ledger going forward. Live with `MARKETS_OPTIONS_LIVE=1`.
- `macro_fred`: FRED series DGS10, CPIAUCSL, UNRATE, FEDFUNDS. Live needs a free `FRED_API_KEY`; fail-closed without it (`MACRO_FRED_LIVE=1`).
- `market_vol`: VIX daily closes via yfinance. Live with `MARKET_VOL_LIVE=1`.
- `gdelt_markets`: GDELT DOC ArtList with a markets-themed query (companion to the Philippines `gdelt` provider, which is untouched). Live with `GDELT_MARKETS_LIVE=1`.

`core/world/markets.py` folds `market.*` events into `Economy.indicators["market_snapshot"]`: per-ticker price, 1/5/20d returns, multi-window realized vol, IV term-structure summary, latest VIX, macro snapshot, news counts.
