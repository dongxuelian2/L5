"""Numerical invariants, competing faults and durable HTTP investigation."""
from copy import deepcopy
import json
import unittest

import numpy as np

from l5.models import resolve
from l5.models.tanks import integrate
from l5.sensor_health import diagnose
from l5.sensor_health_tanks import PARAMETERS, ROLES
from l5.reports import render_report
from test_incidents import IncidentHTTPFixture


def tank(kind='healthy', **changes):
    c = resolve('coupled-tanks').validate(dict(fault=kind, duration=160, start=60, seed=17, **changes))
    rows = integrate(c)[0]
    names = list(ROLES)
    return np.asarray([r['t'] for r in rows]), np.asarray([[r[s] for s in names] for r in rows]), names


def config(names):
    return dict(signals=names, baselineRange=[0, 30], analysisRange=[30.2, 160],
        model=dict(kind='coupled-tanks', mapping={s:s for s in names}, parameters=PARAMETERS.copy()))


class NumericalHealthTests(unittest.TestCase):
    def test_competing_sensor_pump_valve_and_leak_explanations(self):
        for kind, category in [('sensor_bias', 'sensor'), ('pump_degradation', 'process'), ('valve_restriction', 'process'), ('tank_leak', 'process')]:
            with self.subTest(kind=kind):
                t, y, names = tank(kind)
                result = diagnose(t, y, names, config(names))
                episode = max(result['episodes'], key=lambda e:e['samples'])
                self.assertEqual(episode['assessment'], category)
                leader = episode['candidates'][0]
                self.assertTrue(leader['key'].startswith('level2_') if kind == 'sensor_bias' else leader['key'] == kind)
                self.assertGreater(leader['improvement'], .4)
                self.assertGreater(len(episode['candidates']), 5)
                self.assertGreaterEqual(episode['detectedAt'], 60)
                json.dumps(result, allow_nan=False)

    def test_integrity_checks_and_explicit_relationship_find_real_injections(self):
        rng = np.random.default_rng(17)
        t = np.arange(700, dtype=float)
        y = rng.normal(0, .05, (700, 2))
        y[:, 1] += y[:, 0]
        y[220:260, 0] += 2
        y[280:330, 0] += np.linspace(0, 2, 50)
        y[350:390, 0] = 1
        y[430, 0] = 3
        y[470:480, 0] = np.nan
        y[530:620, 0] += rng.normal(0, 1, 90)
        c = dict(signals=['a', 'b'], baselineRange=[0, 199], analysisRange=[200, 699], relationships=[dict(kind='agreement', target='a', predictor='b')])
        r = diagnose(t, y, ['a', 'b'], c)
        for kind, when in [('level_shift', 250), ('drift', 310), ('stuck', 380), ('spike', 430), ('dropout', 475), ('noise', 580), ('relationship', 250)]:
            self.assertTrue(any(v['kind'] == kind and any(s['start'] <= when <= s['end'] for s in v['intervals']) for v in r['indicators']), kind)
        spike = next(v for v in r['indicators'] if v['kind'] == 'spike' and v['signals'] == ['a'])
        event = next(s for s in spike['intervals'] if s['start'] == 430)
        self.assertEqual(event['detectedAt'], 431)
        self.assertTrue(all(e['assessment'] == 'insufficient_evidence' for e in r['episodes']))

    def test_reference_and_hydraulics_do_not_use_target_labels_or_future(self):
        t, y, names = tank('sensor_bias')
        c = config(names)
        before = deepcopy(c)
        r = diagnose(t, y, names, c)
        changed = y.copy(); changed[t >= 80, 1] += 3
        other = diagnose(t, changed, names, c)
        self.assertEqual(r['reference'], other['reference'])
        self.assertEqual([i['threshold'] for i in r['indicators']], [i['threshold'] for i in other['indicators']])
        self.assertEqual(c, before)
        limited = {**c, 'analysisRange':[30.2, 79.8]}
        self.assertEqual(diagnose(t, y, names, limited), diagnose(t, changed, names, limited))
        with self.assertRaises(ValueError):
            diagnose(t, y, names, {**c, 'model': {**c['model'], 'parameters': {**PARAMETERS, 'fault':'sensor_bias'}}})
        shifted = {**c, 'baselineRange':[10, 40], 'analysisRange':[40.2, 160]}
        original = diagnose(t, y, names, shifted)
        adversarial = y.copy(); adversarial[t < 10] *= 100
        other = diagnose(t, adversarial, names, shifted)
        self.assertEqual([i['threshold'] for i in original['indicators']], [i['threshold'] for i in other['indicators']])

    def test_missing_processed_and_acquisition_gaps_abstain_without_interpolation(self):
        t, y, names = tank('sensor_bias')
        mask = np.ones_like(y, dtype=bool); mask[(t>=60)&(t<=90), 3] = False
        result = diagnose(t, y, names, config(names), observed=mask)
        physical = result['physical']
        pos = result['times'].index(70.)
        self.assertEqual(physical['states'][pos], 'insufficient_evidence')
        self.assertIsNone(physical['expected']['level2'][pos])
        self.assertIsNone(physical['residuals'][2]['values'][pos])
        keep = (t < 80) | (t > 90)
        gap = diagnose(t[keep], y[keep], names, config(names))
        self.assertTrue(any(w['code'] == 'acquisition_gaps' for w in gap['warnings']))
        intervals = [s for i in gap['indicators'] for s in i['intervals']]
        self.assertFalse(any(s['start'] < 80 and s['end'] > 90 for s in intervals))

    def test_no_stuck_claim_from_constant_reference_and_invalid_ranges_fail(self):
        t = np.arange(300, dtype=float); y = np.ones((300, 1))
        c = dict(signals=['x'], baselineRange=[0, 149], analysisRange=[150, 299])
        r = diagnose(t, y, ['x'], c)
        self.assertFalse(any(i['kind'] == 'stuck' for i in r['indicators']))
        self.assertEqual(r['episodes'], [])
        for change in [dict(window=True), dict(z=float('nan')), dict(analysisRange=[100, 299]), dict(signals=[{}]), dict(baselineRange=[0, 10])]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                diagnose(t, y, ['x'], {**c, **change})
        with self.assertRaises(ValueError):
            diagnose(np.zeros(300), y, ['x'], c)

    def test_linear_relationship_separates_common_process_changes_from_disagreement(self):
        t = np.arange(500, dtype=float)
        x = np.sin(t/20)
        y = np.column_stack([x, 2*x+4])
        y[250:, 0] += 3; y[250:, 1] += 6
        c = dict(signals=['a', 'b'], baselineRange=[0, 199], analysisRange=[200, 499],
            relationships=[dict(kind='linear', target='b', predictor='a')])
        coherent = diagnose(t, y, ['a', 'b'], c)
        self.assertFalse(next(i for i in coherent['indicators'] if i['kind'] == 'relationship')['intervals'])
        y[300:, 1] += 2
        inconsistent = diagnose(t, y, ['a', 'b'], c)
        self.assertTrue(next(i for i in inconsistent['indicators'] if i['kind'] == 'relationship')['intervals'])


