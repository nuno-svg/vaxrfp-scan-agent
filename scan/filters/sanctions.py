"""Sanctions filter — exclude RFPs targeting sanctioned jurisdictions.

Lists synthesise UN, EU and OFAC comprehensive sanctions as of April 2026.
Review quarterly against:
  - https://data.europa.eu/apps/eusanctionstracker/
  - https://www.un.org/securitycouncil/sanctions/information
  - https://sanctionslist.ofac.treas.gov/
"""

# Hard exclusion — no RFPs accepted for these jurisdictions
SANCTIONED_HARD = {
    "KP": "North Korea",
    "IR": "Iran",
    "SY": "Syria",
    "CU": "Cuba",
    "RU": "Russia",
    "BY": "Belarus",
    # Occupied Ukrainian territories — flagged at country level even though formally UA
    "_CRIMEA": "Crimea (occupied)",
    "_DONETSK": "Donetsk (occupied)",
    "_LUHANSK": "Luhansk (occupied)",
}

# Partial sanctions — flag for human review, do not auto-exclude
SANCTIONED_REVIEW = {
    "YE": "Yemen (Houthi-controlled areas under sanction)",
    "LB": "Lebanon (Hezbollah-linked entities)",
    "SD": "Sudan (partial sanctions)",
    "LY": "Libya (arms embargo, humanitarian generally permitted)",
}

# Country name aliases for free-text matching when ISO code is missing
NAME_ALIASES_HARD = {
    "north korea": "KP", "dprk": "KP", "democratic people's republic of korea": "KP",
    "iran": "IR", "islamic republic of iran": "IR",
    "syria": "SY", "syrian arab republic": "SY",
    "cuba": "CU",
    "russia": "RU", "russian federation": "RU",
    "belarus": "BY",
    "crimea": "_CRIMEA", "donetsk": "_DONETSK", "luhansk": "_LUHANSK",
}

NAME_ALIASES_REVIEW = {
    "yemen": "YE",
    "lebanon": "LB",
    "sudan": "SD",
    "libya": "LY",
}


def check_sanctions(country_iso: str | None, free_text: str = "") -> dict:
    """Return sanctions classification for an RFP.

    Returns dict with:
      - sanctioned (bool): hard exclude
      - requires_review (bool): partial sanctions, flag for human
      - reason (str): explanation
    """
    text_lower = (free_text or "").lower()

    # Check ISO code first
    if country_iso and country_iso.upper() in SANCTIONED_HARD:
        return {
            "sanctioned": True,
            "requires_review": False,
            "reason": f"Hard sanctions: {SANCTIONED_HARD[country_iso.upper()]}",
        }
    if country_iso and country_iso.upper() in SANCTIONED_REVIEW:
        return {
            "sanctioned": False,
            "requires_review": True,
            "reason": f"Partial sanctions: {SANCTIONED_REVIEW[country_iso.upper()]}",
        }

    # Fall back to free-text aliases
    for alias, code in NAME_ALIASES_HARD.items():
        if alias in text_lower:
            return {
                "sanctioned": True,
                "requires_review": False,
                "reason": f"Hard sanctions (text match): {SANCTIONED_HARD[code]}",
            }
    for alias, code in NAME_ALIASES_REVIEW.items():
        if alias in text_lower:
            return {
                "sanctioned": False,
                "requires_review": True,
                "reason": f"Partial sanctions (text match): {SANCTIONED_REVIEW[code]}",
            }

    return {"sanctioned": False, "requires_review": False, "reason": ""}
