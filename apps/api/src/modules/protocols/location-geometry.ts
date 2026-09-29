/**
 * Per-location geometry for the evidence card's room-linked panes.
 * A finding group's `location_pages[location]` says on which page each stage draws a location, but the batch writes
 * the boxes only on the atomic finding of that location (`findings.jsonl`, one row per room). The web viewer needs
 * them to zoom each pane to the chosen room and dim the others, so they are copied into the served group
 * (a copy: artifact rows are cached and shared).
 */
type Json = Record<string, unknown>;

interface Ref extends Json {
  stage?: string;
  file_id?: string;
  pdf_page_number?: number;
  geometry?: unknown;
}

const pageOf = (r: Ref) => `${r.file_id}#${r.pdf_page_number}`;

export function enrichLocationPages(groups: unknown[], findings: unknown[]): unknown[] {
  const byGroupLocation = new Map<string, Ref[]>();
  for (const f of findings as Json[]) {
    const gid = f.finding_group_id;
    const loc = f.location;
    if (typeof gid !== 'string' || typeof loc !== 'string' || !Array.isArray(f.evidence)) continue;
    byGroupLocation.set(`${gid}\u0000${loc}`, f.evidence as Ref[]);
  }
  return groups.map((g) => {
    const group = g as Json;
    const pages = group.location_pages as Record<string, Ref[]> | undefined;
    const gid = group.finding_group_id;
    if (!pages || typeof gid !== 'string') return g;
    let changed = false;
    const next: Record<string, Ref[]> = {};
    for (const [loc, refs] of Object.entries(pages)) {
      const own = byGroupLocation.get(`${gid}\u0000${loc}`) ?? [];
      next[loc] = refs.map((ref) => {
        if (ref.geometry) return ref;
        const match = own.find((e) => e.stage === ref.stage && pageOf(e) === pageOf(ref) && e.geometry);
        if (!match) return ref;
        changed = true;
        return { ...ref, geometry: match.geometry };
      });
    }
    return changed ? { ...group, location_pages: next } : g;
  });
}
