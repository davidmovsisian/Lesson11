"""
Open WebUI Tool
===============

Looks up a place using Google Maps Places API (New)
and returns structured information including:

- Name
- Address
- Coordinates
- Website
- Phone Number
- Google Maps URL
- Place Types

Requirements:
- Google Maps Places API (New) enabled
- API key configured in Valves

"""

import json
import urllib.request
from typing import Dict, Any
from pydantic import BaseModel, Field

PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"

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


class Tools:
    class Valves(BaseModel):
        google_maps_api_key: str = Field(
            default="",
            description="Google Maps Places API key",
        )

        language_code: str = Field(
            default="en",
            description="Language code for returned place details",
        )

        max_results: int = Field(
            default=1,
            ge=1,
            le=5,
            description="Maximum number of results to request",
        )

        timeout_seconds: int = Field(
            default=8,
            ge=1,
            le=60,
            description="HTTP timeout in seconds",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _search_place(self, query: str) -> Dict[str, Any]:
        payload = json.dumps(
            {
                "textQuery": query,
                "maxResultCount": self.valves.max_results,
                "languageCode": self.valves.language_code,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            PLACES_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.valves.google_maps_api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=self.valves.timeout_seconds,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    async def google_place_lookup(
        self,
        place: str,
    ) -> Dict[str, Any]:
        """
        Look up a place using Google Maps Places API.
        Returns address and location information for any place.
        Use this tool when the user asks:

        - Where is a place?
        - What is the address of a place?
        - Directions to a place
        - Location of a university
        - Location of a company
        - Location of a landmark
        - Google Maps information

        Examples:
        - Where is found MIT?
        - What is the address of Stanford University
        - Directions to Eiffel Tower
        - Location of Google Headquarters
        - Location of Heathrow Airport

        :param place: Name of the place to search for.
        """

        print(f"google_place_lookup invoked with place {place}")
        if not self.valves.google_maps_api_key:
            return {
                "success": False,
                "error": "Google Maps API key is not configured.",
            }

        try:
            result = self._search_place(place)

            places = result.get("places", [])

            if not places:
                return {
                    "success": False,
                    "query": place,
                    "error": "No matching place found.",
                }

            p = places[0]

            location = p.get("location", {})
            print(
                json.dumps(
                    {
                        "name": p.get("displayName", {}).get("text"),
                        "address": p.get("formattedAddress"),
                        "latitude": p.get("location", {}).get("latitude"),
                        "longitude": p.get("location", {}).get("longitude"),
                        "website": p.get("websiteUri"),
                        "phone": p.get("internationalPhoneNumber"),
                        "maps_url": p.get("googleMapsUri"),
                        "types": p.get("types", []),
                    },
                    indent=2,
                )
            )

            return {
                "success": True,
                "query": place,
                "name": p.get("displayName", {}).get("text"),
                "address": p.get("formattedAddress"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "website": p.get("websiteUri"),
                "phone": p.get("internationalPhoneNumber"),
                "google_maps_url": p.get("googleMapsUri"),
                "types": p.get("types", []),
            }

        except Exception as exc:
            return {
                "success": False,
                "query": place,
                "error": str(exc),
            }
