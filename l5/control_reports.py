"""Offline control reports reuse L5's escaped tables and embedded SVG plots."""
from .report_locale import fragment, localized_report, text as tr
from .reports import CSS, chart, e, n, table, technical


def numeric(value):
    return '—' if value is None else n(value)


@localized_report
def render_control_report(result):
    title=tr('Closed-loop control comparison')
    parts=[fragment('<!doctype html><html lang="en">')+f'<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(result["name"])} · L5</title><style>{CSS}</style></head><body>',
           fragment('<div class="toolbar"><button onclick="window.print()">Print / Save A4 PDF</button></div>'),
           '<main><div class="brand">L5 / CONTROL</div>',f'<h1>{e(result["name"])}</h1><h2>{e(title)}</h2>',
           f'<p>{e(result["id"])} · {e(result["createdAt"])} · {e(result["format"])}</p>',
           f'<p>{e(tr("Measured tracking and physical safety are evaluated separately. Null settling times mean the specified band and dwell were not achieved."))}</p>',
           table([tr('Metric')]+[tr(b['controller']) for b in result['results']],
                 [[e(tr(m['label'])+' ('+m['unit']+')')]+[e(numeric(b['metrics'][m['key']])) for b in result['results']] for m in result['metricDefinitions']])]
    times=[r['t'] for r in result['results'][0]['rows']]
    for key,label,unit in [('level1','Tank 1 measured level','m'),('level2','Tank 2 measured level','m'),('pump','Pump command','%'),('valve','Connection valve opening','fraction'),('error','Tank 2 tracking error','m')]:
        lines=[dict(label=tr(b['controller']),values=[r[key] for r in b['rows']]) for b in result['results']]
        if key=='level2': lines.append(dict(label=tr('Tank 2 reference'),values=[r['reference'] for r in result['results'][0]['rows']]))
        if key in ('level1','level2'):
            j=key[-1]
            for bound in ('Min','Max'):
                lines.append(dict(label=tr('Operational level bounds')+' '+bound,values=[result['protocol']['constraints'][f'level{bound}{j}']]*len(times)))
        plot_times=times
        if key in ('pump','valve','level2'):
            plot_times=[t for i,t in enumerate(times) for _ in range(1 if i==0 else 2)]
            for line in lines:
                original=line['values'];held=key in ('pump','valve') or line['label']==tr('Tank 2 reference')
                line['values']=[v for i,value in enumerate(original) for v in ([value] if i==0 else [original[i-1] if held else value,value])]
        parts.append(chart(tr(label),plot_times,lines,unit=unit))
    parts.extend([f'<h2>{e(tr("Model, protocol and numerical evidence"))}</h2>',
                  f'<p>{e(tr("Hard actuator limits; soft predicted level bounds. Physical safety is not guaranteed by the local model."))}</p>',
                  technical({k:result[k] for k in ('modelId','modelVersion','config','protocol','scenarioSnapshot','solver','noiseFingerprint')})])
    for branch in result['results']:
        parts.extend([f'<h3>{e(tr(branch["controller"]))}</h3>',technical(dict(settings=branch['settings'],metrics=branch['metrics'])),
                      table([tr('Time (s)'),tr('Solver status'),tr('Iterations'),tr('Primal residual'),tr('Stationarity residual'),tr('Decision time (ms)')],
                            [[e(numeric(d['time'])),e(tr(d['solver']['status'])),e(d['solver'].get('iterations','—')),
                              e(numeric(d['solver'].get('primalResidual'))),e(numeric(d['solver'].get('stationarityResidual'))),e(numeric(d['durationMs']))] for d in branch['decisions']])])
    parts.append('</main></body></html>')
    return ''.join(parts)
