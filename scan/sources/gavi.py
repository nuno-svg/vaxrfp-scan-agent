"""GAVI direct scraper.

Scrapes https://www.gavi.org/about-us/work-us/rfps-eois-and-consulting-opportunities

Strategy: GAVI publishes each RFP/EOI/RFQ as a standalone document-library page.
The URL slug always starts with rfp-, eoi-, rfi-, rfq-, itt-, or contains
"call-for-proposal". We find every such link on the page and extract surrounding
context (date heading + description paragraph) for each.
"""

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ._common import http_get, opportunity

PAGE_URL = "https://www.gavi.org/about-us/work-us/rfps-eois-and-consulting-opportunities"

# URL slug must contain one of these to qualify as an opportunity page
SLUG_PATTERNS = re.compile(
    r"/news/document-library/(rfp[-_]|eoi[-_]|rfi[-_]|rfq[-_]|itt[-_]|"
    r"invitation-to-tender|call-for-proposal|consultancy)",
    re.IGNORECASE,
)

# Date pattern like "8 May 2026" or "11 Mar 2026" appearing near a link
DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b",
    re.IGNORECASE,
)
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def fetch() -> list[dict]:
    r = http_get(PAGE_URL)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    out = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not SLUG_PATTERNS.search(href):
            continue
        full_url = urljoin(PAGE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue

        # Walk up the DOM looking for the nearest date heading and description
        deadline = None
        description = ""
        ancestor = a
        for _ in range(6):
            ancestor = ancestor.parent
            if ancestor is None:
                break
            block_text = ancestor.get_text(" ", strip=True)
            if not deadline:
                m = DATE_RE.search(block_text)
                if m:
                    deadline = _to_iso(int(m.group(1)),
                                       MONTHS[m.group(2).lower()[:3]],
                                       int(m.group(3)))
            # Find a sibling paragraph with substantive description
            if not description:
                for p in ancestor.find_all("p", limit=4):
                    pt = p.get_text(" ", strip=True)
                    if pt and len(pt) > 60 and "Privacy Notice" not in pt:
                        description = pt
                        break
            if deadline and description:
                break

        out.append(opportunity(
            source="GAVI",
            title=title,
            url=full_url,
            description=description[:2000],
            country=None,
            deadline=deadline,
        ))

    return out


def _to_iso(d: int, m: int, y: int) -> str | None:
    try:
        from datetime import date
        return date(y, m, d).isoformat()
    except Exception:
        return None

