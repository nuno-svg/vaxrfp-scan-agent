"""UNGM (UN Global Marketplace) public tender notices scraper.

UNGM aggregates procurement notices from 30+ UN agencies including UNICEF,
WHO, UNDP, UNOPS, FAO, IOM, GIZ (occasional), and others. It does NOT
publish a public RSS feed — the listing page at /Public/Notice is a SPA
that calls an internal AJAX endpoint.

Endpoint discovered by inspecting the bundled JS:
  POST https://www.ungm.org/Public/Notice/Search

Requirements:
  - Session cookie (GCLB) obtained from a prior GET to /Public/Notice
  - Possibly an antiforgery token (extracted from the page if present)
  - Content-Type: application/json
  - X-Requested-With: XMLHttpRequest

We run multiple targeted queries instead of one broad one — UNGM's full-text
search is precision-oriented, so "vaccine OR cold chain OR immunization"
returns nothing, but "vaccine" + "cold chain" + "immunization" as separate
calls returns the expected union. Results are deduplicated by notice ID.
"""

import re
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://www.ungm.org/Public/Notice"
SEARCH_URL = "https://www.ungm.org/Public/Notice/Search"
NOTICE_URL_TPL = "https://www.ungm.org/Public/Notice/{id}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Targeted queries — each runs as a separate POST. Results are merged by notice ID.
# Keep these tightly scoped to vaccine supply-chain consultancy. Broad queries
# return mostly noise; UNGM's relevance ranking is not great.
QUERIES = [
    "vaccine",
    "vaccination",
    "immunization",
    "immunisation",
    "cold chain",
    "vaccine supply chain",
    "vaccine manufacturing",
    "vaccine procurement",
    "EPI",
    "tech transfer vaccine",
    "WHO prequalification",
]

# Delay between requests to be polite — UNGM is behind Cloudflare/WAF
REQUEST_DELAY_SEC = 1.5
PAGE_SIZE = 100        # max notices per query response


