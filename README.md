# TeamBid

A job-search pipeline for a whole team. Each member uploads a resume; TeamBid turns it into structured facts, audits
it, builds a personal knowledge vault, matches them every day against one shared scan of **~27,000 company job boards**,
and tailors resumes, cover letters and application answers for the jobs they choose, with hard guards against
invented facts.

Grew out of Quick Bid (a one-person tool). Everything learned running Quick Bid in production is built in.

## Quick start

```
cd TeamBid
python tb.py ui                       # open http://localhost:8765
```

1. **Add member**: name + resume (PDF, DOCX or TXT). Parsing, audit and vault take a few seconds.
2. **Profile**: check the parsed jobs, dates and skills (fix anything in the JSON editor), set preferences:
   target titles, lanes, level, countries, remote / home cities, companies to target or avoid, minimum score.
3. **Scans**: start a scan (about 1 hour for all boards; "Test with first N boards" for a quick try). One scan serves the
   whole team: every member is matched when it finishes. **Stop scan** keeps every finished board, so starting again the
   same day resumes. Members added after a scan are matched right away against the stored jobs (or use **Match me now**).
4. **Matches**: each member sees only jobs that fit their lanes, level and location, scored 0-100 with reasons.
5. **Apply**: pick a match (or paste a link / job text). You get a GO / CAUTION / SKIP verdict, a one-page tailored
   resume (PDF + DOCX), a cover letter draft with a writing check, and answers to common questions.
6. **Tracker**: move each application through drafting, applied, interview, offer.

Requirements: Python 3.11+ with `requests`, `pyyaml`, `python-docx`, `pymupdf`, `tzdata` (Windows). No other installs,
no paid services. Optional: `ANTHROPIC_API_KEY` for model-assisted parse cleanup and letter polish.

## Remote jobs only

