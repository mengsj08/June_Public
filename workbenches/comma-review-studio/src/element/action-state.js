import { isCommentVisible } from '../core/models.js';

export const COMMA_ACTION_STATE_SCHEMA = 'comma-action-state/v1';

function clone(value) {
  return structuredClone(value);
}

function capabilityAvailable(capabilities, appliesTo, defaultGroup = 'comments') {
  if (appliesTo == null || appliesTo === '') return true;
  if (Array.isArray(appliesTo)) {
    return appliesTo.every((item) => capabilityAvailable(capabilities, item, defaultGroup));
  }
  const raw = typeof appliesTo === 'object' ? appliesTo.capability : appliesTo;
  if (!raw) return true;
  const [group, name] = String(raw).includes('.')
    ? String(raw).split('.', 2)
    : [defaultGroup, String(raw)];
  return Boolean(capabilities?.[group]?.[name]);
}

function visibleCommentCount(comments = [], showWithdrawnComments = false) {
  return comments.filter((comment) => isCommentVisible(comment, {
    showWithdrawn: showWithdrawnComments,
  })).length;
}

export function buildToolbarActionState(action, context = {}) {
  const capabilities = context.capabilities || {};
  const rules = typeof action.appliesTo === 'object' && action.appliesTo ? action.appliesTo : {};
  const visible = capabilityAvailable(capabilities, action.appliesTo, 'document')
    && !(rules.requiresWritable && (context.readonly || !capabilities.document?.save));
  let reason = '';
  if (!visible) reason = 'capability';
  if (visible && rules.requiresCleanDocument && context.dirty) reason = 'dirty';
  if (visible && action.enabled === false) reason = 'host-disabled';
  const count = action.count === 'comments'
    ? visibleCommentCount(context.comments, context.showWithdrawnComments)
    : Number.isFinite(Number(action.count)) && action.count !== ''
      ? Number(action.count)
      : null;
  return {
    id: action.id,
    label: action.label,
    title: action.title || '',
    slot: action.slot === 'overflow' ? 'overflow' : 'primary',
    visible,
    enabled: visible && !reason,
    loading: Boolean(action.loading),
    count,
    countSource: action.count === 'comments' ? 'comments' : '',
    reason,
    action: clone(action),
  };
}

export function buildCommaActionState(context = {}) {
  const documentState = context.document || {};
  const body = String(documentState.body || '');
  const comments = Array.isArray(context.comments) ? context.comments : [];
  const toolbar = (Array.isArray(context.toolbarActions) ? context.toolbarActions : [])
    .map((action) => buildToolbarActionState(action, context));
  const visibleToolbar = toolbar.filter((action) => action.visible);
  const rev = String(documentState.rev || '');
  const sectionIndex = Array.isArray(context.sectionIndex) ? context.sectionIndex : [];
  const activeSectionId = String(context.activeSectionId || '');
  const activeSection = sectionIndex.find((section) => section.id === activeSectionId);
  return {
    schemaVersion: COMMA_ACTION_STATE_SCHEMA,
    document: {
      title: documentState.title || 'untitled.md',
      rev,
      shortRev: rev ? rev.replace('sha256-', '').slice(0, 8) : '',
      dirty: Boolean(context.dirty),
      readonly: Boolean(context.readonly),
      savePolicy: context.savePolicy || 'explicit',
      lineCount: body ? body.split('\n').length : 0,
    },
    status: {
      kind: context.status?.kind || '',
      text: context.status?.text || '',
    },
    capabilities: clone(context.capabilities || {}),
    comments: {
      count: visibleCommentCount(comments, context.showWithdrawnComments),
      total: comments.length,
      commentsRev: String(context.commentsRev || ''),
      open: Boolean(context.commentsOpen),
      showWithdrawn: Boolean(context.showWithdrawnComments),
    },
    outline: {
      open: Boolean(context.outlineOpen),
      mode: ['expanded', 'collapsed', 'drawer'].includes(context.outlineMode) ? context.outlineMode : 'collapsed',
      preference: context.outlinePreference === 'open' || context.outlinePreference === 'closed'
        ? context.outlinePreference
        : '',
      sectionCount: sectionIndex.length,
      activeSectionId,
      activeSectionTitle: String(activeSection?.title || ''),
    },
    toolbar: {
      actions: visibleToolbar,
      primary: visibleToolbar.filter((action) => action.slot === 'primary'),
      overflow: visibleToolbar.filter((action) => action.slot === 'overflow'),
    },
    selection: {
      actions: clone(Array.isArray(context.selectionActions) ? context.selectionActions : []),
      active: Boolean(context.selection?.quoteText),
    },
  };
}
