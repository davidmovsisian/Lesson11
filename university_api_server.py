"""
University Context API Server
==============================
A Flask server that enriches university data with real-time city and country
information from two free public APIs:

  - WhereNext API  (https://getwherenext.com/api/data)  — country cost of living,
                                                           relocation index, salaries
  - World Bank API (https://api.worldbank.org/v2)        — country economic indicators

NOTE: The original Teleport API (api.teleport.org) is permanently offline as of 2026.
      WhereNext is the best free replacement: no API key, CC BY 4.0, 95 countries.
      WhereNext data is country-level (not city-level). For city-level cost data,
      the /api/data/city-prices endpoint covers 50+ major cities.

Run:
    pip install flask flask-cors requests
    python university_api_server.py

Then open: http://localhost:5000/
"""

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

WHERENEXT_BASE = "https://getwherenext.com/api/data"
WORLDBANK_BASE = "https://api.worldbank.org/v2"

TIMEOUT = 8  # seconds for upstream requests

# WhereNext datasets cached at startup to avoid repeated fetches.
# These are bulk endpoints (entire dataset in one call) so we fetch once
# and filter in-memory by country ISO-2 code or city name.
_wn_cache: dict = {}


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def wherenext_get(endpoint: str) -> list | dict:
    """
    Fetch a WhereNext bulk dataset, caching the result in memory.
    WhereNext returns the full dataset in one call — we cache it so
    repeated /enrich calls don't re-fetch the same data.
    """
    if endpoint not in _wn_cache:
        url = f"{WHERENEXT_BASE}/{endpoint}"
        print(f"[wherenext_get] Fetching {url}")
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        _wn_cache[endpoint] = resp.json()
    return _wn_cache[endpoint]


def wherenext_find_country(dataset: list, iso2: str) -> dict | None:
    """
    Find a country row in a WhereNext dataset by ISO-2 code.
    WhereNext uses 'iso2' or 'country_code' as the key depending on dataset.
    """
    iso2 = iso2.upper()
    for row in dataset:
        code = (row.get("iso2") or row.get("country_code") or "").upper()
        if code == iso2:
            return row
    return None


def wherenext_find_city(dataset: list, city_name: str) -> dict | None:
    """Find a city row in a WhereNext dataset by case-insensitive city name."""
    city_lower = city_name.lower()
    # Exact match first
    for row in dataset:
        if row.get("city", "").lower() == city_lower:
            return row
    # Partial match fallback
    for row in dataset:
        if city_lower in row.get("city", "").lower():
            return row
    return None


