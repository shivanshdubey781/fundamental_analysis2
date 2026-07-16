import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Fallbacks for core index groups if index_universes.json is missing or malformed
FALLBACK_NIFTY50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "HCLTECH", "AXISBANK", "BAJFINANCE", "WIPRO",
    "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "ASIANPAINT",
    "NESTLEIND", "POWERGRID", "NTPC", "ONGC", "JSWSTEEL",
    "TATAMOTORS", "M&M", "TECHM", "INDUSINDBK", "ADANIENT",
    "BAJAJFINSV", "GRASIM", "ADANIPORTS", "COALINDIA", "BPCL",
    "CIPLA", "DRREDDY", "EICHERMOT", "HEROMOTOCO", "HINDALCO",
    "TATASTEEL", "SBILIFE", "HDFCLIFE", "BRITANNIA", "DIVISLAB",
    "APOLLOHOSP", "TATACONSUM", "BAJAJ-AUTO", "UPL", "SHREECEM",
]

FALLBACK_NEXT50 = [
    "DMART", "SIEMENS", "HAVELLS", "PIDILITIND", "MUTHOOTFIN",
    "LUPIN", "TORNTPHARM", "BERGEPAINT", "COLPAL", "MARICO",
    "GODREJCP", "DABUR", "INDIGO", "BANKBARODA", "PNB",
    "CANBK", "UNIONBANK", "IDFCFIRSTB", "FEDERALBNK", "BANDHANBNK",
    "MCDOWELL-N", "UBL", "TATAPOWER", "ADANIGREEN", "ADANIENSOL",
    "ATGL", "IGL", "MGL", "PETRONET", "GAIL",
    "SAIL", "NMDC", "VEDL", "NATIONALUM", "HINDCOPPER",
    "VOLTAS", "WHIRLPOOL", "BLUESTARCO", "CROMPTON", "POLYCAB",
    "AUROPHARMA", "ALKEM", "IPCALAB", "GLAXO", "ABBOTT",
    "MPHASIS", "LTIM", "PERSISTENT", "COFORGE", "KPITTECH",
]

FALLBACK_MIDCAP100 = [
    "CHOLAFIN", "BAJAJHLDNG", "MAXHEALTH", "ASTRAL", "SUPREMEIND",
    "TRENT", "NYKAA", "ZOMATO", "IRCTC", "CONCOR",
    "HUDCO", "RVNL", "IRFC", "SUZLON", "CESC",
    "TORNTPOWER", "GSPL", "MOTHERSON", "BALKRISIND", "APOLLOTYRE",
    "MRF", "CEAT", "OBEROIRLTY", "DLF", "GODREJPROP",
    "PRESTIGE", "PHOENIXLTD", "ABCAPITAL", "IIFL", "M&MFIN",
    "SHRIRAMFIN", "MANAPPURAM", "GMRINFRA", "AIAENG", "BHEL",
    "BEL", "HAL", "DIXON", "AMBER", "KAYNES",
    "LAURUSLABS", "GRANULES", "NATCOPHARM", "SUDARSCHEM", "VINATIORGA",
    "DEEPAKNTR", "AAVAS", "HOMEFIRST", "FINEORG", "GALAXYSURF",
]

FALLBACK_NIFTY500_EXTRA = [
    "ANGELONE", "CDSL", "BSE", "MCX", "KFINTECH", "CAMS",
    "CREDITACC", "UJJIVANSFB", "RBLBANK", "DCBBANK", "EQUITASBNK",
    "BIOCON", "PFIZER", "SANOFI", "METROPOLIS", "THYROCARE",
    "IPCA", "SOLARA", "GLENMARK", "TORNTPHARM",
    "TANLA", "ROUTE", "INTELLECT", "MASTEK", "ZENSAR",
    "LTTS", "CMSINFO", "RRKABEL", "HAPPYMINDS",
    "EXIDEIND", "AMARARAJA", "ESCORTS", "MAHINDCIE",
    "CRAFTSMAN", "RAMKRISHNA", "SUPRAJIT",
    "EMAMILTD", "JYOTHYLAB", "RADICO", "VSTIND",
    "HONAUT", "PGHH", "CCL",
    "NBCC", "IRCON", "KEC", "THERMAX", "CUMMINSIND",
    "ELGIEQUIP", "JSWENERGY", "ADANIPOWER", "GRINDWELL",
    "CLEAN", "NAVINFLUOR", "AARTI", "PIDILITIND",
    "SOLUTIONSINF", "TATACHEM",
    "SUNTECK", "MAHLIFE", "BRIGADE", "SOBHA",
    "ZEEL", "PVRINOX", "SAREGAMA",
    "NAUKRI", "JUSTDIAL", "AFFLE", "INDIAMART",
    "DELHIVERY", "EASEMYTRIP",
    "INDHOTEL", "EIHOTEL",
    "BLUEDART", "TCI", "MAHLOG",
    "KRBL", "LTFOODS", "PAGEIND", "RAYMOND",
]

