"""
Open WebUI Tool — University City & Country Enrichment
=======================================================
Paste this entire file into Open WebUI:
  Workspace → Tools → (+) New Tool

The LLM will call `get_university_context` automatically whenever the user
asks about anything not covered by the knowledge base (KB): city liveability,
cost of living, salaries, unemployment, R&D investment, etc.

Data sources (all free, no API key required):
  - WhereNext (getwherenext.com) — cost-of-living index, relocation index,
    median salaries, city-level item prices. CC BY 4.0.
  - World Bank API — GDP per capita, unemployment rate, R&D expenditure.

Configuration:
  Set ENRICH_API_URL below to wherever your Flask server is running.
  If running locally alongside Open WebUI:  http://localhost:5000/enrich
  If running in Docker / a VM:              http://<host-ip>:5000/enrich
"""

import json
import urllib.request
import urllib.parse
from pydantic import BaseModel, Field

# ── Change this to your Flask server address ──────────────────────────────────
ENRICH_API_URL = "http://host.docker.internal:5000/enrich"
# ─────────────────────────────────────────────────────────────────────────────


class Tools:
    class Valves(BaseModel):
        """
        Admin-configurable settings shown in the Open WebUI Tool panel.
        Valves let admins override defaults without editing code.
        """
        enrich_api_url: str = Field(
            default=ENRICH_API_URL,
            description="Full URL of the /enrich endpoint on your Flask server.",
        )
        timeout_seconds: int = Field(
            default=10,
            description="Max seconds to wait for the Flask server to respond.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def get_university_context(
        self,
        city: str,
        country_iso2: str,
        year: str = "2023",
    ) -> str:
        """
        Retrieves real-time city and country context for a university location.

        Call this tool when the user asks about information that is NOT
        in the knowledge base, such as:
          - City quality of life (safety, healthcare, cost of living, housing,
            internet speed, commute times, tolerance, outdoor activities)
          - Graduate salary ranges or job market conditions in the city
          - Country unemployment rate
          - Country R&D expenditure or innovation investment
          - Country GDP per capita or economic context
          - Cost of living comparison between university cities

        Do NOT call this tool for:
          - University ranking scores (Teaching, Research, Industry Impact, etc.)
          - THE overall scores or ranking positions
          - Student population or staff ratios
          - Historical ranking trends
          - International outlook scores
          These are all available in the knowledge base.

        :param city: Name of the city where the university is located.
                     Examples: "London", "Tokyo", "Boston", "Tel Aviv"
        :param country_iso2: ISO 3166-1 alpha-2 country code (two letters).
                             Examples: "GB" (UK), "US", "JP", "DE", "IL"
        :param year: The year to fetch World Bank indicators for.
                     Use a single year ("2023") or a range ("2016:2026").
                     Default is "2023". Match this to the ranking year when
                     the user is asking about a specific year.
        :return: Formatted summary with WhereNext cost-of-living, relocation
                 index, city item prices, and World Bank economic indicators.
        """
        # Build the request URL
        params = urllib.parse.urlencode({
            "city":    city,
            "country": country_iso2,
            "year":    year,
        })
        url = f"{self.valves.enrich_api_url}?{params}"
        print(f"[university-context-tool] Fetching enrichment data from: {url}")
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.valves.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)

        except urllib.error.HTTPError as e:
            return json.dumps({
                "error":   f"Flask server returned HTTP {e.code}",
                "url":     url,
                "details": e.read().decode("utf-8", errors="replace"),
            })
        except urllib.error.URLError as e:
            return json.dumps({
                "error":   "Could not reach the Flask enrichment server.",
                "reason":  str(e.reason),
                "url":     url,
                "hint":    "Check that the Flask server is running and ENRICH_API_URL is correct.",
            })
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})

        # ── Format a clean, LLM-friendly summary ──────────────────────────────
        lines = [
            f"Context for {data.get('city')} ({data.get('country')}) — {data.get('year')}",
            "",
        ]

        # ── WhereNext — cost of living ─────────────────────────────────────
        wn = data.get("wherenext", {})

        col = wn.get("cost_of_living", {})
        if col and "error" not in col and "note" not in col:
            lines.append("Cost of living (WhereNext, country-level):")
            if col.get("monthly_usd"):
                lines.append(f"  - Est. monthly cost: ${col['monthly_usd']:,} USD")
            if col.get("index"):
                lines.append(f"  - Cost index: {col['index']} (US = 82 baseline)")
            for sub in ("rent_index", "groceries_index", "utilities_index", "transport_index"):
                if col.get(sub) is not None:
                    label = sub.replace("_index", "").capitalize()
                    lines.append(f"  - {label} index: {col[sub]}")
        else:
            note = col.get("note") or col.get("error") or "not available"
            lines.append(f"Cost of living: {note}")

        lines.append("")

        # ── WhereNext — relocation index ───────────────────────────────────
        rel = wn.get("relocation_index", {})
        if rel and "error" not in rel and "note" not in rel:
            lines.append("Relocation index (WhereNext, country-level, 0–100):")
            for dim in ("overall", "cost", "safety", "healthcare",
                        "education", "career", "lifestyle", "infrastructure"):
                if rel.get(dim) is not None:
                    lines.append(f"  - {dim.capitalize()}: {rel[dim]}")
        else:
            note = rel.get("note") or rel.get("error") or "not available"
            lines.append(f"Relocation index: {note}")

        lines.append("")

        # ── WhereNext — city-level item prices ─────────────────────────────
        city_prices = wn.get("city_prices")
        if city_prices and "error" not in city_prices:
            lines.append(f"City item prices (WhereNext, {data.get('city')}):")
            price_labels = {
                "rent_1br_city_usd":        "1-bed rent city centre (USD/mo)",
                "rent_1br_outside_usd":     "1-bed rent outside centre (USD/mo)",
                "meal_cheap_usd":           "Cheap restaurant meal (USD)",
                "meal_midrange_usd":        "Mid-range meal for 2 (USD)",
                "monthly_transport_usd":    "Monthly transport pass (USD)",
                "internet_monthly_usd":     "Internet (60 Mbps, USD/mo)",
                "gym_monthly_usd":          "Gym membership (USD/mo)",
            }
            for key, label in price_labels.items():
                if city_prices.get(key) is not None:
                    lines.append(f"  - {label}: ${city_prices[key]:,.0f}")
        else:
            lines.append(
                f"City item prices: not available for '{data.get('city')}' "
                f"(WhereNext covers 50+ major cities)"
            )

        lines.append("")

        # ── World Bank indicators ──────────────────────────────────────────
        wb = data.get("worldbank", {})

        def wb_line(key, label):
            entry = wb.get(key, {})
            if "error" in entry:
                return f"{label}: error — {entry['error']}"
            if entry.get("value") is None:
                return f"{label}: no data available"
            return (
                f"{label}: {entry['value']} {entry.get('unit', '')} "
                f"({entry.get('year', '')})"
            )

        lines.append("Country economic indicators (World Bank):")
        lines.append(f"  - {wb_line('gdp_per_capita', 'GDP per capita')}")
        lines.append(f"  - {wb_line('unemployment',   'Unemployment rate')}")
        lines.append(f"  - {wb_line('rd_expenditure', 'R&D expenditure')}")

        # Also include the raw JSON so the LLM can answer precise follow-up questions
        lines.append("")
        lines.append("Raw data:")
        lines.append(json.dumps(data, indent=2))

        return "\n".join(lines)