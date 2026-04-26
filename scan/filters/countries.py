"""Country detection from free text.

Used by scrapers that don't get a structured country field (UNITAID, GAVI,
Africa CDC, sometimes ReliefWeb). Returns ISO 3166-1 alpha-2 codes, or
special pseudo-codes for multi-country/regional scopes.

Special pseudo-codes (always start with underscore):
  _LMIC       Low- and middle-income countries (global LMIC scope)
  _SSA        Sub-Saharan Africa
  _AU         African Union / continental Africa
  _MENA       Middle East and North Africa
  _GLOBAL     Worldwide / no specific geography
"""

import re

# Regional / multi-country markers (checked first, before specific countries)
REGIONAL_MARKERS = [
    (r"\blow[\s-]+and[\s-]+middle[\s-]+income\s+countries?\b", "_LMIC"),
    (r"\bLMICs?\b", "_LMIC"),
    (r"\bsub[\s-]+saharan\s+africa\b", "_SSA"),
    (r"\bSSA\b", "_SSA"),
    (r"\bAfrican\s+continent\b", "_AU"),
    (r"\bcontinental\s+africa\b", "_AU"),
    (r"\bAfrican?\s+Union\b", "_AU"),
    (r"\bMiddle\s+East\s+and\s+North\s+Africa\b", "_MENA"),
    (r"\bMENA\b", "_MENA"),
    (r"\bGulf\s+(?:states|countries|region)\b", "_MENA"),
    (r"\bworldwide\b|\bglobal(?:ly)?\s+(?:health|access)\b", "_GLOBAL"),
]

# Country name → ISO-2 mapping. Restricted to countries in our scope
# (Africa, Switzerland, Middle East). Add more as needed.
COUNTRY_NAMES = {
    # Africa
    "angola": "AO", "benin": "BJ", "botswana": "BW", "burkina faso": "BF",
    "burundi": "BI", "cameroon": "CM", "cape verde": "CV", "cabo verde": "CV",
    "central african republic": "CF", "chad": "TD", "comoros": "KM",
    "republic of the congo": "CG", "congo-brazzaville": "CG",
    "democratic republic of the congo": "CD", "drc": "CD", "dr congo": "CD",
    "côte d'ivoire": "CI", "cote d'ivoire": "CI", "ivory coast": "CI",
    "djibouti": "DJ", "egypt": "EG", "equatorial guinea": "GQ", "eritrea": "ER",
    "eswatini": "SZ", "swaziland": "SZ", "ethiopia": "ET", "gabon": "GA",
    "gambia": "GM", "ghana": "GH", "guinea": "GN", "guinea-bissau": "GW",
    "kenya": "KE", "lesotho": "LS", "liberia": "LR", "libya": "LY",
    "madagascar": "MG", "malawi": "MW", "mali": "ML", "mauritania": "MR",
    "mauritius": "MU", "morocco": "MA", "mozambique": "MZ", "namibia": "NA",
    "niger": "NE", "nigeria": "NG", "rwanda": "RW",
    "são tomé and príncipe": "ST", "sao tome and principe": "ST",
    "senegal": "SN", "seychelles": "SC", "sierra leone": "SL", "somalia": "SO",
    "south africa": "ZA", "south sudan": "SS", "sudan": "SD",
    "tanzania": "TZ", "togo": "TG", "tunisia": "TN", "uganda": "UG",
    "zambia": "ZM", "zimbabwe": "ZW",
    # Switzerland (consultancy home market)
    "switzerland": "CH", "swiss": "CH",
    # Middle East
    "united arab emirates": "AE", "uae": "AE", "abu dhabi": "AE", "dubai": "AE",
    "bahrain": "BH", "iran": "IR", "iraq": "IQ", "israel": "IL",
    "jordan": "JO", "kuwait": "KW", "lebanon": "LB", "oman": "OM",
    "palestine": "PS", "qatar": "QA", "saudi arabia": "SA", "syria": "SY",
    "turkey": "TR", "türkiye": "TR", "yemen": "YE",
}

