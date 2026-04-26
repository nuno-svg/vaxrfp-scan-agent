"""Manufacturer signal scraper using Google News RSS.

Vaccine manufacturers (Biovac, Afrigen, EVA Pharma, etc.) don't publish
RFPs themselves on a single page — their signals come from press releases
distributed across many partner sites (EIB, IFC, Sanofi, Pfizer, BMGF,
specialised pharma news outlets).

Google News RSS aggregates all of these via a single endpoint and is free.
We query for each manufacturer + a relevance qualifier ("vaccine OR
manufacturing OR partnership OR financing"), then filter to the last 90 days.

These items are NOT formal RFPs — they're signals that a manufacturer just
secured funding (= upcoming supply-chain procurement), signed a tech-transfer
deal (= consultancy needs ahead), or opened a new facility (= validation/
commissioning work). The dashboard routes them to the Signals tab.

Items here have:
  - source = "Signal:<Manufacturer>"
  - deadline = None (these aren't RFPs with deadlines)
  - The orchestrator's gate logic still applies (must mention vaccine/supply-chain
    AND a service-related word — many press releases will pass naturally).
"""

import re
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
REQUEST_DELAY_SEC = 1.5  # polite spacing — Google News throttles burst queries

# Manufacturers to monitor and their search queries
MANUFACTURERS = [
    ("Biovac",     '"Biovac" (vaccine OR manufacturing OR partnership OR financing)'),
    ("Afrigen",    '"Afrigen" (vaccine OR mRNA OR manufacturing OR transfer)'),
    ("EVA Pharma", '"EVA Pharma" (vaccine OR mRNA OR manufacturing OR partnership)'),
    ("Aspen Pharmacare", '"Aspen Pharmacare" (vaccine OR manufacturing OR partnership)'),
    ("Institut Pasteur Dakar", '"Institut Pasteur" Dakar (vaccine OR manufacturing)'),
    ("BioNTech Rwanda", '"BioNTech" Rwanda (vaccine OR mRNA OR factory)'),
]

MAX_AGE_DAYS = 90  # signals older than this are stale


def fetch() -> list[dict]:
    out = []
    seen_titles = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    for label, query in MANUFACTURERS:
        params = {
            "q": query,
            "hl": "en",
            "gl": "US",
            "ceid": "US:en",
        }
        try:
            r = requests.get(
                GOOGLE_NEWS_RSS,
                params=params,
                headers={"User-Agent": "vaxrfp-scan-agent/1.0"},
                timeout=20,
            )
            # One retry on 5xx — Google News occasionally throttles bursts
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3)
                r = requests.get(
                    GOOGLE_NEWS_RSS, params=params,
                    headers={"User-Agent": "vaxrfp-scan-agent/1.0"},
                    timeout=20,
                )
            if r.status_code != 200:
                print(f"[signals:{label}] HTTP {r.status_code}")
                time.sleep(REQUEST_DELAY_SEC)
                continue
        except Exception as e:
            print(f"[signals:{label}] exception: {e}")
            time.sleep(REQUEST_DELAY_SEC)
            continue

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            print(f"[signals:{label}] XML parse error: {e}")
            time.sleep(REQUEST_DELAY_SEC)
            continue

        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            desc_el = item.find("description")

            if title_el is None or link_el is None:
                continue

            title = (title_el.text or "").strip()
            link = (link_el.text or "").strip()
            if not title or not link or title in seen_titles:
                continue

            pub_dt = None
            if pub_el is not None and pub_el.text:
                try:
                    pub_dt = parsedate_to_datetime(pub_el.text)
                except (TypeError, ValueError):
                    pub_dt = None

            if pub_dt and pub_dt < cutoff:
                continue

            seen_titles.add(title)

            description = (desc_el.text or "").strip() if desc_el is not None else ""
            description = re.sub(r"<[^>]+>", " ", description)
            description = re.sub(r"\s+", " ", description).strip()

            out.append({
                "source": f"Signal:{label}",
                "title": title,
                "url": link,
                "description": description[:1500],
                "country": None,
                "deadline": None,
                "value_usd": None,
                "raw": {
                    "manufacturer": label,
                    "published": pub_dt.isoformat() if pub_dt else None,
                    "signal_type": "manufacturer",
                },
            })

        time.sleep(REQUEST_DELAY_SEC)

    return out
