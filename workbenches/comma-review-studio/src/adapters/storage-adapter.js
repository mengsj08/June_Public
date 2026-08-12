import { clone, createEditEvent, normalizeComment } from '../core/models.js';
import { revisionOf, RevisionConflictError } from '../core/revision.js';

export class StorageDocumentAdapter {
  constructor({ storage, key = 'comma-editor', seed = {} } = {}) {
    if (!storage || typeof storage.get !== 'function' || typeof storage.set !== 'function') {
      throw new TypeError('StorageDocumentAdapter requires async storage.get/set');
    }
    this.storage = storage;
    this.capabilities = {
      savePolicy: 'immediate',
      document: { load: true, save: true, replace: true },
      comments: { list: true, create: true, batch: true, update: true, delete: true },
      events: { list: true },
    };
    this.key = key;
    this.seed = {
      title: String(seed.title || 'untitled.md'),
      body: String(seed.body || ''),
      comments: (seed.comments || []).map(normalizeComment),
      events: clone(seed.events || []),
    };
  }

  async _read() {
    let record = await this.storage.get(this.key);
    if (!record) {
      const rev = await revisionOf(this.seed.body);
      record = { ...clone(this.seed), rev };
      await this.storage.set(this.key, record);
    }
    record.comments = Array.isArray(record.comments) ? record.comments.map(normalizeComment) : [];
    record.events = Array.isArray(record.events) ? record.events : [];
    record.rev = record.rev || await revisionOf(record.body || '');
    return record;
  }

  async _write(record) {
    await this.storage.set(this.key, clone(record));
  }

  async load() {
    const { title, body, rev } = await this._read();
    return clone({ title, body, rev });
  }

  async save({ body, baseRev, actor = 'user' }) {
    const record = await this._read();
    if (String(baseRev || '') !== String(record.rev || '')) {
      throw new RevisionConflictError({ expected: baseRev, actual: record.rev, body: record.body });
    }
    const nextBody = String(body ?? '');
    const nextRev = await revisionOf(nextBody);
    record.events.push(createEditEvent({
      actor,
      action: 'save-document',
      summary: `${nextBody.length} characters`,
      revBefore: record.rev,
      revAfter: nextRev,
    }));
    record.body = nextBody;
    record.rev = nextRev;
    await this._write(record);
    return clone({ title: record.title, body: record.body, rev: record.rev });
  }

  async replace({ title, body, actor = 'user' }) {
    const record = await this._read();
    const previousRev = record.rev;
    record.title = String(title || record.title || 'untitled.md');
    record.body = String(body ?? '');
    record.rev = await revisionOf(record.body);
    record.comments = [];
    record.events.push(createEditEvent({
      actor,
      action: 'replace-document',
      summary: record.title,
      revBefore: previousRev,
      revAfter: record.rev,
    }));
    await this._write(record);
    return clone({ title: record.title, body: record.body, rev: record.rev });
  }

  async listComments() {
    return clone((await this._read()).comments);
  }

  async createComment(input) {
    const record = await this._read();
    const comment = normalizeComment(input);
    record.comments.push(comment);
    record.events.push(createEditEvent({
      actor: comment.actor,
      action: 'create-comment',
      summary: comment.content.slice(0, 80),
      revBefore: record.rev,
      revAfter: record.rev,
    }));
    await this._write(record);
    return clone(comment);
  }

  async createComments({ comments = [], baseRev, actor = 'ai-review', source = 'ai-review' } = {}) {
    const record = await this._read();
    if (String(baseRev || '') !== String(record.rev || '')) {
      throw new RevisionConflictError({ expected: baseRev, actual: record.rev, body: record.body });
    }
    const created = comments.map((comment) => normalizeComment({
      ...comment,
      actor: comment.actor || actor,
      source: comment.source || source,
    }));
    record.comments.push(...created);
    record.events.push(createEditEvent({
      actor,
      action: 'create-comment-batch',
      summary: `${created.length} comments from ${source}`,
      revBefore: record.rev,
      revAfter: record.rev,
    }));
    await this._write(record);
    return clone({ comments: created, rev: record.rev });
  }

  async updateComment(id, patch = {}) {
    const record = await this._read();
    const index = record.comments.findIndex((comment) => comment.id === id);
    if (index < 0) throw new Error(`Comment not found: ${id}`);
    record.comments[index] = normalizeComment({ ...record.comments[index], ...patch, id, updatedAt: new Date().toISOString() });
    await this._write(record);
    return clone(record.comments[index]);
  }

  async deleteComment(id) {
    const record = await this._read();
    const kept = record.comments.filter((comment) => comment.id !== id);
    if (kept.length === record.comments.length) throw new Error(`Comment not found: ${id}`);
    record.comments = kept;
    await this._write(record);
  }

  async listEvents() {
    return clone((await this._read()).events);
  }
}

export class LocalStorageDocumentAdapter extends StorageDocumentAdapter {
  constructor(options = {}) {
    const area = options.area || globalThis.localStorage;
    if (!area) throw new Error('localStorage is not available');
    const storage = {
      async get(key) {
        const raw = area.getItem(key);
        if (!raw) return null;
        try { return JSON.parse(raw); } catch { return null; }
      },
      async set(key, value) {
        area.setItem(key, JSON.stringify(value));
      },
    };
    super({ ...options, storage });
  }
}

export class ChromeStorageDocumentAdapter extends StorageDocumentAdapter {
  constructor(options = {}) {
    const area = options.area || globalThis.chrome?.storage?.local;
    if (!area) throw new Error('chrome.storage.local is not available');
    const storage = {
      async get(key) {
        const result = await area.get(key);
        return result?.[key] || null;
      },
      async set(key, value) {
        await area.set({ [key]: value });
      },
    };
    super({ ...options, storage });
  }
}
