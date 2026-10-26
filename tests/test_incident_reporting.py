"""Real HTTP timeline/report workflows, clock alignment, and interval semantics."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import build_opener, ProxyHandler
from xml.etree import ElementTree
import unittest

from l5.incident_timeline import compare_intervals, observed_spans
from l5.report_locale import localized_report
from l5.reports import chart, render_report
from l5.workspace import WorkspaceStore
from tests.test_incidents import IncidentHTTPFixture, csv_with_excursions


class ReportMarkup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.external = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag in ('script', 'link', 'img', 'iframe') or any(
                attrs.get(key, '').startswith(('http:', 'https:', '/api')) for key in ('src', 'href')):
            self.external.append((tag, attrs))

    def handle_data(self, data):
        self.text.append(data)


class ReportLocaleTests(unittest.TestCase):
    def test_system_report_text_and_chart_defaults_follow_each_request_locale(self):
        with TemporaryDirectory() as folder:
            store = WorkspaceStore(Path(folder))
            workspace = store.create_workspace('Project')
            dataset = store.import_dataset(workspace['id'], dict(name='Measurements', csv=csv_with_excursions()))
            result = store.analyze(workspace['id'], dict(name='Anomaly review', datasetId=dataset['id'],
                signals=['temperature','feed','vibration'], baselineRange=[0,199], analysisRange=[200,599],
                algorithm='robust-maxz', alpha=.01))
            incident = store.incidents.create(workspace['id'], dict(title='Investigation', status='investigating',
                source=dict(kind='analysis',analysisId=result['id'])))
            english = render_report(store,incident['id'],locale='en')
            chinese = render_report(store,incident['id'],locale='zh-CN')
            self.assertNotRegex(''.join(ReportMarkup(english).text), r'[\u3400-\u9fff]')
            self.assertIn('Current status:Investigating', english)
            self.assertIn('Status change', english)
            self.assertIn('Anomaly interval', english)
            self.assertIn('当前状态：调查中', chinese)
            self.assertIn('稳健最大 Z 分数', chinese)
            self.assertEqual(english.count('<svg'),chinese.count('<svg'))
            store.incidents.update(incident['id'],dict(title='状态变更',conclusion='Status'))
            before = store.incidents.get(incident['id'])
            retained = render_report(store,incident['id'],locale='en')
            self.assertIn('状态变更',retained)
            self.assertIn('Status',retained)
            self.assertEqual(before,store.incidents.get(incident['id']))
        render_chart = localized_report(lambda: chart('Raw signal',[0,1],[dict(label='raw',values=[1,2])]))
        english_chart = render_chart(locale='en')
        self.assertNotRegex(''.join(ReportMarkup(english_chart).text),r'[\u3400-\u9fff]')
        self.assertIn('原始值（源数据未提供单位）',render_chart(locale='zh-CN'))

    def test_model_forecast_display_translates_without_changing_saved_results(self):
        with TemporaryDirectory() as directory:
            store=WorkspaceStore(Path(directory))
            workspace=store.create_workspace('Model language check')
            session=store.runtime.create(dict(workspaceId=workspace['id'],modelId='coupled-tanks',
                title='Tank trial',config=dict(duration=150,start=40.37,fault='pump_degradation',seed=7)))
            run=store.runtime.intervene(session['id'],dict(asOf=80,at=83.17,horizon=150,
                mode='known',hypothesis='pump_degradation',actions=['adjust_pump','open_valve']))
            incident=store.incidents.create(workspace['id'],dict(title='Tank investigation',
                source=dict(kind='simulation',simulationId=session['id'],windowStart=0,asOf=80)))
            store.incidents.add_link(incident['id'],dict(kind='run',simulationId=session['id'],runId=run['id']))
            english=render_report(store,incident['id'],locale='en')
            chinese=render_report(store,incident['id'],locale='zh-CN')
            self.assertNotRegex(''.join(ReportMarkup(english).text),r'[\u3400-\u9fff]')
            self.assertIn('Adjust inlet pump command',english)
            self.assertIn('调整进水泵指令',chinese)
            self.assertIn('实际液位峰值',chinese)
            self.assertIn('预测不确定性界限',chinese)
            self.assertEqual(english.count('<svg'),chinese.count('<svg'))
            self.assertEqual(run,store.runtime.run(session['id'],run['id']))


class IncidentReportingHTTPTests(IncidentHTTPFixture):
    def report(self, base, download=False, locale=None):
        params = []
        if download:
            params.append('download=1')
        if locale:
            params.append('lang=' + locale)
        with build_opener(ProxyHandler({})).open(
                f'http://127.0.0.1:{self.service.server_port}/api{base}/report.html' + ('?' + '&'.join(params) if params else '')) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('text/html', response.headers['Content-Type'])
            if download:
                self.assertIn('attachment;', response.headers['Content-Disposition'])
            return response.read().decode('utf-8')

    def csv_event(self):
        wid = self.workspace()
        dataset = self.request(f'/workspaces/{wid}/datasets', dict(csv=csv_with_excursions(), name='现场 CSV <A> & 温度'), expected=201)
        results = [self.analyze(wid, dataset['id'], method) for method in ('robust-maxz', 'pca-q')]
        event = self.request(f'/workspaces/{wid}/incidents', dict(title='反应器温升调查', description='真实保存内容 & <检查>',
            start_time=330, end_time=560, source=dict(kind='analysis', analysisId=results[0]['id'])), expected=201)
        base = f'/incidents/{event["id"]}'
        self.request(base + '/links', dict(kind='analysis', analysisId=results[1]['id']), expected=201)
        return wid, dataset, results, base

    def test_report_language_localizes_template_without_translating_saved_evidence(self):
        _, _, _, base = self.csv_event()
        # These deliberately match template translation keys.
        self.request(base, dict(title='事件调查报告', conclusion='状态'), method='PATCH')
        before = self.request(base)
        english = self.report(base, locale='en', download=True)
        chinese = self.report(base, locale='zh-CN')
        self.assertIn('<html lang="en">', english)
        self.assertIn('Incident investigation report', english)
        self.assertIn('Data, parameters and linked records', english)
        self.assertIn('事件调查报告', english)  # Saved title remains verbatim.
        self.assertIn('状态', english)  # Saved conclusion remains verbatim.
        self.assertIn('<html lang="zh-CN">', chinese)
        self.assertIn('附录. 数据、参数与关联记录', chinese)
        self.assertEqual(english.count('<svg'), chinese.count('<svg'))
        self.assertFalse(ReportMarkup(english).external)
        self.assertEqual(before, self.request(base))

    def test_csv_timeline_comparison_report_sources_and_service_restart(self):
        wid, dataset, results, base = self.csv_event()
        event = self.request(base)
        link_id = event['links'][0]['id']
        event = self.request(base + '/entries', dict(kind='hypothesis', title='冷却侧变化', content='待核查冷却水记录'), expected=201)
        hypothesis = event['entries'][0]['id']
        event = self.request(base + '/entries', dict(kind='evidence', title='温升证据', content='现场记录：<script>alert(1)</script> & 温度变化。',
            source_link_id=link_id, observed_at=350, hypothesis_id=hypothesis, stance='support'), expected=201)
        self.request(base + '/entries', dict(kind='evidence', title='进料稳定', content='未支持进料扰动解释', hypothesis_id=hypothesis, stance='oppose'), expected=201)
        self.request(base + '/entries', dict(kind='note', title='后续调查', content='继续核对现场记录'), expected=201)
        self.request(base, dict(status='investigating', conclusion='暂时支持冷却侧解释，尚未确认根因。'), method='PATCH')
        view = self.request(base + '/timeline')
        self.assertEqual(len(view['analyses']), 2)
        self.assertEqual(len(view['comparisons']), 1)
        self.assertEqual(view['primaryAxisId'], 'dataset:' + dataset['id'])
        alarms = [v for v in view['events'] if v['kind'] == 'alarm']
        self.assertEqual(len(alarms), sum(len(r['intervals']) for r in results))
        for alarm in alarms:
            original = next(r for r in results if r['id'] == alarm['analysisId'])['intervals'][alarm['intervalIndex']]
            self.assertEqual((alarm['start'], alarm['end'], alarm['peakTime'], alarm['peakScore']),
                             tuple(original[k] for k in ('start', 'end', 'peakTime', 'peakScore')))
        observation = next(v for v in view['events'] if v['title'] == '温升证据')
        self.assertEqual(observation['start'], 350)
        self.assertIn('T', observation['recordedAt'])
        self.assertTrue(view['comparisons'][0]['common'])
        single = self.request(base + '/timeline?analysis=' + results[0]['id'])
        self.assertEqual(single['comparisons'][0]['analysisIds'], [results[0]['id']])
        self.assertEqual(self.request(base + '/timeline?analysis=')['comparisons'], [])
        self.request(base + '/timeline?analysis=outside', expected=400)
        sample = self.request(f'/datasets/{dataset["id"]}/sample?at=350.2&signal=temperature&signal=feed')
        self.assertEqual(sample['time'], 350)
        saved = self.request(f'/datasets/{dataset["id"]}/series?start=349&end=350&signal=temperature')
        self.assertEqual(sample['values']['temperature'], saved['values']['temperature'][1])
        self.assertEqual(sample['previous']['temperature'], saved['values']['temperature'][0])
        html = self.report(base, download=True)
        parsed = ReportMarkup(html)
        self.assertFalse(parsed.external, 'HTML is self-contained and contains no runtime API dependencies')
        self.assertIn('现场 CSV <A> & 温度', ''.join(parsed.text))
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('暂时支持冷却侧解释，尚未确认根因。', html)
        self.assertIn('进料稳定', html)
        self.assertIn('真实保存内容 &amp; &lt;检查&gt;', html)
        self.assertNotIn('<h2>5. 模拟调查', html)
        self.assertIn('@page { size:A4', html)
        import re
        figures = re.findall(r'<svg\b.*?</svg>', html, re.S)
        self.assertGreaterEqual(len(figures), 9)
        for svg in figures:
            ElementTree.fromstring(svg)
        # Inspect real score and measurement paths rather than asserting a placeholder image exists.
        self.assertIn('异常分数与固定阈值', html)
        self.assertIn('原始变量趋势', html)
        self.assertIn('d="M', html)
        self.stop(); self.start()
        restored = self.request(base + '/timeline')
        for field in ('events', 'analyses', 'history'):
            self.assertEqual(restored[field], view[field])
        self.request(base, dict(status='resolved', conclusion='重启后结论：已核对冷却回路，保留后续复查。'), method='PATCH')
        refreshed = self.report(base)
        self.assertIn('重启后结论：已核对冷却回路，保留后续复查。', refreshed)
        history = self.request(base + '/timeline')['history']
        self.assertEqual(history[-1]['changes']['conclusion']['before'], '暂时支持冷却侧解释，尚未确认根因。')
        self.assertEqual(history[-1]['changes']['status']['after'], 'resolved')

    def test_datetime_origins_align_and_relative_datasets_do_not_merge(self):
        wid = self.workspace()
        raw = csv_with_excursions().splitlines()
        results, datasets = [], []
        for shift in (0, 10):
            origin = datetime(2026, 10, 24, tzinfo=timezone.utc) + timedelta(seconds=shift)
            csv = 'timestamp,temperature,feed,vibration\n' + '\n'.join(
                (origin + timedelta(seconds=int(row.split(',')[0]))).isoformat() + ',' + row.split(',', 1)[1] for row in raw[1:])
            d = self.request(f'/workspaces/{wid}/datasets', dict(csv=csv, timeColumn='timestamp', name=f'UTC {shift}'), expected=201)
            datasets.append(d)
            results.append(self.analyze(wid, d['id']))
        relative = self.request(f'/workspaces/{wid}/datasets', dict(csv=csv_with_excursions(), name='相对秒数'), expected=201)
        results.append(self.analyze(wid, relative['id']))
        incident = self.request(f'/workspaces/{wid}/incidents', dict(title='时间原点验证', source=dict(kind='analysis', analysisId=results[0]['id'])), expected=201)
        base = f'/incidents/{incident["id"]}'
        for result in results[1:]:
            self.request(base + '/links', dict(kind='analysis', analysisId=result['id']), expected=201)
        view = self.request(base + '/timeline')
        self.assertEqual(len(view['comparisons']), 2)
        utc = next(g for g in view['comparisons'] if g['axisId'] == 'utc')
        self.assertEqual(utc['analysisIds'], [r['id'] for r in results[:2]])
        for result, shift in zip(results, (0, 10, 0)):
            alarm = next(v for v in view['events'] if v.get('analysisId') == result['id'])
            expected_offset = datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp() + shift if result != results[-1] else 0
            self.assertEqual(alarm['start'], result['intervals'][0]['start'] + expected_offset)
        source = view['incident']['links'][1]
        event = self.request(base + '/entries', dict(kind='note', title='不同原点的人工观察', observed_at=350, source_link_id=source['id']), expected=201)
        note = event['entries'][0]
        # Existing PR #16 entries acquire their clock before unlinking too.
        with self.service.workspace_store.connect() as db:
            db.execute('UPDATE incident_entries SET observed_axis_key=NULL WHERE id=?', (note['id'],))
        self.request(base + f'/links/{source["id"]}', method='DELETE')
        preserved = next(v for v in self.request(base + '/timeline')['events'] if v.get('entryId') == note['id'])
        self.assertEqual(preserved['start'], datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp() + 360)
        self.assertEqual(preserved['axisId'], 'utc')
        self.assertIn('2026-10-24', self.report(base))

    def test_triplens_report_tools_forecasts_and_restorable_context(self):
        wid = self.workspace('TripLens 报告验证')
        session = self.request('/simulations', dict(workspaceId=wid, title='冷却阀模拟', config=dict(fault='cooling_valve', start=35, duration=180, step=.5, seed=418)), expected=201)
        sid = session['id']
        self.request(f'/simulations/{sid}/save', dict(workspaceId=wid))
        tool = self.request(f'/simulations/{sid}/tools', dict(asOf=93, windowStart=0, hypothesis='cooling_valve', calls=[dict(tool='sensor_consistency', args={})]))
        trial = self.request(f'/simulations/{sid}/interventions', dict(asOf=93, windowStart=0, hypothesis='cooling_valve', mode='known', at=96, horizon=200, actions=['feed_reduce', 'bypass'], parameters={'feedReduction': .3}))
        incident = self.request(f'/workspaces/{wid}/incidents', dict(title='冷却阀模拟调查', source=dict(kind='run', simulationId=sid, runId=tool['id'])), expected=201)
        base = f'/incidents/{incident["id"]}'
        self.request(base + '/links', dict(kind='run', simulationId=sid, runId=trial['id'], hypothesis='cooling_valve'), expected=201)
        view = self.request(base + '/timeline')
        experiment = next(v for v in view['events'] if v['kind'] == 'experiment')
        self.assertEqual(experiment['start'], 93)
        self.assertEqual(experiment['observationWindow'], [0, 93])
        self.assertEqual(experiment['actionAt'], 96)
        self.assertEqual(experiment['axisId'], 'simulation:' + sid)
        html = self.report(base)
        for content in ('模拟调查与干预方案比较', 'sensor_consistency', 'feed_reduce', 'bypass', '物理压力（kPa）', 'feedReduction', trial['id']):
            self.assertIn(content, html)
        self.assertTrue(f'{trial["result"]["branches"][0]["physicalPeak"]:.6g}' in html)
        self.stop(); self.start()
        saved = self.request(f'/simulations/{sid}/runs/{trial["id"]}')
        self.assertEqual(saved['request'], trial['request'])
        self.assertEqual(self.request(base + '/timeline')['events'], view['events'])


class IntervalComparisonTests(unittest.TestCase):
    def test_overlap_unique_point_alarms_and_unevaluated_windows(self):
        def analysis(identity, intervals, observed):
            return dict(id=identity, intervals=[dict(start=a, end=b) for a, b in intervals], observedSpans=observed)
        a = analysis('maxz', [(2, 6), (10, 10), (14, 16)], [[0, 20]])
        b = analysis('pca', [(4, 8), (10, 10)], [[1, 12]])
        compared = compare_intervals([a, b])
        self.assertIn(dict(start=4, end=6, kind='common', analysisIds=['maxz', 'pca']), compared['common'])
        self.assertIn(dict(start=10, end=10, kind='common', analysisIds=['maxz', 'pca']), compared['common'])
        self.assertEqual([(v['start'], v['end']) for v in compared['unique']], [(2, 4), (6, 8)])
        self.assertTrue(any(v['start'] == 14 and v['kind'] == 'uncompared' for v in compared['segments']))
        self.assertEqual(compared['firstAlarmSpread'], 2)
        touching = compare_intervals([analysis('a', [(2, 5)], [[0, 10]]), analysis('b', [(5, 8)], [[0, 10]])])
        self.assertIn(dict(start=5, end=5, kind='common', analysisIds=['a', 'b']), touching['common'])
        gaps = observed_spans(dict(times=[0, 1, 2, 3, 4], states=['normal', 'alarm', 'abstain', 'normal', 'normal']), 100)
        self.assertEqual(gaps, [[100, 101], [103, 104]])


if __name__ == '__main__':
    unittest.main()
