import type { RefNodeData, SourceRef } from '../types/canvas';

export function cleanDisplayText(value: unknown): string {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

export function isAbsolutePathLikeTitle(value: unknown): boolean {
  const text = cleanDisplayText(value);
  return (
    text.startsWith('/') ||
    text.startsWith('~/') ||
    /^[A-Za-z]:[\\/]/.test(text)
  );
}

export function basenameFromPathLike(value: unknown): string {
  const text = cleanDisplayText(value).replace(/[\\/]+$/, '');
  if (!text) return '';
  return text.split(/[\\/]+/).filter(Boolean).pop() || text;
}

export function deriveRefDisplayTitle(data: Partial<RefNodeData>, fallback = 'Reference'): string {
  const ref = data.source_ref as SourceRef | undefined;
  const raw = cleanDisplayText(data.title || data.label || ref?.label || ref?.path || fallback) || fallback;
  if (isAbsolutePathLikeTitle(raw)) return basenameFromPathLike(raw) || raw;
  return raw;
}

export function refHoverTitle(data: Partial<RefNodeData>, displayTitle: string): string {
  const ref = data.source_ref as SourceRef | undefined;
  return cleanDisplayText(ref?.resolved_path || ref?.path || data.title || displayTitle);
}
