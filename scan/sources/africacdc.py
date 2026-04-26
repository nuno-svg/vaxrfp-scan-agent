"""Africa CDC bids scraper.

Africa CDC publishes each tender as a /opportunity/<slug>/ page. The /bids/
listing page links to each opportunity. We collect all such links and extract
title and any deadline visible in the listing card.
"""

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ._common import http_get, opportunity

PAGE_URL = "https://africacdc.org/supply-chain-division/opportunities/"

OPPORTUNITY_SLUG = re.compile(r"/opportunity/[a-z0-9-]+/?$", re.IGNORECASE)

DEADLINE_RE = re.compile(
    r"(?:on\s+or\s+before|deadline|closing|by)\s+"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
    re.IGNORECASE,
)


def fetch() -> list[dict]:
    r = http_get(PAGE_URL)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    out = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not OPPORTUNITY_SLUG.search(href):
            continue
        full_url = urljoin(PAGE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 10:
            continue

        description = ""
        deadline = None
        ancestor = a.parent
        for _ in range(5):
            if ancestor is None:
                break
            block_text = ancestor.get_text(" ", strip=True)[:1500]
            if not deadline:
                m = DEADLINE_RE.search(block_text)
                if m:
                    cleaned = re.sub(r"(st|nd|rd|th)", "", m.group(1), flags=re.IGNORECASE)
                    deadline = _parse_date(cleaned)
            if not description and len(block_text) > 100:
                description = block_text
            if deadline and description:
                break
            ancestor = ancestor.parent

        out.append(opportunity(
            source="Africa CDC",
            title=title,
            url=full_url,
            description=description[:2000],
            country="_AU",
            deadline=deadline,
        ))

    return out


def _parse_date(s: str) -> str | None:
    from dateutil import parser as date_parser
    try:
        return date_parser.parse(s, dayfirst=True).date().isoformat()
    except Exception:
        return None
