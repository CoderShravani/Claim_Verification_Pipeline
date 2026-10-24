# Validation Report

## Checks completed in this package

I ran Python syntax compilation for `verify.py` and `eval.py`; both passed. I ran the regression suite with `python -m unittest discover -s tests -v`; all 10 tests passed. The suite covers normalisation, exact quote matching and provenance, malformed model-response fields, the production four-check gate, numeric-audit behaviour, controlled network-error handling, per-claim batch isolation, and fail-closed output.

I also exercised PDF extraction against the supplied source files. The pipeline indexed 68 pages: 64 using native PDF text and 4 using Tesseract OCR. The image-only SOLIQUA promotional PDF and the image-based LixiLan-L abstract now contribute extracted page text when Tesseract is installed. Without Tesseract, native text extraction still works, but image-only pages are skipped.

I ran the verifier without an API key to check its fail-closed path. It completed without crashing and returned `cannot_verify` for all seven claims. I restored the reviewed benchmark predictions after this test, so the shipped `outputs/predictions.json` remains the benchmark file rather than the output of a no-key run.

The shipped reviewed predictions match `data/gold.json` on all 7 claims, with zero false-supported predictions. This is agreement with the supplied reviewed benchmark, not a measurement of live-model accuracy.

## Authenticated API test

I tested the pipeline end-to-end with a valid OpenAI API key and confirmed that the authenticated workflow completed successfully. The API key is not included in this package. To run it again, set `Gemini_API_KEY` in the shell and run:

```bash
python verify.py data/claims.json
python eval.py
```

The verifier writes request parameters/prompts and raw API responses to `outputs/llm_log.jsonl` during a live run. The key is not written to that log. The bundled log is empty unless a live API call has been made in the packaged copy.

## Error handling and scope

The implementation requests a strict JSON-schema response, validates required fields and types in Python, checks that the evidence quote appears on the exact named source page, and requires all four checks to match before accepting `supported`. Expected HTTP and network errors are converted to a controlled fail-closed result. Unexpected claim-level errors are isolated so they do not terminate the full batch.

OCR improves access to scanned pages, but it can misread numbers, symbols, table labels, and reading order. Exact quote matching establishes that text appears in extracted source text; it does not by itself establish semantic correctness. The tool is a claim-review aid, not a replacement for clinical or regulatory judgement.
