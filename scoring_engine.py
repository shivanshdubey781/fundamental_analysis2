"""
NSE positional trading composite scoring engine.

Combines Yahoo Finance fundamentals plus technical indicators
into a single 0-100 score per stock.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ── Angel One OHLCV integration ───────────────────────────────────────────────
# angel_candle provides exchange-accurate daily bars as a replacement for
# the stale / symbol-broken yfinance OHLCV path.
# Fundamentals (ROE, EPS, D/E) remain on yfinance — Angel One has no fundamentals API.
try:
    import angel_candle as _angel_candle
    _ANGEL_CANDLE_AVAILABLE = True
except ImportError:
    _angel_candle = None          # type: ignore
    _ANGEL_CANDLE_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

NIFTY_INDEX_SYMBOL = "^NSEI"

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║      MANAGEMENT SCREENING THRESHOLDS  (single source of truth)          ║
# ╠══════════════════════════════════════════════════════════════════════════╣
# ║  Change these values here — they propagate everywhere automatically.    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
THRESHOLDS = {
    "de_max":       0.50,   # D/E ≤ 0.50  — low leverage requirement
    "roe_min":      0.15,   # ROE ≥ 15%   — return on equity floor
    "roce_min":     0.15,   # ROCE ≥ 15%  — return on capital employed floor
    "eps_positive": True,   # EPS > 0     — profitable company required
    "atr_min":      25.0,   # ATR > ₹25  — minimum volatility / move size
    "vol_days":     15,     # Volume benchmark window (15-day average)
}


@dataclass
class FundamentalScore:
    roe_score:   float = 0
    margin_score: float = 0
    growth_score: float = 0
    debt_score:  float = 0
    roce_score:  float = 0          # NEW — ROCE ≥ 15% bonus
    total:       float = 0

    roe:          Optional[float] = None
    roce:         Optional[float] = None  # Return on Capital Employed
    eps:          Optional[float] = None  # Trailing EPS (raw value)
    profit_margin: Optional[float] = None
    op_margin:    Optional[float] = None
    rev_growth:   Optional[float] = None
    eps_growth:   Optional[float] = None
    debt_equity:  Optional[float] = None
    passes_filter: bool = True   # False if any hard disqualifier triggered


@dataclass
class TechnicalScore:
    bb_score: float = 0
    volume_score: float = 0
    rs_score: float = 0
    rsi_score: float = 0
    adx_score: float = 0          # ADX(14) trend-strength bonus
    delivery_score: float = 0     # P2-B: NSE delivery % bonus
    oi_score: float = 0           # P3-B: F&O OI buildup bonus
    total: float = 0

    bandwidth_pct: Optional[float] = None
    upper_band: Optional[float] = None    # BB upper band value
    bb_breakout: bool = False             # P1-A: close > upper_band
    vol_ratio: Optional[float] = None
    last_volume: Optional[int] = None        # raw last-session volume (for display)
    rs_ratio: Optional[float] = None
    rsi: Optional[float] = None
    adx: Optional[float] = None           # ADX(14)
    atr: Optional[float] = None           # ATR(14)
    above_ema50: bool = False
    above_ema200: bool = False            # EMA(200) filter
    golden_cross: bool = False            # EMA50 > EMA200
    close: Optional[float] = None
    stop_loss: Optional[float] = None     # close - 1.5 × ATR
    delivery_pct: Optional[float] = None  # NSE delivery %
    pcr: Optional[float] = None           # F&O Put-Call Ratio
    oi_signal: Optional[str] = None       # BULLISH / NEUTRAL / BEARISH


@dataclass
class SectorScore:
    sector_score: float = 0
    sector: str = ""
    sector_rank: int = 99


@dataclass
class AstroScore:
    astro_score: float = 0
    ruling_planets: str = ""
    transit_status: str = ""   # e.g., "UPSIDE", "DOWNSIDE", "NEUTRAL"


@dataclass
class CompositeScore:
    ticker: str = ""
    name: str = ""
    sector: str = ""
    total: float = 0
    grade: str = ""
    signal: str = ""
    fundamental: FundamentalScore = field(default_factory=FundamentalScore)
    technical: TechnicalScore = field(default_factory=TechnicalScore)
    sector_sc: SectorScore = field(default_factory=SectorScore)
    astro_sc: AstroScore = field(default_factory=AstroScore)
    days_to_result: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["fundamental"] = asdict(self.fundamental)
        data["technical"] = asdict(self.technical)
        data["sector_sc"] = asdict(self.sector_sc)
        data["astro_sc"] = asdict(self.astro_sc)
        return data


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_ticker(ticker: str) -> str:
    return (ticker or "").strip().upper().replace(".NSE", "").replace(".NS", "")


# Known yfinance symbol differences for NSE tickers
# Format: { NSE_SYMBOL: yfinance_root (without .NS suffix) }
# Only list symbols where the NSE name != the yfinance root.
YF_ALIAS_MAP: dict[str, str] = {
    # ── Corporate action renames / mergers ─────────────────────────────────
    "MCDOWELL-N":   "UNITDSPR",     # United Spirits / McDowell's
    "ABBOTT":       "ABBOTINDIA",   # Abbott India
    "IPCA":         "IPCALAB",      # IPCA Laboratories
    "SOLARA":       "SOLARA",
    "AMARARAJA":    "ARE&M",        # Amara Raja Energy & Mobility (renamed)
    "HAPPYMINDS":   "HAPPSTMNDS",   # HappyMind Technologies — yf uses HAPPSTMNDS
    "GMRINFRA":     "GMRP&UI",      # GMR Power and Urban Infra
    "RAMKRISHNA":   "RKFORGE",      # Ramkrishna Forgings
    "AARTI":        "AARTIIND",     # Aarti Industries
    "LTIM":         "LTTS",         # LTIMindtree trades as LTTS on yfinance
    "CCL":          "CCL",          # CCL Products — plain CCL.NS works
    "SOLUTIONSINF": "SIS",          # SIS Ltd
    "MAHLOG":       "MAHLOG",       # Mahindra Logistics — plain MAHLOG.NS
    "M&M":          "M&M",          # yfinance handles & correctly
    "M&MFIN":       "M&MFIN",
    "GLAXO":        "GLAXO",
    "PGHH":         "PGHH",
    "HONAUT":       "HONAUT",
}

# Tickers permanently broken / delisted in yfinance — skip before fetching.
# Add any symbol here that consistently returns 404 from both .NS and .BO.
_SKIP_SYMBOLS: set[str] = {
    "TATAMOTORS",   # yfinance 404 as of May 2025 (intermittent CDN issue)
    "MAHINDCIE",    # Mahindra CIE — not available on yfinance
}



def _yf_symbol(ticker: str) -> str:
    symbol = _normalize_ticker(ticker)
    if symbol in {"^NSEI", "NIFTY", "NIFTY50", "NIFTY 50"}:
        return NIFTY_INDEX_SYMBOL
    if symbol.startswith("^"):
        return symbol
    mapped = YF_ALIAS_MAP.get(symbol, symbol)
    return f"{mapped}.NS"


_yf_session = None

def _get_yf_session():
    global _yf_session
    if _yf_session is None:
        import requests
        from urllib3.util import Retry
        from requests.adapters import HTTPAdapter
        
        class TimeoutHTTPAdapter(HTTPAdapter):
            def __init__(self, *args, **kwargs):
                self.timeout = 10
                if "timeout" in kwargs:
                    self.timeout = kwargs.pop("timeout")
                super().__init__(*args, **kwargs)
                
            def send(self, request, **kwargs):
                if kwargs.get("timeout") is None:
                    kwargs["timeout"] = self.timeout
                return super().send(request, **kwargs)
                
        session = requests.Session()
        retries = Retry(total=2, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
        adapter = TimeoutHTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        _yf_session = session
    return _yf_session


def _ticker_obj(ticker: str) -> yf.Ticker:
    return yf.Ticker(_yf_symbol(ticker), session=_get_yf_session())


def _fetch_history_with_fallback(ticker: str, period_days: int) -> Optional[pd.DataFrame]:
    """
    Fetch yfinance history for an NSE ticker.
    Tries .NS first; if empty (common for some tickers like TATAMOTORS after
    an exchange migration in yfinance's database), falls back to .BO (BSE).
    """
    sym_ns = _yf_symbol(ticker)          # e.g. TATAMOTORS.NS
    period = f"{max(period_days, 30)}d"
    try:
        hist = yf.Ticker(sym_ns, session=_get_yf_session()).history(period=period, interval="1d", auto_adjust=False, timeout=10)
        if hist is not None and not hist.empty:
            return hist
    except Exception:
        pass

    # --- .NS failed: try .BO fallback ---
    if sym_ns.endswith(".NS"):
        sym_bo = sym_ns[:-3] + ".BO"
        try:
            hist = yf.Ticker(sym_bo, session=_get_yf_session()).history(period=period, interval="1d", auto_adjust=False, timeout=10)
            if hist is not None and not hist.empty:
                log.debug("%s: .NS empty — using .BO fallback", ticker)
                return hist
        except Exception:
            pass

    return None


def _pick(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_yield(value) -> Optional[float]:
    dividend_yield = _safe_float(value)
    if dividend_yield is None:
        return None
    return dividend_yield / 100 if dividend_yield > 1 else dividend_yield


def _clean_multiple(value, upper_bound: float) -> Optional[float]:
    metric = _safe_float(value)
    if metric is None or metric <= 0 or metric > upper_bound:
        return None
    return metric


def _series_lookup(series: pd.Series, names: list[str]) -> Optional[float]:
    normalized = {str(idx).strip().lower(): val for idx, val in series.items()}
    for name in names:
        if name.lower() in normalized:
            return _safe_float(normalized[name.lower()])
    return None


def _df_row(df: Optional[pd.DataFrame], names: list[str], col_idx: int = 0) -> Optional[float]:
    if df is None or df.empty or col_idx >= len(df.columns):
        return None
    try:
        series = df.iloc[:, col_idx]
    except Exception:
        return None
    return _series_lookup(series, names)


def _quarterly_growth(df: Optional[pd.DataFrame], row_names: list[str]) -> Optional[float]:
    if df is None or df.empty or len(df.columns) < 4:
        return None
    current = _df_row(df, row_names, 0)
    year_ago = _df_row(df, row_names, 3)
    if current is None or year_ago in (None, 0):
        return None
    return (current / year_ago) - 1


def fetch_fundamentals_result(ticker: str, api_key: str = "") -> tuple[Optional[dict], Optional[str]]:
    """
    Fetch fundamentals from Yahoo Finance via yfinance and normalize them
    into the legacy structure expected by the scorer and frontend.
    """
    try:
        tk = _ticker_obj(ticker)
        info = tk.info or {}
        if not info:
            return None, f"Yahoo Finance returned no profile data for {_yf_symbol(ticker)}"

        qbs = tk.quarterly_balance_sheet
        qis = tk.quarterly_income_stmt

        total_debt = _df_row(qbs, ["Total Debt", "Net Debt"])
        total_equity = _df_row(qbs, ["Common Stock Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"])
        cash = _df_row(qbs, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash"])
        latest_quarter = str(qbs.columns[0].date()) if qbs is not None and not qbs.empty else "latest"

        rev_growth = _pick(
            _safe_float(info.get("revenueGrowth")),
            _quarterly_growth(qis, ["Total Revenue", "Operating Revenue"]),
        )
        eps_growth = _pick(
            _safe_float(info.get("earningsQuarterlyGrowth")),
            _safe_float(info.get("earningsGrowth")),
            _quarterly_growth(qis, ["Diluted EPS", "Basic EPS"]),
        )

        revenue_ttm = _safe_float(info.get("totalRevenue"))
        dividend_yield = _pick(
            _safe_float(info.get("trailingAnnualDividendYield")),
            _safe_float(info.get("dividendRate")) / _safe_float(info.get("currentPrice"))
            if _safe_float(info.get("dividendRate")) is not None and _safe_float(info.get("currentPrice"))
            else None,
            _normalize_yield(info.get("dividendYield")),
        )

        normalized = {
            "General": {
                "Code": _normalize_ticker(ticker),
                "Name": info.get("longName") or info.get("shortName") or _normalize_ticker(ticker),
                "Sector": info.get("sector") or "",
                "Industry": info.get("industry") or "",
                "Exchange": "NSE",
                "CurrencyCode": info.get("currency") or "INR",
            },
            "Highlights": {
                "MarketCapitalizationMln": _safe_float(info.get("marketCap")) / 1_000_000 if info.get("marketCap") else None,
                "PERatio": _safe_float(info.get("trailingPE")),
                "PEGRatio": _safe_float(info.get("pegRatio")),
                "BookValue": _safe_float(info.get("bookValue")),
                "DividendYield": dividend_yield,
                "EarningsShare": _safe_float(info.get("trailingEps")),
                "EPSEstimateCurrentYear": _safe_float(info.get("trailingEps")),
                "EPSEstimateNextYear": _safe_float(info.get("forwardEps")),
                "RevenuePerShareTTM": _safe_float(info.get("revenuePerShare")),
                "ProfitMargin": _safe_float(info.get("profitMargins")),
                "OperatingMarginTTM": _safe_float(info.get("operatingMargins")),
                "ReturnOnAssetsTTM":         _safe_float(info.get("returnOnAssets")),
                "ReturnOnEquityTTM":          _safe_float(info.get("returnOnEquity")),
                "RevenueTTM":                 revenue_ttm,
                "GrossProfitTTM":             _safe_float(info.get("grossProfits")),
                "EBITDAMln":                  _safe_float(info.get("ebitda")),
                "DilutedEpsTTM":              _safe_float(info.get("trailingEps")),
                "EarningsShareTTM":           _safe_float(info.get("trailingEps")),   # raw EPS ← NEW
                "QuarterlyRevenueGrowthYOY":  rev_growth,
                "QuarterlyEarningsGrowthYOY": eps_growth,
                # ── ROCE approximation = EBIT / Capital Employed ─────────────────
                # yfinance doesn't have ROCE directly; we proxy via:
                #   ROCE ≈ operatingIncome / (totalAssets − currentLiabilities)
                "EBIT":                       _safe_float(info.get("ebit")),
                "TotalAssets":                _safe_float(info.get("totalAssets")),
                "CurrentLiabilities":         _safe_float(info.get("currentLiabilities")),
                "TotalDebtRaw":               _safe_float(info.get("totalDebt")),
                "TotalEquityRaw":             _safe_float(info.get("bookValue"))
                    and _safe_float(info.get("sharesOutstanding"))
                    and _safe_float(info.get("bookValue")) * _safe_float(info.get("sharesOutstanding")),
            },
            "Valuation": {
                "TrailingPE": _clean_multiple(info.get("trailingPE"), 200),
                "ForwardPE": _clean_multiple(info.get("forwardPE"), 200),
                "PriceSalesTTM": _clean_multiple(info.get("priceToSalesTrailing12Months"), 50),
                "PriceBookMRQ": _clean_multiple(info.get("priceToBook"), 50),
                "EnterpriseValueRevenue": _clean_multiple(info.get("enterpriseToRevenue"), 50),
                "EnterpriseValueEbitda": _clean_multiple(info.get("enterpriseToEbitda"), 100),
            },
            "Financials": {
                "Balance_Sheet": {
                    "quarterly": {
                        latest_quarter: {
                            "totalDebt": total_debt,
                            "totalStockholderEquity": total_equity,
                            "cash": cash,
                        }
                    }
                    if total_debt is not None or total_equity is not None
                    else {}
                }
            },
        }
        return normalized, None
    except Exception as exc:
        message = f"Yahoo Finance fundamentals fetch failed for {_yf_symbol(ticker)}: {exc}"
        log.error(message)
        return None, message


def fetch_fundamentals(ticker: str, api_key: str = "") -> Optional[dict]:
    data, _ = fetch_fundamentals_result(ticker, api_key)
    return data


def fetch_price_data(ticker: str, api_key: str = "", period: int = 180) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV — yfinance first, Angel One fallback.

    Source priority
    ---------------
    1. yfinance                 → primary source to avoid exhausting Angel One API rate limits
    2. Angel One getCandleData  → fallback when yfinance fails or symbol is migrated/broken

    Fundamentals (ROE, EPS, D/E, ROCE) are NOT fetched here — that path
    stays on yfinance via fetch_fundamentals_result().
    """
    from datetime import date

    # ── Path 1: yfinance primary ─────────────────────────────────────────
    df_yf = None
    try:
        hist = _fetch_history_with_fallback(ticker, period)
        if hist is not None and not hist.empty:
            # Drop today's partial bar
            today_str = str(date.today())
            if len(hist) > 1:
                last_date = str(hist.index[-1].date()) if hasattr(hist.index[-1], 'date') else str(hist.index[-1])[:10]
                if last_date == today_str:
                    hist = hist.iloc[:-1]

            df = hist.rename(columns={
                "Open":      "open",
                "High":      "high",
                "Low":       "low",
                "Close":     "close",
                "Adj Close": "adjusted_close",
                "Volume":    "volume",
            })
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df.index.name = "date"
            keep = [c for c in ["open","high","low","close","adjusted_close","volume"] if c in df.columns]
            df   = df[keep].apply(pd.to_numeric, errors="coerce")
            df   = df[df["volume"] > 0]
            df_yf = df.dropna(subset=["open","high","low","close","volume"])
            
            if df_yf is not None and len(df_yf) >= 20:
                log.debug("%s: using yfinance OHLCV (%d bars)", ticker, len(df_yf))
                return df_yf
    except Exception as exc:
        log.warning("%s: yfinance price fetch failed (%s) — trying Angel One fallback", ticker, exc)

    # ── Path 2: Angel One fallback ─────────────────────────────────────────
    if _ANGEL_CANDLE_AVAILABLE and ticker != NIFTY_INDEX_SYMBOL:
        try:
            df_angel = _angel_candle.get_ohlcv(ticker, days=period)
            if df_angel is not None and len(df_angel) >= 20:
                log.debug("%s: using Angel One OHLCV fallback (%d bars)", ticker, len(df_angel))
                return df_angel
            elif df_angel is not None:
                log.debug("%s: Angel One returned only %d bars — too short", ticker, len(df_angel))
        except Exception as exc:
            log.error("%s: Angel One OHLCV fallback failed: %s", ticker, exc)

    # If both failed, return whichever was partially loaded or None
    return df_yf



def fetch_nifty_data(api_key: str = "", period: int = 180) -> Optional[pd.Series]:
    df = fetch_price_data(NIFTY_INDEX_SYMBOL, api_key, period)
    if df is None:
        return None
    return df["close"]


def score_fundamentals(data: dict) -> FundamentalScore:
    """
    Score fundamentals using management thresholds.

    Hard disqualifiers (score.passes_filter = False):
      • D/E  > 0.50   (THRESHOLDS['de_max'])
      • EPS  ≤ 0      (THRESHOLDS['eps_positive'])

    Soft bonuses use the same thresholds as band anchors.
    """
    score  = FundamentalScore()
    h      = data.get("Highlights", {})
    de_max = THRESHOLDS["de_max"]
    roe_min = THRESHOLDS["roe_min"]
    roce_min = THRESHOLDS["roce_min"]

    bs_quarterly = data.get("Financials", {}).get("Balance_Sheet", {}).get("quarterly", {})

    score.roe         = _safe_float(h.get("ReturnOnEquityTTM"))
    score.profit_margin = _safe_float(h.get("ProfitMargin"))
    score.op_margin   = _safe_float(h.get("OperatingMarginTTM"))
    score.rev_growth  = _safe_float(h.get("QuarterlyRevenueGrowthYOY"))
    score.eps_growth  = _safe_float(h.get("QuarterlyEarningsGrowthYOY"))
    score.eps         = _safe_float(h.get("EarningsShareTTM") or h.get("DilutedEpsTTM"))

    # ── ROCE  ≈  EBIT / (Total Assets − Current Liabilities) ─────────────────
    ebit   = _safe_float(h.get("EBIT"))
    ta     = _safe_float(h.get("TotalAssets"))
    cl     = _safe_float(h.get("CurrentLiabilities"))
    if ebit is not None and ta is not None and cl is not None:
        cap_employed = ta - cl
        if cap_employed > 0:
            score.roce = round(ebit / cap_employed, 4)  # e.g. 0.18 = 18%

    # ── D/E from balance sheet ────────────────────────────────────────────────
    latest_q = sorted(bs_quarterly.keys())[-1] if bs_quarterly else None
    if latest_q:
        bs_row = bs_quarterly[latest_q]
        debt   = _safe_float(bs_row.get("totalDebt"))
        equity = _safe_float(bs_row.get("totalStockholderEquity"))
        if debt is not None and equity and equity > 0:
            score.debt_equity = debt / equity

    # ════════════════════════════════════════════════════════════════════
    #  HARD DISQUALIFIERS  — passes_filter stays True only when all pass
    # ════════════════════════════════════════════════════════════════════
    # 1. D/E must be ≤ de_max (0.50)  — skip if D/E unknown (give benefit of doubt)
    if score.debt_equity is not None and score.debt_equity > de_max:
        score.passes_filter = False

    # 2. EPS must be positive
    if score.eps is not None and score.eps <= 0:
        score.passes_filter = False

    # ════════════════════════════════════════════════════════════════════
    #  ROE SCORE  (anchor: roe_min = 15%)
    # ════════════════════════════════════════════════════════════════════
    if score.roe is not None:
        if score.roe >= 0.30:
            score.roe_score = 8        # exceptional
        elif score.roe >= 0.20:
            score.roe_score = 7
        elif score.roe >= roe_min:     # ≥ 15% — meets management threshold
            score.roe_score = 5
        elif score.roe >= 0.10:
            score.roe_score = 3
        elif score.roe > 0:
            score.roe_score = 1
        # roe ≤ 0 → 0 (no contribution)

    # ════════════════════════════════════════════════════════════════════
    #  MARGIN SCORE
    # ════════════════════════════════════════════════════════════════════
    net_pts = 0
    op_pts  = 0
    if score.profit_margin is not None:
        if score.profit_margin > 0.20:
            net_pts = 4
        elif score.profit_margin > 0.12:
            net_pts = 3
        elif score.profit_margin > 0.06:
            net_pts = 2
        elif score.profit_margin > 0:
            net_pts = 1
    if score.op_margin is not None:
        if score.op_margin > 0.20:
            op_pts = 3
        elif score.op_margin > 0.12:
            op_pts = 2
        elif score.op_margin > 0.06:
            op_pts = 1
    score.margin_score = min(7, net_pts + op_pts)

    # ════════════════════════════════════════════════════════════════════
    #  GROWTH SCORE
    # ════════════════════════════════════════════════════════════════════
    rev_pts = 0
    eps_pts = 0
    if score.rev_growth is not None:
        if score.rev_growth > 0.25:
            rev_pts = 4
        elif score.rev_growth > 0.15:
            rev_pts = 3
        elif score.rev_growth > 0.08:
            rev_pts = 2
        elif score.rev_growth > 0.02:
            rev_pts = 1
    if score.eps_growth is not None:
        if score.eps_growth > 0.25:
            eps_pts = 4
        elif score.eps_growth > 0.15:
            eps_pts = 3
        elif score.eps_growth > 0.08:
            eps_pts = 2
        elif score.eps_growth > 0:
            eps_pts = 1
    score.growth_score = min(8, rev_pts + eps_pts)

    # ════════════════════════════════════════════════════════════════════
    #  D/E SCORE  (anchor: de_max = 0.50)
    # ════════════════════════════════════════════════════════════════════
    if score.debt_equity is not None:
        if score.debt_equity <= 0.10:
            score.debt_score = 7        # near-zero debt — premium
        elif score.debt_equity <= 0.30:
            score.debt_score = 6
        elif score.debt_equity <= de_max:  # ≤ 0.50 — passes filter
            score.debt_score = 5
        elif score.debt_equity <= 0.80:
            score.debt_score = 3        # breaches filter but partial credit
        elif score.debt_equity <= 1.50:
            score.debt_score = 1
        # else 0 (highly leveraged)
    else:
        score.debt_score = 3            # unknown → neutral

    # ════════════════════════════════════════════════════════════════════
    #  ROCE SCORE  (anchor: roce_min = 15%)  — up to 5 bonus points
    # ════════════════════════════════════════════════════════════════════
    if score.roce is not None:
        if score.roce >= 0.25:
            score.roce_score = 5        # ROCE ≥ 25%  — excellent
        elif score.roce >= 0.20:
            score.roce_score = 4
        elif score.roce >= roce_min:    # ≥ 15% — meets threshold
            score.roce_score = 3
        elif score.roce >= 0.08:
            score.roce_score = 1        # below threshold, some credit
        # < 8% → 0

    score.total = round(
        score.roe_score + score.margin_score + score.growth_score +
        score.debt_score + score.roce_score, 2
    )
    return score

def _compute_adx_atr(
    df: pd.DataFrame, period: int = 14
) -> tuple[Optional[float], Optional[float]]:
    """Return (atr, adx) using Wilder's smoothing (RMA). Returns (None,None) on insufficient data."""
    if df is None or len(df) < period * 3:
        return None, None
    try:
        high  = df["high"]
        low   = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        up_move   = high.diff()
        down_move = -low.diff()
        plus_dm  = np.where((up_move > down_move) & (up_move > 0),   up_move.values,   0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move.values, 0.0)
        alpha = 1.0 / period
        atr_s    = tr.ewm(alpha=alpha, adjust=False).mean()
        plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr_s
        minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr_s
        di_sum   = (plus_di + minus_di).replace(0, np.nan)
        dx  = (100 * (plus_di - minus_di).abs() / di_sum).fillna(0)
        adx = dx.ewm(alpha=alpha, adjust=False).mean()
        return round(float(atr_s.iloc[-1]), 4), round(float(adx.iloc[-1]), 2)
    except Exception:
        return None, None


def score_technicals(
    df: pd.DataFrame,
    nifty_series: Optional[pd.Series] = None,
    bb_period: int = 20,
    bb_std: float = 2.0,
    ema_period: int = 50,
    rsi_period: int = 14,
    vol_window: int = THRESHOLDS["vol_days"],  # ← 15-day avg (management rule)
    bw_lookback: int = 63,
    atr_min: float = THRESHOLDS["atr_min"],    # ← ATR > 25 filter
    adx_min: float = 25.0,                     # ADX > 25 minimum for trend strength
) -> TechnicalScore:
    score = TechnicalScore()
    if df is None or len(df) < 5:    # need at least 5 bars — was max(bb,ema,rsi)+5
        return score

    n      = len(df)           # actual available bars
    close  = df["close"]
    volume = df["volume"]

    # ── adaptive window: use the smaller of requested or available-5 ────────
    eff_bb  = min(bb_period, max(5, n - 5))
    eff_rsi = min(rsi_period, max(5, n - 5))
    eff_ema = min(ema_period, max(10, n - 5))
    rolling_mean = close.rolling(eff_bb).mean()
    rolling_std  = close.rolling(eff_bb).std()
    upper = rolling_mean + bb_std * rolling_std
    lower = rolling_mean - bb_std * rolling_std
    bandwidth = ((upper - lower) / rolling_mean * 100).dropna()

    # ── P1-A: BB breakout flag ────────────────────────────────────────────────
    score.upper_band  = round(float(upper.iloc[-1]), 2) if not upper.empty else None
    score.bb_breakout = bool(close.iloc[-1] > upper.iloc[-1]) if score.upper_band else False

    if len(bandwidth) >= bw_lookback:
        hist_bw    = bandwidth.iloc[-bw_lookback:]
        current_bw = bandwidth.iloc[-1]
        bw_min     = hist_bw.min()
        bw_max     = hist_bw.max()
        bw_range   = bw_max - bw_min
        if bw_range > 0:
            score.bandwidth_pct = round(((current_bw - bw_min) / bw_range) * 100, 1)
            # Breakout confirmed (close > upper) earns full pts; squeeze-only gets partial
            if score.bb_breakout:
                # Breakout + squeeze = maximum signal
                if score.bandwidth_pct <= 20:
                    score.bb_score = 25      # breakout from tight squeeze
                else:
                    score.bb_score = 18      # breakout from wider band
            else:
                # Squeeze only (coiling, not yet fired)
                if score.bandwidth_pct <= 10:
                    score.bb_score = 15
                elif score.bandwidth_pct <= 20:
                    score.bb_score = 12
                elif score.bandwidth_pct <= 35:
                    score.bb_score = 7
                elif score.bandwidth_pct <= 50:
                    score.bb_score = 3

    # ── Volume ratio: use actual vol_window or fall back to all available bars ──
    eff_vol = min(vol_window, max(3, n - 2))
    avg_vol = volume.rolling(eff_vol).mean()
    if len(avg_vol.dropna()) > 0 and avg_vol.iloc[-1] and avg_vol.iloc[-1] > 0:
        vol_ratio = volume.iloc[-1] / avg_vol.iloc[-1]
        score.vol_ratio = round(float(vol_ratio), 2)
        score.last_volume = int(volume.iloc[-1])   # ← raw volume for compact display
        if vol_ratio >= 3.0:
            score.volume_score = 15
        elif vol_ratio >= 2.0:
            score.volume_score = 12
        elif vol_ratio >= 1.5:
            score.volume_score = 8
        elif vol_ratio >= 1.0:
            score.volume_score = 4
        else:
            score.volume_score = 2   # below average, still show ratio
    else:
        # absolute fallback — normalise last volume vs 3-day median
        med3 = float(volume.iloc[-3:].median()) if n >= 3 else float(volume.iloc[-1])
        if med3 > 0:
            score.vol_ratio = round(float(volume.iloc[-1]) / med3, 2)
            score.last_volume = int(volume.iloc[-1])
            score.volume_score = 2

    if nifty_series is not None:
        combined = pd.DataFrame({"stock": close, "nifty": nifty_series}).dropna()
        if len(combined) >= 60:
            stock_ret = combined["stock"].iloc[-1] / combined["stock"].iloc[-60] - 1
            nifty_ret = combined["nifty"].iloc[-1] / combined["nifty"].iloc[-60] - 1
            rs = (1 + stock_ret) / (1 + nifty_ret) if (1 + nifty_ret) != 0 else 1
            score.rs_ratio = round(float(rs), 3)
            if rs >= 1.30:
                score.rs_score = 15
            elif rs >= 1.15:
                score.rs_score = 12
            elif rs >= 1.05:
                score.rs_score = 8
            elif rs >= 0.95:
                score.rs_score = 4
    else:
        score.rs_score = 7

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(eff_rsi).mean()
    loss = (-delta.clip(upper=0)).rolling(eff_rsi).mean()
    rs_value = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs_value))
    # Use last non-NaN value as fallback
    rsi_val = rsi_series.dropna().iloc[-1] if not rsi_series.dropna().empty else 50.0
    score.rsi = round(float(rsi_val), 1)

    if 55 <= score.rsi <= 68:
        score.rsi_score = 10
    elif 50 <= score.rsi < 55:
        score.rsi_score = 7
    elif 68 < score.rsi <= 75:
        score.rsi_score = 5
    elif 40 <= score.rsi < 50:
        score.rsi_score = 3

    ema50  = close.ewm(span=eff_ema, adjust=False).mean()
    ema200 = close.ewm(span=min(200, max(20, n - 2)), adjust=False).mean()
    score.above_ema50  = bool(close.iloc[-1] > ema50.iloc[-1])
    score.above_ema200 = bool(close.iloc[-1] > ema200.iloc[-1])
    score.golden_cross = bool(ema50.iloc[-1] > ema200.iloc[-1])
    score.close = round(float(close.iloc[-1]), 2)

    if not score.above_ema50:
        score.bb_score = max(0, score.bb_score - 5)

    # ── ADX(14) + ATR(14) ────────────────────────────────────────────────────
    atr_val, adx_val = _compute_adx_atr(df, period=14)
    score.atr = atr_val
    score.adx = adx_val
    if adx_val is not None:
        # Management rule: ADX > 25 = trending market (institutional interest)
        if adx_val >= 35:
            score.adx_score = 8        # strong trend
        elif adx_val >= adx_min:       # >= 25 — passes management threshold
            score.adx_score = 5
        elif adx_val >= 20:
            score.adx_score = 2        # weak trend — below threshold
        # < 20 → 0 (no trend / sideways)

    if atr_val is not None:
        score.stop_loss = round(score.close - 1.5 * atr_val, 2)
        # Management rule: ATR > 25 required (stock must have meaningful move range)
        if atr_val < atr_min:
            # Penalise bb_score for low-volatility stocks that can't make meaningful moves
            score.bb_score = max(0, score.bb_score - 5)

    score.total = round(
        score.bb_score + score.volume_score + score.rs_score + score.rsi_score + score.adx_score, 2
    )
    return score


