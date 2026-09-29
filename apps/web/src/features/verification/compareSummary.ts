/** One-line «Что сравнивали» for the selected room/location, built only from the card's own finding data. */
import type { EvidenceCardView } from './types';

const MAX = 160;

function text(v: unknown): string | null {
  if (v === null || v === undefined || v === '') return null;
  const s = typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : JSON.stringify(v);
  const one = s.replace(/\s+/g, ' ').trim();
  return one.length > MAX ? `${one.slice(0, MAX - 1)}…` : one;
}

function actualStage(card: EvidenceCardView): string {
  const src = card.sources.find((s) => s.role === 'ACTUAL' && s.stage !== 'PD') ?? card.sources.find((s) => s.stage !== 'PD');
  return src?.stage === 'ID' ? 'ИД' : 'РД';
}

export function compareSummary(card: EvidenceCardView): string | null {
  const place = card.location ? `${card.location_type === 'ROOM' ? 'пом. ' : ''}${card.location}` : null;
  const expected = text(card.values.expected ?? card.values.pd);
  const actual = text(card.values.actual ?? card.values.rd ?? card.values.id);
  const stage = actualStage(card);
  let body: string | null = null;
  if (expected && actual) body = `в ПД — ${expected}; в ${stage} — ${actual}`;
  else if (expected) body = `в ПД — ${expected}; в ${stage} — не найдено`;
  else if (actual) body = `в ${stage} — ${actual}; в ПД — не найдено`;
  else body = text(card.rationale);
  if (!body) return null;
  const label = card.param?.label ? `${card.param.label.replace(/\s*\([^)]*\)\s*$/, '')}` : null;
  return `${place ?? label ?? ''}${place || label ? ': ' : ''}${body}`;
}
