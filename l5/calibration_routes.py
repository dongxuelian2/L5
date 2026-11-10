"""Workspace-scoped routes; all numerical jobs retain immutable requests."""


def route(store, method, parts, body):
    service=store.calibration
    workspace_id=parts[2]
    store.workspace(workspace_id)
    if parts[3]=='calibrations':
        if len(parts)==4:
            if method=='GET': return dict(runs=service.list(workspace_id)),200
            if method=='POST': return service.create(workspace_id,body),202
        if len(parts)==5:
            if parts[4]=='catalog' and method=='GET': return service.catalog(),200
            if method=='GET': return service.get(parts[4],workspace_id),200
    if parts[3]=='twins':
        if len(parts)==4:
            if method=='GET': return dict(twins=service.twins(workspace_id)),200
            if method=='POST': return service.save_twin(workspace_id,body),201
        if len(parts)==5 and method=='PATCH': return service.save_twin(workspace_id,body,parts[4]),200
        if len(parts)==6:
            if parts[5]=='revisions' and method=='GET': return dict(revisions=service.revisions(workspace_id,parts[4])),200
            if parts[5]=='scenario' and method=='POST': return service.scenario(workspace_id,parts[4],body),201
    return None,404
