"""Numerical contracts and real HTTP acceptance of the transformation workflow."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from urllib.request import build_opener, ProxyHandler

import numpy as np

from l5.expressions import Quantity, evaluate
from l5.resampling import deduplicate, fill_missing, resample
from l5.units import conversion, convert
from tests.test_incidents import IncidentHTTPFixture


class NumericalTransformationTests(unittest.TestCase):
    def test_affine_temperatures_and_differences(self):
        np.testing.assert_allclose(convert([0, 100, np.nan], '°C', 'K'), [273.15, 373.15, np.nan])
        np.testing.assert_allclose(convert([32, 212], '°F', '°C'), [0, 100], atol=1e-12)
        np.testing.assert_allclose(convert([273.15, 373.15], 'K', '°F'), [32, 212])
        np.testing.assert_allclose(convert([18], 'Δ°F', 'Δ°C'), [10])
        with self.assertRaises(ValueError):
            convert([10], 'Δ°C', 'K')

    def test_industrial_units_custom_units_and_rotation_semantics(self):
        for source, target, value, expected in [
            ('Pa', 'kPa', 1200, 1.2), ('kPa', 'MPa', 300, .3), ('bar', 'Pa', 2, 200000),
            ('m3/s', 'm³/h', 1, 3600), ('m³/h', 'L/min', 6, 100),
            ('W', 'MW', 2000000, 2), ('kV', 'V', 2, 2000), ('mA', 'A', 25, .025),
            ('ms', 's', 2000, 2), ('h', 'min', 2, 120), ('vendor-unit', 'vendor-unit', 42, 42)]:
            with self.subTest(source=source, target=target):
                self.assertAlmostEqual(convert([value], source, target)[0], expected)
        self.assertAlmostEqual(convert([3600], 'rpm', 'Hz', rotational=True)[0], 60)
        for a, b in [('rpm', 'Hz'), ('kPa', 'K'), ('custom', 'other'), ('', 'kW')]:
            with self.assertRaises(ValueError):
                conversion(a, b)

    def test_irregular_interpolation_nearest_previous_and_no_extrapolation(self):
        times, values = np.array([0., 1.5, 4.]), np.array([0., 3., 8.])
        grid = np.arange(-1, 6, dtype=float)
        result, codes, observed = resample(times, values, np.ones(3, dtype=bool), grid,
            method='linear', interval=1, max_gap=3)
        np.testing.assert_allclose(result, [np.nan, 0, 2, 4, 6, 8, np.nan], equal_nan=True)
        np.testing.assert_array_equal(observed, [False, True, False, False, False, True, False])
        self.assertEqual(codes[3], 2)
        previous, _, _ = resample(times, values, np.ones(3, dtype=bool), grid, method='previous', interval=1, max_gap=1.2)
        np.testing.assert_allclose(previous, [np.nan, 0, 0, 3, np.nan, 8, np.nan], equal_nan=True)
        nearest, _, _ = resample(times, values, np.ones(3, dtype=bool), grid, method='nearest', interval=1, max_gap=3)
        np.testing.assert_allclose(nearest, [np.nan, 0, 3, 3, 8, 8, np.nan], equal_nan=True)

    def test_long_gaps_and_explicit_missing_are_not_hidden(self):
        times = np.array([0., 1., 2., 20., 21.])
        values = np.array([0., np.nan, 2., 20., 21.])
        grid = np.arange(22, dtype=float)
        result, codes, observed = resample(times, values, np.isfinite(values), grid,
            method='linear', interval=1, max_gap=3)
        self.assertTrue(np.isnan(result[1]))
        self.assertTrue(np.isnan(result[3:20]).all())
        filled, filled_codes, mask, _ = fill_missing(grid, result, codes, observed, policy={'method': 'linear'},
            max_gap=3, coverage=(0, 21), statistic_values=values)
        self.assertEqual(filled[1], 1)
        self.assertEqual(filled_codes[1], 2)
        self.assertFalse(mask[1])
        self.assertTrue(np.isnan(filled[3:20]).all())

    def test_window_aggregates_are_left_closed_and_bounded(self):
        times, values = np.array([0., .2, .9, 1., 1.9, 2.]), np.array([1., 2., 6., 4., np.nan, 8.])
        for method, expected in [('mean', [3, 4, 8]), ('min', [1, 4, 8]), ('max', [6, 4, 8])]:
            result, codes, mask = resample(times, values, np.isfinite(values), np.arange(3.), method=method, interval=1, max_gap=2)
            np.testing.assert_array_equal(result, expected)
            np.testing.assert_array_equal(codes, [4, 4, 4])
            self.assertTrue(mask.all())

    def test_duplicate_policies_include_missing_values(self):
        times, values = np.array([0., 1., 1., 1., 2.]), np.array([1., np.nan, 3., 5., 6.])
        for policy, expected in [('first', [1, np.nan, 6]), ('last', [1, 5, 6]), ('mean', [1, 4, 6])]:
            t, v, mask, count = deduplicate(times, values, np.isfinite(values), policy)
            np.testing.assert_array_equal(t, [0, 1, 2])
            np.testing.assert_allclose(v, expected, equal_nan=True)
            self.assertEqual(count, 2)
        with self.assertRaises(ValueError):
            deduplicate(times, values, np.isfinite(values), 'error')

    def test_filling_keeps_outside_coverage_missing_and_records_statistic(self):
        grid = np.arange(6.)
        values = np.array([np.nan, 2., np.nan, np.nan, 8., np.nan])
        for method in ('fixed', 'statistic'):
            result, codes, mask, effective = fill_missing(grid, values, np.where(np.isfinite(values), 1, 0), np.isfinite(values),
                policy=dict(method=method, value=42, statistic='median'), max_gap=4, coverage=(1, 4), statistic_values=np.array([2, 8, np.nan]))
            np.testing.assert_allclose(result, [np.nan, 2, 42 if method == 'fixed' else 5, 42 if method == 'fixed' else 5, 8, np.nan], equal_nan=True)
            self.assertFalse(mask[2])
            if method == 'statistic':
                self.assertEqual(effective['computedValue'], 5)
                self.assertEqual(effective['validSourceSamples'], 2)

    def quantities(self):
        return {key: Quantity(np.asarray(values, dtype=float), unit, np.ones(4, dtype=bool)) for key, values, unit in [
            ('hot', [20, 21, 22, 25], '°C'), ('cold', [283.15, 284.15, 285.15, 288.15], 'K'),
            ('up', [100, 102, 106, 112], 'kPa'), ('down', [.09, .09, .09, .09], 'MPa'),
            ('power', [1, 2, 3, 4], 'MW'), ('rated', [2000, 2000, 2000, 2000], 'kW')]}

    def test_expression_compatible_units_ratios_temperatures_and_unequal_time_rates(self):
        times = np.array([0., 1., 3., 6.])
        quantities = self.quantities()
        difference, refs, _ = evaluate('hot - cold', quantities, times)
        np.testing.assert_allclose(difference.values, [10] * 4)
        self.assertEqual(difference.unit, 'Δ°C')
        self.assertEqual(set(refs), {'hot', 'cold'})
        pressure, _, _ = evaluate('up - down', quantities, times, 'Pa')
        np.testing.assert_allclose(pressure.values, [10000, 12000, 16000, 22000])
        ratio, _, _ = evaluate('power / rated', quantities, times)
        np.testing.assert_allclose(ratio.values, [.5, 1, 1.5, 2])
        rate, _, _ = evaluate('rate(up)', quantities, times)
        np.testing.assert_allclose(rate.values, [np.nan, 2, 2, 2], equal_nan=True)
        self.assertEqual(rate.unit, 'kPa/s')
        thermal_rate, _, _ = evaluate('rate(hot)', quantities, times)
        self.assertEqual(thermal_rate.unit, 'Δ°C/s')
        product, _, inferred = evaluate('power * up', quantities, times, 'MW*kPa')
        self.assertIsNone(inferred)
        np.testing.assert_allclose(product.values, [100, 204, 318, 448])
        with self.assertRaises(ValueError):
            evaluate('power * up', quantities, times)
        for expression in ['hot + cold', 'hot * 2', 'hot / cold', 'up + hot', 'log(up)']:
            with self.assertRaises(ValueError):
                evaluate(expression, quantities, times)

    def test_expression_safety_domain_errors_and_observation_dependencies(self):
        quantities, times = self.quantities(), np.arange(4.)
        for expression in ["__import__('os').system('echo bad')", 'up.__class__', 'up[0]', '[x for x in up]', '2 ** 1000', 'unknown + up', 'rate(up, bad=1)', 'lambda: 1', 'True', 'exp(99999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999)']:
            with self.subTest(expression=expression), self.assertRaises((ValueError, OverflowError)):
                evaluate(expression, quantities, times)
        quantities['up'].observed[2] = False
        calculated, _, _ = evaluate('up - down', quantities, times)
        self.assertFalse(calculated.observed[2])
        zero, _, _ = evaluate('up / (up - up)', quantities, times)
        self.assertTrue(np.isnan(zero.values).all())

    def test_direct_reference_conversion_does_not_mutate_sources_and_rate_units_convert(self):
        quantities, times = self.quantities(), np.array([0., 1., 3., 6.])
        output, _, _ = evaluate('up', quantities, times, 'MPa')
        np.testing.assert_allclose(output.values, [.1, .102, .106, .112])
        self.assertEqual(quantities['up'].unit, 'kPa')
        np.testing.assert_array_equal(quantities['up'].values, [100, 102, 106, 112])
        rate, _, _ = evaluate('rate(up)', quantities, times, 'Pa/s')
        np.testing.assert_allclose(rate.values, [np.nan, 2000, 2000, 2000], equal_nan=True)
        clipped, _, _ = evaluate('clip(up, 101, 110)', quantities, times)
        np.testing.assert_array_equal(clipped.values, [101, 102, 106, 110])

    def test_previous_fill_uses_original_anchor_age_and_handles_trailing_missing(self):
        native, raw, grid = np.array([0., 10.]), np.array([10., np.nan]), np.arange(11.)
        values, codes, observed = resample(native, raw, np.isfinite(raw), grid, method='previous', interval=1, max_gap=2)
        result, _, _, _ = fill_missing(grid, values, codes, observed, policy={'method':'previous'}, max_gap=2,
            coverage=(0, 10), statistic_values=raw, anchor_times=native, anchor_values=raw, anchor_observed=np.isfinite(raw))
        np.testing.assert_array_equal(result[:3], [10, 10, 10])
        self.assertTrue(np.isnan(result[3:]).all(), 'held values must not become fresh anchors that extend the maximum gap')

    def test_rotation_meaning_is_retained_in_derived_conversion(self):
        times = np.arange(3.)
        quantities = {'rpm': Quantity(np.array([60., 120., 180.]), 'rpm', np.ones(3, dtype=bool), rotational=True),
                      'hz': Quantity(np.array([1., 2., 3.]), 'Hz', np.ones(3, dtype=bool), rotational=True)}
        result, _, _ = evaluate('rpm / hz', quantities, times)
        np.testing.assert_allclose(result.values, [1, 1, 1])
        rate, _, _ = evaluate('rate(rpm)', quantities, times, 'Hz/s')
        np.testing.assert_allclose(rate.values, [np.nan, 1, 1], equal_nan=True)
        quantities['hz'].rotational = False
        with self.assertRaises(ValueError):
            evaluate('rpm / hz', quantities, times)


class TransformationHTTPTests(IncidentHTTPFixture):
    def source(self, wid, name, text, unit='', **options):
        dataset = self.request(f'/workspaces/{wid}/datasets', dict(name=name, csv=text, **options), expected=201)
        signal = next(s for s in self.request(f'/workspaces/{wid}/signals')['signals'] if s['datasetId'] == dataset['id'])
        if unit:
            self.request('/signals/' + signal['id'], {'unit': unit}, method='PATCH')
        return dataset, signal

    @staticmethod
    def input(signal, key, **options):
        return dict(signalId=signal['id'], key=key, resampling='linear', maxGapSeconds=4,
                    duplicatePolicy='mean', missing={'method': 'keep'}, **options)

    def test_three_example_sources_preview_save_restart_versions_analysis_incident_report(self):
        wid = self.workspace('Three-source transformation')
        root = Path(__file__).resolve().parents[1] / 'examples' / 'data-foundation'
        temp, ts = self.source(wid, 'Temperature', (root / 'temperature-1s.csv').read_text(), '°C')
        flow, fs = self.source(wid, 'Flow', (root / 'flow-2s-unix-ms.csv').read_text(), 'm³/h', timeKind='unix', timeUnit='milliseconds')
        pressure, ps = self.source(wid, 'Pressure', (root / 'pressure-irregular.csv').read_text(), 'kPa', timeColumn='seconds', timeKind='numeric')
        self.request(f'/datasets/{pressure["id"]}/time-reference', dict(mode='reference', referenceDatasetId=temp['id'], offsetSeconds=25), method='PATCH')
        source_paths = [self.folder / wid / 'datasets' / d['id'] / filename for d in [temp, flow, pressure] for filename in ['source.csv', 'series.npz']]
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths]
        config = dict(version=1, grid=dict(mode='intersection', intervalSeconds=1), sources=[
            self.input(ts, 'temperature'), {**self.input(fs, 'flow'), 'resampling': 'previous'}, self.input(ps, 'pressure', unit='MPa')],
            derived=[dict(key='pressure_rate', displayName='Pressure rate', expression='rate(pressure)', unit=''),
                     dict(key='temperature_change', displayName='Temperature change', expression='diff(temperature)', unit='')])
        preview = self.request(f'/workspaces/{wid}/transformations/preview', {'config': config})
        self.assertEqual(preview['metadata']['rowCount'], 496)
        self.assertAlmostEqual(preview['series']['values']['pressure'][0], .3)
        columns = preview['metadata']['columns']
        self.assertEqual([c['unit'] for c in columns], ['°C', 'm³/h', 'MPa', 'MPa/s', 'Δ°C'])
        self.assertEqual(preview['metadata']['time']['origin'], '2026-10-24T00:00:25+00:00')
        self.assertIsNone(preview['series']['values']['pressure'][225])
        self.assertEqual(preview['samples'][0]['provenance']['flow'], 'held')
        self.assertFalse(preview['samples'][0]['observed']['flow'])
        definition = self.request(f'/workspaces/{wid}/transformations', {'name': 'Motor pipeline', 'config': config}, expected=201)
        did = definition['id']
        dataset = self.request(f'/transformations/{did}/execute', {}, expected=201)
        old_hash = hashlib.sha256((self.folder / wid / 'datasets' / dataset['id'] / 'series.npz').read_bytes()).hexdigest()
        self.assertEqual(dataset['metadata']['columns'][2]['unit'], 'MPa')
        sample = self.request(f'/datasets/{dataset["id"]}/sample?at=0&signal=flow')
        self.assertEqual(sample['provenance']['flow'], 'held')
        self.assertFalse(sample['observed']['flow'])
        results = []
        for algorithm in ('robust-maxz', 'pca-q'):
            result = self.request(f'/workspaces/{wid}/analyses', dict(datasetId=dataset['id'], signals=['temperature', 'flow', 'pressure'],
                algorithm=algorithm, baselineRange=[0, 169], analysisRange=[170, 495], observationPolicy='processed'), expected=201)
            self.assertTrue(result['intervals'])
            self.assertGreater(result['summary']['abstainedSamples'], 0)
            self.assertGreater(result['summary']['processedInputValues'], 0)
            self.assertEqual(result['transformation']['revision'], 1)
            results.append(result)
        incident = self.request(f'/workspaces/{wid}/incidents', dict(title='Derived data excursion', source=dict(kind='interval', analysisId=results[0]['id'], intervalIndex=0)), expected=201)
        self.request(f'/incidents/{incident["id"]}/links', dict(kind='analysis', analysisId=results[1]['id']), expected=201)
        self.stop(); self.start()
        self.assertEqual(self.request(f'/transformations/{did}'), definition)
        self.assertEqual(self.request(f'/datasets/{dataset["id"]}'), dataset)
        self.assertEqual(self.request(f'/analyses/{results[0]["id"]}'), results[0])
        timeline = self.request(f'/incidents/{incident["id"]}/timeline')
        self.assertEqual(len(timeline['analyses']), 2)
        url = f'http://127.0.0.1:{self.service.server_port}/api/incidents/{incident["id"]}/report.html'
        with build_opener(ProxyHandler({})).open(url) as response:
            report = response.read().decode()
        for value in ['派生数据来源与处理步骤', 'Motor pipeline', 'Temperature', 'Pressure', ps['id'], 'MPa', 'pressure_rate', 'observationPolicy']:
            self.assertIn(value, report)
        edited = deepcopy(definition['config'])
        edited['grid']['intervalSeconds'] = 2
        updated = self.request(f'/transformations/{did}', dict(name='Motor pipeline 2s', config=edited), method='PATCH')
        self.assertEqual(updated['revision'], 2)
        newer = self.request(f'/transformations/{did}/execute', {}, expected=201)
        self.assertNotEqual(newer['id'], dataset['id'])
        self.assertEqual(newer['metadata']['transformation']['revision'], 2)
        self.assertEqual(self.request(f'/analyses/{results[0]["id"]}')['datasetId'], dataset['id'])
        self.assertEqual(self.request(f'/incidents/{incident["id"]}')['links'][0]['details']['datasetId'], dataset['id'])
        self.assertEqual(hashlib.sha256((self.folder / wid / 'datasets' / dataset['id'] / 'series.npz').read_bytes()).hexdigest(), old_hash)
        self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths], hashes)

    def test_relative_offsets_frozen_clocks_union_validation_and_chained_provenance(self):
        wid = self.workspace()
        a, sa = self.source(wid, 'A', 't,x\n0,10\n2,20\n4,30\n', 'kPa')
        b, sb = self.source(wid, 'B', 't,x\n0,100\n2,200\n', 'Pa')
        config = dict(grid=dict(mode='union', intervalSeconds=1), sources=[self.input(sa, 'a'), self.input(sb, 'b')])
        self.request(f'/workspaces/{wid}/transformations/preview', dict(config=config), expected=400)
        self.request(f'/datasets/{b["id"]}/time-reference', dict(mode='reference', referenceDatasetId=a['id'], offsetSeconds=2), method='PATCH')
        config['derived'] = [dict(key='difference', expression='a - b', unit='kPa')]
        definition = self.request(f'/workspaces/{wid}/transformations', dict(name='Relative', config=config), expected=201)
        output = self.request(f'/transformations/{definition["id"]}/execute', {}, expected=201)
        self.assertEqual(output['metadata']['clock']['axisId'], 'dataset:' + a['id'])
        self.assertEqual(output['metadata']['clock']['offset'], 0)
        self.assertEqual(self.request(f'/datasets/{output["id"]}/series?signal=b')['values']['b'][:2], [None, None])
        self.request(f'/datasets/{b["id"]}/time-reference', dict(mode='reference', referenceDatasetId=a['id'], offsetSeconds=20), method='PATCH')
        rerun = self.request(f'/transformations/{definition["id"]}/execute', {}, expected=201)
        self.assertEqual(output['metadata']['time'], rerun['metadata']['time'])
        self.assertEqual(self.request(f'/datasets/{rerun["id"]}/series?signal=b')['values'], self.request(f'/datasets/{output["id"]}/series?signal=b')['values'])
        self.request(f'/datasets/{output["id"]}/time-reference', dict(mode='independent'), method='PATCH', expected=400)
        s = next(s for s in self.request(f'/workspaces/{wid}/signals')['signals'] if s['datasetId'] == output['id'] and s['name'] == 'a')
        second = self.request(f'/workspaces/{wid}/transformations', dict(name='Chained', config=dict(sources=[self.input(s, 'again')], grid=dict(mode='intersection', intervalSeconds=1))), expected=201)
        chained = self.request(f'/transformations/{second["id"]}/execute', {}, expected=201)
        sample = self.request(f'/datasets/{chained["id"]}/sample?at=1&signal=again')
        self.assertFalse(sample['observed']['again'])
        other = self.workspace('Other')
        self.request(f'/workspaces/{other}/transformations/preview', dict(config=config), expected=400)
        self.request(f'/workspaces/{wid}/transformations/preview', dict(config={**config, 'grid':dict(mode='union', intervalSeconds=1e-12)}), expected=400)

    def test_trip_lens_derived_units_monitoring_incident_and_source_session_survive(self):
        wid = self.workspace('TripLens transform')
        session = self.request('/simulations', dict(workspaceId=wid, title='Transform source', config=dict(fault='cooling_valve', start=70, duration=180, step=.5, seed=328)), expected=201)
        original = self.request(f'/simulations/{session["id"]}/save', {'workspaceId': wid})
        signals = {s['name']: s for s in self.request(f'/workspaces/{wid}/signals')['signals'] if s['datasetId'] == original['id']}
        config = dict(grid=dict(mode='intersection', intervalSeconds=1), sources=[self.input(signals['pressure'], 'pressure', unit='MPa'), self.input(signals['temperature'], 'temperature')],
            derived=[dict(key='pressure_rate', expression='rate(pressure)', unit='')])
        definition = self.request(f'/workspaces/{wid}/transformations', dict(name='Simulator pressure', config=config), expected=201)
        output = self.request(f'/transformations/{definition["id"]}/execute', {}, expected=201)
        self.assertEqual(output['metadata']['transformation']['sourceSimulations'], [session['id']])
        self.assertNotIn('model', output['metadata'])
        result = self.request(f'/workspaces/{wid}/analyses', dict(datasetId=output['id'], signals=['pressure', 'temperature'], algorithm='robust-maxz', baselineRange=[0, 99], analysisRange=[100, 180]), expected=201)
        incident = self.request(f'/workspaces/{wid}/incidents', dict(title='Transformed simulation', source=dict(kind='analysis', analysisId=result['id'])), expected=201)
        self.assertEqual(self.request(f'/incidents/{incident["id"]}/timeline')['datasets'][0]['metadata']['transformation']['sourceSimulations'], [session['id']])
        self.stop(); self.start()
        self.assertEqual(self.request(f'/simulations/{session["id"]}')['rows'], session['rows'])
        tool = self.request(f'/simulations/{session["id"]}/tools', dict(asOf=110, windowStart=0, calls=[dict(tool='sensor_consistency', args={})]))
        self.assertTrue(tool['id'])

    def test_analysis_uses_original_mask_by_default_and_processed_only_when_explicit(self):
        wid = self.workspace()
        csv = 't,x\n' + '\n'.join(f'{t},{np.sin(t / 8) + (8 if t > 400 else 0)}' for t in range(0, 600, 2))
        source, signal = self.source(wid, 'Sparse', csv)
        definition = self.request(f'/workspaces/{wid}/transformations', dict(name='Dense', config=dict(grid=dict(mode='intersection', intervalSeconds=1), sources=[self.input(signal, 'x')])), expected=201)
        output = self.request(f'/transformations/{definition["id"]}/execute', {}, expected=201)
        config = dict(datasetId=output['id'], signals=['x'], baselineRange=[0, 199], analysisRange=[200, 598], algorithm='robust-maxz')
        measured = self.request(f'/workspaces/{wid}/analyses', config, expected=201)
        processed = self.request(f'/workspaces/{wid}/analyses', {**config, 'observationPolicy':'processed'}, expected=201)
        self.assertEqual(measured['states'][1], 'abstain')
        self.assertNotEqual(processed['states'][1], 'abstain')
        self.assertLess(measured['summary']['fitSamples'], processed['summary']['fitSamples'])
        self.assertEqual(measured['summary']['observationPolicy'], 'measured')

    def test_timezone_alignment_custom_grid_and_fills_never_extrapolate(self):
        wid = self.workspace()
        a, sa = self.source(wid, 'Shanghai', 'timestamp,x\n2026-10-24T08:00:00+08:00,0\n2026-10-24T08:00:02+08:00,2\n', 'kPa')
        b, sb = self.source(wid, 'UTC', 'timestamp,x\n2026-10-24T00:00:00Z,100\n2026-10-24T00:00:02Z,102\n', 'kPa')
        epoch = 1792800000
        config = dict(grid=dict(mode='custom', start=epoch - 1, end=epoch + 3, intervalSeconds=1), sources=[
            {**self.input(sa, 'a'), 'missing':dict(method='fixed', value=999)}, self.input(sb, 'b')])
        preview = self.request(f'/workspaces/{wid}/transformations/preview', dict(config=config))
        self.assertEqual(preview['metadata']['time']['origin'], '2026-10-23T23:59:59+00:00')
        self.assertEqual(preview['series']['values']['a'], [None, 0, 1, 2, None])
        self.assertEqual(preview['series']['values']['b'], [None, 100, 101, 102, None])

    def test_millisecond_grid_does_not_round_unix_timestamps_or_drop_the_last_sample(self):
        wid = self.workspace()
        _, signal = self.source(wid, 'Millisecond source', 'timestamp,x\n2026-10-24T00:00:00Z,10\n2026-10-24T00:00:00.001Z,20\n', 'kPa')
        config = dict(grid=dict(mode='intersection', intervalSeconds=.001), sources=[self.input(signal, 'x')])
        preview = self.request(f'/workspaces/{wid}/transformations/preview', dict(config=config))
        self.assertEqual(preview['series']['times'], [0, .001])
        self.assertEqual(preview['series']['values']['x'], [10, 20])
        self.assertEqual(preview['metadata']['transformation']['quality'][0]['observedCount'], 2)


if __name__ == '__main__':
    unittest.main()
