"""Fictional test resumes (no real people): a mid-level frontend engineer (DOCX) and a senior data engineer (TXT)."""
from pathlib import Path

import docx

HERE = Path(__file__).resolve().parent / "fixtures"

FRONTEND = [
    ("Maya Chen", "Title"),
    ("Frontend Engineer | React, TypeScript", None),
    ("Austin, TX | maya.chen@example.com | (512) 555-0142 | linkedin.com/in/maya-chen-example | github.com/mayachen-example", None),
    ("SUMMARY", None),
    ("Frontend engineer who builds fast, accessible React apps for B2B SaaS.", None),
    ("EXPERIENCE", None),
    ("Brightline Analytics | Frontend Engineer | Austin, TX | Mar 2022 - Present", None),
    ("Rebuilt the reporting dashboard in React and TypeScript, cutting load time from 6 s to 1.8 s for 40,000 users.", "List Bullet"),
    ("Led the move from Redux to React Query and Zustand across 120 screens, removing 9,000 lines of code.", "List Bullet"),
    ("Built a component library in Storybook with Tailwind CSS used by 4 product teams.", "List Bullet"),
    ("Raised Lighthouse accessibility scores to 98 by fixing WCAG issues across checkout.", "List Bullet"),
    ("Pixelworks Studio | Junior Web Developer | Remote | Jun 2020 - Feb 2022", None),
    ("Shipped 25+ marketing sites in Next.js and Vue.js with Jest and Cypress tests.", "List Bullet"),
    ("Cut build times by 40% by moving from Webpack to Vite.", "List Bullet"),
    ("Campus Tech Help | Web Development Intern | Austin, TX | May 2019 - Aug 2019", None),
    ("Built an internal ticket form in JavaScript and Node.js that handled 300 requests a week.", "List Bullet"),
    ("EDUCATION", None),
    ("University of Texas at Austin | B.S. in Computer Science | 2016 - 2020 | GPA 3.6", None),
    ("SKILLS", None),
    ("Languages: TypeScript, JavaScript, HTML, CSS", None),
    ("Frameworks: React, Next.js, Vue.js, Redux, Tailwind CSS, Storybook", None),
    ("Testing and tools: Jest, Cypress, Playwright, Git, Figma, GitHub Actions", None),
]

DATA_TXT = """RAJ PATEL
Senior Data Engineer
Bengaluru, India  |  raj.patel@example.org  |  +91 98450 12345  |  linkedin.com/in/raj-patel-example

PROFESSIONAL SUMMARY
Data engineer with 8 years building batch and streaming pipelines on AWS.

WORK EXPERIENCE
Senior Data Engineer, Northwind Retail Data        Jan 2021 - Present
- Designed Airflow and Spark pipelines on AWS (S3, EMR, Glue) that process 3 TB a day for 200 analysts.
- Moved the warehouse from Redshift to Snowflake with dbt models, cutting monthly cost by 35%.
- Built Kafka streaming ingestion for 50,000 events per second with exactly-once delivery.
- Mentored 4 engineers and set code review standards for the data platform team.

Data Engineer, Contoso Fintech        Jul 2017 - Dec 2020
- Built PySpark ETL jobs for fraud features used by 12 ML models.
- Created data quality checks with Great Expectations that caught 1,200 bad records a month.

Software Engineer, Fabrikam Systems        Aug 2015 - Jun 2017
- Wrote Java and SQL services for billing reports used by 30 enterprise customers.

EDUCATION
Indian Institute of Technology Bombay, B.Tech in Computer Science, 2011 - 2015

TECHNICAL SKILLS
Python, SQL, Scala, Java, Apache Spark, PySpark, Airflow, dbt, Kafka, Snowflake, Redshift, AWS, Terraform, Docker
CERTIFICATIONS
AWS Certified Data Engineer - Associate
"""


EU_TXT = """LENA SCHMIDT
Backend Engineer
Berlin, Germany  |  lena.schmidt@example.de  |  +49 30 1234 5678  |  linkedin.com/in/lena-schmidt-example

PROFILE
Backend engineer building payment and logistics APIs in Python and Go.

WORK EXPERIENCE
Backend Engineer, Parcelway GmbH        03.2022 – present
- Built Go and Python microservices for parcel tracking that handle 2,000 requests per second.
- Moved order events from cron jobs to Kafka, cutting delivery-status delay from 15 minutes to 20 seconds.
- Wrote PostgreSQL migrations and Redis caching that reduced API latency by 45%.

Software Developer, Finora Payments        01.2019 – 02.2022
- Developed REST APIs in Django for SEPA payments used by 300 merchants.
- Added pytest and GitHub Actions pipelines, raising test coverage from 40% to 85%.

Working Student, Software Development, Datenwerk        15.09.2016 – 31.12.2018
- Built internal Flask tools for report exports used by 40 colleagues.

EDUCATION
Technical University of Munich, M.Sc. in Informatics, 10.2016 – 09.2018
Karlsruhe Institute of Technology, B.Sc. in Computer Science, 10.2013 – 09.2016

SKILLS
Python, Go, SQL, Django, Flask, FastAPI, PostgreSQL, Redis, Kafka, Docker, Kubernetes, AWS, GitHub Actions

LANGUAGES
English (C1), German (native)
"""


def make():
    HERE.mkdir(exist_ok=True)
    out = HERE / "maya_chen_frontend.docx"
    if out.exists():                 # a fresh save changes the file's timestamps: keep git clean between test runs
        (HERE / "raj_patel_data.txt").write_text(DATA_TXT, encoding="utf-8")
        (HERE / "lena_schmidt_eu.txt").write_text(EU_TXT, encoding="utf-8")
        return out, HERE / "raj_patel_data.txt"
    d = docx.Document()
    for text, style in FRONTEND:
        if style == "Title":
            d.add_paragraph(text).runs[0].bold = True
        elif style:
            d.add_paragraph(text, style=style)
        else:
            d.add_paragraph(text)
    d.save(HERE / "maya_chen_frontend.docx")
    (HERE / "raj_patel_data.txt").write_text(DATA_TXT, encoding="utf-8")
    (HERE / "lena_schmidt_eu.txt").write_text(EU_TXT, encoding="utf-8")
    return HERE / "maya_chen_frontend.docx", HERE / "raj_patel_data.txt"


if __name__ == "__main__":
    print(make())
