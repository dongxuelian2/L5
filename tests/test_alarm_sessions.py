"""Alarm lifecycle, time snapshots, and Incident integration through the local API."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

from test_incidents import IncidentHTTPFixture, csv_with_excursions


class AlarmSessionTests(IncidentHTTPFixture):
    def dataset(self, wid, name='Reactor'):
        return self.request(f'/workspaces/{wid}/datasets', dict(name=name, csv=csv_with_excursions()), expected=201)

    def session(self, wid, results, **policy):
        return self.request(f'/workspaces/{wid}/alarm-sessions', dict(name='Shift review',
            analysisIds=[r['id'] for r in results], policy=policy), expected=201)

    def download(self, path):
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{self.service.server_port}/api{path}', timeout=30) as response:
            return response.headers, response.read().decode('utf-8')

    def test_actions_are_audited_without_changing_measurement_state(self):
        wid = self.workspace()
        dataset = self.dataset(wid)
        result = self.request(f'/workspaces/{wid}/analyses', dict(datasetId=dataset['id'], signals=['temperature'],
            algorithm='robust-maxz', baselineRange=[0, 199], analysisRange=[200, 350], alpha=.01), expected=201)
        started = datetime(2026, 5, 1, 8, tzinfo=timezone.utc)
        with patch('l5.alarm_sessions.now', return_value=started.isoformat()):
            view = self.session(wid, [result], escalationSeconds=2, maxShelveSeconds=60)
        event = next(e for e in view['events'] if e['nativeEnd'] == 350)
        self.assertEqual(event['measuredState'], 'active')
        self.assertFalse(event['operator']['escalated'])
        base = f'/alarm-sessions/{view["id"]}'
        action = base + f'/events/{event["id"]}/actions'

        def current_view(at, body=None, expected=200):
            with patch('l5.alarm_sessions.now', return_value=(started + timedelta(seconds=at)).isoformat()):
                value = self.request(action if body else base, body, expected=expected)
            if expected == 200:
                self.assertEqual(next(e for e in value['events'] if e['id'] == event['id'])['measuredState'], 'active')
            return value

        def state(view):
            return next(e['operator'] for e in view['events'] if e['id'] == event['id'])

        self.assertTrue(state(current_view(3))['escalated'])
        end = (started + timedelta(seconds=15)).isoformat()
        shelved = current_view(5, dict(kind='shelve', actor='Kai', expiresAt=end))
        self.assertEqual(state(shelved)['shelvedUntil'], end)
        self.assertIsNone(state(current_view(15))['shelvedUntil'])
        current_view(16, dict(kind='shelve', expiresAt=end), expected=400)
        acknowledged = current_view(18, dict(kind='acknowledge', actor='Kai'))
        self.assertFalse(state(acknowledged)['escalated'])
        self.assertEqual(acknowledged['flood']['axes'][0]['meanAcknowledgementDelaySeconds'], 18)
        self.assertEqual(len(current_view(19, dict(kind='acknowledge'))['audit']), 2)
        current_view(20, dict(kind='note', actor='Kai', note='<script>alert(1)</script> & next shift'))
        self.assertEqual(self.request(f'/analyses/{result["id"]}'), result)
        listed = self.request(f'/workspaces/{wid}/alarm-sessions')['sessions']
        self.assertEqual((listed[0]['id'], listed[0]['eventCount']), (view['id'], view['eventCount']))

        self.stop()
        self.start()
        restored = self.request(base)
        self.assertEqual([a['kind'] for a in restored['audit']], ['shelve', 'acknowledge', 'note'])
        self.assertEqual(restored['groups'], view['groups'])
        headers, history = self.download(base + '/history.json')
        self.assertIn('attachment', headers['Content-Disposition'])
        self.assertEqual(json.loads(history)['audit'], restored['audit'])
        headers, html = self.download(base + '/report.html?lang=zh-CN&download=1')
        self.assertIn('attachment', headers['Content-Disposition'])
        self.assertIn('<html lang="zh-CN">', html)
        self.assertIn('报警负荷', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)

    def test_clock_edits_keep_session_and_created_incident_observations_frozen(self):
        wid = self.workspace()
        left, right = self.dataset(wid, 'Train A'), self.dataset(wid, 'Train B')
        results = [self.analyze(wid, d['id']) for d in (left, right)]
        policy = dict(relationships=[dict(left=dict(datasetId=left['id'], signal='temperature'),
                                          right=dict(datasetId=right['id'], signal='temperature'))])
        first = self.session(wid, results, **policy)
        self.assertEqual(len(first['axes']), 2)
        sources = {event['id']: event for event in first['events']}
        self.assertTrue(all(len({sources[i]['datasetId'] for i in group['eventIds']}) == 1 for group in first['groups']))
        clock_path = f'/datasets/{right["id"]}/time-reference'
        self.request(clock_path, dict(mode='reference', referenceDatasetId=left['id'], offsetSeconds=0), method='PATCH')
        view = self.session(wid, results, **policy)
        group = next(g for g in view['groups'] if g['start'] <= 350 <= g['end'] and len(g['eventIds']) > 1)
        base = f'/alarm-sessions/{view["id"]}'
        self.request(base + f'/events/{group["eventIds"][0]}/actions', dict(kind='note', actor='Lin', note='Check the common feed.'))
        self.request(clock_path, dict(mode='reference', referenceDatasetId=left['id'], offsetSeconds=120), method='PATCH')
        self.assertEqual(self.request(base)['groups'], view['groups'])
        self.assertEqual(self.request(base)['sources'], view['sources'])
        path = base + f'/groups/{group["id"]}/incident'
        linked = self.request(path, dict(title='Feed investigation'))
        incident_id = linked['audit'][-1]['incidentId']
        self.assertEqual(self.request(path, dict(title='Retry'))['audit'], linked['audit'])
        incident = self.request(f'/incidents/{incident_id}/timeline')
        primary = incident['primaryAxisId']
        self.assertTrue(primary.startswith('alarm-snapshot:'))
        recorded = [e for e in incident['events'] if e['axisId'] == primary]
        self.assertEqual(next(e for e in recorded if e['kind'] == 'incident')['start'], group['start'])
        self.assertTrue(any('Check the common feed.' in e.get('content', '') for e in recorded))
        self.assertEqual({a['id'] for a in incident['analyses']}, {r['id'] for r in results})
        self.assertEqual({l['reference_id'] for l in incident['incident']['links'] if l['kind'] == 'dataset'}, {left['id'], right['id']})
        self.assertTrue(any('Explicit signal relationship' in e['content'] for e in incident['incident']['entries']))

    def test_incident_transfer_is_atomic_and_idempotent_under_concurrency(self):
        wid = self.workspace()
        result = self.analyze(wid, self.dataset(wid)['id'])
        view = self.session(wid, [result])
        group = view['groups'][0]
        service = self.service.workspace_store.alarms
        with patch.object(self.service.workspace_store.incidents, 'insert_entry', side_effect=RuntimeError('insert failed')):
            with self.assertRaisesRegex(RuntimeError, 'insert failed'):
                service.incident(view['id'], group['id'], dict(title='Will roll back'))
        self.assertEqual(self.request(f'/workspaces/{wid}/incidents')['incidents'], [])
        self.assertEqual(service.get(view['id'])['audit'], [])

        base = f'/alarm-sessions/{view["id"]}/groups/{group["id"]}/incident'
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.request(base, dict(title='One investigation')), range(2)))
        self.assertEqual(len(responses[0]['audit']), 1)
        self.assertEqual(responses[0]['audit'], responses[1]['audit'])
        self.assertEqual(len(self.request(f'/workspaces/{wid}/incidents')['incidents']), 1)

        existing = self.request(f'/workspaces/{wid}/incidents', dict(title='Existing investigation'), expected=201)
        linked = self.request(base, dict(incidentId=existing['id']))
        self.assertEqual(linked['audit'][-1]['incidentId'], existing['id'])
        self.assertEqual(linked['audit'][-1]['createdIncident'], False)
        self.assertEqual(self.request(base, dict(incidentId=existing['id']))['audit'], linked['audit'])
        outside = self.workspace('Different unit')
        wrong = self.request(f'/workspaces/{outside}/incidents', dict(title='Foreign incident'), expected=201)
        self.request(base, dict(incidentId=wrong['id']), expected=400)
        self.request(f'/workspaces/{outside}/alarm-sessions', dict(name='Foreign analysis', analysisIds=[result['id']]), expected=400)
