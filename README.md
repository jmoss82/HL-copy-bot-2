# HyperLiquid Copy Trading Bot (Second Target)

Standalone copy bot for a **second target trader**: larger account, **BTC only**, **0.001** fixed ratio, **10x** leverage. Kept in a **separate repo** so you can deploy it as its own Railway service without affecting the first copy bot (HL-copy-bot).

## Target

- **Address:** `0xe3c97b18216f58af4b9c1347d0ee010c42e6a85d`
- **Default config:** `COPY_FIXED_RATIO=0.001`, `COPY_LEVERAGE=10`, `COPY_COINS=BTC`

You can use the **same wallet** as the first bot; this repo only changes target, ratio, leverage, and coin filter.

## How It Works

1. **Poll** the target wallet every 3 seconds via the public `/info` API
2. **Diff** positions to detect opens, closes, increases, decreases, flips
3. **Scale** by `COPY_FIXED_RATIO` (0.001 = 0.1% of their size)
4. **Execute** IOC limit orders on your account (BTC only)

## Files

| File       | Purpose                                              |
|-----------|------------------------------------------------------|
| `bot.py`  | Main entry point, async loop, startup sync, heartbeat |
| `config.py` | Env-based config; defaults for this target          |
| `tracker.py` | Poll target, diff positions, classify changes     |
| `copier.py`  | Execute mirrored trades via HL SDK                 |

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Set `HL_WALLET_ADDRESS`, `HL_PRIVATE_KEY`, and optionally `HL_ACCOUNT_ADDRESS` (if using an agent wallet). The example already has this target and 0.001 ratio.

### 3. Run

```bash
python bot.py
```

Start with `COPY_DRY_RUN=true`, then flip to `false` when ready.

## Deployment (Railway)

Create a **new** Railway service and connect this repo (not HL-copy-bot). Set variables in the service; no `.env` on the server.

**Recommended variables:**

```
HL_WALLET_ADDRESS=0x...
HL_PRIVATE_KEY=0x...
HL_ACCOUNT_ADDRESS=0x...
COPY_TARGET_ADDRESS=0xe3c97b18216f58af4b9c1347d0ee010c42e6a85d
COPY_FIXED_RATIO=0.001
COPY_LEVERAGE=10
COPY_COINS=BTC
COPY_IS_CROSS=false
COPY_DRY_RUN=false
COPY_SYNC_STARTUP=false
```

Use `COPY_SYNC_STARTUP=false` until you’ve manually synced, then set to `true` if you want restarts to stay aligned. Pushes to this repo only redeploy this bot, not the first one.

## Going Live Checklist

1. Set env vars in Railway
2. Run with `COPY_DRY_RUN=true` and confirm trades appear in logs
3. Set `COPY_SYNC_STARTUP=false` and `COPY_DRY_RUN=false`
4. Manually match target’s current BTC position (scaled by 0.001)
5. Optionally set `COPY_SYNC_STARTUP=true` for future restarts
