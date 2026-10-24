#!/usr/bin/env python3
"""Conservative claim verifier for supplied clinical-study PDFs.

With GEMINI_API_KEY set, uses a JSON-only evidence-labeling call and validates the
returned schema and quotation against extracted source text. Without a key, it
fails closed: every claim is cannot_verify. Arithmetic is intentionally performed
only in Python; the model is explicitly forbidden from calculating.
"""
from __future__ import annotations
import argparse, json, os, re, sys, urllib.request, urllib.error, subprocess, tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')
VALID_VERDICTS = {'supported', 'overstated', 'cannot_verify'}
VALID_CHECKS = {'match', 'mismatch', 'unclear'}


def norm(s: str) -> str:
    s = s.lower().replace('âˆ’', '-').replace('â€“', '-').replace('â€”', '-')
    s = re.sub(r'\s+', ' ', s)
    return re.sub(r'[^a-z0-9%<>=.+/-]+', ' ', s).strip()


def extract_page_text(page: Any, *, ocr_dpi: int = 160, ocr_timeout: int = 15) -> tuple[str, str]:
    """Extract selectable PDF text first, then OCR image-only pages with Tesseract."""
    native = page.get_text("text").strip()
    if native:
        return native, "native"
    if not shutil_which("tesseract"):
        return "", "unavailable"
    try:
        pix = page.get_pixmap(dpi=ocr_dpi, alpha=False)
        with tempfile.TemporaryDirectory(prefix="claim_ocr_") as tmp:
            image_path = Path(tmp) / "page.png"
            pix.save(str(image_path))
            proc = subprocess.run(
                ["tesseract", str(image_path), "stdout", "--psm", "6"],
                capture_output=True, text=True, timeout=ocr_timeout, check=False
            )
            if proc.returncode != 0:
                return "", "failed"
            text = proc.stdout.strip()
            if len(re.sub(r"[^A-Za-z0-9]", "", text)) < 20:
                return "", "empty_ocr"
            return text, "ocr"
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return "", "failed"


def shutil_which(command: str) -> str | None:
    import shutil
    return shutil.which(command)


def load_pdfs(root: Path) -> list[dict[str, Any]]:
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError("PDF extraction dependency missing. Run: pip install -r requirements.txt") from e
    records = []
    for pdf in sorted((root / "papers").glob("*.pdf")):
        try:
            with fitz.open(pdf) as doc:
                for idx, page in enumerate(doc):
                    text, method = extract_page_text(page)
                    if text:
                        records.append({
                            "file": pdf.name, "path": str(pdf.relative_to(root)),
                            "page": idx + 1, "text": text, "extraction": method
                        })
        except Exception as e:
            print(f"WARNING: could not process {pdf.name}: {e}", file=sys.stderr)
    return records


def source_for_claim(claim: dict[str, Any], pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cited = str(claim.get('cited_paper', '')).lower()
    # Resolve both the assignment's canonical names and a renamed/relative path.
    aliases = {
        'solimix': ('solimix',), 'rosenstock2021': ('solimix',),
        'lixilan-o': ('lixilan-o',), 'rosenstock2016': ('lixilan-o',),
        'tabak': ('tabak',), 'psm': ('tabak',),
        'lixilan-l': ('lixilan-l', 'soliqua_lbl'), 'aro da': ('lixilan-l',),
        'soliqua_lbl': ('soliqua_lbl',), 'prescribing': ('soliqua_lbl',),
    }
    selected = []
    for key, terms in aliases.items():
        if key in cited:
            selected = [p for p in pages if any(t in p['file'].lower() for t in terms)]
            if selected:
                break
    if not selected:
        # A path may be supplied directly in the claim JSON.
        base = Path(cited).name
        selected = [p for p in pages if p['file'].lower() == base]
    return selected


def candidate_pages(claim: dict[str, Any], pages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    source_pages = source_for_claim(claim, pages)
    if not source_pages:
        source_pages = pages
    terms = set(re.findall(r'[a-zA-Z]{3,}|\d+(?:\.\d+)?%?', ' '.join(str(claim.get(k, '')) for k in ('text','population','molecule')) .lower()))
    scored = []
    for p in source_pages:
        body = p['text'].lower()
        score = sum(1 for term in terms if term in body)
        scored.append((score, p))
    return [p for _, p in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]


def log_call(log_path: Path, request_obj: dict[str, Any], raw: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'request': request_obj, 'raw_response': raw}, ensure_ascii=False) + '\n')


