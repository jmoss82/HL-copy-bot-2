#!/usr/bin/env python3
"""Print recent user fills with notional USD."""
import requests
import sys

user = sys.argv[1] if len(sys.argv) > 1 else "0xc1f8aa0d8832aaf9986673c2099d8fa0fab618db"
r = requests.post(
    "https://api.hyperliquid.xyz/info",
    json={"type": "userFills", "user": user},
    timeout=15,
)
fills = r.json()

print("Recent fills (newest first) with notional = sz * px:")
print("-" * 75)
for f in fills[:50]:
    sz = float(f.get("sz", 0))
    px = float(f.get("px", 0))
    ntl = sz * px
    side = "SELL" if f.get("side") == "A" else "BUY"
    print(f"  {f.get('coin', ''):14} {side:4}  sz={sz:>10.5f}  px={px:>10.2f}  notional=${ntl:>8.2f}  time={f.get('time')}")
print(f"\n(API returned {len(fills)} total fills)")