SECTOR_RANKS = {
    "Capital Goods": 1,
    "Banking & Finance": 2,
    "Pharma": 3,
    "IT": 4,
    "Auto / Consumer": 5,
    "FMCG / Consumer": 6,
    "Power": 7,
    "Oil & Gas": 7,
    "Metals": 8,
    "Realty": 9,
    "Media & Telecom": 10,
    "PSU": 10
}


def score_sector(sector: str) -> SectorScore:
    score = SectorScore(sector=sector)
    for key, rank in SECTOR_RANKS.items():
        if key.lower() in sector.lower():
            score.sector_rank = rank
            score.sector_score = max(0, 5 - (rank - 1))
            return score
    score.sector_rank = 10
    score.sector_score = 1
    return score


def grade(score: float) -> tuple[str, str]:
    if score >= 80:
        return "A+", "Strong Buy"
    if score >= 70:
        return "A", "Buy"
    if score >= 60:
        return "B", "Watch"
    if score >= 45:
        return "C", "Neutral"
    return "D", "Skip"


def build_composite_score(
    ticker: str,
    fund_data: dict,
    price_df: Optional[pd.DataFrame] = None,
    nifty_data: Optional[pd.Series] = None,
) -> CompositeScore:
    result = CompositeScore(ticker=ticker.upper())

    if fund_data is None:
        result.error = "Fundamental fetch failed"
        return result

    from astro_engine import normalize_sector, calculate_astro_score
    result.name = fund_data.get("General", {}).get("Name", ticker)
    raw_sector = fund_data.get("General", {}).get("Sector", "")
    result.sector = normalize_sector(raw_sector, result.ticker)
    result.fundamental = score_fundamentals(fund_data)

    if price_df is not None:
        result.technical = score_technicals(price_df, nifty_series=nifty_data)
    else:
        result.error = "Price fetch failed"

    result.sector_sc = score_sector(result.sector)
    
    # ── Astrological Power Integration (pure-additive) ─────────────────────
    try:
        astro_data = calculate_astro_score(result.sector, ticker=result.ticker)
        result.astro_sc = AstroScore(
            astro_score=astro_data["score"],
            ruling_planets=astro_data["ruling_planets"],
            transit_status=astro_data["transit_status"]
        )
    except Exception as exc:
        log.warning("Could not calculate astro score for %s: %s", result.ticker, exc)
        result.astro_sc = AstroScore(astro_score=3.0, ruling_planets="Jup", transit_status="Neutral")
        
    result.total = round(
        min(100, max(0, result.fundamental.total + result.technical.total + result.sector_sc.sector_score + result.astro_sc.astro_score)),
        1,
    )
    result.grade, result.signal = grade(result.total)
    return result


