"""
University Context API Server
==============================
A Flask server that enriches university data with real-time city and country
information from two free public APIs:

  - Teleport API  (https://api.teleport.org/api)   — city quality of life, salaries
  - World Bank API (https://api.worldbank.org/v2)  — country economic indicators

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

TELEPORT_BASE  = "https://api.teleport.org/api"
WORLDBANK_BASE = "https://api.worldbank.org/v2"

TIMEOUT = 8  # seconds for upstream requests


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def teleport_get(path: str, **kwargs):
    """GET a Teleport endpoint and return parsed JSON, or raise on error."""
    url = f"{TELEPORT_BASE}{path}"
    resp = requests.get(url, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp.json()


def worldbank_get(path: str, **kwargs):
    """GET a World Bank endpoint (JSON format forced) and return the data array."""
    url = f"{WORLDBANK_BASE}{path}"
    params = kwargs.pop("params", {})
    params["format"] = "json"
    resp = requests.get(url, params=params, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    payload = resp.json()
    # World Bank returns [metadata, data_array]
    if isinstance(payload, list) and len(payload) == 2:
        return payload[1]
    return payload


def get_urban_area_slug(city_name: str) -> str | None:
    """
    Resolve a free-text city name to a Teleport urban-area slug by calling
    /cities/?search=<name> and following the embedded urban-area link.

    Returns the slug string (e.g. 'london') or None if the city has no
    associated Teleport urban area.
    """
    data = teleport_get("/cities/", params={"search": city_name, "limit": 5})
    results = data.get("_embedded", {}).get("city:search-results", [])
    if not results:
        return None

    for result in results:
        links = result.get("_links", {})
        ua_link = links.get("city:urban_area", {}).get("href", "")
        if ua_link:
            # href looks like: https://api.teleport.org/api/urban_areas/slug:london/
            slug = ua_link.rstrip("/").split("slug:")[-1]
            return slug

    return None


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
    Returns a directory of all available endpoints with their descriptions
    and required parameters. Use this as a quick reference while developing.
    """
    return jsonify({
        "name": "University Context API",
        "description": (
            "Enriches university data with real-time city quality-of-life "
            "and country economic indicators. Data sourced from Teleport and "
            "the World Bank — both free, no API key required."
        ),
        "endpoints": {
            # ── Teleport ──────────────────────────────────────────
            "GET /teleport/slug": {
                "description": (
                    "Resolve a city name to its Teleport urban-area slug. "
                    "Call this first if you want to build raw Teleport URLs manually."
                ),
                "params": {"city": "City name (e.g. 'London')"},
                "example": "/teleport/slug?city=London",
            },
            "GET /teleport/scores": {
                "description": (
                    "Quality-of-life scores (0–10) across 17 categories for a city: "
                    "housing, cost of living, safety, healthcare, education, "
                    "tolerance, internet access, outdoor activities, and more. "
                    "Resolves the city name to a slug automatically."
                ),
                "params": {"city": "City name (e.g. 'Tokyo')"},
                "example": "/teleport/scores?city=Tokyo",
            },
            "GET /teleport/details": {
                "description": (
                    "Raw data behind the quality-of-life scores: concrete values "
                    "such as average apartment rent (USD), commute time (minutes), "
                    "broadband speed (Mbps), startup job count, and employer tax rates."
                ),
                "params": {"city": "City name (e.g. 'Berlin')"},
                "example": "/teleport/details?city=Berlin",
            },
            "GET /teleport/salaries": {
                "description": (
                    "Salary distribution by job title for the urban area — 25th, "
                    "50th, and 75th percentile in USD. Useful for graduate "
                    "employability context."
                ),
                "params": {"city": "City name (e.g. 'San Francisco')"},
                "example": "/teleport/salaries?city=San Francisco",
            },
            # ── World Bank ────────────────────────────────────────
            "GET /worldbank/gdp_per_capita": {
                "description": (
                    "GDP per capita (current USD) time series for a country "
                    "(indicator NY.GDP.PCAP.CD). Contextualises whether a highly "
                    "ranked university sits in a wealthy or developing economy."
                ),
                "params": {
                    "country": "ISO-2 country code (e.g. 'GB')",
                    "year":    "(optional) single year or range '2016:2026'",
                },
                "example": "/worldbank/gdp_per_capita?country=GB&year=2016:2026",
            },
            "GET /worldbank/unemployment": {
                "description": (
                    "Total unemployment rate (% of labour force, ILO estimate) "
                    "per year (indicator SL.UEM.TOTL.ZS). Relevant for graduate "
                    "employment prospects in that country."
                ),
                "params": {
                    "country": "ISO-2 country code (e.g. 'DE')",
                    "year":    "(optional) single year or range",
                },
                "example": "/worldbank/unemployment?country=DE&year=2020",
            },
            "GET /worldbank/rd_expenditure": {
                "description": (
                    "R&D expenditure as a percentage of GDP (indicator "
                    "GB.XPD.RSDV.GD.ZS). Directly complements the Research "
                    "Environment and Research Quality scores in the THE dataset."
                ),
                "params": {
                    "country": "ISO-2 country code (e.g. 'US')",
                    "year":    "(optional) single year or range",
                },
                "example": "/worldbank/rd_expenditure?country=US&year=2016:2026",
            },
            "GET /worldbank/tertiary_enrollment": {
                "description": (
                    "Gross tertiary enrolment ratio — percentage of the "
                    "college-age population enrolled in higher education "
                    "(indicator SE.TER.ENRR). Indicates how competitive "
                    "university access is in that country."
                ),
                "params": {
                    "country": "ISO-2 country code (e.g. 'JP')",
                    "year":    "(optional) single year or range",
                },
                "example": "/worldbank/tertiary_enrollment?country=JP",
            },
            "GET /worldbank/population": {
                "description": (
                    "Total population time series (indicator SP.POP.TOTL). "
                    "Useful for normalising other indicators (e.g. researchers "
                    "per capita) and understanding the national talent pool size."
                ),
                "params": {
                    "country": "ISO-2 country code (e.g. 'CN')",
                    "year":    "(optional) single year or range",
                },
                "example": "/worldbank/population?country=CN&year=2016:2026",
            },
            # ── Combined ──────────────────────────────────────────
            "GET /enrich": {
                "description": (
                    "One-shot enrichment endpoint. Given a university city and "
                    "country ISO-2 code, returns Teleport quality-of-life scores "
                    "alongside World Bank GDP per capita, unemployment, and R&D "
                    "expenditure — all in a single response. Use this to enrich "
                    "a university record from the THE dataset."
                ),
                "params": {
                    "city":    "City name (e.g. 'Cambridge')",
                    "country": "ISO-2 country code (e.g. 'GB')",
                    "year":    "(optional) World Bank year or range, default '2023'",
                },
                "example": "/enrich?city=Cambridge&country=GB&year=2023",
            },
        },
    })


