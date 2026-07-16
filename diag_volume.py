"""Re-run volume check after the fixes."""
import sys
sys.path.insert(0, r"c:\Users\Shivansh Dubey\OneDrive\Desktop\fundamental_analysis")
import scoring_engine as se

tickers = ["TCS", "TATAMOTORS", "HDFCBANK", "INFY", "RELIANCE", "WIPRO", "BAJFINANCE"]

print(f"{'SYMBOL':<16} {'LAST_VOL':>14} {'15D_AVG':>14} {'RATIO':>8} {'STATUS'}")
print("-" * 72)

for t in tickers:
    df = se.fetch_price_data(t, period=35)
    if df is None or len(df) < 3:
        print(f"{t:<16} {'NO DATA':>14}")
        continue

    vol = df["volume"]
    last_vol = int(vol.iloc[-1])
    avg_15d  = vol.iloc[-15:].mean() if len(vol) >= 15 else vol.mean()
    ratio    = last_vol / avg_15d if avg_15d > 0 else 0

    # flag suspiciously low values
    flag = "✅ OK" if last_vol > 50_000 else "⚠ LOW"
    print(f"{t:<16} {last_vol:>14,} {avg_15d:>14,.0f} {ratio:>8.2f}  {flag}")
