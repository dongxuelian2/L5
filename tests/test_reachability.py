"""Independent finite references and coupled-tank recovery integration checks."""
from functools import lru_cache
from itertools import combinations, product
import math
from pathlib import Path
import unittest
from urllib.request import build_opener, ProxyHandler

import numpy as np

from l5.reachability import Study, margin, physical_step, predecessor, reach, validate, viability
from l5.recovery_reports import render
from l5.workspace import WorkspaceStore
from test_incidents import IncidentHTTPFixture


class FiniteReferenceTests(unittest.TestCase):
    def test_control_is_selected_before_disturbance_and_feedback_can_branch(self):
        # From 0 action 0 branches to 1 or 2. Each has its own safe action.
        # At 4, every action has an unsafe outcome, despite each disturbance
        # having a safe action when considered in isolation.
        edges = np.array([[[1, 2], [-1, -1]], [[3, 3], [-1, -1]],
                          [[-1, -1], [3, 3]], [[3, 3], [3, 3]], [[3, -1], [-1, 3]]])
        target = np.arange(5) == 3
        rank, witness = reach(edges, target, 2, np.zeros((5, 2)))
        np.testing.assert_array_equal(rank, [2, 1, 1, 0, -1])
        np.testing.assert_array_equal(witness, [0, 0, 1, -1, -1])
        np.testing.assert_array_equal(predecessor(edges, target)[4], [False, False])
        members, rounds = viability(edges, np.ones(5, bool))
        np.testing.assert_array_equal(members, [True, True, True, True, False])
        self.assertEqual(rounds, 2)

    def test_random_small_graphs_against_tree_search_and_exhaustive_invariant_subsets(self):
        rng = np.random.default_rng(425)
        for _ in range(36):
            edges = rng.integers(-1, 5, size=(5, 2, 2))
            safe = rng.integers(0, 5, size=5) > 0
            target = (rng.integers(0, 3, size=5) == 0) & safe
            movement = rng.random((5, 2))

            @lru_cache(None)
            def can_reach(state, depth):
                if state < 0 or not safe[state]:
                    return False
                return target[state] or (depth > 0 and any(
                    all(can_reach(dest, depth-1) for dest in action) for action in edges[state]))

            valid = edges.copy()
            valid[~safe] = -1
            rank, witness = reach(valid, target, 5, movement)
            for state in range(5):
                expected = next((depth for depth in range(6) if can_reach(state, depth)), -1)
                self.assertEqual(rank[state], expected)
                if expected > 0:
                    actions = [a for a in range(2) if all(can_reach(dest, expected-1) for dest in edges[state, a])]
                    self.assertEqual(witness[state], min(actions, key=lambda a: movement[state, a]))

            safe_nodes = np.flatnonzero(safe).tolist()
            union = set()
            for size in range(1, len(safe_nodes)+1):
                for subset in combinations(safe_nodes, size):
                    for policy in product(range(2), repeat=size):
                        if all(dest in subset for state, a in zip(subset, policy) for dest in edges[state, a]):
                            union.update(subset)
                            break
            actual, rounds = viability(edges, safe)
            self.assertEqual(set(np.flatnonzero(actual)), union)
            expected = safe.copy()
            for i in range(rounds):
                updated = expected & predecessor(edges, expected).any(axis=1)
                self.assertEqual(np.array_equal(expected, updated), i == rounds-1)
                expected = updated

    def test_target_and_indefinite_viability_have_different_objectives(self):
        edges = np.array([[[1]], [[-1]], [[2]]])
        safe, target = np.ones(3, bool), np.array([False, True, False])
        rank, _ = reach(edges, target, 2, np.zeros((3, 1)))
        members, rounds = viability(edges, safe)
        np.testing.assert_array_equal(rank, [1, 0, -1])
        np.testing.assert_array_equal(members, [False, False, True])
        self.assertEqual(rounds, 3)


