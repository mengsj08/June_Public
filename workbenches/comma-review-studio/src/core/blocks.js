export function segmentMarkdown(lexer, source) {
  const body = String(source ?? '');
  if (!body) return [];
  if (typeof lexer !== 'function') {
    return [{ index: 0, start: 0, end: body.length, raw: body, type: 'document', editable: true }];
  }

  const tokens = lexer(body);
  const rawJoined = tokens.map((token) => token.raw || '').join('');
  if (rawJoined !== body) {
    return [{ index: 0, start: 0, end: body.length, raw: body, type: 'document', editable: true }];
  }

  const blocks = [];
  let offset = 0;
  let index = 0;
  for (const token of tokens) {
    const raw = String(token.raw || '');
    const start = offset;
    offset += raw.length;
    if (!raw || token.type === 'space') continue;
    blocks.push({
      index: index++,
      start,
      end: offset,
      raw,
      type: String(token.type || 'unknown'),
      editable: true,
    });
  }
  return blocks;
}

export function replaceBlock(source, block, replacement) {
  const body = String(source ?? '');
  if (!block || block.start < 0 || block.end < block.start || block.end > body.length) {
    throw new RangeError('Invalid Markdown block range');
  }
  return body.slice(0, block.start) + String(replacement ?? '') + body.slice(block.end);
}
