"""UNITAID scraper.

UNITAID has two distinct opportunity pages:
  1. https://unitaid.org/calls-for-proposals/      — large grants (US$10-30M)
  2. https://unitaid.org/consultancies-and-rfps/   — RFPs for consultancy services

Both list opportunities with title links pointing to detail pages. We drill
into each detail page to extract:
  - Call status (Open / Closed) — items with status=Closed are excluded here
  - Closing date / deadline
  - Full description text (used downstream for country detection and scoring)

Filtering by Call status is critical — the listing pages show both open and
closed CFPs, and many remain visible months after closing.
"""

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ._common import http_get, opportunity

PAGES = [
    ("https://unitaid.org/calls-for-proposals/", "/call-for-proposal/"),
    ("https://unitaid.org/consultancies-and-rfps/", "/consultancy-rfp/"),
]

DETAIL_SLUGS = re.compile(
    r"/(call-for-proposal|consultancy-rfp|consultancies-and-rfp|rfp-\d+)/",
    re.IGNORECASE,
)

# Direct extractors for UNITAID detail pages
CALL_STATUS_RE = re.compile(
    r"Call\s+status\s+(Open|Closed|Active|Expired)",
    re.IGNORECASE,
)
DEADLINE_RE = re.compile(
    r"(?:Closing\s+date|Deadline)\s+"
    r"(?:[A-Z][a-z]+(?:day)?,?\s+)?"  # optional weekday
    r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
    re.IGNORECASE,
)
DATE_POSTED_RE = re.compile(
    r"Date\s+posted\s+(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
    re.IGNORECASE,
)


def fetch() -> list[dict]:
    out = []
    seen_urls = set()
    listing_urls = {p[0].rstrip("/") for p in PAGES}

    for page_url, _ in PAGES:
        r = http_get(page_url)
        if not r:
            continue

        soup = BeautifulSoup(r.text, "lxml")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not DETAIL_SLUGS.search(href):
                continue
            full_url = urljoin(page_url, href)
            if full_url in seen_urls:
                continue
            if full_url.rstrip("/") in listing_urls:
                continue
            seen_urls.add(full_url)

            title = a.get_text(" ", strip=True)
            generic = {"learn more", "read more", "more info", "details",
                       "view more", "view details", "see more"}
            if title.lower().strip() in generic or len(title) < 15:
                title = None
                ancestor = a.parent
                for _ in range(5):
                    if ancestor is None:
                        break
                    h = ancestor.find(["h1", "h2", "h3", "h4", "h5"])
                    if h:
                        candidate = h.get_text(" ", strip=True)
                        if candidate and len(candidate) >= 15:
                            title = candidate
                            break
                    ancestor = ancestor.parent

            if not title or len(title) < 10:
                continue

            # Drill into detail page
            detail_r = http_get(full_url)
            if not detail_r:
                # Skip items we can't drill into — better to miss than to
                # surface stale/closed RFPs
                continue

            detail_soup = BeautifulSoup(detail_r.text, "lxml")
            full_text = detail_soup.get_text(" ", strip=True)

            # Status check — skip if Closed
            status_match = CALL_STATUS_RE.search(full_text)
            if status_match:
                status = status_match.group(1).lower()
                if status in {"closed", "expired"}:
                    continue  # skip closed RFPs entirely

            # Extract deadline
            deadline = None
            dl_match = DEADLINE_RE.search(full_text)
            if dl_match:
                deadline = _parse_date(dl_match.group(1))

            # Build description from main content paragraphs
            paragraphs = []
            for p in detail_soup.find_all("p"):
                pt = p.get_text(" ", strip=True)
                if pt and len(pt) > 30:
                    paragraphs.append(pt)
            description = " ".join(paragraphs)[:3000]

            out.append(opportunity(
                source="UNITAID",
                title=title,
                url=full_url,
                description=description,
                deadline=deadline,
            ))

    return out


def _parse_date(s: str) -> str | None:
    from dateutil import parser as date_parser
    try:
        return date_parser.parse(s, dayfirst=True).date().isoformat()
    except Exception:
        return None
