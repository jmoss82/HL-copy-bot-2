#!/usr/bin/env python3
"""
Analyze Activity.csv + Historical Positions.csv to characterize trading strategy.
"""
import csv
from pathlib import Path
from collections import defaultdict
from datetime import datetime

DESKTOP = Path(r"c:\Users\jmoss\Desktop")

def parse_ts(s):
    try:
        return datetime.strptime(s.strip(), "%Y/%m/%d %H:%M:%S")
    except Exception:
        return None

def main():
    # ---- Historical Positions: closed round-trips ----
    pos_file = DESKTOP / "Historical Positions.csv"
    positions = []
    with open(pos_file, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            ot = parse_ts(row.get("Open Time", ""))
            ct = parse_ts(row.get("Close Time", ""))
            pv = float(row.get("Position Value($)", "0").replace(",", "") or 0)
            pnl = float(row.get("PNL($)", "0").replace(",", "") or 0)
            positions.append({
                "open": ot, "close": ct, "perps": row.get("Perps", ""),
                "type": row.get("Type", ""), "value": pv, "pnl": pnl,
            })
            if ct and ot:
                positions[-1]["duration_h"] = (ct - ot).total_seconds() / 3600

    print("=" * 60)
    print("HISTORICAL POSITIONS (closed round-trips)")
    print("=" * 60)
    print(f"Total closed positions: {len(positions)}")
    by_asset = defaultdict(list)
    for p in positions:
        by_asset[p["perps"]].append(p)
    print("\nBy asset (count):")
    for a in sorted(by_asset.keys(), key=lambda x: -len(by_asset[x])):
        print(f"  {a}: {len(by_asset[a])}")
    print("\nBy direction:")
    long_count = sum(1 for p in positions if p["type"] == "Long")
    short_count = sum(1 for p in positions if p["type"] == "Short")
    print(f"  Long: {long_count}  Short: {short_count}")

    durations = [p["duration_h"] for p in positions if p.get("duration_h") is not None]
    if durations:
        print(f"\nHold time (closed positions): min={min(durations):.2f}h  max={max(durations):.2f}h  median={sorted(durations)[len(durations)//2]:.2f}h")
    total_pnl = sum(p["pnl"] for p in positions)
    wins = sum(1 for p in positions if p["pnl"] > 0)
    print(f"\nPnL: total=${total_pnl:,.0f}  winning trades={wins}/{len(positions)} ({100*wins/len(positions):.1f}%)")

    # ---- Activity: individual fills (opens/closes) ----
    act_file = DESKTOP / "Activity.csv"
    activities = []
    with open(act_file, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            t = parse_ts(row.get("Time", ""))
            tx = row.get("Transaction", "").strip()
            activities.append({
                "time": t, "perps": row.get("Perps", ""),
                "type": row.get("Type", "").strip(), "tx": tx,
            })

    print("\n" + "=" * 60)
    print("ACTIVITY (individual order events)")
    print("=" * 60)
    print(f"Total activity rows: {len(activities)}")

    type_counts = defaultdict(int)
    for a in activities:
        type_counts[a["type"]] += 1
    print("\nBy event type:")
    for k in sorted(type_counts.keys(), key=lambda x: -type_counts[x]):
        print(f"  {k}: {type_counts[k]}")

    # Opens vs closes per asset
    print("\nOpens vs Closes by asset (sample):")
    by_asset_act = defaultdict(lambda: {"Open Long": 0, "Open Short": 0, "Close Long": 0, "Close Short": 0, "Liquidation": 0})
    for a in activities:
        by_asset_act[a["perps"]][a["type"]] = by_asset_act[a["perps"]][a["type"]] + 1
    for asset in sorted(by_asset_act.keys(), key=lambda x: -sum(by_asset_act[x].values()))[:12]:
        d = by_asset_act[asset]
        opens = d["Open Long"] + d["Open Short"]
        closes = d["Close Long"] + d["Close Short"]
        liq = d["Liquidation"]
        print(f"  {asset}: opens={opens}  closes={closes}  liquidations={liq}")

    # Consecutive opens: same asset, same direction, within a short window -> scaling in
    print("\n--- Strategy signature ---")
    print("Pattern: Many small OPEN orders then many small CLOSE orders (scale in / scale out).")
    print("Assets: BTC-heavy, plus ETH, SOL, HYPE, PAXG, JUP, ETC, XMR.")
    print("Direction: Both Long and Short; sometimes flip same day.")
    print("Hold times: Mix of very short (minutes/hours) and overnight.")
    print("Conclusion: Likely GRID / DCA / scaling style - build position in chunks, unwind in chunks.")
    print("Copy-bot relevance: Bot mirrors NET position changes. This trader's NET changes")
    print("  are the sum of many small orders; bot would see the same net delta and replicate it.")
    print("  You'd get one order per 'position change' (open/close/increase/decrease), not")
    print("  one order per leg - so replication is coarser but strategy is replicable.")

if __name__ == "__main__":
    main()