# ISO-3 → ISO-2 (used by TED, ReliefWeb)
ISO3_TO_ISO2 = {
    "AGO": "AO", "BEN": "BJ", "BWA": "BW", "BFA": "BF", "BDI": "BI",
    "CMR": "CM", "CPV": "CV", "CAF": "CF", "TCD": "TD", "COM": "KM",
    "COG": "CG", "COD": "CD", "CIV": "CI", "DJI": "DJ", "EGY": "EG",
    "GNQ": "GQ", "ERI": "ER", "SWZ": "SZ", "ETH": "ET", "GAB": "GA",
    "GMB": "GM", "GHA": "GH", "GIN": "GN", "GNB": "GW", "KEN": "KE",
    "LSO": "LS", "LBR": "LR", "LBY": "LY", "MDG": "MG", "MWI": "MW",
    "MLI": "ML", "MRT": "MR", "MUS": "MU", "MAR": "MA", "MOZ": "MZ",
    "NAM": "NA", "NER": "NE", "NGA": "NG", "RWA": "RW", "STP": "ST",
    "SEN": "SN", "SYC": "SC", "SLE": "SL", "SOM": "SO", "ZAF": "ZA",
    "SSD": "SS", "SDN": "SD", "TZA": "TZ", "TGO": "TG", "TUN": "TN",
    "UGA": "UG", "ZMB": "ZM", "ZWE": "ZW",
    # Switzerland & EU
    "CHE": "CH", "DEU": "DE", "FRA": "FR", "GBR": "GB", "BEL": "BE",
    "ITA": "IT", "ESP": "ES", "PRT": "PT", "NLD": "NL", "AUT": "AT",
    "SWE": "SE", "DNK": "DK", "FIN": "FI", "NOR": "NO", "ISL": "IS",
    "IRL": "IE", "POL": "PL", "CZE": "CZ", "HUN": "HU", "ROU": "RO",
    "GRC": "GR", "BGR": "BG", "HRV": "HR", "SVN": "SI", "SVK": "SK",
    "LTU": "LT", "LVA": "LV", "EST": "EE", "LUX": "LU", "MLT": "MT",
    "CYP": "CY",
    # Middle East
    "ARE": "AE", "BHR": "BH", "IRN": "IR", "IRQ": "IQ", "ISR": "IL",
    "JOR": "JO", "KWT": "KW", "LBN": "LB", "OMN": "OM", "PSE": "PS",
    "QAT": "QA", "SAU": "SA", "SYR": "SY", "TUR": "TR", "YEM": "YE",
}


def normalise_country_code(code) -> str | None:
    """Normalise any country code-like string to ISO-2.

    Accepts ISO-2 (returns as-is), ISO-3 (converts), NUTS region codes
    (returns the country prefix), or None.
    """
    if not code or not isinstance(code, str):
        return None
    code = code.upper().strip()
    if len(code) == 2 and code.isalpha():
        return code
    if len(code) == 3 and code.isalpha():
        return ISO3_TO_ISO2.get(code, code)
    # NUTS regions like "BE10", "DE21A" — country prefix is first 2 chars
    if len(code) >= 4 and code[:2].isalpha():
        return code[:2].upper()
    return None


def detect_country(text: str) -> str | None:
    """Detect country/region from free text.

    Strategy:
      1. Look for regional markers first (LMIC, SSA, MENA, etc.) — these
         take precedence because if text says "in LMICs including Nigeria",
         the project is multi-country, not Nigeria-specific.
      2. If no regional marker, look for first specific country name.
      3. Returns ISO-2 code, special _XXX pseudo-code, or None.
    """
    if not text:
        return None
    text_lower = text.lower()

    # Step 1: regional markers
    for pattern, code in REGIONAL_MARKERS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return code

    # Step 2: specific country names
    # Sort longest first to avoid "guinea" matching before "guinea-bissau"
    for name in sorted(COUNTRY_NAMES.keys(), key=len, reverse=True):
        # Word-boundary match
        if re.search(r"\b" + re.escape(name) + r"\b", text_lower):
            return COUNTRY_NAMES[name]

    return None
