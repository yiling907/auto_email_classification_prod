# Accuracy Metrics by Task Type

| Task Type | Metric | Definition | Threshold | Unit |
|---|---|---|---|---|
| **Intent Classification** | Accuracy | Accuracy of 17-intent classification | ≥ 0.80 | 0–1 |
| | Macro F1 | Average F1 across 17 intents | — | 0–1 |
| | Precision/Recall/F1 (per intent) | Per-intent precision/recall/F1 | — | 0–1 |
| | Routing Accuracy | Routing accuracy across 12 teams | — | 0–1 |
| | Latency | Average response time | — | ms |
| **RAG Retrieval** | Hit Rate | % emails with ≥1 relevant doc retrieved | ≥ 0.60 | 0–1 |
| | Empty Retrieval Rate | % emails with no relevant docs | — | 0–1 |
| | Avg Docs Retrieved | Average # of documents per query | — | count |
| | Avg Doc Precision | % of retrieved docs matching gold labels | — | 0–1 |
| | Per-Intent Hit Rate | Hit rate breakdown by intent | — | 0–1 |
| **Response Generation** | Avg LLM Judge Score | LLM quality score (relevance, accuracy, completeness, professionalism) | — | 0–1 |
| | Escalation Agreement | % human-review emails correctly flagged | ≥ 0.70 | 0–1 |
| | Hedge Rate | % responses with polite/cautious phrases | — | 0–1 |
| | Response Coverage Rate | % emails with generated responses | — | 0–1 |
| | Per-Intent Judge Score | Average judge score by intent | — | 0–1 |
| **Claim Form Extraction** | String Field F1 (26 fields) | Precision/Recall/F1 per string field | — | 0–1 |
| | Bool Field F1 (3 fields) | Precision/Recall/F1 per boolean field | — | 0–1 |
| | Numeric Accuracy (2 fields) | % within ±5% tolerance + MAE | — | 0–1 / $ |
| | Receipts F1 | Row-level treatment matching + cost accuracy | — | 0–1 |
| | Dependants F1 | Dependant name matching | — | 0–1 |
| | Overall Score | Weighted score (30% identity + 20% payment + 20% receipts + 20% specialist + 10% dependants) | — | 0–1 |
| **End-to-End Pipeline** | Composite Score | Weighted average of all components | ≥ 0.70 | 0–1 |
| | Intent Accuracy | 17-intent classification accuracy | — | 0–1 |
| | Routing Accuracy | Routing accuracy | — | 0–1 |
| | Confidence Calibration | Quality of confidence scores | — | 0–1 |
| | Response Quality | LLM judge score | — | 0–1 |
| | Escalation Routing | % human-review emails correctly identified | — | 0–1 |
| | Success Rate | % executions completed without error | — | 0–1 |
| | Avg Latency | Average execution time per email | — | ms |
