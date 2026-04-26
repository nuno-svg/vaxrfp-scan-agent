"""CEPI procurement tenders scraper.

CEPI (Coalition for Epidemic Preparedness Innovations) publishes operational
support tenders at https://cepi.net/procurement-tenders. The page often
shows "From time to time, we publish tenders" — meaning empty most of the
time. When tenders exist, they appear as headed entries linking to detail
pages.

Returns 0 items when the page has no active tenders. That's expected.
"""

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ._common import http_get, opportunity

PAGE_URL = "https://cepi.net/procurement-tenders"

# CEPI tender detail slugs follow various patterns; we accept anything under
# the procurement-tenders subtree that isn't the listing page itself.
TENDER_LINK = re.compile(
    r"/(procurement-tenders|tender|rfp|rfx|rfq)/[a-z0-9-]+",
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
        if not TENDER_LINK.search(href):
            continue
        full_url = urljoin(PAGE_URL, href)
        if full_url in seen_urls:
            continue
        # Skip the listing page itself
        if full_url.rstrip("/").endswith("/procurement-tenders"):
            continue
        seen_urls.add(full_url)

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 15:
            # Walk up to find the title in a heading
            ancestor = a.parent
            for _ in range(4):
                if ancestor is None:
                    break
                h = ancestor.find(["h2", "h3", "h4"])
                if h:
                    candidate = h.get_text(" ", strip=True)
                    if candidate and len(candidate) >= 15:
                        title = candidate
                        break
                ancestor = ancestor.parent

        if not title or len(title) < 10:
            continue

        # Drill into detail page for description and deadline if available
        description = ""
        deadline = None
        detail_r = http_get(full_url)
        if detail_r:
            ds = BeautifulSoup(detail_r.text, "lxml")
            full_text = ds.get_text(" ", strip=True)
            description = full_text[:2000]
            # Generic deadline patterns
            m = re.search(
                r"(?:deadline|closing\s+date|submit\s+by|due)[:\s]+"
                r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
                full_text, re.IGNORECASE,
            )
            if m:
                from dateutil import parser as date_parser
                try:
                    deadline = date_parser.parse(m.group(1), dayfirst=True).date().isoformat()
                except Exception:
                    pass

        out.append(opportunity(
            source="CEPI",
            title=title,
            url=full_url,
            description=description,
            deadline=deadline,
        ))

    return out
