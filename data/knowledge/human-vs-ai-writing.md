# Human vs AI writing (measurable)

Group: Writing · Related vault file: `Job/Writing/01-ai-mistakes.md` · 9 sources, 27 findings

## Findings (strongest sources first)

- Some words are massively overrepresented in instruction-tuned model output. **camaraderie 162x (GPT-4o), tapestry 155x, intricate 119x, palpable 95x, amidst 100x; tapestry in 23% and amidst in 27% of GPT-4o outputs** (PNAS (open preprint at arxiv.org/html/2410.16107), 2025-02-18; high)
  - Takeaway: Hard-ban tapestry, intricate, palpable, amidst, camaraderie.
- LLM excess words are mostly style verbs and adjectives, unlike past vocabulary shifts that were content nouns. **Of 379 excess style words in 2024, 66% were verbs and 14% adjectives; earlier excess words were 79.2% nouns** (Science Advances (PMC copy); preprint arXiv:2406.07016, 2025-07-02; high)
  - Takeaway: Checker should scan fancy verbs/adjectives, not nouns. Concrete nouns (tool names, numbers) read human.
- Human sentence lengths are more scattered; LLM sentences cluster in a middle band. **Models produce sentences in the 10 to 30 token range more often than humans; humans produce long (and varied) sentences more often** (Artificial Intelligence Review 57:265, 2024-08; high)
  - Takeaway: Mix very short sentences (under 8 words) with longer ones; avoid every sentence landing at 12-25 words.
