"""Fixed, untuned evaluation protocol; no fitting or covariance search.

Run: node scripts/python.mjs -m benchmarks.estimation_evaluate
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from l5.estimation import FILTER_DEFAULTS, estimate, score
from l5.estimation_workspace import simulation_observations

SEEDS = [11, 29, 47]
CASES = [
    dict(id='healthy-both', sensors=['level1','level2']),
    dict(id='healthy-tank1-only', sensors=['level1']),
    dict(id='healthy-tank2-only', sensors=['level2']),
    dict(id='async-dropout-irregular', sensors=['level2'], acquisition=dict(every=[1,4],dropout=.35,irregular=True)),
    dict(id='pump-degradation', sensors=['level2'], simulation=dict(fault='pump_degradation')),
    dict(id='valve-restriction', sensors=['level2'], simulation=dict(fault='valve_restriction')),
    dict(id='parameter-mismatch', sensors=['level1','level2'], model=dict(connection=.025,pumpRate=.038)),
    dict(id='initial-uncertainty-small', sensors=['level2'], config=dict(initialCovariance=[[1e-5,0],[0,1e-5]])),
    dict(id='initial-uncertainty-large', sensors=['level2'], config=dict(initialCovariance=[[1.,0],[0,1.]])),
    dict(id='sensor-bias-overconfident-R', sensors=['level1','level2'], simulation=dict(fault='sensor_bias'),
         config=dict(measurementCovariance=[[1e-6,0],[0,1e-6]])),
    dict(id='exact-initial-open-loop-baseline', sensors=['level1','level2'], config=dict(initialState=[1.5625,1.])),
]


def evaluate():
    runs=[]
    for case in CASES:
        for seed in SEEDS:
            source = dict(simulation=dict(duration=180.,step=.5,start=40.,seed=seed,**case.get('simulation',{})),
                          noise=[.02,.02],every=[1,1],dropout=0.,irregular=False)
            source.update(case.get('acquisition',{}))
            observations, controls, truth, resolved = simulation_observations(source)
            cfg = {**deepcopy(FILTER_DEFAULTS), **case.get('config',{})}
            result = estimate(observations,controls,model=case.get('model'),config=cfg,sensors=case['sensors'])
            metrics = score(result,truth)
            runs.append(dict(case=case['id'],seed=seed,sensors=case['sensors'],model=case.get('model',{}),
                source=resolved, config=cfg, samples=len(observations), predictionOnly=result['predictionOnly'],
                inputSha256=hashlib.sha256(json.dumps(dict(observations=observations,controls=controls),sort_keys=True).encode()).hexdigest(),
                score=metrics, innovationConsistency=result['innovationConsistency'], warnings=result['warnings'],
                maxAbsoluteError=np.max(np.abs(np.array([r['estimate'] for r in result['rows']])-
                    np.array([[r['level1'],r['level2']] for r in truth])),axis=0).tolist()))
    summary=[]
    for case in CASES:
        group=[r for r in runs if r['case']==case['id']]
        summary.append(dict(case=case['id'],seeds=SEEDS,
            meanRMSE={m:np.mean([[r['score']['methods'][m][j]['rmse'] if r['score']['methods'][m][j]['rmse'] is not None else np.nan
                                for j in range(2)] for r in group],axis=0).tolist() for m in ('estimate','openLoop')},
            meanCoverage95=np.mean([r['score']['coverage95'] for r in group],axis=0).tolist(),
            worseThanOpenLoopCount=np.sum([r['score']['worseThanOpenLoop'] for r in group],axis=0).tolist(),
            convergedRuns=sum(r['score']['convergenceTime'] is not None for r in group),
            numericalFailures=0))
    return dict(protocol='tank-estimation-evaluation-v1',seeds=SEEDS,cases=CASES,defaults=FILTER_DEFAULTS,
        assumptions='Fixed Q, R and initial settings declared before evaluation; no final-run covariance fitting. '
            'Deterministic simulator plus independent additive sensor noise; Q is a robustness assumption, not injected physical process noise. '
            'NIS/NEES therefore diagnose misspecification and are not claimed chi-square calibrated here. '
            'NEES dimension=2; NIS dimension=current measurement count. Temporal samples are correlated. '
            'Coverage is pointwise empirical coverage; convergence means both errors stay <=0.05 m through run end. '
            'Three fixed seeds characterize examples, not population guarantees. Numerical failures abort this script.',
        summary=summary,runs=runs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='examples/state-estimation/evaluation.json')
    args=parser.parse_args()
    result=evaluate()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(f'{len(result["runs"])} fixed evaluations written to {path}')
    for row in result['summary']:
        print(row['case'], 'RMSE', [round(v,4) for v in row['meanRMSE']['estimate']],
              'coverage', [round(v,3) for v in row['meanCoverage95']], 'worse',row['worseThanOpenLoopCount'])


if __name__ == '__main__':
    main()
