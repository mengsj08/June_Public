export function setupMarkdown(ctx) {
  const { ui, dataState, uiState } = ctx;
  const { esc, toast } = ui;
  const { lightboxOverlay, lightboxImage, lightboxCaption, fmResults, fmTabs, fileMentionDd } = ctx.el;

  const BOX_DRAW_RE = /[┌┬┐├┼┤└┴┘│─]/;
  const FENCED_CODE_RE = /^```/;
  const COMMENT_QUOTE_OPEN_RE = /^:::comment-quote\b(.*)$/;
  const MERMAID_FALLBACK_MESSAGE = 'Mermaid 渲染失败';

  if (window.mermaid && typeof window.mermaid.initialize === 'function') {
    mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'loose' });
  }

  const markedLib = window.marked;
  if (markedLib && typeof markedLib.use === 'function') {
    markedLib.use({
      renderer: {
        code({ text, lang }) {
          if ((lang || '').trim().toLowerCase() === 'mermaid') {
            return '<div class="mermaid-wrapper"><div class="mermaid">' + text + '</div></div>';
          }
          const source = text || '';
          if (window.hljs) {
            if (lang && hljs.getLanguage(lang)) {
              return '<pre><code class="hljs language-' + lang + '">' + hljs.highlight(source, { language: lang, ignoreIllegals: true }).value + '</code></pre>';
            }
            return '<pre><code class="hljs">' + hljs.highlightAuto(source).value + '</code></pre>';
          }
          return '<pre><code>' + esc(source) + '</code></pre>';
        }
      }
    });
  }

  function parseMarkdown(markdown, options) {
    const prepared = _prepareCommentQuoteTokens(preprocessMarkdown(markdown || ''), options);
    if (options && typeof options.onCommentQuotes === 'function') {
      options.onCommentQuotes(prepared.commentQuotes);
    }
    const source = prepared.markdown;
    if (markedLib && typeof markedLib.parse === 'function') {
      return markedLib.parse(source);
    }
    return '<pre class="markdown-fallback"><code>' + esc(source) + '</code></pre>';
  }

  function _commentQuoteAttrUnescape(value) {
    return String(value || '').replace(/\\(["\\])/g, '$1');
  }

  function _parseCommentQuoteAttrs(text) {
    const attrs = {};
    String(text || '').replace(/([a-zA-Z0-9_-]+)="((?:\\.|[^"\\])*)"/g, (_, key, value) => {
      attrs[key] = _commentQuoteAttrUnescape(value);
      return '';
    });
    return attrs;
  }

  function _isValidCommentRef(ref) {
    return /^[^#\s"<>]+#[0-9]+$/.test(String(ref || ''));
  }

  function _commentQuoteHash(value) {
    let hash = 5381;
    const text = String(value || '');
    for (let i = 0; i < text.length; i += 1) hash = ((hash << 5) + hash) ^ text.charCodeAt(i);
    return (hash >>> 0).toString(36);
  }

  function _nearestCommentContext(lines, index, endIndex) {
    let heading = '';
    for (let i = index - 1; i >= 0; i -= 1) {
      const match = String(lines[i] || '').trim().match(/^#{1,6}\s+(.+)$/);
      if (match) {
        heading = match[1].replace(/\s+#+\s*$/, '').trim();
        break;
      }
    }
    if (!heading) {
      for (let i = (Number.isInteger(endIndex) ? endIndex + 1 : index + 1); i < lines.length; i += 1) {
        const text = String(lines[i] || '').trim();
        if (/^:::comment-quote\b/.test(text)) break;
        const match = text.match(/^#{1,6}\s+(.+)$/);
        if (match) {
          heading = match[1].replace(/\s+#+\s*$/, '').trim();
          break;
        }
      }
    }
    let paragraph = '';
    for (let i = index - 1; i >= 0; i -= 1) {
      const text = String(lines[i] || '').trim();
      if (!text) {
        if (paragraph) break;
        continue;
      }
      if (/^#{1,6}\s+/.test(text) || text === ':::' || /^:::comment-quote\b/.test(text)) break;
      paragraph = text.replace(/^[-*+]\s+/, '').replace(/^>\s?/, '').trim();
      if (paragraph) break;
    }
    if (!paragraph) {
      for (let i = (Number.isInteger(endIndex) ? endIndex + 1 : index + 1); i < lines.length; i += 1) {
        const text = String(lines[i] || '').trim();
        if (/^:::comment-quote\b/.test(text)) break;
        if (!text || text === ':::') continue;
        if (/^#{1,6}\s+/.test(text)) continue;
        paragraph = text.replace(/^[-*+]\s+/, '').replace(/^>\s?/, '').trim();
        if (paragraph) break;
      }
    }
    return { heading, paragraph };
  }

  function _encodeBodyQuoteData(value) {
    try { return encodeURIComponent(String(value || '')); } catch (e) { return ''; }
  }

  function _decodeBodyQuoteData(value) {
    try { return decodeURIComponent(String(value || '')); } catch (e) { return String(value || ''); }
  }

  function _bodyQuoteFromButton(button) {
    const locatorText = _decodeBodyQuoteData(button.dataset.bodyLocator || '');
    let locator = {};
    try {
      locator = locatorText ? JSON.parse(locatorText) : {};
    } catch (e) {
      locator = {};
    }
    return {
      quote_text: _decodeBodyQuoteData(button.dataset.bodyQuote || ''),
      section: button.dataset.bodySection || '',
      source_locator: locator,
      context: {
        prefix: locator.prefix || '',
        suffix: locator.suffix || '',
      },
    };
  }

  function _renderCommentQuoteHtml(attrs, quoteText, meta) {
    attrs = attrs || {};
    if (attrs.source === 'body' && !(meta && meta.asAnchor)) {
      const quote = String(quoteText || '').trim();
      const paragraphs = quote
        ? quote.split(/\n{2,}/).map((part) => '<p>' + esc(part).replace(/\n/g, '<br>') + '</p>').join('')
        : '<p class="comment-quote-empty">（空引文）</p>';
      const section = String(attrs.section || '').trim();
      const label = section ? ('引用正文 · ' + section) : '引用正文';
      const encodedQuote = _encodeBodyQuoteData(quote);
      const encodedLocator = String(attrs.locator || '');
      return '<div class="comment-quote-block body-quote-block" data-source="body" data-body-locator="' + esc(encodedLocator) + '" data-body-quote="' + esc(encodedQuote) + '" data-body-section="' + esc(section) + '">'
        + '<blockquote class="comment-quote-text">' + paragraphs + '</blockquote>'
        + '<div class="comment-quote-meta"><span class="comment-quote-author">' + esc(label) + '</span>'
        + '<button type="button" class="comment-quote-jump body-quote-jump" data-body-locator="' + esc(encodedLocator) + '" data-body-quote="' + esc(encodedQuote) + '" data-body-section="' + esc(section) + '">↩ 跳到正文原位</button></div>'
        + '</div>';
    }
    const ref = String(attrs.ref || '').trim();
    const author = attrs.author || '';
    const reachable = _isValidCommentRef(ref);
    const safeRef = reachable ? ref : '';
    const quote = String(quoteText || '').trim();
    if (meta && meta.asAnchor) {
      const anchorKey = String(meta.anchorKey || ('cq-' + _commentQuoteHash(ref + '\0' + author + '\0' + quote)));
      const status = attrs.source === 'body' ? 'body-source' : (!ref ? 'missing-ref' : (reachable ? 'ready' : 'invalid-ref'));
      const label = status === 'ready' || status === 'body-source' ? '查看批注' : '查看批注（来源不可达）';
      return '<button type="button" class="comment-quote-anchor" data-comment-anchor="' + esc(anchorKey)
        + '" data-comment-ref="' + esc(safeRef) + '" data-comment-ref-status="' + status
        + '" aria-label="' + esc(label) + '" title="' + esc(label) + '"><span aria-hidden="true">批注</span></button>';
    }
    const paragraphs = quote
      ? quote.split(/\n{2,}/).map((part) => '<p>' + esc(part).replace(/\n/g, '<br>') + '</p>').join('')
      : '<p class="comment-quote-empty">（空引文）</p>';
    const jump = reachable
      ? '<button type="button" class="comment-quote-jump" data-comment-ref="' + esc(safeRef) + '">↩ 跳到该评论</button>'
      : '<span class="comment-quote-missing">原评论不可达</span>';
    return '<div class="comment-quote-block" data-comment-ref="' + esc(safeRef) + '" data-comment-author="' + esc(author || '') + '">'
      + '<blockquote class="comment-quote-text">' + paragraphs + '</blockquote>'
      + '<div class="comment-quote-meta"><span class="comment-quote-author">— ' + esc(author || '未知作者') + '</span>' + jump + '</div>'
      + '</div>';
  }

  function _prepareCommentQuoteTokens(markdown, options) {
    const lines = String(markdown || '').split('\n');
    const output = [];
    const commentQuotes = [];
    let inFence = false;
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const trimmed = line.trim();
      if (FENCED_CODE_RE.test(trimmed)) {
        inFence = !inFence;
        output.push(line);
        continue;
      }
      if (!inFence) {
        const open = line.match(COMMENT_QUOTE_OPEN_RE);
        if (open) {
          const quoteLines = [];
          let j = i + 1;
          let closed = false;
          while (j < lines.length) {
            if (lines[j].trim() === ':::') {
              closed = true;
              break;
            }
            quoteLines.push(lines[j]);
            j += 1;
          }
          if (closed) {
            const attrs = _parseCommentQuoteAttrs(open[1] || '');
            const quoteText = quoteLines.join('\n');
            const taskBodyMode = Boolean(options && options.mode === 'task-body');
            if (!taskBodyMode) {
              output.push(_renderCommentQuoteHtml(attrs, quoteText));
            } else {
              const context = _nearestCommentContext(lines, i, j);
              const signature = [attrs.source || 'comment', attrs.ref || '', attrs.author || '', attrs.section || '', quoteText].join('\0');
              const anchorKey = 'cq-' + _commentQuoteHash(signature);
              const ref = String(attrs.ref || '').trim();
              const refStatus = attrs.source === 'body'
                ? 'body-source'
                : (!ref ? 'missing-ref' : (_isValidCommentRef(ref) ? 'ready' : 'invalid-ref'));
              commentQuotes.push({
                anchorKey,
                author: attrs.source === 'body'
                  ? ('正文引用' + (attrs.section ? ' · ' + String(attrs.section).trim() : ''))
                  : String(attrs.author || '').trim(),
                quoteText: String(quoteText || '').trim(),
                ref,
                refStatus,
                source: attrs.source === 'body' ? 'body' : 'comment',
                heading: context.heading,
                paragraph: context.paragraph,
                order: commentQuotes.length,
              });
              output.push(_renderCommentQuoteHtml(attrs, quoteText, { anchorKey, asAnchor: true }));
            }
            i = j;
            continue;
          }
        }
      }
      output.push(line);
    }
    return { markdown: output.join('\n'), commentQuotes };
  }

  function _renderCommentQuoteTokens(markdown) {
    return _prepareCommentQuoteTokens(markdown).markdown;
  }

  function extractCommentQuotes(markdown) {
    return _prepareCommentQuoteTokens(preprocessMarkdown(markdown || ''), { mode: 'task-body' }).commentQuotes;
  }

  function _splitSrcSuffix(src) {
    const idx = src.search(/[?#]/);
    return idx === -1 ? { path: src, suffix: '' } : { path: src.slice(0, idx), suffix: src.slice(idx) };
  }

  function _isExternalImageSrc(src) {
    return /^(https?:|data:|blob:)/i.test(src || '');
  }

  function _decodeHrefPath(path) {
    try { return decodeURIComponent(path); } catch (e) { return path; }
  }

  function _localPathFromHref(href) {
    const raw = String(href || '').trim();
    if (!raw) return '';
    const lower = raw.toLowerCase();
    if (lower.startsWith('http://') || lower.startsWith('https://') ||
        lower.startsWith('mailto:') || raw.startsWith('#') ||
        raw.startsWith('//') || raw.startsWith('/api/') || raw.startsWith('/static/')) return '';
    if (lower.startsWith('file:///')) {
      try {
        const url = new URL(raw);
        if (url.protocol !== 'file:' || (url.host && url.host !== 'localhost')) return '';
        const decodedPath = _decodeHrefPath(url.pathname || '');
        return decodedPath.startsWith('/Users/') ? decodedPath : '';
      } catch (e) {
        return '';
      }
    }
    const decodedPath = _decodeHrefPath(_splitSrcSuffix(raw).path);
    if (decodedPath.startsWith('/Users/') || decodedPath.startsWith('~/')) return decodedPath;
    return '';
  }

  function _resolveTaskRelativePath(taskPath, relativePath) {
    if (!taskPath || !relativePath) return '';
    const clean = _splitSrcSuffix(relativePath);
    const baseParts = taskPath.split('/').filter(Boolean);
    baseParts.pop();
    const relParts = clean.path.split('/').filter((part) => part !== '');
    const finalParts = [...baseParts];
    relParts.forEach((part) => {
      if (part === '.') return;
      if (part === '..') {
        if (finalParts.length > 0) finalParts.pop();
        return;
      }
      finalParts.push(part);
    });
    return finalParts.join('/') + clean.suffix;
  }

  function _makeImageFallbackLink(label, href) {
    const link = document.createElement('a');
    link.className = 'image-fallback-link';
    link.href = href || 'javascript:void(0)';
    if (href) {
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
    link.textContent = label;
    return link;
  }

  function _replaceImageWithFallback(img, message) {
    const href = img.dataset.fallbackHref || img.dataset.originalHref || img.getAttribute('src') || '';
    const label = message || ('图片不可用: ' + (img.alt || href || '未命名图片'));
    const fallback = _makeImageFallbackLink(label, href);
    img.replaceWith(fallback);
  }

  function _convertUnicodeTableBlock(lines) {
    const trimmed = lines.map((line) => line.trim());
    const hasTop = trimmed.some((line) => line.startsWith('┌') && line.endsWith('┐'));
    const hasBottom = trimmed.some((line) => line.startsWith('└') && line.endsWith('┘'));
    const rowLines = trimmed.filter((line) => line.startsWith('│') && line.endsWith('│'));
    if (!hasTop || !hasBottom || rowLines.length < 1) return null;
    const rows = rowLines.map((line) => line.slice(1, -1).split('│').map((cell) => cell.trim()));
    const colCount = rows[0].length;
    if (colCount < 2 || rows.some((row) => row.length !== colCount)) return null;
    const header = '| ' + rows[0].join(' | ') + ' |';
    const separator = '| ' + rows[0].map(() => '---').join(' | ') + ' |';
    const body = rows.slice(1).map((row) => '| ' + row.join(' | ') + ' |');
    return [header, separator, ...body];
  }

  function _normalizePipeTableSpacing(markdown) {
    const lines = String(markdown || '').split('\n');
    const output = [];
    let inFence = false;
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      if (FENCED_CODE_RE.test(line.trim())) {
        inFence = !inFence;
        output.push(line);
        continue;
      }
      if (!inFence && line.trim().startsWith('|') && i + 1 < lines.length && lines[i + 1].trim().startsWith('|')) {
        if (output.length && output[output.length - 1] !== '') output.push('');
        while (i < lines.length && lines[i].trim().startsWith('|')) {
          output.push(lines[i]);
          i += 1;
        }
        if (output[output.length - 1] !== '') output.push('');
        i -= 1;
        continue;
      }
      output.push(line);
    }
    return output.join('\n');
  }

  function _neutralizeScriptTagsInMdLine(line) {
    return line
      .replace(/<\/script>/gi, '&lt;/script&gt;')
      .replace(/<script\b/gi, '&lt;script');
  }

  function preprocessMarkdown(markdown) {
    const lines = String(markdown || '').split('\n');
    const output = [];
    let inFence = false;
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const trimmed = line.trim();
      if (FENCED_CODE_RE.test(trimmed)) {
        inFence = !inFence;
        output.push(line);
        continue;
      }
      if (!inFence && BOX_DRAW_RE.test(line)) {
        const block = [];
        let j = i;
        while (j < lines.length && BOX_DRAW_RE.test(lines[j]) && !FENCED_CODE_RE.test(lines[j].trim())) {
          block.push(lines[j]);
          j += 1;
        }
        const converted = _convertUnicodeTableBlock(block);
        if (converted) {
          if (output.length && output[output.length - 1] !== '') output.push('');
          output.push(...converted);
          if (j < lines.length && lines[j].trim() !== '') output.push('');
          i = j - 1;
          continue;
        }
      }
      output.push(inFence ? line : _neutralizeScriptTagsInMdLine(line));
    }
    return _normalizePipeTableSpacing(output.join('\n'));
  }

  function addCopyButtons(container) {
    container.querySelectorAll('pre').forEach((pre) => {
      if (pre.querySelector('.code-copy-btn')) return;
      const button = document.createElement('button');
      button.className = 'code-copy-btn';
      button.type = 'button';
      button.textContent = 'Copy';
      button.onclick = () => {
        const code = pre.querySelector('code');
        const text = code ? code.textContent : pre.textContent;
        navigator.clipboard.writeText(text || '').then(() => {
          toast('代码已复制');
        }).catch(() => {
          toast('复制失败', true);
        });
      };
      pre.appendChild(button);
    });
  }

  function rewriteImageSrcs(container, taskPath) {
    container.querySelectorAll('img').forEach((img) => {
      const original = img.getAttribute('src') || '';
      if (!original) return;
      img.dataset.originalHref = original;
      img.dataset.fallbackHref = original;
      if (_isExternalImageSrc(original) || original.startsWith('/api/file?') || original.startsWith('/')) return;
      if (!ctx.hasApi) {
        _replaceImageWithFallback(img, '本地图片仅在服务模式可预览: ' + original);
        return;
      }
      const resolved = _resolveTaskRelativePath(taskPath, original);
      if (!resolved) return;
      const proxiedSrc = '/api/file?path=' + encodeURIComponent(_splitSrcSuffix(resolved).path);
      img.src = proxiedSrc;
      img.dataset.fallbackHref = proxiedSrc;
      img.dataset.originalHref = original;
    });
  }

  function bindLocalPathLinks(container) {
    container.querySelectorAll('a[href]').forEach((link) => {
      if (link.dataset.localPathBound === 'true') return;
      const openPath = _localPathFromHref(link.getAttribute('href'));
      if (!openPath) return;
      link.dataset.localPathBound = 'true';
      link.dataset.openPath = openPath;
      link.addEventListener('click', (e) => {
        e.preventDefault();
        if (ctx.api && typeof ctx.api.openInEditor === 'function') ctx.api.openInEditor(link.dataset.openPath || openPath);
        else toast('打开本地文件仅在服务模式可用', true);
      });
    });
  }

  function openLightbox(src, alt) {
    lightboxImage.src = src;
    lightboxImage.alt = alt || '';
    lightboxCaption.textContent = alt || src || '';
    lightboxOverlay.classList.add('on');
    lightboxOverlay.setAttribute('aria-hidden', 'false');
  }

  function closeLightbox() {
    lightboxOverlay.classList.remove('on');
    lightboxOverlay.setAttribute('aria-hidden', 'true');
    lightboxImage.removeAttribute('src');
    lightboxCaption.textContent = '';
  }

  function setupImageLightbox(container) {
    container.querySelectorAll('img').forEach((img) => {
      if (img.dataset.lightboxBound === 'true') return;
      img.dataset.lightboxBound = 'true';
      img.addEventListener('click', () => {
        if (img.src) openLightbox(img.src, img.alt || img.dataset.originalHref || '');
      });
      img.addEventListener('error', () => {
        _replaceImageWithFallback(img, '图片加载失败: ' + (img.alt || img.dataset.originalHref || img.src || '未命名图片'));
      }, { once: true });
    });
  }

  async function renderMermaidDiagrams(container) {
    const nodes = Array.from(container.querySelectorAll('.mermaid'));
    if (!nodes.length) return;
    if (!window.mermaid || typeof mermaid.render !== 'function') {
      nodes.forEach((node) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'mermaid-wrapper';
        wrapper.innerHTML = '<pre><code class="language-mermaid">' + esc(node.textContent || '') + '</code></pre><div class="mermaid-error">Mermaid CDN 未加载，已回退为源码显示。</div>';
        node.parentNode.replaceChild(wrapper, node);
        addCopyButtons(wrapper);
      });
      return;
    }
    for (const node of nodes) {
      const source = node.textContent || '';
      const renderId = 'mermaid-' + Date.now() + '-' + Math.random().toString(16).slice(2);
      try {
        const result = await mermaid.render(renderId, source);
        const wrapper = document.createElement('div');
        wrapper.className = 'mermaid-wrapper';
        wrapper.innerHTML = result.svg;
        node.parentNode.replaceChild(wrapper, node);
        if (typeof result.bindFunctions === 'function') result.bindFunctions(wrapper);
      } catch (error) {
        const wrapper = document.createElement('div');
        wrapper.className = 'mermaid-wrapper';
        wrapper.innerHTML = '<pre><code class="language-mermaid">' + esc(source) + '</code></pre><div class="mermaid-error">' + MERMAID_FALLBACK_MESSAGE + ': ' + esc(String(error && error.message ? error.message : error)) + '</div>';
        node.parentNode.replaceChild(wrapper, node);
        addCopyButtons(wrapper);
      }
    }
  }

  function renderMarkdownEnhanced(container, markdown, taskPath, options) {
    container.innerHTML = parseMarkdown(markdown, options);
    bindCommentQuoteBlocks(container);
    renderFileMentionLinks(container);
    bindLocalPathLinks(container);
    addCopyButtons(container);
    rewriteImageSrcs(container, taskPath);
    setupImageLightbox(container);
    void renderMermaidDiagrams(container);
  }

  function _fmClassifyFile(name, isDir) {
    if (isDir) return 'folder';
    const dot = name.lastIndexOf('.');
    const ext = dot >= 0 ? name.slice(dot).toLowerCase() : '';
    if (uiState.fileMention.extCode[ext]) return 'code';
    if (uiState.fileMention.extImage[ext]) return 'image';
    if (uiState.fileMention.extDocument[ext]) return 'document';
    return 'other';
  }

  function _fmFindTaskByPath(path) {
    return (dataState.tasks || []).find((task) => task.path === path);
  }

  function _fmOpenFileLink(path) {
    if (_fmFindTaskByPath(path)) {
      ctx.renderDetail.openTaskDetail(path);
    } else {
      ctx.api.openInEditor(path);
    }
  }

  async function _fmCheckBrokenLinks(container) {
    const links = Array.from(container.querySelectorAll('.file-mention-link'));
    const paths = Array.from(new Set(links.map((el) => el.dataset.fmPath).filter(Boolean)));
    const existence = new Map();
    await Promise.all(paths.map(async (path) => {
      try {
        const r = await fetch('/api/file-exists?path=' + encodeURIComponent(path));
        const j = await r.json();
        existence.set(path, Boolean(j.ok && j.exists));
      } catch (e) {
        return null;
      }
      return null;
    }));
    links.forEach((el) => {
      if (existence.get(el.dataset.fmPath) === false) el.classList.add('broken');
    });
  }

  function renderFileMentionLinks(container) {
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        let p = node.parentElement;
        while (p && p !== container) {
          if (['CODE', 'PRE', 'SCRIPT', 'STYLE'].includes(p.tagName)) return NodeFilter.FILTER_REJECT;
          p = p.parentElement;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const textNodes = [];
    let node;
    while ((node = walker.nextNode())) {
      if (/\[\[[^\]]+\]\]/.test(node.textContent)) textNodes.push(node);
    }
    textNodes.forEach((textNode) => {
      const frag = document.createDocumentFragment();
      const parts = textNode.textContent.split(/(\[\[[^\]]+\]\])/);
      parts.forEach((part) => {
        const match = part.match(/^\[\[([^\]]+)\]\]$/);
        if (match) {
          const filePath = match[1];
          const fileName = filePath.split('/').pop();
          const task = _fmFindTaskByPath(filePath);
          const cat = task ? 'task' : _fmClassifyFile(fileName, false);
          const span = document.createElement('span');
          span.className = 'file-mention-link';
          span.dataset.fmPath = filePath;
          span.dataset.fmType = cat;
          span.title = filePath;
          span.innerHTML = '<span class="file-mention-icon">@</span>' + esc(fileName);
          span.onclick = () => _fmOpenFileLink(filePath);
          frag.appendChild(span);
        } else if (part) {
          frag.appendChild(document.createTextNode(part));
        }
      });
      textNode.replaceWith(frag);
    });
    if (textNodes.length) _fmCheckBrokenLinks(container);
  }

  function _insertTextAtCursor(textarea, text) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    textarea.setRangeText(text, start, end, 'end');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function _findCommentQuoteTarget(ref) {
    return Array.from(document.querySelectorAll('[data-entry-id]')).find((el) => el.dataset.entryId === ref) || null;
  }

  function _expandCollapsedBranchForTarget(target) {
    let branch = target.closest('.thread-branch.is-collapsed');
    while (branch) {
      const toggle = branch.querySelector(':scope > .thread-branch-head .thread-branch-toggle');
      if (toggle) toggle.click();
      else {
        branch.classList.remove('is-collapsed');
        branch.classList.add('is-expanded');
        const body = branch.querySelector(':scope > .thread-branch-body');
        if (body) body.style.display = '';
      }
      branch = target.closest('.thread-branch.is-collapsed');
    }
  }

  function jumpToCommentQuote(ref) {
    const target = _findCommentQuoteTarget(ref);
    if (!target) {
      toast('原评论不可达', true);
      return false;
    }
    _expandCollapsedBranchForTarget(target);
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('msg-bubble-quoted');
    setTimeout(() => target.classList.remove('msg-bubble-quoted'), 1600);
    return true;
  }

  function refreshCommentQuoteAvailability(root) {
    const scope = root || document;
    const loaded = Boolean(uiState.ai && uiState.ai.quoteHistoryLoaded);
    scope.querySelectorAll('.comment-quote-block[data-comment-ref]').forEach((block) => {
      if (block.dataset.source === 'body') return;
      const ref = block.dataset.commentRef || '';
      const target = ref ? _findCommentQuoteTarget(ref) : null;
      const missing = loaded && !target;
      block.classList.toggle('is-missing', missing);
      const btn = block.querySelector('.comment-quote-jump');
      if (btn) {
        btn.disabled = missing;
        btn.textContent = missing ? '原评论不可达' : '↩ 跳到该评论';
      }
    });
    scope.querySelectorAll('.comment-quote-anchor[data-comment-anchor]').forEach((anchor) => {
      const ref = anchor.dataset.commentRef || '';
      const status = anchor.dataset.commentRefStatus || '';
      const invalid = status !== 'ready' && status !== 'body-source';
      const missing = invalid || (status === 'ready' && loaded && (!ref || !_findCommentQuoteTarget(ref)));
      anchor.classList.toggle('is-missing', missing);
      anchor.title = missing ? '批注快照可读，原评论不可达' : '查看批注';
    });
    refreshBodyQuoteAvailability(scope);
    if (ctx.renderDetail && typeof ctx.renderDetail.refreshCommentSidebarAvailability === 'function') {
      ctx.renderDetail.refreshCommentSidebarAvailability();
    }
  }

  function refreshBodyQuoteAvailability(root) {
    const scope = root || document;
    const canResolve = Boolean(ctx.ai && typeof ctx.ai.resolveBodyQuoteTarget === 'function');
    scope.querySelectorAll('.body-quote-block[data-source="body"]').forEach((block) => {
      const btn = block.querySelector('.body-quote-jump');
      if (!btn || !canResolve) return;
      const sourceQuote = _bodyQuoteFromButton(btn);
      const missing = !ctx.ai.resolveBodyQuoteTarget(sourceQuote);
      block.classList.toggle('is-missing', missing);
      btn.disabled = missing;
      btn.textContent = missing ? '原位置已变化' : '↩ 跳到正文原位';
    });
  }

  function bindCommentQuoteBlocks(container) {
    container.querySelectorAll('.comment-quote-anchor[data-comment-anchor]').forEach((button) => {
      if (button.dataset.commentAnchorBound === 'true') return;
      button.dataset.commentAnchorBound = 'true';
      button.addEventListener('click', (e) => {
        e.preventDefault();
        if (ctx.renderDetail && typeof ctx.renderDetail.openCommentSidebar === 'function') {
          ctx.renderDetail.openCommentSidebar(button.dataset.commentAnchor || '');
        }
      });
    });
    container.querySelectorAll('.comment-quote-jump[data-comment-ref]').forEach((button) => {
      if (button.dataset.commentQuoteBound === 'true') return;
      button.dataset.commentQuoteBound = 'true';
      button.addEventListener('click', (e) => {
        e.preventDefault();
        jumpToCommentQuote(button.dataset.commentRef || '');
        refreshCommentQuoteAvailability(container);
      });
    });
    container.querySelectorAll('.body-quote-jump[data-body-quote]').forEach((button) => {
      if (button.dataset.bodyQuoteBound === 'true') return;
      button.dataset.bodyQuoteBound = 'true';
      button.addEventListener('click', (e) => {
        e.preventDefault();
        const sourceQuote = _bodyQuoteFromButton(button);
        if (ctx.ai && typeof ctx.ai.jumpToBodyQuote === 'function') {
          ctx.ai.jumpToBodyQuote(sourceQuote);
        } else {
          toast('正文原位置已变化，保留引用快照', true);
        }
        refreshBodyQuoteAvailability(container);
      });
    });
    refreshCommentQuoteAvailability(container);
  }

  function _replaceTextOnce(textarea, needle, replacement) {
    const index = textarea.value.indexOf(needle);
    if (index === -1) return false;
    textarea.value = textarea.value.slice(0, index) + replacement + textarea.value.slice(index + needle.length);
    const pos = index + replacement.length;
    textarea.selectionStart = pos;
    textarea.selectionEnd = pos;
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  }

  async function _requestUploadContract(file) {
    const response = await fetch('/api/prepare-upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: uiState.detail.currentTaskPath,
        filename: file.name,
        content_type: file.type || 'application/octet-stream'
      })
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || '准备上传失败');
    return payload;
  }

  async function _postFileToStorage(contract, file) {
    const form = new FormData();
    Object.entries(contract.fields || {}).forEach(([key, value]) => form.append(key, value));
    form.append('file', file);
    const response = await fetch(contract.upload_url, { method: contract.method || 'POST', body: form });
    if (!response.ok) throw new Error('上传失败: ' + response.status);
  }

  function _trackPendingUploadTask(task) {
    uiState.pendingUploadTasks.add(task);
    task.finally(() => {
      uiState.pendingUploadTasks.delete(task);
    });
    return task;
  }

  async function _waitForPendingUploads() {
    while (uiState.pendingUploadTasks.size) {
      await Promise.allSettled(Array.from(uiState.pendingUploadTasks));
    }
  }

  function _hasPendingUploads() {
    return uiState.pendingUploadTasks.size > 0;
  }

  function _guardPendingUploads(actionLabel) {
    if (!_hasPendingUploads()) return false;
    toast((actionLabel || '当前操作') + '前请等待图片上传完成', true);
    return true;
  }

  async function uploadImageAndInsert(file, textarea) {
    return _trackPendingUploadTask((async () => {
      if (!file || !file.type.startsWith('image/')) return;
      if (!ctx.hasApi) {
        toast('图片上传仅在服务模式可用', true);
        return;
      }
      const token = 'uploading-' + Date.now() + '-' + Math.random().toString(16).slice(2);
      const placeholder = '![上传中...](uploading://' + token + ')';
      _insertTextAtCursor(textarea, placeholder);
      let lastError = null;
      try {
        const contract = await _requestUploadContract(file);
        for (let attempt = 0; attempt < 3; attempt += 1) {
          try {
            await _postFileToStorage(contract, file);
            _replaceTextOnce(textarea, placeholder, '![](' + contract.final_url + ')');
            toast('图片已上传');
            return;
          } catch (error) {
            lastError = error;
          }
        }
        throw lastError || new Error('上传失败');
      } catch (error) {
        _replaceTextOnce(textarea, placeholder, '');
        toast((error && error.message) || '图片上传失败', true);
      }
    })());
  }

  async function uploadImagesAndInsert(files, textarea) {
    return _trackPendingUploadTask((async () => {
      for (const file of files) {
        if (file && file.type && file.type.startsWith('image/')) {
          await uploadImageAndInsert(file, textarea);
        }
      }
    })());
  }

  lightboxOverlay.addEventListener('click', (e) => {
    if (e.target === lightboxOverlay || e.target === lightboxImage) closeLightbox();
  });

  fmResults.addEventListener('scroll', function() {
    if (!uiState.fileMention.visible || !uiState.fileMention.hasMore || uiState.fileMention.loading) return;
    if (this.scrollTop + this.clientHeight >= this.scrollHeight - 48) {
      _fmFetchResults(uiState.fileMention.query, true);
    }
  });

  fmTabs.addEventListener('mousedown', (e) => {
    e.preventDefault();
  });
  fileMentionDd.addEventListener('click', (e) => {
    e.stopPropagation();
  });

  document.addEventListener('click', (e) => {
    if (uiState.fileMention.visible) {
      if (!fileMentionDd.contains(e.target) && e.target !== uiState.fileMention.textarea) _fmHide();
    }
  });

  const FM_CATEGORIES = [
    { key: 'all', label: '全部' },
    { key: 'folder', label: '文件夹' },
    { key: 'task', label: '任务' },
    { key: 'code', label: '代码' },
    { key: 'image', label: '图片' },
    { key: 'document', label: '文档' },
    { key: 'other', label: '其他' },
  ];

  uiState.fileMention.extCode = {'.py':1,'.js':1,'.ts':1,'.jsx':1,'.tsx':1,'.vue':1,'.go':1,'.rs':1,'.java':1,'.c':1,'.cpp':1,'.h':1,'.rb':1,'.php':1,'.swift':1,'.kt':1,'.sh':1,'.bash':1,'.sql':1,'.yaml':1,'.yml':1,'.toml':1,'.json':1,'.xml':1,'.html':1,'.css':1,'.scss':1,'.less':1};
  uiState.fileMention.extImage = {'.png':1,'.jpg':1,'.jpeg':1,'.gif':1,'.webp':1,'.svg':1,'.bmp':1,'.ico':1};
  uiState.fileMention.extDocument = {'.md':1,'.pdf':1,'.ppt':1,'.pptx':1,'.doc':1,'.docx':1,'.xls':1,'.xlsx':1,'.key':1,'.numbers':1};
  uiState.fileMention.icons = { folder:'📁', task:'📄', code:'💻', image:'🖼️', document:'📊', other:'📎' };

  function _fmIcon(cat) {
    return uiState.fileMention.icons[cat] || '📎';
  }

  function _fmGetContextProject(textarea) {
    if (textarea && textarea.id === 'new-body') {
      return (ctx.el.newProject && ctx.el.newProject.value.trim()) || '';
    }
    if (uiState.detail.currentTaskPath) {
      const parts = uiState.detail.currentTaskPath.split('/');
      if (parts[0] === 'project' && parts.length > 1) return parts[1];
    }
    return '';
  }

  function _fmPositionDropdown(textarea, dd) {
    const rect = textarea.getBoundingClientRect();
    const anchor = _fmGetCaretAnchor(textarea, rect, uiState.fileMention.triggerStart);
    const ddWidth = Math.min(window.innerWidth - 24, 560);
    const margin = 12;
    const left = Math.max(margin, Math.min(anchor.left - 12, window.innerWidth - ddWidth - margin));
    dd.style.width = ddWidth + 'px';
    dd.style.left = left + 'px';
    dd.style.top = (anchor.bottom + 4) + 'px';
    requestAnimationFrame(() => {
      const ddRect = dd.getBoundingClientRect();
      const left2 = Math.max(margin, Math.min(anchor.left - 12, window.innerWidth - ddRect.width - margin));
      dd.style.left = left2 + 'px';
      if (ddRect.bottom > window.innerHeight - 8) dd.style.top = Math.max(8, anchor.top - ddRect.height - 4) + 'px';
    });
  }

  function _fmGetCaretAnchor(textarea, rect, index) {
    const start = Math.max(0, index || 0);
    const mirror = document.createElement('div');
    const style = window.getComputedStyle(textarea);
    const props = [
      'boxSizing','width','height','overflowX','overflowY','borderTopWidth','borderRightWidth',
      'borderBottomWidth','borderLeftWidth','paddingTop','paddingRight','paddingBottom','paddingLeft',
      'fontFamily','fontSize','fontWeight','fontStyle','lineHeight','letterSpacing','textTransform',
      'textAlign','textIndent','whiteSpace','wordWrap','wordBreak','tabSize'
    ];
    mirror.style.position = 'absolute';
    mirror.style.visibility = 'hidden';
    mirror.style.whiteSpace = 'pre-wrap';
    mirror.style.wordWrap = 'break-word';
    props.forEach((prop) => { mirror.style[prop] = style[prop]; });
    mirror.style.left = '-9999px';
    mirror.style.top = '0';
    const text = textarea.value.slice(0, start).replace(/\n$/, '\n\u200b').replace(/ /g, '\u00a0');
    mirror.textContent = text;
    const span = document.createElement('span');
    span.textContent = textarea.value.slice(start, start + 1) || '\u200b';
    mirror.appendChild(span);
    document.body.appendChild(mirror);
    const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4 || 20;
    const anchor = {
      left: rect.left + span.offsetLeft - textarea.scrollLeft + 2,
      top: rect.top + span.offsetTop - textarea.scrollTop,
      bottom: rect.top + span.offsetTop - textarea.scrollTop + lineHeight,
    };
    document.body.removeChild(mirror);
    return anchor;
  }

  function _fmRenderActiveItem() {
    const items = document.querySelectorAll('#fm-results .fm-item');
    items.forEach((el, idx) => el.classList.toggle('active', idx === uiState.fileMention.activeIndex));
    const active = items[uiState.fileMention.activeIndex];
    if (active) active.scrollIntoView({ block: 'nearest' });
  }

  function _fmAvailableTabKeys() {
    return FM_CATEGORIES.map((c) => c.key).filter((key) => key === 'all' || (uiState.fileMention.categoryCounts[key] || 0) > 0);
  }

  function _fmMoveTab(step) {
    const catKeys = _fmAvailableTabKeys();
    if (catKeys.length < 2) return;
    const ci = Math.max(0, catKeys.indexOf(uiState.fileMention.activeTab));
    const ni = (ci + step + catKeys.length) % catKeys.length;
    _fmSwitchTab(catKeys[ni]);
  }

  function _fmSelect(item) {
    if (item && (item.is_dir || item.type === 'folder')) return;
    const ta = uiState.fileMention.textarea;
    if (!ta) return;
    const insertText = '[[' + item.path + ']]';
    const before = ta.value.slice(0, uiState.fileMention.triggerStart);
    const after = ta.value.slice(ta.selectionStart);
    ta.value = before + insertText + ' ' + after;
    const newPos = uiState.fileMention.triggerStart + insertText.length + 1;
    ta.selectionStart = newPos;
    ta.selectionEnd = newPos;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    _fmHide();
    ta.focus();
  }

  function _fmRenderTab() {
    uiState.fileMention.results = uiState.fileMention.allResults;
    fmTabs.innerHTML = '';
    FM_CATEGORIES.forEach((cat) => {
      const count = cat.key === 'all' ? uiState.fileMention.allTotal : (uiState.fileMention.categoryCounts[cat.key] || 0);
      if (cat.key !== 'all' && count === 0) return;
      const div = document.createElement('div');
      div.className = 'fm-tab' + (cat.key === uiState.fileMention.activeTab ? ' on' : '');
      div.textContent = cat.label + (count ? ' (' + count + ')' : '');
      div.onclick = (e) => { e.stopPropagation(); _fmSwitchTab(cat.key); };
      fmTabs.appendChild(div);
    });

    fmResults.innerHTML = '';
    if (uiState.fileMention.error) {
      fmResults.innerHTML = '<div class="fm-empty">' + esc(uiState.fileMention.error) + '</div>';
      return;
    }
    if (!uiState.fileMention.results.length) {
      fmResults.innerHTML = '<div class="fm-empty">' + (uiState.fileMention.loading ? '搜索中...' : '无匹配文件') + '</div>';
      return;
    }
    uiState.fileMention.results.forEach((item, idx) => {
      const div = document.createElement('div');
      const isDir = Boolean(item.is_dir || item.type === 'folder');
      div.className = 'fm-item' + (idx === uiState.fileMention.activeIndex ? ' active' : '') + (isDir ? ' disabled' : '');
      div.setAttribute('role', 'option');
      if (isDir) div.setAttribute('aria-disabled', 'true');
      const fileName = item.name;
      const authorTag = item.author ? '<span class="fm-author">' + esc(item.author) + '</span>' : '';
      const mtimeTag = item.mtime ? '<span class="fm-mtime">' + esc(item.mtime) + '</span>' : '';
      div.innerHTML =
        '<span class="fm-icon">' + _fmIcon(item.type) + '</span>' +
        '<span class="fm-meta">' +
          '<span class="fm-name" title="' + esc(fileName) + '">' + esc(fileName) + '</span>' +
          '<span class="fm-path" title="' + esc(item.path) + '">' + esc(item.path) + '</span>' +
        '</span>' +
        mtimeTag + authorTag;
      div.onclick = (e) => { e.stopPropagation(); if (!isDir) _fmSelect(item); };
      fmResults.appendChild(div);
    });
  }

  async function _fmFetchResults(query, append = false) {
    if (!uiState.fileMention.visible || (append && uiState.fileMention.loading)) return;
    const seq = ++uiState.fileMention.requestSeq;
    const offset = append ? uiState.fileMention.offset : 0;
    uiState.fileMention.loading = true;
    uiState.fileMention.error = '';
    if (!append) {
      uiState.fileMention.offset = 0;
      uiState.fileMention.allResults = [];
      uiState.fileMention.activeIndex = 0;
      _fmRenderTab();
    }
    try {
      const params = new URLSearchParams({
        q: query,
        project: uiState.fileMention.project,
        offset: String(offset),
        limit: String(uiState.fileMention.limit),
        type: uiState.fileMention.activeTab,
      });
      const r = await fetch('/api/search-files?' + params.toString());
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      if (seq !== uiState.fileMention.requestSeq || !uiState.fileMention.visible) return;
      if (j.ok) {
        const nextResults = j.results || [];
        uiState.fileMention.allResults = append ? uiState.fileMention.allResults.concat(nextResults) : nextResults;
        uiState.fileMention.offset = offset + nextResults.length;
        uiState.fileMention.total = j.total || uiState.fileMention.allResults.length;
        uiState.fileMention.allTotal = j.all_total || uiState.fileMention.total;
        uiState.fileMention.categoryCounts = j.category_counts || {};
        uiState.fileMention.hasMore = Boolean(j.has_more);
        if (!append) uiState.fileMention.activeIndex = 0;
        uiState.fileMention.loading = false;
        _fmRenderTab();
      } else {
        throw new Error(j.error || 'search failed');
      }
    } catch (e) {
      if (seq === uiState.fileMention.requestSeq && uiState.fileMention.visible) {
        uiState.fileMention.error = '搜索失败，稍后重试';
        uiState.fileMention.hasMore = false;
        uiState.fileMention.loading = false;
        _fmRenderTab();
      }
    } finally {
      if (seq === uiState.fileMention.requestSeq) uiState.fileMention.loading = false;
    }
  }

  function _fmSwitchTab(tabKey) {
    if (uiState.fileMention.activeTab === tabKey) return;
    uiState.fileMention.activeTab = tabKey;
    uiState.fileMention.activeIndex = 0;
    uiState.fileMention.offset = 0;
    uiState.fileMention.allResults = [];
    uiState.fileMention.hasMore = false;
    uiState.fileMention.error = '';
    _fmFetchResults(uiState.fileMention.query, false);
  }

  function _fmSearch(query) {
    clearTimeout(uiState.fileMention.debounceTimer);
    uiState.fileMention.debounceTimer = setTimeout(() => _fmFetchResults(query, false), 150);
  }

  function _fmShow(textarea, triggerStart, query) {
    const isNewQuery = !uiState.fileMention.visible || uiState.fileMention.query !== query || uiState.fileMention.textarea !== textarea;
    uiState.fileMention.visible = true;
    uiState.fileMention.textarea = textarea;
    uiState.fileMention.triggerStart = triggerStart;
    uiState.fileMention.query = query;
    if (isNewQuery) {
      uiState.fileMention.activeTab = 'all';
      uiState.fileMention.activeIndex = 0;
      uiState.fileMention.results = [];
      uiState.fileMention.allResults = [];
      uiState.fileMention.offset = 0;
      uiState.fileMention.total = 0;
      uiState.fileMention.allTotal = 0;
      uiState.fileMention.categoryCounts = {};
      uiState.fileMention.hasMore = false;
      uiState.fileMention.error = '';
      uiState.fileMention.project = _fmGetContextProject(textarea);
    }
    _fmPositionDropdown(textarea, fileMentionDd);
    fileMentionDd.classList.add('on');
    _fmSearch(query);
  }

  function _fmHide() {
    uiState.fileMention.visible = false;
    uiState.fileMention.textarea = null;
    uiState.fileMention.triggerStart = -1;
    clearTimeout(uiState.fileMention.debounceTimer);
    uiState.fileMention.requestSeq += 1;
    fileMentionDd.classList.remove('on');
  }

  function _fmHandleInput(e) {
    const ta = e.target;
    const pos = ta.selectionStart;
    const val = ta.value;
    let atPos = -1;
    for (let i = pos - 1; i >= 0; i -= 1) {
      const ch = val[i];
      if (ch === '@') {
        if (i === 0 || /[\s\n]/.test(val[i - 1])) atPos = i;
        break;
      }
      if (/[\s\n]/.test(ch)) break;
    }
    if (atPos >= 0 && atPos <= pos) {
      const query = val.slice(atPos + 1, pos);
      if (!query.includes('\n')) {
        _fmShow(ta, atPos, query);
        return;
      }
    }
    _fmHide();
  }

  function _fmHandleKeydown(e) {
    if (!uiState.fileMention.visible) return;
    const results = uiState.fileMention.results;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      _fmHide();
      return;
    }
    if (e.key === 'Tab') {
      e.preventDefault();
      e.stopPropagation();
      _fmMoveTab(e.shiftKey ? -1 : 1);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      e.stopPropagation();
      _fmMoveTab(1);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      e.stopPropagation();
      _fmMoveTab(-1);
    } else if (e.key === 'ArrowDown') {
      if (!results.length) return;
      e.preventDefault();
      uiState.fileMention.activeIndex = Math.min(uiState.fileMention.activeIndex + 1, results.length - 1);
      _fmRenderActiveItem();
    } else if (e.key === 'ArrowUp') {
      if (!results.length) return;
      e.preventDefault();
      uiState.fileMention.activeIndex = Math.max(uiState.fileMention.activeIndex - 1, 0);
      _fmRenderActiveItem();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      const item = results[uiState.fileMention.activeIndex];
      if (item && !(item.is_dir || item.type === 'folder')) _fmSelect(item);
    }
  }

  function looksLikeMarkdown(txt) {
    return !!txt && (
      txt.includes('```') ||
      txt.includes(':::comment-quote') ||
      txt.includes('## ') ||
      txt.includes('**') ||
      txt.includes('|') ||
      txt.includes('![') ||
      txt.includes('```mermaid') ||
      BOX_DRAW_RE.test(txt)
    );
  }

  ctx.markdown = {
    BOX_DRAW_RE,
    preprocessMarkdown,
    addCopyButtons,
    rewriteImageSrcs,
    bindLocalPathLinks,
    openLightbox,
    closeLightbox,
    renderMermaidDiagrams,
    renderMarkdownEnhanced,
    extractCommentQuotes,
    renderFileMentionLinks,
    bindCommentQuoteBlocks,
    refreshCommentQuoteAvailability,
    jumpToCommentQuote,
    looksLikeMarkdown,
    _insertTextAtCursor,
    _replaceTextOnce,
    _requestUploadContract,
    _postFileToStorage,
    _trackPendingUploadTask,
    _waitForPendingUploads,
    _hasPendingUploads,
    _guardPendingUploads,
    uploadImageAndInsert,
    uploadImagesAndInsert,
    _fmFindTaskByPath,
    _fmOpenFileLink,
    _fmCheckBrokenLinks,
    _fmHandleInput,
    _fmHandleKeydown,
    _fmHide,
    _test: {
      _renderCommentQuoteTokens,
      _prepareCommentQuoteTokens,
      _parseCommentQuoteAttrs,
      _bodyQuoteFromButton,
    },
  };

  return ctx.markdown;
}
