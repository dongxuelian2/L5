"""Study denominator, timing, cache isolation and saved-negative regressions."""
import copy
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from l5.analysis import build_monitor
from l5.experiment_evaluation import evaluate
from l5.tep_study import aggregate, identity, protocol_for, protocol_hash, validate_benchmark
from l5.workspace import WorkspaceStore
from test_experiments import finish
from test_external_tep import csv_fixture


class StudyMetricTests(unittest.TestCase):
    def test_saved_small_exports_retain_all_runs_methods_and_negative_outcomes(self):
        root = Path(__file__).resolve().parents[1]/'examples/tep'
        for kind, count in (('expanded',585),('robustness',1755)):
            with (root/f'{kind}_per_run.csv').open(encoding='utf-8',newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows),count)
            self.assertEqual(len({(r['configuration'],r['externalRun'],r['algorithm']) for r in rows}),count)
            self.assertEqual({r['status'] for r in rows},{'succeeded'})
            for configuration in {r['configuration'] for r in rows}:
                for algorithm in {r['algorithm'] for r in rows}:
                    group = [r for r in rows if r['configuration']==configuration and r['algorithm']==algorithm]
                    self.assertEqual(len(group),65)
                    self.assertEqual(len({r['fitId'] for r in group}),1)
                    self.assertEqual(len({r['threshold'] for r in group}),1)
                    self.assertEqual(sum(int(r['eventCount']) for r in group),60)
            weak = [r for r in rows if r['configuration']=='A' and r['faultNumber']=='3']
            self.assertEqual(sum(int(r['missedEvents']) for r in weak),26)
            self.assertEqual(sum(int(r['detected30m']) for r in weak),0)

    def test_gap_without_observations_and_truncated_follow_up_remain_visible(self):
        labels = dict(id='truth',version=1,source='generated',intervals=[dict(kind='anomaly',start=180,end=360),
            dict(kind='anomaly',start=720,end=1080,onset=540)])
        result = dict(times=[0,720,900],states=['normal','alarm','normal'],durationMs=0,relatedSignals=[])
        metrics = evaluate(result,labels)['detection']
        self.assertEqual(metrics['windows']['1800']['totalEvents'],2)
        self.assertEqual(metrics['windows']['1800']['unobservedEvents'],1)
        self.assertEqual(metrics['windows']['1800']['truncatedEvents'],2)
        self.assertEqual(metrics['events'][1]['delay'],180,'delay uses original onset, not the analysis sample')

    def test_exact_early_horizons_keep_missed_and_wholly_abstained_events(self):
        times = np.arange(0, 54000, 180).tolist()
        states = ['normal']*len(times)
        for index, time in enumerate(times):
            if 21600 <= time <= 36000:
                states[index] = 'abstain'
        states[times.index(1800)] = 'alarm'
        labels = dict(id='truth', version=1, source='generated', intervals=[
            dict(kind='anomaly',start=0,end=14400),
            dict(kind='anomaly',start=21600,end=36000),
            dict(kind='anomaly',start=39600,end=53820)])
        metrics = evaluate(dict(times=times, states=states, durationMs=0, relatedSignals=[]), labels)
        # Preserve the previous formal eligibility metric, while the new study
        # denominator includes the unobserved event and the observed miss.
        self.assertEqual(metrics['labelled']['event']['eligibleEvents'], 2)
        for key in ('1800','3600','14400','eventual'):
            window = metrics['detection']['windows'][key]
            self.assertEqual((window['detectedEvents'],window['totalEvents'],window['unobservedEvents']), (1,3,1))
            self.assertEqual(window['rate'],1/3)
        self.assertEqual([v['delay'] for v in metrics['detection']['events']], [1800,None,None])

    def test_native_tep_onset_and_no_pre_onset_early_detection(self):
        times = np.arange(960)*180
        states = np.full(960,'normal',dtype=object)
        states[159] = 'alarm'
        states[170] = 'alarm'  # Exactly 30 minutes after sample 161, inclusive.
        labels = dict(id='truth', version=1, source='generated', intervals=[dict(kind='normal',start=0,end=28620),
            dict(kind='anomaly',start=28800,end=172620,onset=28800)])
        result = dict(times=times.tolist(),states=states.tolist(),durationMs=0,relatedSignals=[])
        detection = evaluate(result,labels)['detection']
        self.assertEqual(detection['events'][0]['delay'],1800)
        self.assertEqual(detection['windows']['1800']['detectedEvents'],1)
        self.assertEqual(detection['preInjection']['alarmSamples'],1)
        self.assertEqual(detection['postInjection']['observedSamples'],800)
        states[170] = 'normal'
        states[171] = 'alarm'
        result['states'] = states.tolist()
        self.assertEqual(evaluate(result,labels)['detection']['windows']['1800']['detectedEvents'],0)

    def test_alarm_episode_duration_gaps_and_unknown_time(self):
        labels = dict(id='truth',version=1,source='generated',intervals=[dict(kind='normal',start=0,end=180),
            dict(kind='normal',start=360,end=1260),dict(kind='anomaly',start=1440,end=1620)])
        result = dict(times=[0,180,360,1080,1260,1440,1620],states=['alarm','alarm','alarm','alarm','abstain','normal','alarm'],durationMs=0,relatedSignals=[])
        metrics = evaluate(result,labels,gap_threshold=270)['detection']
        self.assertEqual(metrics['normal']['alarmSamples'],4)
        self.assertEqual(metrics['normal']['alarmEvents'],3)
        self.assertEqual(metrics['normal']['alarmDuration'],180)
        self.assertEqual(metrics['postInjection']['alarmFraction'],.5)
        self.assertIsNone(evaluate(result)['detection']['windows'])

    def test_batches_pool_with_status_and_training_isolation(self):
        result = dict(times=[0,180,360],states=['normal']*3,durationMs=1,relatedSignals=[])
        labels = dict(id='truth',version=1,source='fixture',intervals=[dict(kind='anomaly',start=0,end=360)])
        metrics = evaluate(result,labels)
        def task(config,batch,status='succeeded'):
            return dict(id=f'{config}-{batch}',run_id=f'batch{batch}',algorithm='robust-maxz',
                config=dict(algorithm='robust-maxz',alpha=.01,training={'fit':config}),
                benchmark=dict(configuration=config),external=dict(faultNumber=3),status=status,error='fixture' if status=='failed' else None,
                metrics=metrics if status=='succeeded' else None)
        cells = aggregate([task('A',1),task('A',2),task('A',3,'failed'),task('B',1)])
        self.assertEqual(len(cells),2)
        a = next(c for c in cells if c['configuration']=='A')
        self.assertEqual((a['plannedRuns'],a['succeeded'],a['failed'],a['unresolvedRuns']),(3,2,1,1))
        self.assertEqual(a['windows']['1800']['totalEvents'],3)
        self.assertEqual(a['windows']['1800']['unresolvedEvents'],1)
        self.assertEqual(a['delayDistribution']['missed'],2)
        self.assertIsNone(a['delay']['median'])

    def test_fixed_declarations_disjoint_training_and_batch_budget(self):
        expanded, robust = (protocol_for(f'rieth-{kind}-nine-v1') for kind in ('expanded','robustness'))
        self.assertEqual(expanded['tests'],robust['tests'])
        self.assertEqual(len(expanded['tests']),65)
        self.assertEqual({t['faultNumber'] for t in expanded['tests']},set(range(21)))
        self.assertEqual({s['simulationRun'] for g in robust['configurations'].values() for s in g.values()},set(range(1,7)))
        self.assertEqual(len({identity(t) for t in expanded['tests']}),65)
        self.assertEqual(expanded['algorithms'],json.loads((Path(__file__).resolve().parents[1]/'examples/tep/protocol.json').read_text())['algorithms'])
        meta = dict(studyId='a'*32,protocolId=robust['id'],protocolHash=protocol_hash(robust),configuration='B',batch=1,batches=3)
        self.assertEqual(validate_benchmark(meta),meta)
        with self.assertRaises(ValueError):
            validate_benchmark({**meta,'protocolHash':'wrong'})


