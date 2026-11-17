import copy
import unittest

from l5.alarms import extract_events, flood_metrics, group_alarms, normalize_policy


DATASET = dict(name='Loop 1', metadata=dict(quality=dict(gapThreshold=5)))
CLOCK = dict(key='dataset:d', axisId='utc', offset=100)


def analysis(times, states, scores, intervals):
    return dict(id='a', name='Analysis A', datasetId='d', config=dict(algorithm='z'),
                algorithmLabel='Robust z', times=times, states=states, scores=scores,
                threshold=2, intervals=intervals, createdAt='2026-11-01T00:00:00Z',
                contributionMetric='absolute-robust-z')


def interval(start, end, samples, peak_time, peak_score, signals=('pump', 'valve')):
    return dict(start=start, end=end, samples=samples, peakTime=peak_time, peakScore=peak_score,
                signals=list(signals), contributions=[dict(signal=signal, value=peak_score / (index + 1))
                                                      for index, signal in enumerate(signals)])


def alarm(identity, start, end, *, axis='utc', dataset='d', detector='z', signal='pump',
          observed=(0, 100), samples=3):
    return dict(id=identity, datasetId=dataset, detector=detector, axisId=axis, start=start, end=end,
                signals=[signal], samples=samples, durationSeconds=end - start, observedSpan=list(observed))


class AlarmExtractionTests(unittest.TestCase):
    def test_acquisition_gap_abstention_and_point_events_remain_visible(self):
        result = analysis([0, 1, 2, 12, 13, 14, 15, 16, 17, 18],
                          ['normal', 'alarm', 'alarm', 'alarm', 'abstain',
                           'alarm', 'normal', 'normal', 'alarm', 'alarm'],
                          [1, 8, 6, 4, 0, 9, 1, 1, 5, 6],
                          [interval(1, 12, 3, 1, 8), interval(14, 14, 1, 14, 9),
                           interval(17, 18, 2, 18, 6)])
        result['observedFraction'] = [1, .5, 1, 1, 0, 1, 1, 1, 1, 1]
        before = copy.deepcopy(result)
        events = extract_events(result, DATASET, CLOCK)
        self.assertEqual(result, before)
        self.assertEqual([(e['intervalIndex'], e['fragmentIndex'], e['samples']) for e in events],
                         [(0, 0, 2), (0, 1, 1), (1, 0, 1), (2, 0, 2)])
        self.assertEqual([(e['start'], e['end']) for e in events],
                         [(101, 102), (112, 112), (114, 114), (117, 118)])
        self.assertEqual([e['measuredState'] for e in events], ['unknown', 'unknown', 'cleared', 'active'])
        self.assertEqual([e['endReason'] for e in events], ['data-gap', 'abstention', 'normal-sample', 'analysis-end'])
        self.assertEqual([e['observedSpan'] for e in events], [[100, 102], [112, 112], [114, 118], [114, 118]])
        self.assertEqual(events[0]['observedFraction'], .75)
        self.assertEqual(events[0]['quality']['abstainedSamples'], 1)
        self.assertEqual(events[1]['peakAboveThreshold'], 2)
        self.assertEqual(events[1]['nativeContributionTime'], 1)
        self.assertIsNone(events[1]['peakMagnitude'])
        self.assertEqual(events[0]['peakMagnitude'], 8)
        self.assertEqual(events[0]['signals'], ['pump', 'valve'])
        self.assertEqual(events[0]['affectedSignals'], ['pump'])
        self.assertEqual(events[2]['clearTime'], 115)

    def test_equal_timestamps_are_resolved_by_detector_sample_order(self):
        result = analysis([0, 1, 1, 1, 2], ['normal', 'alarm', 'abstain', 'alarm', 'normal'],
                          [1, 5, 0, 6, 1], [interval(1, 1, 1, 1, 5), interval(1, 1, 1, 1, 6)])
        events = extract_events(result, DATASET, CLOCK)
        self.assertEqual([e['peakIndex'] for e in events], [1, 3])
        self.assertEqual([e['endReason'] for e in events], ['abstention', 'normal-sample'])

    def test_old_saved_intervals_need_no_per_sample_states(self):
        result = analysis([0, 1, 2], None, [1, 4, 1], [interval(1, 1, 1, 1, 4)])
        del result['states']
        event, = extract_events(result, DATASET, CLOCK)
        self.assertEqual(event['provenance']['stateBasis'], 'saved-intervals')
        self.assertEqual(event['measuredState'], 'cleared')


