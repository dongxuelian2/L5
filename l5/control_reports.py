"""Offline control reports reuse L5's escaped tables and embedded SVG plots."""
from .labels import display_label
from .reports import CSS, chart, e, n, table, technical


def numeric(value):
    return '—' if value is None else n(value)


def render_control_report(result):
    title='Closed-loop control comparison'
    parts=['<!doctype html><html lang="en">'+f'<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(result["name"])} · L5</title><style>{CSS}</style></head><body>',
           '<div class="toolbar"><button onclick="window.print()">Print / Save A4 PDF</button></div>',
           '<main><div class="brand">L5 / CONTROL</div>',f'<h1>{e(result["name"])}</h1><h2>{e(title)}</h2>',
           f'<p>{e(result["id"])} · {e(result["createdAt"])} · {e(result["format"])}</p>',
           f'<p>{e("Measured tracking and physical safety are evaluated separately. Null settling times mean the specified band and dwell were not achieved.")}</p>',
           table(['Metric']+[display_label(b['controller']) for b in result['results']],
                 [[e(display_label(m['label'])+' ('+m['unit']+')')]+[e(numeric(b['metrics'][m['key']])) for b in result['results']] for m in result['metricDefinitions']])]
    times=[r['t'] for r in result['results'][0]['rows']]
    for key,label,unit in [('level1','Tank 1 measured level','m'),('level2','Tank 2 measured level','m'),('pump','Pump command','%'),('valve','Connection valve opening','fraction'),('error','Tank 2 tracking error','m')]:
        lines=[dict(label=display_label(b['controller']),values=[r[key] for r in b['rows']]) for b in result['results']]
        if key=='level2': lines.append(dict(label='Tank 2 reference',values=[r['reference'] for r in result['results'][0]['rows']]))
        if key in ('level1','level2'):
            j=key[-1]
            for bound in ('Min','Max'):
                lines.append(dict(label='Operational level bounds'+' '+bound,values=[result['protocol']['constraints'][f'level{bound}{j}']]*len(times)))
        plot_times=times
        if key in ('pump','valve','level2'):
            plot_times=[t for i,t in enumerate(times) for _ in range(1 if i==0 else 2)]
            for line in lines:
                original=line['values'];held=key in ('pump','valve') or line['label']=='Tank 2 reference'
                line['values']=[v for i,value in enumerate(original) for v in ([value] if i==0 else [original[i-1] if held else value,value])]
        parts.append(chart(display_label(label),plot_times,lines,unit=unit))
    parts.extend([f'<h2>{e("Model, protocol and numerical evidence")}</h2>',
                  f'<p>{e("The simulation applies hard actuator limits and soft predicted level bounds.")}</p>',
                  technical({k:result[k] for k in ('modelId','modelVersion','config','protocol','scenarioSnapshot','solver')})])
    for branch in result['results']:
        parts.extend([f'<h3>{e(display_label(branch["controller"]))}</h3>',technical(dict(settings=branch['settings'],metrics=branch['metrics'])),
                      table(['Time (s)','Solver status','Iterations','Primal residual','Stationarity residual','Decision time (ms)'],
                            [[e(numeric(d['time'])),e(display_label(d['solver']['status'])),e(d['solver'].get('iterations','—')),
                              e(numeric(d['solver'].get('primalResidual'))),e(numeric(d['solver'].get('stationarityResidual'))),e(numeric(d['durationMs']))] for d in branch['decisions']])])
    parts.append('</main></body></html>')
    return ''.join(parts)
