import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

P = Path(__file__).with_name('skill_invocation.py')
spec = importlib.util.spec_from_file_location('skill_invocation_tested', P)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class Response:
    status = 200
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.payload).encode()

def invocation(revision=1):
    return {'mechanism':'skill', 'target':'skill-board/decision-action',
            'params':{'proposalId':'p1','proposalRevision':revision,'evidenceHash':'h','action':'approve'}}

def test_approve_posts_and_auto_close():
    seen = {}
    def opener(req, timeout):
        seen['url'] = req.full_url; seen['body'] = json.loads(req.data)
        return Response({'ok':True, 'message':'accepted'})
    result, status = mod.execute(invocation(), {'skill_invocation_targets':{'skill-board':'http://127.0.0.1:7788'}}, opener=opener)
    assert status == 200 and result['outcome'] == 'accepted'
    assert seen['url'].endswith('/api/decision-action') and seen['body']['proposalId'] == 'p1'
    cards = mod.reconcile([], [{'id':'p1','proposal_revision':1}], [{'proposal_id':'p1'}])
    assert len(cards) == 1 and cards[0]['status'] == 'done'

def test_stale_rejection_returns_card_to_review():
    def opener(req, timeout):
        raise HTTPError(req.full_url, 409, 'conflict', {}, io.BytesIO(b'{"error":"revision stale","stale":true}'))
    result, status = mod.execute(invocation(), {'skill_invocation_targets':{'skill-board':'http://localhost:7788'}}, opener=opener)
    card = mod.apply_invocation_result({'status':'done'}, result)
    assert status == 409 and result['outcome'] == 'stale'
    assert card['status'] == 'review' and 'stale' in card['next_action']

def test_reopen_updates_original_card_without_duplicate():
    old = [{'proposal_id':'p1','proposal_revision':1,'status':'done'}]
    cards = mod.reconcile(old, [{'id':'p1','proposal_revision':2,'question':'重新登录后确认'}])
    assert len(cards) == 1 and cards[0]['proposal_revision'] == 2
    assert cards[0]['status'] == 'review' and cards[0]['next_action'] == '重新登录后确认'

def test_duplicate_projection_is_idempotent():
    decision = {'id':'p1','proposal_revision':3,'evidence_hash':'h3'}
    once = mod.reconcile([], [decision, decision])
    twice = mod.reconcile(once, [decision])
    assert len(once) == len(twice) == 1 and twice[0] == once[0]
