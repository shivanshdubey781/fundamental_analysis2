"""Quick unit test for sectoral_analysis.build_sector_summary"""
from sectoral_analysis import build_sector_summary

fake = [
    {"ticker": "TCS",       "sector": "Technology", "total_score": 80, "rsi": 62, "rs_vs_nifty": 1.15, "signal": "Buy",     "grade": "A"},
    {"ticker": "INFY",      "sector": "Technology", "total_score": 75, "rsi": 58, "rs_vs_nifty": 1.10, "signal": "Buy",     "grade": "A"},
    {"ticker": "HDFCBANK",  "sector": "Banking",    "total_score": 70, "rsi": 55, "rs_vs_nifty": 1.05, "signal": "Buy",     "grade": "A"},
    {"ticker": "SBIN",      "sector": "Banking",    "total_score": 45, "rsi": 48, "rs_vs_nifty": 0.95, "signal": "Neutral", "grade": "C"},
    {"ticker": "SUNPHARMA", "sector": "Pharma",     "total_score": 60, "rsi": 60, "rs_vs_nifty": 1.01, "signal": "Watch",   "grade": "B"},
]

result = build_sector_summary(fake)
print("build_sector_summary test:")
print(f"  Sectors returned: {len(result)}")
for s in result:
    print(f"  {s['sector']:15} avg={s['avg_score']:5}  momentum={s['momentum']:8}  top={s['top_stock']}  bull={s['bullish_count']}/{s['stock_count']}  top3={[t['ticker'] for t in s['top3']]}")

# Assertions
assert len(result) == 12, f"Expected 12 sectors, got {len(result)}"
tech = next(s for s in result if s["sector"] == "IT")
assert tech["avg_score"] == 77.5
assert tech["momentum"] == "STRONG"
assert tech["top_stock"] == "TCS"
bank = next(s for s in result if s["sector"] == "Banking & Finance")
assert bank["avg_score"] == 57.5
assert bank["momentum"] == "MODERATE"

print("\nAll assertions passed!")
