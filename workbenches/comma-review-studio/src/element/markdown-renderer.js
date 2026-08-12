import DOMPurify from 'dompurify';
import hljs from 'highlight.js/lib/common';
import katex from 'katex';
import { Marked } from 'marked';

let mermaidReady = false;
let mermaidCounter = 0;
let mermaidPromise = null;

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function mathExtensions() {
  const render = (tex, displayMode) => {
    try {
      return katex.renderToString(tex, { displayMode, throwOnError: false, strict: 'warn' });
    } catch {
      return `<code class="ce-math-error">${escapeHtml(tex)}</code>`;
    }
  };
  return [
    {
      name: 'blockMath',
      level: 'block',
      start(source) {
        const index = source.indexOf('$$');
        return index < 0 ? undefined : index;
      },
      tokenizer(source) {
        const match = /^\$\$\n?([\s\S]+?)\n?\$\$(?:\n|$)/.exec(source);
        if (!match) return undefined;
        return { type: 'blockMath', raw: match[0], text: match[1].trim() };
      },
      renderer(token) {
        return `<div class="ce-math-block">${render(token.text, true)}</div>`;
      },
    },
    {
      name: 'inlineMath',
      level: 'inline',
      start(source) {
        const index = source.indexOf('$');
        return index < 0 ? undefined : index;
      },
      tokenizer(source) {
        const match = /^\$(?!\$)((?:\\.|[^$\\])+?)\$/.exec(source);
        if (!match) return undefined;
        return { type: 'inlineMath', raw: match[0], text: match[1] };
      },
      renderer(token) {
        return render(token.text, false);
      },
    },
  ];
}

export function stabilizeImageLabelBackticks(source) {
  let fenced = false;
  return String(source ?? '').split(/(\r?\n)/).map((part) => {
    if (/^\r?\n$/.test(part)) return part;
    const fence = /^\s*(```|~~~)/.test(part);
    if (fence) {
      fenced = !fenced;
      return part;
    }
    if (fenced || /^(?: {4}|\t)/.test(part)) return part;
    return part.replace(/!\[((?:\\.|[^\]\\])*)\]\(([^)\n]+)\)/g, (match, label, href) => {
      if (!label.includes('`')) return match;
      return `![${label.replace(/(^|[^\\])`/g, '$1\\`')}](${href})`;
    });
  }).join('');
}

export class MarkdownRenderer {
  constructor() {
    this.assetResolver = null;
    this.marked = new Marked({ gfm: true, breaks: false });
    this.marked.use({
      extensions: mathExtensions(),
      renderer: {
        code({ text, lang }) {
          const language = String(lang || '').trim().toLowerCase();
          if (language === 'mermaid') {
            return `<pre class="ce-mermaid-source" data-language="mermaid">${escapeHtml(text || '')}</pre>`;
          }
          const source = String(text || '');
          let highlighted = escapeHtml(source);
          if (language && hljs.getLanguage(language)) {
            highlighted = hljs.highlight(source, { language, ignoreIllegals: true }).value;
          } else if (source) {
            highlighted = hljs.highlightAuto(source).value;
          }
          const className = language ? ` class="hljs language-${escapeHtml(language)}"` : ' class="hljs"';
          return `<pre><code${className}>${highlighted}</code></pre>`;
        },
        image: ({ href, title, text }) => {
          const original = String(href || '');
          let resolved = original;
          try {
            const candidate = this.assetResolver?.(original);
            if (typeof candidate === 'string' && candidate) resolved = candidate;
          } catch { /* the rendered fallback will explain a failed URL */ }
          const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
          return `<img src="${escapeHtml(resolved)}" data-original-src="${escapeHtml(original)}" alt="${escapeHtml(text || '')}"${titleAttr}>`;
        },
      },
    });
  }

  lexer(source) {
    return this.marked.lexer(String(source ?? ''));
  }

  render(source, { resolveAsset = null } = {}) {
    this.assetResolver = typeof resolveAsset === 'function' ? resolveAsset : null;
    try {
      const unsafe = this.marked.parse(stabilizeImageLabelBackticks(source));
      return DOMPurify.sanitize(unsafe, {
        USE_PROFILES: { html: true },
        ADD_ATTR: ['target', 'rel', 'data-language', 'data-original-src'],
      });
    } finally {
      this.assetResolver = null;
    }
  }

  async hydrate(root) {
    const diagrams = Array.from(root.querySelectorAll('.ce-mermaid-source'));
    if (!diagrams.length) return;
    if (!mermaidPromise) mermaidPromise = import('mermaid').then((module) => module.default);
    const mermaid = await mermaidPromise;
    if (!mermaidReady) {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'neutral',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      });
      mermaidReady = true;
    }
    await Promise.all(diagrams.map(async (node) => {
      const source = node.textContent || '';
      const host = document.createElement('div');
      host.className = 'ce-mermaid';
      try {
        const { svg } = await mermaid.render(`comma_mermaid_${++mermaidCounter}`, source);
        host.innerHTML = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
        node.replaceWith(host);
      } catch {
        node.classList.add('is-error');
        node.title = 'Mermaid diagram could not be rendered';
      }
    }));
  }
}
