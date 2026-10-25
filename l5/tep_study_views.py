"""Compact projections for the live dashboard; full audit exports stay separate."""
import json


def study_view(study):
    tasks = []
    for task in study['tasks']:
        metrics = task['metrics']
        tasks.append({**{k:task[k] for k in ('id','algorithm','status','error','result_id','run_id','datasetId','datasetName','experimentId','benchmark')},
            'external': {k:task['external'][k] for k in ('id','faultNumber','simulationRun','faultOnsetSeconds')},
            'metrics': dict(detection=metrics.get('detection'),training=metrics.get('training'),
                sample=metrics['labelled']['sample'] if metrics['labelled'] else None) if metrics else None})
    cells = [{**c, 'condition':json.dumps(dict(algorithm=c['algorithm']))} for c in study['cells']]
    return {**{k:v for k,v in study.items() if k not in ('tasks','cells')}, 'tasks':tasks,'cells':cells}
