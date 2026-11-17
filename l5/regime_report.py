"""Offline HTML report from an immutable regime run."""
from __future__ import annotations

import numpy as np

from .data_quality import segment_ids
from .regime_workspace import normalized_score
from .reports import CSS, chart, e, n, table, technical


def render_regime_report(run):
    fitted, decisions, times = run['model'], run['decisions'], run['times']
    modes = {m['id']: m['label'] for m in fitted['config']['modes']}

    def mode_label(mode_id):
        return modes.get(mode_id, 'Unresolved')

    def seconds(value):
        return n(None) if value is None else format(value, '.16g')

    heading = 'Operating regime monitoring report'
    results = [f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(heading)} · {e(run['name'])}</title>
<style>{CSS}</style></head><body><main><div class="brand">L5 / {e(heading)}</div><h1>{e(run['name'])}</h1>
<p>{e(run['source']['name'])} · {seconds(times[0])}–{seconds(times[-1])} s · {e(run['createdAt'])}</p>''']
    protocol = ('Chronological holdout from a training dataset'
                if run['protocol'] == 'chronological-holdout' else 'Distinct evaluation dataset')
    results.append(f"<p>{e(protocol)} · {e('Dataset-native seconds')}</p>")
    results.append(f"<h2>{e('Detector comparison')}</h2>")
    methods = [('regime', '', 'Regime-aware', '#b45742'),
               ('global', 'global', 'Global', '#246b63'),
               ('single', 'single', 'Single regime', '#3b78a1')]
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
    results.append(table(['Detector', 'Evaluated samples', 'Alarm samples',
                          'Alarm episodes', 'First alarm (s)',
                          'Labelled events detected / total',
                          'False alarm episodes on normal labels'], rows))
    results.append(chart('Detector scores and confirmed alarms', times, lines,
                         threshold=0, intervals=run['intervals'], unit='log1p(score) − log1p(threshold)'))
    results.append(f"<h2>{e('Recognition and transitions')}</h2>")
    summary = run['summary']
    results.append(table(['Samples', 'Ambiguous', 'Unrecognized',
                          'Insufficient data', 'Confirmed changes'],
                         [[n(summary[key]) for key in ('samples', 'ambiguousSamples', 'unrecognizedSamples',
                                                       'insufficientSamples', 'confirmedTransitions')]]))
    outcomes = {'confirmed': 'Confirmed', 'transient': 'Transient', 'pending': 'Unresolved'}
    results.append(table(['From', 'Candidate mode', 'First evidence (s)',
                          'Candidate (s)', 'Confirmation (s)', 'Outcome'],
                         [[e(mode_label(x['fromMode'])), e(mode_label(x['toMode'])), seconds(x['startTime']),
                           seconds(x['candidateTime']), seconds(x['confirmedTime']), e(outcomes.get(x['outcome'], x['outcome']))]
                          for x in run['transitions']]))
    results.append(f"<h2>{e('Alarm evidence')}</h2>")
    kinds = {'mode': 'Within mode', 'transition': 'During transition',
             'unknown': 'Unrecognized condition'}
    results.append(table(['Start (s)', 'End (s)', 'Detector mode',
                          'Condition', 'Peak / threshold', 'Top signals'],
                         [[seconds(i['start']), seconds(i['end']), e(mode_label(i['mode'])), e(kinds[i['kind']]),
                           f"{n(i['peakScore'])} / {n(i['threshold'])}", e(', '.join(i['signals']))] for i in run['intervals']]))
    results.append(f"<h2>{e('Frozen model and source provenance')}</h2>")
    results.append(table(['Regime', 'Fit samples', 'Calibration samples',
                          'Recognition distance limit', 'Detector',
                          'Alarm threshold'],
                         [[e(mode_label(mode_id)), n(m['fitSamples']), n(m['calibrationSamples']), n(m['distanceThreshold']),
                           e(m['detector']['algorithm']), n(m['detector']['threshold'])]
                          for mode_id, m in fitted['model']['modes'].items()]))
    sources = {**fitted['sources'], run['datasetId']: run['source']}
    results.append(technical(dict(modelId=fitted['id'], config=fitted['config'], evaluation=run['evaluation'],
                                  sources={key: {field: source[field] for field in ('name', 'sha256', 'sourceCsvSha256')}
                                           for key, source in sources.items()})))
    results.append('</main></body></html>')
    return ''.join(results)
