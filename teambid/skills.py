"""Skills taxonomy: canonical name -> (category, aliases). Used to read skills out of resumes and job posts,
compare them, and infer a member's career lanes (AI, data, backend, frontend...).

Matching is case-insensitive with word boundaries that also work for names like C++, C#, .NET and Node.js.
Short or ambiguous names (Go, R, C, Rust...) only count in clearly technical contexts (see AMBIGUOUS).
"""
import re
from collections import Counter
from functools import lru_cache

S = {
    # languages
    "Python": ("language", ["python3", "python 3"]), "Java": ("language", []), "JavaScript": ("language", ["js", "es6", "ecmascript"]),
    "TypeScript": ("language", ["ts"]), "Go": ("language", ["golang"]), "Rust": ("language", []), "C": ("language", []),
    "C++": ("language", ["cpp"]), "C#": ("language", ["c sharp", "csharp"]), "Kotlin": ("language", []), "Swift": ("language", []),
    "Objective-C": ("language", ["objective c"]), "Ruby": ("language", []), "PHP": ("language", []), "Scala": ("language", []),
    "R": ("language", []), "SQL": ("language", ["t-sql", "pl/sql", "plsql"]), "Bash": ("language", ["shell scripting", "bash scripting"]),
    "PowerShell": ("language", []), "Dart": ("language", []), "Elixir": ("language", []), "Haskell": ("language", []),
    "Lua": ("language", []), "MATLAB": ("language", []), "Perl": ("language", []), "Julia": ("language", []),
    "Solidity": ("language", []), "HTML": ("frontend", ["html5"]), "CSS": ("frontend", ["css3"]), "Sass": ("frontend", ["scss"]),
    # frontend
    "React": ("frontend", ["react.js", "reactjs"]), "Next.js": ("frontend", ["nextjs", "next js"]), "Vue.js": ("frontend", ["vue", "vuejs", "vue 3"]),
    "Nuxt": ("frontend", ["nuxt.js"]), "Angular": ("frontend", ["angularjs"]), "Svelte": ("frontend", ["sveltekit"]),
    "Redux": ("frontend", []), "Tailwind CSS": ("frontend", ["tailwind", "tailwindcss"]), "Bootstrap": ("frontend", []),
    "jQuery": ("frontend", []), "Webpack": ("frontend", []), "Vite": ("frontend", []), "Storybook": ("frontend", []),
    "Material UI": ("frontend", ["mui"]), "Three.js": ("frontend", ["threejs"]), "D3.js": ("frontend", ["d3"]),
    "WebGL": ("frontend", []), "Remix": ("frontend", []), "Astro": ("frontend", []), "Ember.js": ("frontend", ["ember"]),
    "Figma": ("design", []), "Accessibility": ("frontend", ["a11y", "wcag"]), "Responsive design": ("frontend", []),
    "Zustand": ("frontend", []), "React Query": ("frontend", ["tanstack query"]), "Web Components": ("frontend", []),
    # mobile
    "React Native": ("mobile", ["expo"]), "Flutter": ("mobile", []), "SwiftUI": ("mobile", []), "UIKit": ("mobile", []),
    "Android": ("mobile", ["android sdk"]), "iOS": ("mobile", []), "Jetpack Compose": ("mobile", []), "Xcode": ("mobile", []),
    # backend frameworks
    "Node.js": ("backend", ["nodejs", "node js"]), "Express": ("backend", ["express.js", "expressjs"]), "NestJS": ("backend", ["nest.js"]),
    "Django": ("backend", []), "Flask": ("backend", []), "FastAPI": ("backend", []), "Spring Boot": ("backend", ["spring framework", "spring mvc"]),
    "Ruby on Rails": ("backend", ["rails"]), ".NET": ("backend", ["dotnet", ".net core", "asp.net", "asp.net core"]),
    "Laravel": ("backend", []), "GraphQL": ("backend", ["apollo graphql"]), "REST APIs": ("backend", ["restful", "rest api", "restful apis", "rest apis", "restful api"]),
    "gRPC": ("backend", ["protobuf", "protocol buffers"]), "Microservices": ("backend", ["microservice"]),
    "WebSockets": ("backend", ["websocket", "socket.io"]), "Celery": ("backend", []), "RabbitMQ": ("backend", []),
    "Kafka": ("data", ["apache kafka"]), "Redis": ("database", []), "Nginx": ("devops", []), "OAuth": ("security", ["oauth2", "oidc", "openid connect"]),
    "Temporal": ("backend", []), "Cadence": ("backend", []), "Hibernate": ("backend", []), "Gin": ("backend", []),
    "Stripe": ("backend", ["stripe api"]), "Twilio": ("backend", []), "Supabase": ("database", []), "Firebase": ("database", ["firestore"]),
    "Prisma": ("database", []), "SQLAlchemy": ("database", []), "Pydantic": ("backend", []), "Serverless": ("cloud", ["serverless framework"]),
    "Event-driven architecture": ("backend", ["event driven", "event-driven"]), "Distributed systems": ("backend", ["distributed system"]),
    "System design": ("backend", []), "API design": ("backend", []),
    # databases
    "PostgreSQL": ("database", ["postgres", "psql"]), "MySQL": ("database", ["mariadb"]), "MongoDB": ("database", ["mongo"]),
    "SQLite": ("database", []), "Oracle": ("database", ["oracle db"]), "SQL Server": ("database", ["mssql", "ms sql", "microsoft sql server"]),
    "DynamoDB": ("database", []), "Cassandra": ("database", []), "Elasticsearch": ("database", ["elastic search", "opensearch"]),
    "Neo4j": ("database", []), "ClickHouse": ("database", []), "CockroachDB": ("database", []), "Couchbase": ("database", []),
    "DocumentDB": ("database", []), "Cosmos DB": ("database", ["cosmosdb"]), "Memcached": ("database", []),
    # data engineering
    "Apache Spark": ("data", ["spark", "pyspark"]), "PySpark": ("data", []), "Hadoop": ("data", ["hdfs", "hive"]), "Airflow": ("data", ["apache airflow"]),
    "dbt": ("data", ["data build tool"]), "Snowflake": ("data", []), "BigQuery": ("data", []), "Redshift": ("data", []),
    "Databricks": ("data", []), "Flink": ("data", ["apache flink"]), "Beam": ("data", ["apache beam", "dataflow"]),
    "ETL": ("data", ["elt", "etl pipelines", "data pipelines", "data pipeline"]), "Data modeling": ("data", ["data modelling", "dimensional modeling"]),
    "Data warehousing": ("data", ["data warehouse"]), "Data lake": ("data", ["lakehouse", "delta lake"]), "Iceberg": ("data", ["apache iceberg"]),
    "Kinesis": ("data", []), "Pandas": ("data", []), "NumPy": ("data", []), "Polars": ("data", []), "Dask": ("data", []),
    "Fivetran": ("data", []), "Looker": ("analytics", []), "Tableau": ("analytics", []), "Power BI": ("analytics", ["powerbi"]),
    "Excel": ("analytics", ["microsoft excel"]), "A/B testing": ("analytics", ["ab testing", "a/b tests", "experimentation"]),
    "Data validation": ("data", ["data quality"]), "Streaming": ("data", ["stream processing", "real-time data"]),
    "Salesforce": ("data", ["salesforce crm"]), "Web scraping": ("data", ["scraping", "beautifulsoup", "scrapy", "selenium scraping"]),
    "Statistics": ("analytics", ["statistical analysis"]), "Jupyter": ("data", ["jupyter notebook"]),
    # ML / AI
    "Machine learning": ("ml", ["ml"]), "Deep learning": ("ml", []), "PyTorch": ("ml", ["torch"]), "TensorFlow": ("ml", []),
    "Keras": ("ml", []), "scikit-learn": ("ml", ["sklearn", "scikit learn"]), "XGBoost": ("ml", ["lightgbm"]), "JAX": ("ml", []),
    "Computer vision": ("ml", ["opencv", "image recognition"]), "NLP": ("ml", ["natural language processing"]),
    "MLOps": ("ml", ["ml ops"]), "MLflow": ("ml", []), "Kubeflow": ("ml", []), "SageMaker": ("ml", ["aws sagemaker"]),
    "Vertex AI": ("ai", ["google vertex ai"]), "Hugging Face": ("ai", ["huggingface", "transformers"]), "Recommendation systems": ("ml", ["recommender systems", "recsys"]),
    "Time series": ("ml", ["forecasting"]), "Feature engineering": ("ml", []), "Model evaluation": ("ai", ["evals", "llm evaluation", "model evals"]),
    "LLMs": ("ai", ["llm", "large language models", "large language model"]), "Generative AI": ("ai", ["genai", "gen ai"]),
    "RAG": ("ai", ["retrieval-augmented generation", "retrieval augmented generation"]), "Prompt engineering": ("ai", ["prompting"]),
    "AI agents": ("ai", ["agentic", "agents", "agentic ai", "multi-agent"]), "LangChain": ("ai", []), "LangGraph": ("ai", []),
    "LlamaIndex": ("ai", []), "CrewAI": ("ai", []), "MCP": ("ai", ["model context protocol"]), "OpenAI API": ("ai", ["openai", "gpt-4", "gpt-4o", "chatgpt api"]),
    "Claude API": ("ai", ["anthropic", "claude"]), "Gemini": ("ai", ["google gemini"]), "Embeddings": ("ai", ["embedding", "vector embeddings"]),
    "Vector databases": ("ai", ["vector database", "vector db", "vector search"]), "ChromaDB": ("ai", ["chroma"]), "Pinecone": ("ai", []),
    "Weaviate": ("ai", []), "pgvector": ("ai", []), "Milvus": ("ai", []), "FAISS": ("ai", []), "Fine-tuning": ("ai", ["fine tuning", "finetuning", "lora"]),
    "Function calling": ("ai", ["tool calling", "tool use", "structured outputs"]), "Semantic Kernel": ("ai", []), "Azure OpenAI": ("ai", []),
    "AWS Bedrock": ("ai", ["bedrock"]), "Ollama": ("ai", []), "vLLM": ("ai", []), "Speech recognition": ("ai", ["asr", "whisper"]),
    "Reinforcement learning": ("ml", ["rlhf"]),
    # cloud / devops
    "AWS": ("cloud", ["amazon web services"]), "GCP": ("cloud", ["google cloud", "google cloud platform"]), "Azure": ("cloud", ["microsoft azure"]),
    "AWS Lambda": ("cloud", ["lambda"]), "S3": ("cloud", ["aws s3", "amazon s3"]), "EC2": ("cloud", []), "ECS": ("cloud", ["fargate"]), "EKS": ("cloud", []),
    "CloudFormation": ("devops", []), "API Gateway": ("cloud", []), "Cloud Run": ("cloud", []), "App Engine": ("cloud", ["gcp app engine"]),
    "Docker": ("devops", ["containers", "containerization"]), "Kubernetes": ("devops", ["k8s"]), "Helm": ("devops", []), "Terraform": ("devops", ["iac", "infrastructure as code"]),
    "Ansible": ("devops", []), "CI/CD": ("devops", ["ci cd", "continuous integration", "continuous delivery"]), "GitHub Actions": ("devops", []),
    "Jenkins": ("devops", []), "GitLab CI": ("devops", []), "CircleCI": ("devops", []), "ArgoCD": ("devops", ["argo cd"]),
    "Prometheus": ("devops", []), "Grafana": ("devops", []), "Datadog": ("devops", []), "OpenTelemetry": ("devops", ["otel"]),
    "Observability": ("devops", ["monitoring", "logging"]), "Linux": ("devops", ["unix"]), "Vercel": ("cloud", []), "Netlify": ("cloud", []),
    "Heroku": ("cloud", []), "Render": ("cloud", []), "Cloudflare": ("cloud", ["cloudflare workers"]), "DigitalOcean": ("cloud", []),
    "SRE": ("devops", ["site reliability"]), "Networking": ("devops", ["tcp/ip", "dns", "load balancing"]),
    # security
    "Application security": ("security", ["appsec", "owasp"]), "IAM": ("security", []), "Penetration testing": ("security", ["pentesting", "pen testing"]),
    "Cryptography": ("security", ["encryption"]), "SOC 2": ("security", ["soc2"]), "Zero trust": ("security", []),
    # testing
    "Unit testing": ("testing", ["unit tests"]), "pytest": ("testing", []), "Jest": ("testing", []), "Cypress": ("testing", []),
    "Playwright": ("testing", []), "Selenium": ("testing", []), "JUnit": ("testing", []), "TDD": ("testing", ["test-driven development"]),
    "Integration testing": ("testing", ["integration tests", "end-to-end testing", "e2e"]), "Postman": ("testing", []),
    # tools / practice
    "Git": ("tools", ["github", "gitlab", "bitbucket"]), "Jira": ("tools", []), "Agile": ("practice", ["scrum", "kanban"]),
    "Code review": ("practice", ["code reviews"]), "Technical writing": ("practice", ["documentation"]), "Mentoring": ("practice", ["mentorship", "coaching"]),
    "Cross-functional collaboration": ("practice", ["cross-functional"]), "Product management": ("practice", ["product strategy"]),
    "Claude Code": ("tools", ["cursor", "copilot", "github copilot", "ai coding tools"]), "Unity": ("other", []), "Unreal": ("other", ["unreal engine"]),
    "Embedded": ("other", ["embedded systems", "firmware", "rtos"]), "Blockchain": ("other", ["web3", "smart contracts"]),
    "HubSpot": ("data", []), "SAP": ("other", []), "ServiceNow": ("other", []), "Shopify": ("backend", []), "WordPress": ("frontend", []),
    "Electron": ("frontend", ["electrobun", "tauri"]), "Valgrind": ("tools", []),
}

