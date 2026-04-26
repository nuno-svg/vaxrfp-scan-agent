"""Donor-side signal scraper using Google News RSS.

Different from manufacturer_signals.py: those track when a vaccine manufacturer
secures funding or signs a deal (downstream procurement signal). This module
tracks donors and programmes that DIRECTLY commission consultancy work —
GIZ, SaVax, KfW, AFD, SDC — but whose own websites either block scrapers
(GIZ has Cloudflare WAF returning 503), or don't expose RFPs in machine-
readable format.

Filter strategy is STRICTER than manufacturer signals:
  - Title or description must mention "tender", "RFP", "consultancy",
    "advisory", "expression of interest", "call for proposals", "procurement",
    "evaluation", or similar service-procurement keywords.
  - Stale items (>180 days) excluded — donor announcements have longer
    lead times than manufacturer news.

Without this strict filter, queries like '"GIZ" vaccine' return hundreds of
program-update articles per day with no actionable opportunity.

These items appear under source = "Signal:<DonorName>" and are routed to
the Signals tab in the dashboard, like manufacturer signals.
"""

import re
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
REQUEST_DELAY_SEC = 1.5  # polite spacing — Google News throttles burst queries

# Donor-side targets. Each tuple is (signal label, Google News query).
# Queries are tightened to vaccine/health value chain context. We prefer
# donor entities with continuous news flow over one-off programme launches
# (e.g. AVMA/PAVM had launch coverage in 2021-2024 but minimal recent news).
DONORS = [
    ("GIZ",   '"GIZ" (vaccine OR immunization OR "supply chain" OR "value chain") '
              '(tender OR RFP OR consultancy OR procurement OR "expression of interest")'),
    # SaVax: the donor programme. Avoid homonym with SAVAX crypto token on
    # Avalanche blockchain — exclude crypto/DeFi terms and require vaccine
    # context. The query is verbose but necessary.
    ("SaVax", '("SaVax" vaccine) OR "Sustainable Vaccines initiative" OR '
              '"vaccine value chain" OR "vaccine value-chain" '
              '-crypto -BENQI -staking -DeFi -Avalanche'),
    ("KfW",   '"KfW" (vaccine OR immunization OR "vaccine manufacturing") '
              '(tender OR consultancy OR financing OR support)'),
    ("AFD",   '("Agence Française de Développement" OR "AFD France") '
              '(vaccine OR vaccin OR immunization) (tender OR consultancy OR appel OR finance)'),
    ("SDC",   '("Swiss Agency for Development" OR "Swiss SDC") '
              '(vaccine OR immunization OR "global health") (tender OR mandate OR consultancy)'),
    ("FCDO",  '"FCDO" (vaccine OR immunization OR "Gavi") '
              '(tender OR procurement OR contract)'),
    # AVMA programme-level news (announces, partner selections, country windows)
    ("AVMA",  '"African Vaccine Manufacturing Accelerator" '
              '(awarded OR selected OR partner OR partnership OR window OR announces)'),
]

MAX_AGE_DAYS = 180

# Domain check — the combined title+description MUST contain at least one
# vaccine/health keyword. Otherwise GIZ "supports gender inclusion in Nigeria"
# slips through because "support" matched the service filter.
DOMAIN_KEYWORDS = [
    "vaccine", "vaccines", "vaccination", "vaccin",
    "immuniz", "immunis", "immunization", "immunisation",
    "epi", "vph", "hpv",
    "cold chain", "cold-chain",
    "global health", "pandemic", "outbreak",
    "biolog", "biopharma", "pharmaceutical",
    "gavi", "unitaid", "who", "unicef",
]

# Strict service-keyword filter applied to title + description before keeping.
# At least one must appear (case-insensitive substring). The list mixes:
#   (a) explicit procurement language (tender, RFP, EOI, consultancy)
#   (b) donor announcement language (support, pledge, billion, commits, awarded,
#       framework, partnership, launches, programme) — a "$1.8B for African
#       vaccine manufacturing" headline IS the early-warning signal we want.
# Still strict enough to drop pure-news items with no procurement implication.
SERVICE_FILTER_KEYWORDS = [
    # Procurement language
    "tender", "rfp", "rfq", "rfi", "eoi",
    "expression of interest", "request for proposal", "call for proposal",
    "consultancy", "consultant", "consulting", "advisory",
    "technical assistance", "ta ",
    "procurement", "appel d'offres", "appel a propositions",
    "evaluation", "feasibility", "study", "assessment",
    "mandate", "framework agreement", "contract awarded",
    # Donor announcement language
    "partnership", "agreement signed", "memorandum of understanding", "mou ",
    "launches", "launching", "launched", "announces", "announced",
    "new program", "new programme", "initiative",
    "financing", "grant", "funding", "funded",
    "support", "supports", "supporting",
    "pledge", "pledges", "pledged", "commits", "committed",
    "billion", "million",  # "$1.8 billion in support" — strong donor signal
    "awarded", "selected", "shortlisted",
    "framework", "facility", "window",
    "scaling", "scale-up", "expand", "expansion",
    "boost", "booster",  # vaccine boosters AND donor "boosts funding"
]


def fetch() -> list[dict]:
    out = []
    seen_titles = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    for label, query in DONORS:
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
            # One retry on 5xx — Google News occasionally throttles
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3)
                r = requests.get(
                    GOOGLE_NEWS_RSS, params=params,
                    headers={"User-Agent": "vaxrfp-scan-agent/1.0"},
                    timeout=20,
                )
            if r.status_code != 200:
                print(f"[donor_signals:{label}] HTTP {r.status_code}")
                time.sleep(REQUEST_DELAY_SEC)
                continue
        except Exception as e:
            print(f"[donor_signals:{label}] exception: {e}")
            time.sleep(REQUEST_DELAY_SEC)
            continue

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            print(f"[donor_signals:{label}] XML parse error: {e}")
            continue

        kept_for_label = 0
        skipped_for_label = 0
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

            description = (desc_el.text or "").strip() if desc_el is not None else ""
            description = re.sub(r"<[^>]+>", " ", description)
            description = re.sub(r"\s+", " ", description).strip()

            combined = f"{title} {description}".lower()

            # Domain check FIRST — must be vaccine/health relevant. Without
            # this, donor news about unrelated sectors (gender, infrastructure,
            # agriculture) leaks through because "support" or "billion" matches
            # the service filter.
            if not any(kw in combined for kw in DOMAIN_KEYWORDS):
                skipped_for_label += 1
                continue

            # Strict service filter — must mention something procurement-y
            if not any(kw in combined for kw in SERVICE_FILTER_KEYWORDS):
                skipped_for_label += 1
                continue

            seen_titles.add(title)
            kept_for_label += 1

            out.append({
                "source": f"Signal:{label}",
                "title": title,
                "url": link,
                "description": description[:1500],
                "country": None,
                "deadline": None,
                "value_usd": None,
                "raw": {
                    "donor": label,
                    "published": pub_dt.isoformat() if pub_dt else None,
                    "signal_type": "donor",
                },
            })

        print(f"[donor_signals:{label}] kept={kept_for_label} skipped={skipped_for_label}")
        time.sleep(REQUEST_DELAY_SEC)

    return out
