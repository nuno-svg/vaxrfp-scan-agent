"""Africa CDC bids scraper.

Africa CDC publishes each tender as a /opportunity/<slug>/ page. The listing
page at /supply-chain-division/opportunities/ links to each one. We collect
those links, then drill into each detail page to extract:
  - Full description text (used downstream for country detection and scoring)
  - Deadline (parsed from "on or before <date>" or "Deadline <date>")

Detail-page drill-down is essential: listing cards often only show the title,
not the deadline. Without it we'd surface long-closed tenders.
"""

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ._common import http_get, opportunity

PAGE_URL = "https://africacdc.org/supply-chain-division/opportunities/"

OPPORTUNITY_SLUG = re.compile(r"/opportunity/[a-z0-9-]+/?$", re.IGNORECASE)

# Africa CDC bid notices use these phrasings for the closing date
DEADLINE_RE = re.compile(
    r"(?:on\s+or\s+before|deadline)\s*:?\s*"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+"
    r"\d{4})",
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

        # Drill into detail page for full description + deadline
        deadline = None
        description = ""
        detail_r = http_get(full_url)
        if detail_r:
            detail_soup = BeautifulSoup(detail_r.text, "lxml")
            full_text = detail_soup.get_text(" ", strip=True)

            # Extract deadline
            m = DEADLINE_RE.search(full_text)
            if m:
                cleaned = re.sub(r"(st|nd|rd|th)", "",
                                 m.group(1), flags=re.IGNORECASE)
                deadline = _parse_date(cleaned)

            # Build description from main content
            main = detail_soup.find("main") or detail_soup.find("article") or detail_soup
            paragraphs = []
            for p in main.find_all("p"):
                pt = p.get_text(" ", strip=True)
                if pt and len(pt) > 30:
                    paragraphs.append(pt)
            description = " ".join(paragraphs)[:3000]

        out.append(opportunity(
            source="Africa CDC",
            title=title,
            url=full_url,
            description=description,
            country=None,  # let downstream country detector infer from text
            deadline=deadline,
        ))

    return out


def _parse_date(s: str) -> str | None:
    from dateutil import parser as date_parser
    try:
        return date_parser.parse(s, dayfirst=True).date().isoformat()
    except Exception:
        return None
