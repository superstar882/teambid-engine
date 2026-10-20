"""Writing checker for application text: cover letters, answers, recruiter replies, bullets.

Flags AI tells and hard-to-read text. Rules come from published research:
Kobak et al. 2025 and Juzek & Ward 2024 (excess AI vocabulary), Reinhart et al. PNAS 2025 (participle clauses 2-5x,
nominalizations 1.5-2x the human rate), Munoz-Ortiz 2024 (LLM sentence lengths cluster at 10-30 tokens),
GOV.UK style guide (split sentences over 25 words), Flesch reading ease (aim 60+, grade about 8).
"""
import re
import statistics

BANNED = set("""delve delves delving underscore underscores underscoring showcase showcases showcasing garner garnered boasts
realm groundbreaking advancements aligns surpassing emphasizing commendable meticulous meticulously intricate intricacies
camaraderie tapestry amidst palpable testament multifaceted nuanced pivotal transformative unwavering profound renowned
leverage leveraging leveraged utilize utilizing utilized facilitate facilitated commence endeavor spearheaded orchestrated
robust seamless seamlessly comprehensive innovative cutting-edge crucial vital foster fostering empower empowering
elevate navigate navigating streamline streamlined enhance enhanced honed proficient passionate furthermore moreover
additionally ultimately thrilled synergy holistic paradigm harness unlock bolster resonate resonates embark myriad plethora
adept tech-savvy results-driven detail-oriented self-starter go-getter""".split())

PHRASES = ["i am writing to express", "excited to apply", "thrilled to", "eager to apply", "highly motivated", "a passion for",
           "when it comes to", "fast-paced", "resonates with me", "allowed me to", "taught me the importance", "great fit",
           "perfect fit", "not only", "it's not just", "worth noting", "important to note", "overall,", "in summary",
           "in conclusion", "opportunity to contribute", "thank you for considering", "look forward to hearing", "feel free to",
           "proven track record", "team player", "in order to", "due to the fact", "a wide range of", "diverse array",
           "serves as", "stands as", "i believe i", "i think i could", "hopefully", "could potentially", "in today's",
           "ever-evolving", "rapidly evolving", "responsible for", "helped with", "worked on various"]

PLAIN = {"utilize": "use", "leverage": "use", "facilitate": "help", "commence": "start", "endeavor": "try", "approximately": "about",
         "demonstrate": "show", "in order to": "to", "prior to": "before", "subsequently": "then", "assist": "help",
         "implement": "build", "spearheaded": "led", "orchestrated": "ran", "streamlined": "simplified", "enhanced": "improved",
         "robust": "solid", "seamless": "smooth", "comprehensive": "full", "innovative": "new", "proficient": "skilled"}

WEAK_STARTS = re.compile(r"(?i)^(responsible for|helped|assisted|worked on|involved in|participated in|tasked with|duties included)")
STRONG_VERBS = set("""built shipped cut led designed migrated automated scaled launched owned created reduced increased improved wrote
developed delivered drove grew saved deployed architected refactored optimized implemented integrated analyzed trained mentored
founded negotiated resolved accelerated rebuilt replaced redesigned streamlined consolidated introduced established managed""".split())


def syllables(word):
    w = word.lower().strip("'")
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def stats(text):
    words = re.findall(r"[a-zA-Z][a-zA-Z'-]*", text)
    sents = [s for s in re.split(r"(?<=[.?!])\s+|\n+", text) if re.search(r"[A-Za-z]", s)]
    lens = [len(re.findall(r"[A-Za-z0-9$%][\w$%,.'-]*", s)) for s in sents]
    nw, ns = max(1, len(words)), max(1, len(sents))
    syl = sum(syllables(w) for w in words)
    return {"chars": len(text), "words": len(words), "sentences": len(sents), "avg_sentence": round(nw / ns, 1),
            "reading_ease": round(206.835 - 1.015 * (nw / ns) - 84.6 * (syl / nw)),
            "grade": round(0.39 * (nw / ns) + 11.8 * (syl / nw) - 15.59, 1), "lens": lens, "sents": sents, "words_list": words}


