"""Numerical exports and a localized, portable summary of a saved assessment."""
from __future__ import annotations

import csv
from html import escape
from io import StringIO
import json

from .report_locale import localized_report, text as tr


def csv_text(value):
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def write_series(writer, kind, constraint, margin_unit, series):
    for time, value, margin, state, raw_state, segment in zip(
            series['times'], series['values'], series['margins'], series['states'], series['rawStates'], series['segmentIds']):
        writer.writerow((kind, csv_text(constraint['id']), time, value, csv_text(constraint['unit']), margin,
                         csv_text(margin_unit), state, raw_state, segment,
                         constraint.get('lower'), constraint.get('upper'),
                         constraint.get('warningLower'), constraint.get('warningUpper')))


def export_series(assessment):
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(('evidence', 'constraint_id', 'time_seconds', 'value', 'unit', 'margin', 'margin_unit', 'state', 'raw_state',
                     'segment_id', 'lower', 'upper', 'warning_lower', 'warning_upper'))
    for result in assessment['observed']:
        write_series(writer, 'observed', result['constraint'], result['marginUnit'], result['series'])
    forecast = assessment['forecast'] or {}
    constraints = {definition['id']: definition for definition in assessment['configuration']['constraints']}
    for result in forecast.get('constraints', []):
        if result.get('series'):
            write_series(writer, 'predicted', constraints[result['constraintId']], result['marginUnit'], result['series'])
    return output.getvalue()


def md(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.8g}'
    return escape(str(value)).replace('|', '&#124;').replace('\r', ' ').replace('\n', ' ')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(map(md, headers)) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |',
                      *('| ' + ' | '.join(map(md, row)) + ' |' for row in rows)])


@localized_report
def render_markdown(assessment):
    source, config = assessment['source'], assessment['configuration']
    output = [
        f"# {md(assessment['name'])}",
        table([tr('Dataset'), tr('Assessment created'), tr('Observation start (s)'), tr('Observed through (s)'),
               tr('Configuration revision')], [[source['datasetName'], assessment['createdAt'], source['observationStart'],
                                              source['observedThrough'], config.get('revision')]]),
        f"## {tr('Observed operating limits')}",
        table([tr('Constraint'), tr('Unit'), tr('State'), tr('Current margin'), tr('Minimum margin'),
               tr('Maximum exceedance'), tr('Violation duration (s)'), tr('Sample coverage'), tr('Time coverage')],
              [[r['constraint']['name'], r['marginUnit'], tr(r['current']['state']), r['current']['margin'],
                r['minimumMargin'], r['maximumExceedance'], r['violationDuration'],
                r['coverage']['sampleFraction'], r['coverage']['durationFraction']] for r in assessment['observed']]),
        table([tr('Constraint'), tr('State'), tr('Start (s)'), tr('End (s)'), tr('Duration (s)'), tr('Maximum exceedance')],
              [[r['constraint']['name'], tr(span['state']), span['start'], span['end'], span['duration'],
                span['maximumExceedance']] for r in assessment['observed'] for span in r['intervals']]),
        f"### {tr('Observed raw threshold breaches')}",
        table([tr('Constraint'), tr('Start (s)'), tr('End (s)'), tr('Maximum exceedance')],
              [[r['constraint']['name'], span['start'], span['end'], span['maximumExceedance']]
               for r in assessment['observed'] for span in r['rawViolationIntervals']]),
    ]
    forecast = assessment['forecast']
    if forecast:
        definitions = {definition['id']: definition for definition in config['constraints']}
        output.extend([
            f"## {tr('Predicted operating limits')}",
            md(tr(forecast.get('reason') or forecast['status'])),
            table([tr('Constraint'), tr('Unit'), tr('Status'), tr('Time to violation (s)'), tr('First crossing (s)'),
                   tr('Minimum margin'), tr('Violation duration (s)'), tr('Maximum exceedance')],
                  [[definitions[r['constraintId']]['name'], r['marginUnit'], tr(r['status']),
                    r.get('timeToViolation'), r.get('firstCrossingTime'), r.get('minimumMargin'),
                    r.get('violationDuration'), r.get('maximumExceedance')] for r in forecast.get('constraints', [])]),
            tr('Crossing times are conditional on the saved model and future input assumptions. '
               'Scenario fractions describe only the evaluated trajectories.'),
        ])
        if uncertainty := forecast.get('uncertainty'):
            output.extend([
                f"### {tr('Forecast scenario sensitivity')}",
                table([tr('Constraint'), tr('Evaluated scenarios'), tr('Unavailable scenarios'), tr('Violation fraction'),
                       tr('Earliest crossing (s)'), tr('Latest crossing (s)'), tr('Worst scenario margin')],
                      [[definitions[r['constraintId']]['name'], r['evaluatedScenarios'], r['unavailableScenarios'],
                        r['violationFraction'], r['earliestCrossingTime'], r['latestCrossingTime'], r['worstMargin']]
                       for r in uncertainty['constraints']]),
                table([tr('Constraint'), tr('Parameter'), tr('Lower endpoint margin'), tr('Upper endpoint margin')],
                      [[definitions[r['constraintId']]['name'], s['parameter'], s['lowerMargin'], s['upperMargin']]
                       for r in uncertainty['constraints'] for s in r['sensitivity']]),
            ])
    assumptions = dict(source=dict(datasetId=source['datasetId'], clock=source['clock'], model=source['model']),
                       configuration=config, forecastOptions=assessment['forecastOptions'])
    if forecast:
        assumptions.update(model=forecast.get('model'), forecastAssumptions=forecast.get('assumptions'),
                           inputMeasurements=forecast.get('inputMeasurements'))
    output.extend([f"## {tr('Source and assumptions')}",
                   '\x60\x60\x60json\n' + json.dumps(assumptions, ensure_ascii=False, indent=2) + '\n\x60\x60\x60'])
    return '\n\n'.join(output) + '\n'


def export(assessment, kind, locale):
    if kind == 'json':
        return json.dumps(assessment, ensure_ascii=False, allow_nan=False), 'json', 'application/json'
    if kind == 'csv':
        return export_series(assessment), 'csv', 'text/csv'
    if kind == 'markdown':
        return render_markdown(assessment, locale='zh-CN' if locale in ('zh', 'zh-CN') else 'en'), 'md', 'text/markdown'
    raise ValueError('Choose json, csv or markdown for the assessment export.')
