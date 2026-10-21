# TeamBid

**Your team's daily job search, done for you.** Every day TeamBid checks over 600,000 open jobs, picks the ones that
truly fit each person, and writes a tailored resume and cover letter for any job in one click. Built for small teams of
engineers who apply to remote jobs, wherever they live: the US, the UK, the EU, Serbia, Brazil and beyond.

---

## Why

Looking for a remote job takes hours a day: opening dozens of job sites, reading posts that turn out to be US-only or
hybrid, guessing which skills matter, and rewriting the same resume again and again. Most of that is the same work for
everyone on a team, and most of it can be automated, honestly.

## What each member gets

- **A short daily list of jobs that fit them**, posted yesterday or today, ranked 0-100, with the reason for every
  score: "has 6 of 8 required skills; missing: Kafka", "asks 5+ years: you have 7", "open to Europe (CET)".
- **Only jobs they can actually take.** Remote, open to the country they live in (checked in the post *and* the
  application form), not secretly hybrid, not asking for skills or years they don't have.
- **A tailored resume and cover letter for any job, in about 5 minutes.** Built only from facts in their own resume,
  fact-checked, as PDF and Word, plus a "copy cover letter" button.
- **A shared team page** to save, mark applied, add notes and track applications together.
- **Their own profile**, editable on the page: jobs, skills, education, preferences (countries, target titles,
  companies to avoid).

## How it works

```
 Every day                                    For each member                       When they want to apply
 ───────────────────────────────────────      ──────────────────────────────────    ──────────────────────────────
 1 Download 630k open jobs from 52k     ──►   5 Keep engineering jobs posted   ──►  8 Click "Tailor" on a job
   company career pages + 14 job feeds          yesterday or today, at the          9 Resume + cover letter are
 2 Read every engineering job's                 right level                           written from their real
   description: skills, years, where          6 Keep only remote jobs open to        resume, fact-checked
   it's open to, hybrid or not                  their country                      10 Download, apply, mark
 3 Read application forms ("Are you           7 Score on their skills and years,      "Applied" for the team
   authorized to work in…?")                    remove duplicates
 4 Publish an encrypted team page
```

1. **Collect.** Each day at 14:00 (Japan time), on GitHub's servers, TeamBid downloads every open job from
   **52,553 company career pages** (Greenhouse, Lever, Ashby, Workday, Workable, BambooHR, Personio, Teamtailor,
   SmartRecruiters, Recruitee, Breezy, iCIMS, Pinpoint) and **14 job feeds** (Himalayas, Jobicy, We Work Remotely,
   4dayweek, Djinni, Get on Board, Jobindex, JobTech and more).
2. **Understand.** For every engineering job it reads the description: required and nice-to-have skills, years of
   experience, the countries or time zones it is open to, "US residents only" style limits, and office/hybrid wording.
3. **Double-check.** Where the job system allows it, it also reads the application form, which often says what the
   post doesn't: "Are you legally authorized to work in the United States?", "Do you hold a work permit for France?",
   "Hybrid 3 days a week?", "Do you speak fluent French?".
4. **Match.** For each member: engineering roles at their level, posted yesterday or today, remote and open to their
   country, scored mostly on how many required skills their resume shows, then years and title. Duplicates from
   several sources are merged.
5. **Share.** Results go to a team web page, encrypted with the team password.
6. **Apply.** On the page, a member clicks **Tailor**, picks the writer (Claude Haiku, Claude Sonnet or a free
   template) and gets a resume and cover letter built from their own resume, checked so no number, skill or result is
   invented.
7. **Track.** Saved / Applied / Interview / Offer / Rejected, with notes, shared by the whole team.

## Trust and privacy

- **Encrypted everywhere.** The team page, team progress, member data and documents are encrypted (AES-256) with the
  team password. Nothing readable is stored online.
- **No invented facts.** Every resume line and letter claim comes from the member's own resume. Generated text that
  adds a number, tool or result the resume doesn't have is rejected.