class AlarmCorrelationTests(unittest.TestCase):
    def test_point_overlap_cross_detector_and_mappings(self):
        events = [alarm('first', 1, 3), alarm('second', 3, 3, detector='pca', samples=1),
                  alarm('other', 2, 4, signal='valve'), alarm('wrong-clock', 2, 4, axis='dataset:r'),
                  alarm('unmapped-dataset', 2, 4, dataset='r')]
        policy = normalize_policy(dict(mappings=[dict(datasetId='d', signal='pump', equipment='loop', priority='high')]))
        result = group_alarms(events, policy)
        self.assertEqual(result, group_alarms(reversed(events), policy))
        self.assertEqual(sum(len(g['eventIds']) for g in result['groups']), len(events))
        pair, = (g for g in result['groups'] if len(g['eventIds']) == 2)
        self.assertEqual(pair['eventIds'], ['first', 'second'])
        self.assertEqual(pair['priority'], 'high')
        relationship, = pair['relationships']
        self.assertEqual(relationship['reasons'], ['shared-signal', 'detector-agreement'])
        self.assertEqual(relationship['temporal'], 'overlap')
        self.assertNotIn('priority', events[0])

    def test_cross_dataset_relationship_needs_coverage_for_proximity(self):
        events = [alarm('left', 1, 3), alarm('right', 4, 5, dataset='r', signal='level'),
                  alarm('after-gap', 7, 7, dataset='r', signal='level', observed=(7, 20))]
        policy = normalize_policy(dict(proximitySeconds=5, repeatWindowSeconds=5, relationships=[
            dict(left=dict(datasetId='r', signal='level'), right=dict(datasetId='d', signal='pump')),
        ]))
        result = group_alarms(events, policy)
        self.assertEqual([g['eventIds'] for g in result['groups']], [['left', 'right'], ['after-gap']])
        edge, = result['groups'][0]['relationships']
        self.assertEqual((edge['temporal'], edge['gapSeconds'], edge['reasons']),
                         ('proximity', 1, ['explicit-relationship']))
        self.assertEqual(edge['explicitPairs'], [
            dict(left=dict(datasetId='d', signal='pump'), right=dict(datasetId='r', signal='level')),
        ])

    def test_equipment_grouping_is_explicit_and_opt_in(self):
        events = [alarm('pump', 2, 4), alarm('valve', 3, 6, signal='valve'), alarm('fan', 3, 6, signal='fan')]
        maps = [dict(datasetId='d', signal=signal, equipment=equipment) for signal, equipment in
                [('pump', 'loop'), ('valve', 'loop'), ('fan', 'cabinet')]]
        self.assertEqual(len(group_alarms(events, normalize_policy(dict(mappings=maps)))['groups']), 3)
        groups = group_alarms(events, normalize_policy(dict(mappings=maps, groupByEquipment=True)))['groups']
        self.assertEqual([g['eventIds'] for g in groups], [['pump', 'valve'], ['fan']])
        self.assertEqual(groups[0]['relationships'][0]['reasons'], ['shared-equipment'])

    def test_repeat_policy_and_persistence_keep_original_events(self):
        events = [alarm('a', 1, 2), alarm('b', 4, 5), alarm('point', 6, 6, samples=1)]
        self.assertEqual(len(group_alarms(events, normalize_policy(dict(proximitySeconds=10)))['groups']), 3)
        result = group_alarms(events, normalize_policy(dict(repeatWindowSeconds=3, minSamples=2)))
        self.assertEqual([g['eventIds'] for g in result['groups']], [['a', 'b'], ['point']])
        self.assertIn('repeat', result['groups'][0]['relationships'][0]['reasons'])
        self.assertFalse(result['events'][-1]['policyEligible'])

    def test_policy_rejects_invalid_values(self):
        for body in ({'priorities': []}, {'proximitySeconds': float('inf')}, {'floodWindowSeconds': 0},
                     {'minSamples': 2.5}, {'defaultPriority': 'missing'}, {'groupByEquipment': 'false'},
                     {'relationships': [{'left': {}, 'right': {}}]}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                normalize_policy(body)


class AlarmFloodTests(unittest.TestCase):
    def test_arrivals_and_peak_concurrency_use_distinct_denominators(self):
        events = [alarm('long', 5, 10), alarm('point', 10, 10), alarm('next', 10, 14, detector='pca'),
                  alarm('independent', 10, 10, axis='relative')]
        policy = normalize_policy(dict(floodWindowSeconds=10))
        correlated = group_alarms(events, policy)
        flood = flood_metrics(**correlated, policy=policy, acknowledgements={'point': 12},
                              axes=[dict(id='utc', start=0, end=20)])
        self.assertEqual((flood['rawEventCount'], flood['groupCount']), (4, 2))
        utc = next(a for a in flood['axes'] if a['axisId'] == 'utc')
        self.assertEqual([(b['start'], b['arrivals'], b['groupArrivals'], b['peakConcurrent']) for b in utc['bins']],
                         [(0, 1, 1, 1), (10, 2, 0, 3), (20, 0, 0, 0)])
        self.assertEqual(utc['peakArrivalsPerHour'], 720)
        self.assertEqual(utc['repeatedEventCount'], 1)
        self.assertEqual(utc['totalDurationSeconds'], 9)
        self.assertEqual(utc['acknowledgedCount'], 1)
        self.assertEqual(utc['meanAcknowledgementDelaySeconds'], 12)

    def test_sparse_axis_compresses_empty_windows_and_preserves_coverage_bounds(self):
        policy = normalize_policy(dict(floodWindowSeconds=1))
        correlated = group_alarms([alarm('early', 0, 0), alarm('late', 100000000, 100000000)], policy)
        flood = flood_metrics(**correlated, policy=policy, axes=[dict(id='empty', start=2, end=5)])
        empty, utc = flood['axes']
        self.assertEqual(empty['rawEventCount'], 0)
        self.assertEqual(empty['bins'][0]['windowCount'], 4)
        self.assertEqual(len(utc['bins']), 3)
        self.assertEqual(utc['bins'][1]['windowCount'], 99999999)
        self.assertEqual(sum(b['arrivals'] for b in utc['bins']), 2)


if __name__ == '__main__':
    unittest.main()
