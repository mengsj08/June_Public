"""skill-state/v1 invocation transport and decision lifecycle rules."""
from __future__ import annotations
import json
from urllib import error, parse, request

class InvocationError(ValueError): pass

def _target_parts(target):
    value = str(target or '').strip().strip('/')
    if '/' not in value: raise InvocationError('skill target 必须为 <adapter>/<action>')
    adapter, action = value.split('/', 1)
    if not adapter or not action or any(x in {'.', '..'} for x in action.split('/')):
        raise InvocationError('skill target 非法')
    return adapter, action

def resolve_target(target, config=None, state=None):
    adapter, action = _target_parts(target)
    config = config if isinstance(config, dict) else {}
    state = state if isinstance(state, dict) else {}
    declared = state.get('skill_targets') if isinstance(state.get('skill_targets'), dict) else {}
    configured = config.get('skill_invocation_targets')
    configured = configured if isinstance(configured, dict) else {}
    base = configured.get(adapter) or declared.get(adapter)
    if isinstance(base, dict): base = base.get('base_url')
    base = str(base or '').strip().rstrip('/')
    parsed = parse.urlparse(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
        raise InvocationError(f'未配置可信 skill target: {adapter}')
    return f'{base}/api/{action}'

def execute(invocation, config=None, state=None, opener=None, timeout=15):
    if not isinstance(invocation, dict) or invocation.get('mechanism') != 'skill':
        raise InvocationError('只接受 mechanism=skill')
    url = resolve_target(invocation.get('target'), config, state)
    params = invocation.get('params')
    if not isinstance(params, dict): raise InvocationError('skill invocation params 必须为对象')
    req = request.Request(url, data=json.dumps(params, ensure_ascii=False).encode(),
                          headers={'Content-Type':'application/json'}, method='POST')
    try:
        with (opener or request.urlopen)(req, timeout=timeout) as response:
            raw = response.read().decode(); result = json.loads(raw) if raw else {}
            status = getattr(response, 'status', 200)
    except error.HTTPError as exc:
        raw = exc.read().decode('utf-8', 'replace')
        try: result = json.loads(raw)
        except json.JSONDecodeError: result = {'error': raw or str(exc)}
        status = exc.code
    except (OSError, error.URLError) as exc:
        return {'ok':False, 'outcome':'failed', 'error':str(exc), 'message':str(exc)}, 502
    stale = status == 409 or result.get('stale') is True or result.get('outcome') == 'stale'
    ok = 200 <= status < 300 and result.get('ok', True) is not False
    outcome = 'stale' if stale else 'accepted' if ok else 'failed'
    message = result.get('message') or result.get('error') or outcome
    return {'ok':ok, 'outcome':outcome, 'status':status, 'result':result, 'message':message}, (200 if ok else status)

def proposal_key(item):
    return str(item.get('proposal_id') or item.get('proposalId') or item.get('id') or '').strip()

def reconcile(existing, decisions, auto_close=None):
    by_key = {proposal_key(x):dict(x) for x in existing if proposal_key(x)}
    for decision in decisions if isinstance(decisions, list) else []:
        key = proposal_key(decision)
        if not key: continue
        card = by_key.get(key, {'proposal_id':key, 'status':'review'})
        revision = int(decision.get('proposal_revision') or 0)
        if revision >= int(card.get('proposal_revision') or 0):
            card.update({'proposal_id':key, 'proposal_revision':revision,
              'evidence_hash':decision.get('evidence_hash',''), 'question':decision.get('question',key),
              'next_action':decision.get('next_action') or decision.get('question',''),
              'status':'review', 'decision_state':'pending'})
        by_key[key] = card
    signals = auto_close if isinstance(auto_close, list) else []
    for signal in signals:
        key = proposal_key(signal) if isinstance(signal, dict) else str(signal)
        if key in by_key: by_key[key].update(status='done', decision_state='auto_closed')
    return list(by_key.values())

def apply_invocation_result(card, result):
    card = dict(card); outcome = result.get('outcome')
    card.update(decision_state=outcome, decision_result=result.get('message', outcome or ''))
    if outcome in {'stale','failed'}:
        card.update(status='review', next_action=result.get('message') or '重新确认当前提案')
    return card