def _new_session() -> tuple[requests.Session, str | None]:
    """Open a session against UNGM. Returns (session, antiforgery_token).

    The GET to /Public/Notice gives us the GCLB cookie and lets us extract
    the __RequestVerificationToken if it's present in the page. UNGM's
    internal JS uses standard ASP.NET MVC antiforgery handling.
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    })

    try:
        r = s.get(LISTING_URL, timeout=30, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
    except requests.RequestException as e:
        print(f"[ungm] session init failed: {e}")
        return s, None

    if r.status_code != 200:
        print(f"[ungm] session init HTTP {r.status_code}")
        return s, None

    # Try to extract the antiforgery token from the page HTML
    token = None
    m = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',
        r.text,
    )
    if m:
        token = m.group(1)
    return s, token


def _search_one(s: requests.Session, query: str, token: str | None) -> list[dict]:
    """Run one POST search against UNGM. Returns list of notice dicts.

    Payload schema is reverse-engineered from the SPA. Fields beyond
    PageIndex/PageSize/Title are sent empty; UNGM accepts that.
    """
    payload = {
        "PageIndex": 0,
        "PageSize": PAGE_SIZE,
        "Title": query,
        "Description": "",
        "Reference": "",
        "PublishedFrom": "",
        "PublishedTo": "",
        "DeadlineFrom": "",
        "DeadlineTo": "",
        "Countries": [],
        "Agencies": [],
        "UNSPSCs": [],
        "NoticeTypes": [],
        "SortField": "DatePublished",
        "SortAscending": False,
    }

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": LISTING_URL,
        "Origin": "https://www.ungm.org",
    }
    if token:
        headers["__RequestVerificationToken"] = token

    try:
        r = s.post(SEARCH_URL, json=payload, headers=headers, timeout=30,
                   allow_redirects=False)
    except requests.RequestException as e:
        print(f"[ungm] search '{query}' exception: {e}")
        return []

    # 302 → endpoint rejected our session/token; 200 with JSON or HTML are valid attempts
    if r.status_code in (301, 302):
        print(f"[ungm] search '{query}' redirected to {r.headers.get('Location')} — auth/session issue")
        return []
    if r.status_code != 200:
        print(f"[ungm] search '{query}' HTTP {r.status_code}: {r.text[:200]}")
        return []

    # The endpoint returns either JSON or rendered HTML depending on Accept
    # negotiation. Try JSON first; if that fails, parse as HTML table.
    ctype = r.headers.get("Content-Type", "")
    if "application/json" in ctype:
        return _parse_json(r.json(), query)
    return _parse_html(r.text, query)


def _parse_json(data, query: str) -> list[dict]:
    """Parse the JSON response shape (preferred path)."""
    items = []
    # Response shapes vary. Common shapes seen in similar ASP.NET endpoints:
    #   {"Notices": [...], "Total": N}
    #   {"Results": [...], "Total": N}
    #   [...]
    rows = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("Notices", "Results", "Items", "Data"):
            if key in data and isinstance(data[key], list):
                rows = data[key]
                break

    for row in rows:
        # Field names vary; try the most common
        notice_id = (row.get("Id") or row.get("NoticeId")
                     or row.get("id") or row.get("noticeId"))
        title = (row.get("Title") or row.get("Subject")
                 or row.get("title") or row.get("subject") or "")
        agency = (row.get("Agency") or row.get("AgencyName")
                  or row.get("UNAgency") or "")
        country = (row.get("BeneficiaryCountry") or row.get("Country")
                   or row.get("country") or "")
        published = (row.get("PublishedDate") or row.get("DatePublished")
                     or row.get("publishedDate") or "")
        deadline = (row.get("DeadlineDate") or row.get("Deadline")
                    or row.get("deadlineDate") or "")
        notice_type = (row.get("NoticeType") or row.get("Type") or "")
        ref = row.get("Reference") or row.get("reference") or ""

        if not notice_id or not title:
            continue

        items.append({
            "_ungm_id": str(notice_id),
            "title": title.strip(),
            "agency": agency,
            "country": country,
            "published": _normalise_date(published),
            "deadline": _normalise_date(deadline),
            "notice_type": notice_type,
            "ref": ref,
            "_query": query,
        })
    return items


def _parse_html(html: str, query: str) -> list[dict]:
    """Parse the HTML response — this is the actual response shape from UNGM.

    Each notice row is a <div role="row" data-noticeid="NNN"> containing 8
    cells in fixed order:
      0 - save/unsave buttons (skip)
      1 - title (with trailing "Open in a new window" text we strip)
      2 - deadline date + timezone
      3 - published date
      4 - UN agency
      5 - notice type
      6 - reference number
      7 - beneficiary country
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    rows = soup.find_all("div", attrs={"data-noticeid": True})

    for row in rows:
        notice_id = row.get("data-noticeid", "").strip()
        if not notice_id:
            continue

        cells = row.find_all("div", attrs={"role": "cell"})
        if len(cells) < 8:
            # Layout changed — try a defensive minimal extraction
            text_blob = row.get_text(" ", strip=True)
            items.append({
                "_ungm_id": notice_id,
                "title": text_blob[:200],
                "agency": "",
                "country": "",
                "published": None,
                "deadline": None,
                "notice_type": "",
                "ref": "",
                "_query": query,
            })
            continue

        title = cells[1].get_text(" ", strip=True)
        # Strip the trailing accessibility text from the "open in new window" link
        title = re.sub(r"\s*Open in a new window\s*$", "", title, flags=re.IGNORECASE).strip()
        if not title:
            continue

        # Deadline cell typically reads "29-Apr-2026 14:00 (GMT 2.00) ..."
        deadline_raw = cells[2].get_text(" ", strip=True)
        m_dl = re.match(r"(\d{1,2}-\w{3}-\d{4})", deadline_raw)
        deadline = _normalise_date(m_dl.group(1)) if m_dl else None

        # Published cell is "DD-MMM-YYYY"
        published_raw = cells[3].get_text(" ", strip=True)
        m_pub = re.match(r"(\d{1,2}-\w{3}-\d{4})", published_raw)
        published = _normalise_date(m_pub.group(1)) if m_pub else None

        agency = cells[4].get_text(" ", strip=True)
        notice_type = cells[5].get_text(" ", strip=True)
        ref = cells[6].get_text(" ", strip=True)
        country = cells[7].get_text(" ", strip=True) or None

        items.append({
            "_ungm_id": notice_id,
            "title": title,
            "agency": agency,
            "country": country,
            "published": published,
            "deadline": deadline,
            "notice_type": notice_type,
            "ref": ref,
            "_query": query,
        })
    return items


