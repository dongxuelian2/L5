"""Closed-loop process integration across persistence, statistics and control."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch

import numpy as np
from scipy.integrate import solve_ivp

from l5.industrial_study import CHANNELS, diagnose, study
from l5.plant_runs import ACTIVE
from l5.plants import SCENARIOS
from l5.reports import render_report
from l5.workspace import WorkspaceStore
from simulation import cstr
from simulation.tep import executable, simulate


class CoolingStudy(unittest.TestCase):
    def test_onset_search_uses_only_observations_through_cutoff(self):
        times = np.arange(0, 5400, 180)
        ages = np.arange(-5400, 5400, 180)
        reference = np.maximum(ages[:, None], 0) / 180
        observed = np.maximum(times[:, None] - 1440, 0) / 180
        observed[times >= 2880] = -100
        for alarm in (1620, 2160):
            result = diagnose(times, observed, alarm, {'ramp': (ages, reference)}, [0.], np.eye(1), 720)
            self.assertEqual(result['hypothesis'], 'ramp')
            self.assertEqual(result['estimatedOnsets']['ramp'], 1440)
            self.assertEqual(result['distances']['ramp'], 0.)
            self.assertEqual(result['cutoff'], alarm + 540)

    def test_matched_intervention_and_workspace_reuse(self):
        with TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory))
            self.addCleanup(store.close)
            wid = store.create_workspace('Cooling study')['id']
            first = study(store, wid, 'measurements')
            with patch('l5.industrial_study.simulate', side_effect=ValueError('simulation failed')):
                with self.assertRaisesRegex(ValueError, 'simulation failed'):
                    study(store, wid, 'investigation')
            self.assertEqual(study(store, wid)['datasets'], first['datasets'])
            with patch.object(store.incidents, 'create', side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    study(store, wid, 'investigation')
            analysis_id = store.jobs(wid)[0]['id']
            result = study(store, wid, 'investigation')
            self.assertEqual(result['analysisId'], analysis_id)
            self.assertEqual(first['datasets']['evaluation'], result['datasets']['evaluation'])
            report = result['report']
            baseline = report['sources']['evaluation']
            self.assertAlmostEqual(baseline['initialPressureKPaGauge'], 2705, places=3)
            self.assertLess(baseline['componentBalanceMaxLbmolPerHour'], 1e-9)
            self.assertEqual(report['detection']['windows']['1800']['detectedEvents'], 1)
            self.assertLess(report['signatureDistances']['reactor-reference'], report['signatureDistances']['condenser-reference'])
            def series(role):
                return store.load_data(store.dataset(result['datasets'][role]))[1]
            x = series('evaluation')
            y = series('intervention')
            np.testing.assert_array_equal(x[:160], y[:160])
            self.assertLess(report['comparison']['intervention']['coolingValveTravel'],
                            report['comparison']['evaluation']['coolingValveTravel'])
            repeat, _ = simulate(executable(store.root / 'tep-build')[0], 4, baseline['seed'])
            np.testing.assert_allclose(repeat[:, 1:], x, rtol=1e-13)
            self.assertEqual(result['datasets'], study(store, wid)['datasets'])

            analysis = store.result(result['analysisId'])
            model = analysis['model']
            delta = x[:, np.array(CHANNELS)-1] - model['center']
            scores = np.einsum('ij,ij->i', delta, np.linalg.solve(model['covariance'], delta.T).T)
            np.testing.assert_allclose(analysis['scores'], scores)
            self.assertEqual(analysis['config']['industrialStudy']['sources'], result['datasets'])
            self.assertEqual(analysis['experiment']['runId'], result['runId'])
            self.assertEqual(report['diagnosis']['hypothesis'], 'reactor-reference')
            self.assertEqual(report['diagnosis']['cutoff'], analysis['summary']['firstDetection'] + 3420)
            self.assertIn('RMS whitened residual', render_report(store, result['incidentId']))
            edited = store.experiments.get(result['experimentId'])['config']
            edited['persistence'] = 3
            store.experiments.save(wid, dict(config=edited), result['experimentId'])
            source = store.root / wid / 'datasets' / result['datasets']['evaluation'] / 'series.npz'
            self.assertFalse(source.with_name('source.csv').exists())
            original_bytes = source.read_bytes()
            source.unlink()
            self.assertNotIn('evaluation', study(store, wid)['datasets'])
            restored = study(store, wid, 'investigation')
            self.assertEqual(restored, result)
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(len(store.jobs(wid)), 1)
            self.assertEqual(len(store.experiments.list(wid)), 1)
            self.assertEqual(len(store.incidents.list(wid)), 1)
            store.close()
            reopened = WorkspaceStore(Path(directory))
            try:
                self.assertEqual(study(reopened, wid), result)
            finally:
                reopened.close()

    def test_condenser_scenario_and_incremental_reference_driver(self):
        with TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory))
            self.addCleanup(store.close)
            wid = store.create_workspace('Condenser study')['id']
            binary, _ = executable(store.root / 'tep-build')
            ticks = []
            states = []
            config = dict(duration=21600, onset=7200, intervention_at=8100)
            control, _ = simulate(binary, 5, 5658678765, .5, gain_loop=11, states=states,
                                  observe=lambda row: ticks.append(row[0]), **config)
            baseline, audit = simulate(binary, 5, 5658678765, **config)
            normal, _ = simulate(binary, 0, 5658678765, **config)
            np.testing.assert_array_equal(ticks, baseline[:, 0])
            self.assertEqual(np.asarray(states).shape, (120, 50))
            np.testing.assert_array_equal(baseline[:40], normal[:40])
            np.testing.assert_array_equal(control[:45], baseline[:45])
            self.assertGreater(np.max(abs(control[45:, 52] - baseline[45:, 52])), .01)
            self.assertLess(audit['componentBalanceMaxLbmolPerHour'], 1e-9)
            half_step, _ = simulate(binary, 5, 5658678765, subdivisions=2, **config)
            # Refinement changes the noise draw sequence. Compare operating means.
            self.assertLess(abs(half_step[40:, 7].mean() - baseline[40:, 7].mean()), 5)
            result = study(store, wid, 'investigation', scenario=SCENARIOS['condenser-cooling'],
                           config=dict(durationSeconds=21600, onsetSeconds=7200, interventionSeconds=8100))
            self.assertEqual(result['report']['diagnosis']['hypothesis'], 'condenser-reference')
            self.assertEqual(result['report']['detection']['events'][0]['delay'], 360.)


class CascadeStudy(unittest.TestCase):
    def test_published_equilibrium_and_independent_energy_species_solution(self):
        initial = cstr.initial_state()
        np.testing.assert_allclose(initial[:3], [877.25294608097, 122.74705391903, 324.475443431599],
                                   rtol=0, atol=2e-8)
        np.testing.assert_allclose(cstr.derivative(initial, cstr.FEED, [300, 300]), 0, atol=1e-11)
        a, b, c = cstr.linearization(initial)
        self.assertLess(max(np.linalg.eigvals(a).real), 0)
        a *= 60
        self.assertEqual(np.linalg.matrix_rank(np.hstack([np.linalg.matrix_power(a, k) @ b for k in range(6)])), 4)
        self.assertEqual(np.linalg.matrix_rank(np.vstack([c @ np.linalg.matrix_power(a, k) for k in range(6)])), 4)

        # Independent conserved coordinates. N stores total moles, Y stores moles of B,
        # and H stores sensible energy plus the chemical energy remaining in A.
        volume, cv, h = .1, 239000., 50000.
        capacity = volume * cv
        def to_inventory(values):
            a, b, temp = values.reshape(2, 3).T
            return np.column_stack((volume*(a+b), volume*b, capacity*temp+h*volume*a)).ravel()

        def from_inventory(values):
            n, y, e = values.reshape(2, 3).T
            return np.column_stack(((n-y)/volume, y/volume, (e-h*(n-y))/capacity)).ravel()

        feed = to_inventory(np.array([1000, 0, 356] * 2))[:3]
        def balances(_, flat):
            state = from_inventory(flat)
            current = flat.reshape(2, 3)
            upstream = np.vstack((feed, current[0]))
            result = (upstream - current) / 60
            result[:, 1] += (current[:, 0] - current[:, 1]) * 1.2e9 * np.exp(-8750 / state[2::3])
            result[:, 2] += (50000 / 60) * (300 - state[2::3])
            return result.ravel()

        settings = dict(duration=1200, onset=400, intervention_at=460)
        reference_t = np.arange(400, 1201, 10)
        reference = solve_ivp(balances, (400, 1200), to_inventory(initial), t_eval=reference_t,
                              method='DOP853', rtol=1e-12, atol=1e-11)
        self.assertTrue(reference.success)
        expected = np.stack([from_inventory(x) for x in reference.y.T])
        _, _, actual = cstr.simulate('warm-feed', 659, **settings)
        _, _, finer = cstr.simulate('warm-feed', 659, step=1, **settings)
        _, _, coarser = cstr.simulate('warm-feed', 659, step=2, **settings)
        np.testing.assert_allclose(actual[40:], expected, rtol=0, atol=8e-6)
        np.testing.assert_array_equal(actual, finer)
        self.assertGreater(np.max(abs(coarser[40:] - expected)), 8 * np.max(abs(actual[40:] - expected)))
        np.testing.assert_allclose(actual[:, 0::3] + actual[:, 1::3], 1000, rtol=0, atol=5e-12)

    def test_live_prefix_cancel_resume_and_saved_report(self):
        with TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory))
            self.addCleanup(store.close)
            wid = store.create_workspace('Cascade study')['id']
            observed, resume = Event(), Event()
            original = cstr.simulate

            def paused(*args, **kwargs):
                progress = kwargs['observe']
                if progress:
                    def sample(row):
                        progress(row)
                        observed.set()
                        if not resume.wait(10):
                            raise AssertionError('Test must release the sample checkpoint.')
                    kwargs['observe'] = sample
                return original(*args, **kwargs)

            def finished(identity):
                deadline = monotonic() + 30
                while monotonic() < deadline:
                    run = store.plants.get(wid, identity)
                    if run['status'] not in ACTIVE:
                        return run
                    sleep(.03)
                self.fail('Plant did not complete before the deadline.')

            with patch('l5.industrial_study.cstr.simulate', side_effect=paused):
                selected = store.plants.start(wid, 'cstr-feed-warming', {})
                identity = selected['id']
                try:
                    self.assertTrue(observed.wait(10))
                    self.assertEqual(store.plants.preview(wid, identity)['times'], [0.])
                    self.assertEqual(store.plants.start(wid, 'cstr-feed-warming', {})['id'], identity)
                    store.plants.cancel(wid, identity)
                finally:
                    resume.set()
                self.assertEqual(finished(identity)['status'], 'cancelled')
            self.assertEqual(store.plants.start(wid, 'cstr-feed-warming', {})['id'], identity)
            result = finished(identity)
            self.assertEqual(result['status'], 'completed', result.get('error'))
            investigate = result['result']
            self.assertEqual(investigate['report']['diagnosis']['hypothesis'], 'warm-feed-reference')
            self.assertEqual(investigate['report']['detection']['events'][0]['delay'], 20.)
            self.assertEqual(len(store.datasets(wid)), 6)
            self.assertEqual(len(store.incidents.list(wid)), 1)
            self.assertIn('Jacket command travel', render_report(store, investigate['incidentId']))
            staged = store.plants.start(wid, 'cstr-feed-dilution', {}, 'measurements')
            preview = finished(staged['id'])
            self.assertEqual(preview['status'], 'measurements_ready')
            self.assertEqual(len(preview['result']['datasets']), 1)
            self.assertEqual(store.plants.start(wid, 'cstr-feed-dilution', {})['id'], staged['id'])
            lean = finished(staged['id'])
            self.assertEqual(lean['status'], 'completed', lean.get('error'))
            self.assertEqual(lean['result']['datasets']['evaluation'], preview['evaluationId'])
            self.assertEqual(lean['result']['report']['diagnosis']['hypothesis'], 'lean-feed-reference')
            store.close()
            reopened = WorkspaceStore(Path(directory))
            try:
                self.assertEqual(reopened.plants.get(wid, identity), result)
                self.assertEqual(len(reopened.plants.preview(wid, identity)['times']), 181)
                self.assertEqual(reopened.plants.start(wid, 'cstr-feed-warming', {})['id'], identity)
            finally:
                reopened.close()
