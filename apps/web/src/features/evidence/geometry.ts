/**
 * Normalized page geometry (contract PDF_VISIBLE_ROTATED_TL_V1: visible area after CropBox/MediaBox/Rotate,
 * origin top-left, [0;1] — ТЗ §9.1 п.4) → OpenSeadragon viewport coordinates.
 *
 * OSD viewport units are width-normalized: the page spans x ∈ [0, 1], y ∈ [0, h/w]. A bbox [x0, y0, x1, y1]
 * maps to Rect(x0, y0·h/w, x1−x0, (y1−y0)·h/w) (05 §3.17.2). Tiles come from the same MuPDF engine that
 * computed the boxes, so there is no rotation math here.
 */
import type { BBoxNorm } from '../../contracts/protocol';

export interface VRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** aspect = page height / page width (visible area). */
export function bboxToViewport(b: BBoxNorm, aspect: number): VRect {
  const [x0, y0, x1, y1] = b;
  return { x: x0, y: y0 * aspect, width: Math.max(0, x1 - x0), height: Math.max(0, (y1 - y0) * aspect) };
}

export function unionBox(boxes: BBoxNorm[]): BBoxNorm | null {
  if (boxes.length === 0) return null;
  let [x0, y0, x1, y1] = boxes[0]!;
  for (const b of boxes.slice(1)) {
    x0 = Math.min(x0, b[0]);
    y0 = Math.min(y0, b[1]);
    x1 = Math.max(x1, b[2]);
    y1 = Math.max(y1, b[3]);
  }
  return [x0, y0, x1, y1];
}

/**
 * Viewport rect to fit on «Показать фрагмент»: the boxes ⊕ `padding` (25 % of their size on each side), at
 * least `minFrac` of the page width wide/tall (a tiny room label must not fill the screen), clamped to the page.
 * No boxes → the whole page.
 */
export function fitRect(boxes: BBoxNorm[], aspect: number, padding = 0.25, minFrac = 0.08): VRect {
  const u = unionBox(boxes);
  if (!u) return { x: 0, y: 0, width: 1, height: aspect };
  const r = bboxToViewport(u, aspect);
  let w = Math.max(r.width * (1 + 2 * padding), minFrac);
  let h = Math.max(r.height * (1 + 2 * padding), minFrac);
  w = Math.min(w, 1);
  h = Math.min(h, aspect);
  const cx = r.x + r.width / 2;
  const cy = r.y + r.height / 2;
  const x = Math.min(Math.max(cx - w / 2, 0), 1 - w);
  const y = Math.min(Math.max(cy - h / 2, 0), aspect - h);
  return { x, y, width: w, height: h };
}

/** «0,697; 0,274 — 0,888; 0,574» — for screen readers and tooltips. */
export function bboxLabel(b: BBoxNorm): string {
  const f = (v: number) => v.toFixed(3).replace('.', ',');
  return `${f(b[0])}; ${f(b[1])} — ${f(b[2])}; ${f(b[3])}`;
}

export const ROLE_COLORS = {
  /** Organizers' legend: «ПД — проектное решение, база сравнения» (blue). */
  EXPECTED: '#1D4ED8',
  /** «РД — зона отсутствующего или измененного решения» (red). */
  ACTUAL: '#C62828',
  CLOUD: '#722ED1',
  ROOM: '#595959',
} as const;

/** Colour by role; stages fall back to the same convention (ПД blue, РД/ИД red). */
export function roleColor(role: string | undefined, stage: string): string {
  if (role === 'EXPECTED' || role === 'SUPPORTING_EXPECTED') return ROLE_COLORS.EXPECTED;
  if (role === 'ACTUAL' || role === 'SUPPORTING_ACTUAL') return ROLE_COLORS.ACTUAL;
  return stage === 'PD' ? ROLE_COLORS.EXPECTED : ROLE_COLORS.ACTUAL;
}
