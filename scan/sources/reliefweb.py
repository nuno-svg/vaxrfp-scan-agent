"""ReliefWeb API scraper.

NOTE: As of 1 November 2025, ReliefWeb v2 requires a PRE-APPROVED appname.
Without approval, the API returns HTTP 403. To activate this source:

  1. Request an appname at https://apidoc.reliefweb.int/parameters#appname
  2. Once approved, set the GitHub Secret RELIEFWEB_APPNAME to your appname
  3. The workflow will pass it as an environment variable

Until then this scraper returns [] and logs a clear message so the rest of
the pipeline keeps running.

ReliefWeb (UN OCHA) aggregates procurement notices from many of our Tier 1/2
sources: GAVI, UNITAID, GFATM, WHO, UNICEF, Africa CDC, etc. Once activated,
this single source covers a large share of the pipeline.
"""

import os
from ._common import opportunity

API_URL = "https://api.reliefweb.int/v2/reports"
APP_NAME = os.environ.get("RELIEFWEB_APPNAME")  # set as GitHub Secret once approved

# Publishers we care about (ReliefWeb source names)
PUBLISHER_NAMES = [
    "Gavi, the Vaccine Alliance",
    "Unitaid",
    "Global Fund to Fight AIDS, Tuberculosis and Malaria",
    "World Health Organization",
    "UN Children's Fund",
    "Africa Centres for Disease Control and Prevention",
    "International Finance Corporation",
    "European Investment Bank",
    "Bill & Melinda Gates Foundation",
    "Coalition for Epidemic Preparedness Innovations",
    "Medicines Patent Pool",
]


def fetch() -> list[dict]:
    """Fetch up to 200 recent procurement notices from selected publishers."""
    if not APP_NAME:
        print("[reliefweb] RELIEFWEB_APPNAME env var not set — skipping. "
              "Request an approved appname at https://apidoc.reliefweb.int/parameters#appname")
        return []

    payload = {
        "profile": "list",
        "limit": 200,
        "fields": {
            "include": [
                "title", "url", "url_alias", "body",
                "country.name", "country.iso3", "source.name",
                "date.created", "format.name",
            ]
        },
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "format.name", "value": "Procurement"},
                {
                    "field": "source.name",
                    "value": PUBLISHER_NAMES,
                    "operator": "OR",
                },
            ],
        },
        "sort": ["date.created:desc"],
    }

    # ReliefWeb requires appname as URL query param even on POST
    import requests
    try:
        resp = requests.post(
            f"{API_URL}?appname={APP_NAME}",
            json=payload,
            timeout=30,
            headers={"User-Agent": APP_NAME, "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            print(f"[reliefweb] HTTP {resp.status_code}: {resp.text[:300]}")
            return []
        data = resp.json()
    except Exception as e:
        print(f"[reliefweb] exception: {e}")
        return []

    out = []
    for item in data.get("data", []):
        f = item.get("fields", {})
        title = f.get("title", "")
        url = f.get("url_alias") or f.get("url", "")
        description = (f.get("body") or "")[:3000]

        countries = f.get("country") or []
        country_iso = None
        if countries:
            iso3 = countries[0].get("iso3")
            country_iso = _iso3_to_iso2(iso3) if iso3 else None

        sources = f.get("source") or []
        source_name = sources[0].get("name", "ReliefWeb") if sources else "ReliefWeb"

        # ReliefWeb /reports doesn't carry a structured deadline.
        # The dashboard will render "—" until we extract it from body downstream.
        out.append(opportunity(
            source=_normalise_source(source_name),
            title=title,
            url=url,
            description=description,
            country=country_iso,
            deadline=None,
            raw={"reliefweb_id": item.get("id")},
        ))

    return out


def _normalise_source(name: str) -> str:
    """Map ReliefWeb publisher names to our canonical short names."""
    mapping = {
        "Gavi, the Vaccine Alliance": "GAVI",
        "Unitaid": "UNITAID",
        "UNITAID": "UNITAID",
        "Global Fund to Fight AIDS, Tuberculosis and Malaria": "GFATM",
        "Global Fund": "GFATM",
        "World Health Organization": "WHO",
        "UN Children's Fund": "UNICEF",
        "Africa Centres for Disease Control and Prevention": "Africa CDC",
        "International Finance Corporation": "IFC",
        "European Investment Bank": "EIB",
        "Bill & Melinda Gates Foundation": "BMGF",
        "Coalition for Epidemic Preparedness Innovations": "CEPI",
        "Medicines Patent Pool": "MPP",
    }
    return mapping.get(name, name)


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
    "CHE": "CH",
    "ARE": "AE", "BHR": "BH", "IRN": "IR", "IRQ": "IQ", "ISR": "IL",
    "JOR": "JO", "KWT": "KW", "LBN": "LB", "OMN": "OM", "PSE": "PS",
    "QAT": "QA", "SAU": "SA", "SYR": "SY", "TUR": "TR", "YEM": "YE",
}


def _iso3_to_iso2(iso3: str) -> str | None:
    return _ISO3_TO_ISO2.get(iso3.upper())