FALLBACK_NIFTY500_CUSTOM = list(set(FALLBACK_NIFTY50 + FALLBACK_NEXT50 + FALLBACK_MIDCAP100 + FALLBACK_NIFTY500_EXTRA))

# Sectoral Indices constants
NIFTY_BANK_TICKERS = ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "IDFCFIRSTB", "FEDERALBNK", "BANDHANBNK", "UJJIVANSFB", "RBLBANK", "DCBBANK", "EQUITASBNK"]
NIFTY_IT_TICKERS = ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "MPHASIS", "LTIM", "PERSISTENT", "COFORGE", "KPITTECH", "TANLA", "ROUTE", "INTELLECT", "MASTEK", "ZENSAR", "LTTS", "CMSINFO", "HAPPYMINDS", "NAUKRI", "JUSTDIAL", "AFFLE", "INDIAMART"]
NIFTY_PHARMA_TICKERS = ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP", "LUPIN", "TORNTPHARM", "AUROPHARMA", "ALKEM", "IPCALAB", "GLAXO", "ABBOTT", "MAXHEALTH", "LAURUSLABS", "GRANULES", "NATCOPHARM", "BIOCON", "PFIZER", "SANOFI", "METROPOLIS", "THYROCARE", "IPCA", "SOLARA", "GLENMARK"]
NIFTY_AUTO_TICKERS = ["MARUTI", "TATAMOTORS", "M&M", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO", "MOTHERSON", "BALKRISIND", "APOLLOTYRE", "MRF", "CEAT", "EXIDEIND", "AMARARAJA", "ESCORTS", "MAHINDCIE", "SUPRAJIT"]
NIFTY_METAL_TICKERS = ["JSWSTEEL", "HINDALCO", "TATASTEEL", "SAIL", "NMDC", "VEDL", "NATIONALUM", "HINDCOPPER", "RAMKRISHNA"]
NIFTY_REALTY_TICKERS = ["OBEROIRLTY", "DLF", "GODREJPROP", "PRESTIGE", "PHOENIXLTD", "SUNTECK", "MAHLIFE", "BRIGADE", "SOBHA"]
NIFTY_MEDIA_TICKERS = ["BHARTIARTL", "ZEEL", "PVRINOX", "SAREGAMA"]
NIFTY_FMCG_TICKERS = ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM", "GODREJCP", "MARICO", "COLPAL", "DABUR", "EMAMILTD", "JYOTHYLAB", "RADICO", "VSTIND", "MCDOWELL-N", "UBL"]
NIFTY_CONSUMER_DURABLES_TICKERS = ["TITAN", "HAVELLS", "VOLTAS", "WHIRLPOOL", "BLUESTARCO", "CROMPTON", "TRENT", "NYKAA", "PAGEIND", "RAYMOND"]
NIFTY_OIL_GAS_TICKERS = ["RELIANCE", "ONGC", "BPCL", "GAIL", "PETRONET", "MGL", "IGL", "ATGL", "GSPL", "IOC", "HPCL"]
HOTEL_TICKERS = ["INDHOTEL", "EIHOTEL", "IRCTC", "EASEMYTRIP", "INDIGO"]

REQUIRED_KEYS = ["nifty50", "next50", "midcap100", "smallcap250", "midsmallcap400", "nifty500_custom"]

def normalize_ticker(ticker: str) -> str:
    return (ticker or "").strip().upper().replace(".NSE", "").replace(".NS", "")

_normalize_ticker = normalize_ticker

_nifty500_custom_cache: list[str] | None = None

def _load_nifty500_csv_symbols() -> list[str]:
    csv_path = Path(__file__).resolve().parent / "NIFTY-500.csv"
    if not csv_path.exists():
        log.warning(f"NIFTY-500.csv not found at {csv_path}")
        return []
    symbols = []
    try:
        import csv
        with open(csv_path, mode="r", encoding="utf-8", errors="ignore") as fh:
            reader = csv.reader(fh)
            try:
                headers = next(reader)
            except StopIteration:
                return []

            # The corrected workbook stores the full broad universe row-wise
            # across these three columns. We read them row-by-row and then
            # dedupe later to reconstruct the intended 500-symbol union.
            target_cols = []
            for name in ("NIFTY 500", "NIFTY NEXT 50", "NIFTY 50"):
                for i, h in enumerate(headers):
                    if h.strip().upper() == name:
                        target_cols.append(i)
                        break

            if not target_cols:
                log.warning("Could not find target columns in NIFTY-500.csv header")
                return []

            for row in reader:
                for col_idx in target_cols:
                    if len(row) <= col_idx:
                        continue
                    val = row[col_idx].strip()
                    if val and not val.lower().startswith("nifty"):
                        symbols.append(val)
    except Exception as exc:
        log.error(f"Failed to read NIFTY-500.csv row-wise: {exc}")
    return symbols

def _dedupe_preserve_order(symbols: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for s in symbols:
        norm = normalize_ticker(s)
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(norm)
    return deduped

def _filter_symbols_present_in_angel_master(symbols: list[str]) -> list[str]:
    import angel_candle
    filtered = []
    for s in symbols:
        token = angel_candle.get_token(s)
        if token:
            filtered.append(s)
    return filtered

def get_nifty500_custom() -> list[str]:
    global _nifty500_custom_cache
    if _nifty500_custom_cache is None:
        raw_symbols = _load_nifty500_csv_symbols()
        deduped = _dedupe_preserve_order(raw_symbols)
        filtered = _filter_symbols_present_in_angel_master(deduped)
        if filtered:
            _nifty500_custom_cache = filtered
            log.info(f"Loaded CSV-backed nifty500_custom: {len(filtered)} symbols (filtered from {len(deduped)} unique)")
        else:
            log.warning("No symbols resolved from CSV and Angel Master! Using fallback list.")
            _nifty500_custom_cache = list(FALLBACK_NIFTY50 + FALLBACK_NEXT50)
    return _nifty500_custom_cache

def load_universes() -> dict[str, list[str]]:
    """
    Loads `data/index_universes.json` from disk.
    Validates required keys. Normalizes symbol names.
    Falls back to safe defaults if missing or malformed.
    """
    json_path = Path(__file__).resolve().parent / "data" / "index_universes.json"
    universes = {}
    
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    # Check and normalize keys/values
                    for k in REQUIRED_KEYS:
                        if k in data and isinstance(data[k], list):
                            universes[k] = [_normalize_ticker(t) for t in data[k] if t]
                        else:
                            log.warning(f"Key {k} missing or invalid in index_universes.json, falling back")
                            universes[k] = _get_default_universe(k)
                else:
                    log.warning("index_universes.json does not contain a dictionary, falling back to defaults")
        except Exception as e:
            log.warning(f"Could not load index_universes.json: {e}. Falling back to defaults")
            
    # If file was missing or malformed, make sure all REQUIRED_KEYS have default values
    for k in REQUIRED_KEYS:
        if k not in universes:
            universes[k] = _get_default_universe(k)
            
    # Always force nifty500_custom to be from CSV
    universes["nifty500_custom"] = get_nifty500_custom()
    return universes

def _get_default_universe(key: str) -> list[str]:
    if key == "nifty50":
        return FALLBACK_NIFTY50
    elif key == "next50":
        return FALLBACK_NEXT50
    elif key == "midcap100":
        return FALLBACK_MIDCAP100
    elif key == "nifty500_custom":
        return get_nifty500_custom()
    # For smallcap250 and midsmallcap400, fallback to empty list if json not readable
    return []

def get_universe(index_key: str) -> list[str]:
    """
    Returns the list of tickers for a given index key.
    Returns empty list for unknown keys.
    """
    clean_key = (index_key or "").strip().lower()
    
    # Handle aliases
    if clean_key == "all" or clean_key == "nifty500":
        clean_key = "nifty500_custom"
        
    # Check if it is a sectoral index first
    sectors = _get_sector_map()
    if clean_key in sectors:
        return sectors[clean_key]
        
    # Load core universes
    universes = load_universes()
    return universes.get(clean_key, [])

def _get_sector_map() -> dict[str, list[str]]:
    return {
        "nifty_bank": NIFTY_BANK_TICKERS,
        "nifty_it": NIFTY_IT_TICKERS,
        "nifty_pharma": NIFTY_PHARMA_TICKERS,
        "nifty_auto": NIFTY_AUTO_TICKERS,
        "nifty_metal": NIFTY_METAL_TICKERS,
        "nifty_realty": NIFTY_REALTY_TICKERS,
        "nifty_media": NIFTY_MEDIA_TICKERS,
        "nifty_fmcg": NIFTY_FMCG_TICKERS,
        "nifty_consumer": NIFTY_CONSUMER_DURABLES_TICKERS,
        "nifty_oilgas": NIFTY_OIL_GAS_TICKERS,
        "nifty_hotel": HOTEL_TICKERS,
    }

def get_index_map() -> dict[str, list[str]]:
    """
    Returns the complete mapping of index and sector names to ticker lists.
    Incorporates both core index groups and sectoral indices.
    """
    core = load_universes()
    
    # Merge core + aliases + sectors
    index_map = {}
    for k, v in core.items():
        index_map[k] = v
        
    # Set up compatibility aliases
    index_map["nifty500"] = core.get("nifty500_custom", [])
    index_map["all"] = get_full_universe()
    
    # Add sectoral indices
    for k, v in _get_sector_map().items():
        index_map[k] = v
        
    return index_map


def get_full_universe() -> list[str]:
    """
    Returns the complete list of unique tickers for the broad scan universe.
    Aligns 'all' to represent the Nifty 500 custom universe.
    """
    return get_nifty500_custom()


def _collapse_overlapping_indices(index_names: list[str]) -> list[str]:
    """
    Collapses overlapping index names to optimize scan complexity.
    If a broader index is selected, narrower child indices are ignored.
    Preserves original insertion order.
    """
    normalized = []
    seen = set()
    for name in index_names:
        clean = (name or "").strip().lower()
        if clean in ("all", "nifty500"):
            clean = "nifty500_custom"
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
            
    collapsed = []
    for clean in normalized:
        # 1. If nifty500_custom (or all) is present, ignore nifty50, next50, midcap100
        if clean in ("nifty50", "next50", "midcap100") and "nifty500_custom" in seen:
            continue
        # 2. If midsmallcap400 is present, ignore smallcap250 and midcap100
        if clean in ("smallcap250", "midcap100") and "midsmallcap400" in seen:
            continue
        collapsed.append(clean)
        
    return collapsed


def build_unique_universe(index_names: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """
    Reads all tickers from the requested indices, normalizes them,
    deduplicates while preserving order, and builds a mapping:
    ticker -> [source index names]
    """
    collapsed_indices = _collapse_overlapping_indices(index_names)
    unique_tickers = []
    source_map = {}
    seen = set()
    
    # Pre-load mapping of all known indices and sectors
    index_map = get_index_map()
    
    for idx_name in collapsed_indices:
        clean_idx = idx_name.strip().lower()
        if not clean_idx:
            continue
        # Get list of tickers from index map (which already resolves aliases)
        tickers = index_map.get(clean_idx, [])
        for t in tickers:
            norm = normalize_ticker(t)
            if not norm:
                continue
            if norm not in seen:
                seen.add(norm)
                unique_tickers.append(norm)
            if norm not in source_map:
                source_map[norm] = []
            if idx_name not in source_map[norm]:
                source_map[norm].append(idx_name)
                
    return unique_tickers, source_map