# names that are also ordinary words: only count them when the text around them is clearly technical
AMBIGUOUS = {"Go", "R", "C", "Rust", "Swift", "Spark", "Express", "Gin", "Beam", "Temporal", "Render", "Remix", "Astro",
             "Unity", "Agile", "Excel", "Statistics", "Streaming", "Networking", "Observability", "Oracle", "Gemini", "Helm",
             "Mentoring", "Linux", "Embedded", "Iceberg", "Elixir", "Julia", "Dart", "Lua", "Cadence", "Kinesis"}

# which career lanes a skill category feeds
LANE_OF = {"ai": "ai", "ml": "ml", "data": "data", "analytics": "data", "backend": "backend", "database": "backend",
           "frontend": "frontend", "design": "frontend", "mobile": "mobile", "cloud": "devops", "devops": "devops",
           "security": "security"}

LANES = {
    "ai": ("AI / LLM engineering", ["AI Engineer", "Applied AI Engineer", "LLM Engineer", "Generative AI Engineer", "AI/ML Engineer", "Forward Deployed Engineer"]),
    "ml": ("Machine learning", ["Machine Learning Engineer", "ML Engineer", "MLOps Engineer", "Applied Scientist"]),
    "data": ("Data engineering", ["Data Engineer", "Analytics Engineer", "Data Platform Engineer", "ETL Developer", "BI Engineer"]),
    "backend": ("Backend", ["Backend Engineer", "Software Engineer", "API Engineer", "Platform Engineer"]),
    "frontend": ("Frontend", ["Frontend Engineer", "UI Engineer", "Web Developer", "React Developer"]),
    "fullstack": ("Full-stack", ["Full Stack Engineer", "Software Engineer", "Product Engineer"]),
    "mobile": ("Mobile", ["Mobile Engineer", "iOS Engineer", "Android Engineer", "React Native Developer"]),
    "devops": ("DevOps / cloud", ["DevOps Engineer", "Site Reliability Engineer", "Cloud Engineer", "Infrastructure Engineer"]),
    "security": ("Security", ["Security Engineer", "Application Security Engineer"]),
    "qa": ("Quality / test", ["QA Engineer", "Test Automation Engineer", "SDET"]),
}

