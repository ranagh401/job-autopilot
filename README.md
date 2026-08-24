# Job Autopilot

An automated job-search portal that runs your whole pipeline: it finds fresh AI/ML and software-engineering jobs across dozens of sources, scores each one against your profile with an LLM, tailors your resume per job with an ATS fit score, hunts down recruiter emails, drafts personalised cold emails (sent from your Gmail **only after your approval**), chases non-replies with follow-ups, and auto-classifies replies into interview / offer / rejection.

React + Vite frontend, FastAPI + SQLite backend, GitHub Actions as the always-on hourly scheduler.

## What it does

1. **Fetch** — Remotive, RemoteOK, Arbeitnow, The Muse, Adzuna (India + 8 sponsorship markets), Seek AU/NZ, JSearch/Google-for-Jobs, Greenhouse / Lever / Ashby company boards, Instahyre, Wellfound, and your own Gmail job-alert emails. Cross-source duplicates collapse on a normalised company+title key.
2. **Score** — the LLM rates each job 0–100 against `profile.yaml`, detects the country and the experience the posting demands, and skips anything above your experience ceiling.
3. **Tailor** — generates a per-job resume variant with an ATS fit score.
4. **Enrich** — finds HR/recruiter contact emails for shortlisted jobs.
5. **Outreach** — drafts personalised cold emails; you approve in the dashboard before anything is sent (hard cap 50/day), with automatic follow-ups.
6. **Replies** — incoming responses are classified into interview / offer / rejection and surfaced on the board.

Full pipeline documentation: [job-portal/README.md](job-portal/README.md).

## Quickstart

1. Fill in your details in [job-portal/profile.yaml](job-portal/profile.yaml) — name, contact, target roles, experience notes, and the company boards you want swept.
2. Put your resume at `job-portal/assets/base_resume.pdf`.
3. Copy `job-portal/.env.example` to `job-portal/.env` and fill in your keys (LLM, Adzuna/JSearch, Gmail app password, dashboard password).
4. Run:

```bat
cd job-portal
run.bat
```

Opens at http://127.0.0.1:8000 — log in with `DASHBOARD_PASSWORD` from `.env`. After changing anything under `frontend/`, run `build-ui.bat`.

## Scheduling

`.github/workflows/pipeline.yml` runs the pipeline hourly on GitHub Actions (free-tier friendly) — configure your secrets in the repo settings and it keeps hunting while your laptop sleeps. `prepare_secrets.py` helps package local config into Actions secrets.

## Safety rails

- Nothing is ever emailed without your explicit approval in the dashboard.
- Hard daily send cap (50) and a company blocklist (e.g. your current employer).
- Senior/lead/intern/off-stack titles are filtered out before they waste LLM calls.
