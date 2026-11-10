"""Fixed-parameter control evaluation; no tuning on these evaluation scenarios.

node scripts/python.mjs scripts/benchmark-control.py
Add --data-dir .integration-cache/control-benchmark to reopen complete results
in L5. The compact checked-in JSON retains configurations, metrics and hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from l5.control import compare, validate_protocol, PI_DEFAULTS, MPC_DEFAULTS, VERSION
from l5.models.tanks import CoupledTankModel


CASES=[
    ('scheduled-step',dict(duration=180),dict(reference=[dict(time=0,level=1),dict(time=45,level=1.25)])),
    ('unannounced-step',dict(duration=180),dict(reference=[dict(time=0,level=1),dict(time=45,level=1.25)],
        controllers=[dict(kind='open-loop'),PI_DEFAULTS,{**MPC_DEFAULTS,'preview':False}])),
    ('outlet-disturbance',dict(duration=240),dict(disturbances=[dict(start=70,end=130,inletFactor=1.,outletFactor=1.4)])),
    ('pump-degradation',dict(duration=240,fault='pump_degradation',start=70,severity=.4,fault_duration=80),{}),
    ('unreachable-pump-loss',dict(duration=240,fault='pump_degradation',start=70,severity=1.),{}),
    ('valve-restriction',dict(duration=240,fault='valve_restriction',start=70,severity=.6,fault_duration=90),
        dict(controllers=[dict(kind='open-loop'),{**PI_DEFAULTS,'actuateValve':True},{**MPC_DEFAULTS,'actuateValve':True}])),
    ('sensor-bias',dict(duration=240,fault='sensor_bias',start=70,sensorBias=.4,severity=.6),{}),
    ('quiet-regulation',dict(duration=180,noise=.01),{}),
    ('initial-level-excursion',dict(duration=120,initial1=2.6,initial2=1.4),dict(constraints=dict(levelMax1=2.,levelMax2=1.3))),
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('docs/control-benchmark.json'))
    parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args()
    store=workspace=None
    if args.data_dir:
        from l5.workspace import WorkspaceStore
        store=WorkspaceStore(args.data_dir);workspace=store.create_workspace('Closed-loop control benchmark')
    result=dict(protocolVersion=VERSION,python=platform.python_version(),platform=platform.system(),
        parameterPolicy='Fixed engineering defaults based on the nominal equilibrium; no parameter selection on these evaluation cases. Preview is explicitly disabled in the unannounced-step case. PI is a practical baseline, not an optimally tuned controller.',
        pi=PI_DEFAULTS,mpc=MPC_DEFAULTS,cases=[])
    for name,changes,protocol_changes in CASES:
        config=CoupledTankModel().validate(dict(seed=947,noise=.002)|changes)
        protocol=validate_protocol(protocol_changes,config)
        run=store.control.create(workspace['id'],dict(name=name,config=config,protocol=protocol)) if store else compare(config,protocol)
        result.setdefault('solver',run['solver'])
        entry=dict(name=name,config=config,protocol=protocol,noiseFingerprint=run['noiseFingerprint'],controllers=[])
        if store:entry['savedExperimentId']=run['id']
        for branch in run['results']:
            evidence=dict(rows=branch['rows'],physical=branch['physical'],decisions=[{k:v for k,v in d.items() if k!='durationMs'} for d in branch['decisions']])
            digest=hashlib.sha256(json.dumps(evidence,sort_keys=True,allow_nan=False).encode()).hexdigest()
            entry['controllers'].append(dict(controller=branch['controller'],settings=branch['settings'],metrics=branch['metrics'],trajectorySha256=digest,
                solverStatuses={status:sum(d['solver']['status']==status for d in branch['decisions']) for status in sorted({d['solver']['status'] for d in branch['decisions']})}))
        result['cases'].append(entry)
        print(name,[(b['controller'],round(b['metrics']['iae'],4),b['metrics']['solverFailures']) for b in run['results']],flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if workspace:print('Reopen: #/workspaces/'+workspace['id']+'/control')
    print('Saved',args.output)


if __name__=='__main__':main()