# job-title words per lane, used by the matcher (regex fragments)
TITLE_WORDS = {
    "ai": r"AI|A\.I\.|LLM|GenAI|Gen AI|Generative|Artificial Intelligence|Applied AI|AI/ML|Agent|Agentic|Forward Deployed|Prompt",
    "ml": r"Machine Learning|ML|MLOps|Applied Scientist|Deep Learning|Computer Vision|NLP|Recommendation|Ranking",
    "data": r"Data Engineer|Analytics Engineer|Data Platform|ETL|Data Infrastructure|BI Engineer|Business Intelligence|Data Warehouse|Data Developer",
    "backend": r"Backend|Back[- ]End|Server|API|Platform Engineer|Software Engineer|Software Developer|Python|Golang|Go Engineer|Java Engineer|Java Developer|Distributed",
    "frontend": r"Front[- ]?End|UI Engineer|UI Developer|Web Developer|React|Angular|Vue|JavaScript Engineer|Web Engineer",
    "fullstack": r"Full[- ]?Stack|Fullstack|Software Engineer|Software Developer|Product Engineer|Web Developer",
    "mobile": r"Mobile|iOS|Android|React Native|Flutter|Swift",
    "devops": r"DevOps|SRE|Site Reliability|Infrastructure|Cloud Engineer|Platform Engineer|Release Engineer|Build Engineer",
    "security": r"Security|AppSec|Application Security|Cyber",
    "qa": r"QA|Quality|Test|SDET",
}


