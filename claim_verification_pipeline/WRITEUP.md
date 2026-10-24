# Claim Verification Mini-Pipeline — Technical Write-up

## Approach

I treated the cited study—not the promotional wording—as the evidence source. The pipeline extracts text page by page, falls back to Tesseract OCR for image-only pages when available, and ranks likely evidence pages using the claim's terms. It sends a bounded evidence packet to the model and requests a strict JSON-schema response. Python validates the response structure, requires a verbatim evidence quotation on the exact named source page, and downgrades any `supported` result unless all four checks—figure, population, drug/indication, and explicit statement—are `match`.

The model is instructed not to calculate. A narrow Python audit handles eligible approximate-ratio claims; ambiguous arithmetic is not inferred. Missing credentials, network failures, invalid model output, or evidence that cannot be matched result in `cannot_verify` rather than a fabricated supported verdict.

## Findings from the supplied claims

The reviewed reference set labels C3 as `overstated`: LixiLan-O reports HbA1c reductions of −1.6% with iGlarLixi and −1.3% with insulin glargine, which does not substantiate “~2×.” C5 is `overstated` because the LixiLan-L abstract reports a mean 0.7 kg decrease with iGlarLixi, not literal weight neutrality. C7 is `overstated` because the propensity-score-matched panel compares iGlarLixi with a basal-bolus group drawn from a different trial; that is not the same comparator or design as the randomized basal-insulin and premix panels. C1 remains `cannot_verify` because the supplied source packet does not provide a readable copy of the exact prescribing-information source needed to verify the indication wording.

## Benchmark result

The shipped reviewed predictions were evaluated against `data/gold.json`:

```text
Accuracy: 7/7 = 1.000
Confusion matrix (rows=gold, columns=prediction)
gold\pred          supported      overstated  cannot_verify
supported                  3               0              0
overstated                 0               3              0
cannot_verify              0               0              1
False supported verdicts: 0
Per-claim:
  C1: gold=cannot_verify, predicted=cannot_verify, OK
  C2: gold=supported, predicted=supported, OK
  C3: gold=overstated, predicted=overstated, OK
  C4: gold=supported, predicted=supported, OK
  C5: gold=overstated, predicted=overstated, OK
  C6: gold=supported, predicted=supported, OK
  C7: gold=overstated, predicted=overstated, OK
```

This score measures agreement with the seven reviewed reference labels. It is not live-model accuracy and does not establish performance on unseen claims. I also tested the authenticated workflow with a valid API key and confirmed that it completed successfully. The key is not included in this submission.

## Risk controls and limitations

PDF tables can separate values from row labels, and OCR can misread numbers, symbols, or reading order. A verified quote establishes that text appears on the named extracted page; it does not alone prove semantic support. I cross-checked C4's proportions and odds ratio against the same endpoint and checked C6's level-2 definition (<54 mg/dL) separately from its reported odds ratio and confidence interval. I also added regression tests for the production supported-check gate, malformed response fields, exact quote provenance, and network failure handling.

The verifier is designed to abstain when the available evidence is insufficient. I would evaluate any future table-aware extraction improvements on a held-out claim set and report false-supported rate, quote-verification rate, and abstention rate separately.