class SensorHealthHTTPTests(IncidentHTTPFixture):
    def test_saved_simulation_diagnosis_incident_timeline_report_and_restart(self):
        wid = self.workspace('Sensor investigation')
        session = self.request('/simulations', dict(workspaceId=wid, modelId='coupled-tanks', config=dict(fault='tank_leak', seed=17, start=60, duration=160)), expected=201)
        dataset = self.request(f'/simulations/{session["id"]}/save', dict(workspaceId=wid))
        model = self.request(f'/datasets/{dataset["id"]}/sensor-model')['model']
        self.assertEqual(set(model['parameters']), set(PARAMETERS))
        self.assertNotIn('fault', json.dumps(model))
        # Explicit unit metadata must agree with the equations' SI inputs.
        level_id = next(s['id'] for s in dataset['metadata']['columns'] if s['name'] == 'level2')
        self.request(f'/signals/{level_id}', dict(unit='cm'), method='PATCH')
        self.request(f'/workspaces/{wid}/sensor-health', dict(datasetId=dataset['id'], **config(list(ROLES))), expected=400)
        self.request(f'/signals/{level_id}', dict(unit='m'), method='PATCH')
        c = config(list(ROLES))
        result = self.request(f'/workspaces/{wid}/sensor-health', dict(datasetId=dataset['id'], **c), expected=201)
        index = max(range(len(result['episodes'])), key=lambda i:result['episodes'][i]['samples'])
        incident = self.request(f'/workspaces/{wid}/incidents', dict(title='Check tank loss'), expected=201)
        source = dict(kind='sensor-health', diagnosticId=result['id'], episodeIndex=index)
        linked = self.request(f'/incidents/{incident["id"]}/links', source, expected=201)
        self.assertEqual(linked['links'][0]['details']['episode'], result['episodes'][index])
        self.request(f'/incidents/{incident["id"]}/links', source, expected=201)
        timeline = self.request(f'/incidents/{incident["id"]}/timeline')
        self.assertTrue(any(e['id'].startswith('sensor-health:') for e in timeline['events']))
        report = render_report(self.service.workspace_store, incident['id'], locale='en')
        self.assertIn('Tank 1 leak', report)
        self.assertIn(result['sourceDigest'], report)
        chinese = render_report(self.service.workspace_store, incident['id'], locale='zh-CN')
        self.assertIn('传感器健康', chinese)
        self.stop(); self.start()
        self.assertEqual(self.request(f'/sensor-health/{result["id"]}'), result)
        history = self.request(f'/workspaces/{wid}/sensor-health')['diagnostics']
        self.assertEqual(history[0]['id'], result['id'])
        self.assertEqual(len(self.request(f'/incidents/{incident["id"]}')['links']), 1)
        other = self.workspace('Other')
        self.request(f'/workspaces/{other}/sensor-health', dict(datasetId=dataset['id'], **c), expected=400)
        foreign = self.request(f'/workspaces/{other}/incidents', dict(title='Foreign'), expected=201)
        self.request(f'/incidents/{foreign["id"]}/links', source, expected=400)
        self.request(f'/incidents/{incident["id"]}/links', {**source, 'episodeIndex':999}, expected=400)
