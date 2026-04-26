# Changelog

## v3.1

**New source — Donor Signals.** Google News RSS scraper for donor-side
activity (GIZ, SaVax, KfW, AFD, SDC, FCDO, AVMA). Distinct from the existing
Manufacturer Signals: those track when a vaccine maker secures funding
(downstream procurement coming); donor signals track when a programme is
launched or a partnership is announced (upstream consultancy coming).

Triple-filter design to keep noise out:
  1. Domain check — title or description must mention vaccine/health
  2. Service filter — must mention procurement/donor announcement language
  3. 180-day age cutoff (donor news has longer lead times than manufacturer news)

SaVax query explicitly excludes the SAVAX crypto token (Avalanche blockchain
homonym) via `-crypto -BENQI -staking -DeFi -Avalanche`.

**Hardened — Manufacturer Signals.** Added 1.5s delay between Google News
queries plus one retry on 5xx responses. Without this the scraper occasionally
hits transient throttling that drops a manufacturer for the day.

**Orchestrator.** Registers `donor_signals` as the 11th source.

## v3

**Three policy decisions implemented:**

1. **Goods/works tenders excluded from all RFP sources.** New
   `goods_exclusion_keywords` list in `archetype_keywords.json` (39 phrases:
   "supply and delivery", "procurement of equipment", "construction of",
   "supervision of works", etc.). Override list (18 phrases:
   "technical assistance", "consultancy", "training", etc.) prevents false
   negatives — a tender saying "supply and delivery WITH associated
   technical assistance and training" still passes. We're a consultancy,
   not a supplier; this gate alone removes ~half of UNGM's noise.

2. **BMGF strict vaccine gate.** BMGF Grand Challenges items must contain
   a vaccine/immunization keyword in the title OR first 300 characters of
   the description. Diagnostic tools, fetal growth, micronutrient grants
   no longer leak through.

3. **Dashboard split into RFPs and Signals tabs.** Toggle at the top
   (RFPs default), state persisted in localStorage. Each view has its own
   KPI panel:
     - RFPs: Total / New / Applied / Top fit
     - Signals: Total (90d) / New since last visit / On watch list / Manufacturers active
   Signals view hides the deadline column and the "hide expired" filter
   (signals don't have deadlines). Unseen signals get a yellow left-border
   marker; switching away from Signals marks all visible items as seen.
   CSV export is named per view (`vaxrfp-rfps-...csv` or `vaxrfp-signals-...csv`).

**New source — UNGM (UN Global Marketplace).** Aggregates procurement
notices from 30+ UN agencies (UNICEF, WHO, UNDP, UNOPS, FAO, IOM, etc.).
UNGM has no public RSS — implementation uses `POST /Public/Notice/Search`
with session cookies. 11 targeted queries (vaccine, immunization, cold
chain, EPI, vaccine procurement, etc.); results deduplicated by notice ID.
Agency names are normalised to canonical labels so downstream filters and
publisher boosts work as expected. The new goods exclusion gate proves its
worth here — a typical UNGM "vaccine" query returns ~15 raw items of which
only 2-3 are real consultancy opportunities; the rest are vaccine purchases
or cold chain equipment supply, all correctly excluded.

**Orchestrator.** New exclusion types in `meta.json` for monitoring:
`exclusion_type: "goods"` and `exclusion_type: "bmgf_strict"` so you can
audit how aggressive the gates have been each day.