def call_gemini(claim: dict[str, Any], candidates: list[dict[str, Any]], log_path: Path) -> dict[str, Any]:
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY is not set')
    # Keep the evidence packet bounded, but preserve page/source labels.
    evidence_packet = '\n\n'.join(
        f"SOURCE={p['file']} | PAGE={p['page']}\n{p['text'][:7000]}" for p in candidates
    )
    schema = {
        'type': 'OBJECT',
        'properties': {
            'verdict': {'type': 'STRING', 'enum': ['supported', 'overstated', 'cannot_verify']},
            'checks': {'type': 'OBJECT', 'properties': {
                'figure': {'type': 'STRING', 'enum': ['match', 'mismatch', 'unclear']},
                'population': {'type': 'STRING', 'enum': ['match', 'mismatch', 'unclear']},
                'drug_indication': {'type': 'STRING', 'enum': ['match', 'mismatch', 'unclear']},
                'actually_stated': {'type': 'STRING', 'enum': ['match', 'mismatch', 'unclear']},
            }, 'required': ['figure', 'population', 'drug_indication', 'actually_stated']},
            'evidence_file': {'type': 'STRING', 'nullable': True},
            'evidence_page': {'type': 'INTEGER', 'nullable': True},
            'evidence_span': {'type': 'STRING', 'nullable': True},
            'reason': {'type': 'STRING'},
            'source_numbers': {'type': 'ARRAY', 'items': {'type': 'NUMBER'}},
        },
        'required': ['verdict', 'checks', 'evidence_file', 'evidence_page',
                     'evidence_span', 'reason', 'source_numbers']
    }
    prompt = (
        'You are a conservative evidence reviewer for a pharma claim. Use only the supplied pages. '
        'A claim is supported only if the source explicitly states it and figure, population, drug/indication, '
        'and time point all match. If evidence is absent, ambiguous, or not parseable, use cannot_verify. '
        'Use overstated only when the source clearly contradicts or narrows the claim. Quote one exact, verbatim '
        'source span and return its source filename and printed PDF page number. Do not invent evidence. '
        'Do NOT calculate, add, subtract, divide, compute percentages, ratios, confidence intervals, or derive '
        'any numbers. Only copy numeric values explicitly present in the source into source_numbers. '
        'If the claim needs arithmetic to assess, say so in reason and use cannot_verify. '
        'Return only JSON conforming to the supplied schema.\n\n'
        f'CLAIM JSON:\n{json.dumps(claim, ensure_ascii=False)}\n\nSOURCE EXCERPTS:\n{evidence_packet}'
    )
    request_obj = {
        'model': MODEL,
        'generationConfig': {
            'temperature': 0,
            'responseMimeType': 'application/json',
            'responseSchema': schema
        },
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}]
    }
    url = (
        'https://generativelanguage.googleapis.com/v1beta/models/'
        f'{MODEL}:generateContent?key={api_key}'
    )
    req = urllib.request.Request(
        url, data=json.dumps(request_obj).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST'
    )
    # Never log the API key or the keyed URL.
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw_api = response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        log_call(log_path, request_obj, json.dumps({'http_error': e.code, 'body': detail}))
        raise RuntimeError(f'Gemini API returned HTTP {e.code}; see outputs/llm_log.jsonl') from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        log_call(log_path, request_obj, json.dumps({
            'network_error': type(e).__name__, 'message': str(e)
        }))
        raise RuntimeError(
            f'Gemini API connection failed ({type(e).__name__}); claim was not adjudicated'
        ) from e
    log_call(log_path, request_obj, raw_api)
    outer = json.loads(raw_api)
    raw_content = outer['candidates'][0]['content']['parts'][0]['text']
    result = json.loads(raw_content)
    validate_model_result(result)
    return result


