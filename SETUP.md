# VaxRFP — Deployment Setup

Step-by-step to get the agent running on GitHub.

## 1. Create the GitHub repo

Option A — via GitHub web:
1. Go to https://github.com/new
2. Name: `vaxrfp-scan-agent` (or your choice)
3. Public or Private — both work with GitHub Pages on Free tier
4. Do NOT initialise with README/license/gitignore (this zip already has them)

Option B — via `gh` CLI:
```bash
gh repo create nuno-svg/vaxrfp-scan-agent --public --source=. --remote=origin
```

## 2. Push the code

```bash
cd vaxrfp-scan-agent
git init
git add .
git commit -m "Initial commit: VaxRFP scan agent"
git branch -M main
git remote add origin https://github.com/nuno-svg/vaxrfp-scan-agent.git
git push -u origin main
```

## 3. Enable GitHub Pages

1. Repo → Settings → Pages
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/docs`
4. Save. Wait ~1 minute for first deploy.
5. Dashboard available at: `https://<your-username>.github.io/vaxrfp-scan-agent/`

## 4. Trigger the first scan

The cron runs daily at 06:00 UTC. To trigger immediately:

1. Repo → Actions tab
2. Select "daily-scan" workflow
3. Click "Run workflow" → "Run workflow"
4. Wait ~30 seconds for completion
5. Refresh the dashboard URL — should now show real opportunities

## 5. (Optional) Activate ReliefWeb source

ReliefWeb v2 API requires a pre-approved appname. Without it, that source is skipped.

1. Request appname at https://apidoc.reliefweb.int/parameters#appname
   (typically approved within 1-2 days)
2. Once approved:
   - Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `RELIEFWEB_APPNAME`
   - Value: your approved appname
3. Next scan run will auto-activate ReliefWeb (covers GAVI, UNITAID, GFATM, WHO,
   UNICEF, Africa CDC, IFC, EIB, BMGF, CEPI, MPP via single API)

## 6. Tuning over time

After 1-2 weeks of data, review what's surfacing vs what should be:

- **Too many low-score items?** Increase `MIN_FIT_SCORE` in `scan/run_daily.py`
  (currently 1).
- **Missing relevant items?** Add keywords to `scan/archetype_keywords.json` —
  domain_gate_keywords (catch upstream) or expertise_areas (raise scores).
- **A source is broken?** Check the Actions tab → latest run logs. Each source
  is in its own try/except, so one broken scraper doesn't kill the run.
- **New source?** Create `scan/sources/<n>.py` with a `fetch() -> list[dict]`
  function and add to `SOURCES` list in `scan/run_daily.py`.

## 7. Sharing with your client

Send them the GitHub Pages URL. Status changes (New/Reviewing/Applied/Dismissed)
persist in their browser only — perfect for single-user use, no auth needed.

If multiple users at the consultancy need shared status, that's a future
upgrade (would require a backend — out of scope for the zero-cost design).
