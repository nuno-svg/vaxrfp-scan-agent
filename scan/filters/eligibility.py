"""Bidder eligibility filter — Swiss consultancy.

Swiss entities are typically eligible for:
  - All UN, GAVI, UNITAID, GFATM, WHO (Switzerland is host country for most)
  - All EU/EuropeAid (Switzerland has bilateral agreements)
  - World Bank, IFC, EIB, EBRD
  - Most bilateral development agencies (SDC home, GIZ, AFD, FCDO)

Flag for review when:
  - USAID/US government (Buy American provisions, sometimes US-only)
  - Specific RFPs that explicitly restrict to host-country entities
"""

# Phrases that suggest restrictive bidder eligibility
RESTRICTION_FLAGS = [
    "us entities only",
    "u.s. entities only",
    "american companies only",
    "buy american",
    "registered in the country",
    "national bidders only",
    "local entities only",
    "local firms only",
    "domestic suppliers only",
    "host country firms",
    "Gavi-eligible countries only",  # Sometimes appears
    "set-aside for",
]


def check_eligibility(title: str, description: str, source: str) -> dict:
    """Check whether Swiss bidder eligibility is at risk.

    Returns dict:
      - eligible_likely (bool)
      - requires_review (bool)
      - reason (str)
    """
    text = f"{title} {description}".lower()

    # USAID / US government sources always flagged for review
    if source in {"USAID", "SAM.gov", "State Dept"}:
        return {
            "eligible_likely": True,
            "requires_review": True,
            "reason": "US-funded RFP — verify Swiss bidder eligibility (Buy American provisions may apply)",
        }

    for phrase in RESTRICTION_FLAGS:
        if phrase.lower() in text:
            return {
                "eligible_likely": False,
                "requires_review": True,
                "reason": f"Restrictive eligibility phrase detected: '{phrase}'",
            }

    return {"eligible_likely": True, "requires_review": False, "reason": ""}
