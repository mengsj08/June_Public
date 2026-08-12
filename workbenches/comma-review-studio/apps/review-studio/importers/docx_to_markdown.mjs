#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

import mammoth from 'mammoth';
import sanitizeHtml from 'sanitize-html';
import TurndownService from 'turndown';
import gfmPlugin from 'turndown-plugin-gfm';

const [inputPath, outputRoot, assetPrefix] = process.argv.slice(2);
if (!inputPath || !outputRoot || !assetPrefix) {
  throw new Error('usage: docx_to_markdown.mjs INPUT.docx OUTPUT_ROOT ASSET_PREFIX');
}

const assetsRoot = path.join(outputRoot, 'assets');
await fs.mkdir(assetsRoot, { recursive: true });
const assets = [];

const imageConverter = mammoth.images.imgElement(async (image) => {
  const buffer = await image.readAsBuffer();
  const mediaType = String(image.contentType || 'application/octet-stream').toLowerCase();
  const extensions = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/svg+xml': '.svg',
    'image/tiff': '.tiff',
    'image/bmp': '.bmp',
  };
  const extension = extensions[mediaType];
  if (!extension) throw new Error(`unsupported DOCX image type: ${mediaType}`);
  const digest = crypto.createHash('sha256').update(buffer).digest('hex').slice(0, 16);
  const name = `figure-${digest}${extension}`;
  if (!assets.some((item) => item.name === name)) {
    await fs.writeFile(path.join(assetsRoot, name), buffer, { flag: 'wx' }).catch(async (error) => {
      if (error.code !== 'EEXIST') throw error;
    });
    assets.push({ name, media_type: mediaType, byte_count: buffer.length });
  }
  return { src: `${assetPrefix}/${name}` };
});

const converted = await mammoth.convertToHtml(
  { path: inputPath },
  {
    convertImage: imageConverter,
    includeDefaultStyleMap: true,
    styleMap: [
      "p[style-name='Title'] => h1:fresh",
      "p[style-name='Subtitle'] => p.subtitle:fresh",
      "p[style-name='Caption'] => p.figure-caption:fresh",
    ],
  },
);

const cleanHtml = sanitizeHtml(converted.value, {
  allowedTags: [
    'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'strong', 'b', 'em', 'i', 'u', 's', 'sub', 'sup', 'code', 'pre',
    'blockquote', 'ul', 'ol', 'li', 'a', 'img',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption',
  ],
  allowedAttributes: {
    a: ['href', 'title'],
    img: ['src', 'alt', 'title'],
    td: ['colspan', 'rowspan'],
    th: ['colspan', 'rowspan'],
    p: ['class'],
  },
  allowedClasses: { p: ['subtitle', 'figure-caption'] },
  allowedSchemes: ['http', 'https', 'mailto'],
  allowProtocolRelative: false,
  disallowedTagsMode: 'discard',
  enforceHtmlBoundary: true,
});

const turndown = new TurndownService({
  headingStyle: 'atx',
  bulletListMarker: '-',
  codeBlockStyle: 'fenced',
  emDelimiter: '*',
  strongDelimiter: '**',
});
turndown.use(gfmPlugin.gfm);
turndown.addRule('figureCaption', {
  filter: (node) => node.nodeName === 'P' && node.classList?.contains('figure-caption'),
  replacement: (content) => `\n\n*${content.trim()}*\n\n`,
});
const descendants = (root, tagName) => {
  const matches = [];
  const visit = (node) => {
    for (const child of Array.from(node?.childNodes || [])) {
      if (child.nodeName === tagName) matches.push(child);
      visit(child);
    }
  };
  visit(root);
  return matches;
};
const plainText = (root) => {
  if (root?.nodeType === 3) return root.nodeValue || '';
  return Array.from(root?.childNodes || []).map(plainText).join(' ');
};
turndown.addRule('wordTable', {
  filter: 'table',
  replacement: (_content, node) => {
    const rows = descendants(node, 'TR').map((row) => (
      Array.from(row.childNodes || [])
        .filter((cell) => ['TD', 'TH'].includes(cell.nodeName))
        .map((cell) => plainText(cell).replace(/\s+/g, ' ').trim().replace(/\|/g, '\\|'))
    )).filter((row) => row.length);
    if (!rows.length) return '';
    const width = Math.max(...rows.map((row) => row.length));
    const formatRow = (row) => `| ${[...row, ...Array(Math.max(0, width - row.length)).fill('')].join(' | ')} |`;
    return `\n\n${formatRow(rows[0])}\n${formatRow(Array(width).fill('---'))}\n${rows.slice(1).map(formatRow).join('\n')}\n\n`;
  },
});

// Mammoth wraps each Word table cell in <p>. The GFM table rule expects the
// cell's inline content, so collapse those paragraph wrappers deterministically
// while preserving multi-paragraph cells as explicit line breaks.
let gfmReadyHtml = cleanHtml.replace(
  /<(td|th)([^>]*)>([\s\S]*?)<\/\1>/gi,
  (_match, tag, attributes, inner) => {
    const flattened = inner
      .replace(/<\/p>\s*<p[^>]*>/gi, '<br>')
      .replace(/^\s*<p[^>]*>/i, '')
      .replace(/<\/p>\s*$/i, '');
    return `<${tag}${attributes}>${flattened}</${tag}>`;
  },
);
gfmReadyHtml = gfmReadyHtml.replace(/<table([^>]*)>([\s\S]*?)<\/table>/gi, (table) => {
  if (/<thead[\s>]/i.test(table) || !/<tbody[\s>]/i.test(table)) return table;
  const promoted = table
    .replace(/<tbody([^>]*)>/i, '<thead$1>')
    .replace(/<\/tr>/i, '</tr></thead><tbody>');
  return promoted.replace(
    /(<thead[^>]*>\s*<tr[^>]*>)([\s\S]*?)(<\/tr>)/i,
    (_match, start, cells, end) => `${start}${cells.replace(/<(\/?)td\b/gi, '<$1th')}${end}`,
  );
});

const markdown = turndown.turndown(gfmReadyHtml);
const packageVersion = async (name) => {
  try {
    const raw = await fs.readFile(new URL(`../../../node_modules/${name}/package.json`, import.meta.url), 'utf8');
    return JSON.parse(raw).version || '';
  } catch {
    return '';
  }
};

const result = {
  schema_version: 'comma-docx-conversion/v1',
  markdown,
  assets,
  messages: (converted.messages || []).map((item) => `${item.type || 'warning'}: ${item.message || ''}`),
  versions: {
    mammoth: await packageVersion('mammoth'),
    sanitize_html: await packageVersion('sanitize-html'),
    turndown: await packageVersion('turndown'),
    turndown_plugin_gfm: await packageVersion('turndown-plugin-gfm'),
  },
};
await fs.writeFile(path.join(outputRoot, 'result.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
