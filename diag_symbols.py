"""Second pass for remaining unmapped stocks."""
import yfinance as yf

checks = {
    'TATAMOTORS': ['TATAMTRS', 'TML', 'TATAMOT', 'TATAMOTORS-BE'],
    'LTIM':       ['LTIMINDTREE', 'LTI', 'MINDTREE', 'LTTS'],
    'MAHINDCIE':  ['MAHINDCIE', 'MAHCIE', 'MCIE', 'MAHINDRA-CIE'],
}
for nse, roots in checks.items():
    found = False
    for r in roots:
        for sfx in ['.NS', '.BO']:
            try:
                h = yf.Ticker(r+sfx).history(period='5d')
                if h is not None and not h.empty:
                    print(f"{nse} -> {r+sfx}  close={h['Close'].iloc[-1]:.2f}  FOUND")
                    found = True; break
            except Exception:
                pass
        if found: break
    if not found:
        print(f"{nse} -> still not found")
