import { clone, createEditEvent, normalizeComment } from '../core/models.js';
import { revisionOf, RevisionConflictError } from '../core/revision.js';

export class MemoryDocumentAdapter {
  constructor({ title = 'untitled.md', body = '', comments = [], events = [] } = {}) {
    this.capabilities = {
      savePolicy: 'immediate',
      document: { load: true, save: true, replace: false },
      comments: { list: true, create: true, batch: true, update: true, delete: true },
      events: { list: true },
    };
    this._record = {
      title: String(title || 'untitled.md'),
      body: String(body || ''),
      rev: '',
      comments: comments.map(normalizeComment),
      events: clone(events) || [],
    };
    this._ready = revisionOf(this._record.body).then((rev) => { this._record.rev = rev; });
  }

  async _beforeRead() {
    await this._ready;
  }

  async load() {
    await this._beforeRead();
    const { title, body, rev } = this._record;
    return clone({ title, body, rev });
  }

  async save({ body, baseRev, actor = 'user' }) {
    await this._beforeRead();
    if (String(baseRev || '') !== this._record.rev) {
      throw new RevisionConflictError({ expected: baseRev, actual: this._record.rev, body: this._record.body });
    }
    const nextBody = String(body ?? '');
    const nextRev = await revisionOf(nextBody);
    const previousRev = this._record.rev;
    this._record.body = nextBody;
    this._record.rev = nextRev;
    this._record.events.push(createEditEvent({
      actor,
      action: 'save-document',
      summary: `${nextBody.length} characters`,
      revBefore: previousRev,
      revAfter: nextRev,
    }));
    const { title } = this._record;
    return clone({ title, body: nextBody, rev: nextRev });
  }

  async listComments() {
    await this._beforeRead();
    return clone(this._record.comments);
  }

  async createComment(input) {
    await this._beforeRead();
    const comment = normalizeComment(input);
    this._record.comments.push(comment);
    this._record.events.push(createEditEvent({
      actor: comment.actor,
      action: 'create-comment',
      summary: comment.content.slice(0, 80),
      revBefore: this._record.rev,
      revAfter: this._record.rev,
    }));
    return clone(comment);
  }

  async createComments({ comments = [], baseRev, actor = 'ai-review', source = 'ai-review' } = {}) {
    await this._beforeRead();
    if (String(baseRev || '') !== this._record.rev) {
      throw new RevisionConflictError({ expected: baseRev, actual: this._record.rev, body: this._record.body });
    }
    const created = comments.map((comment) => normalizeComment({
      ...comment,
      actor: comment.actor || actor,
      source: comment.source || source,
    }));
    this._record.comments.push(...created);
    this._record.events.push(createEditEvent({
      actor,
      action: 'create-comment-batch',
      summary: `${created.length} comments from ${source}`,
      revBefore: this._record.rev,
      revAfter: this._record.rev,
    }));
    return clone({ comments: created, rev: this._record.rev });
  }

  async updateComment(id, patch = {}) {
    await this._beforeRead();
    const index = this._record.comments.findIndex((comment) => comment.id === id);
    if (index < 0) throw new Error(`Comment not found: ${id}`);
    const next = normalizeComment({ ...this._record.comments[index], ...patch, id, updatedAt: new Date().toISOString() });
    this._record.comments[index] = next;
    return clone(next);
  }

  async deleteComment(id) {
    await this._beforeRead();
    const before = this._record.comments.length;
    this._record.comments = this._record.comments.filter((comment) => comment.id !== id);
    if (before === this._record.comments.length) throw new Error(`Comment not found: ${id}`);
  }

  async listEvents() {
    await this._beforeRead();
    return clone(this._record.events);
  }
}
