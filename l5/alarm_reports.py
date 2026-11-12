"""Self-contained alarm reports with the saved grouping and operator history."""
from datetime import datetime, timedelta, timezone

from .reports import CSS, e, n, table


REASONS = {
    'shared-signal': ('同一来源信号', 'Shared source signal'),
    'explicit-relationship': ('显式信号关系', 'Explicit signal relationship'),
    'shared-equipment': ('同一设备组', 'Shared equipment'),
    'detector-agreement': ('检测器一致', 'Detector agreement'),
    'repeat': ('同一来源重复报警', 'Repeated alarm from the same source'),
}


def relationship_text(relation, chinese):
    left, right = relation['leftId'], relation['rightId']
    temporal = ('时间重叠' if chinese else 'Temporal overlap') if relation['temporal'] == 'overlap' else (
        ('时间间距 ' if chinese else 'Temporal gap ') + n(relation['gapSeconds']) + ' s')
    reasons = ', '.join(REASONS.get(reason, (reason, reason))[0 if chinese else 1] for reason in relation['reasons'])
    def signal(source):
        return f"{source['signal']} [{source['datasetId']}]"

    signals = ', '.join(signal(s) for s in relation['signals'])
    pairs = ', '.join(f"{signal(p['left'])} ↔ {signal(p['right'])}" for p in relation.get('explicitPairs', []))
    return ' · '.join(value for value in (f'{left} ↔ {right}', temporal, reasons, signals, pairs, ', '.join(relation['equipment'])) if value)


