#!/usr/bin/env python3
"""
HyperLiquid Copy Trading Bot

Monitors a target trader's perp positions in real-time and mirrors
their trades proportionally onto your account.

Usage:
    python bot.py              # uses .env for configuration
    COPY_DRY_RUN=false python bot.py   # live trading (be careful!)
"""
import asyncio
import sys
import signal
import time
from pathlib import Path
from datetime import datetime, timezone

from loguru import logger

from config import load_config, validate_config, CopyBotConfig
from tracker import PositionTracker
from copier import TradeCopier


class CopyBot:
    """
    Main copy-trading controller.

    Lifecycle:
        1. setup()        – initialise SDK, load metadata, set leverage
        2. startup_sync() – optionally match target's current position
        3. run()          – async poll loop (runs until stopped)
    """

    def __init__(self, config: CopyBotConfig):
        self.config = config
        self.tracker = PositionTracker(config.target_address)
        self.copier = TradeCopier(config)

        self.running = False
        self.start_time: float = 0.0
        self.trades_executed: int = 0

    # ── Lifecycle ──────────────────────────────────────────────────

    def setup(self) -> None:
        """Initialise the copier (SDK, leverage, metadata)."""
        logger.info("Initialising copy bot...")
        validate_config(self.config)
        self.copier.setup()

        our_equity = self.copier.get_our_equity(force=True)
        logger.info(f"Your account equity: ${our_equity:,.2f}")

    def startup_sync(self) -> None:
        """
        Synchronise with the target's current positions.

        If sync_on_startup is enabled, we open positions to match theirs
        right now.  Otherwise we just seed the tracker so the first diff
        doesn't treat existing positions as new trades.
        """
        logger.info(f"Polling target wallet: {self.config.target_address}")
        target_positions = self.tracker.poll()

        # Filter to coins we care about
        filtered = self._filter_coins(target_positions)

        if not filtered:
            logger.info("Target has no matching positions — starting clean")
            self.tracker.seed({})
            return

        # Log what the target is holding
        for coin, data in filtered.items():
            size = data["size"]
            side = "LONG" if size > 0 else "SHORT"
            logger.info(
                f"  Target: {side} {abs(size):.6f} {coin} "
                f"(entry ${data['entry_px']:,.1f}, {data['leverage']}x)"
            )

        if self.config.sync_on_startup:
            logger.info("sync_on_startup=True — matching target positions now")

            our_positions = self.copier.get_our_positions()

            for coin, data in filtered.items():
                target_size = data["size"]
                our_size = our_positions.get(coin, 0.0)

                # Build a synthetic PositionChange to use the normal scaling path
                from tracker import PositionChange
                change = PositionChange(
                    coin=coin,
                    old_size=0.0,
                    new_size=target_size,
                    delta=target_size,
                    action="OPEN",
                    target_entry_px=data["entry_px"],
                    target_leverage=data["leverage"],
                    timestamp=time.time(),
                )

                needed = self.copier.scale_delta(change, self.tracker.target_equity)
                already = our_size
                gap = needed - already

                if abs(gap) < 1e-10:
                    logger.info(f"  {coin}: already in sync (size={our_size:.6f})")
                    continue

                logger.info(
                    f"  {coin}: need {needed:+.6f}, have {already:+.6f}, "
                    f"gap {gap:+.6f}"
                )
                result = self.copier.execute(coin, gap, dry_run=self.config.dry_run)
                if result and result.success:
                    self.trades_executed += 1
        else:
            logger.info("sync_on_startup=False — recording target state, waiting for changes")

        # Seed the tracker so the first poll-diff cycle is clean
        self.tracker.seed(target_positions)

    # ── Main loop ──────────────────────────────────────────────────

    async def run(self) -> None:
        """Async polling loop — runs until self.running is set to False."""
        self.running = True
        self.start_time = time.time()

        heartbeat_interval = 60
        last_heartbeat = time.time()

        logger.info(
            f"Entering main loop  |  "
            f"poll={self.config.poll_interval_seconds}s  "
            f"coins={self.config.coins_to_copy}  "
            f"mode={'DRY RUN' if self.config.dry_run else 'LIVE'}"
        )

        while self.running:
            try:
                # ── 1. Poll target ─────────────────────────────────
                target_positions = self.tracker.poll()
                filtered = self._filter_coins(target_positions)

                # ── 2. Diff ────────────────────────────────────────
                changes = self.tracker.diff(filtered, self.config.coins_to_copy)

                # ── 3. React to changes ────────────────────────────
                for change in changes:
                    logger.warning(f"TARGET MOVED: {change}")

                    scaled = self.copier.scale_delta(
                        change, self.tracker.target_equity,
                    )
                    if abs(scaled) < 1e-10:
                        logger.info(f"  Scaled delta is zero — skipping")
                        continue

                    side = "BUY" if scaled > 0 else "SELL"
                    logger.info(
                        f"  Mirroring: {side} {abs(scaled):.6f} {change.coin} "
                        f"(scaling={self.config.scaling_mode})"
                    )

                    result = self.copier.execute(
                        change.coin, scaled, dry_run=self.config.dry_run,
                    )
                    if result and result.success:
                        self.trades_executed += 1

                # ── 4. Heartbeat ───────────────────────────────────
                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    self._heartbeat(filtered)
                    last_heartbeat = now

                # ── 5. Sleep ───────────────────────────────────────
                await asyncio.sleep(self.config.poll_interval_seconds)

            except Exception as e:
                logger.error(f"Main-loop error: {e}")
                logger.exception(e)
                await asyncio.sleep(5)

    def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("Stopping copy bot...")
        self.running = False
        self._print_summary()
        logger.info("Copy bot stopped.")

    # ── Helpers ────────────────────────────────────────────────────

    def _filter_coins(self, positions: dict) -> dict:
        """Keep only the coins we're configured to copy."""
        if "*" in self.config.coins_to_copy:
            return positions
        return {
            k: v for k, v in positions.items()
            if k in self.config.coins_to_copy
        }

    def _heartbeat(self, target_positions: dict) -> None:
        """Periodic status log."""
        runtime = time.time() - self.start_time
        hours = int(runtime // 3600)
        mins = int((runtime % 3600) // 60)

        parts = [
            f"Runtime: {hours}h{mins:02d}m",
            f"Trades: {self.trades_executed}",
        ]

        # Target position summary
        for coin, data in target_positions.items():
            size = data["size"]
            side = "L" if size > 0 else "S"
            parts.append(f"Target {coin}: {side}{abs(size):.4f}")

        # Our position summary
        our = self.copier.get_our_positions()
        for coin in self.config.coins_to_copy:
            if coin == "*":
                continue
            our_size = our.get(coin, 0.0)
            if abs(our_size) > 1e-10:
                side = "L" if our_size > 0 else "S"
                parts.append(f"Ours {coin}: {side}{abs(our_size):.4f}")
            else:
                parts.append(f"Ours {coin}: flat")

        logger.info("HEARTBEAT | " + " | ".join(parts))

    def _print_summary(self) -> None:
        """Print a final status block on shutdown."""
        runtime = time.time() - self.start_time if self.start_time else 0
        hours = int(runtime // 3600)
        mins = int((runtime % 3600) // 60)

        print(f"\n{'=' * 60}")
        print(f"  Copy Bot Summary")
        print(f"{'=' * 60}")
        print(f"  Mode:          {'DRY RUN' if self.config.dry_run else 'LIVE'}")
        print(f"  Target:        {self.config.target_address[:10]}...{self.config.target_address[-6:]}")
        print(f"  Runtime:       {hours}h {mins}m")
        print(f"  Trades:        {self.trades_executed}")
        print(f"  Coins tracked: {', '.join(self.config.coins_to_copy)}")
        print(f"  Scaling:       {self.config.scaling_mode}", end="")
        if self.config.scaling_mode == "fixed_ratio":
            print(f" (ratio={self.config.fixed_ratio})")
        elif self.config.scaling_mode == "fixed_size":
            print(f" (size={self.config.fixed_size})")
        else:
            print()
        print(f"{'=' * 60}\n")


# ── Entry point ────────────────────────────────────────────────────

async def main():
    """Top-level entry: load config, wire up signals, run bot."""

    cfg = load_config()

    # ── Logging ────────────────────────────────────────────────────
    bot_dir = Path(__file__).parent
    log_dir = bot_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "{message}"
        ),
        level=cfg.log_level,
    )
    logger.add(
        str(log_dir / "copy_bot_{time}.log"),
        rotation="1 day",
        retention="14 days",
        level="DEBUG",
    )

    # ── Banner ─────────────────────────────────────────────────────
    mode_label = "DRY RUN" if cfg.dry_run else "LIVE TRADING"
    print(f"""
    ╔══════════════════════════════════════════════════════╗
    ║         HYPERLIQUID COPY TRADING BOT                ║
    ║         Mode: {mode_label: <39}║
    ╚══════════════════════════════════════════════════════╝
    """)

    logger.info(f"Target:    {cfg.target_address}")
    logger.info(f"Coins:     {cfg.coins_to_copy}")
    logger.info(f"Scaling:   {cfg.scaling_mode} (ratio={cfg.fixed_ratio})")
    logger.info(f"Leverage:  {cfg.leverage}x ({'cross' if cfg.is_cross else 'isolated'})")
    logger.info(f"Polling:   every {cfg.poll_interval_seconds}s")
    logger.info(f"Slippage:  {cfg.slippage_bps} bps")
    logger.info(f"Dry run:   {cfg.dry_run}")

    # ── Build bot ──────────────────────────────────────────────────
    bot = CopyBot(cfg)

    # ── Graceful shutdown ──────────────────────────────────────────
    def handle_signal(sig, _frame):
        logger.info(f"Signal {sig} received — shutting down")
        bot.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        bot.setup()
        bot.startup_sync()
        await bot.run()
    except KeyboardInterrupt:
        bot.stop()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        bot.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