def score_stock(
    ticker: str,
    api_key: str = "",
    nifty_data: Optional[pd.Series] = None,
    rate_limit: float = 0.5,
) -> CompositeScore:
    result = CompositeScore(ticker=ticker.upper())

    log.info("  %s: fetching fundamentals ...", ticker)
    fund_data = fetch_fundamentals(ticker, api_key)
    time.sleep(rate_limit)
    if fund_data is None:
        result.error = "Fundamental fetch failed"
        return result

    log.info("  %s: fetching price data ...", ticker)
    price_df = fetch_price_data(ticker, api_key)
    time.sleep(rate_limit)

    return build_composite_score(
        ticker=ticker,
        fund_data=fund_data,
        price_df=price_df,
        nifty_data=nifty_data,
    )


def run_batch_screener(
    tickers: list[str],
    api_key: str = "",
    min_score: float = 0.0,
    rate_limit: float = 0.5,
    progress_callback=None,   # callable(done: int, total: int) | None
) -> pd.DataFrame:
    log.info("Fetching Nifty 50 data for relative strength ...")
    nifty_df = fetch_price_data(NIFTY_INDEX_SYMBOL, api_key, period=180)
    nifty_series = nifty_df["close"] if nifty_df is not None else None
    time.sleep(0.5)

    results = []
    for index, ticker in enumerate(tickers, 1):
        # Skip tickers known to be permanently broken in yfinance
        normalized = _normalize_ticker(ticker)
        if normalized in _SKIP_SYMBOLS:
            log.warning("  %s: in _SKIP_SYMBOLS — skipping (no yfinance data available)", ticker)
            if progress_callback:
                try: progress_callback(index, len(tickers))
                except Exception: pass
            continue

        log.info("[%s/%s] Scoring %s ...", index, len(tickers), ticker)
        if progress_callback:
            try:
                progress_callback(index, len(tickers))
            except Exception:
                pass
        try:
            results.append(score_stock(ticker, api_key, nifty_data=nifty_series, rate_limit=rate_limit))
        except Exception as exc:
            log.error("  %s error: %s", ticker, exc)

    rows = []
    for result in results:
        fund = result.fundamental
        tech = result.technical
        rows.append(
            {
                "ticker":        result.ticker,
                "name":          result.name,
                "sector":        result.sector,
                "total_score":   result.total,
                "grade":         result.grade,
                "signal":        result.signal,
                "fund_score":    fund.total,
                "tech_score":    tech.total,
                "sector_score":  result.sector_sc.sector_score,
                # ── Fundamental metrics with management thresholds ────────────
                "roe_pct":       round(fund.roe * 100, 1) if fund.roe is not None else None,
                "roce_pct":      round(fund.roce * 100, 1) if fund.roce is not None else None,
                "eps":           round(fund.eps, 2) if fund.eps is not None else None,
                "profit_margin": round(fund.profit_margin * 100, 1) if fund.profit_margin else None,
                "rev_growth":    round(fund.rev_growth * 100, 1) if fund.rev_growth else None,
                "eps_growth":    round(fund.eps_growth * 100, 1) if fund.eps_growth else None,
                "debt_equity":   round(fund.debt_equity, 2) if fund.debt_equity is not None else None,
                "passes_filter": fund.passes_filter,  # False if D/E > 0.5 or EPS ≤ 0
                # ── Technical metrics ─────────────────────────────────────────
                "bb_squeeze_pct": tech.bandwidth_pct,
                "bb_breakout":    tech.bb_breakout,
                "upper_band":     tech.upper_band,
                "volume_ratio":   tech.vol_ratio,
                "last_volume":    tech.last_volume,   # raw vol for K/L/Cr display
                "rs_vs_nifty":    tech.rs_ratio,
                "rsi":            tech.rsi,
                "adx":            tech.adx,
                "atr":            tech.atr,
                "atr_ok":         (tech.atr or 0) >= THRESHOLDS["atr_min"],  # ATR > 25 check
                "above_ema50":    tech.above_ema50,
                "above_ema200":   tech.above_ema200,
                "golden_cross":   tech.golden_cross,
                "stop_loss":      tech.stop_loss,
                "close":          tech.close,
                "delivery_pct":   tech.delivery_pct,
                "pcr":            tech.pcr,
                "oi_signal":      tech.oi_signal,
                "error":          result.error,
                # Data quality flag: False means no price data at all
                "has_price_data": tech.close is not None,
                "astro_score":    result.astro_sc.astro_score if result.astro_sc else 3.0,
                "ruling_planets": result.astro_sc.ruling_planets if result.astro_sc else "Jup",
                "transit_status": result.astro_sc.transit_status if result.astro_sc else "Neutral",
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # ── Remove ghost rows: stocks where ALL technical metrics are null ──
    # These contribute nothing except noise (score=3-4, all N/A columns).
    # A row is considered "data-empty" when close, rsi, adx AND atr are all null.
    tech_cols = ["close", "rsi", "adx", "atr"]
    data_empty = df[[c for c in tech_cols if c in df.columns]].isnull().all(axis=1)
    n_before = len(df)
    df = df[~data_empty].copy()
    if len(df) < n_before:
        log.info("Filtered %d ghost rows (no price data) from screener output.", n_before - len(df))

    return (
        df[df["total_score"] >= min_score]
        .sort_values(["total_score", "fund_score"], ascending=False)
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scoring_engine.py <TICKER> [TICKER2 ...]")
        sys.exit(1)

    tickers = sys.argv[1:]

    if len(tickers) == 1:
        score = score_stock(tickers[0])
        print(json.dumps(score.to_dict(), indent=2, default=str))
    else:
        frame = run_batch_screener(tickers, min_score=0)
        cols = ["ticker", "total_score", "grade", "signal", "fund_score", "tech_score", "bb_squeeze_pct", "rsi", "rs_vs_nifty"]
        print(frame[cols].to_string(index=False))
        frame.to_csv("screener_results.csv", index=False)
        print("\nSaved -> screener_results.csv")
