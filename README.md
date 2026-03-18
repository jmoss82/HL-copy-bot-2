# HyperLiquid Copy Trading Bot

This folder contains one of the three live HyperLiquid copy-trading bots in this repository.

It is a separate bot instance with its own deployment, copied wallet, coin universe, and risk settings. The core engine is the same as the other `copy-bot*` folders, but the runtime configuration is independent.

## Important Context

This README explains how the bot is structured and how it behaves. It is not meant to be a perfect record of the exact wallet address, copied coins, or limits currently running in production.

For this bot, the real source of truth is:

1. the code in this folder
2. the environment variables configured for this deployment

That means this folder represents one live strategy, but its exact target wallet and coin list should be confirmed from Railway variables or a local `.env`, not assumed from documentation text.

## Runtime Flow

1. Poll the target wallet through HyperLiquid's public `/info` API.
2. Keep only the configured `COPY_COINS` for this bot.
3. Compare the latest snapshot to the previous one.
4. Convert the detected target move into the bot's own desired size.
5. Execute the mirrored trade on your account using the HyperLiquid SDK.

The most advanced mode is `lifecycle`, where the bot anchors a copy ratio when the target opens a trade and then mirrors adds, trims, closes, and flips across the rest of that trade lifecycle.

## Key Files

| File | Purpose |
|---|---|
| `bot.py` | Main process, startup sync, polling loop, reconciliation, heartbeat logging |
| `config.py` | Environment-variable loading, defaults, and validation |
| `tracker.py` | Polls the copied wallet and detects position changes |
| `copier.py` | Queries account state, computes sizes, sets leverage, and places orders |
| `.env.example` | Local configuration template |
| `requirements.txt` | Python dependencies |
| `analyze_strategy.py` | Helper script for reviewing trading behavior |
| `check_wallet.py` | Helper script for inspecting wallet state |
| `recent_fills.py` | Helper script for checking recent fills |

## Configuration

In production, Railway variables are the main configuration surface. For local use, create a `.env` from `.env.example`.

The main variables to understand are:

| Variable | Meaning |
|---|---|
| `HL_WALLET_ADDRESS` | Signer wallet address |
| `HL_PRIVATE_KEY` | Private key for signing |
| `HL_ACCOUNT_ADDRESS` | Trading account or agent wallet |
| `COPY_TARGET_ADDRESS` | Wallet being copied |
| `COPY_COINS` | Coins this bot may copy |
| `COPY_SCALING_MODE` | How copied trades are sized |
| `COPY_RECONCILE_MODE` | `state`, `delta`, or `lifecycle` |
| `COPY_SYNC_STARTUP` | Whether to join existing positions on startup |
| `COPY_DRY_RUN` | Simulated vs live execution |

Use `.env.example` as a template, not as guaranteed documentation of the live deployed values.

## Reconcile Modes

- `state`: aim for a desired net position each cycle
- `delta`: trade only the detected net change since the last snapshot
- `lifecycle`: anchor a copy ratio on open, then mirror the full trade lifecycle

## Startup Behavior

If the target is already in a position when the bot starts, the bot can lock that coin and wait for a clean next entry instead of jumping into the middle of a trade.

If `COPY_SYNC_STARTUP=true`, the bot is allowed to sync into already-open target positions immediately. That is mainly useful when recovering after a restart and you intentionally want to rejoin the current trade state.

## Risk Guards

- `COPY_MAX_TRADE_USD` caps a single order's notional
- `COPY_MAX_POSITION_USD` caps total resulting exposure
- `COPY_MIN_TRADE_USD` filters out trades below the exchange minimum
- `COPY_MAX_DAILY_TRADES` limits unexpected bursts of activity

## Running

Local entry point:

```bash
python bot.py
```

Production entry point:

```bash
python bot.py
```
