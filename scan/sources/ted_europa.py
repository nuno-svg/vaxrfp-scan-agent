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

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from filters.countries import normalise_country_code

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
    # Restrict to notices published in the last 60 days — older notices
    # are almost certainly closed even if they still appear under scope=ACTIVE.
    # TED expects YYYYMMDD format or today(±N) for relative dates.
    date_clause = 'publication-date>=today(-60)'
    return f"{notice_clause} AND ({cpv_clause}) AND {date_clause}"


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
        country = normalise_country_code(pop[0]) if pop else None

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
