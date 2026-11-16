"""Printable, offline summaries of saved recovery studies."""
from .report_locale import fragment as r, localized_report, text
from .reports import CSS, chart, e, n, table, technical
from .recovery_studies import COLUMNS


def render(study, locale='en'):
    return _render(study, locale='zh-CN' if locale == 'zh-CN' else 'en')


@localized_report
def _render(study):
    analysis = study['analysis']
    numerical = analysis['numerical']
    parts = [
        r('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'),
        e(study['name']), '</title><style>', CSS, '</style></head><body>',
        r('<div class="toolbar"><button onclick="window.print()">Print / Save A4 PDF</button></div>'),
        '<main><div class="brand">', e(text('reach.nav')), '</div><h1>', e(study['name']),
        f"</h1><p>{e(study['id'])} · {e(study['createdAt'])}</p>",
        '<p>', e(text('reach.scope')), '</p>',
        '<h2>', e(text('reach.assumptions')), '</h2>',
        technical(dict(config=analysis['config'], numerical={k: v for k, v in numerical.items() if k != 'axes'},
                       modelVersion=analysis['modelVersion'], scenario=study['scenario'], incident=study['incident'])),
    ]
    result = study['evaluation']
    if result:
        parts += ['<h2>', e(text('reach.comparison')), '</h2>',
                  technical(dict(initial=result['initial'], classification=result['classification'],
                                 integrationStep=result['integrationStep'])),
                  table([text(f'reach.{k}') for k in ('strategy', 'status', 'recoveryTime', 'margin', 'movement', 'effort', 'violations')], [
                      [e(text(f"reach.{run['strategy']}")), e(text(f"reach.{run['status']}")),
                       e(n(run['recoverySeconds'])), e(n(run['minimumMargin'])),
                       e(' / '.join(n(v) for v in run['movement'])), e(' / '.join(n(v) for v in run['effort'])), e(len(run['violations']))]
                      for run in result['replays'].values()])]
        for key, run in result['replays'].items():
            parts += ['<h3>', e(text(f'reach.{key}')), '</h3>']
            for signal, key in (('level1', 'level1'), ('level2', 'level2'), ('safetyMargin', 'margin')):
                _, unit = COLUMNS[signal]
                label = text(f'reach.{key}')
                rows = run['trajectory']
                parts.append(chart(label, [row['t'] for row in rows],
                                   [dict(label=label, values=[row[signal] for row in rows])], unit=unit))
            parts.append(technical(dict(actions=run['actions'], minimumMargin=run['minimumMargin'],
                                        violationSamples=len(run['violations']))))
    return ''.join([*parts, '</main></body></html>'])