def validate_model_result(result: Any) -> None:
    """Validate every field the verifier consumes before trusting model output."""
    if not isinstance(result, dict):
        raise ValueError("Model response must be a JSON object")
    required = {"verdict", "checks", "evidence_file", "evidence_page",
                "evidence_span", "reason", "source_numbers"}
    if set(result) != required:
        raise ValueError("Model response has missing or unexpected fields")
    if result["verdict"] not in VALID_VERDICTS:
        raise ValueError("Invalid verdict in model response")
    checks = result["checks"]
    check_keys = {"figure", "population", "drug_indication", "actually_stated"}
    if not isinstance(checks, dict) or set(checks) != check_keys:
        raise ValueError("Checks must contain exactly the four required fields")
    if any(value not in VALID_CHECKS for value in checks.values()):
        raise ValueError("Each check must be match, mismatch, or unclear")
    if result["evidence_file"] is not None and not isinstance(result["evidence_file"], str):
        raise ValueError("evidence_file must be a string or null")
    if result["evidence_page"] is not None and (
        isinstance(result["evidence_page"], bool) or not isinstance(result["evidence_page"], int)
        or result["evidence_page"] < 1
    ):
        raise ValueError("evidence_page must be a positive integer or null")
    if result["evidence_span"] is not None and not isinstance(result["evidence_span"], str):
        raise ValueError("evidence_span must be a string or null")
    if not isinstance(result["reason"], str) or not result["reason"].strip():
        raise ValueError("reason must be a non-empty string")
    if not isinstance(result["source_numbers"], list) or any(
        isinstance(n, bool) or not isinstance(n, (int, float)) for n in result["source_numbers"]
    ):
        raise ValueError("source_numbers must be a list of numbers")


