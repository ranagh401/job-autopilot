# Running the portal in the cloud, free

The goal: a URL you can open from your phone, and a pipeline that keeps
working when your laptop is off. Three free services, **no credit card**:

| Piece | Service | Free tier |
|---|---|---|
| Database | **Neon** Postgres | 0.5 GB, always on |
| Scheduler | **GitHub Actions** | 2,000 min/month (private repo) |
| UI + URL | **Render** web service | 750 h/month, sleeps when idle |

Why three: Render's free instance sleeps after ~15 minutes idle, so it
cannot be trusted to run a schedule. GitHub Actions never sleeps, so it
does the work; Render just serves the interface you log into.

---

## 1. Database (5 min)

1. Sign up at **neon.tech** with GitHub — no card.
2. Create a project (region: Singapore or Mumbai).
3. Copy the connection string; it looks like
   `postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`

Move your existing data across:

```bash
cd job-portal
set DATABASE_URL=postgresql://...        # PowerShell: $env:DATABASE_URL="..."
.venv\Scripts\python.exe migrate_to_postgres.py
```

It copies every job, contact, resume record, email and application, then
resets the id sequences. Re-running needs `--replace`.

## 2. Repository (3 min)

**Already done locally**: the repo is initialised and committed (73
files), and it was checked that no credential appears in the commit —
`.env`, `data/` and the database are excluded, and the staged content was
scanned for every API key and password in use. Your resume is included at
`job-portal/assets/base_resume.pdf` so the cloud run can tailor it, which
is why the repo must be **private**.

Create the empty repo, then push:

1. Go to **github.com/new** → name it `job-mania` → **Private** → do NOT
   add a README or .gitignore → **Create repository**
2. Back in this folder:

```bash
git remote add origin https://github.com/<your-username>/job-mania.git
git push -u origin main
```

Git will ask you to sign in to GitHub in the browser the first time.

## 3. Scheduler (10 min)

In the repo: **Settings → Secrets and variables → Actions → New
repository secret**, and add each of:

```
DATABASE_URL           GMAIL_ADDRESS          GMAIL_APP_PASSWORD
AZURE_OPENAI_ENDPOINT  AZURE_OPENAI_API_KEY   AZURE_OPENAI_DEPLOYMENT
AZURE_OPENAI_API_VERSION   SERPER_API_KEY     HUNTER_API_KEY
ADZUNA_APP_ID          ADZUNA_APP_KEY         RAPIDAPI_KEY
```

`.github/workflows/pipeline.yml` then runs hourly. Trigger it by hand
from the **Actions** tab (**Run workflow**) to confirm it works — you can
also pass specific steps, e.g. `fetch score send`.

## 4. The URL (10 min)

1. Sign up at **render.com** with GitHub — no card for the free plan.
2. **New → Blueprint**, pick the repo; it reads `render.yaml`.
3. Add the same secrets under **Environment**, plus
   `DASHBOARD_PASSWORD`.
4. Deploy. You get **`https://job-mania.onrender.com`**.

`SCHEDULER_ENABLED=false` is already set there, so the web service only
serves the UI and never competes with the cron job for the database.

First load after idle takes ~50 seconds while the instance wakes. That is
the price of the free tier.

---

## What still needs your laptop

**Filling application forms.** That drives a real Chromium through
Playwright, which free hosts do not provide, so the workflow sets
`BROWSER_APPLY=false`. Applications are still *prepared* in the cloud —
cover letter, answers and a country-correct resume — and wait on the
Applications page. Run `run.bat` locally when you want to submit them.

Everything else runs in the cloud: fetching, enrichment, scoring,
filtering, contact discovery, resume tailoring, drafting, sending,
reply classification and follow-ups.

## Costs

Everything above is free at this volume. The paid edges, if you ever hit
them: Neon beyond 0.5 GB (thousands of jobs away), GitHub Actions beyond
2,000 minutes (hourly runs use ~300), and Render if you want to stop the
sleeping (\$7/month).
