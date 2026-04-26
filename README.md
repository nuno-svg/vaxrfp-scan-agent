# VaxRFP Scan Agent

Automated daily scan for vaccine supply chain consulting opportunities (RFPs, EOIs, CFPs, calls for tender).

Tailored for a Switzerland-based consultancy serving vaccine manufacturers, with five expertise areas:
- Cold chain & logistics
- Manufacturing setup & tech transfer
- Regulatory (WHO PQ, SAHPRA, AMA)
- Procurement strategy & market shaping
- M&E and programme evaluations

## Architecture

- **Scan**: Python script runs daily via GitHub Actions (06:00 UTC).
- **Sources**: 31 institutional, multilateral, bilateral and manufacturer-side sources.
- **Scoring**: Multi-dimensional fit score (0-10 per expertise area) by keyword matching.
- **Filters**: Sanctions exclusion (UN/EU/OFAC), eligibility check (Swiss bidder), value/deadline filters.
- **Storage**: JSON committed to repo. Full git history = audit trail.
- **Dashboard**: Static HTML + JS served by GitHub Pages. State (New/Reviewing/Applied/Dismissed) in localStorage.
- **Cost**: €0/month — GitHub Free tier covers everything.

## Setup

1. Fork or clone this repo to `nuno-svg/vaxrfp-scan-agent` (or similar).
2. In repo Settings → Pages, set source to `docs/` folder on `main` branch.
3. Workflow runs automatically every day at 06:00 UTC. Trigger manually via Actions tab if needed.
4. Dashboard available at `https://nuno-svg.github.io/vaxrfp-scan-agent/`.

## Local development

```bash
pip install -r requirements.txt
python scan/run_daily.py
# Output written to data/opportunities.json and data/excluded.json
# Open docs/index.html in browser to preview dashboard
```

## Adding a source

Create `scan/sources/<name>.py` exposing a `fetch() -> list[dict]` function. Each dict must have:
- `source` (str), `title` (str), `url` (str), `country` (str ISO-2 or `null`), `deadline` (ISO date or `null`), `description` (str), `value_usd` (number or `null`).

Then import it in `scan/run_daily.py`.

## Tuning scoring

Edit `scan/archetype_keywords.json`. Each expertise area has a list of weighted keywords. After commit, the next scheduled run uses the new config.

## Sanctions list maintenance

Edit `scan/filters/sanctions.py`. Recommended quarterly review against:
- EU Consolidated List (https://data.europa.eu/apps/eusanctionstracker/)
- UN Security Council Sanctions
- OFAC SDN List
