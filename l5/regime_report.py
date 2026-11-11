"""Offline HTML report from an immutable regime run."""
from __future__ import annotations

import numpy as np

from .data_quality import segment_ids
from .regime_workspace import normalized_score
from .report_locale import localized_report
from .reports import CSS, chart, e, n, table, technical


@localized_report
def _report(run, language):
    def t(english, chinese):
        return chinese if language == 'zh-CN' else english

    fitted, decisions, times = run['model'], run['decisions'], run['times']
    modes = {m['id']: m['label'] for m in fitted['config']['modes']}

    def mode_label(mode_id):
        return modes.get(mode_id, t('Unresolved', '未确定'))

    def seconds(value):
        return n(None) if value is None else format(value, '.16g')

    heading = t('Operating regime monitoring report', '运行工况监测报告')
    results = [f'''<!doctype html><html lang="{language}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(heading)} · {e(run['name'])}</title>
<style>{CSS}</style></head><body><main><div class="brand">L5 / {e(heading)}</div><h1>{e(run['name'])}</h1>
<p>{e(run['source']['name'])} · {seconds(times[0])}–{seconds(times[-1])} s · {e(run['createdAt'])}</p>''']
    protocol = (t('Chronological holdout from a training dataset', '训练数据集的时间顺序留出')
                if run['protocol'] == 'chronological-holdout' else t('Distinct evaluation dataset', '单独的评估数据集'))
    results.append(f"<p>{e(protocol)} · {e(t('Dataset-native seconds', '数据集原生秒数'))}</p>")
    results.append(f"<h2>{e(t('Detector comparison', '检测器比较'))}</h2>")
    methods = [('regime', '', t('Regime-aware', '工况感知'), '#b45742'),
               ('global', 'global', t('Global', '全局'), '#246b63'),
               ('single', 'single', t('Single regime', '单一工况'), '#3b78a1')]
    rows, lines = [], []
    for key, prefix, label, color in methods:
        behavior = run['metrics'][key]['behavior']
        labelled = run['metrics'][key]['labelled']
        events = run['metrics'][key]['detection']['windows']
        false_events = labelled['event']['falseAlarmEvents'] if labelled else None
        hits = f"{events['eventual']['detectedEvents']} / {events['eventual']['totalEvents']}" if events else '—'
        rows.append([e(label), n(behavior['validSamples']), n(behavior['alarmSamples']),
                     n(behavior['alarmIntervalCount']), seconds(behavior['firstDetection']), e(hits),
                     n(false_events) if false_events is not None else '—'])
        score_key, threshold_key = (prefix + 'Score', prefix + 'Threshold') if prefix else ('score', 'threshold')
        scores = [None if row[score_key] is None else normalized_score(row[score_key], row[threshold_key]) for row in decisions]
        segments = segment_ids(np.asarray(times), np.asarray(scores, dtype=float), run['gapThreshold']).tolist()
        lines.append(dict(label=label, values=scores, color=color, segmentIds=segments))
    results.append(table([t('Detector', '检测器'), t('Evaluated samples', '已评估样本'), t('Alarm samples', '报警样本'),
                          t('Alarm episodes', '报警区间'), t('First alarm (s)', '首次报警（秒）'),
                          t('Labelled events detected / total', '检出／全部标注事件'),
                          t('False alarm episodes on normal labels', '正常标注区间内的误报')], rows))
    results.append(chart(t('Detector scores and confirmed alarms', '检测分数与已确认报警'), times, lines,
                         threshold=0, intervals=run['intervals'], unit='log1p(score) − log1p(threshold)'))
    results.append(f"<h2>{e(t('Recognition and transitions', '工况识别与切换'))}</h2>")
    summary = run['summary']
    results.append(table([t('Samples', '样本数'), t('Ambiguous', '歧义'), t('Unrecognized', '未识别'),
                          t('Insufficient data', '数据不足'), t('Confirmed changes', '已确认切换')],
                         [[n(summary[key]) for key in ('samples', 'ambiguousSamples', 'unrecognizedSamples',
                                                       'insufficientSamples', 'confirmedTransitions')]]))
    outcomes = {'confirmed': t('Confirmed', '已确认'), 'transient': t('Transient', '短暂'), 'pending': t('Unresolved', '未确定')}
    results.append(table([t('From', '起始工况'), t('Candidate mode', '候选工况'), t('First evidence (s)', '最早证据（秒）'),
                          t('Candidate (s)', '候选出现（秒）'), t('Confirmation (s)', '确认时刻（秒）'), t('Outcome', '结果')],
                         [[e(mode_label(x['fromMode'])), e(mode_label(x['toMode'])), seconds(x['startTime']),
                           seconds(x['candidateTime']), seconds(x['confirmedTime']), e(outcomes.get(x['outcome'], x['outcome']))]
                          for x in run['transitions']]))
    results.append(f"<h2>{e(t('Alarm evidence', '报警证据'))}</h2>")
    kinds = {'mode': t('Within mode', '工况内'), 'transition': t('During transition', '切换中'),
             'unknown': t('Unrecognized condition', '未识别状态')}
    results.append(table([t('Start (s)', '起点（秒）'), t('End (s)', '终点（秒）'), t('Detector mode', '检测器工况'),
                          t('Condition', '状态'), t('Peak / threshold', '峰值／阈值'), t('Top signals', '主要信号')],
                         [[seconds(i['start']), seconds(i['end']), e(mode_label(i['mode'])), e(kinds[i['kind']]),
                           f"{n(i['peakScore'])} / {n(i['threshold'])}", e(', '.join(i['signals']))] for i in run['intervals']]))
    results.append(f"<h2>{e(t('Frozen model and source provenance', '冻结模型与来源追溯'))}</h2>")
    results.append(table([t('Regime', '工况'), t('Fit samples', '拟合样本'), t('Calibration samples', '校准样本'),
                          t('Recognition distance limit', '识别距离阈值'), t('Detector', '检测器'),
                          t('Alarm threshold', '报警阈值')],
                         [[e(mode_label(mode_id)), n(m['fitSamples']), n(m['calibrationSamples']), n(m['distanceThreshold']),
                           e(m['detector']['algorithm']), n(m['detector']['threshold'])]
                          for mode_id, m in fitted['model']['modes'].items()]))
    sources = {**fitted['sources'], run['datasetId']: run['source']}
    results.append(technical(dict(modelId=fitted['id'], config=fitted['config'], evaluation=run['evaluation'],
                                  sources={key: {field: source[field] for field in ('name', 'sha256', 'sourceCsvSha256')}
                                           for key, source in sources.items()})))
    results.append('</main></body></html>')
    return ''.join(results)


def render_regime_report(run, *, locale='en'):
    language = 'zh-CN' if locale == 'zh-CN' else 'en'
    return _report(run, language, locale=language)
