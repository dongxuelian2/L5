"""Persisted experiment workflow, explicit evaluation and real HTTP restart."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

import numpy as np

from l5.analysis import ALGORITHMS
from l5.experiment_evaluation import evaluate, validate_intervals
from l5.experiment_reports import render_experiment_report
from l5.experiments import MAX_TASKS
from l5.workspace import WorkspaceStore
from test_incidents import IncidentHTTPFixture


def csv_data(irregular=False):
    rng = np.random.default_rng(44)
    values = rng.normal(size=(600, 3))
    values[400:460, 0] += 9
    return 't,a,b,c\n' + '\n'.join(','.join(map(str, [i + (.1 if irregular and i == 350 else 0), *row])) for i, row in enumerate(values))


def config(dataset_id, algorithms=None):
    return dict(datasetId=dataset_id, signals=['a', 'b', 'c'], baselineRange=[0, 199], analysisRange=[200, 599],
                algorithms=algorithms or [dict(algorithm=algorithm) for algorithm in ALGORITHMS])


def finish(service, identity):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = service.run(identity)
        if run['status'] not in ('queued', 'running'):
            # The terminal row commits before the worker closes its final queue
            # connection. Let it release Windows WAL handles before temp cleanup.
            while service.working and time.monotonic() < deadline:
                time.sleep(.001)
            return run
        time.sleep(.01)
    raise AssertionError('Experiment worker did not finish in 30 seconds.')


class EvaluationTests(unittest.TestCase):
    def test_sample_event_unknown_abstain_and_gap_rules(self):
        result = dict(times=list(range(8)), states=['normal', 'alarm', 'alarm', 'abstain', 'normal', 'alarm', 'normal', 'abstain'],
                      durationMs=3, relatedSignals=['a'])
        labels = dict(id='labels', version=1, source='manual', intervals=[
            dict(kind='normal', start=0, end=1), dict(kind='anomaly', start=3, end=5), dict(kind='anomaly', start=7, end=7)])
        metrics = evaluate(result, labels)
        self.assertEqual(metrics['behavior']['alarmSamples'], 3)
        sample, event = metrics['labelled']['sample'], metrics['labelled']['event']
        self.assertEqual([sample[k] for k in ('TP', 'FP', 'TN', 'FN')], [1, 1, 1, 1])
        self.assertEqual(sample['unlabelledSamples'], 2)
        self.assertEqual(sample['labelledAbstainedSamples'], 2)
        self.assertEqual(sample['f1'], .5)
        self.assertEqual([event[k] for k in ('detectedEvents', 'missedEvents', 'unobservedEvents', 'falseAlarmEvents')], [1, 0, 1, 1])
        self.assertEqual(event['firstDetectionDelay'], 2)
        self.assertIsNone(evaluate(result)['labelled'])
        gaps = evaluate(dict(times=[0, 1, 20, 21], states=['alarm']*4, durationMs=1, relatedSignals=[]), gap_threshold=2)
        self.assertEqual(gaps['behavior']['alarmDuration'], 2)
        self.assertEqual(gaps['behavior']['alarmIntervalCount'], 2)

    def test_closed_labels_and_undefined_metrics(self):
        with self.assertRaises(ValueError):
            validate_intervals([dict(kind='normal', start=0, end=2), dict(kind='anomaly', start=2, end=3)], [0, 4])
        result = dict(times=[1], states=['abstain'], durationMs=1, relatedSignals=[])
        labels = dict(id='x', version=1, source='manual', intervals=[dict(kind='anomaly', start=0, end=2, onset=-2)])
        evaluated = evaluate(result, labels)['labelled']
        self.assertIsNone(evaluated['sample']['precision'])
        self.assertIsNone(evaluated['sample']['recall'])
        self.assertEqual(evaluated['event']['unobservedEvents'], 1)
        result['states'] = ['alarm']
        self.assertEqual(evaluate(result, labels)['labelled']['event']['firstDetectionDelay'], 3)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WorkspaceStore(Path(self.temp.name))
        self.wid = self.store.create_workspace('Research')['id']
        self.dataset = self.store.import_dataset(self.wid, dict(csv=csv_data(), timeColumn='t', timeKind='numeric'))
        self.service = self.store.experiments

    def save(self, raw=None):
        return self.service.save(self.wid, dict(name='Nine algorithms', config=raw or config(self.dataset['id'])))

    def test_nine_algorithms_snapshot_labels_comparison_report_restart(self):
        labels = self.service.save_labels(self.dataset['id'], dict(name='Reviewed labels', timeBasis='dataset-seconds',
            timeSource='Reviewed event log', intervals=[dict(kind='normal', start=200, end=399), dict(kind='anomaly', start=400, end=459)]))
        experiment = self.save({**config(self.dataset['id']), 'labelSetId': labels['id']})
        run = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        self.assertEqual(run['status'], 'completed', [task['error'] for task in run['tasks']])
        self.assertEqual(len({task['result_id'] for task in run['tasks']}), 9)
        self.assertEqual(run['snapshot']['labels']['id'], labels['id'])
        for task in run['tasks']:
            result = self.store.result(task['result_id'])
            self.assertEqual(result['experiment']['taskId'], task['id'])
            self.assertIsNotNone(task['metrics']['labelled'])
        comparison = self.service.comparison(experiment['id'], dict(taskIds=[t['id'] for t in run['tasks']]))
        self.assertTrue(comparison['groups'][0]['matchingWindows'])
        self.assertEqual(len(comparison['analyses']), 9)
        self.assertEqual(len(comparison['groups'][0]['agreement']), 36)
        self.service.save(self.wid, dict(notes='<script>test</script>', conclusion='PCA comparison', conclusion_run_ids=[run['id']]), experiment['id'])
        report = render_experiment_report(self.store, experiment['id'])
        self.assertIn('<svg', report)
        self.assertIn('PCA comparison', report)
        self.assertIn('&lt;script&gt;test&lt;/script&gt;', report)
        self.assertNotIn('<script>test', report)
        self.assertIn(run['snapshot']['dataset']['sha256'], report)
        self.assertIn('Sample evaluation', report)
        reopened = WorkspaceStore(Path(self.temp.name)).experiments
        self.assertEqual(reopened.run(run['id']), run)
        self.assertEqual(reopened.get(experiment['id'])['conclusion_run_ids'], [run['id']])
        reopened.save(self.wid, dict(conclusion='Later conclusion', conclusion_run_ids=[]), experiment['id'])
        records = reopened.get(experiment['id'])['records']
        self.assertEqual(records[1]['conclusion'], 'PCA comparison')
        self.assertEqual(records[1]['run_ids'], [run['id']])

    def test_study_limits_copy_edit_history_and_label_versions(self):
        raw = config(self.dataset['id'], [dict(algorithm='pca-q', study=dict(variance=[.6, .8, .95], alpha=[.01, .05]))])
        experiment = self.save(raw)
        self.assertEqual(self.service.preview(self.wid, raw)['taskCount'], 6)
        run = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        edited = self.service.save(self.wid, dict(config=config(self.dataset['id'], [dict(algorithm='ewma')])), experiment['id'])
        second = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        self.assertNotEqual(run['id'], second['id'])
        self.assertEqual(self.service.run(run['id']), run)
        self.assertGreater(edited['revision'], experiment['revision'])
        duplicate = self.service.copy(experiment['id'])
        self.assertNotEqual(duplicate['id'], experiment['id'])
        self.assertEqual(duplicate['runs'], [])
        too_large = config(self.dataset['id'], [dict(algorithm='dpca-q', study=dict(lags=list(range(1, 9)), variance=[.5+i*.01 for i in range(8)], alpha=[.01, .02]))])
        with self.assertRaisesRegex(ValueError, str(MAX_TASKS)):
            self.service.preview(self.wid, too_large)
        with self.assertRaises(ValueError):
            self.service.save(self.wid, dict(revision=1, name='stale'), experiment['id'])

    def test_partial_failure_and_retry_keep_original_inputs(self):
        dataset = self.store.import_dataset(self.wid, dict(csv=csv_data(True), timeColumn='t', timeKind='numeric'))
        experiment = self.save(config(dataset['id'], [dict(algorithm='robust-maxz'), dict(algorithm='ewma')]))
        run = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        self.assertEqual(run['status'], 'partial')
        self.assertEqual([t['status'] for t in run['tasks']], ['succeeded', 'failed'])
        self.assertIn('regular', run['tasks'][1]['error'])
        self.service.save(self.wid, dict(config=config(self.dataset['id'], [dict(algorithm='pca-q')])), experiment['id'])
        retry = finish(self.service, self.service.execute(experiment['id'], dict(retryRunId=run['id']))['id'])
        self.assertEqual(retry['snapshot'], run['snapshot'])
        self.assertEqual(retry['tasks'][0]['algorithm'], 'ewma')
        self.assertEqual(self.service.run(run['id']), run)

    def test_workspace_read_snapshot_does_not_block_batch_commits(self):
        experiment = self.save(config(self.dataset['id'], [dict(algorithm='robust-maxz'), dict(algorithm='pca-q')]))
        with self.store.connect() as reader:
            reader.execute('BEGIN')
            reader.execute('SELECT * FROM datasets').fetchall()
            run = self.service.execute(experiment['id'], {})
            finished = finish(self.service, run['id'])
            self.assertEqual(finished['status'], 'completed', [task['error'] for task in finished['tasks']])
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0, 'the open reader keeps its own stable snapshot')
        self.assertEqual(len(self.store.jobs(self.wid)), 2)

    def test_cross_workspace_validation_and_incident_lineage(self):
        experiment = self.save(config(self.dataset['id'], [dict(algorithm='robust-maxz'), dict(algorithm='pca-q')]))
        run = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        incident = self.service.link_incident(run['id'], dict(taskIds=[t['id'] for t in run['tasks']], intervals={run['tasks'][0]['id']:0}))
        self.assertEqual(len(incident['links']), 2)
        self.assertTrue(all(link['details']['experiment']['runId'] == run['id'] for link in incident['links']))
        other = self.store.create_workspace('Other')['id']
        other_incident = self.store.incidents.create(other, dict(title='Other'))
        with self.assertRaises(ValueError):
            self.service.link_incident(run['id'], dict(taskIds=[run['tasks'][0]['id']], incidentId=other_incident['id']))
        with self.assertRaises(ValueError):
            self.service.save(other, dict(name='Invalid', config=config(self.dataset['id'])))

    def test_restart_marks_unfinished_and_retains_successful_tasks(self):
        experiment = self.save(config(self.dataset['id'], [dict(algorithm='robust-maxz')]))
        run = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        with self.store.connect() as db:
            db.execute("UPDATE experiment_runs SET status='running' WHERE id=?", (run['id'],))
            db.execute("INSERT INTO experiment_tasks(id,run_id,ordinal,algorithm,config,status) VALUES ('pending',?,1,'ewma',?,'queued')", (run['id'], json.dumps({**run['tasks'][0]['config'], 'algorithm':'ewma'})))
        reopened = WorkspaceStore(Path(self.temp.name)).experiments
        interrupted = reopened.run(run['id'])
        self.assertEqual(interrupted['status'], 'interrupted')
        self.assertEqual(interrupted['tasks'][0], run['tasks'][0])
        self.assertEqual(interrupted['tasks'][1]['status'], 'interrupted')
        retry = finish(reopened, reopened.execute(experiment['id'], dict(retryRunId=run['id']))['id'])
        self.assertEqual(retry['status'], 'completed')
        self.assertEqual(len(retry['tasks']), 1)

    def test_derived_observation_policy_and_original_lineage_survive_reruns(self):
        signal = next(s for s in self.store.signals.catalog(self.wid) if s['datasetId'] == self.dataset['id'] and s['name'] == 'a')
        transform = self.store.transformations.save(self.wid, dict(name='Half-second grid', config=dict(version=1,
            sources=[dict(signalId=signal['id'], key='a', resampling='linear', maxGapSeconds=2, missing={'method':'keep'}, duplicatePolicy='mean')],
            derived=[], grid=dict(mode='intersection', intervalSeconds=.5))))
        derived = self.store.transformations.execute(transform['id'], {})
        raw = config(derived['id'], [dict(algorithm='robust-maxz'), dict(algorithm='ewma')])
        raw['signals'] = ['a']
        experiment = self.save(raw)
        measured = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        self.assertEqual(measured['status'], 'partial')
        self.assertLess(measured['tasks'][0]['metrics']['behavior']['coverageFraction'], .51)
        self.assertIn('fully observed baseline', measured['tasks'][1]['error'])
        self.service.save(self.wid, dict(config={**raw, 'observationPolicy':'processed'}), experiment['id'])
        processed = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        self.assertEqual(processed['status'], 'completed')
        self.assertEqual(processed['tasks'][0]['metrics']['behavior']['coverageFraction'], 1)
        incident = self.service.link_incident(processed['id'], dict(taskIds=[processed['tasks'][0]['id']], intervals={processed['tasks'][0]['id']:0}))
        self.assertEqual([link['kind'] for link in incident['links']], ['interval'])
        from l5.reports import render_report
        report = render_report(self.store, incident['id'])
        self.assertIn('来源分析实验', report)
        self.assertIn(transform['id'], render_experiment_report(self.store, experiment['id']))
        self.assertEqual(self.service.run(measured['id']), measured)

    def test_triplens_known_truth_and_derived_clock_mapping(self):
        session = self.store.runtime.create(dict(workspaceId=self.wid, config=dict(fault='cooling_valve', start=43.7, duration=150, step=.2, seed=7)))
        dataset = self.store.runtime.save(session['id'], dict(workspaceId=self.wid))
        labels = self.service.triplens_labels(dataset['id'], {})
        anomaly = next(i for i in labels['intervals'] if i['kind'] == 'anomaly')
        self.assertAlmostEqual(anomaly['start'], 43.7)
        self.assertEqual(labels['source'], 'triplens-simulation')
        raw = dict(datasetId=dataset['id'], signals=['flow', 'pressure', 'pump'], baselineRange=[0, 19.8], analysisRange=[20, 150],
            labelSetId=labels['id'], algorithms=[dict(algorithm='robust-maxz'), dict(algorithm='ewma')])
        experiment = self.save(raw)
        run = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['tasks'][0]['metrics']['labelled']['event']['eligibleEvents'], 1)
        signal = next(s for s in self.store.signals.catalog(self.wid) if s['datasetId'] == dataset['id'] and s['name'] == 'flow')
        transform = self.store.transformations.save(self.wid, dict(name='TripLens crop', config=dict(version=1,
            sources=[dict(signalId=signal['id'], key='flow', resampling='nearest', maxGapSeconds=1, missing={'method':'keep'}, duplicatePolicy='mean')],
            derived=[], grid=dict(mode='custom', start=10, end=100, intervalSeconds=.2, axisId=signal['clock']['axisId']))))
        derived = self.store.transformations.execute(transform['id'], {})
        derived_labels = self.service.triplens_labels(derived['id'], {})
        anomaly = next(i for i in derived_labels['intervals'] if i['kind'] == 'anomaly')
        self.assertAlmostEqual(anomaly['start'], 33.7)
        self.assertEqual(derived_labels['provenance']['simulationId'], session['id'])

    def test_label_versions_and_mismatched_comparison_windows(self):
        body = dict(timeBasis='dataset-seconds', timeSource='Reviewed event log', intervals=[dict(kind='anomaly', start=400, end=459)])
        labels = self.service.save_labels(self.dataset['id'], body)
        raw = {**config(self.dataset['id'], [dict(algorithm='robust-maxz')]), 'labelSetId':labels['id']}
        experiment = self.save(raw)
        first = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        latest = self.service.save_labels(self.dataset['id'], {**body, 'intervals':[dict(kind='normal', start=200, end=399)]})
        self.assertEqual(latest['version'], 2)
        self.service.save(self.wid, dict(config={**raw, 'labelSetId':latest['id'], 'analysisRange':[250,599]}), experiment['id'])
        second = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        comparison = self.service.comparison(experiment['id'], dict(taskIds=[first['tasks'][0]['id'], second['tasks'][0]['id']]))
        self.assertFalse(comparison['groups'][0]['matchingWindows'])
        self.assertEqual(self.service.run(first['id'])['snapshot']['labels']['id'], labels['id'])
        self.store.signals.set_reference(self.dataset['id'], dict(mode='utc', utcOrigin='2026-10-24T00:00:00Z', offsetSeconds=0))
        third = finish(self.service, self.service.execute(experiment['id'], {})['id'])
        comparison = self.service.comparison(experiment['id'], dict(taskIds=[first['tasks'][0]['id'], third['tasks'][0]['id']]))
        self.assertEqual(len(comparison['groups']), 2, 'historical clock snapshots must not be rewritten by new time references')


class ExperimentHTTPTests(IncidentHTTPFixture):
    def test_http_labels_progress_report_and_restart(self):
        wid = self.workspace('HTTP research')
        dataset = self.request(f'/workspaces/{wid}/datasets', dict(csv=csv_data(), timeColumn='t', timeKind='numeric'), expected=201)
        labels = self.request(f'/datasets/{dataset["id"]}/labels', dict(timeBasis='dataset-seconds', timeSource='Reviewed native clock',
            intervals=[dict(kind='normal', start=200, end=399), dict(kind='anomaly', start=400, end=459)]), expected=201)
        experiment = self.request(f'/workspaces/{wid}/experiments', dict(name='HTTP study', config={**config(dataset['id']), 'labelSetId':labels['id']}), expected=201)
        run = self.request(f'/experiments/{experiment["id"]}/runs', {}, expected=202)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            run = self.request('/experiment-runs/' + run['id'])
            if run['status'] not in ('queued', 'running'):
                break
            time.sleep(.02)
        self.assertEqual(run['status'], 'completed')
        self.stop()
        self.start()
        self.assertEqual(self.request('/experiment-runs/' + run['id']), run)
        self.assertEqual(self.request(f'/datasets/{dataset["id"]}/labels')['labels'][0]['id'], labels['id'])
        self.assertEqual(len(self.request(f'/workspaces/{wid}/experiments')['experiments']), 1)
        copied = self.request(f'/experiments/{experiment["id"]}/copy', {}, expected=201)
        self.assertNotEqual(copied['id'], experiment['id'])


if __name__ == '__main__':
    unittest.main()
