"""Offline format fixtures and independent-dataset leakage/state regressions.

All numeric fixtures here are generated, not published TEP evaluation results.
The opt-in external workflow exercises the checksum-pinned original files.
"""
import gzip
import copy
import hashlib
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from benchmarks.rieth_stream import COLUMNS, read_selected
from l5.analysis import ALGORITHMS, build_monitor
from l5.independent import fit_detector, score_detector
from l5.tep_import import PROFILES, SOURCES, prepare_runs
from l5.workspace import WorkspaceStore
from test_experiments import finish
from l5.experiment_reports import render_experiment_report


def r_fixture(path, *, samples=80, keys=((0, 1), (0, 2)), names=COLUMNS, object_name='fault_free_training'):
    """Minimal literal RDX2 data.frame matching the supported public format."""
    integer = lambda v: struct.pack('>i', v)
    char = lambda s: integer(9)+integer(len(s.encode()))+s.encode()
    symbol = lambda s: integer(1)+char(s)
    strings = lambda ss: integer(16)+integer(len(ss))+b''.join(char(s) for s in ss)
    rng = np.random.default_rng(44)
    data = np.column_stack(([f for f, _ in keys for _ in range(samples)], [r for _, r in keys for _ in range(samples)],
        np.tile(np.arange(1, samples+1), len(keys)), rng.normal(size=(samples*len(keys), 52))))
    stream = b'RDX2\nX\n'+integer(2)+integer(197379)+integer(131840)+integer(1026)+symbol(object_name)+integer(787)+integer(55)
    for col in data.T:
        stream += integer(14)+integer(len(col))+np.asarray(col, dtype='>f8').tobytes()
    stream += integer(1026)+symbol('names')+strings(names)
    stream += integer(1026)+symbol('class')+strings(['data.frame'])+integer(254)+integer(254)
    path.write_bytes(gzip.compress(stream))
    return data


def csv_fixture(values, *, names=('a', 'b', 'c'), interval=180):
    return ','.join(('t', *names))+'\n'+'\n'.join(','.join(map(str, [i*interval, *row])) for i, row in enumerate(values))


