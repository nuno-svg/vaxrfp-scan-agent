"""Keyword matching and fit scoring against expertise areas."""

import json
from pathlib import Path

_KEYWORDS_PATH = Path(__file__).parent.parent / "archetype_keywords.json"

with open(_KEYWORDS_PATH) as f:
    CONFIG = json.load(f)


def _matches_any(text_lower: str, keywords: list[str]) -> bool:
    return any(kw.lower() in text_lower for kw in keywords)


def _is_goods_tender(title: str, description: str) -> tuple[bool, str]:
    """Detect goods/works tenders that should be excluded.

    A tender is "goods" if its title or first 300 chars of description
    contain a goods-exclusion keyword AND no consultancy override appears
    in the same range. The override exists because some legitimate service
    contracts mention "supply and delivery" alongside "with associated
    technical assistance and training" — those should pass.

    Returns (is_goods, matched_phrase).
    """
    head = f"{title} {(description or '')[:300]}".lower()

    matched = None
    for phrase in CONFIG.get("goods_exclusion_keywords", []):
        if phrase.lower() in head:
            matched = phrase
            break
    if not matched:
        return False, ""

    # Check overrides — if any consultancy keyword is in the same head text,
    # the goods phrase is incidental, not the contract's substance.
    for override in CONFIG.get("goods_exclusion_overrides", []):
        if override.lower() in head:
            return False, ""

    return True, matched


def _bmgf_passes_vaccine_gate(title: str, description: str) -> bool:
    """BMGF Grand Challenges has many R&D grants unrelated to vaccines.

    Require an explicit vaccine/immunization keyword in the title or first
    300 chars of the description. Burying "vaccine" in paragraph 5 of a
    diagnostic-tools grant doesn't make it a vaccine opportunity.
    """
    head = f"{title} {(description or '')[:300]}".lower()
    return any(kw.lower() in head for kw in CONFIG.get("bmgf_strict_vaccine_keywords", []))


def passes_gates(title: str, description: str, source: str = "",
                 raw: dict | None = None) -> tuple[bool, str]:
    """Check domain gate (vaccine-related), service gate (consulting-type),
    goods exclusion gate (no equipment/works tenders), and source-specific
    strict gates (BMGF requires vaccine keyword in head).

    Returns (passes, reason_if_not).

    Special cases:
      - TED notices already classified under CPV 33651600 (Vaccines) bypass
        the domain gate via text inference.
      - Signal:* sources (manufacturer press releases) only need the domain
        gate — they aren't formal RFPs, so the "consultancy/TA" service gate
        doesn't apply. They also bypass the goods-exclusion gate (a press
        release about supplying vaccines is still a useful market signal).
    """
    text = f"{title} {description}".lower()

    # Manufacturer signals: domain gate only
    if source.startswith("Signal:"):
        if _matches_any(text, CONFIG["domain_gate_keywords"]):
            return True, ""
        return False, "no_domain_match"

    # Goods/works exclusion — applied to all RFP sources before any other gate.
    # We're a consultancy, not a supplier. "Supply and delivery of lab equipment"
    # is rejected here regardless of how vaccine-relevant the equipment is.
    is_goods, goods_phrase = _is_goods_tender(title, description)
    if is_goods:
        return False, f"goods_tender (matched: '{goods_phrase}')"

    # Structural domain match: TED CPV-classified vaccine notices skip text gate
    if source == "TED" and raw:
        if any(kw in text for kw in ["vaccine", "vaccin", "pharmaceutical",
                                      "medicinal", "health service",
                                      "supply chain", "cold chain"]):
            if _matches_any(text, CONFIG["service_gate_keywords"]):
                # Still check BMGF gate (TED won't be BMGF, but be defensive)
                if source == "BMGF" and not _bmgf_passes_vaccine_gate(title, description):
                    return False, "bmgf_no_vaccine_in_head"
                return True, ""

    if not _matches_any(text, CONFIG["domain_gate_keywords"]):
        return False, "no_domain_match"
    if not _matches_any(text, CONFIG["service_gate_keywords"]):
        return False, "no_service_match"

    # BMGF-specific strict gate: vaccine keyword must be in title or head of description
    if source == "BMGF" and not _bmgf_passes_vaccine_gate(title, description):
        return False, "bmgf_no_vaccine_in_head"

    return True, ""


def compute_fit_scores(title: str, description: str, source: str) -> dict:
    """Compute fit score per expertise area + breadth bonus + total.

    Returns dict:
      - per_area: {area_key: score_0_to_10}
      - breadth_bonus: int (0-3)
      - total: int (0-10) — max area score + breadth bonus, capped at 10
      - top_area: str — area with highest score
    """
    text = f"{title} {description}".lower()
    per_area = {}

    for area_key, area_def in CONFIG["expertise_areas"].items():
        score = 0
        for kw, weight in area_def["keywords"].items():
            if kw.lower() in text:
                score += weight
        # Apply publisher boost ONLY if there's already at least one keyword
        # match in this area. Otherwise the boost would inflate noise — every
        # RFP from a given publisher would score >0 in every "boosted" area
        # regardless of actual relevance.
        if score > 0:
            boost = CONFIG.get("publisher_boosts", {}).get(source, {}).get(area_key, 0)
            score += boost
        per_area[area_key] = min(score, 10)

    # Breadth bonus: number of areas with score >= 3, capped at 3
    breadth = sum(1 for s in per_area.values() if s >= 3)
    breadth_bonus = min(breadth - 1, 3) if breadth > 1 else 0

    max_area_score = max(per_area.values()) if per_area else 0
    total = min(max_area_score + breadth_bonus, 10)
    top_area = max(per_area, key=per_area.get) if per_area else None

    return {
        "per_area": per_area,
        "breadth_bonus": breadth_bonus,
        "total": total,
        "top_area": top_area,
    }
