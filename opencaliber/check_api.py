"""Shared authenticated HTTP operations for check development."""
def handle(operation,body,connect):
    from . import custom_checks as checks,check_models as models
    if operation=='checks/save':return checks.save(body,connect)
    if operation=='checks/manage':return checks.manage(body,connect)
    if operation=='checks/preview':
        if set(body)!={'spec'}:raise ValueError('Provide spec')
        return checks.test(body['spec'])
    if operation=='check-model/save':return models.save(body,connect)
    if operation=='check-model/local':return models.local_operation(body,connect)
    if operation=='check-model/generate':return models.generate(body,connect)
    if operation=='check-model/clear-key':
        if body:raise ValueError('No fields needed')
        config,_=models.read(connect);config['enabled']=False
        import json
        with connect() as c:c.execute('UPDATE check_model SET secret=NULL,config=? WHERE id=1',(json.dumps(config),))
        return {'cleared':True}
    raise ValueError('Unknown check operation')
