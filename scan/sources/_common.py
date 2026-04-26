"""Shared HTTP helpers for source scrapers."""

import time
import requests

USER_AGENT = "vaxrfp-scan-agent/1.0 (+https://github.com/nuno-svg/vaxrfp-scan-agent)"
DEFAULT_TIMEOUT = 30


def http_get(url: str, params: dict | None = None, headers: dict | None = None,
             timeout: int = DEFAULT_TIMEOUT, retries: int = 2) -> requests.Response | None:
    """GET with retries and a polite UA. Returns None on persistent failure."""
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        h.update(headers)

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return None
        except requests.RequestException:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def opportunity(source: str, title: str, url: str, description: str = "",
                country: str | None = None, deadline: str | None = None,
                value_usd: float | None = None, raw: dict | None = None) -> dict:
    """Construct a normalised opportunity dict."""
    return {
        "source": source,
        "title": title.strip(),
        "url": url,
        "description": description.strip(),
        "country": country,
        "deadline": deadline,
        "value_usd": value_usd,
        "raw": raw or {},
    }