def worldbank_get(path: str, **kwargs):
    """GET a World Bank endpoint (JSON format forced) and return the data array."""
    url = f"{WORLDBANK_BASE}{path}"
    print(f"[worldbank_get] Fetching {url} with params: {kwargs.get('params', {})}")
    params = kwargs.pop("params", {})
    params["format"] = "json"
    resp = requests.get(url, params=params, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    payload = resp.json()
    # World Bank returns [metadata, data_array]
    if isinstance(payload, list) and len(payload) == 2:
        return payload[1]
    return payload


def error(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# ──────────────────────────────────────────────
#  Root — API index
# ──────────────────────────────────────────────

@app.route("/")
def index():
    """
    GET /
    -----
    Returns a directory of all available endpoints.
    """
    return jsonify({"message": "University Context Server"})

# ──────────────────────────────────────────────
#  Combined /enrich endpoint
# ──────────────────────────────────────────────

@app.route("/enrich")
def enrich():
    """
    GET /enrich?city=<name>&country=<iso2>[&year=<year>]
    ------------------------------------------------------
    One-shot enrichment for a university record from the THE dataset.

    Combines WhereNext cost-of-living and relocation data (country level,
    with city-level prices where available) with three World Bank indicators.
    Partial results are returned gracefully if a source has no data for the
    given country or city.

    Query params:
        city    (str, required) — city where the university is located
        country (str, required) — ISO-2 country code (e.g. 'GB')
        year    (str, optional) — World Bank year or range (default: '2023')

    Returns:
        {
          "city": "Oxford", "country": "GB", "year": "2023",
          "wherenext": {
            "cost_of_living": { "index": 72, "monthly_usd": 2800, ... },
            "relocation_index": { "overall": 74, "safety": 81, ... },
            "city_prices": { "rent_1br_city_usd": 1800, ... } | null
          },
          "worldbank": {
            "gdp_per_capita": { "value": 46125, "unit": "current USD" },
            "unemployment":   { "value": 4.1,   "unit": "% of labour force" },
            "rd_expenditure": { "value": 2.93,  "unit": "% of GDP" }
          }
        }
    """
    city    = request.args.get("city", "").strip()
    country = request.args.get("country", "").strip().upper()
    year    = request.args.get("year", "2023").strip()

    if not city:
        return error("'city' query parameter is required")
    if not country:
        return error("'country' query parameter is required (ISO-2 code)")

    result = {"city": city, "country": country, "year": year}

    # ── WhereNext ─────────────────────────────
    wn = {}
    try:
        col_rows = wherenext_get("cost-of-living")
        col_rows = col_rows if isinstance(col_rows, list) else col_rows.get("data", [])
        col_row  = wherenext_find_country(col_rows, country)
        wn["cost_of_living"] = col_row or {"note": f"No WhereNext cost data for '{country}'"}
    except Exception as exc:
        wn["cost_of_living"] = {"error": str(exc)}

    try:
        rel_rows = wherenext_get("relocation-index")
        rel_rows = rel_rows if isinstance(rel_rows, list) else rel_rows.get("data", [])
        rel_row  = wherenext_find_country(rel_rows, country)
        wn["relocation_index"] = rel_row or {"note": f"No WhereNext relocation data for '{country}'"}
    except Exception as exc:
        wn["relocation_index"] = {"error": str(exc)}

    try:
        city_rows = wherenext_get("city-prices")
        city_rows = city_rows if isinstance(city_rows, list) else city_rows.get("data", [])
        city_row  = wherenext_find_city(city_rows, city)
        wn["city_prices"] = city_row  # None is fine — not all cities are covered
    except Exception as exc:
        wn["city_prices"] = {"error": str(exc)}

    result["wherenext"] = wn

    # ── World Bank indicators ─────────────────
    wb = {}
    indicators = {
        "gdp_per_capita": ("NY.GDP.PCAP.CD", "current USD"),
        "unemployment":   ("SL.UEM.TOTL.ZS", "% of labour force"),
        "rd_expenditure": ("GB.XPD.RSDV.GD.ZS", "% of GDP"),
    }
    for key, (code, unit) in indicators.items():
        try:
            raw     = worldbank_get(f"/country/{country}/indicator/{code}", params={"date": year})
            entries = [e for e in (raw or []) if e.get("value") is not None]
            if entries:
                latest  = sorted(entries, key=lambda x: x["date"], reverse=True)[0]
                wb[key] = {"value": latest["value"], "unit": unit, "year": latest["date"]}
            else:
                wb[key] = {"value": None, "unit": unit, "note": "no data for this year"}
        except Exception as exc:
            wb[key] = {"error": str(exc)}

    result["worldbank"] = wb
    return jsonify(result)


# ──────────────────────────────────────────────
#  Error handlers
# ──────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found. GET / for the full list."}), 404


@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("\n University Context API")
    print(" ─────────────────────────────────────────────────")
    print(" WhereNext  →  https://getwherenext.com/api/data")
    print(" World Bank →  https://api.worldbank.org/v2")
    print(" ─────────────────────────────────────────────────")
    print(" NOTE: Teleport API is permanently offline (2026)")
    print(" Open http://localhost:5000/ for the endpoint index\n")
    app.run(host="0.0.0.0", port=5000, debug=True)