# ──────────────────────────────────────────────
#  Teleport endpoints
# ──────────────────────────────────────────────

@app.route("/teleport/slug")
def teleport_slug():
    """
    GET /teleport/slug?city=<name>
    --------------------------------
    Resolve a city name to its Teleport urban-area slug.

    The Teleport API identifies cities via "slugs" (lowercase, hyphenated
    identifiers like 'new-york' or 'tel-aviv'). This endpoint performs the
    /cities/?search= lookup and returns the resolved slug so callers can
    build custom Teleport URLs without a separate lookup step.

    Query params:
        city (str, required) — free-text city name

    Returns:
        { "city": "...", "slug": "...", "urban_area_url": "..." }

    Errors:
        400 if `city` param is missing
        404 if no Teleport urban area is found for that city
    """
    city = request.args.get("city", "").strip()
    if not city:
        return error("'city' query parameter is required")

    slug = get_urban_area_slug(city)
    if not slug:
        return error(f"No Teleport urban area found for '{city}'", 404)

    return jsonify({
        "city": city,
        "slug": slug,
        "urban_area_url": f"{TELEPORT_BASE}/urban_areas/slug:{slug}/",
    })


@app.route("/teleport/scores")
def teleport_scores():
    """
    GET /teleport/scores?city=<name>
    ----------------------------------
    Quality-of-life scores (0–10) for a city across 17 categories.

    Internally calls /cities/?search= to resolve the slug, then fetches
    /urban_areas/slug:<slug>/scores/. Categories include:
      housing, cost_of_living, startups, venture_capital, travel,
      connectivity, commute, business_freedom, safety, healthcare,
      education, environmental_quality, economy, taxation, internet_access,
      leisure_culture, tolerance, outdoors.

    Query params:
        city (str, required) — free-text city name

    Returns:
        {
          "city": "...",
          "slug": "...",
          "teleport_city_score": 0–100,
          "summary": "<html description>",
          "categories": [{ "name": "...", "score_out_of_10": 7.3, "color": "#..." }]
        }
    """
    city = request.args.get("city", "").strip()
    if not city:
        return error("'city' query parameter is required")

    slug = get_urban_area_slug(city)
    if not slug:
        return error(f"No Teleport urban area found for '{city}'", 404)

    data = teleport_get(f"/urban_areas/slug:{slug}/scores/")
    categories = [
        {
            "name":           cat.get("name"),
            "score_out_of_10": round(cat.get("score_out_of_10", 0), 2),
            "color":          cat.get("color"),
        }
        for cat in data.get("categories", [])
    ]

    return jsonify({
        "city":                city,
        "slug":                slug,
        "teleport_city_score": round(data.get("teleport_city_score", 0), 1),
        "summary":             data.get("summary", ""),
        "categories":          categories,
    })


