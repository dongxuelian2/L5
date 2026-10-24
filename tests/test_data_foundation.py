"""Signal semantics, source clocks, real quality, explorer persistence and compatibility."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.request import build_opener, ProxyHandler

import numpy as np

from l5.datasets import prepare_csv, series_preview
from l5.incident_timeline import investigation, observed_spans
from l5.workspace import WorkspaceStore
from l5.reports import timestamp
from tests.test_incidents import IncidentHTTPFixture


class SourceDataTests(unittest.TestCase):
    def test_invalid_duplicate_unsorted_time_and_missing_measurements_are_distinct(self):
        csv = 't,temp,offline\n3,13,\n0,10,\n1,,\n1,12,\ninvalid,99,\n2,bad,\n30,14,\n31,15,\n'
        meta, times, values = prepare_csv(csv, {'timeKind': 'numeric'})
        np.testing.assert_array_equal(times, [0, 1, 1, 2, 3, 30, 31])
        np.testing.assert_allclose(values[:, 0], [10, np.nan, 12, np.nan, 13, 14, 15], equal_nan=True)
        q = meta['quality']
        self.assertEqual((q['totalCount'], q['timedCount'], q['invalidTimeCount'], q['duplicateCount']), (8, 7, 1, 1))
        self.assertEqual(q['invalidTimes'][0]['row'], 6)
        self.assertEqual(q['typicalInterval'], 1)
        self.assertEqual(q['gaps'], [dict(start=3., end=30., duration=27.)])
        self.assertEqual(q['signals']['temp']['validCount'], 5)
        self.assertEqual(q['signals']['temp']['missing'], 2)
        self.assertEqual(q['signals']['temp']['invalidTimeMeasurements'], 1)
        self.assertEqual(q['signals']['temp']['max'], 99)
        self.assertEqual(q['signals']['offline']['availableSpans'], [])
        self.assertEqual(q['signals']['offline']['missing'], 8)
        self.assertTrue(all(not (s['start'] < 10 < s['end']) for s in q['signals']['temp']['availableSpans']))

    def test_iso_timezone_unix_and_relative_interpretations(self):
        self.assertEqual(timestamp(1792800000, {'origin': '1970-01-01T00:00:00Z'}), '2026-10-24 00:00:00.000 UTC')
        iso, times, _ = prepare_csv('timestamp,x\n2026-10-24T08:00:00+08:00,2\n2026-10-24T00:00:02Z,3\n', {})
        self.assertEqual(iso['time']['origin'], '2026-10-24T00:00:00+00:00')
        np.testing.assert_array_equal(times, [0, 2])
        naive, _, _ = prepare_csv('timestamp,x\n2026-10-24 08:00:00,2\n2026-10-24 08:00:01,3\n', {'timezone': 'Asia/Shanghai'})
        self.assertEqual(naive['time']['origin'], iso['time']['origin'])
        epoch = datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp()
        unix, times, _ = prepare_csv(f't,x\n{epoch*1000},2\n{(epoch+2)*1000},3\n', {'timeKind': 'unix', 'timeUnit': 'milliseconds'})
        self.assertEqual(unix['time']['origin'], iso['time']['origin'])
        self.assertEqual(unix['time']['kind'], 'unix')
        np.testing.assert_array_equal(times, [0, 2])
        relative, times, _ = prepare_csv(f't,x\n{epoch},2\n{epoch+2},3\n', {})
        self.assertIsNone(relative['time']['origin'])
        self.assertEqual(times[0], epoch)
        with self.assertRaises(ValueError):
            prepare_csv('t,x\nno-time,2\n', {'timeKind': 'numeric'})

    def test_irregular_steps_do_not_become_continuous_observations_and_preview_keeps_holes(self):
        meta, _, _ = prepare_csv('t,p\n0,1\n1,2\n2.4,3\n3.2,4\n4.2,5\n30,6\n31,7\n', {})
        q = meta['quality']
        self.assertTrue(q['irregular'])
        self.assertEqual(q['gapCount'], 1)
        self.assertEqual(len(q['signals']['p']['availableSpans']), 2)
        times = np.arange(12000, dtype=float)
        values = np.sin(times/10)[:, None]
        values[[20, 40, 50, 3050, 9500]] = np.nan
        values[6001, 0] = 999
        preview = series_preview(times, values, ['x'])
        self.assertLess(preview['displayRows'], 1600)
        self.assertIn(999, preview['values']['x'])
        ids = preview['segmentIds']['x']
        for a, b, ia, ib in zip(preview['times'], preview['times'][1:], ids, ids[1:]):
            if any(a < missing < b for missing in (20, 40, 50, 3050, 9500)):
                self.assertNotEqual(ia, ib, 'display path must not bridge a hidden missing sample')
        spans = observed_spans(dict(times=[0, 1, 2, 30, 31], states=['normal']*5), 100, 5)
        self.assertEqual(spans, [[100, 102], [130, 131]])

    def test_additive_migration_preserves_old_data_jobs_incidents_and_signal_ids(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            store = WorkspaceStore(root)
            wid = store.create_workspace('Existing project')['id']
            csv = 't,x\n' + '\n'.join(f'{t},{np.sin(t/7) + (10 if t > 250 else 0)}' for t in range(400))
            dataset = store.import_dataset(wid, dict(csv=csv))
            result = store.analyze(wid, dict(datasetId=dataset['id'], signals=['x'], algorithm='robust-maxz', baselineRange=[0, 149], analysisRange=[150, 399]))
            incident = store.incidents.create(wid, dict(title='Old incident', source=dict(kind='analysis', analysisId=result['id'])))
            source = root / wid / 'datasets' / dataset['id'] / 'source.csv'
            original = source.read_bytes()
            ids = [s['id'] for s in store.signals.catalog(wid)]
            with store.connect() as db:
                legacy_meta = store.base_dataset(dataset['id'])['metadata']
                legacy_meta.pop('quality')
                db.execute('UPDATE datasets SET metadata=? WHERE id=?', (json.dumps(legacy_meta), dataset['id']))
                for table in ('signals', 'dataset_time_references', 'explorer_views'):
                    db.execute(f'DROP TABLE {table}')
            restored = WorkspaceStore(root)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(restored.result(result['id']), result)
            self.assertEqual(restored.incidents.get(incident['id'])['title'], 'Old incident')
            self.assertEqual([s['id'] for s in restored.signals.catalog(wid)], ids)
            self.assertEqual(restored.dataset(dataset['id'])['metadata']['quality']['totalCount'], 400)
            self.assertTrue(investigation(restored, incident['id'])['analyses'])
            self.assertEqual([s['id'] for s in WorkspaceStore(root).signals.catalog(wid)], ids)


class SignalWorkspaceHTTPTests(IncidentHTTPFixture):
    def import_csv(self, wid, name, csv, **options):
        return self.request(f'/workspaces/{wid}/datasets', dict(csv=csv, name=name, **options), expected=201)

    def test_three_sources_metadata_quality_cursor_analysis_incident_report_and_restart(self):
        wid = self.workspace('Signal workspace acceptance')
        epoch = datetime(2026, 10, 24, tzinfo=timezone.utc)
        temp_csv = 'timestamp,temp_C\n' + '\n'.join(
            f'{(epoch+timedelta(seconds=t)).isoformat()},{80+np.sin(t/7)*.1+(8 if 400 <= t < 460 else 0)}' for t in range(600))
        flow_csv = 't,flow\n' + '\n'.join(f'{(epoch.timestamp()+t)*1000},{"" if t == 302 else 12+np.sin(t/20)}' for t in range(0, 500, 2))
        pressure_csv = 't,pressure\n' + '\n'.join(f'{t},{300+t*.1}' for t in [0, 1, 2.1, 3, 4, 5, 80, 81, 82, 83])
        temp = self.import_csv(wid, 'Temperature 1s', temp_csv)
        flow = self.import_csv(wid, 'Flow 2s', flow_csv, timeKind='unix', timeUnit='milliseconds')
        pressure = self.import_csv(wid, 'Pressure irregular', pressure_csv)
        catalog = self.request(f'/workspaces/{wid}/signals')['signals']
        by_dataset = {s['datasetId']: s for s in catalog}
        ids = [by_dataset[d['id']]['id'] for d in (temp, flow, pressure)]
        for dataset, label, unit, category in [(temp, 'Motor temperature', '°C', 'Temperature'), (flow, 'Cooling flow', 'm³/h', 'Flow'), (pressure, 'Feed pressure', 'kPa', 'Pressure')]:
            signal = by_dataset[dataset['id']]
            self.request('/signals/' + signal['id'], dict(displayName=label, unit=unit, category=category, device='Motor A', tags=['campaign'], logicalKey='motor-a.' + category.lower()), method='PATCH')
        isolated = self.request(f'/workspaces/{wid}/explore', dict(signalIds=ids))
        self.assertEqual(len(isolated['axes']), 2)
        self.request(f'/datasets/{pressure["id"]}/time-reference', dict(mode='reference', referenceDatasetId=temp['id'], offsetSeconds=300), method='PATCH')
        viewed = self.request(f'/workspaces/{wid}/explore', dict(signalIds=ids))
        self.assertEqual(len(viewed['axes']), 1)
        self.assertEqual(viewed['axes'][0]['id'], 'utc')
        p = next(s for s in viewed['series'] if s['signal']['datasetId'] == pressure['id'])
        self.assertEqual(p['nativeTimes'][0], 0)
        self.assertEqual(p['times'][0], epoch.timestamp()+300)
        quality = self.request(f'/datasets/{pressure["id"]}/quality')
        self.assertEqual(quality['gapCount'], 1)
        self.assertGreater(quality['irregularCount'], 0)
        cursor = self.request(f'/workspaces/{wid}/cursor', dict(signalIds=ids, at=epoch.timestamp()+302, axisId='utc'))
        statuses = {s['signalId']: s for s in cursor['samples']}
        self.assertEqual(statuses[ids[1]]['status'], 'missing')
        self.assertAlmostEqual(statuses[ids[2]]['nativeTime'], 2.1)
        gap = self.request(f'/workspaces/{wid}/cursor', dict(signalIds=ids, at=epoch.timestamp()+340, axisId='utc'))
        self.assertEqual(next(s for s in gap['samples'] if s['signalId'] == ids[2])['status'], 'gap')
        stopped = self.request(f'/workspaces/{wid}/cursor', dict(signalIds=ids, at=epoch.timestamp()+550, axisId='utc'))
        self.assertEqual(next(s for s in stopped['samples'] if s['signalId'] == ids[1])['status'], 'outside')
        saved = self.request(f'/workspaces/{wid}/views', dict(name='Motor comparison', signalIds=ids, windows={'utc':dict(start=epoch.timestamp()+280, end=epoch.timestamp()+480, at=epoch.timestamp()+340)}, displayMode='separate'), expected=201)
        analysis = self.request(f'/workspaces/{wid}/analyses', dict(datasetId=temp['id'], signals=['temp_C'], algorithm='robust-maxz', baselineRange=[0, 199], analysisRange=[200, 599]), expected=201)
        self.assertTrue(analysis['intervals'])
        incident = self.request(f'/workspaces/{wid}/incidents', dict(title='Motor event', start_time=400, end_time=460, source=dict(kind='interval', datasetId=temp['id'], analysisId=analysis['id'], intervalIndex=0)), expected=201)
        self.stop(); self.start()
        self.assertEqual(self.request(f'/workspaces/{wid}/views')['views'][0], saved)
        restored = self.request(f'/workspaces/{wid}/signals')['signals']
        self.assertEqual({s['id'] for s in restored}, set(ids))
        self.assertEqual({s['device'] for s in restored}, {'Motor A'})
        self.assertEqual(self.request(f'/datasets/{pressure["id"]}/time-reference')['offset'], epoch.timestamp()+300)
        timeline = self.request(f'/incidents/{incident["id"]}/timeline')
        self.assertEqual(timeline['primaryAxisId'], 'utc')
        url = f'http://127.0.0.1:{self.service.server_port}/api/incidents/{incident["id"]}/report.html'
        with build_opener(ProxyHandler({})).open(url) as response:
            report = response.read().decode()
        self.assertIn('Motor temperature (°C)', report)
        self.assertEqual(self.request('/analyses/' + analysis['id'])['config']['signals'], ['temp_C'])

    def test_reference_chains_cycles_cross_workspace_and_view_validation(self):
        wid, other = self.workspace(), self.workspace('Other workspace')
        a, b, c = [self.import_csv(wid, name, 't,x\n0,1\n1,2\n2,3\n') for name in ('a', 'b', 'c')]
        foreign = self.import_csv(other, 'foreign', 't,x\n0,4\n1,5\n')
        self.request(f'/datasets/{b["id"]}/time-reference', dict(mode='reference', referenceDatasetId=a['id'], offsetSeconds=20), method='PATCH')
        clock = self.request(f'/datasets/{c["id"]}/time-reference', dict(mode='reference', referenceDatasetId=b['id'], offsetSeconds=-5), method='PATCH')
        self.assertEqual(clock['offset'], 15)
        for target in (c, foreign):
            self.request(f'/datasets/{a["id"]}/time-reference', dict(mode='reference', referenceDatasetId=target['id'], offsetSeconds=0), method='PATCH', expected=400)
        self.request(f'/datasets/{a["id"]}/time-reference', dict(mode='utc', utcOrigin='2026-10-24T08:00:00'), method='PATCH', expected=400)
        self.request(f'/datasets/{a["id"]}/time-reference', dict(mode='utc', utcOrigin='2026-10-24T08:00:00+08:00', offsetSeconds=0), method='PATCH')
        self.assertEqual(self.request(f'/datasets/{c["id"]}/time-reference')['axisId'], 'utc')
        foreign_signal = foreign['metadata']['columns'][0]['id']
        self.request(f'/workspaces/{wid}/explore', dict(signalIds=[foreign_signal]), expected=400)
        self.request(f'/workspaces/{wid}/views', dict(name='Bad window', signalIds=[a['metadata']['columns'][0]['id']], windows={'utc':dict(start=10, end=0)}), expected=400)
        self.request('/signals/' + a['metadata']['columns'][0]['id'], dict(name='changed-column'), method='PATCH', expected=400)

    def test_simulation_saved_output_uses_same_catalog_quality_explorer_and_restores_tools(self):
        wid = self.workspace()
        session = self.request('/simulations', dict(workspaceId=wid, title='Pump experiment', config=dict(duration=120, start=30, step=1, seed=19)), expected=201)
        saved = self.request(f'/simulations/{session["id"]}/save', dict(workspaceId=wid))
        dataset_id = saved['id']
        signals = self.request(f'/workspaces/{wid}/signals')['signals']
        self.assertEqual(len(signals), 18)
        self.assertTrue(all(s['simulationId'] == session['id'] and s['unit'] for s in signals))
        self.assertEqual(self.request(f'/datasets/{dataset_id}/quality')['invalidTimeCount'], 0)
        view = self.request(f'/workspaces/{wid}/explore', dict(signalIds=[s['id'] for s in signals[:3]]))
        self.assertEqual(view['axes'][0]['id'], 'simulation:' + session['id'])
        tools = self.request(f'/simulations/{session["id"]}/tools', dict(asOf=93, windowStart=0, calls=[dict(tool='inspect_signal_window', args=dict(signal='temperature'))]))
        self.assertEqual(tools['kind'], 'tools')
        self.stop(); self.start()
        self.assertEqual(len(self.request(f'/simulations/{session["id"]}/runs')['runs']), 1)
        self.assertEqual(self.request(f'/simulations/{session["id"]}')['datasetId'], dataset_id)


if __name__ == '__main__':
    unittest.main()