def render_alarm_report(view, locale='en'):
    chinese = locale == 'zh-CN'

    def tr(zh, en):
        return zh if chinese else en

    def timestamp(value, axis):
        if axis['origin']:
            try:
                stamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=value)
                return stamp.isoformat(timespec='milliseconds').replace('+00:00', ' UTC')
            except OverflowError:
                return f'{value} s UTC'
        return n(value) + ' s'

    title = tr('报警管理报告', 'Alarm management report')
    axes = {a['id']: a for a in view['axes']}
    events = {v['id']: v for v in view['events']}
    defaults = {('high', 'High'): '高', ('medium', 'Medium'): '中', ('low', 'Low'): '低', ('unclassified', 'Unclassified'): '未分类'}
    priority = {p['id']: defaults.get((p['id'], p['label']), p['label']) if chinese else p['label'] for p in view['policy']['priorities']}
    kinds = {
        'acknowledge': tr('确认', 'Acknowledge'), 'shelve': tr('搁置', 'Shelve'),
        'unshelve': tr('取消搁置', 'Unshelve'), 'note': tr('备注', 'Note'),
        'incident': tr('关联调查', 'Link incident'),
    }
    measured = {'active': tr('活动', 'Active'), 'cleared': tr('已清除', 'Cleared'), 'unknown': tr('未知', 'Unknown')}
    parts = [f'''<!doctype html><html lang="{'zh-CN' if chinese else 'en'}"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · {e(view['name'])}</title>
        <style>{CSS}td {{overflow-wrap:anywhere}} .prose {{white-space:pre-wrap}}</style></head><body><main>
        <div class="brand">L5 / {e(title)}</div><h1>{e(view['name'])}</h1>
        <div class="meta"><span>{e(view['id'])}</span><span>{e(view['asOf'])}</span></div>''',
        '<p class="muted">' + e(tr('报警分组基于时间与配置证据。物理因果关系仍需验证。',
            'Groups reflect timing and configured evidence. Physical causality still requires verification.')) + '</p>',
        f"<h2>{e(tr('报警负荷', 'Alarm workload'))}</h2><p>"
        f"{e(tr('原始报警', 'Raw events'))} {view['eventCount']} · {e(tr('相关组', 'Correlated groups'))} {view['groupCount']}</p>",
        '<p class="muted">' + e(tr(
            '到达量按报警开始时间计数。小时率以固定窗口秒数为分母。确认延迟从会话建立时起算。',
            'Arrivals count event starts. Hourly rates use the full configured window as denominator. Acknowledgement delay starts at session creation.')) + '</p>']
    for metric in view['flood']['axes']:
        axis = axes[metric['axisId']]
        label = tr('UTC 绝对时间', 'UTC absolute time') if axis['origin'] else axis['label']
        parts.append(f"<h3>{e(label)} · {e(n(metric['windowSeconds']))} s</h3>")
        parts.append(table([tr('峰值窗口到达量', 'Peak arrivals per window'), tr('峰值到达量 / 小时', 'Peak arrivals / hour'),
                             tr('峰值并发', 'Peak concurrency'), tr('重复报警', 'Repeated events'),
                             tr('平均持续时间 (s)', 'Mean duration (s)'), tr('平均确认延迟 (s)', 'Mean acknowledgement delay (s)')],
            [[e(n(metric[key])) if metric[key] is not None else '—' for key in ('peakArrivalCount', 'peakArrivalsPerHour',
                'peakConcurrent', 'repeatedEventCount', 'meanDurationSeconds', 'meanAcknowledgementDelaySeconds')]]))
        parts.append(table([tr('窗口开始', 'Window start'), tr('窗口结束', 'Window end'), tr('报警到达量', 'Event arrivals'),
                             tr('分组到达量', 'Group arrivals'), tr('峰值并发', 'Peak concurrency'), tr('窗口数', 'Windows')],
            [[e(timestamp(b['start'], axis)), e(timestamp(b['end'], axis)), str(b['arrivals']), str(b['groupArrivals']),
              str(b['peakConcurrent']), str(b.get('windowCount', 1))] for b in metric['bins']]))
    parts.append(f"<h2>{e(tr('相关组与关联证据', 'Correlated groups and grouping evidence'))}</h2>")
    for group in view['groups']:
        axis = axes[group['axisId']]
        start, end = (timestamp(group[k], axis) for k in ('start', 'end'))
        members = ' '.join(f'<li><a href="#event-{e(key)}">{e(events[key]["analysisName"])} · {e(key)}</a></li>'
                           for key in group['eventIds'])
        relationships = ''.join('<li>' + e(relationship_text(rel, chinese)) + '</li>' for rel in group['relationships'])
        parts.append(f"<details><summary>{e(start)} → {e(end)} · {e(priority[group['priority']])} · {len(group['eventIds'])}"
                     f"</summary><p>{e(group['id'])} · {e(group['axisId'])}</p><ul>{members}</ul><ul>{relationships}</ul></details>")
    parts.append(f"<h2>{e(tr('原始报警', 'Source alarms'))}</h2>")
    parts.append(table([tr('来源 / 分析', 'Dataset / analysis'), tr('实际时间', 'Observation time'), tr('测量状态', 'Measured state'),
                         tr('优先级', 'Priority'), tr('峰值 / 阈值', 'Peak / threshold'), tr('信号', 'Signals'),
                         tr('确认 / 搁置至', 'Acknowledged / shelved until')], [
        [f"<span id=\"event-{e(v['id'])}\">{e(v['datasetName'])} · {e(v['analysisName'])}</span><br>{e(v['id'])}",
         e(timestamp(v['start'], axes[v['axisId']])) + ' → ' + e(timestamp(v['end'], axes[v['axisId']])),
         e(measured[v['measuredState']]), e(priority[v['priority']]), e(n(v['peakScore'])) + ' / ' + e(n(v['threshold'])),
         e(', '.join(v['signals'])), e(v['operator']['acknowledgedAt'] or '—') + ' / ' + e(v['operator']['shelvedUntil'] or '—')]
        for v in view['events']]))
    parts.append(f"<h2>{e(tr('操作记录', 'Operator history'))}</h2>")
    parts.append(table([tr('记录时间 (UTC)', 'Recorded time (UTC)'), tr('操作员', 'Operator'), tr('操作', 'Action'),
                         tr('报警或分组 ID', 'Event or group ID'), tr('详情', 'Details')], [
        [e(a['recordedAt']), e(a['actor']), e(kinds[a['kind']]), e(a.get('eventId') or a.get('groupId')),
         '<span class="prose">' + e('\n'.join(a[k] for k in ('note', 'expiresAt', 'incidentId') if k in a)) + '</span>']
        for a in view['audit']]))
    parts.append('</main></body></html>')
    return ''.join(parts)