def check(text, limit=None, kind="prose"):
    """-> {"stats": {...}, "fails": [...], "warnings": [...], "ok": bool}. kind: prose | bullet."""
    text = (text or "").strip()
    st = stats(text)
    low = text.lower()
    fails, warn = [], []
    if limit and len(text) > limit:
        fails.append(f"Over the limit by {len(text) - limit} characters")
    for w in sorted(BANNED):
        if re.search(rf"\b{re.escape(w)}\b", low):
            warn.append(f"AI-style word: '{w}'" + (f" (try '{PLAIN[w]}')" if w in PLAIN else ""))
    for p in PHRASES:
        if p in low:
            warn.append(f"Stock phrase: '{p}'" + (f" (try '{PLAIN[p]}')" if p in PLAIN else ""))
    for ch, name in [("—", "em dash"), ("–", "en dash"), (";", "semicolon"), ("**", "bold markers"), ("!", "exclamation mark")]:
        if ch in text and not (kind == "bullet" and ch == "–"):
            warn.append(f"Contains {name}")
    if kind == "prose":
        part = re.findall(r",\s+(?:\w+ly\s+)?\w+ing\b", text)
        if len(part) > 1:
            warn.append(f"{len(part)} ', ...ing' clauses (an AI pattern; keep at most 1)")
        noms = [w for w in st["words_list"] if len(w) > 6 and re.search(r"(tion|tions|ment|ments|ance|ence|sion|ization)$", w.lower())]
        if st["sentences"] >= 2 and len(noms) / st["sentences"] > 1.0:
            warn.append(f"Heavy on -tion/-ment nouns ({', '.join(noms[:4])}). Use verbs")
        for s, n in zip(st["sents"], st["lens"]):
            if n > 25:
                warn.append(f"Long sentence ({n} words), split it: {s[:60]}...")
        if len(st["lens"]) >= 4 and min(st["lens"]) >= 8:
            warn.append("No short sentence (under 8 words). Mix short and long")
        if len(st["lens"]) >= 5 and statistics.pstdev(st["lens"]) < 5:
            warn.append("Sentence lengths are too even. Mix short and long")
        if st["words"] >= 40 and (st["reading_ease"] < 45 or st["grade"] > 12):
            warn.append(f"Hard to read (reading ease {st['reading_ease']}, grade {st['grade']}). Shorter sentences and words")
        if re.match(r"(furthermore|moreover|additionally|however|ultimately)\b", low):
            warn.append("Opens with a stiff transition")
    else:
        if WEAK_STARTS.match(text):
            warn.append("Weak opening ('responsible for', 'helped'...). Start with a strong past-tense verb")
        if len(text) > 220:
            warn.append("Bullet over 2 lines (~220 characters)")
        if re.match(r"(?i)^(i|my|we)\b", text):
            warn.append("Drop pronouns in bullets")
    st.pop("sents"), st.pop("words_list"), st.pop("lens")
    return {"stats": st, "fails": fails, "warnings": warn, "ok": not fails and not warn}


def format_report(res):
    s = res["stats"]
    head = (f"{s['chars']} chars, {s['words']} words, {s['sentences']} sentences, reading ease {s['reading_ease']}, "
            f"grade {s['grade']}")
    lines = [head] + [f"FAIL: {f}" for f in res["fails"]] + [f"WARNING: {w}" for w in res["warnings"]]
    return "\n".join(lines if len(lines) > 1 else lines + ["OK: no flags"])


RULES_MD = """# Writing rules (shared by the team)

Short, true, human. The two failure modes to beat are **too long** and **AI-sounding words**.

1. Answer in the first sentence. Then add only what helps.
2. One concrete detail beats three adjectives: a number, a product name, a link.
3. Say something the resume doesn't. Never restate it.
4. Name the company and one real reason that only fits them.
5. Mix short sentences (under 8 words) with longer ones. Nothing over 25 words.
6. Verbs, not -tion/-ment nouns: "I built", not "the implementation of".
7. At most one ", ...ing" clause per answer.
8. No em dashes, semicolons, exclamation marks or bold.
9. Plain words: use (not utilize), help (not facilitate), start (not commence), about (not approximately).
10. Never claim what you didn't do. No invented numbers, no tools you didn't use in that job.

Banned words (they mark text as AI-written): """ + ", ".join(sorted(BANNED)) + """

Run any draft through the checker (UI: Writing checker, CLI: `python tb.py check file.txt`) and fix every warning.
"""
