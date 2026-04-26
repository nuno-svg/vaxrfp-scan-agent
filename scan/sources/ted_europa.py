"""TED Europa (Tenders Electronic Daily) scraper.

TED is the EU's public procurement portal. Its v3 search API is open
(no API key for read access) and covers:
  - All EU public procurement above thresholds
  - EuropeAid / external aid programmes (relevant for Africa & ME)
  - EIB-funded projects (since EIB notices flow through TED)

We query for ACTIVE notices matching CPV codes for vaccines, health
consultancy, and business/management consultancy. The downstream gates and
keyword scoring filter further to keep only vaccine supply-chain consulting.
"""

import requests
from urllib.parse import quote

API_URL = "https://api.ted.europa.eu/v3/notices/search"

# CPV codes most relevant for vaccine supply-chain consultancy
CPV_CODES = [
    "33651600",  # Vaccines
    "33000000",  # Medical equipments, pharmaceuticals (broad)
    "73000000",  # Research and development services
    "79400000",  # Business and management consultancy
    "79410000",  # Business and management consultancy services
    "79411000",  # General management consultancy services
    "79419000",  # Evaluation consultancy services
    "85100000",  # Health services
    "75230000",  # Provision of services to the community
]

# Build expert query: notice type = contract notice (open competition),
# active scope, in any of our CPV codes
def _build_query() -> str:
    cpv_clause = " OR ".join(f'classification-cpv="{c}"' for c in CPV_CODES)
    notice_clause = '(notice-type="cn-standard" OR notice-type="cn-social")'
    return f"{notice_clause} AND ({cpv_clause})"


def fetch() -> list[dict]:
    payload = {
        "query": _build_query(),
        "fields": [
            "publication-number",
            "notice-title",
            "buyer-name",
            "deadline-receipt-tender-date-lot",
            "place-of-performance",
            "publication-date",
            "description-lot",
            "classification-cpv",
        ],
        "page": 1,
        "limit": 100,
        "scope": "ACTIVE",
    }
    try:
        r = requests.post(API_URL, json=payload,
                          headers={"User-Agent": "vaxrfp-scan-agent/1.0"},
                          timeout=30)
        if r.status_code != 200:
            print(f"[ted] HTTP {r.status_code}: {r.text[:200]}")
            return []
        data = r.json()
    except Exception as e:
        print(f"[ted] exception: {e}")
        return []

    out = []
    for n in data.get("notices") or []:
        pub_num = n.get("publication-number")
        if not pub_num:
            continue

        # Title: prefer English, fall back to any language
        title = _pick_lang(n.get("notice-title"))
        if not title:
            continue

        # Buyer name as part of context
        buyer = _pick_lang(n.get("buyer-name")) or ""

        # Description (often in the lot field)
        description_text = _pick_lang(n.get("description-lot")) or ""
        full_description = f"{buyer}. {description_text}".strip(". ")

        # Place of performance is a list of country/region codes
        pop = n.get("place-of-performance") or []
        country = _normalise_country(pop[0]) if pop else None

        # Deadline (first lot's deadline if multiple)
        dl = n.get("deadline-receipt-tender-date-lot") or []
        deadline = dl[0][:10] if dl else None

        url = f"https://ted.europa.eu/en/notice/{pub_num}"

        out.append({
            "source": "TED",
            "title": title.strip(),
            "url": url,
            "description": full_description[:2000],
            "country": country,
            "deadline": deadline,
            "value_usd": None,
            "raw": {"ted_publication_number": pub_num},
        })

    return out


def _pick_lang(field) -> str | None:
    """TED multi-language fields look like {"eng": ["..."], "fra": ["..."]}."""
    if field is None:
        return None
    if isinstance(field, str):
        return field
    if isinstance(field, list):
        return field[0] if field else None
    if isinstance(field, dict):
        # Prefer English
        for lang in ["eng", "ENG", "en", "EN"]:
            if lang in field and field[lang]:
                v = field[lang]
                return v[0] if isinstance(v, list) else v
        # Fall back to first available
        for v in field.values():
            if v:
                return v[0] if isinstance(v, list) else v
    return None


# TED uses ISO 3166-1 alpha-3 codes, sometimes NUTS regions
_ISO3_TO_ISO2 = {
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
    "CHE": "CH", "DEU": "DE", "FRA": "FR", "GBR": "GB", "BEL": "BE",
    "ITA": "IT", "ESP": "ES", "PRT": "PT", "NLD": "NL", "AUT": "AT",
    "SWE": "SE", "DNK": "DK", "FIN": "FI", "NOR": "NO", "ISL": "IS",
    "ARE": "AE", "BHR": "BH", "IRN": "IR", "IRQ": "IQ", "ISR": "IL",
    "JOR": "JO", "KWT": "KW", "LBN": "LB", "OMN": "OM", "PSE": "PS",
    "QAT": "QA", "SAU": "SA", "SYR": "SY", "TUR": "TR", "YEM": "YE",
}


def _normalise_country(code: str) -> str | None:
    if not code or not isinstance(code, str):
        return None
    code = code.upper().strip()
    if len(code) == 2:
        return code
    if len(code) == 3:
        return _ISO3_TO_ISO2.get(code, code)
    # NUTS regions like "BE10" — keep first 2 chars (country prefix)
    if len(code) >= 4 and code[:2].isalpha():
        return code[:2]
    return None
