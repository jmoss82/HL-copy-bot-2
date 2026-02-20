"""
Trade Copier

Executes mirrored trades on your HyperLiquid account using the official SDK.
Handles position sizing, leverage, price slippage, and safety guards.

This module targets STANDARD HyperLiquid perps (BTC, ETH, etc.),
not XYZ HIP-3 pairs.
"""
import time
from typing import Dict, Optional
from collections import deque
from dataclasses import dataclass
from loguru import logger

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from config import CopyBotConfig
from tracker import PositionChange


@dataclass
class TradeResult:
    """Outcome of a single copy-trade execution."""
    success: bool
    coin: str
    side: str           # "BUY" or "SELL"
    requested_size: float
    filled_size: float = 0.0
    avg_price: float = 0.0
    order_id: Optional[int] = None
    error: str = ""


class TradeCopier:
    """
    Mirrors detected position changes onto your HyperLiquid account.

    Uses the standard HyperLiquid SDK (Exchange / Info) for order placement
    and account queries.  All orders are IOC (immediate-or-cancel) limits
    priced aggressively through the spread so they behave like market orders.
    """

    def __init__(self, config: CopyBotConfig):
        self.config = config

        # SDK clients — initialised in setup()
        self._account: Optional[Account] = None
        self.info: Optional[Info] = None
        self.exchange: Optional[Exchange] = None

        # Resolved address used for info queries
        self.query_address: str = ""

        # Metadata cache
        self._sz_decimals: Dict[str, int] = {}

        # Rate-limiting / daily trade counter
        self._trade_timestamps: deque = deque(maxlen=config.max_daily_trades)

        # Cached equity (refreshed periodically, not every cycle)
        self._our_equity: float = 0.0
        self._equity_ts: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────

    def setup(self) -> None:
        """Initialise SDK clients, load metadata, set leverage."""
        self._account = Account.from_key(self.config.private_key)

        if self._account.address.lower() != self.config.wallet_address.lower():
            raise ValueError(
                f"Private key does not match wallet address. "
                f"Expected {self.config.wallet_address}, got {self._account.address}"
            )

        base_url = constants.MAINNET_API_URL
        self.info = Info(base_url, skip_ws=True)

        # Agent-wallet: if account_address differs from the signer, pass it
        acct = self.config.account_address
        if acct and acct.lower() != self._account.address.lower():
            self.exchange = Exchange(self._account, base_url, account_address=acct)
            self.query_address = acct
        else:
            self.exchange = Exchange(self._account, base_url)
            self.query_address = self._account.address

        logger.info(f"SDK initialised  | signer={self._account.address}")
        logger.info(f"Trading account  | address={self.query_address}")

        # Load universe metadata (size decimals and tick sizes per coin)
        meta = self.info.meta()
        for asset in meta.get("universe", []):
            name = asset["name"]
            self._sz_decimals[name] = asset.get("szDecimals", 5)

        logger.info(f"Loaded metadata for {len(self._sz_decimals)} perps")

        # Set leverage for each coin we plan to copy
        for coin in self.config.coins_to_copy:
            if coin == "*":
                continue
            self._set_leverage(coin)

    # ── Account queries ────────────────────────────────────────────

    def get_our_equity(self, force: bool = False) -> float:
        """Account equity, cached for 60 s unless *force*."""
        if not force and (time.time() - self._equity_ts) < 60:
            return self._our_equity
        try:
            state = self.info.user_state(self.query_address)
            self._our_equity = float(
                state.get("marginSummary", {}).get("accountValue", 0)
            )
            self._equity_ts = time.time()
        except Exception as e:
            logger.error(f"Failed to fetch our equity: {e}")
        return self._our_equity

    def get_our_positions(self) -> Dict[str, float]:
        """Return our current positions as {coin: signed_size}."""
        try:
            state = self.info.user_state(self.query_address)
            positions: Dict[str, float] = {}
            for entry in state.get("assetPositions", []):
                pos = entry.get("position", {})
                coin = pos.get("coin", "")
                size = float(pos.get("szi", 0))
                if abs(size) > 1e-10:
                    positions[coin] = size
            return positions
        except Exception as e:
            logger.error(f"Failed to fetch our positions: {e}")
            return {}

    def get_mid_price(self, coin: str) -> float:
        """Current mid-market price for *coin*."""
        try:
            mids = self.info.all_mids()
            return float(mids.get(coin, 0))
        except Exception as e:
            logger.error(f"Failed to get mid price for {coin}: {e}")
            return 0.0

    # ── Scaling ────────────────────────────────────────────────────

    def scale_delta(
        self,
        change: PositionChange,
        target_equity: float,
    ) -> float:
        """
        Convert the target's raw delta into the size we should trade.

        Returns a signed float (positive = buy, negative = sell).
        """
        raw = change.delta

        if self.config.scaling_mode == "proportional":
            our_eq = self.get_our_equity()
            ratio = (our_eq / target_equity) if target_equity > 0 else 0
            scaled = raw * ratio
        elif self.config.scaling_mode == "fixed_ratio":
            scaled = raw * self.config.fixed_ratio
        elif self.config.scaling_mode == "fixed_size":
            scaled = self.config.fixed_size * (1.0 if raw > 0 else -1.0)
        else:
            logger.error(f"Unknown scaling mode: {self.config.scaling_mode}")
            return 0.0

        # Apply max-position guard
        mid = self.get_mid_price(change.coin)
        if mid > 0 and abs(scaled) * mid > self.config.max_position_usd:
            capped = self.config.max_position_usd / mid
            logger.warning(
                f"Position cap hit: {abs(scaled):.6f} {change.coin} "
                f"(${abs(scaled) * mid:,.0f}) capped to {capped:.6f} "
                f"(${self.config.max_position_usd:,.0f})"
            )
            scaled = capped * (1.0 if scaled > 0 else -1.0)

        return scaled

    # ── Execution ──────────────────────────────────────────────────

    def execute(
        self,
        coin: str,
        size_delta: float,
        dry_run: bool = True,
    ) -> Optional[TradeResult]:
        """
        Place an IOC limit order to mirror a position change.

        Args:
            coin:       e.g. "BTC"
            size_delta: signed size to trade (positive = buy, negative = sell)
            dry_run:    if True, log but don't send the order

        Returns:
            TradeResult, or None if the trade was filtered out.
        """
        if abs(size_delta) < 1e-10:
            return None

        is_buy = size_delta > 0
        abs_size = abs(size_delta)
        side = "BUY" if is_buy else "SELL"

        # ── Round to valid size increment ──────────────────────────
        decimals = self._sz_decimals.get(coin, 5)
        abs_size = round(abs_size, decimals)
        if abs_size == 0:
            logger.debug(f"Size rounded to zero for {coin}, skipping")
            return None

        # ── Min trade size check ───────────────────────────────────
        mid = self.get_mid_price(coin)
        if mid <= 0:
            logger.error(f"No price data for {coin}, cannot execute")
            return TradeResult(False, coin, side, abs_size, error="no price data")
        notional = abs_size * mid
        if notional < self.config.min_trade_size_usd:
            logger.debug(
                f"Trade too small: {abs_size} {coin} = ${notional:.2f} "
                f"(min ${self.config.min_trade_size_usd})"
            )
            return None

        # ── Daily trade limit ──────────────────────────────────────
        now = time.time()
        day_ago = now - 86400
        while self._trade_timestamps and self._trade_timestamps[0] < day_ago:
            self._trade_timestamps.popleft()
        if len(self._trade_timestamps) >= self.config.max_daily_trades:
            logger.critical("Daily trade limit reached — refusing to execute")
            return TradeResult(False, coin, side, abs_size, error="daily limit")

        # ── Calculate aggressive IOC price ─────────────────────────
        slip = self.config.slippage_bps / 10_000
        raw_px = mid * (1 + slip) if is_buy else mid * (1 - slip)
        tick = self._tick_for_price(raw_px)
        limit_px = round(raw_px / tick) * tick

        # ── Dry-run shortcut ───────────────────────────────────────
        if dry_run:
            logger.info(
                f"[DRY RUN] {side} {abs_size} {coin} @ ~${limit_px:,.1f} "
                f"(mid=${mid:,.1f}, notional=${notional:,.0f})"
            )
            return TradeResult(True, coin, side, abs_size, abs_size, mid)

        # ── Live execution ─────────────────────────────────────────
        logger.warning(
            f"EXECUTING: {side} {abs_size} {coin} @ ${limit_px:,.1f} "
            f"(mid=${mid:,.1f}, slippage={self.config.slippage_bps}bps)"
        )

        try:
            result = self.exchange.order(
                coin, is_buy, abs_size, limit_px,
                {"limit": {"tif": "Ioc"}},
                reduce_only=False,
            )

            self._trade_timestamps.append(now)

            # Parse SDK response
            if result and result.get("status") == "ok":
                statuses = (
                    result.get("response", {})
                    .get("data", {})
                    .get("statuses", [])
                )
                if statuses:
                    st = statuses[0]
                    if "filled" in st:
                        fill = st["filled"]
                        avg = float(fill.get("avgPx", 0))
                        tsz = float(fill.get("totalSz", 0))
                        oid = fill.get("oid", 0)
                        logger.success(
                            f"FILLED: {side} {tsz} {coin} @ ${avg:,.1f} "
                            f"(oid={oid})"
                        )
                        return TradeResult(True, coin, side, abs_size, tsz, avg, oid)

                    if "resting" in st:
                        oid = st["resting"].get("oid", 0)
                        logger.warning(
                            f"Order resting (unexpected for IOC): oid={oid}"
                        )
                        return TradeResult(True, coin, side, abs_size, 0, 0, oid)

                    if "error" in st:
                        err = st["error"]
                        logger.error(f"Order rejected: {err}")
                        return TradeResult(False, coin, side, abs_size, error=err)

            logger.error(f"Unexpected order response: {result}")
            return TradeResult(False, coin, side, abs_size, error=str(result))

        except Exception as e:
            logger.error(f"Execution exception: {e}")
            return TradeResult(False, coin, side, abs_size, error=str(e))

    # ── Internal helpers ───────────────────────────────────────────

    @staticmethod
    def _tick_for_price(price: float) -> float:
        """
        HyperLiquid prices use 5 significant figures.
        Tick size = 10^(magnitude - 4) where magnitude = floor(log10(price)).
        E.g. BTC ~$66,000 → tick=$1, ETH ~$2,000 → tick=$0.1
        """
        import math
        if price <= 0:
            return 0.01
        magnitude = math.floor(math.log10(price))
        return 10 ** (magnitude - 4)

    def _set_leverage(self, coin: str) -> None:
        """Set leverage for a coin. Failures are non-fatal."""
        try:
            self.exchange.update_leverage(
                self.config.leverage, coin, is_cross=self.config.is_cross,
            )
            mode = "cross" if self.config.is_cross else "isolated"
            logger.info(f"Leverage set: {coin} {self.config.leverage}x ({mode})")
        except Exception as e:
            logger.warning(f"Could not set leverage for {coin}: {e} (may already be set)")
