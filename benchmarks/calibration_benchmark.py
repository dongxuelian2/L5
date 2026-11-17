"""Fixed offline identification protocol; held-out data never selects parameters.

Run: node scripts/python.mjs -m benchmarks.calibration_benchmark
Optional --datasets writes ordinary CSVs that can be imported in the UI.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from l5.calibration_examples import observations,csv_observations
from l5.identification import VERSION,Observations,configuration,fit


def observed(rows,name):
    return Observations(np.array([r['t'] for r in rows]),
        {k:np.array([r[k] for r in rows]) for k in ('level1','level2','pump','valve')},dict(datasetName=name))


def run_benchmark():
    cases=[('clean',dict(noise=0),{}),
           *[(f'noise-{seed}',dict(seed=seed),{}) for seed in (19,32,71)],
           ('equilibrium',dict(noise=0,equilibrium=True),{}),
           ('pump-product',dict(noise=0),dict(confounded=True)),
           ('leak-mismatch',dict(mismatch=True),{}),
           ('budget-exhausted',{},dict(budget=1)),
           ('different-start',dict(seed=19),dict(initial=[.055,.025,.045]))]
    report=[]
    for name,generator,options in cases:
        rows,truth=observations(**generator)
        # Different initial state, input sequence and independent sensor noise.
        test,_=observations(seed=201,validation=True,noise=generator.get('noise',.002),mismatch=generator.get('mismatch',False))
        initial=options.get('initial',[.03,.04,.03])
        raw=dict(parameters={k:dict(initial=v,lower=.01,upper=.08) for k,v in zip(truth,initial)},
                 maxEvaluations=options.get('budget',80))
        if options.get('confounded'):
            raw['parameters']['pumpEfficiency']=dict(initial=.8,lower=.3,upper=1.)
        result=fit(configuration(raw),observed(rows,name),observed(test,'held-out operating sequence'))
        identifiable=result['identifiability']['status']=='locally-identifiable'
        valid=identifiable and result['optimizer']['converged'] and not generator.get('mismatch')
        record=dict(case=name,converged=result['optimizer']['converged'],evaluations=result['optimizer']['evaluations'],
            rank=result['identifiability']['rank'],parameters=result['identifiability']['parameterCount'],
            identifiability=result['identifiability']['status'],warnings=result['warnings'],
            estimates={k:v['value'] for k,v in result['parameters'].items()},
            recoveryRelativeError={k:abs(result['parameters'][k]['value']/v-1) for k,v in truth.items()} if valid else None,
            validation={k:dict(rmse=v['rmse'],originalRmse=result['validation']['originalMetrics'][k]['rmse'],
                               ratioToOriginal=v['rmse']/result['validation']['originalMetrics'][k]['rmse'])
                        for k,v in result['validation']['metrics'].items()},
            massBalanceError=result['calibration']['massBalanceError'],
            numericalDifference=result['calibration']['numericalStepDifferenceRmse'])
        report.append(record)
        print(f"{name}: rank {record['rank']}/{record['parameters']}, converged={record['converged']}, "
              f"held-out LT2 RMSE={record['validation']['level2']['rmse']:.6g}",flush=True)
    noisy=[r for r in report if r['case'].startswith('noise-')]
    stability={k:float(np.std([r['estimates'][k] for r in noisy],ddof=1)/observations()[1][k])
               for k in noisy[0]['estimates']}
    return dict(protocol=VERSION,seeds=[19,32,71],validationSeed=201,
        noiseStdMeters=.002,integrationStepSeconds=.05,generatorStepSeconds=.025,
        assumptions='Known geometry; observed levels; exact zero-order-held pump and valve commands; Gaussian level noise.',
        scope='Deterministic simulator benchmarks, not real-plant validation. The single operating equilibrium is deliberately uninformative.',
        noiseRecoveryRelativeStd=stability,cases=report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('output/calibration-benchmark.json'))
    parser.add_argument('--datasets',type=Path)
    args=parser.parse_args()
    report=run_benchmark()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if args.datasets:
        args.datasets.mkdir(parents=True,exist_ok=True)
        for name,options in [('calibration',{}),('validation',dict(seed=201,validation=True)),('insufficient-excitation',dict(noise=0,equilibrium=True)),('model-mismatch',dict(mismatch=True))]:
            rows,_=observations(**options)
            (args.datasets/f'{name}.csv').write_text(csv_observations(rows),encoding='utf-8')


if __name__=='__main__': main()
