"""
Open WebUI Filter Function — University Address (Google Maps Places API)
=========================================================================
Install:  Admin Panel → Functions → (+) New Function → paste this file
Type:     Filter (inlet only)

How it works:
  - Detects when the user asks for an address, location, or directions
    for a university in their message
  - Calls Google Maps Places API (Text Search) to find the university
  - Injects the formatted address, coordinates, Maps URL, and website
    into the system prompt before the LLM responds

Requirements:
  - A Google Maps API key with the Places API (New) enabled
  - Enable it at: https://console.cloud.google.com/apis/library/places-backend.googleapis.com
  - The free tier includes $200/month credit (~6,600 Text Searches free/month)

Set your API key in the Valves panel (gear icon) after installing.
"""

import json
import urllib.request
import urllib.parse
from typing import Optional
from pydantic import BaseModel, Field

PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"

# Fields to request from the Places API (New)
# Only request what you need — billing is per field mask
FIELD_MASK = ",".join(
    [
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.websiteUri",
        "places.googleMapsUri",
        "places.internationalPhoneNumber",
        "places.types",
    ]
)

# Keywords that indicate the user wants address/location info
ADDRESS_KEYWORDS = [
    "address",
    "located",
    "location",
    "where is",
    "where's",
    "directions",
    "how to get",
    "find",
    "campus",
    "map",
    "maps",
    "situated",
    "place",
    "building",
    "postcode",
    "zip code",
]

# Keywords to confirm it's a university query
UNIVERSITY_KEYWORDS = [
    "university",
    "college",
    "institute",
    "school of",
    "faculty",
    "campus",
    "mit",
    "eth",
    "ucl",
    "epfl",
]


class Filter:
    class Valves(BaseModel):
        """Admin-configurable settings."""

        google_maps_api_key: str = Field(
            default="",
            description=(
                "Google Maps API key with Places API (New) enabled. "
                "Get one at https://console.cloud.google.com"
            ),
        )
        max_results: int = Field(
            default=1,
            description="Number of Places results to return (1–3). Usually 1 is sufficient.",
        )
        language_code: str = Field(
            default="en",
            description="Language for returned place details (e.g. 'en', 'fr', 'de').",
        )
        debug: bool = Field(
            default=False,
            description="Append a debug block to the system prompt showing what was matched.",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_address_query(self, text: str) -> bool:
        """Return True if the message looks like an address/location question."""
        lower = text.lower()
        has_address_kw = any(kw in lower for kw in ADDRESS_KEYWORDS)
        has_university_kw = any(kw in lower for kw in UNIVERSITY_KEYWORDS)
        return has_address_kw and has_university_kw

    def _search_place(self, query: str) -> Optional[dict]:
        """
        Call the Google Maps Places API (New) Text Search endpoint.
        Returns the first place result dict, or None on failure.

        Uses POST with a JSON body and X-Goog-FieldMask header to control
        which fields are returned (and billed).
        """
        if not self.valves.google_maps_api_key:
            return None

        payload = json.dumps(
            {
                "textQuery": query,
                "maxResultCount": self.valves.max_results,
                "languageCode": self.valves.language_code,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            PLACES_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.valves.google_maps_api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        places = data.get("places", [])
        return places[0] if places else None

    def _format_place(self, place: dict) -> str:
        """Render a Places API result as a clean, LLM-readable context block."""
        name = place.get("displayName", {}).get("text", "Unknown")
        address = place.get("formattedAddress", "Not available")
        loc = place.get("location", {})
        lat = loc.get("latitude", "?")
        lng = loc.get("longitude", "?")
        maps = place.get("googleMapsUri", "")
        website = place.get("websiteUri", "")
        phone = place.get("internationalPhoneNumber", "")

        lines = [
            "--- UNIVERSITY ADDRESS (Google Maps Places API) ---",
            f"Name:             {name}",
            f"Formatted address:{address}",
            f"Coordinates:      {lat}, {lng}",
        ]
        if phone:
            lines.append(f"Phone:            {phone}")
        if website:
            lines.append(f"Website:          {website}")
        if maps:
            lines.append(f"Google Maps URL:  {maps}")
        lines.append("--- END ADDRESS ---")
        return "\n".join(lines)

    # ── Inlet ─────────────────────────────────────────────────────────────────

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """
        Pre-LLM intercept.

        Checks the latest user message for an address/location question
        about a university. If detected, calls the Google Maps Places API
        and injects the result into the system prompt so the LLM can give
        an accurate, sourced answer.

        The raw user query is passed directly to Places API Text Search
        (e.g. "Where is MIT located?" → query: "MIT university address").
        This gives the best results without needing a hardcoded lookup table.
        """
        if not self.valves.google_maps_api_key:
            return body  # No API key set — pass through silently

        messages = body.get("messages", [])
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )

        if not last_user or not self._is_address_query(last_user):
            return body  # Not an address query — pass through

        # Build a clean search query from the user message
        search_query = f"{last_user} university address"

        try:
            place = self._search_place(search_query)
            if place:
                context = self._format_place(place)
            else:
                context = (
                    "--- UNIVERSITY ADDRESS ---\n"
                    f"No result found on Google Maps for: '{last_user}'\n"
                    "--- END ---"
                )
        except Exception as exc:
            context = (
                "--- UNIVERSITY ADDRESS ---\n"
                f"Google Maps API error: {exc}\n"
                "--- END ---"
            )

        if self.valves.debug:
            context += f"\n[DEBUG] Search query sent to Places API: '{search_query}'"

        # Inject into system prompt
        enrichment = f"\n\n{context}"
        system_msg = next(
            (m for m in body["messages"] if m.get("role") == "system"), None
        )
        if system_msg:
            system_msg["content"] += enrichment
        else:
            body["messages"].insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "You are a helpful university assistant. "
                        "Use the address information below when answering the user."
                        + enrichment
                    ),
                },
            )

        return body

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """Pass-through — no modification to the LLM response."""
        return body
