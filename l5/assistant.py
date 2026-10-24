"""A small deterministic tool interface with an optional evidence summarizer."""
import json
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from simulation.platform import FAULTS, KEYS, META, diagnose, run_tools


def local_brief(prompt, context):
    rows = context['rows']
    calls = context.get('calls')
    if not calls:
        text = prompt.lower()
        signal = next((k for k in KEYS if k in text or META[k]['tag'].lower() in text), None)
        tool = next((name for word,name in [('alarm','inspect_alarm_history'), ('报警','inspect_alarm_history'),
                    ('controller','inspect_controller'), ('控制','inspect_controller'),
                    ('sensor','sensor_consistency'), ('传感器','sensor_consistency'),
                    ('path','trace_downstream'), ('传播','trace_downstream'),
                    ('next','recommend_next_measurement'), ('下一步','recommend_next_measurement')]
                     if word in text), None)
        calls = [dict(tool=tool, args={})] if tool else [dict(tool='inspect_signal_window', args={'signal':signal})] if signal else [dict(tool='compare_hypotheses', args={})]
    trace = run_tools(rows, calls)
    diagnosis = diagnose(rows)
    leader = diagnosis['candidates'][0]
    return dict(schemaVersion=2, incidentId=context['id'], provider='local', prompt=prompt,
                observedThrough=rows[-1]['t'], candidateId=leader['id'], evidenceTags=list(diagnosis['detections']),
                summary=f"Observed {len(rows)} samples through {rows[-1]['t']:g}s. Status: {diagnosis['status']}. Leading support: {leader['name']} ({leader['score']}/100).",
                limitation='Local keyword routing executes the tools shown below. Select a tool explicitly for precise requests. Evidence support is not a probability.',
                trace=trace, steps=[dict(action='Computed observed evidence', tool=s['tool'], result=json.dumps(s['result'], ensure_ascii=False)) for s in trace])


def validate_brief(brief, context):
    if not isinstance(brief, dict) or brief.get('incidentId') != context['id']:
        raise ValueError('Invalid investigation identity.')
    if brief.get('candidateId') not in FAULTS or not isinstance(brief.get('summary'), str):
        raise ValueError('Invalid hypothesis or summary.')
    if not isinstance(brief.get('evidenceTags'), list) or any(k not in KEYS for k in brief['evidenceTags']):
        raise ValueError('Invalid evidence signals.')


def model_brief(prompt, context):
    endpoint = os.environ['TRIPLENS_MODEL_ENDPOINT']
    if urlparse(endpoint).scheme not in ('http', 'https') or not os.environ.get('TRIPLENS_MODEL'):
        raise ValueError('Configure an HTTP(S) model endpoint and TRIPLENS_MODEL.')
    evidence = local_brief(prompt, context)
    system = ('Summarize the supplied current investigation and actual Python tool results. Return a JSON object with '
              'incidentId, candidateId, summary, evidenceTags. Preserve the supplied incident identity; candidateId must '
              'be one of the supplied hypotheses. Use only observed evidence, never infer future observations. '
              'Do not claim plant actuation. Scores are rule support, not probabilities.\n' +
              json.dumps(dict(evidence=evidence, hypotheses=FAULTS), ensure_ascii=False))
    payload = dict(model=os.environ['TRIPLENS_MODEL'], messages=[dict(role='system', content=system), dict(role='user', content=prompt)],
                   response_format={'type':'json_object'}, temperature=.2, max_tokens=1600)
    headers = {'Content-Type':'application/json'}
    if token := os.environ.get('TRIPLENS_MODEL_API_KEY'):
        headers['Authorization'] = f'Bearer {token}'
    with urlopen(Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method='POST'), timeout=40) as response:
        reply = json.loads(json.loads(response.read(1_000_000))['choices'][0]['message']['content'])
    validate_brief(reply, context)
    return {**evidence, **reply, 'provider':'model', 'trace':evidence['trace'], 'steps':evidence['steps']}