@app.route("/teleport/details")
def teleport_details():
    """
    GET /teleport/details?city=<name>
    -----------------------------------
    Raw data behind the Teleport quality-of-life scores.

    Returns concrete values (not just scores) grouped by category:
      - Housing: avg rent for small/medium/large apartments (USD/month)
      - Startups: startup jobs available, venture capital access
      - Commute: avg commute time (minutes)
      - Internet: broadband speed (Mbps)
      - Taxation: employer social security rate, income tax rates
      ... and more.

    Query params:
        city (str, required) — free-text city name

    Returns:
        { "city": "...", "slug": "...", "categories": [ { "id": "...", "label": "...", "data": [...] } ] }
    """
    city = request.args.get("city", "").strip()
    if not city:
        return error("'city' query parameter is required")

    slug = get_urban_area_slug(city)
    if not slug:
        return error(f"No Teleport urban area found for '{city}'", 404)

    data = teleport_get(f"/urban_areas/slug:{slug}/details/")
    categories = data.get("categories", [])

    return jsonify({
        "city":       city,
        "slug":       slug,
        "categories": categories,
    })


@app.route("/teleport/salaries")
def teleport_salaries():
    """
    GET /teleport/salaries?city=<name>
    ------------------------------------
    Salary percentile distribution by job title for a city's urban area.

    Returns the 25th, 50th (median), and 75th salary percentiles in USD
    for each tracked job title (e.g. Software Engineer, Data Scientist,
    Marketing Manager, etc.). Useful for assessing graduate income prospects
    near a given university.

    Query params:
        city (str, required) — free-text city name

    Returns:
        {
          "city": "...",
          "slug": "...",
          "salaries": [
            {
              "job":  { "id": "...", "title": "..." },
              "percentile_25": 60000,
              "percentile_50": 80000,
              "percentile_75": 110000
            }
          ]
        }
    """
    city = request.args.get("city", "").strip()
    if not city:
        return error("'city' query parameter is required")

    slug = get_urban_area_slug(city)
    if not slug:
        return error(f"No Teleport urban area found for '{city}'", 404)

    data = teleport_get(f"/urban_areas/slug:{slug}/salaries/")
    salaries = [
        {
            "job":           entry.get("job"),
            "percentile_25": round(entry["salary_percentiles"]["percentile_25"], 0),
            "percentile_50": round(entry["salary_percentiles"]["percentile_50"], 0),
            "percentile_75": round(entry["salary_percentiles"]["percentile_75"], 0),
        }
        for entry in data.get("salaries", [])
    ]

    return jsonify({
        "city":     city,
        "slug":     slug,
        "salaries": salaries,
    })


