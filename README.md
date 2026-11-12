# BTC SignalLab — Sniper-style paper-trading research bot

**Not Kalshi Sniper.** The vendor's proprietary signals cannot be recovered from marketing pages. This is an independently developed 10-signal approximation. **Paper-only: no Kalshi key, wallet, or order submission.** Its claimed edge is an uncalibrated heuristic and must be validated before any real-money use.

## Install (GitHub + Streamlit, or PC/VPS)

1. Extract this ZIP; upload `app.py`, `engine.py`, `worker.py`, `requirements.txt`, and `settings.json` into the **same GitHub repository root**. Do not upload the ZIP itself as an app file.
2. Streamlit Community Cloud: deploy repository, point main entry to `app.py`. This hosts the **dashboard only**; it will NOT automatically run an always-on worker or share local SQLite with a separate host. Streamlit sleeping or filesystem resets may lose paper data.
3. For a real working persistent bot, run both worker and dashboard **on the same always-on host with shared files**, such as a VPS:

```bash
python -m pip install -r requirements.txt
python worker.py
# In a second terminal in same folder:
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

4. Open the server's Streamlit page on your iPhone. Protect the service with authenticated HTTPS, not an open public port.
5. Worker writes `worker_status.json` and `sniper_paper.db` in current working directory. Back up the SQLite DB regularly.

## Signal approximation
1. Target/strike distance normalized by recent BTC volatility.
2. 3-minute momentum.
3. 10-minute momentum.
4. Momentum acceleration.
5. Fast vs slow EMA.
6. 1-minute candle body direction.
7. Volume-confirmed move.
8. Kalshi YES vs NO book-depth imbalance.
9. Binance USD-M futures mark/index basis (unavailable in some regions).
10. Binance futures open-interest change (requires two successful snapshots).

The engine uses Kalshi KXBTC15M official `floor_strike`, bid-based implied asks, Coinbase BTC-USD one-minute candles and optional Binance futures. Kalshi's actual settlement index is CF Benchmarks BRTI, not Coinbase; small differences are meaningful. No unsupported futures metrics are silently substituted. Inputs can be delayed, blocked, missing, or inaccurate.

## Safety and limitations
- Position sizes limited by per-trade dollars, daily loss, trade caps, exposure, and capital assumption.
- Strategy checks edge against a **heuristic** model probability. It has **not** been calibrated or backtested, and cannot be claimed profitable.
- Fees are approximated as ceiling($0.07 × contracts × price × (1-price), to the nearest cent). Check current Kalshi fee schedule. Fill slippage is simulated and queue / market depth are not simulated.
- Paper profit/loss on closing uses actual displayed bid minus estimated slippage, but does not prove those fills were executable. Settled trades use official Kalshi market results when available.
- Exits may be missed during network failures or sleeping workers. No live execution, no private keys, no guarantee.
- If Kalshi or Coinbase changes API formats, worker will explicitly raise an error rather than fabricate data.
- `worker_status.json` is the worker→dashboard transport, and both processes **must share a filesystem**. Streamlit Community Cloud alone is insufficient for persistent autonomous operation.

## Research sources
- https://www.kalshi-sniper.com/faq
- https://www.kalshi-sniper.com/blog/kalshi-trading-bots-a-complete-guide
- https://docs.kalshi.com/
- https://huggingface.co/datasets/DegenHedge/kalshi-btc-15m
