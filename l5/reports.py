"""Standalone localized incident reports. Figures are inline SVG from saved data."""
from __future__ import annotations

from .report_locale import fragment as r, localized_report, text as report_text, local_brief_summary

from datetime import datetime, timezone
from html import escape
import json
import math

import numpy as np

from .incident_timeline import investigation
from .data_quality import segment_ids


STATUS = {'open': '待调查', 'investigating': '调查中', 'resolved': '已形成结论', 'archived': '已归档'}
KINDS = {'alarm': '报警', 'note': '调查笔记', 'evidence': '证据', 'hypothesis': '候选解释', 'experiment': '干预实验',
         'investigation': '工具调查', 'status': '状态变更', 'conclusion': '结论更新', 'incident': '事件范围'}
STANCE = {'support': '支持', 'oppose': '反对', 'neutral': '待判断'}
METRIC = {'absolute-robust-z': '稳健 Z 分数绝对值', 'squared-residual': 'PCA-Q 标准化残差平方',
          'model-leverage': 'PCA-T² 模型空间贡献（描述性排序，不加和为 T²）', 'history-contribution': '历史序列贡献度'}


def e(value):
    return escape(str(value) if value is not None else r('未记录'), quote=True)


def n(value):
    if value is None:
        return r('未检出')
    return f'{value:.6g}' if isinstance(value, (int, float)) else str(value)


def timestamp(value, axis=None):
    if value is None:
        return r('未确定')
    if axis and axis.get('origin'):
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='milliseconds').replace('T', ' ', 1).replace('+00:00', ' UTC')
    return n(value) + ' s'


def recorded_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('T', ' ').replace('+00:00', ' UTC')


def table(heads, rows, css_class=''):
    return '<table' + (f' class="{css_class}"' if css_class else '') + '><thead><tr>' + ''.join(f'<th>{e(h)}</th>' for h in heads) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows) + '</tbody></table>'


def prose(value):
    return '<p class="prose">' + e(value or r('尚未记录。')) + '</p>'


def technical(value):
    return '<pre>' + e(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)) + '</pre>'


def parameters(value):
    labels = {'datasetId': r('数据集 ID'), 'signals': r('分析变量'), 'algorithm': r('检测算法'), 'alpha': r('校准 α'),
              'baselineRange': r('正常基线（s）'), 'analysisRange': r('分析区间（s）'), 'fitFraction': r('拟合比例'),
              'minCoverage': r('最低观测比例'), 'persistence': r('报警确认样本数'), 'requiredSignals': r('必需观测变量'),
              'hypothesis': r('候选解释'), 'asOf': r('观察截止（s）'), 'windowStart': r('观察起点（s）'),
              'mode': r('模型模式'), 'at': r('干预执行（s）'), 'horizon': r('预测终点（s）'), 'actions': r('干预动作'),
              'parameters': r('控制参数'), 'calls': r('调查工具'), 'fittedParameters': r('拟合模型参数'), 'fitError': r('拟合误差'),
              'variance': r('保留方差比例'), 'name': r('分析名称'), 'missingValues': r('缺失值处理'), 'sessionId': r('模拟会话 ID'),
              'fault': r('故障模板'), 'start': r('故障开始（s）'), 'severity': r('故障强度'), 'delay': r('执行延迟（s）'),
              'noise': r('测量噪声倍数'), 'response': r('控制器响应倍数'), 'operating': r('初始温差（°C）'),
              'seed': r('随机种子'), 'duration': r('模拟时长（s）'), 'step': r('积分步长（s）'), 'observedThrough': r('观测截止（s）')}
    return table([r('参数'), r('保存值')], [[e(labels.get(k, k)), e(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else r('未记录') if v is None else v)] for k, v in value.items()], 'parameters')


