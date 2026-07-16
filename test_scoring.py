"""
Tests for the composite scoring engine.
Uses fully synthetic data, so no API key is needed.
Run: python test_scoring.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from scoring_engine import grade, score_fundamentals, score_sector, score_technicals

PASS = "\033[32mOK\033[0m"
FAIL = "\033[31mX\033[0m"
errors = []


def check(name, condition, got=None, expect=None):
    if condition:
        print(f"  {PASS}  {name}")
    else:
        message = f"  {FAIL}  {name}"
        if got is not None:
            message += f"  (got {got}, expected {expect})"
        print(message)
        errors.append(name)


def make_fund_data(
    roe=0.18,
    profit_margin=0.10,
    op_margin=0.15,
    rev_growth=0.12,
    eps_growth=0.15,
    debt=5e9,
    equity=20e9,
):
    return {
        "Highlights": {
            "ReturnOnEquityTTM": roe,
            "ProfitMargin": profit_margin,
            "OperatingMarginTTM": op_margin,
            "QuarterlyRevenueGrowthYOY": rev_growth,
            "QuarterlyEarningsGrowthYOY": eps_growth,
        },
        "Financials": {
            "Balance_Sheet": {
                "quarterly": {
                    "2024-09-30": {
                        "totalDebt": str(int(debt)),
                        "totalStockholderEquity": str(int(equity)),
                    }
                }
            }
        },
    }


def make_price_df(n=150, squeeze=True, volume_spike=True, trend="up"):
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    if trend == "up":
        price = 1000 + np.cumsum(np.random.randn(n) * 2 + 0.5)
    else:
        price = 1000 + np.cumsum(np.random.randn(n) * 2 - 0.5)

    if squeeze and n >= 21:
        base = price[-21]
        price[-20:] = base + np.random.randn(20) * 1.5

    volume = np.random.randint(500_000, 1_000_000, n).astype(float)
    if volume_spike and n >= 20:
        volume[-1] = volume[-20:].mean() * 2.8

    return pd.DataFrame(
        {
            "open": price * 0.998,
            "high": price * 1.005,
            "low": price * 0.995,
            "close": price,
            "volume": volume,
        },
        index=dates,
    )


print("\nFundamental scoring")
print("-" * 40)

s = score_fundamentals(make_fund_data(roe=0.35))
check("ROE 35% -> roe_score = 8", s.roe_score == 8, s.roe_score, 8)

s = score_fundamentals(make_fund_data(roe=0.12))
check("ROE 12% -> roe_score = 3", s.roe_score == 3, s.roe_score, 3)

s = score_fundamentals(make_fund_data(roe=-0.05))
check("ROE negative -> roe_score = 0", s.roe_score == 0, s.roe_score, 0)

s = score_fundamentals(make_fund_data(profit_margin=0.22, op_margin=0.25))
check("Fat margins -> margin_score = 7", s.margin_score == 7, s.margin_score, 7)

s = score_fundamentals(make_fund_data(rev_growth=0.30, eps_growth=0.30))
check("High growth -> growth_score = 8", s.growth_score == 8, s.growth_score, 8)

s = score_fundamentals(make_fund_data(debt=1e9, equity=20e9))
check("Very low debt -> debt_score = 7", s.debt_score == 7, s.debt_score, 7)

s = score_fundamentals(make_fund_data(debt=20e9, equity=10e9))
check("High debt -> debt_score = 0", s.debt_score == 0, s.debt_score, 0)

s = score_fundamentals(
    make_fund_data(
        roe=0.22,
        profit_margin=0.14,
        op_margin=0.18,
        rev_growth=0.18,
        eps_growth=0.20,
        debt=2e9,
        equity=15e9,
    )
)
check("Strong stock -> fundamental total >= 22", s.total >= 22, s.total, ">=22")
check("Fundamental total <= 30", s.total <= 30, s.total, "<=30")

print("\nTechnical scoring")
print("-" * 40)

df_squeeze = make_price_df(squeeze=True, volume_spike=True, trend="up")
t = score_technicals(df_squeeze)
check("Squeeze detected -> bandwidth_pct < 25", t.bandwidth_pct is not None and t.bandwidth_pct < 25, t.bandwidth_pct, "<25")
check("Volume spike -> volume_score >= 12", t.volume_score >= 12, t.volume_score, ">=12")
check("BB score > 0", t.bb_score > 0, t.bb_score, ">0")
check("Technical total <= 65", t.total <= 65, t.total, "<=65")

df_wide = make_price_df(squeeze=False, volume_spike=False, trend="up")
t2 = score_technicals(df_wide)
check("No squeeze -> bb_score lower than squeeze case", t2.bb_score <= t.bb_score)

df_short = make_price_df(n=3)
t3 = score_technicals(df_short)
check("Too-short data -> all zeros", t3.total == 0, t3.total, 0)

nifty = make_price_df(n=150, trend="down")["close"] * 0.8
t4 = score_technicals(df_squeeze, nifty_series=nifty)
check("Outperforming Nifty -> rs_score > 0", t4.rs_score > 0, t4.rs_score, ">0")

print("\nSector scoring")
print("-" * 40)

ss = score_sector("Capital Goods")
check("Capital Goods -> rank 1, score 5", ss.sector_score == 5 and ss.sector_rank == 1)

ss = score_sector("Power")
check("Power -> rank 7, score 0", ss.sector_score == 0 and ss.sector_rank == 7)

ss = score_sector("Pharma")
check("Pharma -> rank 3, score 3", ss.sector_score == 3, ss.sector_score, 3)

ss = score_sector("Unknown Niche Sector XYZ")
check("Unknown sector -> participation bonus 1", ss.sector_score == 1)

print("\nGrade assignment")
print("-" * 40)

check("Score 85 -> A+", grade(85) == ("A+", "Strong Buy"))
check("Score 72 -> A", grade(72) == ("A", "Buy"))
check("Score 62 -> B", grade(62) == ("B", "Watch"))
check("Score 50 -> C", grade(50) == ("C", "Neutral"))
check("Score 30 -> D", grade(30) == ("D", "Skip"))

print("\n" + "-" * 40)
if errors:
    print(f"  {len(errors)} test(s) failed: {', '.join(errors)}")
    sys.exit(1)

print(f"  {PASS}  All tests passed")
