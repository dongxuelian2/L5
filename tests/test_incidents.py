"""Persistent CSV and model investigations through the actual local HTTP routes."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler

import numpy as np

from l5.workspace import WorkspaceStore
from server import Handler


def csv_with_excursions():
    rng = np.random.default_rng(816)
    values = rng.normal(0, .1, (700, 3)) + [80, 300, 4]
    values[340:380, 0] += 6
    values[510:555, 2] += 3
    return 'seconds,temperature,feed,vibration\n' + '\n'.join(
        str(t) + ',' + ','.join(str(v) for v in row) for t, row in enumerate(values))


class IncidentHTTPFixture(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.start()

    def start(self):
        self.service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.service.workspace_store = WorkspaceStore(self.folder)
        self.thread = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.service.shutdown()
        self.service.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def request(self, path, body=None, method=None, expected=200):
        req = Request(f'http://127.0.0.1:{self.service.server_port}/api{path}',
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'}, method=method)
        try:
            response = build_opener(ProxyHandler({})).open(req, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, expected)
            return json.load(response)

    def workspace(self, name='工业事件调查'):
        return self.request('/workspaces', {'name': name}, expected=201)['id']

    def analyze(self, wid, did, algorithm='robust-maxz'):
        return self.request(f'/workspaces/{wid}/analyses', dict(datasetId=did,
            signals=['temperature', 'feed', 'vibration'], algorithm=algorithm,
            baselineRange=[0, 199], analysisRange=[200, 699], alpha=.01), expected=201)

class IncidentHTTPTests(IncidentHTTPFixture):
    def test_csv_incident_multiple_intervals_algorithms_records_restart_and_resume(self):
        wid = self.workspace()
        dataset = self.request(f'/workspaces/{wid}/datasets', {'csv': csv_with_excursions(), 'name': '反应器记录'}, expected=201)
        result = self.analyze(wid, dataset['id'])
        indices = [next(i for i, interval in enumerate(result['intervals']) if interval['start'] <= t <= interval['end']) for t in (350, 520)]
        self.assertNotEqual(indices[0], indices[1])
        source = dict(kind='interval', analysisId=result['id'], datasetId=dataset['id'], intervalIndex=indices[0])
        incident = self.request(f'/workspaces/{wid}/incidents', dict(title='两次工况偏离', description='等待现场核对',
            start_time=330, end_time=560, source=source), expected=201)
        base = f'/incidents/{incident["id"]}'
        first_link = incident['links'][0]['id']
        self.assertEqual(incident['links'][0]['details']['interval'], result['intervals'][indices[0]])
        # Repeated clicks reuse the same source reference; distinct intervals remain distinct.
        self.request(base + '/links', source, expected=201)
        incident = self.request(base + '/links', {**source, 'intervalIndex': indices[1]}, expected=201)
        self.assertEqual(len(incident['links']), 2)
        pca = self.analyze(wid, dataset['id'], 'pca-q')
        pca_index = next(i for i, v in enumerate(pca['intervals']) if v['start'] <= 520 <= v['end'])
        self.request(base + '/links', dict(kind='interval', analysisId=pca['id'], intervalIndex=pca_index), expected=201)
        # An incident can also include a second dataset and the entire analysis.
        second = self.request(f'/workspaces/{wid}/datasets', {'csv': 'time,pressure\n0,3\n1,4\n2,6', 'name': '现场补充'}, expected=201)
        self.request(base + '/links', dict(kind='dataset', datasetId=second['id']), expected=201)
        self.request(base + '/links', dict(kind='analysis', analysisId=pca['id']), expected=201)
        incident = self.request(base + '/entries', dict(kind='hypothesis', title='冷却不足', content='核对冷却回路'), expected=201)
        hypothesis = incident['entries'][0]['id']
        incident = self.request(base + '/entries', dict(kind='evidence', title='温升先于振动', content='温度曲线在第一个区间持续偏离。',
            hypothesis_id=hypothesis, stance='support', source_link_id=first_link, observed_at=350), expected=201)
        evidence = incident['entries'][-1]['id']
        self.request(base + '/entries', dict(kind='evidence', title='进料未变化', content='进料曲线稳定', hypothesis_id=hypothesis, stance='oppose'), expected=201)
        incident = self.request(base + '/entries', dict(kind='note', title='下一步', content='联系现场核对冷却水。'), expected=201)
        note = incident['entries'][-1]['id']
        self.request(base + f'/entries/{note}', {'content': '已查阅交接记录，明天复核。'}, method='PATCH')
        self.request(base + f'/entries/{evidence}', {'content': '补充说明：温度在 340 秒出现持续偏离。'}, method='PATCH')
        saved = self.request(base, dict(title='反应器两次偏离调查', status='investigating', start_time=335, end_time=560,
            conclusion='第一阶段判断为冷却侧变化，振动来源仍需确认。'), method='PATCH')
        listed = self.request(f'/workspaces/{wid}/incidents?status=investigating&start=340&end=550&q={quote("反应器")}')['incidents']
        self.assertEqual([i['id'] for i in listed], [saved['id']])
        self.assertEqual(listed[0]['analysis_count'], 2)
        self.assertEqual(listed[0]['interval_count'], 3)
        self.stop(); self.start()
        restored = self.request(base)
        self.assertEqual(restored, saved)
        self.assertEqual(self.request(base + '/entries')['entries'], saved['entries'])
        self.assertEqual(self.request(base + '/links')['links'], saved['links'])
        self.assertEqual(self.request(f'/analyses/{result["id"]}'), result)
        curves = self.request(f'/datasets/{dataset["id"]}/series?signal=temperature&start=340&end=379')
        self.assertEqual(len(curves['times']), 40)
        resumed = self.request(base + f'/entries/{note}', {'content': '重启后继续：现场已确认冷却水波动。'}, method='PATCH')
        self.assertIn('重启后继续', next(e['content'] for e in resumed['entries'] if e['id'] == note))
        self.request(base + f'/entries/{hypothesis}', method='DELETE')
        remaining = self.request(base)['entries']
        self.assertTrue(all(e['hypothesis_id'] is None and e['stance'] == 'neutral' for e in remaining))
        unlinked = self.request(base + f'/links/{first_link}', method='DELETE')
        self.assertIsNone(next(e['source_link_id'] for e in unlinked['entries'] if e['id'] == evidence))
        archived = self.request(base, {'status': 'archived'}, method='PATCH')
        self.assertEqual(archived['status'], 'archived')
        self.assertEqual(len(self.request(f'/workspaces/{wid}/incidents?status=archived')['incidents']), 1)

    def test_runtime_tools_hypothesis_intervention_restart_and_continue(self):
        wid = self.workspace('TripLens 事件调查')
        session = self.request('/simulations', dict(workspaceId=wid, title='冷却模型调查',
            config=dict(fault='cooling_valve', start=35, duration=180, step=.5, seed=418)), expected=201)
        sid = session['id']
        dataset = self.request(f'/simulations/{sid}/save', {'workspaceId': wid})
        tool = self.request(f'/simulations/{sid}/tools', dict(asOf=93, windowStart=0, hypothesis='cooling_valve',
            calls=[{'tool': 'sensor_consistency', 'args': {}}]))
        trial = self.request(f'/simulations/{sid}/interventions', dict(asOf=93, windowStart=0, hypothesis='cooling_valve',
            mode='known', at=96, horizon=200, actions=['feed_reduce', 'bypass'], parameters={'feedReduction': .3}))
        incident = self.request(f'/workspaces/{wid}/incidents', dict(title='冷却阀候选调查', start_time=35, end_time=100,
            source=dict(kind='run', simulationId=sid, runId=tool['id'], hypothesis='cooling_valve')), expected=201)
        base = f'/incidents/{incident["id"]}'
        hypothesis_id = incident['entries'][0]['id']
        self.request(base + f'/entries/{hypothesis_id}', {'title': '冷却侧工作解释', 'content': '保留人工补充说明。'}, method='PATCH')
        incident = self.request(base + '/links', dict(kind='run', simulationId=sid, runId=trial['id'], hypothesis='cooling_valve'), expected=201)
        self.assertEqual(len(incident['entries']), 1)
        self.assertEqual(incident['entries'][0]['kind'], 'hypothesis')
        self.assertEqual(incident['entries'][0]['content'], '保留人工补充说明。')
        self.request(base + '/entries', dict(kind='evidence', title='传感器一致性结果', content='记录工具调查并保留原始结果。',
            hypothesis_id=incident['entries'][0]['id'], stance='support', source_link_id=incident['links'][0]['id']), expected=201)
        saved = self.request(base, dict(status='resolved', conclusion='保留冷却阀解释，后续用观测拟合继续验证。'), method='PATCH')
        self.stop(); self.start()
        self.assertEqual(self.request(base), saved)
        links = self.request(base)['links']
        self.assertEqual(next(l['details']['run'] for l in links if l['selector'] == trial['id']), trial)
        self.assertEqual(self.request(f'/simulations/{sid}/runs/{tool["id"]}'), tool)
        self.assertEqual(self.request(f'/datasets/{dataset["id"]}')['metadata']['model']['simulationId'], sid)
        next_tool = self.request(f'/simulations/{sid}/tools', dict(asOf=110, windowStart=0,
            calls=[{'tool': 'inspect_controller', 'args': {'controller': 'TIC-101'}}]))
        continued = self.request(base + '/links', dict(kind='run', simulationId=sid, runId=next_tool['id']), expected=201)
        self.assertEqual(len(continued['links']), 3)
        selected = self.request(base + '/links', dict(kind='simulation', simulationId=sid, asOf=110.2,
            windowStart=0, hypothesis='pump_loss'), expected=201)
        context = next(l['details']['observationWindow'] for l in selected['links'] if l['kind'] == 'simulation')
        self.assertEqual(context, dict(asOf=110, windowStart=0, hypothesis='pump_loss'))
        self.assertEqual(len([e for e in selected['entries'] if e['kind'] == 'hypothesis']), 2)

    def test_ownership_existence_and_record_relationships(self):
        wid, other = self.workspace(), self.workspace('另一个项目')
        d = self.request(f'/workspaces/{other}/datasets', {'csv': csv_with_excursions()}, expected=201)
        analysis = self.analyze(other, d['id'])
        incident = self.request(f'/workspaces/{wid}/incidents', {'title': '引用检查'}, expected=201)
        base = f'/incidents/{incident["id"]}'
        for source in [dict(kind='dataset', datasetId=d['id']), dict(kind='analysis', analysisId=analysis['id']),
                       dict(kind='interval', analysisId=analysis['id'], intervalIndex=0)]:
            self.request(base + '/links', source, expected=400)
        self.request(base + '/links', dict(kind='analysis', analysisId='missing'), expected=404)
        same = self.request(f'/workspaces/{wid}/datasets', {'csv': csv_with_excursions()}, expected=201)
        result = self.analyze(wid, same['id'])
        self.request(base + '/links', dict(kind='interval', analysisId=result['id'], datasetId=d['id'], intervalIndex=0), expected=400)
        self.request(base + '/links', dict(kind='interval', analysisId=result['id'], intervalIndex=99999), expected=400)
        sid = self.request('/simulations', dict(workspaceId=other, config=dict(duration=100, step=1, seed=16)), expected=201)['id']
        self.request(base + '/links', dict(kind='simulation', simulationId=sid), expected=400)
        own_sid = self.request('/simulations', dict(workspaceId=wid, config=dict(duration=100, step=1, seed=17)), expected=201)['id']
        self.request(base + '/links', dict(kind='run', simulationId=own_sid, runId='a'*32), expected=404)
        second = self.request(f'/workspaces/{wid}/incidents', {'title': '另一事件'}, expected=201)
        second = self.request(f'/incidents/{second["id"]}/entries', dict(kind='hypothesis', title='其他事件的解释'), expected=201)
        self.request(base + '/entries', dict(kind='evidence', title='错误关系', hypothesis_id=second['entries'][0]['id']), expected=400)
        self.request(base + '/entries', dict(kind='evidence', title='不存在的来源', source_link_id='missing'), expected=400)
        self.request(base, dict(start_time=20, end_time=10), method='PATCH', expected=400)
        self.request(base, {'status': 'unknown'}, method='PATCH', expected=400)
        self.request(f'/workspaces/{wid}/incidents', dict(title='失败的关联', source=dict(kind='analysis', analysisId='missing')), expected=404)
        self.assertEqual(len(self.request(f'/workspaces/{wid}/incidents')['incidents']), 2)


class IncidentMigrationTests(unittest.TestCase):
    def test_existing_incident_schema_adds_clocks_and_history_without_rewriting_records(self):
        with TemporaryDirectory() as folder:
            store = WorkspaceStore(Path(folder))
            workspace = store.create_workspace('PR16 原有项目')
            incident = store.incidents.create(workspace['id'], dict(title='已有调查', conclusion='保留原文', start_time=10, end_time=20))
            store.incidents.save_entry(incident['id'], dict(kind='note', title='历史观察', content='仍需复核', observed_at=15))
            with store.connect() as db:
                db.execute('DROP TABLE incident_history')
                db.execute('ALTER TABLE incidents DROP COLUMN time_axis_key')
                db.execute('ALTER TABLE incident_entries DROP COLUMN observed_axis_key')
            migrated = WorkspaceStore(Path(folder))
            restored = migrated.incidents.get(incident['id'])
            self.assertEqual(restored['conclusion'], '保留原文')
            self.assertEqual(restored['entries'][0]['observed_at'], 15)
            self.assertIsNone(restored['time_axis_key'])
            self.assertEqual(migrated.incidents.history(incident['id']), [])
            migrated.incidents.update(incident['id'], {'conclusion': '迁移后继续调查'})
            self.assertEqual(migrated.incidents.history(incident['id'])[0]['changes']['conclusion']['before'], '保留原文')

    def test_additive_tables_preserve_existing_workspace_and_files(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            db = sqlite3.connect(root / 'workspace.sqlite3')
            db.executescript('''CREATE TABLE workspaces (id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                INSERT INTO workspaces VALUES ('old','既有项目','2026-10-01','2026-10-01');''')
            db.close()
            original = root / 'source.csv'
            original.write_text('time,pressure\n0,4\n1,5', encoding='utf-8')
            store = WorkspaceStore(root)
            self.assertEqual(store.workspace('old')['name'], '既有项目')
            incident = store.incidents.create('old', {'title': '迁移后创建'})
            self.assertEqual(WorkspaceStore(root).incidents.get(incident['id']), incident)
            self.assertEqual(original.read_text(encoding='utf-8'), 'time,pressure\n0,4\n1,5')
            store.delete_workspace('old')
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
