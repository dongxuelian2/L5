"""Saved numerical diagnostic evidence inside the existing incident report."""
from __future__ import annotations

from .report_locale import text


def diagnostic_sections(store, incident, axes):
    from .reports import chart, e, n, parameters, table, technical
    from .incident_timeline import source_clock
    parts = []
    for link in incident['links']:
        if link['kind'] != 'sensor-health':
            continue
        result = store.sensor_health.get(link['reference_id'])
        parts.append(f'<h2 id="source-{e(link["id"])}">{e(text("Sensor health"))} · {e(result["name"])}</h2>')
        parts.append(parameters(dict(version=result['version'], sourceDigest=result['sourceDigest'], **result['config'])))
        parts.append('<p>' + e(text('Rankings compare residual corrections under a single-fault assumption. Fit scores are not causal probabilities.')) + '</p>')
        clock = source_clock(store, link)
        times = [t+clock['offset'] for t in result['times']]
        axis = axes.get(clock['axisId'])
        episodes = [result['episodes'][int(link['selector'])]] if link['selector'] else result['episodes']
        parts.append(table([text('Start'), text('End'), text('Peak severity'), text('Assessment')],
            [[n(v['start']), n(v['end']), n(v['severity']), e(text(v['assessment']))] for v in episodes]))
        for signal in result['config']['signals']:
            lines = [dict(label=signal, values=result['signals'][signal]['observed'], segmentIds=result['signals'][signal]['segmentIds'])]
            if result['physical'] and signal in result['physical']['expected']:
                lines.append(dict(label=text('Expected from related measurements'), values=result['physical']['expected'][signal], segmentIds=result['physical']['segmentIds'][signal], color='#536daf'))
            elif any(v['target'] == signal for v in result['relationships']):
                relation = next(v for v in result['relationships'] if v['target'] == signal)
                lines.append(dict(label=text('Expected from related measurements'), values=relation['expected'], segmentIds=result['signals'][relation['predictor']]['segmentIds'], color='#536daf'))
            parts.append(chart(signal, times, lines, axis=axis))
        if result['physical']:
            for residual in result['physical']['residuals']:
                parts.append(chart(text(residual['key']), times, [dict(label=text(residual['key']), values=residual['values'], segmentIds=residual.get('segmentIds'))], axis=axis, threshold=residual['threshold'], unit=residual['unit']))
            parts.append('<p>' + e(' · '.join(text(v) for v in result['physical']['assumptions'])) + '</p>')
        for episode in episodes:
            parts.append(table([text('Candidate explanation'), text('Residual fit error'), text('Penalized error'), text('Improvement')],
                [[e(text(v['key'])), n(v['fitError']), n(v['penalizedError']), n(v['improvement'])] for v in episode['candidates']]))
            selected = [v for v in result['indicators'] if v['id'] in episode['indicatorIds']]
            parts.append(technical(dict(episode=episode, indicators=[{k: v for k, v in i.items() if k != 'scores'} for i in selected])))
        parts.append('<p>' + e(' · '.join(text(v) for v in result['limitations'])) + '</p>')
        parts.append('<details><summary>' + e(text('Saved reference and reproducibility')) + '</summary>' + technical(result['reference']) + '</details>')
    return parts
