"""UNITAID scraper.

UNITAID has two distinct opportunity pages:
  1. https://unitaid.org/calls-for-proposals/      — large grants (US$10-30M)
  2. https://unitaid.org/consultancies-and-rfps/   — RFPs for consultancy services

Both pages list opportunities with title links pointing to detail pages.
We extract from both.
"""

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ._common import http_get, opportunity

PAGES = [
    ("https://unitaid.org/calls-for-proposals/", "/call-for-proposal/"),
    ("https://unitaid.org/consultancies-and-rfps/", "/consultancy-rfp/"),
]

# Detail-page URL slugs we accept
DETAIL_SLUGS = re.compile(
    r"/(call-for-proposal|consultancy-rfp|consultancies-and-rfp|rfp-\d+)/",
    re.IGNORECASE,
)

DEADLINE_RE = re.compile(
    r"(?:closing\s+date|deadline|by|before)[^.]{0,80}?"
    r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
    re.IGNORECASE,
)


def fetch() -> list[dict]:
    out = []
    seen_urls = set()

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
            # Skip the listing pages themselves
            if full_url.rstrip("/") in {p[0].rstrip("/") for p in PAGES}:
                continue
            seen_urls.add(full_url)

            title = a.get_text(" ", strip=True)

            # If link text is generic ('Learn more', 'Read more', etc.),
            # walk up to find the actual title in a sibling heading.
            generic_phrases = {"learn more", "read more", "more info", "details",
                               "view more", "view details", "see more"}
            if title.lower().strip() in generic_phrases or len(title) < 15:
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

            # Description from the listing card (look at parent container)
            description = ""
            ancestor = a.parent
            for _ in range(4):
                if ancestor is None:
                    break
                for p in ancestor.find_all("p", limit=2):
                    pt = p.get_text(" ", strip=True)
                    if pt and len(pt) > 60:
                        description = pt
                        break
                if description:
                    break
                ancestor = ancestor.parent

            # Try to extract deadline from description text if present
            deadline = _extract_deadline(description)

            out.append(opportunity(
                source="UNITAID",
                title=title,
                url=full_url,
                description=description[:2000],
                deadline=deadline,
            ))

    return out


def _extract_deadline(text: str) -> str | None:
    if not text:
        return None
    m = DEADLINE_RE.search(text)
    if not m:
        return None
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(m.group(1), dayfirst=True).date().isoformat()
    except Exception:
        return None

