"""
Open WebUI Tool — Currency Rate via N8N + Perplexity
=====================================================
Paste this entire file into Open WebUI:
  Workspace → Tools → (+) New Tool

The LLM calls `get_currency_rate` automatically when the user asks about
exchange rates or currency values. The tool sends a currency pair to an
N8N webhook, which uses a Perplexity node to fetch current rate data and
returns the result.

N8N Webhook URL: http://localhost:5678/webhook-test/currency-rate
Expected N8N request  (POST JSON): { "currency_pair": "USD/ILS" }
Expected N8N response (JSON):      { "result": "<Perplexity answer text>" }
"""

import json
import urllib.request
import urllib.parse
from pydantic import BaseModel, Field

N8N_WEBHOOK_URL = "http://n8n:5678/webhook-test/currency-rate"


class Tools:
    class Valves(BaseModel):
        """Admin-configurable settings (gear icon next to the tool)."""
        n8n_webhook_url: str = Field(
            default=N8N_WEBHOOK_URL,
            description=(
                "Full URL of the N8N currency-rate webhook."
            ),
        )
        timeout_seconds: int = Field(
            default=15,
            description=(
                "Max seconds to wait for the N8N webhook response. "
                "Perplexity lookups can take a few seconds — 15 is safe."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    def get_currency_rate(
        self,
        base_currency: str,
        quote_currency: str,
    ) -> str:
        """
        Fetches the current exchange rate between two currencies via N8N and Perplexity.

        Call this tool when the user asks about:
          - Current exchange rates between any two currencies
          - How much one currency is worth in another
          - Currency conversion context (e.g. "how expensive is tuition in USD?")
          - Whether a country's currency is strong or weak right now

        Do NOT call this tool for:
          - University ranking scores or THE dataset questions
          - City quality of life or cost of living indexes
          - Historical currency trends beyond what Perplexity returns
          These are handled by the knowledge base or other tools.

        :param base_currency: The currency to convert FROM.
                              Use ISO 4217 three-letter codes.
                              Examples: "USD", "EUR", "GBP", "ILS", "JPY", "CNY"
        :param quote_currency: The currency to convert TO.
                               Examples: "ILS", "USD", "EUR", "GBP", "JPY"
        :return: Current exchange rate and context from Perplexity via N8N.
        """
        # Normalise to uppercase and build the pair string
        base  = base_currency.strip().upper()
        quote = quote_currency.strip().upper()

        if not base or not quote:
            return json.dumps({"error": "Both base_currency and quote_currency are required."})

        if base == quote:
            return json.dumps({"result": f"1 {base} = 1 {quote} (same currency)."})

        currency_pair = f"{base}/{quote}"

        payload = json.dumps({"currency_pair": currency_pair}).encode("utf-8")
        url     = self.valves.n8n_webhook_url

        print(f"[currency-rate-tool] POST {url} — pair: {currency_pair}")

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept":       "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.valves.timeout_seconds) as resp:
                raw  = resp.read().decode("utf-8")
                data = json.loads(raw)

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return json.dumps({
                "error":   f"N8N webhook returned HTTP {e.code}",
                "url":     url,
                "details": body,
                "hint": (
                    "Check that the N8N workflow is active (not in test/inactive mode) "
                    "and that the webhook path matches 'currency-rate'."
                ),
            })
        except urllib.error.URLError as e:
            return json.dumps({
                "error":  "Could not reach the N8N webhook.",
                "reason": str(e.reason),
                "url":    url,
                "hint": (
                    "If Open WebUI runs in Docker, make sure N8N_WEBHOOK_URL uses "
                    "'host.docker.internal' instead of 'localhost'. "
                    "Also verify N8N is running on port 5678."
                ),
            })
        except json.JSONDecodeError:
            return json.dumps({
                "error": "N8N returned a non-JSON response.",
                "raw":   raw[:500],
                "hint":  "Check the N8N workflow's Respond to Webhook node — it must return JSON.",
            })
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})

        # ── Format the response for the LLM ───────────────────────────────────
        # N8N is expected to return: { "result": "<Perplexity answer>" }
        # but we handle common variations gracefully.
        perplexity_text = (
            data.get("result")
            or data.get("output")
            or data.get("text")
            or data.get("answer")
            or data.get("message")
        )

        if perplexity_text:
            lines = [
                f"Currency rate: {currency_pair}",
                f"Source: Perplexity via N8N",
                "",
                str(perplexity_text),
            ]
            return "\n".join(lines)

        # If N8N returns a different structure, pass the raw JSON to the LLM
        return json.dumps({
            "currency_pair": currency_pair,
            "source":        "Perplexity via N8N",
            "data":          data,
            "note": (
                "N8N returned data in an unexpected shape. "
                "Raw response passed through — extract the rate from 'data'."
            ),
        }, indent=2)