class HydraulicPlanningTests(unittest.TestCase):
    def test_equilibrium_analytic_transition_and_donor_volume(self):
        config = validate({})
        h = (1.5625, 1.)
        final, _, trace, net = physical_step(config, h, (100., 1.), {}, .1, trace=True)
        np.testing.assert_allclose(final, h, atol=1e-14)
        self.assertAlmostEqual(net, 0.)
        self.assertEqual(trace[-1][0], config['controlSeconds'])
        h = (.02, .08)
        disturbance = dict(leak=.09, outlet=1.2)
        result, _, path, net = physical_step(config, h, (0., 1.), disturbance, 2., trace=True)
        self.assertGreaterEqual(min(min(row[1:3]) for row in path), 0.)
        plant = config['plant']
        area = [plant['area1'], plant['area2']]
        self.assertAlmostEqual(float(np.dot(area, result)-np.dot(area, h)), net, places=13)

        # A fully obstructed valve decouples the ODEs. Tank 1 fills at a
        # constant rate while sqrt(Tank 2 head) decreases linearly.
        h, action = (1.29, .81), (100., 1.)
        duration = config['controlSeconds']
        expected = (h[0] + duration*plant['pumpRate']/plant['area1'],
                    (math.sqrt(h[1]) - duration*plant['outlet']*plant['outletValve']/(2*plant['area2']))**2)
        fine = physical_step(config, h, action, {'valve': 0.}, .02)[0]
        np.testing.assert_allclose(fine, expected, atol=1e-8, rtol=0)

    def test_interior_violation_rejects_graph_edge_even_when_both_ends_are_safe(self):
        study = Study(dict(grid=[31, 31], controlSeconds=30,
                           safe=[[.1, 2.48], [.25, 1.145]], target=[[1.4, 1.8], [.85, 1.1]]))
        heads = (2.34, 1.08)
        final, minimum, path, _ = physical_step(study.config, heads, (0., 1.), {}, .1, trace=True)
        self.assertGreater(margin(heads, study.config['safe']), 0)
        self.assertGreater(margin(final, study.config['safe']), 0)
        self.assertLess(minimum, -.02)
        self.assertLess(min(row[3] for row in path[1:-1]), 0)
        node = int(study.project(heads))*len(study.actions)+2
        self.assertEqual(study.edges[node, 2, 0], -1)
        replay = study.replay(heads, 2, 'hold')
        self.assertEqual(replay['status'], 'unsafe')
        self.assertTrue(0 < replay['violations'][0]['t'] < 30)

    def test_actuator_limits_and_previous_command_are_enforced_on_each_switch(self):
        study = Study({'mode': 'robust', 'disturbances': ['leakage', 'pump-loss']})
        node = int(study.project((2.1, .8)))*len(study.actions)
        self.assertTrue((study.edges[node+8, 2] < 0).all())  # 100 -> 0 is too fast
        self.assertTrue((study.edges[node+2, 2] >= 0).all())  # 0 -> 0 is admissible
        self.assertTrue((study.edges[node+8, 6] < 0).all())  # 1 -> .2 is too fast
        replay = study.replay([2.1, .8], 8)
        self.assertEqual(replay['status'], 'recovered')
        previous = study.actions[8]
        for k, action in enumerate(replay['actions']):
            next_command = np.array([action['pump'], action['valve']])
            self.assertEqual(action['t'], k*10)
            self.assertTrue((abs(next_command-previous) <= [60., .5]).all())
            self.assertTrue((next_command >= [0, .2]).all() and (next_command <= [150, 1]).all())
            previous = next_command
        self.assertGreaterEqual(replay['minimumMargin'], 0.)
        self.assertEqual(len(replay['violations']), 0)
        self.assertTrue(np.all(np.diff([row['t'] for row in replay['trajectory']]) > 0))
        self.assertTrue(np.all((study.rank < 0) | (study.nominal_rank <= study.rank)))
        self.assertTrue(np.all(study.nominal_viable | ~study.viable))
        self.assertEqual(study.replay([2.1, .8], 8, 'fill')['status'], 'unsafe')
        self.assertEqual(study.replay([0., .6], 8)['status'], 'unsafe')

    def test_validation_nonrecoverable_and_reproducible_grid_sensitivity(self):
        for overrides, message in [
                ({'target': [[.1, .2], [.9, 1.]]}, 'inside the operating region'),
                ({'target': [[1.41, 1.42], [.91, .92]], 'grid': [7, 7]}, 'no grid points'),
                ({'safe': [[.3, 2.6], [.25, 2.35]]}, 'overflow height'),
                ({'pump': [-1, 150]}, 'command bounds'),
                ({'mode': 'robust', 'disturbances': []}, 'modeled disturbances'),
                ({'mode': 'robust', 'grid': [61, 61], 'actionCounts': [5, 5]}, 'budget')]:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, message):
                Study(overrides)
        model = Study({'pump': [0, 0]})
        self.assertEqual(model.inspect([.45, .35], 2)['category'], 'nonrecoverable')
        self.assertEqual(model.replay([.45, .35], 2)['status'], 'no-policy')
        a, b = Study({'grid': [17, 17]}), Study({'grid': [17, 17]})
        np.testing.assert_array_equal(a.edges, b.edges)
        self.assertEqual(a.replay([2.1, .8], 8), b.replay([2.1, .8], 8))
        fine = Study({'grid': [41, 41]})
        self.assertLess(fine.spacing[0], a.spacing[0])
        self.assertNotEqual(fine.boundary_mask().sum(), a.boundary_mask().sum())


