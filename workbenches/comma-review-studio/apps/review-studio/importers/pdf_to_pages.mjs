#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';

const [inputPath, outputRoot] = process.argv.slice(2);
if (!inputPath || !outputRoot) {
  throw new Error('usage: pdf_to_pages.mjs INPUT.pdf OUTPUT_ROOT');
}

const warnings = [];
const originalWarn = console.warn;
console.warn = (...args) => {
  warnings.push(args.map(String).join(' ').slice(0, 800));
};

try {
  const bytes = new Uint8Array(await fs.readFile(inputPath));
  const task = getDocument({
    data: bytes,
    disableFontFace: true,
    useSystemFonts: false,
    isEvalSupported: false,
    stopAtErrors: false,
  });
  const document = await task.promise;
  const pages = [];
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const content = await page.getTextContent({ disableNormalization: false });
    const chunks = [];
    for (const item of content.items || []) {
      if (!item || typeof item.str !== 'string' || !item.str) continue;
      chunks.push(item.str);
      chunks.push(item.hasEOL ? '\n' : ' ');
    }
    pages.push({ page: pageNumber, text: chunks.join('').replace(/[ \t]+\n/g, '\n').trim() });
    page.cleanup();
  }
  let metadata = {};
  try {
    const raw = await document.getMetadata();
    const info = raw?.info || {};
    metadata = {
      title: String(info.Title || '').slice(0, 500),
      author: String(info.Author || '').slice(0, 500),
      subject: String(info.Subject || '').slice(0, 1000),
    };
  } catch (error) {
    warnings.push(`metadata: ${error.message || error}`);
  }
  await task.destroy();
  const packageRaw = await fs.readFile(new URL('../../../node_modules/pdfjs-dist/package.json', import.meta.url), 'utf8');
  const result = {
    schema_version: 'comma-pdf-pages/v1',
    pages,
    page_count: pages.length,
    metadata,
    warnings,
    versions: { pdfjs_dist: JSON.parse(packageRaw).version || '' },
  };
  await fs.mkdir(outputRoot, { recursive: true });
  await fs.writeFile(path.join(outputRoot, 'result.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
} finally {
  console.warn = originalWarn;
}
