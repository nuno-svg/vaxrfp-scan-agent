"""World Bank procurement notices scraper via REST API.

The World Bank publishes ~400k procurement notices via an open REST API at
search.worldbank.org/api/v2/procnotices. We filter for:
  - notice_type: Request for Bid, Request for Expression of Interest, Invitation
    for Bids (excluding Contract Awards and General Procurement Notices)
  - sector: Health (or unspecified — we filter further with text gates)
  - submission_date in the future (skip closed bids)

Notices link to detail pages on the WB Projects portal.
"""

import requests
from datetime import datetime, timezone

API_URL = "https://search.worldbank.org/api/v2/procnotices"

# Notice types that are real opportunities (not awards or general info)
ACTIONABLE_TYPES = {
    "Request for Bids",
    "Request for Bid",
    "Request for Expression of Interest",
    "Request for Expressions of Interest",
    "Invitation for Bids",
    "Invitation for Prequalification",
    "Specific Procurement Notice",
    "REOI",
    "RFB",
}

# Health-related sector names in WB's taxonomy
HEALTH_SECTORS = {
    "Health", "Public Administration - Health",
    "Other Public Administration",  # often used for health-adjacent
}


def fetch() -> list[dict]:
    out = []
    # Pull most recent 200 notices to filter locally — WB's API doesn't
    # support sector filtering reliably for procnotices
    params = {
        "format": "json",
        "rows": 200,
        "os": 0,
    }
    try:
        r = requests.get(
            API_URL, params=params,
            headers={"User-Agent": "vaxrfp-scan-agent/1.0"},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[worldbank] HTTP {r.status_code}")
            return []
        data = r.json()
    except Exception as e:
        print(f"[worldbank] exception: {e}")
        return []

    notices = data.get("procnotices") or []
    if not isinstance(notices, list):
        print("[worldbank] unexpected response shape")
        return []

    today = datetime.now(timezone.utc).date().isoformat()

    for n in notices:
        notice_type = n.get("notice_type", "")
        # Skip non-actionable types (Contract Award, General Procurement Notice, etc.)
        if not any(t in notice_type for t in ACTIONABLE_TYPES):
            continue

        # Skip if submission_deadline_date is in the past (closed bids).
        # Note: submission_date is the publish date, not the deadline.
        deadline_raw = n.get("submission_deadline_date") or ""
        if deadline_raw and deadline_raw[:10] < today:
            continue

        title = n.get("bid_description") or n.get("project_name") or ""
        title = title.strip()
        if not title or len(title) < 15:
            continue

        ref = n.get("bid_reference_no") or n.get("id") or ""
        country = n.get("project_ctry_name") or ""
        project_name = n.get("project_name") or ""
        method = n.get("procurement_method_name") or ""

        description = (
            f"{notice_type}. {method}. Project: {project_name}. "
            f"Country: {country}. Reference: {ref}."
        )

        # WB notice URL: use the procnotice ID
        notice_id = n.get("id", "")
        url = (
            f"https://projects.worldbank.org/en/projects-operations/"
            f"procurement-detail/{notice_id}"
            if notice_id else
            "https://projects.worldbank.org/en/projects-operations/procurement"
        )

        deadline = deadline_raw[:10] if deadline_raw else None

        out.append({
            "source": "World Bank",
            "title": title,
            "url": url,
            "description": description[:1500],
            "country": country if country else None,
            "deadline": deadline,
            "value_usd": None,
            "raw": {
                "wb_notice_type": notice_type,
                "wb_project_id": n.get("project_id"),
                "wb_reference": ref,
            },
        })

    return out