class RecoveryWorkspaceTests(IncidentHTTPFixture):
    def test_compute_save_restart_report_and_export(self):
        workspace = self.workspace('Recovery')
        other = self.workspace('Other')
        base = f'/workspaces/{workspace}/reachability'
        initial = self.request(base)
        self.assertEqual(initial['defaults']['modelId'], 'coupled-tanks')
        scenario = self.request(f'/workspaces/{workspace}/scenarios',
                                dict(modelId='coupled-tanks', name='Hydraulic reference'), expected=201)
        incident = self.request(f'/workspaces/{workspace}/incidents', dict(title='Water loss'), expected=201)
        data = dict(name='Tank recovery', scenarioId=scenario['id'], scenarioVersion=scenario['version'],
                    incidentId=incident['id'], config={'grid': [29, 29]},
                    initial=dict(heads=[2.1, .8], previousAction=8, disturbance='nominal'))
        computed = self.request(base+'/compute', data)
        saved = self.request(base, data, expected=201)
        self.assertEqual(computed['analysis']['policy'], saved['analysis']['policy'])
        self.assertEqual(computed['evaluation'], saved['evaluation'])
        self.assertEqual(saved['evaluation']['replays']['policy']['status'], 'recovered')
        self.assertEqual(saved['incident']['id'], incident['id'])
        identity = saved['id']
        self.request(f'/workspaces/{other}/reachability/{identity}', expected=404)
        self.stop()
        self.start()
        self.assertEqual(self.request(base+'/'+identity), saved)
        self.assertEqual(self.request(base)['studies'][0]['id'], identity)
        self.assertIn('representative grid points', render(saved))
        self.assertIn('Time to target (s)', render(saved))
        report_url = f'http://127.0.0.1:{self.service.server_port}/api{base}/{identity}/report.html?download=1'
        with build_opener(ProxyHandler({})).open(report_url, timeout=10) as response:
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertIn('Nonlinear replay comparison', response.read().decode('utf-8'))
        dataset = self.request(base+'/'+identity+'/dataset', dict(strategy='policy'), expected=201)
        self.assertEqual(dataset['metadata']['recovery']['studyId'], identity)
        self.assertEqual(dataset['metadata']['columns'][0]['unit'], 'm')
        self.assertGreater(dataset['metadata']['rowCount'], 2)
        signals = self.request(f'/workspaces/{workspace}/signals')['signals']
        self.assertTrue(any(s['datasetId'] == dataset['id'] and s['unit'] == '%' for s in signals))
        self.request(base, dict(data, scenarioId=scenario['id'], scenarioVersion=999), expected=404)
        self.request(f'/workspaces/{workspace}', method='DELETE')
        with WorkspaceStore(Path(self.folder)).connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recovery_studies').fetchone()[0], 0)