def _normalise_date(s) -> str | None:
    """Normalise dates from UNGM's various formats to ISO YYYY-MM-DD."""
    if not s:
        return None
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None

    # Already ISO?
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]

    # ASP.NET /Date(...)/
    m = re.match(r"/Date\((\d+)", s)
    if m:
        ts = int(m.group(1)) / 1000
        try:
            return datetime.utcfromtimestamp(ts).date().isoformat()
        except (ValueError, OSError):
            return None

    # DD-MMM-YYYY, DD MMM YYYY, etc.
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(s, dayfirst=True).date().isoformat()
    except Exception:
        return None


def fetch() -> list[dict]:
    """Run all queries against UNGM, dedupe by notice ID, return opportunities."""
    session, token = _new_session()

    by_id = {}  # notice_id -> merged item

    for query in QUERIES:
        items = _search_one(session, query, token)
        print(f"[ungm] query={query!r} returned {len(items)} items")
        for item in items:
            nid = item["_ungm_id"]
            if nid not in by_id:
                by_id[nid] = item
            else:
                # If a later query gave us better data (e.g. has deadline), merge
                existing = by_id[nid]
                if not existing.get("deadline") and item.get("deadline"):
                    existing["deadline"] = item["deadline"]
                if not existing.get("agency") and item.get("agency"):
                    existing["agency"] = item["agency"]
        time.sleep(REQUEST_DELAY_SEC)

    out = []
    for item in by_id.values():
        nid = item["_ungm_id"]
        agency = item.get("agency", "") or ""
        country = item.get("country", "") or None
        notice_type = item.get("notice_type", "") or ""
        ref = item.get("ref", "") or ""

        description_parts = []
        if agency:
            description_parts.append(f"Agency: {agency}.")
        if notice_type:
            description_parts.append(f"Type: {notice_type}.")
        if ref:
            description_parts.append(f"Reference: {ref}.")
        description_parts.append(f"Matched query: {item.get('_query', '')}.")
        description = " ".join(description_parts)

        # Map UN agency to a canonical source label so downstream filters and
        # publisher boosts work as expected. UNGM aggregates many agencies;
        # we surface the underlying publisher when known.
        source = _normalise_source(agency)

        out.append({
            "source": source,
            "title": item["title"],
            "url": NOTICE_URL_TPL.format(id=nid),
            "description": description[:1500],
            "country": country,
            "deadline": item.get("deadline"),
            "value_usd": None,
            "raw": {
                "ungm_id": nid,
                "ungm_agency": agency,
                "ungm_notice_type": notice_type,
                "ungm_reference": ref,
                "ungm_query": item.get("_query"),
                "published": item.get("published"),
            },
        })

    return out


def _normalise_source(agency: str) -> str:
    """Map UN agency names to canonical labels used elsewhere in the pipeline."""
    if not agency:
        return "UNGM"
    a = agency.upper()
    mapping = {
        "WHO": "WHO", "WORLD HEALTH": "WHO",
        "UNICEF": "UNICEF",
        "UNDP": "UNDP",
        "UNOPS": "UNOPS",
        "UNFPA": "UNFPA",
        "UNHCR": "UNHCR",
        "FAO": "FAO",
        "WFP": "WFP",
        "IOM": "IOM",
        "GAVI": "GAVI",
        "GIZ": "GIZ",
        "GLOBAL FUND": "GFATM",
        "PAHO": "PAHO",
    }
    for needle, label in mapping.items():
        if needle in a:
            return label
    # Fallback: prefix with UNGM so it's identifiable as coming from there
    return f"UNGM ({agency[:30]})"
