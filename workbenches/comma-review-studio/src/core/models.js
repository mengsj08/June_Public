function randomId(prefix) {
  if (globalThis.crypto?.randomUUID) return `${prefix}_${globalThis.crypto.randomUUID()}`;
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

export const COMMA_SCHEMAS = Object.freeze({
  document: 'comma-document/v1',
  comment: 'comma-comment/v1',
  finding: 'comma-finding/v1',
  reviewSession: 'comma-review-session/v1',
  conversationSession: 'comma-conversation-session/v1',
  writebackReceipt: 'comma-writeback-receipt/v1',
  editEvent: 'comma-edit-event/v1',
});

const LIFECYCLE_STATES = new Set(['active', 'withdrawn']);
const FINDING_STATES = new Set(['provisional', 'accepted', 'pending', 'withdrawn']);

function first(input, ...keys) {
  for (const key of keys) {
    if (input?.[key] != null) return input[key];
  }
  return undefined;
}

function normalizedDecision(value) {
  const decision = String(value || 'proposed').trim().toLowerCase();
  return ['accepted', 'proposed', 'rejected'].includes(decision) ? decision : 'proposed';
}

function normalizedBoolean(value) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase());
}

function normalizedLifecycleState(value) {
  const state = String(value || 'active').trim().toLowerCase();
  return LIFECYCLE_STATES.has(state) ? state : 'active';
}

function normalizedFindingState(input) {
  const explicit = String(first(input, 'findingState', 'finding_state') || '').trim().toLowerCase();
  if (FINDING_STATES.has(explicit)) return explicit;
  const legacy = String(first(input, 'reviewState', 'review_state') || '').trim().toLowerCase();
  if (legacy === 'active') return 'accepted';
  if (legacy === 'pending' || legacy === 'withdrawn') return legacy;
  return '';
}

export function normalizeCommentReply(input = {}) {
  return {
    id: String(input.id || randomId('reply')),
    actor: String(first(input, 'actor', 'author') || 'user'),
    content: String(input.content || '').trim(),
    createdAt: String(first(input, 'createdAt', 'created_at') || new Date().toISOString()),
    updatedAt: String(first(input, 'updatedAt', 'updated_at') || new Date().toISOString()),
    state: normalizedLifecycleState(input.state),
  };
}

export function normalizeDocument(input = {}) {
  return {
    schemaVersion: String(first(input, 'schemaVersion', 'schema_version') || COMMA_SCHEMAS.document),
    id: String(first(input, 'id', 'documentId', 'document_id', 'path') || ''),
    title: String(first(input, 'title', 'name', 'path') || 'untitled.md'),
    body: String(first(input, 'body', 'content') || ''),
    rev: String(first(input, 'rev', 'sha256', 'revision') || ''),
  };
}

