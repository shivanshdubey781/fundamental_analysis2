"""
sectoral_analysis.py — Flask Blueprint for Sector-Level Analysis
================================================================
Pure-additive module. Register in main.py with:

    from sectoral_analysis import sector_bp
    app.register_blueprint(sector_bp)

Endpoints exposed:
  GET /api/sectors/summary      — per-sector aggregated metrics from last screener run
  GET /api/sectors/top-picks    — top 3 stocks per sector by composite score
  GET /api/sectors/nse-indices  — live NSE sector index % change (best-effort)
"""

from __future__ import annotations

import logging
from collections import defaultdict

import requests
from flask import Blueprint, jsonify

log = logging.getLogger(__name__)

sector_bp = Blueprint("sectors", __name__)

# ---------------------------------------------------------------------------
# NSE sector index symbol → display name mapping
# ---------------------------------------------------------------------------
NSE_INDEX_NAMES: dict[str, str] = {
    "NIFTY IT":            "IT",
    "Nifty Bank":          "Bank",
    "NIFTY PHARMA":        "Pharma",
    "Nifty Auto":          "Auto",
    "Nifty FMCG":          "FMCG",
    "Nifty Metal":         "Metal",
    "Nifty Energy":        "Energy",
    "NIFTY REALTY":        "Realty",
    "Nifty Infra":         "Infra",
    "Nifty Financial Services": "Financials",
    "Nifty Healthcare Index":   "Healthcare",
    "Nifty Media":         "Media",
    "Nifty PSU Bank":      "PSU Bank",
    "Nifty Private Bank":  "Pvt Bank",
    "Nifty Oil & Gas":     "Oil & Gas",
    "Nifty Consumer Durables": "Cons. Dur.",
    "Nifty Capital Markets":   "Cap. Mkts",
    "Nifty Defence":       "Defence",
}

# ---------------------------------------------------------------------------
# User-friendly display names for yfinance sector strings
# Matches the user's reference table (image) as closely as possible
# ---------------------------------------------------------------------------
SECTOR_DISPLAY_NAMES: dict[str, str] = {
    "Auto / Consumer": "Auto / Consumer",
    "FMCG / Consumer": "FMCG / Consumer",
    "Pharma": "Pharma",
    "Media & Telecom": "Media & Telecom",
    "Metals": "Metals",
    "Banking & Finance": "Banking & Finance",
    "PSU": "PSU",
    "Oil & Gas": "Oil & Gas",
    "IT": "IT",
    "Realty": "Realty",
    "Capital Goods": "Capital Goods",
    "Power": "Power"
}

# ---------------------------------------------------------------------------
# PSU: Government-owned enterprises → ruled by Sun
# ---------------------------------------------------------------------------
PSU_TICKERS = {
    "HUDCO", "IRFC", "RVNL", "IRCON", "NBCC",
    "BEL", "HAL", "BHEL", "SAIL", "NMDC", "NATIONALUM", "HINDCOPPER",
    "COALINDIA", "ONGC", "BPCL", "NTPC", "POWERGRID", "SJVN", "NHPC", "PFC", "REC", "RECLTD", "IOC", "HPCL"
}

# Power: Private power generation/distribution companies
POWER_TICKERS = {
    "ADANIGREEN", "ADANIENSOL", "ADANIPOWER", "JSWENERGY", "CESC", "TATAPOWER",
    "TORNTPOWER", "SUZLON", "GAIL", "IGL", "MGL", "ATGL", "PETRONET",
    "GSPL",
}


# ---------------------------------------------------------------------------
# Reference to main._bg — injected by main.py at startup via set_bg_ref()
# This avoids circular imports entirely.
# ---------------------------------------------------------------------------

_bg_ref: dict | None = None


def set_bg_ref(bg: dict) -> None:
    """
    Called once by main.py after creating _bg:

        from sectoral_analysis import sector_bp, set_bg_ref
        set_bg_ref(_bg)
        app.register_blueprint(sector_bp)
    """
    global _bg_ref
    _bg_ref = bg
    log.info("[sectors] _bg reference injected — sector endpoints are live")


