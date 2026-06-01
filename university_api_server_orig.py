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
    return jsonify({
        "name": "University Context API",
        "description": (
            "Enriches university data with country cost-of-living and economic "
            "indicators. Data from WhereNext (getwherenext.com, CC BY 4.0) and "
            "the World Bank — both free, no API key required."
        ),
        "note": "Teleport API (api.teleport.org) is permanently offline as of 2026. "
                "Replaced by WhereNext.",
        "endpoints": {
            "GET /enrich": {
                "description": "One-shot enrichment: WhereNext data + World Bank indicators",
                "params": {"city": "city name", "country": "ISO-2 code", "year": "optional, default 2023"},
                "example": "/enrich?city=Oxford&country=GB&year=2023",
            },
            "GET /wherenext/relocation": {
                "description": "Country relocation index — 7 dimensions (cost, safety, healthcare, education, career, lifestyle, infrastructure)",
                "params": {"country": "ISO-2 code"},
                "example": "/wherenext/relocation?country=GB",
            },
            "GET /wherenext/cost_of_living": {
                "description": "Country cost-of-living index with sub-indexes for rent, groceries, utilities, transport",
                "params": {"country": "ISO-2 code"},
                "example": "/wherenext/cost_of_living?country=DE",
            },
            "GET /wherenext/salaries": {
                "description": "Country median salary — gross, net (after-tax), and PPP-adjusted in USD",
                "params": {"country": "ISO-2 code"},
                "example": "/wherenext/salaries?country=US",
            },
            "GET /wherenext/city_prices": {
                "description": "City-level item prices (50+ cities): rent, meals, groceries, transport pass, gym, etc.",
                "params": {"city": "city name"},
                "example": "/wherenext/city_prices?city=London",
            },
            "GET /worldbank/gdp_per_capita": {
                "description": "GDP per capita current USD (NY.GDP.PCAP.CD)",
                "params": {"country": "ISO-2 code", "year": "optional year or range"},
                "example": "/worldbank/gdp_per_capita?country=JP&year=2016:2023",
            },
            "GET /worldbank/unemployment": {
                "description": "Unemployment rate % of labour force (SL.UEM.TOTL.ZS)",
                "params": {"country": "ISO-2 code", "year": "optional"},
                "example": "/worldbank/unemployment?country=FR&year=2023",
            },
            "GET /worldbank/rd_expenditure": {
                "description": "R&D expenditure % of GDP (GB.XPD.RSDV.GD.ZS)",
                "params": {"country": "ISO-2 code", "year": "optional"},
                "example": "/worldbank/rd_expenditure?country=KR&year=2023",
            },
        },
    })


# ──────────────────────────────────────────────
#  WhereNext endpoints
# ──────────────────────────────────────────────

@app.route("/wherenext/relocation")
def wn_relocation():
    """
    GET /wherenext/relocation?country=<iso2>
    -----------------------------------------
    Country relocation index from WhereNext — 7 composite dimensions:
    cost, safety, healthcare, education, career opportunity, lifestyle,
    and infrastructure. Each scored 0–100 using institutional data
    (World Bank, WHO, OECD, Global Peace Index, and more).

    Query params:
        country (str, required) — ISO-2 country code (e.g. 'GB', 'DE', 'JP')

    Returns:
        { "country": "GB", "relocation_index": { "overall": 74, "cost": 52,
          "safety": 81, "healthcare": 79, "education": 85, ... } }
    """
    country = request.args.get("country", "").strip().upper()
    if not country:
        return error("'country' query parameter is required (ISO-2 code)")

    dataset = wherenext_get("relocation-index")
    # Dataset may be wrapped in a key
    rows = dataset if isinstance(dataset, list) else dataset.get("data", [])
    row = wherenext_find_country(rows, country)

    if not row:
        return error(f"Country '{country}' not found in WhereNext relocation index "
                     f"(covers 95 countries — check the ISO-2 code)", 404)

    return jsonify({
        "country":          country,
        "source":           "WhereNext Global Relocation Index 2026 (CC BY 4.0)",
        "relocation_index": row,
    })


@app.route("/wherenext/cost_of_living")
def wn_cost_of_living():
    """
    GET /wherenext/cost_of_living?country=<iso2>
    ---------------------------------------------
    Country cost-of-living index with monthly USD estimates and sub-indexes
    for rent, groceries, utilities, and transport. Calibrated against World
    Bank purchasing power parity data (not crowdsourced surveys).

    Query params:
        country (str, required) — ISO-2 country code

    Returns:
        { "country": "DE", "cost_of_living": { "index": 72, "monthly_usd": 2100,
          "rent_index": 58, "groceries_index": 71, ... } }
    """
    country = request.args.get("country", "").strip().upper()
    if not country:
        return error("'country' query parameter is required (ISO-2 code)")

    dataset = wherenext_get("cost-of-living")
    rows = dataset if isinstance(dataset, list) else dataset.get("data", [])
    row = wherenext_find_country(rows, country)

    if not row:
        return error(f"Country '{country}' not found in WhereNext cost-of-living index", 404)

    return jsonify({
        "country":        country,
        "source":         "WhereNext Cost of Living Index 2026 (CC BY 4.0)",
        "cost_of_living": row,
    })


