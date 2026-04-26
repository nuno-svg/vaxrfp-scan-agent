"""Keyword matching and fit scoring against expertise areas."""

import json
from pathlib import Path

_KEYWORDS_PATH = Path(__file__).parent.parent / "archetype_keywords.json"

with open(_KEYWORDS_PATH) as f:
    CONFIG = json.load(f)


def _matches_any(text_lower: str, keywords: list[str]) -> bool:
    return any(kw.lower() in text_lower for kw in keywords)


def passes_gates(title: str, description: str, source: str = "",
                 raw: dict | None = None) -> tuple[bool, str]:
    """Check domain gate (vaccine-related) and service gate (consulting-type).

    Returns (passes, reason_if_not).

    Special cases:
      - TED notices already classified under CPV 33651600 (Vaccines) bypass
        the domain gate via text inference.
      - Signal:* sources (manufacturer press releases) only need the domain
        gate — they aren't formal RFPs, so the "consultancy/TA" service gate
        doesn't apply. They surface as upstream signals of future opportunities.
    """
    text = f"{title} {description}".lower()

    # Manufacturer signals: domain gate only
    if source.startswith("Signal:"):
        if _matches_any(text, CONFIG["domain_gate_keywords"]):
            return True, ""
        return False, "no_domain_match"

    # Structural domain match: TED CPV-classified vaccine notices skip text gate
    if source == "TED" and raw:
        if any(kw in text for kw in ["vaccine", "vaccin", "pharmaceutical",
                                      "medicinal", "health service",
                                      "supply chain", "cold chain"]):
            if _matches_any(text, CONFIG["service_gate_keywords"]):
                return True, ""

    if not _matches_any(text, CONFIG["domain_gate_keywords"]):
        return False, "no_domain_match"
    if not _matches_any(text, CONFIG["service_gate_keywords"]):
        return False, "no_service_match"
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
