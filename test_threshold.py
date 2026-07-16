"""Quick threshold validation — run once to verify all management rules are live."""
from scoring_engine import score_stock, THRESHOLDS

print("=" * 60)
print("  MANAGEMENT THRESHOLDS IN USE")
print("=" * 60)
for k, v in THRESHOLDS.items():
    print(f"  {k:15s} = {v}")
print()

s = score_stock("TCS")
f = s.fundamental
t = s.technical

thr_de   = THRESHOLDS["de_max"]
thr_roe  = THRESHOLDS["roe_min"]
thr_roce = THRESHOLDS["roce_min"]
thr_atr  = THRESHOLDS["atr_min"]

print(f"TCS  |  Total: {s.total}  Grade: {s.grade}  Signal: {s.signal}")
print(f"  Fund score:    {f.total}")
print(f"  Tech score:    {t.total}")
print()
print(f"  ROE:           {(f.roe or 0)*100:.1f}%  (threshold >= {thr_roe*100:.0f}%)  OK={f.roe is not None and f.roe >= thr_roe}")
print(f"  ROCE:          {(f.roce or 0)*100:.1f}%  (threshold >= {thr_roce*100:.0f}%)  OK={f.roce is not None and f.roce >= thr_roce}")
print(f"  EPS:           {f.eps}  (must be > 0)  OK={f.eps is not None and f.eps > 0}")
print(f"  D/E:           {f.debt_equity}  (threshold <= {thr_de})  OK={f.debt_equity is None or f.debt_equity <= thr_de}")
print(f"  ATR(14):       {t.atr}  (threshold > {thr_atr})  OK={t.atr is not None and t.atr > thr_atr}")
print(f"  ADX(14):       {t.adx}  (threshold >= 25)")
print(f"  Vol window:    {THRESHOLDS['vol_days']}d  |  vol_ratio: {t.vol_ratio}")
print(f"  passes_filter: {f.passes_filter}")
