"""Find correct Angel One instrument master symbols for problem stocks."""
import angel_candle as ac

tm = ac._load_token_map()

# Search partial name matches
search_terms = {
    'TATAMOTORS': ['TATA MOTOR','TATAMOTO'],
    'GMRINFRA':   ['GMR','GMRINFRA','GMRP'],
    'HAPPYMINDS': ['HAPPY','HAPPSTMNDS','HAPPYMIND'],
    'AMARARAJA':  ['AMARA','AMARAJA','ARE'],
    'LTIM':       ['LTIM','LTIMINDT','LTI'],
    'AARTI':      ['AARTI'],
    'RAMKRISHNA': ['RAMKRISHNA','RKFORGE'],
    'CCL':        ['CCL'],
    'MAHLOG':     ['MAHLOG','MAHINDRA LOG'],
}

print("Searching Angel One instrument master for problem stocks...\n")
for nse, terms in search_terms.items():
    print(f"  {nse}:")
    matches = []
    for sym, tok in tm.items():
        for term in terms:
            if term.upper() in sym.upper():
                matches.append(f"    {sym} (token={tok})")
                break
    if matches:
        for m in matches[:6]:
            print(m)
    else:
        print("    NO MATCH FOUND")
    print()
