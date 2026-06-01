"""
Open WebUI Tool — University City & Country Enrichment
=======================================================
Paste this entire file into Open WebUI:
  Workspace → Tools → (+) New Tool

The LLM will call `get_university_context` automatically whenever the user
asks about anything not covered by the knowledge base (KB): city liveability,
cost of living, salaries, unemployment, R&D investment, etc.

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
        :return: JSON string with Teleport quality-of-life scores and World
                 Bank indicators (GDP per capita, unemployment, R&D spending).
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

        # Teleport quality-of-life
        teleport = data.get("teleport", {})
        if "error" in teleport:
            lines.append(f"City quality-of-life data: not available ({teleport['error']})")
        else:
            lines.append(
                f"Overall city score (Teleport): {teleport.get('teleport_city_score')}/100"
            )
            lines.append("Quality-of-life categories:")
            for cat in teleport.get("categories", []):
                lines.append(f"  - {cat['name']}: {cat['score_out_of_10']}/10")

        lines.append("")

        # World Bank indicators
        wb = data.get("worldbank", {})

        def wb_line(key, label):
            entry = wb.get(key, {})
            if "error" in entry:
                return f"{label}: error — {entry['error']}"
            if entry.get("value") is None:
                return f"{label}: no data available"
            return f"{label}: {entry['value']} {entry.get('unit', '')} ({entry.get('year', '')})"

        lines.append("Country economic indicators (World Bank):")
        lines.append(f"  - {wb_line('gdp_per_capita', 'GDP per capita')}")
        lines.append(f"  - {wb_line('unemployment',   'Unemployment rate')}")
        lines.append(f"  - {wb_line('rd_expenditure', 'R&D expenditure')}")

        # Also return the raw JSON so the LLM can answer precise questions
        lines.append("")
        lines.append("Raw data:")
        lines.append(json.dumps(data, indent=2))

        return "\n".join(lines)