@app.route("/wherenext/salaries")
def wn_salaries():
    """
    GET /wherenext/salaries?country=<iso2>
    ----------------------------------------
    National median salary — gross annual USD, net after-tax USD, and
    PPP-adjusted purchasing power. Data from OECD, Eurostat, ILO, and
    national statistical offices (43 countries covered).

    Query params:
        country (str, required) — ISO-2 country code

    Returns:
        { "country": "US", "salaries": { "gross_usd": 58000,
          "net_usd": 43000, "ppp_adjusted_usd": 43000, "data_year": 2023 } }
    """
    country = request.args.get("country", "").strip().upper()
    if not country:
        return error("'country' query parameter is required (ISO-2 code)")

    dataset = wherenext_get("median-salaries")
    rows = dataset if isinstance(dataset, list) else dataset.get("data", [])
    row = wherenext_find_country(rows, country)

    if not row:
        return error(f"Country '{country}' not found in WhereNext salary data "
                     f"(covers 43 countries)", 404)

    return jsonify({
        "country":  country,
        "source":   "WhereNext Median Salaries 2026 (OECD/Eurostat/ILO, CC BY 4.0)",
        "salaries": row,
    })


@app.route("/wherenext/city_prices")
def wn_city_prices():
    """
    GET /wherenext/city_prices?city=<name>
    ----------------------------------------
    City-level item prices in USD and local currency for 50+ major cities.
    Covers 14 categories: rent, restaurant meals, groceries, transport pass,
    gym membership, utilities, and more. Useful for comparing cost of living
    between university cities directly.

    Query params:
        city (str, required) — city name (e.g. 'London', 'Tokyo', 'Boston')

    Returns:
        { "city": "London", "prices": { "rent_1br_city_usd": 2400,
          "meal_cheap_usd": 18, "monthly_transport_usd": 185, ... } }
    """
    city = request.args.get("city", "").strip()
    if not city:
        return error("'city' query parameter is required")

    dataset = wherenext_get("city-prices")
    rows = dataset if isinstance(dataset, list) else dataset.get("data", [])
    row = wherenext_find_city(rows, city)

    if not row:
        return error(
            f"City '{city}' not found in WhereNext city prices (covers 50+ cities). "
            f"Try a major city name like 'London', 'Tokyo', or 'Boston'.",
            404,
        )

    return jsonify({
        "city":   row.get("city", city),
        "source": "WhereNext City-Level Item Prices 2026 (CC BY 4.0)",
        "prices": row,
    })


# ──────────────────────────────────────────────
#  World Bank endpoints
# ──────────────────────────────────────────────

def _worldbank_indicator(indicator_code: str, label: str, unit: str):
    """Shared handler for World Bank indicator endpoints."""
    country = request.args.get("country", "").strip().upper()
    if not country:
        return error("'country' query parameter is required (ISO-2 code, e.g. 'GB')")

    year = request.args.get("year", "").strip()
    params = {"date": year} if year else {}

    raw = worldbank_get(f"/country/{country}/indicator/{indicator_code}", params=params)
    if raw is None:
        return error(f"No data returned for country '{country}'", 404)

    cleaned = sorted(
        [{"year": e["date"], "value": e["value"]}
         for e in (raw or []) if e.get("value") is not None],
        key=lambda x: x["year"],
    )

    return jsonify({
        "country":   country,
        "indicator": indicator_code,
        "label":     label,
        "unit":      unit,
        "data":      cleaned,
    })


@app.route("/worldbank/gdp_per_capita")
def wb_gdp_per_capita():
    """
    GET /worldbank/gdp_per_capita?country=<iso2>[&year=<year_or_range>]
    ---------------------------------------------------------------------
    GDP per capita in current USD (indicator: NY.GDP.PCAP.CD).
    Use year range '2016:2026' to align with THE ranking years.
    """
    return _worldbank_indicator("NY.GDP.PCAP.CD", "GDP per capita", "current USD")


@app.route("/worldbank/unemployment")
def wb_unemployment():
    """
    GET /worldbank/unemployment?country=<iso2>[&year=<year_or_range>]
    -------------------------------------------------------------------
    Total unemployment rate % of labour force, ILO estimate (SL.UEM.TOTL.ZS).
    """
    return _worldbank_indicator("SL.UEM.TOTL.ZS", "Unemployment rate", "% of labour force")


@app.route("/worldbank/rd_expenditure")
def wb_rd_expenditure():
    """
    GET /worldbank/rd_expenditure?country=<iso2>[&year=<year_or_range>]
    ---------------------------------------------------------------------
    R&D expenditure as % of GDP (GB.XPD.RSDV.GD.ZS). Complements the
    Research Environment and Research Quality scores in the THE dataset.
    """
    return _worldbank_indicator("GB.XPD.RSDV.GD.ZS", "R&D expenditure", "% of GDP")


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