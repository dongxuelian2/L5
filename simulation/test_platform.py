import copy
import csv
import io
import json
import math
from pathlib import Path
import unittest

from simulation.platform import (Config, DURATION, KEYS, THRESHOLD, alarm_analysis,
                                 analyze_rows, diagnose, parse_csv, run_tools, simulate)


class InvestigationTests(unittest.TestCase):
    def test_diagnosis_is_blind_to_labels_and_row_metadata(self):
        rows=simulate(Config(fault='pump_loss'))
        labeled=[dict(row,scenario='pressure_bias',ground_truth='cooling_valve') for row in rows]
        self.assertEqual(diagnose(rows),diagnose(labeled))
        self.assertEqual(diagnose(rows)['candidates'][0]['id'],'pump_loss')

    def test_healthy_controls_do_not_raise_incidents(self):
        for noise in (.5,1,2):
            d=diagnose(simulate(Config(fault='healthy',noise=noise,operating=.6)))
            self.assertEqual(d['status'],'nominal')
            self.assertIsNone(d['firstDetection'])

    def test_partial_window_cannot_read_future_samples(self):
        rows=simulate(Config(start=100))
        self.assertEqual(diagnose(rows[:71])['status'],'nominal')
        self.assertIsNotNone(diagnose(rows)['firstDetection'])
        self.assertTrue(all(step['status']=='completed' for step in run_tools(rows[:71])))

    def test_physical_trip_does_not_follow_biased_pressure_sensor(self):
        c=Config(fault='pressure_bias',severity=2)
        self.assertGreater(max(r['pressure'] for r in simulate(c)),THRESHOLD)
        self.assertIsNone(simulate(c,compact=True)['trip'])
        self.assertEqual(diagnose(simulate(c))['candidates'][0]['id'],'pressure_bias')

    def test_frozen_sensor_is_not_trusted_as_process_evidence(self):
        d=diagnose(simulate(Config(fault='sensor_freeze')))
        self.assertEqual(d['health']['pressure']['status'],'frozen')
        self.assertFalse(d['health']['pressure']['usable'])
        self.assertEqual(d['candidates'][0]['id'],'sensor_freeze')
        self.assertTrue(all(not p['trusted'] for p in d['paths'] if 'pressure' in (p['source'],p['target'])))

    def test_missing_independent_sensor_removes_agreement_credit(self):
        rows=simulate(Config(fault='pressure_bias'))
        for row in rows: row['pressure_peer']=None
        d=diagnose(rows)
        c=next(c for c in d['candidates'] if c['id']=='pressure_bias')
        self.assertEqual(c['score'],0)
        self.assertTrue(c['unresolved'])
        self.assertEqual(d['health']['pressure_peer']['status'],'missing')

    def test_data_quality_rejects_invalid_time_and_nonfinite(self):
        rows=simulate(Config())
        for mutate in (lambda r:r[5].update(t=4),lambda r:r[5].update(flow=math.nan),lambda r:r[5].update(t=True)):
            changed=copy.deepcopy(rows);mutate(changed)
            with self.assertRaises(ValueError): diagnose(changed)

    def test_missing_and_irregular_samples_are_visible(self):
        rows=simulate(Config());rows.pop(70)
        for r in rows[-8:]:r['flow']=None
        d=diagnose(rows)
        self.assertFalse(d['clock']['regular'])
        self.assertEqual(d['health']['flow']['status'],'stale')
        self.assertEqual(d['health']['flow']['freshness'],8)

    def test_interventions_preserve_pre_action_prefix(self):
        c=Config();base=simulate(c)
        for action in ('bypass','backup_pump','shutdown','combined'):
            self.assertEqual(simulate(c,action,90)[:90],base[:90])

    def test_generated_recovery_boundary_is_safe_and_next_second_is_not(self):
        artifact=json.loads((Path(__file__).parents[1]/'src/data/platform.json').read_text())
        case=artifact['cases'][0];config=Config(**case['fit']['parameters'])
        for action in case['recovery']['actions']:
            latest=action['latest']
            if latest is not None:
                self.assertIsNone(simulate(config,action['id'],latest,compact=True)['trip'])
                if latest<DURATION:
                    self.assertIsNotNone(simulate(config,action['id'],latest+1,compact=True)['trip'])
            self.assertEqual(len(action['trials']),221)
        self.assertEqual(case['recovery']['evaluated'],1547)

    def test_generated_observation_analysis_matches_engine(self):
        artifact=json.loads((Path(__file__).parents[1]/'src/data/platform.json').read_text())
        for case in artifact['cases']:
            self.assertEqual(case['diagnosis'],diagnose(case['rows']))
            for snapshot in case['snapshots']:
                prefix=[r for r in case['rows'] if r['t']<=snapshot['time']]
                self.assertEqual(snapshot['diagnosis'],diagnose(prefix))

    def test_alarm_events_preserve_returns_and_reannunciations(self):
        rows=simulate(Config(fault='healthy'))
        for i in range(50,80):rows[i]['flow']=50
        a=alarm_analysis(rows)
        self.assertEqual(a['uniqueConditions'],1)
        self.assertEqual(a['eventCount'],11)  # one activation, nine repeats, one return
        self.assertEqual(a['reannunciations'],9)
        self.assertEqual(a['rationalization'][0]['repeats'],9)
        self.assertEqual(a['events'][-1]['kind'],'return')
        self.assertEqual(a['conditions'][0]['duration'],30)

    def test_csv_roundtrip_and_validation(self):
        rows=simulate(Config());stream=io.StringIO()
        writer=csv.DictWriter(stream,fieldnames=['t',*KEYS]);writer.writeheader();writer.writerows(rows)
        parsed=parse_csv(stream.getvalue())
        self.assertEqual(diagnose(parsed),diagnose(rows))
        for text in ('nonsense\n1','t,unknown\n0,1','t,pressure\n0,nan'):
            with self.assertRaises(ValueError):parse_csv(text)

    def test_structured_tools_are_allowlisted_and_preserve_values(self):
        rows=simulate(Config())
        calls=[{'tool':'inspect_signal_window','args':{'signal':'valve'}},{'tool':'compare_hypotheses','args':{}}]
        trace=run_tools(rows,calls)
        self.assertEqual(trace[0]['result']['samples'][-1]['value'],rows[-1]['valve'])
        self.assertEqual(trace[1]['result'][0]['id'],'cooling_valve')
        for calls in ([{'tool':'run_shell'}],[{'tool':'inspect_signal_window','args':{'signal':'unknown'}}],[{'tool':'compare_hypotheses','args':{'groundTruth':'pump_loss'}}]):
            with self.assertRaises(ValueError):run_tools(rows,calls)


if __name__=='__main__':unittest.main()
