import { RevisionConflictError } from '../core/revision.js';

async function requestJson(url, init = {}) {
  const response = await fetch(url, init);
  let data = {};
  try { data = await response.json(); } catch { data = {}; }
  if (response.status === 409 && data.code === 'comment_version_conflict') {
    const error = new Error(data.message || 'Comment changed before this action');
    error.name = 'CommentVersionConflictError';
    error.code = 'COMMENT_VERSION_CONFLICT';
    error.currentComment = data.current_comment || null;
    error.commentsRev = String(data.comments_rev || '');
    throw error;
  }
  if (response.status === 409 || data.conflict) {
    throw new RevisionConflictError({
      expected: data.expected || '',
      actual: data.rev || data.actual || '',
      body: data.body || '',
      draft: data.draft || null,
    });
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || data.message || `HTTP ${response.status}`);
  }
  return data;
}

export class HttpDocumentAdapter {
  constructor({ documentUrl, commentsUrl, commentsBatchUrl = '', eventsUrl = '', assetUrl = '', headers = {} } = {}) {
    if (!documentUrl || !commentsUrl) throw new TypeError('documentUrl and commentsUrl are required');
    this.documentUrl = documentUrl;
    this.commentsUrl = commentsUrl;
    this.commentsBatchUrl = commentsBatchUrl;
    this.eventsUrl = eventsUrl;
    this.assetUrl = assetUrl;
    this.headers = { ...headers };
    this.commentsRev = '';
    this.capabilities = {
      savePolicy: 'immediate',
      document: { load: true, save: true, replace: false },
      comments: {
        list: true,
        create: true,
        batch: Boolean(commentsBatchUrl),
        update: true,
        delete: true,
        restore: true,
        reply: true,
        history: true,
      },
      events: { list: Boolean(eventsUrl) },
      assets: { resolve: Boolean(assetUrl) },
    };
  }

  _json(method, body) {
    return {
      method,
      headers: { 'Content-Type': 'application/json', ...this.headers },
      body: JSON.stringify(body),
    };
  }

  _commentItemUrl(id, suffix = '') {
    const [path, query = ''] = this.commentsUrl.split('?', 2);
    const itemPath = `${path.replace(/\/$/, '')}/${encodeURIComponent(id)}${suffix}`;
    return query ? `${itemPath}?${query}` : itemPath;
  }

  _rememberCommentsRev(data) {
    if (data?.comments_rev != null) this.commentsRev = String(data.comments_rev);
    return data;
  }

  async load() {
    const data = await requestJson(this.documentUrl, { headers: this.headers });
    return { title: data.title || data.path || 'document.md', body: data.body || '', rev: data.rev || '' };
  }

  async save({ body, baseRev, actor }) {
    try {
      const data = await requestJson(this.documentUrl, this._json('PUT', {
        body,
        base_rev: baseRev,
        actor,
      }));
      return { title: data.title || data.path || 'document.md', body: data.body ?? body, rev: data.rev || '' };
    } catch (error) {
      if (error instanceof RevisionConflictError) error.draftBody = String(body ?? '');
      throw error;
    }
  }

  async listComments() {
    const data = this._rememberCommentsRev(await requestJson(this.commentsUrl, { headers: this.headers }));
    return data.comments || [];
  }

  async createComment(comment) {
    const data = this._rememberCommentsRev(await requestJson(this.commentsUrl, this._json('POST', comment)));
    return data.comment || (data.comments || []).at(-1);
  }

  async createComments({ comments, baseRev, actor, source }) {
    if (!this.commentsBatchUrl) {
      throw new Error('commentsBatchUrl is required for atomic comment batches');
    }
    const data = this._rememberCommentsRev(await requestJson(this.commentsBatchUrl, this._json('POST', {
      comments,
      base_rev: baseRev,
      actor,
      source,
    })));
    return { comments: data.comments || [], rev: data.rev || baseRev };
  }

  async updateComment(id, patch) {
    const data = this._rememberCommentsRev(await requestJson(this._commentItemUrl(id), this._json('PATCH', {
      base_comment_version: patch.baseCommentVersion ?? patch.base_comment_version,
      content: patch.content,
      actor: patch.actor,
    })));
    return data.comment || (data.comments || []).find((comment) => comment.id === id);
  }

  async deleteComment(id, options = {}) {
    const data = this._rememberCommentsRev(await requestJson(this._commentItemUrl(id), this._json('DELETE', {
      base_comment_version: options.baseCommentVersion ?? options.base_comment_version,
      actor: options.actor,
      reason: options.reason,
    })));
    return data.comment || null;
  }

  async restoreComment(id, options = {}) {
    const data = this._rememberCommentsRev(await requestJson(this._commentItemUrl(id, '/restore'), this._json('POST', {
      base_comment_version: options.baseCommentVersion ?? options.base_comment_version,
      actor: options.actor,
    })));
    return data.comment || null;
  }

  async createCommentReply(id, options = {}) {
    const data = this._rememberCommentsRev(await requestJson(this._commentItemUrl(id, '/replies'), this._json('POST', {
      base_comment_version: options.baseCommentVersion ?? options.base_comment_version,
      actor: options.actor,
      content: options.content,
    })));
    return data.comment || null;
  }

  async updateCommentReply(id, replyId, options = {}) {
    const data = this._rememberCommentsRev(await requestJson(
      this._commentItemUrl(id, `/replies/${encodeURIComponent(replyId)}`),
      this._json('PATCH', {
        base_comment_version: options.baseCommentVersion ?? options.base_comment_version,
        actor: options.actor,
        content: options.content,
      }),
    ));
    return data.comment || null;
  }

  async deleteCommentReply(id, replyId, options = {}) {
    const data = this._rememberCommentsRev(await requestJson(
      this._commentItemUrl(id, `/replies/${encodeURIComponent(replyId)}`),
      this._json('DELETE', {
        base_comment_version: options.baseCommentVersion ?? options.base_comment_version,
        actor: options.actor,
      }),
    ));
    return data.comment || null;
  }

  async listCommentEvents(id) {
    const data = await requestJson(this._commentItemUrl(id, '/events'), { headers: this.headers });
    return data.events || [];
  }

  async listEvents() {
    if (!this.eventsUrl) return [];
    const data = await requestJson(this.eventsUrl, { headers: this.headers });
    return data.events || [];
  }

  resolveAsset({ src }) {
    const source = String(src || '').trim();
    if (!this.assetUrl || !source) return source;
    if (/^(?:https?:|data:|blob:)/i.test(source) || source.startsWith('//')) return source;
    const separator = this.assetUrl.includes('?') ? '&' : '?';
    return `${this.assetUrl}${separator}source=${encodeURIComponent(source)}`;
  }
}
