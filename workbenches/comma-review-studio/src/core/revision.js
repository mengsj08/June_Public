const encoder = new TextEncoder();

export async function revisionOf(body) {
  const text = String(body ?? '');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', encoder.encode(text));
  const short = Array.from(new Uint8Array(digest).slice(0, 10))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
  return `sha256-${short}`;
}

export class RevisionConflictError extends Error {
  constructor({ expected, actual, body, draft = null, draftBody = '' }) {
    super(`Document revision changed: expected ${expected || 'none'}, actual ${actual || 'none'}`);
    this.name = 'RevisionConflictError';
    this.code = 'REVISION_CONFLICT';
    this.expected = expected || '';
    this.actual = actual || '';
    this.body = String(body ?? '');
    this.draft = draft && typeof draft === 'object' ? { ...draft } : null;
    this.draftBody = String(draftBody ?? '');
  }
}
