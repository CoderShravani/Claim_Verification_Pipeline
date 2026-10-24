# Clinical Claim Verification Mini-Pipeline

A conservative, evidence-first pipeline for checking the seven supplied SOLIQUA promotional claims against the accompanying study PDFs. It retrieves pages from the cited source, asks an LLM for a structured assessment when an API key is configured, validates the response and its evidence provenance, and returns `cannot_verify` when the evidence is missing or cannot be checked.

## Run

Requirements: Python 3.10+, the Python package in `requirements.txt`, and Tesseract OCR for image-only PDF pages. Tesseract is an optional system dependency: without it, the verifier still extracts selectable PDF text but skips pages that need OCR. An Gemini API key and network access are required for live adjudication.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export Gemini_API_KEY="your-key"  # PowerShell: $env:OPENAI_API_KEY="your-key"
python verify.py data/claims.json && python eval.py
```

. Do not store API keys in project files or commit them.

Without `OPENAI_API_KEY`, the verifier completes in fail-closed mode and emits `cannot_verify` for each claim; it does not pretend that an LLM adjudication occurred. A run replaces `outputs/predictions.json` and starts a fresh `outputs/llm_log.jsonl`. The log records request parameters/prompts and raw API responses, but never includes the API key.

## How it works

1. Extract selectable text from each PDF page.
2. If a page has no selectable text, use Tesseract OCR when it is installed.
3. Rank pages from the cited source using claim terms and send a bounded evidence packet to the model.
4. Request a strict JSON-schema response and validate every required field and type in Python.
5. Require the evidence quote to match the normalised text on the exact source file and PDF page named by the model.
6. Downgrade `supported` to `cannot_verify` unless all four required checks—figure, population, drug/indication, and explicit statement—are `match`.
7. Apply the implemented narrow Python numeric audit to eligible approximate-ratio claims. The model is instructed not to perform arithmetic.
8. On missing credentials, API/network errors, invalid output, or unverified evidence, fail closed rather than emit `supported`.

## Project files

- `data/claims.json`: the seven supplied claims.
- `data/gold.json`: manually reviewed reference labels used by `eval.py`.
- `papers/`: supplied promotional material and cited study PDFs.
- `outputs/predictions.json`: the reviewed benchmark predictions included with this package; a fresh run replaces them.
- `outputs/llm_log.jsonl`: per-run API request and response log; empty until a live API call is made.
- `tests/`: regression tests for quote matching, response validation, numeric auditing, required checks, and fail-closed behavior.
- `VALIDATION_REPORT.md`: test results and validation scope.
- `WRITEUP.md`: rationale, benchmark results, and limitations.

## Validation and limitations

The shipped predictions agree with all seven manually reviewed labels (7/7); this is benchmark agreement, not a measurement of live-model accuracy. The test suite checks the main safety gates, but no small test suite can prove that a probabilistic system will be correct on every unseen claim. OCR can misread digits, symbols, table labels, or reading order. An exact quote match verifies that the quote appears in the extracted page text; it does not, by itself, prove that the quote semantically supports the claim. Human review remains necessary for clinical or regulatory use.
