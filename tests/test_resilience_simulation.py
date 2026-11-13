"""Numerical and observation-clock checks for the resilience scenario engine."""
import json
import math
import unittest

from l5.models import resolve
from l5.models.tanks import integrate
from l5.resilience_simulation import preview_scenario, scenario_catalog, simulate_scenario, validate_scenario


def fault(kind, target, onset, *, identity=None, recovery=None, severity=1., profile='step', **parameters):
    return dict(id=identity or kind, type=kind, target=target, onset=onset, recovery=recovery,
                severity=severity, profile=profile, parameters=parameters)


def values(simulation, signal):
    return [row['values'][signal] for row in simulation['observations']]


class ResiliencePhysicsTests(unittest.TestCase):
    def test_off_grid_transitions_have_exact_piecewise_injected_mass(self):
        scenario = dict(duration=3.01, sample_interval=1., integration_step=.25, faults=[
            fault('pump_degradation', 'pump', 1.04, recovery=1.92),
            fault('pump_degradation', 'pump', 1.65, identity='other-pump-event', recovery=2.27, maximum_loss=.5),
        ])
        simulation = simulate_scenario(scenario)
        physical = simulation['truth']['physical']
        self.assertEqual([row['t'] for row in simulation['observations']], [0., 1., 2., 3.])
        self.assertEqual([row['t'] for row in physical], [0., 1., 2., 3., 3.01])
        effective_inlet_time = 1.04+(.61*.3)+(.27*.3*.5)+(.35*.5)+.74
        self.assertAlmostEqual(physical[-1]['injected'], .03*effective_inlet_time, places=14)
        self.assertAlmostEqual(physical[2]['inlet'], .015, places=14)
        self.assertEqual(physical[3]['inlet'], .03)

    def test_combined_process_trajectory_is_nonlinear_and_both_donors_conserve_mass(self):
        scenario = dict(duration=100., sample_interval=1., integration_step=.25)
        pump = fault('pump_degradation', 'pump', 10.13)
        valve = fault('valve_restriction', 'valve', 16.12, recovery=90.12)
        leak = fault('tank_leak', 'tank2', 11.43)
        single = [simulate_scenario({**scenario, 'faults': [event]})['truth']['physical'] for event in (pump, valve, leak)]
        combined = simulate_scenario({**scenario, 'faults': [pump, valve, leak]})['truth']['physical']
        healthy = simulate_scenario(scenario)['truth']['physical']
        linear_sum = sum(run[-1]['level2'] for run in single)-2*healthy[-1]['level2']
        self.assertGreater(abs(combined[-1]['level2']-linear_sum), .001)
        self.assertGreater(combined[-1]['leak2'], 0.)
        self.assertEqual(combined[-1]['leak1'], 0.)
        for initial in [dict(initial1=.001, initial2=.002), dict(initial1=.01, initial2=6.)]:
            stress = simulate_scenario({**scenario, 'initial': initial,
                'parameters': dict(area1=.1, area2=.1, connection=.2, outlet=.2, tankHeight=1),
                'faults': [pump, valve, leak, fault('tank_leak', 'tank1', 0., identity='other-leak', coefficient=.1)]})
            physical = stress['truth']['physical']
            self.assertTrue(all(row['level1'] >= 0 and row['level2'] >= 0 for row in physical))
            self.assertLess(max(abs(row['massResidual']) for row in physical), 1e-11)

    def test_profiles_preview_recovery_and_severity_are_reproducible(self):
        scenario = dict(duration=12., sample_interval=.5, seed=12, faults=[
            fault('pump_degradation', 'pump', 1., recovery=8., profile='linear', rise_time=2.),
            fault('valve_restriction', 'valve', 1., profile='progressive', time_constant=2.),
            fault('tank_leak', 'tank1', 1.15, recovery=3.5, profile='temporary'),
            fault('sensor_dropout', 'level1', 3., recovery=9.5, profile='repeating', period=2., active_duration=1.),
            fault('sensor_noise', 'level2', 0., profile='intermittent', period=1., active_duration=.5),
        ])
        preview = preview_scenario(scenario)
        simulation = simulate_scenario(scenario)
        self.assertEqual(preview['schedule'], simulation['schedule'])
        severities = simulation['truth']['severities']
        self.assertEqual(severities['pump_degradation'][2:7], [0., .25, .5, .75, 1.])
        self.assertEqual(severities['pump_degradation'][16], 0.)
        self.assertAlmostEqual(severities['valve_restriction'][6], 1.-math.exp(-1.))
        self.assertGreater(severities['valve_restriction'][-1], 0.)
        self.assertEqual(severities['tank_leak'][7], 0.)
        repeating = next(event for event in simulation['schedule'] if event['id'] == 'sensor_dropout')
        self.assertEqual([(item['start'], item['end']) for item in repeating['intervals']],
                         [(3., 4.), (5., 6.), (7., 8.), (9., 9.5)])
        self.assertEqual(simulation, simulate_scenario(scenario))
        different_seed = simulate_scenario({**scenario, 'seed': 13})
        self.assertNotEqual(severities['sensor_noise'], different_seed['truth']['severities']['sensor_noise'])

    def test_legacy_single_fault_uses_same_hydraulics(self):
        model = resolve('coupled-tanks')
        for kind, target in [('pump_degradation', 'pump'), ('tank_leak', 'tank1'), ('valve_restriction', 'valve'),
                             ('sensor_bias', 'level2')]:
            with self.subTest(kind=kind):
                legacy = model.validate(dict(fault=kind, duration=30, start=10.37, fault_duration=5., noise=0))
                rows, physical = integrate(legacy)
                simulation = simulate_scenario(dict(duration=30, measurement=dict(noise=0), faults=[
                    fault(kind, target, 10.37, recovery=15.37, severity=legacy['severity'])]))
                for old, new in zip(physical, simulation['truth']['physical']):
                    self.assertEqual(old['t'], new['t'])
                    for key in ('level1', 'level2', 'inlet', 'outlet', 'transfer', 'leak'):
                        self.assertAlmostEqual(old[key], new[key], places=14)
                for old, new in zip(rows, simulation['observations']):
                    self.assertAlmostEqual(old['level2'], new['values']['level2'], places=14)


