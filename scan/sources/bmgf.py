"""BMGF Grand Challenges (Bill & Melinda Gates Foundation) scraper.

The Gates Foundation publishes RFPs primarily through Grand Challenges
(grandchallenges.org and gcgh.grandchallenges.org). RFPs are listed as
headed entries on /grant-opportunities — each h2/h3 is an opportunity name
and a parent link goes to the detail page.

We extract opportunities by walking headings and finding their associated
links + descriptions.
"""

import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from ._common import http_get, opportunity

PAGES = [
    "https://gcgh.grandchallenges.org/grant-opportunities",
    "https://www.grandchallenges.org/grant-opportunities",
]


def fetch() -> list[dict]:
    out = []
    seen_titles = set()

    for page_url in PAGES:
        r = http_get(page_url)
        if not r:
            continue

        soup = BeautifulSoup(r.text, "lxml")

        # Each opportunity is typically a heading; walk all h2/h3 in main content
        for h in soup.find_all(["h2", "h3"]):
            title = h.get_text(" ", strip=True)
            if not title or len(title) < 25:
                continue
            # Skip section headers
            skip_phrases = [
                "grant opportunities", "great ideas", "explore", "where to go",
                "about", "our approach", "our team", "newsletter", "subscribe",
                "related", "share this",
            ]
            if any(s in title.lower() for s in skip_phrases):
                continue
            if title in seen_titles:
                continue
            seen_titles.add(title)

            # Find the detail link: nearest <a> in the heading or its container
            detail_url = page_url
            link = h.find("a", href=True)
            if not link:
                # Look in parent container
                container = h.parent
                for _ in range(3):
                    if container is None:
                        break
                    link = container.find("a", href=True)
                    if link:
                        break
                    container = container.parent
            if link:
                detail_url = urljoin(page_url, link["href"])

            # Description: paragraph immediately following the heading
            description = ""
            sibling = h.find_next_sibling()
            for _ in range(3):
                if sibling is None:
                    break
                if sibling.name == "p":
                    description = sibling.get_text(" ", strip=True)
                    break
                sibling = sibling.find_next_sibling()

            # Drill into detail page for deadline if URL is non-trivial
            deadline = None
            if detail_url != page_url and detail_url not in PAGES:
                detail_r = http_get(detail_url)
                if detail_r:
                    detail_text = BeautifulSoup(
                        detail_r.text, "lxml"
                    ).get_text(" ", strip=True)
                    m = re.search(
                        r"(?:application\s+deadline|deadline|closing|submit\s+by|due)[:\s]+"
                        r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
                        detail_text, re.IGNORECASE,
                    )
                    if m:
                        from dateutil import parser as date_parser
                        try:
                            deadline = date_parser.parse(
                                m.group(1), dayfirst=True
                            ).date().isoformat()
                        except Exception:
                            pass
                    # Use detail-page description if richer
                    if len(detail_text) > len(description):
                        description = detail_text[:2500]

            out.append(opportunity(
                source="BMGF",
                title=title,
                url=detail_url,
                description=description[:2500],
                deadline=deadline,
            ))

    return out
