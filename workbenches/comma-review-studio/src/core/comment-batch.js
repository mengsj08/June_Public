import { findQuoteMatches, resolveQuote } from './anchors.js';

const READY_STATES = new Set(['unique', 'exact-revision', 'context']);
const PRIORITIES = new Set(['P0', 'P1', 'P2', 'P3']);

function locatorAt(body, quoteText, index, rev) {
  const matches = findQuoteMatches(body, quoteText);
  return {
    bodyRev: String(rev || ''),
    textIndex: index,
    blockIndex: -1,
    occurrenceIndex: matches.indexOf(index),
    prefix: body.slice(Math.max(0, index - 160), index),
    suffix: body.slice(index + quoteText.length, index + quoteText.length + 160),
  };
}
function normalizePriority(value) {
  const priority = String(value || '').toUpperCase();
  return PRIORITIES.has(priority) ? priority : '';
}

function normalizeProposal(input, index) {
  const quoteText = String(input?.quoteText ?? input?.quote_text ?? '').trim();
  const requestedKind = String(input?.kind || '').toLowerCase();
  return {
    proposalId: String(input?.proposalId ?? input?.proposal_id ?? input?.id ?? `proposal-${index + 1}`),
    kind: requestedKind === 'overall' ? 'overall' : 'anchored',
    content: String(input?.content || '').trim(),
    quoteText,
    section: String(input?.section || '').trim(),
    priority: normalizePriority(input?.priority),
    sourceLocator: input?.sourceLocator || input?.source_locator || null,
  };
}

function invalidItem(proposal, reason) {
  return {
    proposalId: proposal.proposalId,
    status: 'invalid',
    reason,
    matchCount: 0,
    matches: [],
    comment: proposal,
  };
}

/**
 * Validate an AI or host-proposed comment batch without mutating the adapter.
 * Only unique or explicitly contextualized anchors become ready. Ambiguous
 * anchors stay blocked so a host can ask the reviewer for a more exact quote.
 */
export function previewCommentBatch({ body = '', rev = '', comments = [] } = {}) {
  const source = String(body || '');
  const seen = new Set();
  const items = (Array.isArray(comments) ? comments : []).map((input, index) => {
    const proposal = normalizeProposal(input, index);
    if (!proposal.content) return invalidItem(proposal, 'Comment content is required');
    if (proposal.kind === 'anchored' && !proposal.quoteText) {
      return invalidItem(proposal, 'An anchored comment needs an exact quote');
    }

    const signature = `${proposal.kind}\u0000${proposal.quoteText}\u0000${proposal.content}`;
    if (seen.has(signature)) return invalidItem(proposal, 'Duplicate proposal in this batch');
    seen.add(signature);

    if (proposal.kind === 'overall') {
      return {
        proposalId: proposal.proposalId,
        status: 'ready',
        reason: 'Whole-document comment',
        matchCount: 0,
        matches: [],
        comment: { ...proposal, quoteText: '', sourceLocator: null, anchorState: 'overall' },
      };
    }

    const resolution = resolveQuote(source, proposal.quoteText, proposal.sourceLocator || {}, rev);
    if (!READY_STATES.has(resolution.state)) {
      return {
        proposalId: proposal.proposalId,
        status: resolution.state === 'ambiguous' ? 'ambiguous' : 'missing',
        reason: resolution.state === 'ambiguous'
          ? `${resolution.matches.length} source matches; a more exact quote is required`
          : 'Quoted text was not found in the current Markdown source',
        matchCount: resolution.matches.length,
        matches: [...resolution.matches],
        comment: { ...proposal, anchorState: resolution.state },
      };
    }

    return {
      proposalId: proposal.proposalId,
      status: 'ready',
      reason: resolution.state,
      matchCount: resolution.matches.length,
      matches: [...resolution.matches],
      comment: {
        ...proposal,
        sourceLocator: locatorAt(source, proposal.quoteText, resolution.index, rev),
        anchorState: resolution.state,
      },
    };
  });

  const counts = { total: items.length, ready: 0, ambiguous: 0, missing: 0, invalid: 0 };
  for (const item of items) counts[item.status] += 1;
  return { baseRev: String(rev || ''), counts, items };
}
