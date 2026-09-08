from .models import TaskDefinition, WorkflowPlan
from mediacrawler.workbench.settings.defaults import Defaults
from mediacrawler.workbench.workflows.legacy_models import web_url

DEFINITIONS = [TaskDefinition(id=k, title=t, inputs=i, output=o, fields=f) for k,t,i,o,f in [
    ('session', '准备浏览会话', ['website','session'], 'session', []),
    ('discover', '发现资源', ['session'], 'resources', ['max_items', 'start']),
    ('content', '采集内容', ['session'], 'records', ['max_items', 'start']),
    ('comments', '采集评论', ['session', 'records'], 'records', ['max_items', 'max_comments', 'subcomments']),
    ('media', '下载媒体', ['resources', 'direct'], 'files', ['engine', 'quality', 'audio', 'subdirectory']),
    ('files', '下载文件', ['resources', 'direct', 'direct_file'], 'files', ['engine', 'subdirectory']),
    ('export', '导出数据', ['records', 'files'], 'files', ['output', 'filename', 'subdirectory']),
]]
BY_KIND = {d.id: d for d in DEFINITIONS}


def source_type(plan):
    if plan.source == 'direct':
        from mediacrawler.workbench.browser.capture import classify
        match = classify(plan.target)
        if match and match[0] == 'file': return 'direct_file'
    return {'website': 'website', 'direct': 'direct', 'selection': 'resources', 'history': 'records'}[plan.source]


def supported(definition, platform):
    if definition.id == 'discover': return bool(platform.get('video') and platform.get('collect'))
    if definition.id == 'content': return bool(platform.get('collect'))
    if definition.id == 'comments': return bool(platform.get('comments'))
    return True


def inspect_plan(plan: WorkflowPlan, platform, source_issue=""):
    errors = [source_issue] if source_issue else []
    names = {s.id: s.name or BY_KIND[s.kind].title for s in plan.steps}
    if not platform.get('enabled', True): errors.append('平台已停用')
    if plan.source in ('website', 'direct'):
        if not plan.target.strip(): errors.append('请先设置目标地址或关键词')
        elif plan.mode == 'detail' or plan.source == 'direct':
            try: web_url(plan.target.strip())
            except ValueError as exc: errors.append(str(exc))
        elif plan.mode not in platform.get('inputs', []): errors.append('平台不支持该采集入口')
    if plan.source == 'selection' and (not plan.session_id or not plan.resource_ids): errors.append('请选择浏览器会话中的资源')
    if plan.source == 'history' and not plan.history_id: errors.append('请选择历史运行')
    outputs = {'source': source_type(plan)}
    if plan.source == 'website' and plan.session_id: outputs['source'] = 'session'
    ids = set()
    step_inputs = {}
    for step in plan.steps:
        if step.id in ids: errors.append('卡片编号重复')
        ids.add(step.id)
        definition = BY_KIND[step.kind]
        step_inputs[step.id] = [key for key, kind in outputs.items() if kind in definition.inputs]
        if step.input == step.id: errors.append(f'{definition.title}不能依赖自身')
        unknown = set(step.overrides) - set(definition.fields)
        if unknown: errors.append(f'{definition.title}不支持覆盖：{", ".join(sorted(unknown))}')
        try: Defaults.model_validate(step.overrides)
        except ValueError: errors.append(f'{definition.title}的覆盖设置无效')
        if not step.enabled: continue
        if not supported(definition, platform): errors.append(f'当前平台未接入{definition.title}')
        if outputs.get(step.input) not in definition.inputs: errors.append(f'{step.name or definition.title}依赖的“{names.get(step.input, "方案来源或已移除卡片")}”必须先配置并启用，原方案已保留')
        outputs[step.id] = definition.output
    available, options = [], []
    missing = {
        'session': '需要网站来源，请先配置网站地址',
        'discover': '需要浏览会话，请先添加准备浏览会话',
        'content': '需要浏览会话，请先添加准备浏览会话',
        'comments': '需要浏览会话或内容记录，请先准备会话或采集内容',
        'media': '需要媒体链接或发现的资源，请先配置来源或添加发现资源',
        'files': '需要直接链接或发现的资源，请先配置来源或添加发现资源',
        'export': '需要记录或文件清单，请先添加采集或下载卡片',
    }
    for d in DEFINITIONS:
        inputs = [key for key, kind in outputs.items() if kind in d.inputs]
        reason = ('；'.join(errors) if errors else
                  f'当前平台不支持{d.title}' if not supported(d, platform) else
                  missing[d.id] if not inputs else '')
        entry = {**d.model_dump(), 'sources': inputs}
        options.append({**entry, 'enabled': not reason, 'reason': reason})
        if not reason: available.append(entry)
    return {'valid': not errors, 'errors': errors, 'available': available, 'outputs': outputs,
            'options': options, 'definitions': [d.model_dump() for d in DEFINITIONS], 'step_inputs': step_inputs}


def validate(plan, platform, source_issue=""):
    result = inspect_plan(plan, platform, source_issue)
    if result['errors']: raise ValueError('；'.join(result['errors']))
    return result


def inspect_source(service, plan):
    try:
        if plan.source == 'history' and plan.history_id:
            service.repo.task(plan.history_id)
            data=service.repo.results(plan.history_id)
            if not data['records'] and not data['files']: return '历史运行没有可用数据或文件清单，请选择其他运行'
        if plan.source == 'selection' and plan.session_id and plan.resource_ids:
            service.selected_resources(plan.session_id,plan.resource_ids)
    except (KeyError,ValueError): return '输入来源已失效，请重新选择历史运行或浏览器资源'
    return ''