The team applies to remote jobs only, so on-site and hybrid-only jobs are filtered out (members can turn on-site back
on in Profile). A remote job matches when it is open to a country the member can legally work from ("Countries you can
legally work from" on the Profile tab): e.g. a Copenhagen member (Europe) matches Remote - Denmark / EMEA / Berlin /
Nordics / DACH / Worldwide, not Remote - US or Remote - UK. For the top matches, the job description is also checked for
"must be located in the US", "right to work in the UK", "no sponsorship" and similar lines; such jobs drop 40 points
with the reason shown. Documents follow the job: a US remote job gets Letter / 1 page / US date style even for a
European member, an EU job gets A4 / up to 2 pages.

## Members outside the US (EU / UK)

Each member has a **region** (US / EU / UK / other) and **time zone**, set automatically from the location on their CV
(editable on the Profile tab). English CVs and English job posts are assumed.

| | US | EU / UK |
|---|---|---|
| Paper | Letter | A4 |
| Page budget | 1 page (2 from ~8 years) | 1 page, 2 pages from ~3 years |
| Audit length advice | 1 page under ~7-10 years | 1-2 pages |
| Letter date | October 20, 2026 | 20 October 2026 |
| Default countries | US | e.g. Germany + Europe (so "Remote - EMEA" jobs match), UK + Europe |
| Folder and letter dates | member's time zone | member's time zone |

CV dates understood: `Mar 2022`, `March 2022`, `1 March 2022`, `03/2022`, `03.2022`, `2022-03`, `15.03.2022`
(day-first with dots), `3/15/2022`, `2022-03-15`, seasons, years, and `present / current / now / to date / till date /
until now`. Salaries in $, €, £, CHF, USD, EUR, GBP are read from job posts.

## Free local AI (Ollama, optional)

If [Ollama](https://ollama.com) is running, TeamBid uses it automatically (nothing to configure); without it, everything
falls back to rules.

| Model | Used for | Safety |
|---|---|---|
| `nomic-embed-text` (fast, 20 texts/1.7 s on an i5 CPU) | Ranks resume bullets and letter stories by **meaning** against the job post; adds a "meaning match" to job scores | Writes nothing, so it can't invent facts |
| `qwen3:4b-instruct` (~13 tokens/s on CPU, ~30-60 s per letter) | Optional "polish the letter" (Apply tab) | Output must pass the fact guard (no new numbers, tools, buzzwords; company kept), the full writing check, and an **attribution check** (a paragraph about a job may only claim results that job's bullets show). One retry with the exact problems; otherwise the fact-only draft is kept |

Honest note from testing: a 4B model blends facts across jobs ("improving fault tolerance" moved to the wrong job), so
its letters are often rejected and the fact-only draft is kept. That is the intended behavior. Settings:
`OLLAMA_URL`, `TEAMBID_EMBED_MODEL`, `TEAMBID_LOCAL_MODEL`, `TEAMBID_LOCAL_AI=off`. The Claude API (if a key is set) is
preferred for polish and passes through the same guards.

## Sharing results with the team (encrypted GitHub Pages site)

`python tb.py publish` exports every member's matches, profile, resume score and fix list, applications and experience,
encrypts it with the team password (AES-256-GCM, key from PBKDF2-SHA256 with 600,000 iterations) and pushes it to the
public repo `teambid`. The page lives in a random-words folder: `https://<you>.github.io/teambid/<random-words>/`; the
repo root only says "Nothing here". The page asks for the password and decrypts in the browser. The repo only ever holds
the encrypted file; search engines are told not to index it. Commits use the name/email in `workspace/.publish.json`.

- **Automatic:** `python tb.py schedule` registers a hidden hourly task that scans once a day after 17:00 Japan time
  (3 h after Quick Bid's scan) and then publishes. Every finished `tb.py scan` also publishes.
- Change the password: `python tb.py site-password`, then `python tb.py publish`.
- The password (`workspace/.site-password`) and publish settings (`workspace/.publish.json`) stay on this PC only
  (and in the engine repo's encrypted Actions secrets, for the cloud scan).
- Team progress (status + note per job, set on the page) is stored encrypted in Supabase (`tb.py progress-setup`).
  The page reads it live; `tb.py sync` (and every publish) copies it into TeamBid.

## Daily scan in the cloud (GitHub Actions, PC can be off)

`.github/workflows/scan.yml` runs every day at 08:00 UTC (17:00 Japan time): it downloads the encrypted workspace,
scans, re-matches the team, publishes the site and uploads the workspace again. Free in a public repo.

- The workspace (database, member folders, reports) is one encrypted file (`workspace.enc`, AES-256-GCM with the team
  password), kept in the release `workspace` of the engine repo. Nothing readable is uploaded.
- One-time setup: `python tb.py cloud setup <owner>/<engine-repo>`, `python tb.py cloud push`, and three repo secrets:
  `TEAMBID_SITE_PASSWORD`, `TEAMBID_PUBLISH_JSON` (contents of `.publish.json`), `SITE_DEPLOY_KEY` (SSH key with write
  access to the `teambid` site repo).
- On the PC everything syncs by itself: commands and the web app pull the newest workspace first and push after a
  change. While the cloud scan runs, changes are refused so neither side overwrites the other.
- By hand: `tb.py cloud pull|push|status`, `tb.py cloud scan` (start it now; the web app's scan button does the same).
- The old database is kept in `workspace/backups/` (last 3) every time a newer one is pulled.

## Command line

```
python tb.py add "Jane Doe" resume.pdf        onboard a member
python tb.py members                          team overview
python tb.py audit jane-doe                   resume audit + fix list
python tb.py scan [--per-ats 50] [--days 2]   shared scan + match everyone (--per-ats N = quick test)
python tb.py stop                             stop the running scan (progress kept)
python tb.py publish                          update the encrypted team results site
python tb.py site-password                    change the team password
python tb.py match jane-doe --days 7          re-match one member after changing preferences
python tb.py matches jane-doe --new           today's matches
python tb.py apply jane-doe --job 1234        tailor for a matched job (or --url / --jd file.txt)
python tb.py status 12 applied                application status
python tb.py check letter.txt --limit 1000    writing checker
python tb.py schedule                         Windows task: hourly check, one scan a day
python tb.py test                             test suite (30 tests; live Ollama tests run only if it is up)
```

## What each member gets (their vault, plain markdown)

`workspace/members/<name>/vault/`: Profile, Experience (source of truth), Skills (proven / listed only / market gaps),
Resume Audit, Search Plan (titles + LinkedIn/Google searches), Target Companies, Story Bank (STAR outlines from their
best bullets), Answer Bank, Writing Rules, Market Insights (skills their matched jobs ask for), and prompt packs for
Claude Code / claude.ai. Shared research (29 topics, sourced findings) is in `data/knowledge/`.

## How it works

| Step | Module | Approach |
|---|---|---|
| Read the resume | `resume_parse.py` | PDF/DOCX/TXT text, section headers, date ranges, bullet repair, title-vs-company splitting, US/intl locations and phones, internships detected and excluded from years |
| Skills | `skills.py` | ~330 skills with aliases and categories; ambiguous names (Go, R, Rust...) only count in technical context |
| Level and lanes | `resume_parse.derive` | Years from merged job spans (internships excluded); lanes from recency-weighted skills and past titles |
| Audit | `analyze.py` | ATS risks (columns, tables, images), contact, numbers in bullets, weak verbs, buzzwords, gaps, length |
| Shared scan | `jobs/scanner.py`, `jobs/ats.py`, `jobs/feeds.py` | 10 job systems + 4 feeds, 32 workers, per-board checkpoint (resumes after crash/sleep), internet watchdog (re-checks only boards hit by an outage), Workday retries and multi-location detail, iCIMS HTML reader |
| Matching | `jobs/matcher.py` | Per member: lanes, level blocks, clearance, location (countries, remote, home cities), freshness, skills in title, target companies; job-description skill coverage for top matches |
| Tailoring | `tailor.py`, `render.py` | Must-have vs nice-to-have extraction, fit verdict, bullets kept word for word and ranked by relevance, skills regrouped (never added), one page enforced on the real PDF |
| Guards | `tailor.validate` | Every number must come from the resume, no skill outside the profile, no rewritten bullets, no buzzwords, no training claims |
| Writing | `writing.py`, `cover.py` | Research-based checker (AI vocabulary, participle clauses, sentence rhythm, readability); fact-only letter and answer drafts |
| UI | `server.py`, `static/index.html` | Standard-library HTTP server + one-page app (no build step, works offline) |

## Design decisions

- **One scan, many members.** Scanning 27K boards once and matching each member is N times cheaper than scanning per person.
- **Facts never invented.** Without an API key nothing is generated beyond the member's own sentences. With a key, model
  output that adds a number not found in the resume is rejected.
- **Human review where it matters.** Parsing is heuristic and resumes vary; the Profile tab shows everything parsed and
  lets the member fix it before anything is generated.
- **Local by default.** Data stays in `workspace/` on this computer. The UI binds to 127.0.0.1. To share it on a team
  network: `set TEAMBID_TOKEN=<secret>` then `python tb.py ui --host 0.0.0.0`; every request then needs the token.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `TEAMBID_WORKSPACE` | `./workspace` | database + member folders |
| `TEAMBID_TZ` | America/Los_Angeles | dates in files and reports |
| `TEAMBID_SCAN_TZ`, `TEAMBID_SCAN_HOUR` | Asia/Tokyo, 14 | when the scheduled daily scan runs |
| `ANTHROPIC_API_KEY`, `TEAMBID_MODEL` | none, claude-sonnet-5 | optional parse cleanup and letter polish |
| `TEAMBID_TOKEN` | none | required token when the UI is shared on a network |

## Limits (honest)

- Company boards come from the Common Crawl index (`data/boards.json`, copied from Quick Bid); custom career sites and
  LinkedIn/Indeed aren't scanned (paste those jobs into Apply). Refresh the board list with Quick Bid's `qb discover`.
- Job feeds (Himalayas, RemoteOK) often don't say which country a remote job is open to; such jobs score a little lower.
- Some job pages block automated reading (LinkedIn, Indeed, Himalayas): paste the text instead.
- Parsing works best on single-column resumes with clear section headers and date ranges (the audit says so too).
- A full scan takes about an hour on a good connection, longer over a slow VPN.

## Folder layout

```
TeamBid/
  tb.py                 command line
  teambid/              code (config, storage, skills, resume_parse, analyze, tailor, render, cover, writing,
                        vault, targets, llm, service, server, static/index.html, jobs/{ats, feeds, scanner, matcher, jd})
  data/                 boards.json, seed_companies.yaml, knowledge/ (shared research)
  tests/                unit tests + fictional test resumes
  workspace/            created at runtime: teambid.db, members/<name>/{resume, vault, applications, reports}, cache, reports
  workspace_demo/       sample workspace with three members and a 600-board scan (delete any time)
```
