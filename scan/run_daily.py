"""VaxRFP scan agent — main orchestrator.

Runs daily via GitHub Actions. Fetches from all sources, applies sanctions and
keyword filters, computes fit scores, and writes results to data/opportunities.json.
"""

import hashlib
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from filters.sanctions import check_sanctions
from filters.keywords import passes_gates, compute_fit_scores
from filters.eligibility import check_eligibility
from filters.countries import detect_country, normalise_country_code

from sources import (
    reliefweb, gavi, unitaid, africacdc, ted_europa,
    manufacturer_signals, cepi, bmgf, worldbank, ungm,
    donor_signals,
)

# Active sources. Add new ones here as they are implemented.
SOURCES = [
    ("ReliefWeb", reliefweb.fetch),
    ("GAVI", gavi.fetch),
    ("UNITAID", unitaid.fetch),
    ("Africa CDC", africacdc.fetch),
    ("TED Europa", ted_europa.fetch),
    ("CEPI", cepi.fetch),
    ("BMGF", bmgf.fetch),
    ("World Bank", worldbank.fetch),
    ("UNGM", ungm.fetch),
    ("Manufacturer Signals", manufacturer_signals.fetch),
    ("Donor Signals", donor_signals.fetch),
]

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_DIR = DATA_DIR / "history"
HISTORY_DIR.mkdir(exist_ok=True)

MIN_VALUE_USD = 50_000
URGENT_DAYS = 7
MIN_FIT_SCORE = 0


def make_id(source: str, title: str, url: str) -> str:
    """Stable hash for deduplication and persistent dashboard state."""
    base = f"{source}|{title.strip().lower()}|{url}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def days_until(deadline_iso: str | None) -> int | None:
    if not deadline_iso:
        return None
    try:
        d = datetime.fromisoformat(deadline_iso).date()
        return (d - datetime.now(timezone.utc).date()).days
    except Exception:
        return None