def validate_quote(result: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[bool, dict[str, Any] | None]:
    span = result.get("evidence_span")
    evidence_file = result.get("evidence_file")
    evidence_page = result.get("evidence_page")
    # Require explicit provenance; a quote alone is not enough to establish where it came from.
    if not isinstance(span, str) or not span.strip():
        return False, None
    if not isinstance(evidence_file, str) or not evidence_file.strip():
        return False, None
    if isinstance(evidence_page, bool) or not isinstance(evidence_page, int) or evidence_page < 1:
        return False, None
    target = norm(span)
    for p in candidates:
        if p["file"] != evidence_file or p["page"] != evidence_page:
            continue
        source = norm(p["text"])
        # Normalized exact substring is deliberately stricter than semantic similarity.
        if target and target in source:
            return True, p
    return False, None


def fail_closed(claim: dict[str, Any], reason: str) -> dict[str, Any]:
    return {'claim_id':claim.get('claim_id'), 'verdict':'cannot_verify',
        'checks':{'figure':'unclear','population':'unclear','drug_indication':'unclear','actually_stated':'unclear'},
        'evidence_file':None,'evidence_page':None,'evidence_span':None,'computed':None,
        'reason':reason}


def python_numeric_audit(claim_text: str, evidence_span: str) -> dict[str, Any] | None:
    """Compute simple explicitly signalled treatment ratios in Python, never in the LLM.

    This intentionally supports only a transparent, narrow pattern: a claim stating
    an approximate N-times reduction, with a source sentence listing the intervention
    and comparator reductions in that order. Ambiguous cases return None.
    """
    claim_match = re.search(r'~\s*(\d+(?:\.\d+)?)\s*[Ã—x]', claim_text, re.I)
    if not claim_match or not re.search(r'reduction', claim_text, re.I):
        return None
    # Only parse a sentence that explicitly names the intervention/comparator sequence.
    m = re.search(r'compared with[^()]*\(([^)]{1,120})\)', evidence_span, re.I)
    if not m:
        return None
    values = re.findall(r'[âˆ’-]?\d+(?:\.\d+)?', m.group(1).replace('âˆ’','-'))
    if len(values) < 2:
        return None
    try:
        intervention = abs(float(values[0])); comparator = abs(float(values[1]))
        claimed = float(claim_match.group(1))
        if comparator == 0 or intervention == 0:
            return None
        ratio = intervention / comparator
        return {'claimed_ratio': claimed, 'source_values': [intervention, comparator],
                'computed_ratio': round(ratio, 2), 'arithmetic': f'{intervention} / {comparator}',
                'matches_claim': abs(ratio - claimed) <= 0.25}
    except (ValueError, ZeroDivisionError):
        return None



def enforce_supported_checks(result: dict[str, Any]) -> dict[str, Any]:
    """Downgrade a supported verdict unless every required check is an explicit match."""
    required = ("figure", "population", "drug_indication", "actually_stated")
    checks = result.get("checks")
    if result.get("verdict") == "supported" and (
        not isinstance(checks, dict) or any(checks.get(k) != "match" for k in required)
    ):
        result["verdict"] = "cannot_verify"
        result["reason"] = (str(result.get("reason", "")).rstrip()
                            + " Verdict downgraded: not all four required checks were explicit matches.").strip()
    return result


def verify_one(claim: dict[str, Any], pages: list[dict[str, Any]], log_path: Path) -> dict[str, Any]:
    candidates = candidate_pages(claim, pages)
    if not candidates:
        return fail_closed(claim, 'No readable PDF evidence was found for the cited source.')
    try:
        result = call_gemini(claim, candidates, log_path)
    except RuntimeError as e:
        return fail_closed(claim, f"{e}. Claim was not adjudicated; no supported verdict is emitted.")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        return fail_closed(claim, f"LLM output failed schema/JSON validation ({type(e).__name__}); fail-closed by design.")
    except Exception as e:
        return fail_closed(claim, f"Unexpected claim-level failure ({type(e).__name__}); claim was not adjudicated.")
    quote_ok, page = validate_quote(result, candidates)
    if not quote_ok:
        return fail_closed(claim, 'The proposed evidence quotation did not match the cited source text exactly after whitespace normalization.')
    checks = result['checks']
    computed = python_numeric_audit(str(claim.get('text', '')), result['evidence_span'])
    if computed is not None and not computed['matches_claim']:
        result['verdict'] = 'overstated'
        result['reason'] += f" Python numeric audit: claimed about {computed['claimed_ratio']}x, source values {computed['source_values']} imply {computed['computed_ratio']}x ({computed['arithmetic']})."
        checks['figure'] = 'mismatch'
        checks['actually_stated'] = 'mismatch'
    enforce_supported_checks(result)
    return {'claim_id':claim.get('claim_id'),'verdict':result['verdict'],'checks':checks,
        'evidence_file':page['file'],'evidence_page':page['page'],'evidence_span':result['evidence_span'],
        'computed':computed,'reason':result['reason']}


def main() -> int:
    parser = argparse.ArgumentParser(description='Verify claims against supplied study PDFs (fail closed).')
    parser.add_argument('claims_file', nargs='?', default='data/claims.json')
    parser.add_argument('--root', default=str(ROOT), help='Project root containing papers/ and outputs/')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    claims_path = Path(args.claims_file)
    if not claims_path.is_absolute(): claims_path = root / claims_path
    try:
        claims = json.loads(claims_path.read_text(encoding='utf-8'))
        if not isinstance(claims, list): raise ValueError('claims JSON must be a list of objects')
        if any(not isinstance(c, dict) or not c.get('claim_id') or not c.get('text') for c in claims):
            raise ValueError('each claim must be an object with claim_id and text')
        pages = load_pdfs(root)
    except Exception as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2
    log_path = root / 'outputs' / 'llm_log.jsonl'
    # A new run gets a fresh log, so it contains only calls from that run.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text('', encoding='utf-8')
    predictions = []
    for claim in claims:
        try:
            predictions.append(verify_one(claim, pages, log_path))
        except Exception as e:
            # Last-resort per-claim isolation: one unexpected failure must not abort the batch.
            predictions.append(fail_closed(
                claim, f"Unexpected claim-level failure ({type(e).__name__}); claim was not adjudicated."
            ))
    out = root / 'outputs' / 'predictions.json'
    out.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {out.relative_to(root)} ({len(predictions)} claims).')
    if not os.getenv('GEMINI_API_KEY'):
        print('GEMINI_API_KEY is not set; fail-closed mode returned cannot_verify. Set the key to adjudicate claims.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())