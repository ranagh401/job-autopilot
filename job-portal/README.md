# Job Autopilot

A local job-search automation portal. Finds fresh
AI/ML/GenAI and software engineering jobs (India + remote + abroad-with-
sponsorship), scores them against your profile with GPT-5.1, tailors your
resume per job with an ATS fit score, hunts down HR/recruiter emails,
drafts personalised cold emails, sends them from your Gmail **after your
approval** (max 50/day), chases non-replies with follow-ups, and
classifies replies into interview / offer / rejection automatically.

React + Vite frontend, FastAPI + SQLite backend.

## Run it

```
run.bat
```

Opens at http://127.0.0.1:8000 — password is `DASHBOARD_PASSWORD` in `.env`.
After changing anything under `frontend/`, run `build-ui.bat`.

## Pipeline

1. **Fetch** — Remotive, RemoteOK, Arbeitnow (EU, visa-sponsorship flag),
   The Muse, **Adzuna across India + 8 sponsorship markets** (Australia,
   New Zealand, UK, Germany, Netherlands, Canada, Ireland, Singapore —
   edit `abroad_countries`), **Seek Australia & New Zealand**,
   JSearch/Google-for-Jobs with sponsorship queries per country,
   Greenhouse & Lever boards, your own Gmail **job-alert emails**
   (LinkedIn/Naukri/Indeed/Glassdoor), and optionally JobSpy.

   **Only relevant roles are imported.** A title must match your target
   roles (AI/GenAI/ML/software/backend/full-stack/Python) *and* must not
   be senior/lead/staff/principal/architect/manager, an internship, or an
   off-stack role (frontend, UI/UX, Shopify, QA…). See `title_blocklist`.
   Cross-source duplicates collapse on a normalised company+title key.
2. **Score** — GPT-5.1 rates each job 0–100, and in the same call decides
   the **country** (`is_india`) and the **experience required**. Roles
   demanding more than `max_experience_years` (default **2**) are skipped
   automatically, never shortlisted. ≥ `MATCH_THRESHOLD` (65)
   auto-shortlists. "Re-apply filters" on the dashboard re-runs these
   rules over everything already stored, so tightening `profile.yaml`
   retroactively cleans the pipeline.
3. **HR contacts — real people first, then verified by the LLM.** Every
   candidate address is classified as `hr`, `engineering`, `other_person`,
   `role_inbox`, `wrong_company` or `unknown`, and **only a real named
   person at that employer is ever auto-emailed**. This catches genuine
   mistakes: a "Neko Health" posting had turned up addresses belonging to
   *Neko Lighting*, and placeholder names like `joe.bloggs@` get rejected
   too. When no human is found, it escalates — searching again for
   recruiters/talent acquisition, then for senior engineers who could
   refer you. If nothing usable exists the job is simply left without a
   contact rather than mailing a generic inbox.

   Discovery order: a person named
   in the posting whose address echoes their name → **named HR/recruiting
   staff at the company via Hunter** (`department=hr`, e.g. "Talent
   Acquisition Associate", "VP of HR", with a confidence score and
   LinkedIn link) → recruiters found by name through web search and
   resolved with Hunter's email-finder → people named on the posting page.
   Only when no human is found does it fall back to shared inboxes
   (`careers@`), and last of all to a standard-mailbox guess on the
   company domain, kept only if that domain resolves. Addresses whose
   domain doesn't match the company, or that never reach a hiring team
   (`press@`, `billing@`…), are dropped. The Jobs table shows the chosen
   contact; the job page lists every candidate marked 👤 person or inbox.
4. **Tailor** — rewrites your base resume per job into a `.docx`, never
   inventing facts, then scores it for **ATS fit** (keyword match 55% +
   required-skills coverage 25% + section completeness 20%) and shows the
   keywords the posting wants that your resume doesn't evidence. If the
   first draft scores below 85 it retries once, working in only the missing
   keywords your base resume genuinely supports.

   **The document follows the destination country's conventions**
   (`app/resume_formats.py`): a German *Lebenslauf* with MM/YYYY dates and
   CEFR language levels, a 2-page UK/Irish *CV* in British spelling, a
   strict 1-page US resume, a longer Australian/NZ resume with a Key
   Skills block, and so on. Photos, date of birth and marital status are
   stripped everywhere they are illegal or unwelcome, and where you need
   sponsorship a single line names the right visa (subclass 482, AEWV,
   Skilled Worker, EU Blue Card, Employment Pass…). Unlisted countries get
   their own local conventions applied by name.
5. **Draft** — writes a short personalised cold email, signed with your
   real name, phone and profile links from `profile.yaml`. It reads as
   written by you; nothing indicates it was machine-generated.