def process_one(raw: dict) -> tuple[dict | None, dict | None]:
    """Process a raw opportunity dict.

    Returns (kept_record, excluded_record). Exactly one of them is non-None.
    """
    title = raw.get("title", "")
    description = raw.get("description", "")
    source = raw.get("source", "unknown")
    country = raw.get("country")
    url = raw.get("url", "")

    country = normalise_country_code(country)

    if country is None or country == "_AU":
        detected = detect_country(f"{title} {description}")
        if detected:
            country = detected

    rid = make_id(source, title, url)
    free_text = f"{title} {description} {country or ''}"

    # 1) Sanctions check (hard exclude)
    sanc = check_sanctions(country, free_text)
    if sanc["sanctioned"]:
        return None, {
            "id": rid, "source": source, "title": title, "url": url,
            "country": country,
            "exclusion_reason": sanc["reason"],
            "exclusion_type": "sanctioned",
            "excluded_at": datetime.now(timezone.utc).isoformat(),
        }

    # 2) Domain + service + goods + source-specific gates
    passes, gate_reason = passes_gates(title, description, source, raw.get("raw"))
    if not passes:
        # Use a finer exclusion_type so we can audit goods rejections separately
        excl_type = "gate"
        if gate_reason.startswith("goods_tender"):
            excl_type = "goods"
        elif gate_reason == "bmgf_no_vaccine_in_head":
            excl_type = "bmgf_strict"
        return None, {
            "id": rid, "source": source, "title": title, "url": url,
            "country": country,
            "exclusion_reason": gate_reason,
            "exclusion_type": excl_type,
            "excluded_at": datetime.now(timezone.utc).isoformat(),
        }

    # 3) Value floor (only if value is known)
    value_usd = raw.get("value_usd")
    if value_usd is not None and value_usd < MIN_VALUE_USD:
        return None, {
            "id": rid, "source": source, "title": title, "url": url,
            "country": country,
            "exclusion_reason": f"value_below_floor ({value_usd} < {MIN_VALUE_USD})",
            "exclusion_type": "value",
            "excluded_at": datetime.now(timezone.utc).isoformat(),
        }

    # 4) Compute fit scores
    scores = compute_fit_scores(title, description, source)

    # 4b) Hard exclude expired RFPs
    deadline_days = days_until(raw.get("deadline"))
    if deadline_days is not None and deadline_days < 0:
        return None, {
            "id": rid, "source": source, "title": title, "url": url,
            "country": country,
            "exclusion_reason": f"expired (deadline was {raw.get('deadline')}, {-deadline_days} days ago)",
            "exclusion_type": "expired",
            "excluded_at": datetime.now(timezone.utc).isoformat(),
        }

    # 4c) Min fit floor
    if scores["total"] < MIN_FIT_SCORE:
        return None, {
            "id": rid, "source": source, "title": title, "url": url,
            "country": country,
            "exclusion_reason": f"fit_below_floor (total={scores['total']} < {MIN_FIT_SCORE})",
            "exclusion_type": "fit",
            "excluded_at": datetime.now(timezone.utc).isoformat(),
        }

    # 5) Eligibility check
    elig = check_eligibility(title, description, source)

    # 6) Flags
    flags = {
        "sanctioned": False,
        "requires_review_sanctions": sanc["requires_review"],
        "requires_review_eligibility": elig["requires_review"],
        "urgent_deadline": deadline_days is not None and 0 <= deadline_days <= URGENT_DAYS,
        "expired": False,
    }

    record = {
        "id": rid,
        "source": source,
        "title": title,
        "url": url,
        "country": country,
        "deadline": raw.get("deadline"),
        "deadline_days": deadline_days,
        "value_usd": value_usd,
        "description": description[:1500],
        "fit_per_area": scores["per_area"],
        "fit_total": scores["total"],
        "fit_top_area": scores["top_area"],
        "breadth_bonus": scores["breadth_bonus"],
        "flags": flags,
        "flag_notes": {
            "sanctions": sanc["reason"],
            "eligibility": elig["reason"],
        },
        "raw": raw.get("raw") or {},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return record, None


def main():
    started = datetime.now(timezone.utc)
    all_raw = []
    source_stats = {}

    for source_label, fetch_fn in SOURCES:
        try:
            items = fetch_fn() or []
            source_stats[source_label] = {"fetched": len(items), "errors": 0}
            all_raw.extend(items)
            print(f"[{source_label}] fetched {len(items)} items")
        except Exception as e:
            source_stats[source_label] = {"fetched": 0, "errors": 1,
                                          "error_msg": str(e)[:200]}
            print(f"[{source_label}] ERROR: {e}", file=sys.stderr)
            traceback.print_exc()

    kept = []
    excluded = []
    seen_ids = set()

    for raw in all_raw:
        rec, exc = process_one(raw)
        if rec is not None:
            if rec["id"] in seen_ids:
                continue
            seen_ids.add(rec["id"])
            kept.append(rec)
        elif exc is not None:
            excluded.append(exc)

    # Sort: not expired first, then by fit_total desc, then by deadline asc
    kept.sort(key=lambda r: (
        r["flags"]["expired"],
        -r["fit_total"],
        r["deadline_days"] if r["deadline_days"] is not None else 9999,
    ))

    # Per-exclusion-type stats for monitoring gate effectiveness
    exclusion_breakdown = {}
    for exc in excluded:
        t = exc.get("exclusion_type", "unknown")
        exclusion_breakdown[t] = exclusion_breakdown.get(t, 0) + 1

    finished = datetime.now(timezone.utc)
    meta = {
        "last_run": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "source_stats": source_stats,
        "total_kept": len(kept),
        "total_excluded": len(excluded),
        "exclusion_breakdown": exclusion_breakdown,
        "min_value_usd": MIN_VALUE_USD,
        "urgent_days_threshold": URGENT_DAYS,
    }

    (DATA_DIR / "opportunities.json").write_text(
        json.dumps(kept, indent=2, ensure_ascii=False))
    (DATA_DIR / "excluded.json").write_text(
        json.dumps(excluded, indent=2, ensure_ascii=False))
    (DATA_DIR / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False))

    snapshot_name = finished.strftime("%Y-%m-%d") + ".json"
    (HISTORY_DIR / snapshot_name).write_text(
        json.dumps({"meta": meta, "opportunities": kept}, indent=2, ensure_ascii=False))

    print(f"\n=== Summary ===")
    print(f"Kept: {len(kept)}")
    print(f"Excluded: {len(excluded)}")
    if exclusion_breakdown:
        for t, n in sorted(exclusion_breakdown.items(), key=lambda x: -x[1]):
            print(f"  {t}: {n}")
    print(f"Duration: {meta['duration_seconds']:.1f}s")


if __name__ == "__main__":
    main()
