# ATS parsing and ranking

Group: Resume · Related vault file: `Job/Resume/rules/02-structure-and-format.md` · 8 sources, 14 findings

## Findings (strongest sources first)

- The study also found document length and name frequency influenced which resumes were selected. (arXiv / AAAI-ACM Conference on AI, Ethics, and Society (AIES 2024), 2024-07-29; high)
- Abbreviated job titles and company names without formal identifiers can also cause parsing problems. (Greenhouse Support, n.d.; high)
  - Takeaway: Write full titles ('Software Engineer', not 'SWE') at least once.
- Greenhouse lists columns, tables, headers/footers, text boxes, graphics, image-only files, spaced-out letters and contact info in headers as causes of failed parses. (Greenhouse Support, n.d.; high)
  - Takeaway: Put name and contact in the body, not a header; avoid two-column templates.
- Embedding-based resume retrieval (ranking by cosine similarity to the job description) significantly favored White-associated names in 85.1% of cases and female-associated names in only 11.1%. **85.1% / 11.1%** (arXiv / AAAI-ACM Conference on AI, Ethics, and Society (AIES 2024), 2024-07-29; high)
  - Takeaway: AI rankers compare resume text to JD text; mirroring JD wording helps similarity, but the systems carry bias.
- Greenhouse Recruiting cannot parse resumes larger than 2.5MB. **"Greenhouse Recruiting can't parse resumes larger than 2.5MB."** (Greenhouse Support, n.d.; high)
  - Takeaway: Keep the PDF small and text-based, no embedded high-res images.
- Ashby's AI review checks each resume against recruiter-defined criteria and marks each as Meets or Does Not Meet, citing evidence from the resume. (Ashby, 2024-09-10; high)
  - Takeaway: State requirements explicitly in bullets (tool + outcome) so an evidence-seeking AI can find them.
- Ashby says humans make the final advance/reject decision; criteria are marked 'unknown' if undeterminable or 'skipped' if the resume is unreadable. **"it's ultimately the qualified humans on your team making an advance/reject decision"** (Ashby, 2024-09-10; high)
  - Takeaway: An unreadable resume gets skipped, so parse-safety still matters.
- MIT advises avoiding tables, columns, graphics, images and unusual bullet symbols for ATS compatibility. (MIT Career Advising & Professional Development (CAPD), 2025; medium)
  - Takeaway: Single-column layout with standard round bullets.
  - Takeaway: A clean, simple template is enough; don't pay for 'ATS optimization'.
- 97.4% of Fortune 500 companies (487 of 500) use a detectable ATS, with Workday at 40%+ and SuccessFactors around 12%. **97.4%; Workday 40%+; Workday + SuccessFactors 52.4%** (Jobscan, 2026-08-20; medium)
  - Takeaway: Big-company applications almost always go through Workday; test the resume in Workday's autofill.
- Among 384 recruiters surveyed, 76.4% filter by skills first, 59.7% by education, and 55.3% search by job title. **76.4% skills, 59.7% education, 55.3% title** (Jobscan, 2025-02-25; medium)
- Across 13,000+ companies in Jobscan's broader dataset, Greenhouse (19.0%), Workday (17.5%), Lever (15.6%) and iCIMS (14.4%) lead. **Greenhouse 19.0%, Workday 17.5%, Lever 15.6%, iCIMS 14.4%** (Jobscan, 2026-08-20; medium)
- Automatic filters that do exist mostly target work authorization, licenses, minimum qualifications and location via knockout questions. (IT Brief UK, 2025-11-19; medium)
  - Takeaway: Answer work-authorization questions accurately (permanent resident, no sponsorship needed).
- In Enhancv's interviews with 25 US recruiters, 92% said their ATS does not auto-reject resumes on formatting, keywords or match scores. **92% (23 of 25)** (IT Brief UK, 2025-11-19; low)
  - Takeaway: The widely quoted '75% rejected by ATS' stat has no clear source; focus on what humans see.

## Sources

| Credibility | Source | Type | Date |
|---|---|---|---|
| ★★★★★ | [Gender, Race, and Intersectional Bias in Resume Screening via Language Model Retrieval](https://arxiv.org/abs/2407.20371) | research | 2024-07-29 |
| ★★★★★ | [Unsuccessful resume parse](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse) | official |  |
| ★★★★☆ | [Career toolkit: Crafting an effective resume](https://capd.mit.edu/resources/career-toolkit-crafting-an-effective-resume/) | expert_guide | 2025 |
| ★★★★☆ | [Manage inbound application volume with AI-Assisted Application Review](https://www.ashbyhq.com/product-updates/ai-assisted-application-review) | official | 2024-09-10 |
| ★★★☆☆ | [Applicant Tracking System (ATS) Usage Report (Fortune 500)](https://www.jobscan.co/blog/fortune-500-use-applicant-tracking-systems/) | industry_data | 2026-08-20 |
| ★★★☆☆ | [The State of the Job Search in 2025](https://www.jobscan.co/state-of-the-job-search) | industry_data | 2025-02-25 |
| ★★★☆☆ | [Gergely Orosz on X: resume template and 'ATS proof' claims](https://x.com/GergelyOrosz/status/1816755107859476856) | community |  |
| ★★☆☆☆ | [Study reveals ATS rarely auto-rejects CVs, debunks 75% myth](https://itbrief.co.uk/story/study-reveals-ats-rarely-auto-rejects-cvs-debunks-75-myth) | news | 2025-11-19 |