export function normalizeComment(input = {}) {
  const quoteText = String(first(input, 'quoteText', 'quote_text') || '').trim();
  const sourceLocator = first(input, 'sourceLocator', 'source_locator') || null;
  const kind = input.kind === 'overall' || (!quoteText && !sourceLocator) ? 'overall' : 'anchored';
  const priority = String(input.priority || '').toUpperCase();
  const findingState = normalizedFindingState(input);
  const commentVersion = Number(first(input, 'commentVersion', 'comment_version') || 1);
  return {
    schemaVersion: String(first(input, 'schemaVersion', 'schema_version') || COMMA_SCHEMAS.comment),
    id: String(input.id || randomId('comment')),
    kind,
    content: String(input.content || '').trim(),
    quoteText,
    sourceLocator,
    anchorState: String(first(input, 'anchorState', 'anchor_state') || (kind === 'overall' ? 'overall' : 'unresolved')),
    section: String(input.section || '').trim(),
    priority: ['P0', 'P1', 'P2', 'P3'].includes(priority) ? priority : '',
    source: String(input.source || (String(first(input, 'actor', 'author') || '').toLowerCase().includes('ai') ? 'ai-review' : 'manual')),
    actor: String(first(input, 'actor', 'author') || 'user'),
    sourceKey: String(first(input, 'sourceKey', 'source_key') || ''),
    findingId: String(first(input, 'findingId', 'finding_id') || ''),
    reviewSessionId: String(first(input, 'reviewSessionId', 'review_session_id') || ''),
    reviewRunId: String(first(input, 'reviewRunId', 'review_run_id') || ''),
    appliedSignature: String(first(input, 'appliedSignature', 'applied_signature') || ''),
    appliedOperationId: String(first(input, 'appliedOperationId', 'applied_operation_id') || ''),
    conversationSessionId: String(first(input, 'conversationSessionId', 'conversation_session_id') || ''),
    conversationMessageId: String(first(input, 'conversationMessageId', 'conversation_message_id') || ''),
    reviewState: String(first(input, 'reviewState', 'review_state') || 'active'),
    lifecycleState: normalizedLifecycleState(first(input, 'lifecycleState', 'lifecycle_state')),
    findingState,
    commentVersion: Number.isInteger(commentVersion) && commentVersion > 0 ? commentVersion : 1,
    humanEdited: normalizedBoolean(first(input, 'humanEdited', 'human_edited')),
    originSignature: String(first(input, 'originSignature', 'origin_signature') || ''),
    withdrawnAt: String(first(input, 'withdrawnAt', 'withdrawn_at') || ''),
    withdrawnBy: String(first(input, 'withdrawnBy', 'withdrawn_by') || ''),
    withdrawReason: String(first(input, 'withdrawReason', 'withdraw_reason') || ''),
    replies: (Array.isArray(input.replies) ? input.replies : []).map(normalizeCommentReply),
    createdAt: String(first(input, 'createdAt', 'created_at') || new Date().toISOString()),
    updatedAt: String(first(input, 'updatedAt', 'updated_at') || new Date().toISOString()),
  };
}

export function isCommentWithdrawn(comment = {}) {
  const normalized = normalizeComment(comment);
  return normalized.lifecycleState === 'withdrawn' || normalized.findingState === 'withdrawn';
}

export function isCommentVisible(comment = {}, { showWithdrawn = false } = {}) {
  return Boolean(showWithdrawn || !isCommentWithdrawn(comment));
}

export function normalizeFinding(input = {}, fallbackId = '') {
  const priority = String(input.priority || 'P2').toUpperCase();
  return {
    schemaVersion: String(first(input, 'schemaVersion', 'schema_version') || COMMA_SCHEMAS.finding),
    id: String(input.id || fallbackId || randomId('finding')),
    quoteText: String(first(input, 'quoteText', 'quote_text') || '').trim(),
    issue: String(input.issue || '').trim(),
    action: String(input.action || '').trim(),
    priority: ['P0', 'P1', 'P2', 'P3'].includes(priority) ? priority : 'P2',
    decision: normalizedDecision(input.decision),
    section: String(input.section || '').trim(),
    evidenceRequirement: String(first(input, 'evidenceRequirement', 'evidence_requirement') || '').trim(),
    rationale: String(input.rationale || '').trim(),
    anchorState: String(first(input, 'anchorState', 'anchor_state') || 'unresolved'),
    sourceLocator: first(input, 'sourceLocator', 'source_locator') || null,
    appliedCommentId: String(first(input, 'appliedCommentId', 'applied_comment_id') || ''),
    version: Math.max(1, Number(input.version || 1) || 1),
  };
}

export function normalizeWritebackReceipt(input = {}) {
  const list = (key) => Array.isArray(input[key]) ? clone(input[key]) : [];
  return {
    schemaVersion: String(first(input, 'schemaVersion', 'schema_version') || COMMA_SCHEMAS.writebackReceipt),
    id: String(input.id || randomId('receipt')),
    baseRev: String(first(input, 'baseRev', 'base_rev') || ''),
    created: list('created'),
    updated: list('updated'),
    skipped: list('skipped'),
    blocked: list('blocked'),
    at: String(first(input, 'at', 'createdAt', 'created_at') || new Date().toISOString()),
  };
}