def _alias_pattern(alias):
    a = re.escape(alias.lower())
    return rf"(?<![\w+#.]){a}(?![\w+#])"


@lru_cache(maxsize=1)
def _compiled():
    out = []
    for name, (cat, aliases) in S.items():
        names = [name] + aliases
        pat = re.compile("|".join(_alias_pattern(a) for a in sorted(set(names), key=len, reverse=True)), re.I)
        out.append((name, cat, pat, tuple({a.lower() for a in names})))   # literal anchors: skip the regex when none occurs
    return out


_TECH_CONTEXT = re.compile(r"(?i)\b(language|languages|stack|skills|framework|library|code|coding|program|develop|engineer|"
                           r"python|java|sql|api|backend|frontend|services?|pipelines?|tools?|technolog)")


def find(text, with_counts=False, trusted=False):
    """Skills mentioned in text -> list of canonical names (or Counter with counts).
    trusted=True: the text is a skills list, so short names like Go or R count without extra context."""
    if not text:
        return Counter() if with_counts else []
    low = text.lower()
    found = Counter()
    for name, cat, pat, anchors in _compiled():
        if not any(x in low for x in anchors):
            continue
        hits = pat.findall(low)
        if not hits:
            continue
        if name in AMBIGUOUS and not trusted:
            # keep only if written with the exact canonical casing somewhere (e.g. "Go", "R") and the text is technical
            exact = re.findall(rf"(?<![\w+#.]){re.escape(name)}(?![\w+#])", text)
            if name in ("Go",):
                exact += re.findall(r"(?i)\bgolang\b", text)
            if not exact or not _TECH_CONTEXT.search(text):
                continue
            hits = exact
        found[name] += len(hits)
    if "PySpark" in found:
        found["Apache Spark"] += 0
    return found if with_counts else list(found)


