# Clinical Claim Verification Pipeline

An evidence-based clinical claim verification pipeline that evaluates pharmaceutical promotional claims against source study documents. The system assesses claims for factual support, identifies overstated conclusions, checks population and drug-indication alignment, and extracts supporting evidence with page-level references.

Built with Python and LLM-based verification, the project generates structured verdicts, evidence spans, reasoning, and computed checks in JSON format. It also maintains JSONL logs for traceability and reproducibility.

**Key features**
- Automated verification of pharmaceutical claims
- Verdict classification: `supported`, `overstated`, and `cannot_verify`
- Evidence extraction with source file and page references
- Validation of figures, populations, drug indications, and stated findings
- Numerical checks to identify discrepancies between promotional claims and source data
- Structured JSON predictions and JSONL logging

**Tech stack:** Python, Large Language Models (LLMs), JSON, JSONL, clinical research documents

**Use case:** Clinical evidence validation, pharmaceutical claim auditing, and research-backed promotional content review.
