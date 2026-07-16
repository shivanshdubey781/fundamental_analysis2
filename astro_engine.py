"""
astro_engine.py — Astrological Planet Data Parser & Scorer
=========================================================
Query planetary transit CSV data from planet_downloader/data
and compute real-time Astro scores and alignments for sectors and stocks.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
import pandas as pd

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTOR → RULING PLANET MAP
# ───────────────────────────────────────────────────────────────────────────────
# Source of truth: user's reference table (image) — EXACT 12-sector list:
#
#   Sector              | Ruling Planet(s)
#   ─────────────────────────────────────
#   Auto                | Mar
#   Pharma              | Mer
#   Media               | Mer
#   Entertainment       | Mer/Ven
#   Metals              | Rah/Sat
#   Banking             | Jup
#   PSU                 | Sun
#   Consumer Durables   | Ven
#   Hotel               | Ven
#   Oil and Gas         | Rah/Sat
#   IT                  | Sun
#   Realty              | Mar
#
# RULE: Each sector maps to EXACTLY the planet(s) shown above.
#        No sector borrows another sector's planet.
#        Broad yfinance tags are NOT used — ticker-level overrides handle edge cases.
# ═══════════════════════════════════════════════════════════════════════════════

SECTOR_PLANET_MAP: dict[str, list[str]] = {
    "Auto / Consumer":            ["Venus"],
    "FMCG / Consumer":            ["Venus"],
    "Pharma":                     ["Mercury"],
    "Media & Telecom":            ["Mercury"],
    "Metals":                     ["Rahu", "Saturn"],
    "Banking & Finance":          ["Jupiter"],
    "PSU":                        ["Sun"],
    "Oil & Gas":                  ["Rahu", "Saturn"],
    "IT":                         ["Sun"],
    "Realty":                     ["Mars"],
    "Capital Goods":              ["Rahu", "Saturn"],
    "Power":                      ["Rahu", "Saturn"],
}

# Displays exact planet significators requested by the user
SECTOR_SIGNIFICATOR_MAP: dict[str, str] = {
    "Auto / Consumer": "ven",
    "FMCG / Consumer": "ven",
    "Pharma": "Mer",
    "Media & Telecom": "Mer",
    "Metals": "Rah/sat",
    "Banking & Finance": "Jup",
    "PSU": "Sun",
    "Oil & Gas": "Rah/sat",
    "IT": "Sun",
    "Realty": "Mar",
    "Capital Goods": "Rah/sat",
    "Power": "Rah/sat",
}

def normalize_sector(raw_sector: str, ticker: str = "") -> str:
    ticker = (ticker or "").upper().strip()
    
    # 1. Try single source of truth STOCK_SECTOR from config
    import config
    if hasattr(config, "STOCK_SECTOR") and ticker in config.STOCK_SECTOR:
        return config.STOCK_SECTOR[ticker]

    # 2. Fallback logic for custom/unseen tickers
    raw = (raw_sector or "").strip().lower()
    
    if "psu" in raw:
        return "PSU"
    if "pharma" in raw or "health" in raw or "biotech" in raw or "drug" in raw:
        return "Pharma"
    if "auto" in raw or "veh" in raw or raw == "car" or "car components" in raw or "automobile" in raw:
        return "Auto / Consumer"
    if "media" in raw or "telecom" in raw or "communication" in raw or "broadcast" in raw or "publish" in raw or "entertainment" in raw or "leisure" in raw or "theatre" in raw or "cinema" in raw:
        return "Media & Telecom"
    if "real estate" in raw or "realty" in raw or "property" in raw:
        return "Realty"
    if any(k in raw for k in ["metal", "steel", "mining", "aluminum", "copper", "iron", "basic", "material", "cement"]):
        return "Metals"
    if any(k in raw for k in ["oil", "gas", "petroleum", "coal"]):
        return "Oil & Gas"
    if any(k in raw for k in ["utility", "utilities", "power", "energy"]):
        return "Power"
    if any(k in raw for k in ["technology", "software", "hardware", "internet", "semiconductor"]) or raw == "it":
        return "IT"
    if any(k in raw for k in ["bank", "finan", "insur", "nbfc", "capital market", "securities", "broker", "wealth"]):
        return "Banking & Finance"
    if any(k in raw for k in ["consumer", "fmcg", "retail", "staple", "apparel", "textile", "fashion", "luxury", "beverage", "food", "tobacco", "personal", "household", "agro", "agriculture", "hotel", "resort", "tourism", "hospitality", "aviation", "airline", "travel", "restaurant"]):
        return "FMCG / Consumer"
        
    return "Capital Goods"


# Directory containing planetary CSVs (relative to this file)
DATA_DIR = Path(__file__).resolve().parent.parent / "planet_downloader" / "data"


def get_planet_transit_status(planet: str, target_date: datetime | None = None) -> dict:
    """
    Find the closest row in {planet}_report.csv that is <= target_date.
    Returns a dict with transit info (status, rashi, nakshatra, etc.).
    """
    if target_date is None:
        target_date = datetime.now()
        
    filename = f"{planet.lower()}_report.csv"
    file_path = DATA_DIR / filename
    
    # Default neutral fallback if file is missing or error occurs
    fallback = {
        "planet": planet,
        "status": "Neutral",
        "rashi": "Unknown",
        "nakshatra": "Unknown",
        "final_ud": "Neutral",
        "error": None
    }
    
    if not file_path.exists():
        fallback["error"] = f"File {file_path.name} not found"
        return fallback
        
    try:
        df = pd.read_csv(file_path)
        if df.empty or 'datetime' not in df.columns:
            fallback["error"] = "CSV is empty or missing datetime column"
            return fallback
            
        # Parse datetime column robustly with flexible format support (handles Excel-saved formats)
        df['parsed_dt'] = pd.to_datetime(df['datetime'], errors='coerce')
        df = df.dropna(subset=['parsed_dt'])
        
        # Sort by datetime to ensure proper lookup
        df = df.sort_values('parsed_dt')
        
        target_date_only = target_date.date()
        df['date_only'] = df['parsed_dt'].dt.date
        
        today_rows = df[df['date_only'] == target_date_only]
        if not today_rows.empty:
            # Use the first reading of the day to define the daily status, matching user expectations
            row = today_rows.iloc[0]
        else:
            # Find rows prior to or equal to target_date
            past_rows = df[df['parsed_dt'] <= target_date]
            if past_rows.empty:
                # Fallback to the first available row if target_date is earlier than CSV start
                row = df.iloc[0]
            else:
                row = past_rows.iloc[-1]
            
        final_ud = str(row.get('final U/D', 'Neutral')).strip()
        
        return {
            "planet":       planet,
            "status":       final_ud,
            "rashi":        row.get('rashi', 'Unknown'),
            "nakshatra":    row.get('nakshatra', 'Unknown'),
            "final_ud":     final_ud,
            "error":        None
        }
        
    except Exception as e:
        log.warning("Error parsing astro CSV for %s: %s", planet, e)
        fallback["error"] = str(e)
        return fallback


def calculate_astro_score(sector: str, target_date: datetime | None = None, ticker: str = "") -> dict:
    """
    Get the ruling planet(s) for a sector, retrieve their transit status,
    and compute a composite Astro Score (1 to 5).
    
    Returns a dict with:
      - score: float (1.0 to 5.0)
      - ruling_planets: str (e.g. "Mars" or "Rahu/Saturn")
      - transit_status: str ("Upside" / "Neutral" / "Downside")
      - details: list of dicts (per-planet info)
    """
    norm_sector = normalize_sector(sector, ticker)
    planets = SECTOR_PLANET_MAP.get(norm_sector, ["Jupiter"])
        
    details = []
    scores = []
    
    for p in planets:
        status = get_planet_transit_status(p, target_date)
        details.append(status)
        
        # Map transit status to numeric sub-score
        # Upside -> 5.0, Neutral -> 3.0, Downside -> 1.0
        ud = status["final_ud"].lower()
        if "upside" in ud:
            scores.append(5.0)
        elif "downside" in ud:
            scores.append(1.0)
        else:
            scores.append(3.0)
            
    # Average the scores of all ruling planets (e.g. Rahu + Saturn)
    avg_score = round(sum(scores) / len(scores), 1) if scores else 3.0
    
    # Determine the composite transit status label
    if avg_score >= 4.0:
        composite_status = "Upside"
    elif avg_score <= 2.0:
        composite_status = "Downside"
    else:
        composite_status = "Neutral"
        
    # Get exact user-defined significator string for display
    ruling_str = SECTOR_SIGNIFICATOR_MAP.get(norm_sector, "Jup")
    
    return {
        "score":          avg_score,
        "ruling_planets": ruling_str,
        "transit_status": composite_status,
        "details":        details
    }
