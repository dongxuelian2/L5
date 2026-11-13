"""Workspace-scoped resilience endpoints and offline campaign reports."""
from urllib.parse import parse_qs


def route(handler, service, method, workspace_id, parts, body, query):
    if method == 'GET':
        if parts == ['catalog']:
            from .resilience_evaluation import campaign_catalog
            from .resilience_simulation import scenario_catalog
            service.store.workspace(workspace_id)
            return {**scenario_catalog(), **campaign_catalog()}, 200
        if parts == ['scenarios']:
            return {'scenarios': service.scenarios(workspace_id)}, 200
        if parts == ['runs']:
            return {'runs': service.runs(workspace_id)}, 200
        if parts == ['campaigns']:
            return {'campaigns': service.campaigns(workspace_id)}, 200
        if len(parts) == 2 and parts[0] == 'runs':
            return service.run(workspace_id, parts[1]), 200
        if len(parts) >= 2 and parts[0] == 'campaigns':
            if len(parts) == 2:
                return service.campaign(workspace_id, parts[1]), 200
            if len(parts) == 4 and parts[2] == 'cases':
                return service.case(workspace_id, parts[1], parts[3]), 200
            if len(parts) == 3 and parts[2] == 'report.html':
                campaign = service.campaign(workspace_id, parts[1])
                options = parse_qs(query)
                payload = report(campaign, options.get('lang', ['en'])[0]).encode('utf-8')
                handler.send_response(200)
                handler.send_header('Content-Type', 'text/html; charset=utf-8')
                handler.send_header('Content-Length', str(len(payload)))
                handler.send_header('Cache-Control', 'no-store')
                if options.get('download') == ['1']:
                    handler.send_header('Content-Disposition', f'attachment; filename="l5-resilience-{campaign["id"]}.html"')
                handler.end_headers()
                handler.wfile.write(payload)
                return None, None
    elif method == 'POST' and len(parts) == 1:
        operations = {'scenarios': (service.save_scenario, 200 if body.get('id') else 201),
                      'simulate': (service.simulate, 201), 'campaigns': (service.create_campaign, 202),
                      'export': (service.export, 200)}
        if parts[0] in operations:
            operation, status = operations[parts[0]]
            return operation(workspace_id, body), status
        if parts == ['preview']:
            from .resilience_simulation import preview_scenario
            service.store.workspace(workspace_id)
            return preview_scenario(body.get('scenario')), 200
    return None, 404


def report(campaign, locale):
    from .reports import CSS, e, table, technical

    def tr(en, zh):
        return zh if locale == 'zh-CN' else en

    def cell(value):
        if isinstance(value, float):
            value = f'{value:.5g}'
        return e('—' if value is None else value)

    fields = [('eventDetectionRate', tr('Event detection rate', '事件检出率')),
              ('meanDelay', tr('Mean delay (s)', '平均延迟（秒）')),
              ('missedEvents', tr('Missed events', '漏检事件')),
              ('unobservedEvents', tr('Unobserved events', '未观测事件')),
              ('coverage', tr('Coverage', '覆盖率'))]
    rows = []
    for case in campaign['cases']:
        metrics = case['metrics'] or {}
        detector = case['detector']
        rows.append([cell(case['name']), cell(case['phase']), cell(case['family']),
                     cell(f"{detector['algorithm']} ({', '.join(detector.get('signals', []))})"),
                     cell(case['status']), *[cell(metrics.get(field)) for field, _ in fields],
                     cell((metrics.get('normal') or {}).get('alarmFraction')),
                     cell(metrics.get('searchScores', {}).get(case.get('objective'))),
                     cell(case['runtime_ms']), cell(case['error'])])
    title = e(campaign['name'])
    heads = [tr('Case', '案例'), tr('Phase', '阶段'), tr('Family', '情景类别'), tr('Detector', '检测器'), tr('Status', '状态'),
             *[label for _, label in fields], tr('Normal alarm fraction', '正常工况报警比例'),
             tr('Search score', '搜索评分'), tr('Runtime (ms)', '耗时（毫秒）'), tr('Error', '错误')]
    explanation = tr('Alarm episodes are matched one-to-one to active events by alarm onset. A match is temporal evidence. '
                     'Use coverage and the observation and detector traces to interpret misses. Search cases are exploratory.',
                     '每段报警按开始时刻与活动故障事件进行一对一匹配。匹配表示时间上的对应关系。'
                     '请结合覆盖率、观测曲线与检测器输出解释漏检。搜索案例用于探索。')
    return (f'<!doctype html><html lang="{tr("en", "zh-CN")}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · L5</title>'
            f'<style>{CSS}</style></head><body><main><div class="brand">{tr("L5 / RESILIENCE TESTING", "L5 / 韧性测试")}</div>'
            f'<h1>{title}</h1><p>{e(campaign["mode"])} · {e(campaign["status"])} · {campaign["completed"]}/{campaign["total"]}</p>'
            f'<p>{e(explanation)}</p>{table(heads, rows)}<h2>{tr("Saved campaign definition", "已保存的测试计划")}</h2>'
            f'{technical(campaign["definition"])}</main></body></html>')
