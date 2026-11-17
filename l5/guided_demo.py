"""One resumable built-in case, composed from the normal Workspace services."""
from threading import Lock


CONFIG = dict(fault='pump_degradation', start=120, duration=240, step=.2, seed=17, severity=.6)
PLAN = dict(baselineRange=[0, 79.8], analysisRange=[80, CONFIG['duration']],
            onset=CONFIG['start'], step=CONFIG['step'], signals=['level1', 'level2'],
            contextSignals=['inlet', 'pump'],
            alpha=.01, persistence=3)
DETECTORS = [dict(algorithm='robust-maxz'), dict(algorithm='ewma', parameters=dict(smoothing=.08))]


class GuidedDemo:
    def __init__(self, store):
        self.store = store
        self.lock = Lock()
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS guided_demo (
                id INTEGER PRIMARY KEY CHECK (id=1),
                workspaceId TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                datasetId TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                experimentId TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
                runId TEXT REFERENCES experiment_runs(id) ON DELETE SET NULL)''')

    def state(self):
        with self.store.connect() as db:
            row = db.execute('''SELECT d.*, i.id AS incidentId FROM guided_demo d
                LEFT JOIN incidents i ON i.id=d.runId AND i.workspace_id=d.workspaceId''').fetchone()
        return dict(plan=PLAN, session={k: row[k] for k in row.keys() if k != 'id'} if row else None)

    def prepare(self, locale):
        with self.lock:
            state = self.state()
            if state['session']:
                return state
            store = self.store
            zh = locale == 'zh-CN'
            title = '双水箱 · 入口泵性能下降' if zh else 'Coupled tanks · inlet pump degradation'
            workspace = store.create_workspace('引导调查演示' if zh else 'Guided Investigation Demo')
            workspace_id = workspace['id']
            try:
                scenario = store.scenarios.save(workspace_id, dict(
                    name=title, modelId='coupled-tanks', config=CONFIG))
                simulation = store.runtime.create(dict(scenarioId=scenario['id']))
                dataset = store.runtime.save(simulation['id'], {})
                labels = store.experiments.simulation_labels(dataset['id'], {})
                config = {k: PLAN[k] for k in ('signals', 'baselineRange', 'analysisRange', 'alpha', 'persistence')}
                experiment = store.experiments.save(workspace_id, dict(name=title, config=dict(
                    **config, datasetId=dataset['id'], labelSetId=labels['id'], algorithms=DETECTORS)))
                with store.connect() as db:
                    db.execute('INSERT INTO guided_demo VALUES (1,?,?,?,NULL)',
                               (workspace_id, dataset['id'], experiment['id']))
            except Exception:
                store.delete_workspace(workspace_id)
                raise
            return self.state()

    def start(self):
        with self.lock:
            session = self.require_session()
            experiment_id = session['experimentId']
            retry = {}
            if session['runId']:
                previous = self.store.experiments.run(session['runId'])
                if previous['status'] in ('queued', 'running') or any(t['result_id'] for t in previous['tasks']):
                    return self.state()
                retry = dict(retryRunId=previous['id'])
            run = self.store.experiments.execute(experiment_id, retry, expected_revision=1)
            with self.store.connect() as db:
                db.execute('UPDATE guided_demo SET runId=? WHERE workspaceId=?', (run['id'], session['workspaceId']))
            return self.state()

    def require_session(self):
        session = self.state()['session']
        if session is None:
            raise KeyError('Load the guided scenario first.')
        return session

    def incident(self, locale):
        with self.lock:
            session = self.require_session()
            if session['incidentId']:
                return self.state()
            if not session['runId']:
                raise ValueError('Complete the detector run before opening the investigation.')
            store = self.store
            run = store.experiments.run(session['runId'])
            results = [t['result_id'] for t in run['tasks'] if t['status'] == 'succeeded']
            if run['status'] in ('queued', 'running') or not results:
                raise ValueError('Complete the detector run before opening the investigation.')
            dataset_id = session['datasetId']
            model = store.dataset(dataset_id)['metadata']['model']
            onset, step = model['config']['start'], model['config']['step']
            before, after = (store.sample(dataset_id, at, PLAN['contextSignals'])['values']
                             for at in (onset - step, onset))
            zh = locale == 'zh-CN'
            description = (
                f'在 {onset:g} 秒注入模拟故障。FT-101 入口流量从 {before["inlet"]:.4f} 降至 '
                f'{after["inlet"]:.4f} m³/s，PC-101 泵指令维持在 {after["pump"]:g}%。'
                '将两路液位的报警时序与流量变化对照，记录支持或反对入口泵性能下降的证据。'
                if zh else
                f'The model injects a fault at {onset:g} s. FT-101 inlet flow falls from {before["inlet"]:.4f} '
                f'to {after["inlet"]:.4f} m³/s while the PC-101 pump command stays at {after["pump"]:g}%. '
                'Compare the two level signals and the alarm timing with the flow change. '
                'Record evidence for or against inlet pump degradation.'
            )
            store.incidents.create(session['workspaceId'], dict(
                title='入口泵供水下降调查' if zh else 'Investigate the inlet flow loss',
                description=description, status='investigating',
                start_time=PLAN['analysisRange'][0], end_time=PLAN['analysisRange'][1]),
                identity=run['id'], sources=[
                    dict(kind='dataset', datasetId=dataset_id),
                    *(dict(kind='analysis', analysisId=result) for result in results),
                    dict(kind='simulation', simulationId=model['simulationId']),
                ])
            return self.state()