def chart(title, times, lines, *, axis=None, threshold=None, intervals=(), unit=None, domain=None, markers=()):
    unit = unit if unit is not None else r('原始值（源数据未提供单位）')
    valid = [v for line in lines for v in line['values'] if v is not None and math.isfinite(v)]
    if not times or not valid:
        return f"<p>{e(title)}{r('：此窗口没有可显示的观测值。</p>')}"
    width, height, left, right, top, bottom = 760, 220, 70, 18, 24, 44
    low, high = domain or (min(valid), max(valid))
    if threshold is not None:
        low, high = min(low, threshold), max(high, threshold)
    pad = max((high-low) * .08, abs(high) * .002, .001)
    low, high = low-pad, high+pad
    first, last = times[0], times[-1]
    def x(t): return left + (t-first) / (last-first or 1) * (width-left-right)
    def y(v): return top + (high-v) / (high-low) * (height-top-bottom)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{e(title)}"><title>{e(title)}</title>',
           f'<text x="{left}" y="13">{e(unit)}</text>']
    for f in (0, .5, 1):
        yy = top + f * (height-top-bottom)
        svg.append(f'<line x1="{left}" x2="{width - right}" y1="{yy}" y2="{yy}" stroke="#dce3e6"/><text x="{left - 8}" y="{yy + 4}" text-anchor="end">{n(high - f * (high - low))}</text>')
    for interval in intervals:
        a, b = max(first, interval['start']), min(last, interval['end'])
        if a <= b:
            svg.append(f'<rect x="{x(a):.2f}" y="{top}" width="{max(2, x(b) - x(a)):.2f}" height="{height - top - bottom}" fill="#c8563c" opacity=".13"/>')
    if threshold is not None:
        svg.append(f'''<line x1="{left}" x2="{width - right}" y1="{y(threshold):.2f}" y2="{y(threshold):.2f}" stroke="#ac6b11" stroke-dasharray="6 4"/><text x="{width - right}" y="{y(threshold) - 5:.2f}{r('" text-anchor="end">阈值 ')}{n(threshold)}</text>''')
    for marker in markers:
        if first <= marker['time'] <= last:
            svg.append(f'''<line x1="{x(marker['time']):.2f}" x2="{x(marker['time']):.2f}" y1="{top}" y2="{height - bottom}" stroke="#3b78a1" stroke-dasharray="3 3"/><text x="{x(marker['time']) + 4:.2f}" y="{top + 12}" fill="#3b78a1">{e(marker['label'])}</text>''')
    for line in lines:
        values = line['values']
        # Preserve extrema and explicit missing samples when reducing score paths.
        indices = {0, len(values)-1}
        step = max(1, math.ceil(len(values)/400))
        for start in range(0, len(values), step):
            chunk = range(start, min(start+step, len(values)))
            finite = [i for i in chunk if values[i] is not None]
            missing = [i for i in chunk if values[i] is None]
            if finite:
                indices.update((min(finite, key=lambda i: values[i]), max(finite, key=lambda i: values[i])))
            if missing:
                indices.update((missing[0], missing[-1]))
        points, connected, previous_segment = [], False, None
        segments = line.get('segmentIds')
        for i in sorted(indices):
            if values[i] is None:
                connected = False
                continue
            points.append(f"{('L' if connected and (segments is None or previous_segment == segments[i]) else 'M')}{x(times[i]):.2f},{y(values[i]):.2f}")
            connected = True
            previous_segment = segments[i] if segments is not None else None
        svg.append(f'''<path d="{' '.join(points)}" fill="none" stroke="{line.get('color', '#246b63')}" stroke-width="1.4"/>''')
    # Elapsed seconds keep long UTC labels out of the plot. Caption gives UTC origin.
    for fraction in (0, .25, .5, .75, 1):
        value = first + fraction * (last-first)
        svg.append(f'''<text x="{x(value):.2f}" y="{height - 23}" text-anchor="{('start' if fraction == 0 else 'end' if fraction == 1 else 'middle')}">{n(value - first)}</text>''')
    svg.append(f'''<text x="{(width + left - right) / 2}" y="{height - 5}{r('" text-anchor="middle">相对本图起点的时间（s）</text></svg>')}''')
    legend = ' · '.join(f"""<span style="color:{line.get('color', '#246b63')}">━ {e(line['label'])}</span>""" for line in lines)
    shading = r('阴影为关联报警；') if intervals else ''
    return f"""<figure><figcaption>{e(title)}</figcaption>{''.join(svg)}<p class="caption">{legend}{r('<br>起点：')}{e(timestamp(first, axis))}{r('；终点：')}{e(timestamp(last, axis))}。{shading}{r('缺测／abstain 保留断点。</p></figure>')}"""


