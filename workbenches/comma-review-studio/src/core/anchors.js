export function normalizeQuoteText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

export function findQuoteMatches(body, quote) {
  const source = String(body || '');
  const needle = String(quote || '');
  if (!needle) return [];
  const matches = [];
  let cursor = 0;
  while (cursor <= source.length - needle.length) {
    const index = source.indexOf(needle, cursor);
    if (index < 0) break;
    matches.push(index);
    cursor = index + Math.max(needle.length, 1);
  }
  return matches;
}

function scoreMatch(body, quote, index, locator = {}) {
  const prefix = String(locator.prefix || '').slice(-160);
  const suffix = String(locator.suffix || '').slice(0, 160);
  let score = 0;
  if (prefix && body.slice(Math.max(0, index - prefix.length), index) === prefix) score += 2;
  if (suffix && body.slice(index + quote.length, index + quote.length + suffix.length) === suffix) score += 2;
  return score;
}

export function createSourceLocator(body, quote, {
  rev = '', blockIndex = -1, endBlockIndex = blockIndex, blockStart = -1, blockEnd = -1,
} = {}) {
  const source = String(body || '');
  const quoteText = String(quote || '').trim();
  const matches = findQuoteMatches(source, quoteText);
  const scopedMatches = Number.isInteger(blockStart) && blockStart >= 0
    ? matches.filter((index) => index >= blockStart && (!Number.isInteger(blockEnd) || blockEnd < 0 || index < blockEnd))
    : [];
  const textIndex = scopedMatches.length === 1
    ? scopedMatches[0]
    : matches.length === 1 ? matches[0] : source.indexOf(quoteText);
  return {
    bodyRev: String(rev || ''),
    textIndex,
    blockIndex: Number.isInteger(blockIndex) ? blockIndex : -1,
    endBlockIndex: Number.isInteger(endBlockIndex) ? endBlockIndex : (Number.isInteger(blockIndex) ? blockIndex : -1),
    occurrenceIndex: matches.length > 1 && textIndex >= 0 ? matches.indexOf(textIndex) : 0,
    prefix: textIndex >= 0 ? source.slice(Math.max(0, textIndex - 160), textIndex) : '',
    suffix: textIndex >= 0 ? source.slice(textIndex + quoteText.length, textIndex + quoteText.length + 160) : '',
  };
}

export function resolveQuote(body, quote, locator = {}, currentRev = '') {
  const source = String(body || '');
  const needle = String(quote || '');
  const matches = findQuoteMatches(source, needle);
  if (!needle || !matches.length) return { state: 'missing', index: -1, matches: [] };
  if (matches.length === 1) return { state: 'unique', index: matches[0], matches };

  const recorded = Number(locator.textIndex ?? locator.text_index);
  const recordedRev = String(locator.bodyRev ?? locator.body_rev ?? '');
  if (recordedRev && currentRev && recordedRev === currentRev && matches.includes(recorded)) {
    return { state: 'exact-revision', index: recorded, matches };
  }

  const normalizedLocator = {
    prefix: locator.prefix || locator.context?.prefix || '',
    suffix: locator.suffix || locator.context?.suffix || '',
  };
  const scored = matches
    .map((index) => ({ index, score: scoreMatch(source, needle, index, normalizedLocator) }))
    .sort((a, b) => b.score - a.score);
  if (scored[0].score > 0 && (!scored[1] || scored[1].score < scored[0].score)) {
    return { state: 'context', index: scored[0].index, matches };
  }
  return { state: 'ambiguous', index: -1, matches };
}
