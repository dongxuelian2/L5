"""Self-contained alarm reports with the saved grouping and operator history."""
from datetime import datetime, timedelta, timezone

from .reports import CSS, e, n, table


REASONS = {
    'shared-signal': 'Shared source signal',
    'explicit-relationship': 'Explicit signal relationship',
    'shared-equipment': 'Shared equipment',
    'detector-agreement': 'Detector agreement',
    'repeat': 'Repeated alarm from the same source',
}


def relationship_text(relation):
    left, right = relation['leftId'], relation['rightId']
    temporal = 'Temporal overlap' if relation['temporal'] == 'overlap' else f"Temporal gap {n(relation['gapSeconds'])} s"
    reasons = ', '.join(REASONS.get(reason, reason) for reason in relation['reasons'])
    def signal(source):
        return f"{source['signal']} [{source['datasetId']}]"

    signals = ', '.join(signal(s) for s in relation['signals'])
    pairs = ', '.join(f"{signal(p['left'])} ↔ {signal(p['right'])}" for p in relation.get('explicitPairs', []))
    return ' · '.join(value for value in (f'{left} ↔ {right}', temporal, reasons, signals, pairs, ', '.join(relation['equipment'])) if value)


def render_alarm_report(view):
    def timestamp(value, axis):
        if axis['origin']:
            try:
                stamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=value)
                return stamp.isoformat(timespec='milliseconds').replace('+00:00', ' UTC')
            except OverflowError:
                return f'{value} s UTC'
        return n(value) + ' s'

    title = 'Alarm management report'
    axes = {a['id']: a for a in view['axes']}
    events = {v['id']: v for v in view['events']}
    priority = {p['id']: p['label'] for p in view['policy']['priorities']}
    kinds = {
        'acknowledge': 'Acknowledge', 'shelve': 'Shelve',
        'unshelve': 'Unshelve', 'note': 'Note',
        'incident': 'Link incident',
    }
    measured = {'active': 'Active', 'cleared': 'Cleared', 'unknown': 'Unknown'}
    parts = [f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · {e(view['name'])}</title>
        <style>{CSS}td {{overflow-wrap:anywhere}} .prose {{white-space:pre-wrap}}</style></head><body><main>
        <div class="brand">L5 / {e(title)}</div><h1>{e(view['name'])}</h1>
        <div class="meta"><span>{e(view['id'])}</span><span>{e(view['asOf'])}</span></div>''',
        '<p class="muted">Groups reflect timing and configured signal or equipment relationships.</p>',
        f"<h2>{e('Alarm workload')}</h2><p>"
        f"{e('Raw events')} {view['eventCount']} · {e('Correlated groups')} {view['groupCount']}</p>",
        '<p class="muted">' + e('Arrivals count event starts. Hourly rates use the full configured window as denominator. Acknowledgement delay starts at session creation.') + '</p>']
    for metric in view['flood']['axes']:
        axis = axes[metric['axisId']]
        label = 'UTC absolute time' if axis['origin'] else axis['label']
        parts.append(f"<h3>{e(label)} · {e(n(metric['windowSeconds']))} s</h3>")
        parts.append(table(['Peak arrivals per window', 'Peak arrivals / hour',
                             'Peak concurrency', 'Repeated events',
                             'Mean duration (s)', 'Mean acknowledgement delay (s)'],
            [[e(n(metric[key])) if metric[key] is not None else '—' for key in ('peakArrivalCount', 'peakArrivalsPerHour',
                'peakConcurrent', 'repeatedEventCount', 'meanDurationSeconds', 'meanAcknowledgementDelaySeconds')]]))
        parts.append(table(['Window start', 'Window end', 'Event arrivals',
                             'Group arrivals', 'Peak concurrency', 'Windows'],
            [[e(timestamp(b['start'], axis)), e(timestamp(b['end'], axis)), str(b['arrivals']), str(b['groupArrivals']),
              str(b['peakConcurrent']), str(b.get('windowCount', 1))] for b in metric['bins']]))
    parts.append(f"<h2>{e('Correlated groups and grouping evidence')}</h2>")
    for group in view['groups']:
        axis = axes[group['axisId']]
        start, end = (timestamp(group[k], axis) for k in ('start', 'end'))
        members = ' '.join(f'<li><a href="#event-{e(key)}">{e(events[key]["analysisName"])} · {e(key)}</a></li>'
                           for key in group['eventIds'])
        relationships = ''.join('<li>' + e(relationship_text(rel)) + '</li>' for rel in group['relationships'])
        parts.append(f"<details><summary>{e(start)} → {e(end)} · {e(priority[group['priority']])} · {len(group['eventIds'])}"
                     f"</summary><p>{e(group['id'])} · {e(group['axisId'])}</p><ul>{members}</ul><ul>{relationships}</ul></details>")
    parts.append(f"<h2>{e('Source alarms')}</h2>")
    parts.append(table(['Dataset / analysis', 'Observation time', 'Measured state',
                         'Priority', 'Peak / threshold', 'Signals',
                         'Acknowledged / shelved until'], [
        [f"<span id=\"event-{e(v['id'])}\">{e(v['datasetName'])} · {e(v['analysisName'])}</span><br>{e(v['id'])}",
         e(timestamp(v['start'], axes[v['axisId']])) + ' → ' + e(timestamp(v['end'], axes[v['axisId']])),
         e(measured[v['measuredState']]), e(priority[v['priority']]), e(n(v['peakScore'])) + ' / ' + e(n(v['threshold'])),
         e(', '.join(v['signals'])), e(v['operator']['acknowledgedAt'] or '—') + ' / ' + e(v['operator']['shelvedUntil'] or '—')]
        for v in view['events']]))
    parts.append(f"<h2>{e('Operator history')}</h2>")
    parts.append(table(['Recorded time (UTC)', 'Operator', 'Action',
                         'Event or group ID', 'Details'], [
        [e(a['recordedAt']), e(a['actor']), e(kinds[a['kind']]), e(a.get('eventId') or a.get('groupId')),
         '<span class="prose">' + e('\n'.join(a[k] for k in ('note', 'expiresAt', 'incidentId') if k in a)) + '</span>']
        for a in view['audit']]))
    parts.append('</main></body></html>')
    return ''.join(parts)
