# Job scams and fake recruiters

Group: Offers · Related vault file: `Job/Playbook/Where to Find Jobs.md` · 4 sources, 11 findings

## Findings (strongest sources first)

- Red flags include upfront fees for equipment, payment by cash, Zelle or PayPal, personal email addresses, and requests for SSN, driver's license or bank details before questions are answered. (Federal Trade Commission (Consumer Advice), 2023-08-08; high)
  - Takeaway: Don't send SSN or bank info until a verified offer and real onboarding system exist.
- Fake recruiters on LinkedIn and Indeed send flattering messages, official-looking interview invites and offer letters, then ask for money or personal data. (Federal Trade Commission (Consumer Advice), 2023-08-08; high)
  - Takeaway: A polished recruiter pitch proves nothing; verify the agency and the startup independently.
- The FTC says real employers don't recruit through generic, unexpected texts or WhatsApp messages and that you should never pay to get paid. **"Never pay anyone to get paid"** (Federal Trade Commission, 2024-12-12; high)
- Task scam reports quadrupled to about 20,000 in the first half of 2024, and crypto became the main payment method. **~20,000 task scam reports in H1 2024 vs ~5,000 in 2023; ~$41M crypto losses H1 2024** (Federal Trade Commission, 2024-12-12; high)
- The FTC advises contacting the company directly using a phone number or website you know is legitimate, not one the recruiter provided. **"a phone number you know to be legitimate — not one you got from the recruiter"** (Federal Trade Commission (Consumer Advice), 2023-08-08; high)
- Reported losses to job scams more than tripled from 2020 to 2023 and reached $220 million in just the first half of 2024. **$90M (2020), $286M (2023), $220M (H1 2024)** (Federal Trade Commission, 2024-12-12; high)
- Attackers pose as recruiters from crypto or AI firms and tell candidates to clone and run packages from GitHub, GitLab or Bitbucket. (Microsoft Security Blog, 2026-03-11; high)
  - Takeaway: Directly relevant: an early-stage AI startup pitch is exactly the cover story used.
- North Korea-linked actors pose as recruiters on LinkedIn and job platforms and get developers to run malicious code during fake technical interviews. (Palo Alto Networks Unit 42, 2024-10-09; high)
  - Takeaway: A 'take-home' or live-coding task that requires running a provided repo is a known attack path for engineers.
- The malware includes BeaverTail, disguised as video-call apps such as MiroTalk and FreeConference, and the Python backdoor InvisibleFerret. (Palo Alto Networks Unit 42, 2024-10-09; high)
  - Takeaway: Only join interviews on well-known platforms; never install a meeting app a recruiter links to.
- A newer variant abuses VS Code workspace trust: trusting the repo auto-runs its task configuration file. **"If trust is granted, Visual Studio Code automatically executes the repository's task configuration file."** (Microsoft Security Blog, 2026-03-11; high)
  - Takeaway: Open any recruiter-supplied repo in restricted mode and inspect .vscode/ and package.json scripts first.
- Microsoft recommends doing coding assessments in isolated, non-persistent VMs and reviewing recruiter-provided repos before running them. (Microsoft Security Blog, 2026-03-11; high)
  - Takeaway: Use a throwaway VM for any take-home; never on the machine with cloud keys.

## Sources

| Credibility | Source | Type | Date |
|---|---|---|---|
| ★★★★★ | [Paying to get paid: gamified job scams drive record losses](https://www.ftc.gov/news-events/data-visualizations/data-spotlight/2024/12/paying-get-paid-gamified-job-scams-drive-record-losses) | official | 2024-12-12 |
| ★★★★★ | [Scammers impersonate well-known companies, recruit for fake jobs on LinkedIn and other job platforms](https://consumer.ftc.gov/consumer-alerts/2023/08/scammers-impersonate-well-known-companies-recruit-fake-jobs-linkedin-other-job-platforms) | official | 2023-08-08 |
| ★★★★☆ | [Contagious Interview: Malware delivered through fake developer job interviews](https://www.microsoft.com/en-us/security/blog/2026/03/11/contagious-interview-malware-delivered-through-fake-developer-job-interviews/) | research | 2026-03-11 |
| ★★★★☆ | [Contagious Interview: DPRK Threat Actors Lure Tech Industry Job Seekers to Install New Variants of BeaverTail and InvisibleFerret Malware](https://unit42.paloaltonetworks.com/north-korean-threat-actors-lure-tech-job-seekers-as-fake-recruiters/) | research | 2024-10-09 |