# ──────────────────────────────────────────────
#  World Bank endpoints
# ──────────────────────────────────────────────

def _worldbank_indicator(indicator_code: str, label: str, unit: str):
    """
    Shared handler for all World Bank indicator endpoints.
    Reads `country` and optional `year` from the request args.
    """
    country = request.args.get("country", "").strip().upper()
    if not country:
        return error("'country' query parameter is required (ISO-2 code, e.g. 'GB')")

    year = request.args.get("year", "").strip()
    params = {}
    if year:
        params["date"] = year

    raw = worldbank_get(
        f"/country/{country}/indicator/{indicator_code}",
        params=params,
    )

    if raw is None:
        return error(f"No data returned for country '{country}'", 404)

    cleaned = [
        {
            "year":  entry.get("date"),
            "value": entry.get("value"),
        }
        for entry in (raw or [])
        if entry.get("value") is not None
    ]
    cleaned.sort(key=lambda x: x["year"])

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

    Contextualises the economic wealth of a country in the year(s) a
    university was ranked. A university ranked #50 in a lower-GDP country
    may be a greater national achievement than #50 in a high-GDP country.

    Query params:
        country (str, required) — ISO-2 country code (e.g. 'US', 'JP', 'DE')
        year    (str, optional) — single year ('2023') or range ('2016:2026')

    Returns:
        { "country": "US", "indicator": "NY.GDP.PCAP.CD", "label": "...",
          "unit": "current USD", "data": [{ "year": "2023", "value": 76329 }] }
    """
    return _worldbank_indicator("NY.GDP.PCAP.CD", "GDP per capita", "current USD")


@app.route("/worldbank/unemployment")
def wb_unemployment():
    """
    GET /worldbank/unemployment?country=<iso2>[&year=<year_or_range>]
    -------------------------------------------------------------------
    Total unemployment rate as % of total labour force (ILO estimate).
    Indicator: SL.UEM.TOTL.ZS.

    Directly relevant to graduate employment prospects — a university in a
    high-unemployment country offers graduates a tougher job market regardless
    of its ranking.

    Query params:
        country (str, required) — ISO-2 country code
        year    (str, optional) — single year or range

    Returns:
        { ..., "unit": "% of total labour force", "data": [...] }
    """
    return _worldbank_indicator(
        "SL.UEM.TOTL.ZS",
        "Unemployment rate (total)",
        "% of total labour force",
    )


@app.route("/worldbank/rd_expenditure")
def wb_rd_expenditure():
    """
    GET /worldbank/rd_expenditure?country=<iso2>[&year=<year_or_range>]
    ---------------------------------------------------------------------
    R&D expenditure as % of GDP (indicator: GB.XPD.RSDV.GD.ZS).
    Source: UNESCO Institute for Statistics.

    Directly complements the THE dataset's Research Environment and Research
    Quality scores. Countries that invest heavily in R&D tend to produce
    stronger research outputs, which reinforces university rankings.

    Query params:
        country (str, required) — ISO-2 country code
        year    (str, optional) — single year or range

    Returns:
        { ..., "unit": "% of GDP", "data": [...] }
    """
    return _worldbank_indicator(
        "GB.XPD.RSDV.GD.ZS",
        "R&D expenditure",
        "% of GDP",
    )


@app.route("/worldbank/tertiary_enrollment")
def wb_tertiary_enrollment():
    """
    GET /worldbank/tertiary_enrollment?country=<iso2>[&year=<year_or_range>]
    --------------------------------------------------------------------------
    Gross tertiary enrolment ratio (indicator: SE.TER.ENRR).
    Source: UNESCO Institute for Statistics.

    The percentage of the official college-age population enrolled in
    tertiary education — indicates how broadly accessible higher education
    is in a given country, and how competitive admission is likely to be.

    Query params:
        country (str, required) — ISO-2 country code
        year    (str, optional) — single year or range

    Returns:
        { ..., "unit": "% gross", "data": [...] }
    """
    return _worldbank_indicator(
        "SE.TER.ENRR",
        "Gross tertiary enrolment ratio",
        "% gross",
    )


@app.route("/worldbank/population")
def wb_population():
    """
    GET /worldbank/population?country=<iso2>[&year=<year_or_range>]
    -----------------------------------------------------------------
    Total population (indicator: SP.POP.TOTL).

    Useful for normalising other indicators — e.g. computing researchers
    per capita or university enrolment as a share of population. Also helps
    understand the size of the national talent pool feeding universities.

    Query params:
        country (str, required) — ISO-2 country code
        year    (str, optional) — single year or range

    Returns:
        { ..., "unit": "persons", "data": [...] }
    """
    return _worldbank_indicator("SP.POP.TOTL", "Total population", "persons")


# ──────────────────────────────────────────────
#  Combined enrichment endpoint
# ──────────────────────────────────────────────

@app.route("/enrich")
def enrich():
    """
    GET /enrich?city=<name>&country=<iso2>[&year=<year>]
    ------------------------------------------------------
    One-shot enrichment for a university record from the THE dataset.

    Combines Teleport quality-of-life scores (city level) with three World
    Bank indicators (country level) into a single response. Partial results
    are returned if the city has no Teleport urban area — the `teleport`
    key will contain an `error` field instead of scores.

    Query params:
        city    (str, required) — city where the university is located
        country (str, required) — ISO-2 country code
        year    (str, optional) — World Bank year or range (default: '2023')

    Returns:
        {
          "city":    "Oxford",
          "country": "GB",
          "year":    "2023",
          "teleport": {
            "slug":                "oxford",
            "teleport_city_score": 73.2,
            "categories":          [...]
          },
          "worldbank": {
            "gdp_per_capita":       { "value": 46125, "unit": "current USD" },
            "unemployment":         { "value": 4.1,   "unit": "% of labour force" },
            "rd_expenditure":       { "value": 2.93,  "unit": "% of GDP" }
          }
        }
    """
    city = request.args.get("city", "").strip()
    country = request.args.get("country", "").strip().upper()
    year = request.args.get("year", "2023").strip()

    if not city:
        return error("'city' query parameter is required")
    if not country:
        return error("'country' query parameter is required (ISO-2 code)")

    result = {"city": city, "country": country, "year": year}

    # ── Teleport scores ───────────────────────
    try:
        slug = get_urban_area_slug(city)
        if slug:
            scores_raw = teleport_get(f"/urban_areas/slug:{slug}/scores/")
            result["teleport"] = {
                "slug":                slug,
                "teleport_city_score": round(scores_raw.get("teleport_city_score", 0), 1),
                "summary":             scores_raw.get("summary", ""),
                "categories": [
                    {
                        "name":            cat.get("name"),
                        "score_out_of_10": round(cat.get("score_out_of_10", 0), 2),
                    }
                    for cat in scores_raw.get("categories", [])
                ],
            }
        else:
            result["teleport"] = {
                "error": f"No Teleport urban area found for '{city}'"
            }
    except Exception as exc:
        result["teleport"] = {"error": str(exc)}

    # ── World Bank indicators ─────────────────
    wb = {}
    indicators = {
        "gdp_per_capita": ("NY.GDP.PCAP.CD", "current USD"),
        "unemployment":   ("SL.UEM.TOTL.ZS", "% of labour force"),
        "rd_expenditure": ("GB.XPD.RSDV.GD.ZS", "% of GDP"),
    }

    for key, (code, unit) in indicators.items():
        try:
            raw = worldbank_get(
                f"/country/{country}/indicator/{code}",
                params={"date": year},
            )
            entries = [e for e in (raw or []) if e.get("value") is not None]
            if entries:
                latest = sorted(entries, key=lambda x: x["date"], reverse=True)[0]
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
    return jsonify({"error": "Endpoint not found. GET / for the full endpoint list."}), 404


@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("\n University Context API")
    print(" ─────────────────────────────────────────────")
    print(" Teleport  →  https://api.teleport.org/api")
    print(" World Bank → https://api.worldbank.org/v2")
    print(" ─────────────────────────────────────────────")
    print(" Open http://localhost:5000/ for the endpoint index\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
