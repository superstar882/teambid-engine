"""Fictional LaTeX resumes for the keep-original-style tests (no real people).

SAMPLE uses the layout of a common hand-made resume (\\section*, \\subsection*, itemize, \\textbf keywords);
JAKE uses Jake's Resume template (\\resumeItem macros). PIECES / JAKE_PIECES are what keep_style.confirm keeps from
Claude's reading; SAMPLE_TEXT is what the PDF of SAMPLE reads like (with a word split across lines)."""

SAMPLE = r"""\documentclass[a4paper,10pt]{article}
\usepackage[left=0.5in,right=0.5in,top=0.6in,bottom=0.5in]{geometry}
\usepackage{hyperref}
\usepackage{enumitem}
\pagestyle{empty}
% a comment with \item in it must be ignored
\begin{document}

\begin{center}
{\Huge\bfseries DANA REYES}\\[1em]
{\LARGE SENIOR BACKEND ENGINEER}
\end{center}

\begin{center}
Austin, USA \hspace{2em} \href{mailto:dana@example.com}{dana@example.com} \hspace{2em} \href{https://github.com/dana-example}{GitHub}
\end{center}

\section*{Profile}
Backend engineer with \textbf{7+ years} building \textbf{Python} and \textbf{Go} services for payments and logistics.

\section*{Employment History}

\subsection*{Senior Backend Engineer at Northwind Labs, Austin}
\textbf{March 2022 -- Present}
\begin{itemize}[leftmargin=0.5cm]

\item Built a payments API in \textbf{Python} and FastAPI that handles 2M requests a day.

\item Cut p95 latency 40\% by moving hot reads to \textbf{Redis}.

\item Wrote the \href{https://example.com/docs}{public API docs} for 12 endpoints.

\end{itemize}

\subsection*{Backend Engineer at Contoso Freight, Remote}
\textbf{June 2019 -- February 2022}
\begin{itemize}[leftmargin=0.5cm]

\item Moved 30 cron jobs to Airflow, ending missed nightly runs.

\item Added Go unit tests for 6 backend services, raising coverage to 85\%.

\end{itemize}

\section*{Skills}
\begin{itemize}
\item {Languages:} Python, Go, SQL, C\#.

\item{Cloud \& Data:} AWS, Docker, PostgreSQL, Redis, Airflow.
\end{itemize}

\section*{Education}
\textbf{B.S. Computer Science, University of Texas} (2015 -- 2019)

\end{document}
"""

PIECES = {
    "headline": "SENIOR BACKEND ENGINEER",
    "summary": "Backend engineer with 7+ years building Python and Go services for payments and logistics.",
    "jobs": [
        {"title": "Senior Backend Engineer", "company": "Northwind Labs", "location": "Austin", "start": "2022-03", "end": "Present",
         "bullets": ["Built a payments API in Python and FastAPI that handles 2M requests a day.",
                     "Cut p95 latency 40% by moving hot reads to Redis.",
                     "Wrote the public API docs for 12 endpoints."]},
        {"title": "Backend Engineer", "company": "Contoso Freight", "location": "Remote", "start": "2019-06", "end": "2022-02",
         "bullets": ["Moved 30 cron jobs to Airflow, ending missed nightly runs.",
                     "Added Go unit tests for 6 backend services, raising coverage to 85%."]},
    ],
    "skills": [{"label": "Languages", "items": ["Python", "Go", "SQL", "C#"]},
               {"label": "Cloud & Data", "items": ["AWS", "Docker", "PostgreSQL", "Redis", "Airflow"]}],
}

SAMPLE_TEXT = """DANA REYES
SENIOR BACKEND ENGINEER
Austin, USA    dana@example.com    GitHub
Profile
Backend engineer with 7+ years building Python and Go services for payments and logistics.
Employment History
Senior Backend Engineer at Northwind Labs, Austin
March 2022 – Present
• Built a payments API in Python and FastAPI that handles 2M re-
quests a day.
• Cut p95 latency 40% by moving hot reads to Redis.
• Wrote the public API docs for 12 endpoints.
Backend Engineer at Contoso Freight, Remote
June 2019 – February 2022
• Moved 30 cron jobs to Airflow, ending missed nightly runs.
• Added Go unit tests for 6 backend services, raising coverage to 85%.
Skills
• Languages: Python, Go, SQL, C#.
• Cloud & Data: AWS, Docker, PostgreSQL, Redis, Airflow.
Education
B.S. Computer Science, University of Texas (2015 – 2019)
"""

JAKE = r"""\documentclass[letterpaper,11pt]{article}
\usepackage{titlesec}
\newcommand{\resumeItem}[1]{
  \item\small{
    {#1 \vspace{-2pt}}
  }
}
\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}
\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}
\begin{document}
\begin{center}
    \textbf{\Huge \scshape Dana Reyes} \\ \vspace{1pt}
    \small 555-0100 $|$ \href{mailto:dana@example.com}{\underline{dana@example.com}}
\end{center}
\section{Experience}
  \resumeSubHeadingListStart
    \resumeSubheading
      {Backend Engineer}{June 2022 -- Present}
      {Northwind Labs}{Austin, TX}
      \resumeItemListStart
        \resumeItem{Built a REST API in \textbf{Python} and FastAPI serving 2M requests a day} % comment, here
        \resumeItem{Cut p95 latency 40\% by moving hot reads to Redis}
        \resumeItem{Wrote the \href{https://example.com/docs}{public docs} for 12 endpoints}
      \resumeItemListEnd
    \resumeSubheading
      {Software Engineer Intern}{May 2021 -- Aug 2021}
      {Contoso}{Remote}
      \resumeItemListStart
        \resumeItem{Added Go unit tests that raised coverage to 85\%}
        \resumeItem{Automated releases with GitHub Actions}
      \resumeItemListEnd
  \resumeSubHeadingListEnd
\section{Technical Skills}
 \begin{itemize}[leftmargin=0.15in, label={}]
    \small{\item{
     \textbf{Languages}{: Java, Python, C/C++, SQL (Postgres), JavaScript} \\
     \textbf{Frameworks}{: React, Node.js, Flask, FastAPI}
    }}
 \end{itemize}
\end{document}
"""

JAKE_PIECES = {
    "headline": "", "summary": "",
    "jobs": [
        {"title": "Backend Engineer", "company": "Northwind Labs", "location": "Austin, TX", "start": "2022-06", "end": "Present",
         "bullets": ["Built a REST API in Python and FastAPI serving 2M requests a day",
                     "Cut p95 latency 40% by moving hot reads to Redis",
                     "Wrote the public docs for 12 endpoints"]},
        {"title": "Software Engineer Intern", "company": "Contoso", "location": "Remote", "start": "2021-05", "end": "2021-08",
         "bullets": ["Added Go unit tests that raised coverage to 85%", "Automated releases with GitHub Actions"]},
    ],
    "skills": [{"label": "Languages", "items": ["Java", "Python", "C/C++", "SQL (Postgres)", "JavaScript"]},
               {"label": "Frameworks", "items": ["React", "Node.js", "Flask", "FastAPI"]}],
}
