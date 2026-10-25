"""A bounded index of saved detector results, retaining each model's provenance.

This index reads immutable run snapshots and task metrics. It never reruns a
detector, combines signal spaces, or interprets one process with another model.
"""
import json


def research(store, workspace_id):
    store.workspace(workspace_id)
    rows=[]
    with store.connect() as db:
        runs=db.execute('''SELECT r.id,r.snapshot,r.created_at,e.id AS experiment_id
            FROM experiment_runs r JOIN experiments e ON e.id=r.experiment_id
            WHERE e.workspace_id=? ORDER BY r.created_at DESC,r.id DESC LIMIT 101''',(workspace_id,)).fetchall()
        truncated=len(runs)>100
        for run in runs[:100]:
            snapshot=json.loads(run['snapshot']);dataset=snapshot['dataset'];metadata=dataset['metadata']
            models=[metadata['model']] if metadata.get('model') else metadata.get('transformation',{}).get('sourceModels',[])
            if not models:
                continue
            tasks=db.execute('SELECT * FROM experiment_tasks WHERE run_id=? ORDER BY ordinal',(run['id'],)).fetchall()
            for task in tasks:
                if len(rows)>=200:
                    truncated=True
                    break
                rows.append(dict(experimentId=run['experiment_id'],experimentName=snapshot['experiment']['name'],
                    runId=run['id'],taskId=task['id'],createdAt=run['created_at'],datasetId=dataset['id'],datasetName=dataset['name'],
                    models=[{k:m.get(k) for k in ('id','version','name','simulationId','scenarioId','scenarioVersion')} for m in models],
                    algorithm=task['algorithm'],config=json.loads(task['config']),status=task['status'],resultId=task['result_id'],
                    metrics=json.loads(task['metrics']) if task['metrics'] else None,
                    labelSetId=snapshot['labels']['id'] if snapshot.get('labels') else None,
                    labelVersion=snapshot['labels']['version'] if snapshot.get('labels') else None))
    return dict(rows=rows,truncated=truncated,limit=200,
        scope='Latest 100 experiment runs; at most 200 tasks. Each row retains its original dataset, model, scenario, configuration and label version. Scores and physical variables are not normalized across models.')
