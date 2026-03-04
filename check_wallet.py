#!/usr/bin/env python3
"""One-off script to inspect a HyperLiquid wallet's state and recent activity."""
import requests
import json
import sys

INFO_URL = "https://api.hyperliquid.xyz/info"

def main():
    user = sys.argv[1] if len(sys.argv) > 1 else "0xd79339863b22d5c81b40e65dd9cb63d311e57bc9"

    # Clearinghouse state (perp positions + margin)
    r = requests.post(INFO_URL, json={"type": "clearinghouseState", "user": user}, timeout=10)
    r.raise_for_status()
    state = r.json()

    print("=== CLEARINGHOUSE STATE (perp account) ===")
    m = state.get("marginSummary", {})
    print(f"  Account value:    {m.get('accountValue')}")
    print(f"  Total margin:    {m.get('totalMarginUsed')}")
    print(f"  Withdrawable:    {state.get('withdrawable')}")
    print()
    print("  Open positions:")
    for e in state.get("assetPositions", []):
        p = e.get("position", {})
        szi = float(p.get("szi", 0))
        if abs(szi) < 1e-10:
            continue
        side = "LONG" if szi > 0 else "SHORT"
        print(f"    {p.get('coin')}: {side} {abs(szi)}  entry={p.get('entryPx')}  lev={p.get('leverage')}")
    if not state.get("assetPositions"):
        print("    (none)")
    print()

    # Recent fills
    r2 = requests.post(INFO_URL, json={"type": "userFills", "user": user}, timeout=10)
    r2.raise_for_status()
    fills = r2.json()
    print("=== RECENT FILLS (last 25) ===")
    if not fills:
        print("  No fills.")
    else:
        for f in fills[:25]:
            print(f"  {f.get('coin')} {f.get('side')} sz={f.get('sz')} px={f.get('px')}  time={f.get('time')}")
        print(f"  (total returned: {len(fills)})")
    print()

    # Spot balances (if API supports)
    r3 = requests.post(INFO_URL, json={"type": "spotClearinghouseState", "user": user}, timeout=10)
    if r3.status_code == 200:
        spot = r3.json()
        print("=== SPOT CLEARINGHOUSE (if any) ===")
        print(json.dumps(spot, indent=2)[:500])

if __name__ == "__main__":
    main()
