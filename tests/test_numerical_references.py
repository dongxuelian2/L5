"""Deterministic reference cases for time, exposure, aggregation and simulation."""
import unittest
from types import SimpleNamespace

import numpy as np

from l5.analysis import run_analysis
from l5.estimation import measurement_update
from l5.estimation_workspace import EstimationService
from l5.models.tanks import validate_tank_measurements
from l5.prognostics import _first_passage
from l5.resampling import resample
from l5.control_solver import solve_qp
from l5.experiment_evaluation import evaluate
from l5.models.tanks import DEFAULTS, forecast_path, integrate
from l5.tep_study import aggregate
from simulation.platform import Config, simulate


def evaluation(times, states, intervals, gap=100):
    return evaluate(dict(times=times, states=states, durationMs=1, relatedSignals=[]),
                    dict(id='truth', version=1, source='fixture', intervals=intervals), gap)


class NumericalReferences(unittest.TestCase):
    def test_false_alarm_exposure(self):
        m = evaluation([0, 60, 120, 180, 240, 1800, 1860],
                       ['alarm', 'alarm', 'normal', 'abstain', 'alarm', 'alarm', 'normal'],
                       [dict(kind='normal', start=0, end=1860)])
        normal = m['detection']['normal']
        self.assertEqual((normal['alarmEvents'], normal['alarmDuration'], normal['observedSeconds']), (3, 60, 180))
        self.assertEqual(normal['episodesPerObservedHour'], 60)
        self.assertEqual(m['labelled']['sample']['falseAlarmRate'], 4/6)

    def test_event_denominators(self):
        m = evaluation([0, 1800, 1801, 4000], ['abstain', 'alarm', 'normal', 'abstain'],
                       [dict(kind='anomaly', start=0, end=1800),
                        dict(kind='normal', start=1801, end=1801),
                        dict(kind='anomaly', start=4000, end=4000)])
        task = dict(id='hit', config=dict(analysisRange=[0, 4000]), external=dict(faultNumber=1),
                    benchmark=dict(configuration='A'), algorithm='example', status='succeeded', metrics=m)
        cell, = aggregate([task, dict(task, id='pending', status='not-run', metrics=None)])
        self.assertEqual(cell['event']['recall'], 1)
        self.assertEqual(cell['windows']['1800']['rate'], .5)
        self.assertEqual(cell['windows']['1800']['unresolvedEvents'], 1)
        self.assertEqual(cell['delayDistribution']['missed'], 0)
        self.assertEqual(cell['windows']['1800']['unobservedEvents'], 1)
        self.assertIsNone(m['detection']['normal']['episodesPerObservedHour'])

    def test_delayed_observation(self):
        m = evaluation([2000, 2400], ['normal', 'alarm'],
                       [dict(kind='anomaly', start=2000, onset=0, end=4000)])
        d = m['detection']
        self.assertEqual(d['events'][0]['delay'], 2400)
        self.assertEqual(d['windows']['1800']['unobservedEvents'], 1)
        self.assertEqual(d['windows']['3600']['detectedEvents'], 1)
        self.assertEqual(d['windows']['eventual']['truncatedEvents'], 1)

    def test_decision_resets_across_gap(self):
        times = np.r_[np.arange(104), 200, 201, 202]
        values = np.r_[np.tile([-1., 1.], 50), np.full(7, 10.)][:, None]
        r = run_analysis(times, values, ['x'], dict(algorithm='robust-maxz', signals=['x'],
            baselineRange=[0, 99], analysisRange=[100, 202], persistence=3))
        self.assertEqual([(i['start'], i['end']) for i in r['intervals']], [(102, 103), (202, 202)])

    def test_closed_form_drain(self):
        errors = []
        for dt in (.25, .125, .0625):
            config = dict(DEFAULTS, initial1=0., initial2=1., pumpRate=0., connection=0.,
                          integrationStep=dt, step=1., duration=10.)
            _, states = integrate(config)
            # A dh/dt = -k sqrt(h), positive branch.
            exact = (1 - config['outlet'] * 10 / (2 * config['area2']))**2
            errors.append(abs(states[-1]['level2'] - exact))
            self.assertLess(max(abs(row['massResidual']) for row in states), 1e-12)
        self.assertTrue(all(3.9 < a/b < 4.1 for a, b in zip(errors, errors[1:])))

    def test_stop_ramp_effort(self):
        c = dict(DEFAULTS, duration=4., step=2.)
        p = dict(rampSeconds=1.)
        rows, states = integrate(c, 'stop_supply', 0., p, include_at=True)
        effort = forecast_path(c, rows, states, 0., 'stop_supply', p)['metrics']['controlEffort']
        self.assertEqual(effort, 350)  # Triangle over 1 s plus 3 s at 100 percentage points.

    def test_initial_state_and_off_clock_fault(self):
        c = Config(fault='reaction_rate', start=.5, duration=2., step=1., noise=0)
        rows = simulate(c)
        self.assertEqual(rows[0]['temperature'], 120)
        self.assertAlmostEqual(rows[1]['temperature'], 120 + 10 * .5 / 33, places=4)
        self.assertEqual([r['temperature'] for r in rows], [r['temperature_peer'] for r in rows])

    def test_sample_scores(self):
        m = evaluation(list(range(8)), ['alarm', 'normal', 'normal', 'abstain',
                       'alarm', 'normal', 'alarm', 'alarm'],
                       [dict(kind='normal', start=0, end=3), dict(kind='anomaly', start=4, end=6)])
        sample = m['labelled']['sample']
        self.assertEqual([sample[k] for k in ('TP', 'FP', 'TN', 'FN')], [2, 1, 2, 1])
        for key in ('precision', 'recall', 'f1'):
            self.assertEqual(sample[key], 2/3)
        self.assertEqual(sample['unlabelledSamples'], 1)
        self.assertEqual(sample['labelledAbstainedSamples'], 1)

    def test_scalar_measurement_and_rul(self):
        x, cov, _, _, nis = measurement_update(np.zeros(2), np.eye(2), [2], [0], np.eye(2))
        np.testing.assert_allclose(x, [1, 0])
        np.testing.assert_allclose(cov, np.diag([.5, 1]))
        self.assertAlmostEqual(nis, 2)
        gaps = np.array([0., 6., 6.])
        hits = _first_passage(gaps, np.array([0., 2., -1.]), np.zeros(3), np.random.default_rng(1))
        np.testing.assert_equal(hits, [0, 3, np.inf])

    def test_interpolation_lineage(self):
        result, codes, measured = resample(np.array([0., 2., 10.]), np.array([0., 4., 20.]),
            np.ones(3, dtype=bool), np.array([0., 1., 5.]), method='linear', interval=1, max_gap=3)
        np.testing.assert_equal(result, [0, 2, np.nan])
        np.testing.assert_equal(codes, [1, 2, 0])
        np.testing.assert_equal(measured, [True, False, False])

    def test_model_and_unit_compatibility(self):
        tep = dict(id='tep', metadata=dict(external=dict(kind='tep-rieth')))
        derived = dict(id='derived', metadata=dict(transformation=dict(sources=[dict(datasetId='tep')])))
        with self.assertRaisesRegex(ValueError, 'coupled-tank'):
            validate_tank_measurements(SimpleNamespace(dataset=lambda _: tep), derived)
        tank = dict(id='tank', workspace_id='ws', metadata=dict(columns=[dict(name='signal', unit='kPa')]))
        service = SimpleNamespace(store=SimpleNamespace(dataset=lambda _: tank))
        with self.assertRaisesRegex(ValueError, 'requires m'):
            EstimationService.dataset_observations(service, 'ws', dict(datasetId='tank', mapping=dict(level1='signal')), 0)

    def test_qp_bound(self):
        solved = solve_qp([[2]], [-4], [[1]], [0], [1])
        self.assertAlmostEqual(solved['x'][0], 1)
        with self.assertRaises(ValueError):
            solve_qp([[2]], [-4], [[1]], [np.nan], [1])