class StreamTests(unittest.TestCase):
    def test_published_real_result_retains_protocol_sources_and_negative_outcomes(self):
        from examples.tep.verify import verify
        from examples.tep.run import require_fixed_protocol
        report = json.loads((Path(__file__).resolve().parents[1]/'examples/tep/results.json').read_text(encoding='utf-8'))
        self.assertTrue(verify(report))
        faulty = copy.deepcopy(report)
        faulty['sourceFiles'] = {}
        with self.assertRaisesRegex(ValueError, 'three official'):
            verify(faulty)
        faulty = copy.deepcopy(report)
        faulty['tasks'][0]['externalRun'] = 'unrelated-run'
        with self.assertRaisesRegex(ValueError, 'predeclared'):
            verify(faulty)
        with self.assertRaisesRegex(ValueError, 'case-study protocol'):
            require_fixed_protocol(dict(snapshot=dict(config={})))
        weak = [t for t in report['tasks'] if '-f03-' in t['externalRun']]
        self.assertEqual(sum(t['metrics']['labelled']['event']['missedEvents'] for t in weak), 17)

    def test_selection_keeps_identity_sample_order_and_exact_52_features(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'fixture.RData'
            data = r_fixture(path, keys=((1, 1), (1, 2), (3, 1)), object_name='faulty_testing')
            result = read_selected(path, [(1, 2), (3, 1)], object_name='faulty_testing', samples_per_run=80)
            np.testing.assert_array_equal(result[(1, 2)], data[80:160, 3:])
            np.testing.assert_array_equal(result[(3, 1)], data[160:, 3:])
            self.assertEqual(result[(1, 2)].shape, (80, 52))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                read_selected(path, [(2, 1)], object_name='faulty_testing', samples_per_run=80)
            with self.assertRaisesRegex(ValueError, 'distinct'):
                read_selected(path, [(1, 1), (1, 1)], object_name='faulty_testing', samples_per_run=80)

    def test_corrupt_truncated_wrong_object_and_reordered_columns_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'fixture.RData'
            r_fixture(path)
            with self.assertRaisesRegex(ValueError, 'object mismatch'):
                read_selected(path, [(0, 1)], object_name='faulty_testing', samples_per_run=80)
            raw = path.read_bytes()
            path.write_bytes(raw[:-25])
            with self.assertRaises(ValueError):
                read_selected(path, [(0, 1)], object_name='fault_free_training', samples_per_run=80)
            r_fixture(path, names=(*COLUMNS[:3], *reversed(COLUMNS[3:])))
            with self.assertRaisesRegex(ValueError, 'column names/order'):
                read_selected(path, [(0, 1)], object_name='fault_free_training', samples_per_run=80)

    def test_verified_preparation_import_labels_provenance_and_corrupt_cache(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = 'faulty-testing'
            filename = PROFILES[profile][0]
            path = root/filename
            values = r_fixture(path, samples=960, keys=((1, 1),), object_name='faulty_testing')
            # A known generated fixture has its own pin; production pins are unchanged.
            pin = dict(id=0, persistentId='doi:10.7910/DVN/6C3JR1/TEST-FIXTURE', filesize=path.stat().st_size,
                       checksum=dict(type='MD5', value=hashlib.md5(path.read_bytes()).hexdigest()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            with patch.dict(SOURCES['files'], {filename: pin}):
                manifest = prepare_runs(root, root/'cache', profile, [(1, 1)])
                store = WorkspaceStore(root/'workspace')
                store.tep.cache = root/'cache'
                wid = store.create_workspace('Generated offline format test')['id']
                run_id = manifest['runs'][0]['id']
                dataset = store.tep.import_runs(wid, dict(sourceId=profile, runIds=[run_id]))['datasets'][0]
                _, array = store.load_data(dataset)
                np.testing.assert_array_equal(array, values[:, 3:])
                external = dataset['metadata']['external']
                self.assertEqual(external['faultOnsetSample'], 161)
                self.assertEqual(external['faultOnsetSeconds'], 28800)
                self.assertEqual(len(dataset['metadata']['columns']), 52)
                self.assertEqual(external['originalColumns'], list(COLUMNS))
                labels = store.experiments.label_sets(dataset['id'])[0]
                self.assertEqual(labels['intervals'][0]['end'], 28620)
                self.assertEqual(labels['intervals'][1]['start'], 28800)
                (root/'cache'/f'{run_id}.npz').write_bytes(b'broken')
                with self.assertRaisesRegex(ValueError, 'corrupt'):
                    store.tep.preview(dict(sourceId=profile, runIds=[run_id]))
                path.write_bytes(path.read_bytes()[:-1])
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    prepare_runs(root, root/'cache', profile, [(1, 1)])


class IndependentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = WorkspaceStore(self.root)
        self.wid = self.store.create_workspace('Independent generated fixtures')['id']
        rng = np.random.default_rng(1729)
        self.sources = [self.store.import_dataset(self.wid, dict(csv=csv_fixture(rng.normal(size=(90, 3))), timeColumn='t', name=f'fixture-{i}')) for i in range(4)]
        self.config = dict(datasetId=self.sources[2]['id'], signals=['a', 'b', 'c'], analysisRange=[0, 16020], baselineRange=[0,16020],
            training=dict(fit=dict(datasetId=self.sources[0]['id'], range=[0,16020]), calibration=dict(datasetId=self.sources[1]['id'], range=[0,16020])),
            alpha=.01, minCoverage=.9, persistence=3, observationPolicy='measured', requiredSignals=[])

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_nine_models_reused_and_temporal_sequences_reset(self):
        for algorithm in ALGORITHMS:
            config = {**self.config, 'algorithm': algorithm}
            with self.subTest(algorithm=algorithm):
                model = fit_detector(self.store, self.wid, config)
                first = score_detector(self.store, self.wid, config, model)
                other = {**config, 'datasetId': self.sources[3]['id']}
                score_detector(self.store, self.wid, other, model)
                second = score_detector(self.store, self.wid, config, model)
                self.assertEqual(first['scores'], second['scores'])
                self.assertEqual(first['states'], second['states'])
                self.assertEqual(first['signalContributions'], second['signalContributions'])
                self.assertEqual(first['threshold'], second['threshold'])

    def test_fitting_never_reads_test_values_and_schema_mapping_is_by_name(self):
        config = {**self.config, 'algorithm': 'pca-q'}
        original = self.store.load_data
        reads = []
        def tracked(dataset):
            reads.append(dataset['id'])
            self.assertNotIn(dataset['id'], [s['id'] for s in self.sources[2:]])
            return original(dataset)
        with patch.object(self.store, 'load_data', side_effect=tracked):
            model = fit_detector(self.store, self.wid, config)
        self.assertEqual(reads, [s['id'] for s in self.sources[:2]])
        times, values = original(self.sources[2])
        permuted = self.store.import_dataset(self.wid, dict(csv=csv_fixture(values[:, [2,0,1]], names=('c','a','b')), timeColumn='t'))
        first = score_detector(self.store, self.wid, config, model)
        reordered = score_detector(self.store, self.wid, {**config, 'datasetId':permuted['id']}, model)
        np.testing.assert_array_equal(first['scores'], reordered['scores'])
        with self.assertRaisesRegex(ValueError, 'one-to-one'):
            score_detector(self.store, self.wid, {**config, 'signalMapping':{'a':'b','b':'b','c':'c'}}, model)

    def test_batch_snapshots_multiple_tests_labels_reuse_and_history(self):
        config = {**self.config, 'algorithms':[dict(algorithm=a) for a in ALGORITHMS], 'testDatasets':[
            dict(datasetId=s['id'], analysisRange=[0,16020]) for s in self.sources[2:]]}
        experiment = self.store.experiments.save(self.wid, dict(name='Independent nine-algorithm fixture', config=config))
        with patch('l5.independent.build_monitor', wraps=build_monitor) as build:
            run = finish(self.store.experiments, self.store.experiments.execute(experiment['id'], {})['id'])
            self.assertEqual(build.call_count, 9)
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(len(run['tasks']), 18)
        self.assertEqual(len(run['snapshot']['datasets']), 4)
        self.assertIn('l5/independent.py', run['snapshot']['engine']['sourceHashes'])
        self.assertEqual(len({t['metrics']['training']['modelKey'] for t in run['tasks']}), 9)
        hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.json')}
        reopened = WorkspaceStore(self.root)
        self.assertEqual(reopened.experiments.run(run['id']), run)
        self.assertEqual(hashes, {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.json')})
        report = render_experiment_report(reopened, experiment['id'])
        self.assertIn('Frozen normal training', report)
        self.assertIn('fixture-3', report)
        self.assertNotIn('Published fault onset', report, 'Unlabelled generic datasets do not acquire TEP truth.')

    def test_independence_overlap_temporal_cadence_and_abstention(self):
        with self.assertRaisesRegex(ValueError, 'independent'):
            self.store.analyze(self.wid, {**self.config, 'algorithm':'ewma','datasetId':self.sources[0]['id']})
        bad = {**self.config, 'training': {**self.config['training'], 'calibration': self.config['training']['fit']}}
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            fit_detector(self.store, self.wid, {**bad, 'algorithm':'ewma'})
        times, values = self.store.load_data(self.sources[2])
        values[20:24] = np.nan
        missing = self.store.import_dataset(self.wid, dict(csv=csv_fixture(values), timeColumn='t'))
        config = {**self.config, 'algorithm':'ewma'}
        model = fit_detector(self.store, self.wid, config)
        result = score_detector(self.store, self.wid, {**config, 'datasetId':missing['id']}, model)
        self.assertEqual(result['states'][20:24], ['abstain']*4)
        self.assertEqual(result['summary']['abstainedSamples'], 4)
        slower = self.store.import_dataset(self.wid, dict(csv=csv_fixture(values, interval=360), timeColumn='t'))
        with self.assertRaisesRegex(ValueError, 'sampling interval'):
            score_detector(self.store, self.wid, {**config, 'datasetId':slower['id'], 'analysisRange':[0,32040]}, model)

    def test_snapshot_rejects_changed_input_and_unknown_labels_remain_unknown(self):
        labels = self.store.experiments.save_labels(self.sources[2]['id'], dict(timeBasis='dataset-seconds', timeSource='Generated reviewed fixture only',
            intervals=[dict(kind='anomaly', start=3600, end=5400)]))
        config = {**self.config, 'algorithms':[dict(algorithm='robust-maxz')], 'testDatasets':[
            dict(datasetId=self.sources[2]['id'], analysisRange=[0,16020], labelSetId=labels['id'])]}
        experiment = self.store.experiments.save(self.wid, dict(name='Explicit partial truth', config=config))
        run = finish(self.store.experiments, self.store.experiments.execute(experiment['id'], {})['id'])
        sample = run['tasks'][0]['metrics']['labelled']['sample']
        self.assertEqual(sample['unlabelledSamples'], 79)
        self.assertIsNone(sample['falseAlarmRate'])
        self.store.experiments.save_labels(self.sources[2]['id'], dict(timeBasis='dataset-seconds', timeSource='Later review',
            intervals=[dict(kind='normal', start=0, end=16020)]))
        self.assertEqual(self.store.experiments.run(run['id']), run, 'New label versions do not revise historical metrics.')
        with patch.object(self.store.experiments, '_drain'):
            queued = self.store.experiments.execute(experiment['id'], {})
        self.store.experiments.working = False
        folder = self.root/self.wid/'datasets'/self.sources[0]['id']
        with (folder/'series.npz').open('ab') as out:
            out.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'content changed'):
            self.store.experiments._perform(queued['id'])


if __name__ == '__main__':
    unittest.main()
