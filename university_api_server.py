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
    print(f"[teleport_get] Fetching {url} with params: {kwargs.get('params', {})}")
    resp = requests.get(url, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp.json()


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
    return jsonify({
        "message": f"University Context API — provides city and country data for university records."
    })


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