- Differences between LLMs and humans are larger than differences between LLMs. (Artificial Intelligence Review 57:265, 2024-08; high)
- Instruction-tuned LLMs use present participial clauses (', leaning on...', ', ensuring...') far more than humans. **2 to 5 times the human rate; GPT-4o 5.3x (Cohen's d = 1.38)** (PNAS (open preprint at arxiv.org/html/2410.16107), 2025-02-18; high)
  - Takeaway: Flag sentences with a comma followed by an -ing clause; allow at most one per answer.
- After ChatGPT, rare style words jumped far above their expected frequency in 15.1M PubMed abstracts. **delves r = 28.0; underscores r = 13.8; showcasing r = 10.7** (Science Advances (PMC copy); preprint arXiv:2406.07016, 2025-07-02; high)
  - Takeaway: Flag delve(s), underscore(s), showcasing as near-certain AI tells; never use them.
- Human text has more vocabulary variety and shorter constituents than LLM text. (Artificial Intelligence Review 57:265, 2024-08; high)
  - Takeaway: Don't repeat the same safe words; use specific, concrete terms.
- LLM text shows less negative emotion and more joy, and more numbers, symbols, auxiliaries and pronouns; fewer adjectives (in news). (Artificial Intelligence Review 57:265, 2024-08; high)
  - Takeaway: Upbeat, uniformly positive tone reads machine-made; plain, matter-of-fact tone is safer.
- Common words also rose sharply in absolute frequency after LLMs arrived. **potential delta = 0.052; findings delta = 0.041; crucial delta = 0.037** (Science Advances (PMC copy); preprint arXiv:2406.07016, 2025-07-02; high)
  - Takeaway: Treat 'crucial' and 'potential' as soft tells; cap at zero or one per answer.
- An estimated 6.5% to 16.9% of review text was substantially LLM-modified, more so near deadlines and in low-confidence reviews. **6.5%-16.9%** (ICML 2024 (PMLR 235), 2024; high)
- A classifier on these grammatical features separates LLM text from human text well. **LLM misclassified as human only 4.2%; individual LLM identified with 93-98% accuracy** (PNAS (open preprint at arxiv.org/html/2410.16107), 2025-02-18; high)
  - Takeaway: Grammar style, not just vocabulary, gives AI text away; vary structure.
- Certain adjectives spiked in ICLR 2024 peer reviews after ChatGPT. **commendable 9.8x, meticulous 34.7x, intricate 11.2x increase in probability of appearing in a sentence** (ICML 2024 (PMLR 235), 2024; high)
  - Takeaway: Hard-ban commendable, meticulous, intricate.
- The paper lists the top adjectives and adverbs disproportionately used by AI. **Top adjectives start: commendable, innovative, meticulous, intricate, notable, versatile, noteworthy, invaluable, pivotal, potent; top adverbs start: meticulously, reportedly, lucidly, innovatively, aptly, methodically, excellently, compellingly, impressively, undoubtedly** (ICML 2024 (PMLR 235), 2024; high)
  - Takeaway: Use these lists as a word blacklist in the checker.
- LLMs overuse nominalizations, 'that' clauses as subjects and phrasal coordination, and underuse agentless passives. **Nominalizations 1.5-2x (GPT-4o 2.1x, d = 1.23); that-clause subjects GPT-4o 2.6x; phrasal coordination GPT-4o 1.9x; agentless passive about half the human rate** (PNAS (open preprint at arxiv.org/html/2410.16107), 2025-02-18; high)
  - Takeaway: Prefer verbs over -tion/-ment nouns and avoid 'X and Y' noun pairs stacked in lists.
- At least 13.5% of 2024 biomedical abstracts were processed with LLMs, up to 40% in some subcorpora. **at least 13.5%; up to 40%** (Science Advances (PMC copy); preprint arXiv:2406.07016, 2025-07-02; high)
  - Takeaway: Readers are now primed to spot these words, so avoiding them matters more each year.
- Training on AI feedback with this bias can make models produce needlessly long responses. (arXiv, 2023-10; high)
  - Takeaway: Set a hard length cap for each answer type and enforce it.
- They identified 21 focal words whose use spiked in scientific abstracts 2020-2024. **delve, intricate, underscore, emphasizing, surpassing, showcasing, garnered, groundbreaking, advancements, boasts, comprehending, aligns, realm (and variants)** (arXiv, 2024-12-16; high)
  - Takeaway: Add these to the banned list.
- Frequency jumps for top words were huge. **'delves' +6,697% (0.21 to 14.38 per million); 'intricate' +611% (6.22 to 44.22 per million)** (arXiv, 2024-12-16; high)
  - Takeaway: Even one 'delve' is a strong signal; zero tolerance.
- GPT-4 as a judge prefers longer answers more than humans do, even at similar quality. **Tested on 100 sample answers each to 3 prompts (Vicuna-7b-v1.5, temperature 0.7)** (arXiv, 2023-10; high)
  - Takeaway: AI drafts drift long because models think long is better; humans don't. Cut hard.
- RLHF is the likely cause: human raters seem to have rewarded these words as signs of quality. (arXiv, 2024-12-16; medium)
  - Takeaway: Fancy words that 'sound smart' are exactly what reads as AI now.
- Across 76 chatbot LLMs on 304 brevity-ideal prompts, median excess length (characters beyond a minimal answer) varied by an order of magnitude. **Best YapIndex: gpt-3.5-turbo 22.7 median excess characters; order-of-magnitude spread across models** (arXiv (tabularis.ai), 2026-01-02; high)
  - Takeaway: Write the minimal sufficient answer first, then add only what changes the reader's decision.
- Typical LLM padding is vacuum-filling on vague prompts and explanation/formatting overhead on simple requests. (arXiv (tabularis.ai), 2026-01-02; high)
  - Takeaway: Delete setup sentences, restated questions and explanations the reader didn't ask for.
- Verbosity is trending mildly up with model release date. **r = 0.21 (n = 57 models)** (arXiv (tabularis.ai), 2026-01-02; medium)
  - Takeaway: Newer models need more trimming, not less.
- When told to avoid markdown, models drop headers and bullets but keep em dashes, so em dashes survive as a leftover formatting habit. **GPT-4.1 still 9.10 per 1,000 words when suppressed; Claude Opus 4.6 fell to 0.19** (arXiv, 2026-03; medium)
  - Takeaway: Explicitly strip em dashes after drafting; asking the model not to use them may not be enough.
- Some models use em dashes about 3x more than a human baseline. **GPT-4.1 10.62 per 1,000 words vs human mean 3.23 per 1,000 (human range 0.33-17.12); Claude Opus 4.6 9.09 unconstrained; Llama 3.x 0.00** (arXiv, 2026-03; medium)
  - Takeaway: Zero em dashes in short answers; anything above ~3 per 1,000 words is suspicious.
- Burstiness (sentence-length variance) is higher in human prose than in default LLM output. **Human prose SD of about 8-14 words around the mean; default Claude Sonnet 4.5, GPT-5 and Gemini 2.5 Pro about 3-5 words SD (seen only in a search excerpt; method unknown)** (AutomationLabs (Substack), n.d.; low)
  - Takeaway: Checker can warn if sentence-length SD is under ~5 words in answers with 5+ sentences.
- Low perplexity (predictable text) and uniform sentences are what early GPTZero flagged; GPTZero reportedly moved to a deep-learning classifier in autumn 2023. (AutomationLabs (Substack), n.d.; low)
  - Takeaway: Predictable phrasing reads as AI even with clean vocabulary; use specific, personal details.

## Sources

| Credibility | Source | Type | Date |
|---|---|---|---|
| ★★★★★ | [Delving into LLM-assisted writing in biomedical publications through excess vocabulary](https://pmc.ncbi.nlm.nih.gov/articles/PMC12219543/) | research | 2025-07-02 |
| ★★★★★ | [Do LLMs write like humans? Variation in grammatical and rhetorical styles](https://www.pnas.org/doi/10.1073/pnas.2422455122) | research | 2025-02-18 |
| ★★★★★ | [Contrasting Linguistic Patterns in Human and LLM-Generated News Text](https://arxiv.org/pdf/2308.09067) | research | 2024-08 |
| ★★★★★ | [Monitoring AI-Modified Content at Scale: A Case Study on the Impact of ChatGPT on AI Conference Peer Reviews](https://arxiv.org/abs/2403.07183) | research | 2024 |
| ★★★★☆ | [Why Does ChatGPT "Delve" So Much? Exploring the Sources of Lexical Overrepresentation in Large Language Models](https://arxiv.org/html/2412.11385v1) | research | 2024-12-16 |
| ★★★★☆ | [Verbosity Bias in Preference Labeling by Large Language Models](https://arxiv.org/abs/2310.10076) | research | 2023-10 |
| ★★★☆☆ | [The Last Fingerprint: How Markdown Training Shapes LLM Prose](https://arxiv.org/html/2603.27006v1) | research | 2026-03 |
| ★★★☆☆ | [Do Chatbot LLMs Talk Too Much? The YapBench Benchmark](https://arxiv.org/pdf/2601.00624) | research | 2026-01-02 |
| ★★☆☆☆ | [GPTZero is reading your sentence rhythm](https://automationlabs.substack.com/p/gptzero-is-reading-your-sentence) | community |  |
