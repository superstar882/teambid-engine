# System design interviews

Group: Interviews · Related vault file: `Job/Interview Prep/Prep Plan.md` · 3 sources, 7 findings

## Findings (strongest sources first)

- Junior candidates are expected to take interviewer guidance; senior candidates should proactively find problems and lead. (Hello Interview, n.d.; medium)
  - Takeaway: At early-career level, being coachable and responsive to hints is scored.
- A common delivery order is requirements, core entities, API, optional data flow, high-level design, then deep dives. **~5 min requirements, ~2 min entities, ~5 min API, 10-15 min high-level design, ~10 min deep dives** (Hello Interview, n.d.; medium)
  - Takeaway: Practice hitting a working high-level design within ~30 minutes before going deep.
- New grads are expected to present a simple end-to-end flow with basic components used correctly, not an over-engineered design. **"client -> API -> service -> database"** (AlgoMaster.io, 2026-05-31; medium)
  - Takeaway: Start simple and justify additions; don't name-drop Kafka unless the requirements need it.
- Strong RAG design answers clarify corpus size, citations, permissions, freshness and latency before drawing the pipeline. (Mockingly.ai, 2026-09-08; medium)
- Common pitfalls are post-filtering permissions after retrieval, pure vector search without hybrid/BM25, and weak chunking. (Mockingly.ai, 2026-09-08; medium)
- Evaluate retrieval and generation separately: recall@k and nDCG/MRR for retrieval, faithfulness and correctness for answers. (Mockingly.ai, 2026-09-08; medium)
  - Takeaway: Having an eval story is a gap to close; know the metrics by name.
- Mid-level candidates must estimate capacity, cover main read and write paths, and give trade-off reasoning for at least one deep-dived component. (AlgoMaster.io, 2026-05-31; medium)

## Sources

| Credibility | Source | Type | Date |
|---|---|---|---|
| ★★★☆☆ | [System Design Delivery Framework](https://www.hellointerview.com/learn/system-design/in-a-hurry/delivery) | expert_guide |  |
| ★★☆☆☆ | [RAG System Design Interview Guide](https://www.mockingly.ai/blog/rag-system-design-interview) | vendor_blog | 2026-09-08 |
| ★★☆☆☆ | [Expectations by Level/YoE](https://algomaster.io/learn/system-design-interviews/expectations-by-level) | expert_guide | 2026-05-31 |
