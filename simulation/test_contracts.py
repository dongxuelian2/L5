import copy
import unittest
from unittest.mock import patch

from l5.contracts import ObservationBatch, Signal, SignalSchema, TEP_CLASSIC_SCHEMA, TEP_MULTIMODE_SCHEMA
from simulation.platform import (ACTIONS, BASELINE, DURATION, THRESHOLD, Config, SYNTHETIC_SCHEMA,
                                 alarm_analysis, analyze_rows, diagnose, fit_hypothesis, interventions, parse_csv, simulate)


class EvidenceContractTests(unittest.TestCase):
    def test_source_spaces_are_explicit_and_incompatible(self):
        for schema, width in ((SYNTHETIC_SCHEMA, 18), (TEP_CLASSIC_SCHEMA, 52), (TEP_MULTIMODE_SCHEMA, 53)):
            self.assertEqual(len(schema.signals), width)
        with self.assertRaises(ValueError): TEP_CLASSIC_SCHEMA.require_compatible(TEP_MULTIMODE_SCHEMA)
        self.assertTrue(all(s.unit is None and s.meaning is None for s in TEP_MULTIMODE_SCHEMA.signals))
        self.assertIsNone(TEP_MULTIMODE_SCHEMA.sample_interval_seconds)
        with self.assertRaises(ValueError): analyze_rows(simulate(Config()), schema_id=TEP_CLASSIC_SCHEMA.id)

    def test_missing_and_clock_validity_survive_the_contract(self):
        schema=SignalSchema('test','test source',(Signal('a'),Signal('b')),1)
        values=[[1,None],[2,3]]
        batch=ObservationBatch(schema,'run',(0,1),values)
        values[0][0]=99
        self.assertEqual(batch.values[0][0],1)
        self.assertEqual(batch.observed_mask,((True,False),(True,True)))
        with self.assertRaises(ValueError): batch.complete_values()
        for timestamps in ((0,0),(0,float('nan')),(0,'1')):
            with self.subTest(timestamps=timestamps), self.assertRaises(ValueError):
                ObservationBatch(schema,'run',timestamps,((1,2),(3,4)))

    def test_csv_width_duplicate_header_and_quoting_are_rejected(self):
        for text in ('t,pressure,pressure\n0,1,2','t,pressure\n0,1,2','t,pressure\n0','t,pressure\n0,"unfinished'):
            with self.subTest(text=text), self.assertRaises(ValueError): parse_csv(text)
        text='\ufefft,pressure\n'+'\n'.join(f'{i},2700' for i in range(25))
        rows=parse_csv(text)
        self.assertEqual(rows[0]['pressure'],2700)
        self.assertIsNone(rows[0]['flow'])

    def test_alarm_missing_interval_interrupts_state_without_claiming_return(self):
        rows=simulate(Config(fault='healthy'))
        for row in rows[50:80]: row['flow']=50
        for row in rows[70:75]: row['flow']=None
        alarms=alarm_analysis(rows)
        condition=next(c for c in alarms['conditions'] if c['signal']=='flow')
        self.assertEqual(condition['activations'],2)
        self.assertEqual(condition['duration'],25)
        self.assertFalse(any(70<=e['t']<75 for e in alarms['events']))
        self.assertEqual(next(g for g in alarms['observationGaps'] if g['condition']=='FI-101.LOW')['missingSamples'],5)
        for row in rows[75:]: row['flow']=None
        self.assertEqual(next(g for g in alarm_analysis(rows)['observationGaps'] if g['condition']=='FI-101.LOW')['state'],'abstain')

    def test_alarm_duration_uses_seconds_for_subsecond_records(self):
        rows=simulate(Config(fault='healthy'))
        for i,row in enumerate(rows): row['t']=i*.5
        for row in rows[50:80]: row['flow']=50
        condition=next(c for c in alarm_analysis(rows)['conditions'] if c['signal']=='flow')
        self.assertEqual(condition['duration'],15)


class DecisionBoundaryTests(unittest.TestCase):
    def test_fit_is_invariant_to_absolute_clock_origin(self):
        rows=simulate(Config())[:81]
        original=fit_hypothesis(rows,diagnose(rows))
        shifted=copy.deepcopy(rows)
        for row in shifted: row['t']+=1000.25
        self.assertEqual(fit_hypothesis(shifted,diagnose(shifted)),original)

    def test_fit_rejects_future_diagnosis_and_unsupported_cadence(self):
        rows=simulate(Config())
        with self.assertRaises(ValueError): fit_hypothesis(rows[:81],diagnose(rows))
        irregular=copy.deepcopy(rows[:81]); irregular[40]['t']+=.5
        with self.assertRaises(ValueError): fit_hypothesis(irregular,diagnose(irregular))
        missing=[{'t':i} for i in range(25)]
        with self.assertRaises(ValueError): fit_hypothesis(missing,diagnose(missing))

    def test_no_pressure_intervention_ranked_for_healthy_or_sensor_only_cases(self):
        for fault in ('healthy','pressure_bias','sensor_freeze'):
            with self.subTest(fault=fault):
                recovery=interventions(Config(fault=fault))
                self.assertIsNone(recovery['base']['trip'])
                self.assertEqual(recovery['status'],'baseline_below_pressure_limit')
                self.assertTrue(all(recovery[key] is None for key in ('safest','lowestLoss','latest')))
                self.assertTrue(all(action['latest'] is None for action in recovery['actions']))

    def test_search_includes_both_endpoints_and_uses_physical_trip(self):
        def fake(config,action=None,at=90,*,compact=False):
            safe=action is not None and at==DURATION
            return dict(peak=3050,physicalPeak=THRESHOLD-.001 if safe else THRESHOLD+.001,
                        trip=None if safe else 118,pressure=[2700]*241,productionLoss=0,qualityLoss=0,utilityCost=0)
        with patch('simulation.platform.simulate',side_effect=fake): recovery=interventions(Config())
        self.assertEqual(recovery['evaluated'],len(ACTIONS)*(DURATION-BASELINE+1))
        for action in recovery['actions']:
            self.assertEqual(action['trials'][0]['time'],BASELINE)
            self.assertEqual(action['latest'],DURATION)
            self.assertEqual(action['intervals'],[[DURATION,DURATION]])
            self.assertTrue(action['trials'][-1]['safe'])
            self.assertLess(action['trials'][-1]['physicalPeak'],THRESHOLD)

    def test_unknown_actions_and_fractional_action_times_fail_explicitly(self):
        for action,at in (('unknown',90),('bypass',90.5),('bypass',-1),('bypass',241)):
            with self.subTest(action=action,at=at),self.assertRaises(ValueError): simulate(Config(),action,at)


if __name__=='__main__': unittest.main()
