# HyperLiquid Copy Trading Bot

Monitors a target trader's perp positions on HyperLiquid in real-time and mirrors their trades onto your account.

## How It Works

1. **Poll** the target wallet every 3 seconds via the public `/info` API (no auth needed)
2. **Compute desired position** for your account based on configured sizing
3. **Reconcile gap** between desired and your actual position each poll (state mode)
4. **Execute** an IOC limit order through the spread on your account (prices rounded to HL's 5 significant figure rule)

## Files

| File | Purpose |
|---|---|
| `bot.py` | Main entry point, async loop, startup sync, heartbeat logging |
| `config.py` | All settings loaded from environment variables with defaults |
| `tracker.py` | Polls target wallet, diffs positions, classifies changes |
| `copier.py` | Executes mirrored trades on your account via the HL SDK |

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy the template and fill in your credentials:

```bash
cp .env.example .env
```

**Required variables:**

| Variable | Description |
|---|---|
| `HL_WALLET_ADDRESS` | Your signer wallet address |
| `HL_PRIVATE_KEY` | Your private key |
| `HL_ACCOUNT_ADDRESS` | Your trading account (if using agent wallet) |
| `COPY_TARGET_ADDRESS` | Wallet address of the trader to copy |
| `COPY_SCALING_MODE` | One of `fixed_ratio`, `proportional`, `fixed_size`, `fixed_notional` |

**Optional overrides (sensible defaults built in):**

| Variable | Default | Description |
|---|---|---|
| `COPY_SCALING_MODE` | `fixed_ratio` | `fixed_ratio`, `proportional`, `fixed_size`, or `fixed_notional` |
| `COPY_FIXED_RATIO` | `1.0` | Used by `fixed_ratio` (0.1 = 10% of target deltas) |
| `COPY_FIXED_SIZE` | `0.001` | Used by `fixed_size` (coin units per signal) |
| `COPY_FIXED_NOTIONAL_USD` | `25.0` | Used by `fixed_notional` (USD per signal) |
| `COPY_MAX_TRADE_USD` | `0` | Optional per-trade notional cap (`0` disables) |
| `COPY_LEVERAGE` | `40` | Your leverage |
| `COPY_IS_CROSS` | `false` | `true` for cross margin, `false` for isolated |
| `COPY_POLL_INTERVAL` | `3.0` | Seconds between target polls |
| `COPY_RECONCILE_MODE` | `state` | `state` (recommended) or `delta` |
| `COPY_SLIPPAGE_BPS` | `10.0` | Max slippage for IOC orders (basis points) |
| `COPY_MIN_TRADE_USD` | `11.0` | Skip trades below this notional |
| `COPY_MAX_POSITION_USD` | `5000` | Hard cap on resulting position exposure |
| `COPY_COINS` | `BTC` | Comma-separated coins to copy |
| `COPY_SYNC_STARTUP` | `true` | Match target position on startup |
| `COPY_MAX_DAILY_TRADES` | `200` | Kill switch if something goes wrong |
| `COPY_DRY_RUN` | `true` | No real orders until set to `false` |
| `COPY_LOG_LEVEL` | `INFO` | `DEBUG` for verbose output |

### 3. Run

```bash
python bot.py
```

Start with `COPY_DRY_RUN=true` to watch it detect trades without placing orders. Check the logs, then flip to `false` when ready.

## Deployment (Railway)

The bot is designed to run as a standalone Railway service. Set environment variables in the service's Variables tab - no `.env` file needed on the server. Entry point is `python bot.py`.

**Important:** Every push to the repo triggers a redeploy on Railway, which restarts the bot. Before pushing:

1. Set `COPY_SYNC_STARTUP=false` in Railway if you don't want it to immediately open a position on restart
2. Or ensure you're already in sync so `COPY_SYNC_STARTUP=true` cleanly matches the target

**Recommended Railway variables (everything else uses code defaults):**

```
HL_WALLET_ADDRESS=0x...
HL_PRIVATE_KEY=0x...
HL_ACCOUNT_ADDRESS=0x...
COPY_TARGET_ADDRESS=0x...
COPY_FIXED_RATIO=0.1
COPY_LEVERAGE=40
COPY_IS_CROSS=false
COPY_DRY_RUN=false
COPY_SYNC_STARTUP=true
```

## Scaling Modes

- **`fixed_ratio`** - Multiply target's trade size by `COPY_FIXED_RATIO`. A ratio of `0.1` means you trade 10% of their size.
- **`proportional`** - Automatically scales based on `(your equity / their equity)`. Adjusts as account values change.
- **`fixed_size`** - Always trade `COPY_FIXED_SIZE` per signal regardless of target's size. Direction is matched.
- **`fixed_notional`** - Always trade `COPY_FIXED_NOTIONAL_USD` per signal (converted to coin size at current mid price).

## Risk Guards

- `COPY_MAX_TRADE_USD` caps a single mirrored order's notional (optional).
- `COPY_MAX_POSITION_USD` caps resulting position exposure after each trade.
- `COPY_MIN_TRADE_USD` filters out tiny orders below exchange minimum notional.

## Reconciliation Modes

- `state` (recommended): each poll computes desired position and trades `desired - current`.
- `delta`: legacy mode, mirrors only detected position deltas between polls.

## Going Live Checklist

1. Set all env vars in Railway
2. Start with `COPY_DRY_RUN=true` - verify the bot detects trades in the logs
3. Set `COPY_SYNC_STARTUP=false` and `COPY_DRY_RUN=false`
4. Manually buy/sell to match the target's current position (scaled by your ratio)
5. Once in sync, flip `COPY_SYNC_STARTUP=true` so future restarts stay aligned