def lanes(analyses, axis):
    intervals = [i for a in analyses for i in a['intervals']]
    if not intervals:
        return r('<p>所选来源没有关联报警区间。</p>')
    first, last = min(i['start'] for i in intervals), max(i['end'] for i in intervals)
    x = lambda t: 180 + (t-first)/(last-first or 1)*550
    height = 40 + 36*len(analyses)
    svg = [f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 {height}{r('" role="img" aria-label="检测区间对比"><title>各关联分析的异常区间</title>')}"""]
    for index, a in enumerate(analyses):
        yy = 10 + index*36
        label = report_text(a['result']['algorithmLabel'])
        svg.append(f'<text x="0" y="{yy + 14}">{e(label[:22])} [{index + 1}]</text><line x1="180" x2="730" y1="{yy + 10}" y2="{yy + 10}" stroke="#dce3e6"/>')
        for i in a['intervals']:
            svg.append(f'''<rect x="{x(i['start']):.2f}" y="{yy}" width="{max(3, x(i['end']) - x(i['start'])):.2f}" height="20" rx="2" fill="#327e74"/><circle cx="{x(i['peakTime']):.2f}" cy="{yy + 10}" r="3" fill="#e3ad46"/>''')
    svg.append(f'<text x="180" y="{height - 5}">0 s</text><text x="730" y="{height - 5}" text-anchor="end">{n(last - first)} s</text></svg>')
    return r('<figure><figcaption>关联分析的报警区间与峰值</figcaption>') + ''.join(svg) + f"""<p class="caption">{e(axis['label'])}{r('；起点 ')}{e(timestamp(first, axis))}{r('；金色点为原始分数峰值。仅比较时间和报警状态。</p></figure>')}"""


CSS = '''
@page { size:A4; margin:16mm 15mm 18mm; @bottom-right { content:counter(page); font-size:9pt; color:#667; } }
* { box-sizing:border-box; } body { margin:0; color:#203239; background:#e9eef0; font:14px/1.65 "Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif; }
main { max-width:960px; margin:24px auto; padding:42px 50px; background:white; }
.toolbar { max-width:960px; margin:20px auto; display:flex; gap:18px; align-items:center; }
button { cursor:pointer; border:0; border-radius:4px; background:#246b63; color:white; padding:12px 22px; font:inherit; }
.brand { color:#246b63; font-weight:bold; letter-spacing:2px; border-bottom:3px solid #246b63; padding-bottom:14px; }
h1 { font-size:30px; line-height:1.35; margin:26px 0 16px; } h2 { font-size:21px; border-bottom:1px solid #c7d5d7; padding:18px 0 8px; margin:22px 0 15px; }
h3 { font-size:16px; margin:22px 0 8px; } h4 { margin:18px 0 6px; } h1,h2,h3,h4,figcaption { break-after:avoid; }
p { margin:8px 0 14px; } .prose { white-space:pre-wrap; overflow-wrap:anywhere; orphans:3; widows:3; }
.meta { display:grid; grid-template-columns:1fr 1fr; gap:8px 22px; color:#506169; font-size:12px; } .meta span { overflow-wrap:anywhere; }
.summary { background:#eef5f3; border-left:4px solid #327e74; padding:14px 18px; margin-top:22px; }
table { width:100%; border-collapse:collapse; margin:12px 0 20px; font-size:11px; table-layout:fixed; } th,td { padding:8px 6px; border-bottom:1px solid #dce3e6; text-align:left; vertical-align:top; overflow-wrap:anywhere; }
th { background:#edf2f3; font-weight:600; } thead { display:table-header-group; } tr { break-inside:avoid; }
.parameters td,.parameters th { padding:5px 6px; font-size:10px; line-height:1.5; }
figure { margin:18px 0 22px; border:1px solid #d5dfe1; padding:10px; break-inside:avoid; } figcaption { font-size:13px; font-weight:bold; overflow-wrap:anywhere; margin-bottom:8px; }
svg { width:100%; height:auto; display:block; } svg text { font:10px "Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif; fill:#506169; }
.caption,.muted { color:#62757e; font-size:11px; } .caption { line-height:1.5; margin:6px 0 0; } a { color:#246b63; text-decoration:none; }
pre { font:10px/1.5 Consolas,"Microsoft YaHei",monospace; white-space:pre-wrap; overflow-wrap:anywhere; background:#f4f6f7; padding:12px; }
.evidence { border-left:3px solid #b0c8c2; padding-left:14px; } .opposed { border-color:#b97161; }
.timeline td:first-child { width:24%; } footer { border-top:1px solid #c7d5d7; margin-top:30px; padding-top:12px; color:#62757e; font-size:10px; }
@media print { body { background:white; font-size:10pt; } main { width:auto; max-width:none; margin:0; padding:0; } .toolbar { display:none; } h1 { font-size:24pt; } h2 { font-size:15pt; } h3 { font-size:12pt; } figure { max-width:100%; } pre { background:none; } * { print-color-adjust:exact; -webkit-print-color-adjust:exact; } }
'''


@localized_report
def render_report(store, identity):
    view = investigation(store, identity)
    incident, workspace = view['incident'], view['workspace']
    axes = {a['id']: {**a, 'label': r('UTC absolute time') if a['origin'] else
                     r('事件独立时间轴') if a['id'].startswith('incident:') else a['label']}
            for a in view['axes']}
    datasets = {d['id']: d for d in view['datasets']}
    analysis_datasets = {a['id']: a['datasetId'] for a in view['analyses']}
    def event_title(item):
        if item['kind'] == 'alarm':
            analysis = next(a for a in view['analyses'] if a['id'] == item['analysisId'])
            return report_text(analysis['result']['algorithmLabel']) + r(' · Anomaly interval')
        if item['id'].startswith('truth:'):
            external = datasets[item['id'][6:]]['metadata']['external']
            return r('Published dataset fault ') + str(external['faultNumber']) + r(' · sample ') + str(external['faultOnsetSample'])
        return report_text(item['title']) if item['kind'] in ('status', 'conclusion', 'experiment', 'investigation') else item['title']
    def signal_label(dataset_id, name):
        column = next((c for c in datasets[dataset_id]['metadata']['columns'] if c['name'] == name), {})
        return (column.get('displayName') or name) + (f" ({column['unit']})" if column.get('unit') else '')
    primary = axes[view['primaryAxisId']]
    from .incident_timeline import incident_clock
    offset = incident_clock(store, incident)['offset']
    start, end = (incident[k] + offset if incident[k] is not None else None for k in ('start_time', 'end_time'))
    parts = [f"""{r('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>')}{e(incident['title'])}{r(' · L5 调查报告</title><style>')}{CSS}</style></head><body>""",
        r('<div class="toolbar"><button onclick="window.print()">打印 / 保存为 PDF</button><span>建议 A4，使用默认页边距；全部图表已嵌入，可离线阅读。</span></div><main>'),
        f"""{r('<div class="brand">L5 / 工业运行分析与故障调查</div><h1>事件调查报告<br>')}{e(incident['title'])}</h1>""",
        f"""{r('<div class="meta"><span>事件编号：')}{e(identity)}{r('</span><span>调查状态：')}{e(report_text(STATUS[incident['status']]))}{r('</span><span>Workspace：')}{e(workspace['name'])}{r('</span><span>生成时间：')}{e(recorded_time(view['generatedAt']))}{r('</span><span>事件开始：')}{e(timestamp(start, primary))}{r('</span><span>事件结束：')}{e(timestamp(end, primary))}{r('</span><span>时间轴：')}{e(primary['label'])}{r('</span><span>内容更新：')}{e(recorded_time(incident['updated_at']))}</span></div>""",
        r('<div class="summary"><h3>事件概述</h3>') + prose(incident['description']) + r('<h3>已记录结论</h3>') + prose(incident['conclusion']) + '</div>',
        r('<p class="muted">本报告读取已持久化的事件、分析结果、原始测量和调查记录。未填写的判断保持未记录。不同算法分数使用各自原始尺度；贡献度表示统计关联。带时区的数据按 UTC 对齐；相对时间源使用已保存的显式参考与偏移，否则保留独立时钟。</p>'),
        r('<h2>1. 事件时间线</h2>')]
    for axis in axes.values():
        events = [v for v in view['events'] if v['axisId'] == axis['id'] and v['start'] is not None]
        if not events:
            continue
        parts.append('<h3>' + e(axis['label']) + '</h3>')
        rows = []
        for item in events:
            detail = report_text(item.get('content', '')) if item['kind'] == 'truth' else item.get('content', '')
            if item['kind'] == 'alarm':
                detail = f"{r('峰值 ')}{timestamp(item['peakTime'], axis)}{r('；原始分数 ')}{n(item['peakScore'])}{r('；变量：')}" + ', '.join(signal_label(analysis_datasets[item['analysisId']], s) for s in item['signals'])
            if item.get('observationWindow'):
                detail = r('观察窗口 ') + ' - '.join(n(v) for v in item['observationWindow']) + ' s；' + report_text(item.get('hypothesis') or '')
                if item.get('actionAt') is not None:
                    detail += r('；干预执行 ') + n(item['actionAt']) + ' s'
            target = 'entry-' + item['entryId'] if item.get('entryId') else 'analysis-' + item['analysisId'] if item.get('analysisId') else 'source-' + item.get('linkId', '')
            time = timestamp(item['start'], axis) + (' → ' + timestamp(item['end'], axis) if item['end'] != item['start'] else '')
            rows.append([e(time), f"""<a href="#{e(target)}">{e(report_text(KINDS.get(item['kind'], item['kind'])))} · {e(event_title(item))}</a>""", e(detail), e(recorded_time(item['recordedAt']) if item.get('recordedAt') else r('事件范围'))])
        parts.append('<div class="timeline">' + table([r('实际观察时间 / 区间'), r('记录'), r('内容'), r('记录创建时间')], rows) + '</div>')
    parts.append(r('<h3>调查操作与未标注观察时间的记录</h3>'))
    recorded = sorted([v for v in view['events'] if v['start'] is None], key=lambda v: v.get('recordedAt', ''))
    rows = []
    labels = {'status': r('状态'), 'conclusion': r('结论'), 'title': r('标题'), 'description': r('概述'), 'start_time': r('开始时间'), 'end_time': r('结束时间'), 'time_origin': r('时间原点'), 'time_axis_key': r('时间来源')}
    for item in recorded:
        detail = report_text(item.get('content', '')) if item['kind'] == 'truth' else item.get('content', '')
        if item.get('changes'):
            detail = '\n'.join(labels.get(k, k) + '：' + str(report_text(STATUS.get(v['before'], v['before'])) if k == 'status' and v['before'] is not None else v['before'] if v['before'] is not None else r('未设置')) + ' → ' + str(report_text(STATUS.get(v['after'], v['after'])) if k == 'status' else v['after']) for k, v in item['changes'].items())
        rows.append([e(recorded_time(item['recordedAt'])), e(event_title(item)), '<span class="prose">' + e(detail) + '</span>'])
    parts.append(table([r('记录时间（与设备观察时间分开）'), r('调查操作'), r('保存内容 / 变更')], rows) if rows else r('<p>没有此类记录。</p>'))
    parts.append(r('<h2>2. 监测与分析比较</h2><p class="muted">统计只计算本事件关联的区间；关联完整分析时纳入其全部区间。持续时间为首末样本时间差，单点报警为 0 s。共同／独有区间仅在各分析共同有有效观测的时间内判断，abstain 或窗口外不作为未报警。</p>'))
    for group in view['comparisons']:
        axis = axes[group['axisId']]
        members = [a for a in view['analyses'] if a['id'] in group['analysisIds']]
        parts.append('<h3>' + e(axis['label']) + '</h3>')
        parts.append(lanes(members, axis))
        parts.append(table([r('分析 / 数据集'), r('范围'), r('首次报警 / 峰值时间'), r('区间数 / 持续时间'), r('原始峰值 / 阈值'), r('主要变量')], [
            [f"""<a href="#analysis-{a['id']}">{e(a['result']['name'])}</a><br>{e(a['datasetName'])}<br>{e(report_text(a['result']['algorithmLabel']))}""", e(report_text(a['scope'])),
             e(timestamp(min((i['start'] for i in a['intervals']), default=None), axis)) + '<br>' + e(timestamp(max(a['intervals'], key=lambda i: i['peakScore'])['peakTime'], axis) if a['intervals'] else r('未检出')),
             str(len(a['intervals'])) + ' / ' + n(sum(i['end']-i['start'] for i in a['intervals'])) + ' s',
             n(max((i['peakScore'] for i in a['intervals']), default=None)) + ' / ' + n(a['result']['threshold']),
             e(', '.join(signal_label(a['datasetId'], s) for s in a['result']['relatedSignals'][:5]))] for a in members]))
        spread = n(group['firstAlarmSpread']) + ' s' if group['firstAlarmSpread'] is not None else r('不适用（需要两个有报警的分析）')
        parts.append(f"{r('<p>首次报警：')}{e(timestamp(group['firstDetection'], axis))}{r('；有报警的分析间首次报警时间差：')}{e(spread)}。</p>")
        if len(members) > 1:
            names = {a['id']: a['result']['name'] for a in members}
            parts.append(table([r('比较类别'), r('开始'), r('结束'), r('持续时间'), r('检出分析')], [
                [e({'common': r('全部共同检出'), 'unique': r('独有检出'), 'partial': r('部分共同检出'), 'uncompared': r('缺少共同观测，未比较')}[s['kind']]),
                 e(timestamp(s['start'], axis)), e(timestamp(s['end'], axis)), n(s['end']-s['start']) + ' s', e('、'.join(names[i] for i in s['analysisIds']))] for s in group['segments']]))
    if not view['analyses']:
        parts.append(r('<p>此事件尚未关联异常检测分析。</p>'))
    parts.append(r('<h2>3. 关键曲线、检测指标与变量贡献</h2>'))
    for a in view['analyses']:
        result, axis = a['result'], axes[a['axisId']]
        parts.append(f"""<h3 id="analysis-{a['id']}">{e(result['name'])} · {e(report_text(result['algorithmLabel']))}</h3>""")
        external = result.get('external') or datasets[a['datasetId']]['metadata'].get('external')
        onset = external.get('faultOnsetSeconds') if external else None
        markers = [dict(time=onset+a['offset'], label=r('数据集已知故障注入'))] if onset is not None else []
        if external:
            parts.append(r('<h4>外部原始来源与已知故障标签</h4>')+technical(external))
        if result.get('training'):
            parts.append(r('<h4>正常拟合、校准与独立测试来源</h4>')+technical(result['training']))
            if result.get('experiment'):
                run = store.experiments.run(result['experiment']['runId'])
                task = next((t for t in run['tasks'] if t['id'] == result['experiment']['taskId']), None)
                if task:
                    parts.append(r('<h4>保存的实验评价（标签与候选解释分离）</h4>')+technical(task['metrics']))
        times = [t + a['offset'] for t in result['times']]
        scores = [None if result.get('states', [])[i:i+1] == ['abstain'] else v for i, v in enumerate(result['scores'])]
        segments = segment_ids(np.asarray(times), np.asarray([np.nan if v is None else v for v in scores]), datasets[a['datasetId']]['metadata']['quality']['gapThreshold']).tolist()
        parts.append(chart(r('异常分数与固定阈值 · ') + a['datasetName'], times, [dict(label=report_text(result['algorithmLabel']), values=scores, segmentIds=segments, color='#b45742')],
                           axis=axis, threshold=result['threshold'], intervals=a['intervals'], markers=markers, unit=r('算法原始分数（各方法尺度独立）')))
        summary = result['summary']
        parts.append(f"""{r('<p class="muted">拟合 ')}{summary['fitSamples']}{r(' 样本；校准 ')}{summary['calibrationSamples']}{r(' 样本；分析 ')}{summary['analysisSamples']}{r(' 样本；报警 ')}{summary['flaggedSamples']}{r(' 样本；abstain ')}{summary.get('abstainedSamples', 0)}{r(' 样本。以上为完整分析指标。</p>')}""")
        parts.append(table([r('关联区间开始'), r('结束'), r('峰值时间'), r('峰值分数 / 样本数')], [
            [e(timestamp(i['start'], axis)), e(timestamp(i['end'], axis)), e(timestamp(i['peakTime'], axis)), n(i['peakScore']) + ' / ' + str(i['samples'])] for i in a['intervals']]))
        peak = max(a['intervals'], key=lambda i: i['peakScore']) if a['intervals'] else None
        contributions = (peak or {}).get('contributions') or result.get('signalContributions', [])
        parts.append(r('<h4>关键变量 · ') + e(report_text(METRIC.get(result.get('contributionMetric'), r('已保存变量排序')))) + '</h4>')
        parts.append(table([r('变量'), r('贡献（保留本算法含义）')], [[e(signal_label(a['datasetId'], c['signal'])), n(c['value'])] for c in contributions[:10]]))
        parts.append(r('<p class="muted">贡献值来自最高原始分数的关联峰值；没有关联报警时使用完整分析峰值。不同方法的贡献值不直接相加或排序比较。</p>'))
        native_range = result['config']['analysisRange']
        if a['intervals'] and a['scope'] != '完整分析':
            lo, hi = min(i['start'] for i in a['intervals'])-a['offset'], max(i['end'] for i in a['intervals'])-a['offset']
            padding = max((hi-lo)*.15, (native_range[1]-native_range[0])*.02)
            native_range = [max(native_range[0], lo-padding), min(native_range[1], hi+padding)]
        signals = list(dict.fromkeys([c['signal'] for c in contributions[:3]] or result['relatedSignals'][:3]))
        if signals:
            series = store.series(a['datasetId'], signals, *native_range)
            for signal in signals:
                unit = next((c.get('unit') for c in datasets[a['datasetId']]['metadata']['columns'] if c['name'] == signal), None)
                label = signal_label(a['datasetId'], signal)
                parts.append(chart(r('原始变量趋势 · ') + label, [t+a['offset'] for t in series['times']],
                    [dict(label=label, values=series['values'][signal], segmentIds=series['segmentIds'][signal])], axis=axis, intervals=a['intervals'], markers=markers, unit=unit or r('原始值（源数据未提供单位）')))
            parts.append(f"""<p class="muted">{e(a['datasetName'])}{r('；显示 ')}{series['displayRows']} / {series['sourceRows']}{r(' 个样本，长序列使用保留极值的显示采样；检测结果使用完整数据。</p>')}""")
    # Standalone dataset links still contribute genuine observed charts to a report without analyses.
    analyzed = {a['datasetId'] for a in view['analyses']}
    for dataset in view['datasets']:
        if dataset['id'] in analyzed:
            continue
        from .incident_timeline import clock_for_key
        clock = clock_for_key(store, 'dataset:' + dataset['id'])
        series = store.series(dataset['id'])
        for signal, values in series['values'].items():
            label = signal_label(dataset['id'], signal)
            unit = next((c.get('unit') for c in dataset['metadata']['columns'] if c['name'] == signal), '')
            parts.append(chart(dataset['name'] + ' · ' + label, [t+clock['offset'] for t in series['times']], [dict(label=label, values=values, segmentIds=series['segmentIds'][signal])], axis=axes.get(clock['axisId']), unit=unit or r('原始值（源数据未提供单位）')))
    parts.append(r('<h2>4. 调查证据与候选解释</h2>'))
    entries = incident['entries']
    for entry in sorted(entries, key=lambda v: (v['kind'] != 'hypothesis', v['created_at'])):
        parts.append(f"""<h3 id="entry-{entry['id']}">{e(report_text(KINDS[entry['kind']]))} · {e(entry['title'])}</h3>""")
        if entry['kind'] == 'evidence':
            hypothesis = next((v['title'] for v in entries if v['id'] == entry['hypothesis_id']), None)
            parts.append(f"<p>{e(report_text(STANCE[entry['stance']]))}：{e(hypothesis or r('尚未关联候选解释'))}</p>")
        parts.append('<div class="evidence' + (' opposed' if entry['stance'] == 'oppose' else '') + '">' + prose(entry['content']) + '</div>')
        source = next((l for l in incident['links'] if l['id'] == entry['source_link_id']), None)
        observation = next(v for v in view['events'] if v.get('entryId') == entry['id'])
        parts.append(f"""{r('<p class="muted">实际观察：')}{e(timestamp(observation['start'], axes.get(observation['axisId'])))}{r('；创建：')}{e(recorded_time(entry['created_at']))}{r('；修改：')}{e(recorded_time(entry['updated_at']))}{r('；来源：')}{e(source['details']['title'] if source else r('人工记录 / 来源已解除'))}{r('；记录 ID：')}{e(entry['id'])}</p>""")
        if entry['kind'] == 'hypothesis':
            for stance in STANCE:
                related = [v for v in entries if v['hypothesis_id'] == entry['id'] and v['stance'] == stance]
                parts.append('<p>' + e(report_text(STANCE[stance])) + r('证据：') + ('、'.join(f"""<a href="#entry-{v['id']}">{e(v['title'])}</a>""" for v in related) or r('尚未记录')) + '</p>')
    if not entries:
        parts.append(r('<p>尚未保存调查证据或候选解释。</p>'))
    simulation_links = [l for l in incident['links'] if l['kind'] in ('simulation', 'run')]
    if simulation_links:
        parts.append(r('<h2>5. 模拟调查与干预方案比较</h2>'))
        for link in simulation_links:
            detail = link['details']
            parts.append(f"""<h3 id="source-{link['id']}">{e(detail['title'])}</h3>""")
            session = store.runtime.get(detail['simulationId'])
            parts.append(r('<h4>模型与场景来源</h4>') + parameters(dict(modelId=session['modelId'], modelVersion=session['modelVersion'],
                modelName=session['modelDescriptor']['name'], scenarioId=session['scenarioId'], scenarioVersion=session['scenarioVersion'])))
            parts.append(r('<h4>过程模型配置</h4>') + parameters(session['config']))
            parts.append(table([r('信号'),r('单位')], [[e(report_text(s.get('label', s.get('tag', s['key'])))), e(report_text(s.get('unit',r('未知'))))] for s in session['modelDescriptor']['signals']]))
            run = detail.get('run')
            if not run:
                parts.append(r('<p>已保存观察上下文：</p>') + parameters(detail.get('observationWindow', {})))
                continue
            parts.append(f"{r('<p>实验 ID：')}{e(run['id'])}{r('；类型：')}{e(report_text(run['kind']))}{r('；记录时间：')}{e(recorded_time(run['createdAt']))}{r('</p><h4>实验参数与观察窗口</h4>')}" + parameters(run['request']))
            result = run['result']
            if run['kind'] == 'intervention' and result.get('format') == 'model-forecast-v1':
                paths = [result['baseline'], *result['branches']]
                definitions = result['metricDefinitions']
                parts.append(table([r('方案'), *[e(report_text(m['label'])+' ('+report_text(m['unit'])+')') for m in definitions]],
                    [[e(report_text(p.get('action')) or r('不干预基线')), *[n(p['metrics'][m['key']]) for m in definitions]] for p in paths]))
                for signal in result['signalDefinitions']:
                    parts.append(chart(report_text(signal.get('label', signal['key'])), paths[0]['times'],
                        [dict(label=report_text(p.get('action')) or r('不干预基线'), values=p['values'][signal['key']], color=['#a34e3b','#246b63','#536daf','#9565a6','#957123'][i % 5]) for i,p in enumerate(paths)], unit=report_text(signal['unit'])))
                parts.append(prose(report_text(result['uncertainty'])))
            elif run['kind'] == 'intervention':
                paths = [result['baseline'], *result['branches']]
                parts.append(table([r('方案'), r('物理峰值压力 kPa'), r('预测越限时间 s'), r('产量损失 %'), r('质量损失 pp'), r('能耗 %·s')], [
                    [e(report_text(p.get('action', r('不干预基线')))), n(p['physicalPeak']), n(p['trip']), n(p['productionLoss']), n(p['qualityLoss']), n(p['utilityCost'])] for p in paths]))
                colors = ['#a34e3b', '#246b63', '#536daf', '#9565a6', '#957123']
                # Runtime branches use the same simulation cadence. Retain each grid if a historical result differs.
                same_grid = all(p['times'] == paths[0]['times'] for p in paths)
                domain = [min(v for p in paths for v in p['pressure']), max(v for p in paths for v in p['pressure'])]
                for group in [paths] if same_grid else [[p] for p in paths]:
                    parts.append(chart(r('干预方案对比 · 物理压力'), group[0]['times'], [dict(label=report_text(p.get('action', r('不干预基线'))), values=p['pressure'], color=colors[i % len(colors)]) for i, p in enumerate(group)], threshold=result['threshold'], unit=r('物理压力（kPa）'), domain=domain))
                parts.append(r('<p class="muted">曲线颜色依次对应：') + e(' · '.join(report_text(p.get('action', r('不干预基线'))) for p in paths)) + r('。预测以保存的模型模式、候选解释和观察截止为条件。</p>'))
                parts.append(r('<h4>拟合参数与恢复窗口</h4>') + parameters({k: result[k] for k in ('mode', 'hypothesis', 'observedThrough', 'at', 'horizon', 'fitError', 'fittedParameters') if k in result}))
                if result.get('search'):
                    search = result['search']
                    parts.append(f"{r('<p>恢复窗口搜索分辨率：')}{e(n(search['resolution']))}{r(' s；计算 ')}{e(search['evaluated'])}{r(' 次模拟。下列边界仅对应实际搜索网格。</p>')}")
                    parts.append(table([r('方案'), r('最晚可恢复起点（s）'), r('可恢复区间（s）')], [[e(report_text(action.get('name', action['id']))), n(action['latest']), e('；'.join(' - '.join(n(t) for t in span) for span in action['intervals']) or r('未检出'))] for action in search['actions']]))
            else:
                if result.get('summary'):
                    parts.append(prose(local_brief_summary(result['summary']) if result.get('provider') == 'local' else result['summary']))
                for trace in result.get('trace', []):
                    parts.append('<h4>' + e(report_text(trace['tool'])) + '</h4>' + technical(trace))
                if result.get('limitation'):
                    parts.append(prose(report_text(result['limitation']) if result.get('provider') == 'local' else result['limitation']))
    parts.append(f"<h2>{(6 if simulation_links else 5)}{r('. 调查结论与主要依据</h2><p>当前状态：')}" + e(report_text(STATUS[incident['status']])) + '</p>' + prose(incident['conclusion']))
    evidence = [v for v in entries if v['kind'] == 'evidence']
    parts.append(r('<p>已保存证据：') + ('、'.join(f"""<a href="#entry-{v['id']}">{e(v['title'])}</a>（{e(report_text(STANCE[v['stance']]))}）""" for v in evidence) or r('尚未记录')) + '</p>')
    parts.append(r('<h2>附录. 数据、参数与关联记录</h2>'))
    for dataset in view['datasets']:
        lineage = dataset['metadata'].get('transformation')
        if lineage:
            parts.append(r('<h3>派生数据来源与处理步骤：') + e(dataset['name']) + '</h3>')
            parts.append(prose(f"{r('变换：')}{lineage['definitionName']}{r('；版本：')}{lineage['revision']}{r('；执行：')}{lineage['executionId']}{r('；创建时间：')}{lineage['createdAt']}。"))
            parts.append(table([r('来源数据集'), r('标识'), r('原始数值文件 SHA-256')], [[e(s['datasetName']), e(s['datasetId']), e(s['sha256'])] for s in lineage['sources']]))
            parts.append(table([r('输出变量'), r('原信号 ID'), r('单位转换'), r('重采样 / 最大间隔'), r('缺失 / 重复时间')], [
                [e(s['displayName']) + ' / ' + e(s['key']), e(s['signalId']), e(s['sourceUnit'] or r('未指定')) + ' → ' + e(s['unit'] or r('未指定')),
                 e(s['resampling']) + ' / ' + e(n(s['maxGapSeconds'])) + ' s', e(json.dumps(s['missing'], ensure_ascii=False)) + ' / ' + e(s['duplicatePolicy'])]
                for s in lineage['config']['sources']]))
            for output in lineage['config']['derived']:
                parts.append(prose(output['displayName'] + '：' + output['key'] + ' = ' + output['expression']))
            parts.append(prose(r('插值、保持及填充值保留样本来源标记。分析参数中的 observationPolicy 说明是否将处理值计入覆盖率。统计填充值取自输出窗口内原始有效观测，不作为健康基线保证。')))
            parts.append(technical(dict(grid=lineage['grid'], quality=lineage['quality'], sourceSimulations=lineage['sourceSimulations'], definition=lineage['config'])))
    parts.append(table([r('数据集 / 标识'), r('采样与时间元数据'), r('变量 / 原始列名')], [[e(d['name']) + '<br>' + e(d['id']), e(json.dumps(dict(source=d['metadata']['time'], browsingClock=d['metadata']['clock']), ensure_ascii=False)) + '<br>' + str(d['metadata']['rowCount']) + r(' 行'), e('、'.join(signal_label(d['id'], c['name']) + ' / ' + c['name'] for c in d['metadata']['columns']))] for d in view['datasets']]))
    for a in view['analyses']:
        parts.append('<h3>' + e(a['result']['name']) + r('</h3><p>分析 ID：') + e(a['id']) + r('；贡献度语义：') + e(report_text(METRIC.get(a['result'].get('contributionMetric'), r('历史排序')))) + '</p>' + parameters(a['result']['config']))
        if a['result'].get('experiment'):
            parts.append(r('<h4>来源分析实验 / 执行 / 任务</h4>') + technical(a['result']['experiment']))
    parts.append(table([r('关联记录 ID'), r('类型'), r('原始记录 ID / 区间序号'), r('创建时间')], [[e(l['id']), e(l['kind']), e(l['reference_id']) + '<br>' + e(l['selector']), e(recorded_time(l['created_at']))] for l in incident['links']]))
    parts.append(f"{r('<footer>L5 工业事件调查 · ')}{e(identity)}{r(' · 生成于 ')}{e(recorded_time(view['generatedAt']))}{r('<br>离线独立报告；重新生成将读取最新保存内容。调查结论保留用户原文。</footer></main></body></html>')}")
    return ''.join(parts)