- **Fair use of job sites.** Only official APIs and public feeds whose terms allow automated reading. Sites that forbid
  it are not used (for example Ashby's application-form data, Gupy, JOIN, No Fluff Jobs, Just Join IT).
- **Free to run.** GitHub Actions (public repo), GitHub Pages and Supabase's free tier. A Claude API key is optional.

## Getting started

**As a team member:** ask your team for the page link and password. Open it, pick your name, check your profile once
(fix anything the resume reader got wrong), and look at your matches each day.

**As the person running it** (once):

1. Fork this repo and add the results-site repo, the team password and the Supabase settings as Actions secrets
   (`TEAMBID_SITE_PASSWORD`, `TEAMBID_PUBLISH_JSON`, `SITE_DEPLOY_KEY`). See *Cloud setup* below.
2. Add members on the team page (**+ Add member**: name + resume). Everything else runs by itself.
3. Optional: `python tb.py claude-key` to let Claude write the letters (Claude Max plans include monthly API credits).

## In numbers (one daily scan)

| | |
|---|---|
| Company career pages | 52,553 on 13 job systems |
| Job feeds | 14 |
| Open jobs checked | ~630,000 |
| Job descriptions analyzed | ~90,000 (new ones each day; each job once) |
| Application forms read | ~50,000 (new ones each day) |
| Time | ~35-70 minutes in the cloud, nobody's computer needed |

---

# Technical reference

## Architecture

| Part | Where | What |
|---|---|---|
| Daily scan | `.github/workflows/scan.yml`, `teambid/jobs/scanner.py` | Pulls the encrypted workspace, applies team changes, downloads all boards (32 workers, checkpointed), analyzes new descriptions on all cores, reads new forms (time-boxed), matches everyone, publishes, pushes the workspace back (plus a dated daily copy) |
| Job systems | `teambid/jobs/ats.py`, `feeds.py` | 13 job systems (EU Lever host fallback, Personio language fallback, BambooHR detail for date and description) and 14 feeds |
| Job facts | `teambid/jobs/facts.py` | Per job: must/nice skills, years, regions, work-rights limits, US-only wording, hybrid/office wording; kept as compact JSON (not the text) |
| Forms | `teambid/jobs/forms.py` | Greenhouse API (`questions=true`), Lever `/apply` (1 request/s, its Crawl-delay), Workable `/api/v1/jobs/{code}/form` |
| Matching | `teambid/jobs/matcher.py` | Level, posting window, place rules, skills coverage, years, duplicates, form and post limits |
| Company offices | `teambid/jobs/company.py` | Where a company is based, from the offices in its job posts |
| Team page | `teambid/static/results.html`, `export.py` | One encrypted file, decrypted in the browser (Web Crypto, PBKDF2 600k) |
| Team progress and requests | `teambid/progress.py`, `admin.py`, `docs.py` | Append-only encrypted rows in Supabase: statuses, notes, add/edit/delete member, document requests |
| Documents | `.github/workflows/docs.yml`, `tailor.py`, `cover.py`, `llm.py`, `render.py` | Started instantly from the page (Supabase function → GitHub), PDF/DOCX encrypted onto the site |
| Resume reader | `teambid/resume_parse.py` | PDF/DOCX/TXT, two-column designs, spaced headings, dates in US and EU formats |
| Local app (optional) | `tb.py ui`, `teambid/server.py` | Same data on your own computer, synced with the cloud copy |

## Matching rules

- **Window:** `days` (default 2) = posted today or yesterday; jobs without a posting date use the day first seen.
- **Place:** remote only (unless on-site in a home city is allowed). Members who can't work in the US keep a
  "remote" job only if its post or form shows it is open to their region; posts or forms limited to other countries,
  hybrid or office work are dropped.
- **Skills:** with a description, any engineering title can match; required skills on the resume carry most of the
  score, and posts needing several skills the resume lacks (under 40% of 3+) are dropped. Without a description the
  title must fit the member's lanes or target titles.
- **Years:** asking 3+ more years than the member has drops the job; a smaller gap lowers the score.
- **Duplicates:** the same role from several sources or locations is shown once.

## Cloud setup

1. `python tb.py site-password` and `python tb.py progress-setup <supabase-url> <anon-key>`; run the SQL files in
   `setup/` in Supabase (progress table; `supabase-instant-docs.sql` for instant document builds).
2. `python tb.py cloud setup <owner>/<repo>` and `python tb.py cloud push` (uploads the encrypted workspace).
3. Actions secrets: `TEAMBID_SITE_PASSWORD`, `TEAMBID_PUBLISH_JSON` (contents of `workspace/.publish.json`),
   `SITE_DEPLOY_KEY` (write deploy key of the results-site repo), optional `ANTHROPIC_API_KEY`.
4. Workflows: **Daily scan** (05:00 UTC), **Tailor documents** (on request + every 15 min), **Maintenance**
   (team changes, re-read resumes, re-match, publish).

## Command line

```
python tb.py ui                               local app (http://localhost:8765)
python tb.py scan [--per-ats 5] [--only greenhouse,lever]   scan + match (small test with --per-ats)
python tb.py match <member>                   re-match one member
python tb.py reparse <member|all>             read resumes again (after reader fixes)
python tb.py publish                          update the encrypted team page
python tb.py cloud pull|push|status|scan      sync with the cloud copy / start the cloud scan
python tb.py docs | admin apply|confirm       document requests / team changes (used by the workflows)
python tb.py claude-key [--remove]            Claude API key (here and as a GitHub secret)
python tb.py test                             test suite
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `TEAMBID_WORKSPACE` | `./workspace` | database and member folders |
| `TEAMBID_TZ` | America/Los_Angeles | dates in files and reports |
| `TEAMBID_FORM_MINUTES` | 30 | time box for reading application forms per scan |
| `ANTHROPIC_API_KEY`, `TEAMBID_MODEL` | none, claude-sonnet-5-5 | Claude writing (the page chooses Haiku or Sonnet per request) |
| `TEAMBID_TOKEN` | none | token when the local app is shared on a network |

## Sources and licenses

- Company board list: [kalil0321/ats-scrapers](https://github.com/kalil0321/ats-scrapers) (MIT) plus Common Crawl.
- Feeds used with attribution where asked: Himalayas, RemoteOK, Remotive, HN "Who is hiring", Jobicy, 4dayweek,
  Working Nomads, Get on Board, Djinni, Jobindex, JobTech (CC0), Brazilian community boards on GitHub, We Work Remotely.

## Honest limits

- Jobs on custom career sites, LinkedIn or Indeed aren't scanned; paste those into the Documents tab instead.
- Some job systems publish no posting date (Pinpoint, some iCIMS layouts): those use the day first seen.
- Application forms are read for Greenhouse, Lever and Workable only; Lever is read slowly (its rules), so a backlog
  clears over a few days.
- The resume reader handles common layouts, including two columns; always check a new member's profile once.

## Folder layout

```
tb.py            command line
teambid/         code: jobs/ (scan, job systems, feeds, facts, forms, matching), resume reader, tailoring,
                 page export, cloud sync, team requests, static/ (team page, local app)
data/            boards.json (company boards), seed companies, knowledge/ (job-search research)
setup/           Supabase SQL
tests/           unit tests with fictional resumes
.github/         daily scan, documents, maintenance workflows
```
