/**
 * Linking of the evidence panes by LOCATION (room / element), not by page coordinates.
 * Each finding group knows its locations; `location_pages[location]` lists the evidence (stage, page, boxes) drawn for
 * that location, so a chip can switch every pane to the page where the location is drawn and zoom to its boxes.
 * Pure functions only: the viewer keeps the state, tests pin the logic.
 */
import type { BBoxNorm, EvidenceCard, EvidenceRef, FindingGroup, StageValue } from '../../contracts/protocol';

export interface LocationTarget {
  /** Page key `${file_id}#${pdf_page_number}` (same as PageEvidence.key). */
  pageKey: string;
  boxes: BBoxNorm[];
  note: string | null;
}

export interface LocationLink {
  id: string;
  label: string;
  /** Per stage: where this location is drawn (first evidence of the stage). */
  targets: Record<string, LocationTarget>;
  summary: string;
}

export function pageKeyOf(ref: { file_id: string; pdf_page_number: number }): string {
  return `${ref.file_id}#${ref.pdf_page_number}`;
}

export function boxKey(box: BBoxNorm): string {
  return box.join(',');
}

function locationLabel(id: string, locationType: string | undefined, noun: string | null | undefined): string {
  if (locationType === 'ROOM') return `пом. ${id}`;
  return noun && !id.toLowerCase().startsWith(noun.toLowerCase()) ? `${noun} ${id}` : id;
}

function showValue(v: StageValue | undefined): string | null {
  return v === null || v === undefined || v === '' ? null : String(v);
}

/** Sentences end with . ! ? before a capital letter; abbreviations («с. 88», «л. 10», «пом. 140») do not split. */
function sentences(text: string): string[] {
  return text.split(/(?<=[.!?])\s+(?=[А-ЯЁA-Z])/u).map((s) => s.trim()).filter(Boolean);
}

function escapeRe(token: string): string {
  return token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * The part of a per-location rationale that belongs to one location: «пом. 140: ПД (…) — …; РД (…) — нет;
 * пом. 142: …» → the text between its «пом. 140:» marker and the next location's marker. Null when the rationale
 * has no such markers.
 */
export function locationSegment(rationale: string, id: string, allIds: string[]): string | null {
  const marker = (x: string) => new RegExp(`(?:^|[\\s;])((?:пом\\.\\s*)?${escapeRe(x)}(?:\\s*\\([^)]*\\))?:\\s+)`, 'u');
  const own = marker(id).exec(rationale);
  if (!own) return null;
  const start = own.index + own[0].length - own[1]!.length;
  const from = start + own[1]!.length;
  let end = rationale.length;
  for (const other of allIds) {
    if (other === id) continue;
    const m = marker(other).exec(rationale.slice(from));
    if (m) end = Math.min(end, from + m.index);
  }
  const text = rationale.slice(from, end).replace(/[\s;.]+$/u, '').trim();
  return text || null;
}

function mentions(sentence: string, token: string): boolean {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(^|[^\\p{L}\\p{N}.])${escaped}($|[^\\p{L}\\p{N}])`, 'u').test(sentence);
}

/**
 * The «что сравнивали» line. Sources in priority order: per-stage notes of the location's evidence, the rationale
 * sentences that mention the location, then the group/card ПД and РД values.
 */
export function comparedSummary(
  card: EvidenceCard,
  group: FindingGroup | null | undefined,
  location: { id: string; label: string; refs: EvidenceRef[] } | null,
  allIds: string[] = [],
): string {
  const prefix = location ? `${location.label}: ` : '';
  const note = (stage: string) => {
    const n = location?.refs.find((r) => r.stage === stage && r.note && !r.note.startsWith('пом.'))?.note;
    return n ?? null;
  };
  const pdNote = note('PD');
  const rdNote = note('RD');
  if (pdNote && rdNote) return `${prefix}ПД — ${pdNote}; РД — ${rdNote}`;
  const rationale = card.rationale ?? group?.rationale ?? null;
  if (location && rationale) {
    const segment = locationSegment(rationale, location.id, allIds.length ? allIds : [location.id]);
    if (segment) return `${prefix}${segment}`;
    const own = sentences(rationale).filter((s) => mentions(s, location.id));
    if (own.length) return `${prefix}${own.join(' ')}`;
  }
  const pd = showValue(group?.pd_value) ?? showValue(card.expected_value);
  const rd = showValue(group?.rd_value) ?? showValue(card.actual_value);
  if (pd || rd) return `${prefix}в ПД — ${pd ?? 'нет данных'}; в РД — ${rd ?? 'нет данных'}`;
  return rationale ? `${prefix}${rationale}` : '';
}

/** Locations of a card with the page and boxes each stage shows for them (empty when nothing is linked). */
export function buildLocationLinks(card: EvidenceCard, group?: FindingGroup | null): LocationLink[] {
  const pages = group?.location_pages ?? {};
  const ids = [...(group?.locations?.length ? group.locations : card.locations ?? [])];
  for (const k of Object.keys(pages)) if (!ids.includes(k)) ids.push(k);
  if (ids.length === 0) return [];
  const anchors: EvidenceRef[] = card.sources.map((s) => ({
    stage: s.stage,
    file_id: s.file_id,
    pdf_page_number: s.pdf_page_number,
    role: s.role,
    geometry: s.geometry,
  }));
  return ids.map((id) => {
    const label = locationLabel(id, group?.location_type, group?.element_noun);
    const own = pages[id] ?? [];
    // A location without its own evidence is drawn on the anchor pages of the card.
    const refs = own.length ? own : anchors;
    const targets: Record<string, LocationTarget> = {};
    for (const stage of new Set(refs.map((r) => r.stage))) {
      const ofStage = refs.filter((r) => r.stage === stage);
      const first = ofStage[0]!;
      const key = pageKeyOf(first);
      const boxes = ofStage.filter((r) => pageKeyOf(r) === key).flatMap((r) => (r.geometry?.boxes ?? []) as BBoxNorm[]);
      targets[stage] = { pageKey: key, boxes, note: first.note ?? null };
    }
    return { id, label, targets, summary: comparedSummary(card, group, { id, label, refs: own }, ids) };
  });
}

/** Circular step through locations (lockstep ‹ › and [ ]). */
export function stepLocation(index: number, delta: number, count: number): number {
  return count <= 0 ? 0 : (((index + delta) % count) + count) % count;
}
