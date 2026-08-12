function stripHeadingMarkup(text) {
  return String(text || '')
    .replace(/^[#\s]+/, '')
    .replace(/\s+#+\s*$/, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_~]/g, '')
    .trim();
}

function slug(value) {
  const base = String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return base || 'section';
}

function headingFromBlock(block) {
  if (!block || block.type !== 'heading') return null;
  const line = String(block.raw || '').split(/\r?\n/, 1)[0] || '';
  const match = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
  if (!match) return null;
  const title = stripHeadingMarkup(match[2]);
  if (!title) return null;
  return { level: match[1].length, title };
}

export function buildSectionIndex(blocks = []) {
  const headings = [];
  const usedIds = new Map();
  for (const block of blocks || []) {
    const heading = headingFromBlock(block);
    if (!heading) continue;
    const base = slug(heading.title);
    const count = (usedIds.get(base) || 0) + 1;
    usedIds.set(base, count);
    headings.push({
      id: count === 1 ? `sec-${base}` : `sec-${base}-${count}`,
      title: heading.title,
      level: heading.level,
      blockIndex: block.index,
      startBlockIndex: block.index,
      endBlockIndex: block.index,
    });
  }
  if (!headings.length) {
    const last = blocks.length ? blocks[blocks.length - 1].index : -1;
    return [{
      id: 'sec-document',
      title: 'Document',
      level: 1,
      blockIndex: blocks.length ? blocks[0].index : -1,
      startBlockIndex: blocks.length ? blocks[0].index : -1,
      endBlockIndex: last,
    }];
  }
  for (let index = 0; index < headings.length; index += 1) {
    const next = headings[index + 1];
    const lastBlock = blocks.length ? blocks[blocks.length - 1].index : headings[index].blockIndex;
    headings[index].endBlockIndex = next ? next.blockIndex - 1 : lastBlock;
  }
  return headings;
}

export function sectionForBlock(sectionIndex = [], blockIndex = -1) {
  const sections = Array.isArray(sectionIndex) ? sectionIndex : [];
  if (!sections.length || !Number.isInteger(blockIndex) || blockIndex < 0) return null;
  return sections.find((section) => (
    blockIndex >= section.startBlockIndex && blockIndex <= section.endBlockIndex
  )) || sections[sections.length - 1] || null;
}