def _get_sector_data_and_status() -> tuple[list[dict], dict]:
    """
    Returns the screener results and status to use for sectoral analysis.
    To keep the Sector Intelligence comprehensive, we prefer the broadest
    available scan report of today/yesterday (>= 150 stocks).
    
    1. If the screener is currently running, return that status (so the UI shows loading).
    2. If the active in-memory cache has >= 150 stocks, use it.
    3. Otherwise, search the reports/ directory on disk for the largest CSV report.
    4. If one is found, load it.
    5. Otherwise, fall back to the active in-memory cache.
    """
    if _bg_ref is None:
        log.warning("[sectors] _bg_ref not set — call set_bg_ref(_bg) in main.py")
        return [], {}

    # 1. If currently running, let the frontend know
    if _bg_ref.get("running", False):
        return [], {
            "running":     True,
            "finished_at": None,
            "index":       _bg_ref.get("index", ""),
        }

    # 2. If in-memory cache is broad enough, use it
    in_mem_results = _bg_ref.get("results", [])
    if len(in_mem_results) >= 150:
        return in_mem_results, {
            "running":     False,
            "finished_at": _bg_ref.get("finished_at"),
            "index":       _bg_ref.get("index", ""),
        }

    # 3. Fallback: Search reports/ directory on disk for the newest broad scan report (>= 150 rows)
    from pathlib import Path
    import pandas as pd
    import math
    import pytz
    from datetime import datetime

    ist = pytz.timezone("Asia/Kolkata")
    root = Path(__file__).resolve().parent
    reports_dir = root / "reports"

    if reports_dir.exists():
        csv_files = list(reports_dir.glob("*.csv"))
        if csv_files:
            # Sort files by modification time descending (newest first)
            sorted_files = sorted(csv_files, key=lambda p: p.stat().st_mtime, reverse=True)
            for f in sorted_files:
                try:
                    df = pd.read_csv(f)
                    if not df.empty and len(df) >= 150:
                        records = df.to_dict(orient="records")
                        # Replace float NaN/Inf with None for JSON compliance
                        for r in records:
                            for k, v in list(r.items()):
                                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                                    r[k] = None
                        
                        mtime = f.stat().st_mtime
                        finished_at = datetime.fromtimestamp(mtime, tz=ist).isoformat()
                        
                        # Try to infer index from file columns/metadata
                        index_name = "nifty500_custom"
                        if "index_name" in df.columns:
                            non_null_idx = df["index_name"].dropna()
                            if not non_null_idx.empty:
                                index_name = str(non_null_idx.iloc[0])

                        log.info("[sectors] Loaded fallback broad report: %s (%d rows)", f.name, len(df))
                        return records, {
                            "running":     False,
                            "finished_at": finished_at,
                            "index":       index_name,
                        }
                except Exception as e:
                    log.warning("[sectors] Failed to read report %s: %s", f.name, e)

    # 5. Default fallback to active in-memory cache
    return in_mem_results, {
        "running":     False,
        "finished_at": _bg_ref.get("finished_at"),
        "index":       _bg_ref.get("index", ""),
    }


def build_sector_summary(screener_results: list[dict]) -> list[dict]:
    """
    Group screener results by sector and compute aggregated metrics.
    Reclassifies certain tickers into virtual sectors (PSU, Power)
    to separate government-owned PSUs from private power companies.

    Returns a list of dicts sorted by avg_score descending.
    """
    buckets: dict[str, list[dict]] = {
        "Auto / Consumer": [],
        "FMCG / Consumer": [],
        "Pharma": [],
        "Media & Telecom": [],
        "Metals": [],
        "Banking & Finance": [],
        "PSU": [],
        "Oil & Gas": [],
        "IT": [],
        "Realty": [],
        "Capital Goods": [],
        "Power": []
    }
    for row in screener_results:
        raw_sector = (row.get("sector") or "Other").strip()
        ticker = (row.get("ticker") or "").upper().strip()

        # Use unified normalization from astro_engine
        from astro_engine import normalize_sector
        sector = normalize_sector(raw_sector, ticker)

        if sector not in buckets:
            buckets[sector] = []
        buckets[sector].append(row)

    summary: list[dict] = []
    for sector, stocks in buckets.items():
        scores   = [s["total_score"]   for s in stocks if s.get("total_score")   is not None]
        rsi_vals = [s["rsi"]           for s in stocks if s.get("rsi")           is not None]
        rs_vals  = [s["rs_vs_nifty"]   for s in stocks if s.get("rs_vs_nifty")  is not None]

        avg = round(sum(scores) / len(scores), 1) if scores else 0.0

        # top 3 picks by score
        ranked = sorted(stocks, key=lambda x: x.get("total_score") or 0, reverse=True)

        # Astrological calculations (pure-additive)
        try:
            from astro_engine import calculate_astro_score
            astro = calculate_astro_score(sector)
            ruling_planets = astro["ruling_planets"]
            astro_status   = astro["transit_status"]
            astro_score    = astro["score"]
        except Exception:
            ruling_planets = "Jup"
            astro_status   = "Neutral"
            astro_score    = 3.0

        summary.append({
            "sector":        sector,
            "display_name":  SECTOR_DISPLAY_NAMES.get(sector, sector),  # user-friendly name
            "stock_count":   len(stocks),
            "avg_score":     avg,
            "bullish_count": sum(1 for s in scores if s >= 70),
            "weak_count":    sum(1 for s in scores if s < 50),
            "top_stock":     ranked[0]["ticker"] if ranked else None,
            "top3":          [
                {
                    "ticker": s.get("ticker"),
                    "score":  s.get("total_score"),
                    "signal": s.get("signal", ""),
                    "grade":  s.get("grade", ""),
                    "rsi":    s.get("rsi"),
                }
                for s in ranked[:3]
            ],
            "avg_rsi":       round(sum(rsi_vals) / len(rsi_vals), 1) if rsi_vals else None,
            "avg_rs_nifty":  round(sum(rs_vals)  / len(rs_vals),  3) if rs_vals  else None,
            "ruling_planets": ruling_planets,
            "astro_status":   astro_status,
            "astro_score":    astro_score,
            "momentum":      (
                "STRONG"   if avg >= 65 else
                "MODERATE" if avg >= 50 else
                "WEAK"
            ),
        })

    return sorted(summary, key=lambda x: x["avg_score"], reverse=True)