class ResilienceMeasurementTests(unittest.TestCase):
    def test_measurement_failure_does_not_affect_physics_or_unrelated_random_streams(self):
        noisy = dict(duration=20., sample_interval=.5, seed=19, measurement=dict(noise=.01, physical_noise=.02))
        pump = fault('pump_degradation', 'pump', 3.2)
        scenario = {**noisy, 'faults': [pump]}
        reference = simulate_scenario(scenario)
        frozen = fault('sensor_stuck', 'level1', 6., value=1.6)
        revised = simulate_scenario({**scenario, 'faults': [frozen, pump]})
        self.assertEqual(reference['truth']['physical'], revised['truth']['physical'])
        self.assertEqual(values(reference, 'level2'), values(revised, 'level2'))
        self.assertEqual(values(revised, 'level1')[12:], [1.6]*29)
        self.assertNotEqual(revised['truth']['physical'][-1]['level1'], 1.6)
        self.assertNotEqual(values(reference, 'level2'), values(simulate_scenario(scenario, stream_namespace='training'), 'level2'))
        subset = simulate_scenario({**scenario, 'measurement': {**scenario['measurement'], 'signals': ['level2']}})
        self.assertEqual(values(reference, 'level2'), values(subset, 'level2'))

    def test_lost_delayed_frozen_and_out_of_order_packets(self):
        simulation = simulate_scenario(dict(duration=7., sample_interval=1., measurement=dict(noise=0), faults=[
            fault('communication_blackout', 'all', 2., recovery=3.),
            fault('observation_delay', 'level1', 1., recovery=2., delay=1.5),
            fault('out_of_order', 'level2', 3., recovery=4., delay=1.5, probability=1.),
            fault('frozen_timestamp', 'level2', 5., recovery=7.),
        ]))
        frames = simulation['observations']
        self.assertIsNone(frames[1]['values']['level1'])
        self.assertTrue(all(value is None for value in frames[2]['values'].values()))
        self.assertTrue(all(value is None for value in frames[2]['source_times'].values()))
        self.assertEqual(frames[2]['quality']['level1'], 'missing')
        packets = {(packet['signal'], packet['sample_time']): packet for packet in simulation['observation_packets']}
        self.assertEqual(packets['level1', 1.]['flags'], ['blackout', 'delayed'])
        self.assertEqual(packets['level2', 3.]['acquisition_time'], 4.5)
        self.assertEqual(packets['level2', 3.]['quality'], 'out_of_order')
        self.assertIsNone(frames[3]['values']['level2'])
        self.assertEqual(frames[4]['source_times']['level2'], 4.)
        self.assertEqual(frames[5]['source_times']['level2'], 4.)
        self.assertEqual(frames[5]['quality']['level2'], 'frozen_timestamp')
        self.assertEqual(frames[7]['source_times']['level2'], 7.)
        self.assertTrue(all(timestamp is None or timestamp <= frame['t'] for frame in frames
                            for timestamp in frame['acquisition_times'].values()))
        self.assertNotIn('faults', frames[3])
        json.dumps(simulation, allow_nan=False)

    def test_bias_drift_spikes_and_noise_keep_undistorted_evidence(self):
        simulation = simulate_scenario(dict(duration=6., sample_interval=1., measurement=dict(noise=0), faults=[
            fault('sensor_bias', 'level1', 2., severity=.5, offset=.4),
            fault('sensor_drift', 'level2', 2., rate=.1),
            fault('sensor_spike', 'outlet', 2., recovery=3., probability=1., amplitude=.1),
            fault('sensor_noise', 'transfer', 2., stddev=.2),
        ]))
        self.assertAlmostEqual(values(simulation, 'level1')[-1], 1.7625)
        self.assertAlmostEqual(values(simulation, 'level2')[-1], 1.4)
        self.assertEqual(values(simulation, 'outlet'), [.03, .03, .13, .03, .03, .03, .03])
        transfer = next(packet for packet in simulation['observation_packets'] if packet['signal'] == 'transfer' and packet['sample_time'] == 2.)
        self.assertEqual(transfer['undistorted_value'], .03)
        self.assertNotEqual(transfer['value'], transfer['undistorted_value'])
        self.assertEqual(transfer['flags'], ['distorted'])
        self.assertEqual(simulation['observations'][2]['quality']['transfer'], 'observed')

    def test_catalog_defaults_and_validation(self):
        catalog = scenario_catalog()
        self.assertEqual(validate_scenario(catalog['defaults']), catalog['defaults'])
        self.assertEqual(catalog['models'][0]['id'], resolve('coupled-tanks').id)
        with self.assertRaisesRegex(ValueError, 'unique'):
            validate_scenario(dict(faults=[fault('tank_leak', 'tank2', 12.)]*2))
        with self.assertRaisesRegex(ValueError, 'temporary'):
            validate_scenario(dict(faults=[fault('tank_leak', 'tank2', 12., profile='temporary')]))
        with self.assertRaisesRegex(ValueError, 'pulse cycles'):
            validate_scenario(dict(faults=[fault('tank_leak', 'tank2', 12., profile='repeating', period=.001, active_duration=.001)]))


if __name__ == '__main__':
    unittest.main()
