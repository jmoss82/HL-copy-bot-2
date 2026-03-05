# HyperLiquid Copy Trading Bot

Monitors a target trader's perp positions on HyperLiquid in real-time and mirrors their trades onto your account.

## How It Works

1. **Poll** the target wallet every 3 seconds via the public `/info` API (no auth needed)
2. **Compute desired position** for your account based on configured sizing
3. **Reconcile gap** between desired and your actual position each poll
4. **Execute** an IOC limit order through the spread on your account (prices rounded to HL's 5 significant figure rule)

## Files

| File | Purpose |
|---|---|
| `bot.py` | Main entry point, async loop, startup sync, heartbeat logging |
| `config.py` | All settings loaded from environment variables with defaults |
| `tracker.py` | Polls target wallet, diffs positions, classifies changes |
| `copier.py` | Executes mirrored trades on your account via the HL SDK |

## Deployment (Railway)

Railway is the source of truth for all configuration. Set environment variables in the service's Variables tab — no `.env` file needed. Entry point is `python bot.py`.

**Every push to the repo triggers a redeploy on Railway, which restarts the bot.**

On restart, the bot checks what the target currently has open. Any coins the target is already in are locked — the bot waits for them to close before following the next entry. `COPY_SYNC_STARTUP=true` overrides this and immediately enters to match the target (useful if the server crashed mid-position and you need to re-sync).

## Environment Variables

**Required:**

| Variable | Description |
|---|---|
| `HL_WALLET_ADDRESS` | Your signer wallet address |
| `HL_PRIVATE_KEY` | Your private key |
| `HL_ACCOUNT_ADDRESS` | Your trading account (agent wallet) |
| `COPY_TARGET_ADDRESS` | Wallet address of the trader to copy |

**Current config:**

| Variable | Value | Description |
|---|---|---|
| `COPY_SCALING_MODE` | `fixed_notional` | Trade a fixed USD amount per signal |
| `COPY_FIXED_NOTIONAL_USD` | `20` | USD notional per trade |
| `COPY_MAX_TRADE_USD` | `40` | Per-trade notional cap |
| `COPY_LEVERAGE` | `5` | Leverage applied to your positions |
| `COPY_IS_CROSS` | `false` | Isolated margin |
| `COPY_COINS` | `APT,MON,BERA,ZRO,GRASS,VVV` | Coins to copy |
| `COPY_SYNC_STARTUP` | `false` | Wait for next entry rather than entering existing positions |
| `COPY_MIN_TRADE_USD` | `11` | Skip trades below this notional (HL minimum ~$10) |
| `COPY_RECONCILE_MODE` | `state` | Each poll reconciles desired vs actual position |
| `COPY_DRY_RUN` | `false` | Live trading |

**Other available variables (using defaults):**

| Variable | Default | Description |
|---|---|---|
| `COPY_POLL_INTERVAL` | `3.0` | Seconds between target polls |
| `COPY_SLIPPAGE_BPS` | `10.0` | Max slippage for IOC orders (basis points) |
| `COPY_MAX_POSITION_USD` | `5000` | Hard cap on resulting position exposure |
| `COPY_MAX_DAILY_TRADES` | `200` | Kill switch if something goes wrong |
| `COPY_LOG_LEVEL` | `INFO` | `DEBUG` for verbose output |

## Startup Behaviour

By default (`COPY_SYNC_STARTUP=false`), the bot locks any coins the target already has open at startup and waits for them to close before following the next entry. This avoids entering mid-position at an unfavourable price.

Set `COPY_SYNC_STARTUP=true` only when recovering from a crash where the bot was already in a position and needs to re-sync immediately.

## Risk Guards

- `COPY_MAX_TRADE_USD` caps a single order's notional.
- `COPY_MAX_POSITION_USD` caps resulting position exposure after each trade.
- `COPY_MIN_TRADE_USD` filters out orders below the exchange minimum.
- `COPY_MAX_DAILY_TRADES` halts trading if the daily limit is hit.

## Local Development

If running locally, create a `.env` file based on `.env.example`. Railway variables take precedence in production and no `.env` file is needed there.