# ---------------------------------------------------------------------------
# NSE live sector index fetch
# ---------------------------------------------------------------------------

_NSE_SESSION: requests.Session | None = None


def _get_nse_session() -> requests.Session:
    """Reuse a long-lived NSE session. Creates one if needed."""
    global _NSE_SESSION
    if _NSE_SESSION is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer":         "https://www.nseindia.com/",
        })
        # Warm up session cookie
        try:
            s.get("https://www.nseindia.com", timeout=8)
        except Exception:
            pass
        _NSE_SESSION = s
    return _NSE_SESSION


def fetch_nse_index_performance() -> list[dict]:
    """
    Fetch live % change for NSE sector indices from NSE allIndices API.
    Returns a list of {name, display_name, pct_change, last_price}.
    Falls back to [] on any error.
    """
    try:
        session = _get_nse_session()
        resp = session.get(
            "https://www.nseindia.com/api/allIndices",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        indices_raw = data.get("data", [])

        result: list[dict] = []
        for idx in indices_raw:
            name = idx.get("index", "")
            if name not in NSE_INDEX_NAMES:
                continue
            try:
                pct = float(idx.get("percentChange", 0))
                last = float(idx.get("last", 0))
                result.append({
                    "index":        name,
                    "display_name": NSE_INDEX_NAMES[name],
                    "pct_change":   round(pct, 2),
                    "last_price":   round(last, 2),
                })
            except (TypeError, ValueError):
                continue

        return sorted(result, key=lambda x: x["pct_change"], reverse=True)

    except Exception as exc:
        log.warning("[sectors] NSE index fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Flask Blueprint routes
# ---------------------------------------------------------------------------

@sector_bp.route("/api/sectors/summary")
def api_sectors_summary():
    """
    Aggregate the last screener run results by sector.
    Returns sector-level metrics: avg_score, momentum, bullish_count, top pick.
    """
    results, status = _get_sector_data_and_status()

    if status.get("running"):
        return jsonify({
            "ok":      False,
            "message": "Screener is currently running — please wait and refresh.",
            "sectors": [],
            "running": True,
        })

    if not results:
        return jsonify({
            "ok":      False,
            "message": "No screener results yet. Run the screener first (\u26a1 RUN button), then refresh.",
            "sectors": [],
            "running": False,
        })

    summary = build_sector_summary(results)
    return jsonify({
        "ok":           True,
        "total_stocks": len(results),
        "finished_at":  status.get("finished_at"),
        "index":        status.get("index", ""),
        "sectors":      summary,
    })


@sector_bp.route("/api/sectors/top-picks")
def api_sectors_top_picks():
    """
    Return the top 3 stocks per sector from the last screener run.
    """
    results, status = _get_sector_data_and_status()
    if not results:
        return jsonify({
            "ok":      False,
            "message": "No screener results yet.",
            "picks":   {},
        })

    summary = build_sector_summary(results)
    picks = {s["sector"]: s["top3"] for s in summary}
    return jsonify({"ok": True, "picks": picks})


@sector_bp.route("/api/sectors/nse-indices")
def api_sectors_nse_indices():
    """
    Fetch and return live % change for NSE sector indices.
    Best-effort — returns empty list with ok=False if NSE is unreachable.
    """
    indices = fetch_nse_index_performance()
    return jsonify({
        "ok":      bool(indices),
        "indices": indices,
    })