def category(name):
    return S.get(name, ("other", []))[0]


def lane_scores(skill_counts, titles=()):
    """Evidence per career lane from skills (Counter) and past job titles."""
    lanes = Counter()
    for sk, n in skill_counts.items():
        lane = LANE_OF.get(category(sk))
        if lane:
            lanes[lane] += min(n, 8)
    for t in titles:
        for lane, words in TITLE_WORDS.items():
            if lane in ("backend", "fullstack") and re.search(r"(?i)software engineer|software developer", t):
                lanes[lane] += 3
            elif re.search(rf"(?i)\b({words})\b", t):
                lanes[lane] += 6
    if lanes["frontend"] >= 4 and lanes["backend"] >= 4:
        lanes["fullstack"] += (lanes["frontend"] + lanes["backend"]) // 2
    return lanes


def group(skill_names):
    """{category: [skills]} keeping input order."""
    out = {}
    for s in skill_names:
        out.setdefault(category(s), []).append(s)
    return out


CATEGORY_LABEL = {"language": "Languages", "frontend": "Frontend", "mobile": "Mobile", "backend": "Backend & APIs",
                  "database": "Databases", "data": "Data engineering", "analytics": "Analytics", "ml": "Machine learning",
                  "ai": "AI & LLMs", "cloud": "Cloud", "devops": "DevOps", "security": "Security", "testing": "Testing",
                  "tools": "Tools", "practice": "Practices", "design": "Design", "other": "Other"}