class BatchCacheTests(unittest.TestCase):
    def test_same_frozen_training_reuses_one_fit_across_batches_changed_configuration_refits(self):
        with TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp))
            wid = store.create_workspace('Generated batch-cache regression')['id']
            rng = np.random.default_rng(44)
            datasets = [store.import_dataset(wid,dict(csv=csv_fixture(rng.normal(size=(90,3))),timeColumn='t',name=f'fixture{i}')) for i in range(4)]
            base = dict(signals=['a','b','c'],baselineRange=[0,16020],analysisRange=[0,16020],
                training=dict(fit=dict(datasetId=datasets[0]['id'],range=[0,16020]),calibration=dict(datasetId=datasets[1]['id'],range=[0,16020])),
                algorithms=[dict(algorithm='ewma')])
            runs = []
            with patch('l5.independent.build_monitor',wraps=build_monitor) as builder:
                for i,target in enumerate((2,3,2)):
                    config = {**base,'datasetId':datasets[target]['id']}
                    if i==2:
                        config['training'] = dict(fit=base['training']['calibration'],calibration=base['training']['fit'])
                    experiment = store.experiments.save(wid,dict(name=f'Batch {i}',config=config))
                    runs.append(finish(store.experiments,store.experiments.execute(experiment['id'],{})['id']))
                self.assertEqual(builder.call_count,2)
            training = [r['tasks'][0]['metrics']['training'] for r in runs]
            self.assertEqual(training[0]['fitId'],training[1]['fitId'])
            self.assertEqual(training[0]['threshold'],training[1]['threshold'])
            self.assertTrue(training[1]['reused'])
            self.assertNotEqual(training[1]['fitId'],training[2]['fitId'])


if __name__ == '__main__':
    unittest.main()
