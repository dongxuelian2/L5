"""Numerical exports and a localized, portable summary of a saved assessment."""
from __future__ import annotations

import csv
from html import escape
from io import StringIO
import json

from .labels import display_label


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


def render_markdown(assessment):
    source, config = assessment['source'], assessment['configuration']
    output = [
        f"# {md(assessment['name'])}",
        table(['Dataset', 'Assessment created', 'Observation start (s)', 'Observed through (s)',
               'Configuration revision'], [[source['datasetName'], assessment['createdAt'], source['observationStart'],
                                              source['observedThrough'], config.get('revision')]]),
        f"## Observed operating limits",
        table(['Constraint', 'Unit', 'State', 'Current margin', 'Minimum margin',
               'Maximum exceedance', 'Violation duration (s)', 'Sample coverage', 'Time coverage'],
              [[r['constraint']['name'], r['marginUnit'], display_label(r['current']['state']), r['current']['margin'],
                r['minimumMargin'], r['maximumExceedance'], r['violationDuration'],
                r['coverage']['sampleFraction'], r['coverage']['durationFraction']] for r in assessment['observed']]),
        table(['Constraint', 'State', 'Start (s)', 'End (s)', 'Duration (s)', 'Maximum exceedance'],
              [[r['constraint']['name'], display_label(span['state']), span['start'], span['end'], span['duration'],
                span['maximumExceedance']] for r in assessment['observed'] for span in r['intervals']]),
        f"### Observed raw threshold breaches",
        table(['Constraint', 'Start (s)', 'End (s)', 'Maximum exceedance'],
              [[r['constraint']['name'], span['start'], span['end'], span['maximumExceedance']]
               for r in assessment['observed'] for span in r['rawViolationIntervals']]),
    ]
    forecast = assessment['forecast']
    if forecast:
        definitions = {definition['id']: definition for definition in config['constraints']}
        output.extend([
            f"## Predicted operating limits",
            md(display_label(forecast.get('reason') or forecast['status'])),
            table(['Constraint', 'Unit', 'Status', 'Time to violation (s)', 'First crossing (s)',
                   'Minimum margin', 'Violation duration (s)', 'Maximum exceedance'],
                  [[definitions[r['constraintId']]['name'], r['marginUnit'], display_label(r['status']),
                    r.get('timeToViolation'), r.get('firstCrossingTime'), r.get('minimumMargin'),
                    r.get('violationDuration'), r.get('maximumExceedance')] for r in forecast.get('constraints', [])]),
            'Crossing times are conditional on the saved model and future input assumptions. Scenario fractions describe only the evaluated trajectories.',
        ])
        if uncertainty := forecast.get('uncertainty'):
            output.extend([
                f"### Forecast scenario sensitivity",
                table(['Constraint', 'Evaluated scenarios', 'Unavailable scenarios', 'Violation fraction',
                       'Earliest crossing (s)', 'Latest crossing (s)', 'Worst scenario margin'],
                      [[definitions[r['constraintId']]['name'], r['evaluatedScenarios'], r['unavailableScenarios'],
                        r['violationFraction'], r['earliestCrossingTime'], r['latestCrossingTime'], r['worstMargin']]
                       for r in uncertainty['constraints']]),
                table(['Constraint', 'Parameter', 'Lower endpoint margin', 'Upper endpoint margin'],
                      [[definitions[r['constraintId']]['name'], s['parameter'], s['lowerMargin'], s['upperMargin']]
                       for r in uncertainty['constraints'] for s in r['sensitivity']]),
            ])
    assumptions = dict(source=dict(datasetId=source['datasetId'], clock=source['clock'], model=source['model']),
                       configuration=config, forecastOptions=assessment['forecastOptions'])
    if forecast:
        assumptions.update(model=forecast.get('model'), forecastAssumptions=forecast.get('assumptions'),
                           inputMeasurements=forecast.get('inputMeasurements'))
    output.extend([f"## Source and assumptions",
                   '\x60\x60\x60json\n' + json.dumps(assumptions, ensure_ascii=False, indent=2) + '\n\x60\x60\x60'])
    return '\n\n'.join(output) + '\n'


def export(assessment, kind):
    if kind == 'json':
        return json.dumps(assessment, ensure_ascii=False, allow_nan=False), 'json', 'application/json'
    if kind == 'csv':
        return export_series(assessment), 'csv', 'text/csv'
    if kind == 'markdown':
        return render_markdown(assessment), 'md', 'text/markdown'
    raise ValueError('Choose json, csv or markdown for the assessment export.')
