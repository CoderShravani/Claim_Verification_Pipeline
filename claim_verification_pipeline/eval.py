#!/usr/bin/env python3
"""Evaluate predictions against the manually reviewed gold set."""
import argparse, json
from pathlib import Path

LABELS = ['supported', 'overstated', 'cannot_verify']

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--predictions', default='outputs/predictions.json')
    p.add_argument('--gold', default='data/gold.json')
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    pred_path = Path(args.predictions); gold_path = Path(args.gold)
    if not pred_path.is_absolute(): pred_path = root / pred_path
    if not gold_path.is_absolute(): gold_path = root / gold_path
    preds = json.loads(pred_path.read_text()); gold = json.loads(gold_path.read_text())
    if not isinstance(preds, list) or not isinstance(gold, list): raise SystemExit('Both files must contain JSON lists.')
    pmap = {x['claim_id']: x for x in preds}; gmap = {x['claim_id']: x for x in gold}
    if set(pmap) != set(gmap): raise SystemExit(f'Claim IDs differ: predictions={sorted(pmap)}, gold={sorted(gmap)}')
    matrix = {g:{p:0 for p in LABELS} for g in LABELS}
    false_supported = 0
    for cid, g in gmap.items():
        pv = pmap[cid].get('verdict'); gv = g.get('verdict')
        if pv not in LABELS or gv not in LABELS: raise SystemExit(f'Invalid verdict for {cid}: gold={gv}, prediction={pv}')
        matrix[gv][pv] += 1
        if pv == 'supported' and gv != 'supported': false_supported += 1
    correct = sum(matrix[x][x] for x in LABELS); n = len(gmap)
    print(f'Accuracy: {correct}/{n} = {correct/n:.3f}' if n else 'Accuracy: n/a (no claims)')
    print('Confusion matrix (rows=gold, columns=prediction)')
    print('gold\\pred       ' + '  '.join(f'{x:>14}' for x in LABELS))
    for g in LABELS: print(f'{g:14} ' + '  '.join(f'{matrix[g][p]:14d}' for p in LABELS))
    print(f'False supported verdicts: {false_supported}')
    print('Per-claim:')
    for cid in sorted(gmap): print(f"  {cid}: gold={gmap[cid]['verdict']}, predicted={pmap[cid]['verdict']}, {'OK' if gmap[cid]['verdict']==pmap[cid]['verdict'] else 'MISS'}")
if __name__ == '__main__': main()