export function normalizeReviewSession(input = {}) {
  return {
    schemaVersion: String(first(input, 'schemaVersion', 'schema_version') || COMMA_SCHEMAS.reviewSession),
    id: String(input.id || randomId('review')),
    documentId: String(first(input, 'documentId', 'document_id', 'docPath', 'doc_path') || ''),
    baseRev: String(first(input, 'baseRev', 'base_rev') || ''),
    documentRev: String(first(input, 'documentRev', 'document_rev') || first(input, 'baseRev', 'base_rev') || ''),
    tool: String(input.tool || ''),
    status: String(input.status || 'ready'),
    summary: String(input.summary || ''),
    findings: (Array.isArray(input.findings) ? input.findings : []).map((item, index) => normalizeFinding(item, `F${String(index + 1).padStart(3, '0')}`)),
    messages: clone(Array.isArray(input.messages) ? input.messages : []),
    writebackReceipts: (Array.isArray(first(input, 'writebackReceipts', 'writeback_receipts'))
      ? first(input, 'writebackReceipts', 'writeback_receipts') : []).map(normalizeWritebackReceipt),
    createdAt: String(first(input, 'createdAt', 'created_at') || ''),
    updatedAt: String(first(input, 'updatedAt', 'updated_at') || ''),
  };
}

export function normalizeSourceQuote(input = {}) {
  return {
    quoteText: String(first(input, 'quoteText', 'quote_text') || '').trim(),
    section: String(input.section || '').trim(),
    sourceLocator: first(input, 'sourceLocator', 'source_locator') || null,
  };
}

export function normalizeConversationMessage(input = {}) {
  const role = String(input.role || 'assistant').toLowerCase();
  return {
    id: String(input.id || randomId('message')),
    role: ['user', 'assistant', 'note'].includes(role) ? role : 'assistant',
    content: String(input.content || '').trim(),
    author: String(input.author || ''),
    parentId: String(first(input, 'parentId', 'parent_id') || ''),
    branchId: String(first(input, 'branchId', 'branch_id') || 'main'),
    branchFromMessageId: String(first(input, 'branchFromMessageId', 'branch_from_message_id') || ''),
    noteForMessageId: String(first(input, 'noteForMessageId', 'note_for_message_id') || ''),
    writebackCommentId: String(first(input, 'writebackCommentId', 'writeback_comment_id') || ''),
    mode: String(input.mode || ''),
    at: String(input.at || first(input, 'createdAt', 'created_at') || ''),
  };
}

export function normalizeConversationSession(input = {}) {
  return {
    schemaVersion: String(first(input, 'schemaVersion', 'schema_version') || COMMA_SCHEMAS.conversationSession),
    id: String(input.id || randomId('conversation')),
    documentId: String(first(input, 'documentId', 'document_id', 'docPath', 'doc_path') || ''),
    baseRev: String(first(input, 'baseRev', 'base_rev') || ''),
    documentRev: String(first(input, 'documentRev', 'document_rev') || first(input, 'baseRev', 'base_rev') || ''),
    tool: String(input.tool || ''),
    status: String(input.status || 'ready'),
    sourceQuote: normalizeSourceQuote(first(input, 'sourceQuote', 'source_quote') || {}),
    messages: (Array.isArray(input.messages) ? input.messages : []).map(normalizeConversationMessage),
    writebackReceipts: clone(Array.isArray(first(input, 'writebackReceipts', 'writeback_receipts'))
      ? first(input, 'writebackReceipts', 'writeback_receipts') : []),
    createdAt: String(first(input, 'createdAt', 'created_at') || ''),
    updatedAt: String(first(input, 'updatedAt', 'updated_at') || ''),
  };
}

export function createEditEvent({ actor = 'user', action, summary = '', revBefore = '', revAfter = '' }) {
  if (!action) throw new TypeError('EditEvent.action is required');
  return {
    schemaVersion: COMMA_SCHEMAS.editEvent,
    id: randomId('event'),
    at: new Date().toISOString(),
    actor: String(actor || 'user'),
    action: String(action),
    summary: String(summary || ''),
    revBefore: String(revBefore || ''),
    revAfter: String(revAfter || ''),
  };
}

export function clone(value) {
  return value == null ? value : structuredClone(value);
}