6. **Send** — with `AUTO_SEND=true` clean drafts go out **without your
   approval**, 9:00–19:00, staggered, max `DAILY_EMAIL_CAP` (50)/day.
   A draft is held back for you whenever any of these is true:
   - **the posting has no real description**, so the employer cannot be
     confirmed. Job-alert emails give only a title and a link, and a short
     company name ("UNIS", "Charlie") will happily match an unrelated
     university or firm — those jobs are never cold-emailed, and no
     external contact lookup runs for them either. Open the link and
     apply yourself.
   - the recipient is not an LLM-verified real person (shared inbox,
     wrong company, placeholder, or unverified)
   - the address was only guessed at
   - your phone or LinkedIn URL is missing from the body
   - the job scores below `AUTO_SEND_MIN_SCORE` (70) or wants 3+ years
   - the text still contains a placeholder, or is suspiciously short

   Set `AUTO_SEND=false` to go back to approving everything yourself.
7. **Follow up** — no reply after 3 days → follow-up #1; after 7 → #2. Any
   reply on that job cancels the rest. Follow-ups queue as drafts too.
8. **Replies** — polled over IMAP and classified as interview / offer /
   rejection / info_request / auto_ack; interviews and rejections move the
   job card automatically.

The scheduler runs the whole loop hourly (sources refetch every 12h). Every
step also has a button on the dashboard.

## Applying through company forms

`AUTO_APPLY=true` makes the portal submit applications itself where that
is actually reliable, and prepare them everywhere else. What each ATS
supports was checked against live boards (Aug 2026):

| ATS | What happens | Why |
|---|---|---|
| **Lever** | **Submitted automatically** | Classic HTML form: real `name` attributes, `method=POST`, plain file input — fillable over HTTP. |
| Greenhouse | Answers prepared + direct apply link | Its form has `id`s but **no `name` attributes** and declares `method=get`; JavaScript collects and posts the values, so an HTTP POST would submit nothing. |
| Workday, Taleo, iCIMS, SuccessFactors, Ashby, Workable… | Answers prepared + link | Multi-step wizards behind sessions, with employer-specific screening questions. |
| LinkedIn / Naukri / Indeed links | Skipped | Aggregator links, not the employer's own form. Applying there needs your logged-in account, which is exactly what gets accounts banned. |

For every one of them the portal writes a tailored **cover letter**, plus
answers for notice period, salary expectation, why-this-company and work
authorisation, and attaches the country-correct resume. Open the job in
the portal, expand "Prepared answers", and paste. Nothing is ever
submitted blind: a form we cannot fill correctly is reported as
`ready to submit`, never as `submitted`.

## Pages

- **Dashboard** — pipeline KPIs, config health, manual run buttons, activity log
- **Jobs** — three tabs: **All / 🇮🇳 India / 🌍 Abroad + sponsorship**. The
  abroad tab shows only roles that plausibly sponsor or hire remotely and
  adds a **country dropdown**. Columns: match score, role, company,
  location + country, posted ("3d ago", green when fresh), experience
  required, HR contact, source, status.
- **Pipeline** — kanban board; drag cards between stages
- **Queue** — review/edit/approve every email before it sends
- **Outreach** — everything sent, with reply status and classification

## API keys (all three are configured)

| Key | Where | Notes |
|---|---|---|
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | https://developer.adzuna.com/admin/access_details | Best India coverage. |
| `RAPIDAPI_KEY` | https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch | JSearch v5. **The endpoint is `/search-v2`** — plain `/search` 404s, and results arrive as `data.jobs`. |
| `HUNTER_API_KEY` | https://hunter.io/api-keys | Named recruiters. **Free plan: 50 searches/month and `limit` must be ≤ 10** (higher 400s). Remaining quota shows on the dashboard. |

Hunter credits are precious, so contacts found for one posting are reused
for every other posting from that same company.

## Optional: JobSpy

`pip install python-jobspy`, then set `JOBSPY_SITES=indeed,naukri,google` in
`.env`. It uses public/guest endpoints with **no login**, so there is no
account to ban — but hammering it can get your IP rate-limited, so keep the
site list short. Leave `JOBSPY_SITES` empty to disable.

## Notes

- `.env` holds real credentials — never share or upload it.
- No LinkedIn/Naukri logins, scraping of your accounts, or automated
  actions on them: sources are public APIs, public web search, and your own
  mailbox. Your accounts stay safe.
- The Gmail app password only works while 2-Step Verification is on.
- Failed sends show as `failed` in the Queue with the error text.
