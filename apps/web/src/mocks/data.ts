/**
 * Mock data for MSW (dev without the API: `pnpm --filter @inspector/web dev:mock`, and the page tests).
 *
 * - Тюменская 5: the D1 fixture of apps/api/fixtures/d1 (contract-valid protocol, finding groups and the F0202
 *   layout: gold groups, real file hashes, registered markup zones).
 * - OBJ-SYNTH-*: synthetic objects (clearly named so) that exercise every indicator colour. Never real ids.
 * Colours are computed with the API's own function (apps/api/src/modules/dashboard/indicator.ts).
 */
import tyumenProtocol from '../../../api/fixtures/d1/OBJ-TYUMENSKAYA-5-GOLD-SEED.protocol.json';
import tyumenGroupsRaw from '../../../api/fixtures/d1/OBJ-TYUMENSKAYA-5-GOLD-SEED.groups.jsonl?raw';
import f0202Layout from '../../../api/fixtures/d1/F0202.layout.json';
import { computeIndicator, tallyProtocol } from '../../../api/src/modules/dashboard/indicator';
import type { components } from '../api/schema.gen';
import type { FileItem, ObjectDetail } from '../api/types';
import type { FindingGroup, Protocol } from '../contracts/protocol';
import type { PageView } from '../features/evidence/pageSource';

type S = components['schemas'];

export const TYUMEN = 'OBJ-TYUMENSKAYA-5-GOLD-SEED';
const TS = '2026-09-28T09:00:00.000Z';

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export const RUN_IDS = {
  tyumenV1: '01923a6e-0000-7000-8000-000000000001',
  tyumenV2: '01923a6e-0000-7000-8000-000000000002',
  red: '01923a6e-0000-7000-8000-000000000003',
  green: '01923a6e-0000-7000-8000-000000000004',
};

export interface MockObject {
  detail: ObjectDetail;
  protocols: Array<{ runId: string; batchRunId: string; protocol: Protocol; groups: FindingGroup[]; formats: Array<'json' | 'docx' | 'pdf'> }>;
}

function detail(id: string, name: string, split: 'TRAIN_PUBLIC' | 'TEST_HIDDEN', total: number): ObjectDetail {
  return {
    object_id: id,
    name,
    split,
    scenario: null,
    indicator_color: 'NONE',
    files_total: total,
    files_present: total,
    files_missing_on_disk: 0,
    files_by_stage: { PD: Math.round(total * 0.8), RD: 0, ID: 0, RD_ID_MIXED: total - Math.round(total * 0.8), UNKNOWN: 0 },
    last_run: { id: '01923a6e-0000-7000-8000-0000000000aa', batch_run_id: 'm0-int-inventory-all', imported_at: '2026-09-27T21:32:20.160Z' },
    updated_at: TS,
    input_manifest_hash: '39d1d452d64d6629bfc37a7caee6dc4cdc2e55f9317711ca464de40851fa5f91',
    address: null,
    customer: null,
    contractor: null,
    permit_number: null,
    created_at: TS,
  };
}

const tyumen = tyumenProtocol as unknown as Protocol;
const tyumenGroups = tyumenGroupsRaw
  .split('\n')
  .filter((l) => l.trim())
  .map((l) => JSON.parse(l) as FindingGroup);

/** Version 1 of Тюменская: a day earlier, before the FREE-HEATING hypothesis was bound. */
function tyumenV1(): Protocol {
  const p = clone(tyumen);
  p.generated_at = '2026-09-27T09:00:00Z';
  p.protocol_no = '2026-09-27-TYUMEN5-1';
  p.header.title = `ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ № ${p.protocol_no}`;
  p.header.generated_at_ru = '27 сентября 2026 г.';
  return p;
}

/** Synthetic: the inspector confirmed the first critical group → the object turns red. */
function redProtocol(): Protocol {
  const p = clone(tyumen);
  p.object = { object_id: 'OBJ-SYNTH-RED', name: 'Синтетический объект «Северный», корпус 2 (демо)', address: 'демонстрационные данные' };
  p.protocol_no = '2026-09-28-SYNTHRED-1';
  p.header.title = `ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ № ${p.protocol_no}`;
  p.header.status_line = '🔄 ВЕРИФИКАЦИЯ В ПРОЦЕССЕ (дозагрузка возможна)';
  p.process_status = 'VERIFYING';
  const row = p.appendix2.section4_critical.rows[0]!;
  row.inspector_status = 'CONFIRMED_VIOLATION';
  row.inspector_decision_ru = '✅ Подтверждено';
  p.evidence_cards[0]!.inspector = { status: 'CONFIRMED_VIOLATION', basis_code: null, comment: 'Подтверждено по листу 26 ПД и плану ОВ1', decided_at: '2026-09-28T10:15:00Z' };
  p.tz92_tables.a3_confirmed = (p.tz92_tables.a2_candidates ?? []).slice(0, 1).map((r) => ({ ...r, inspector_status: 'CONFIRMED_VIOLATION' }));
  p.tz92_tables.a2_candidates = (p.tz92_tables.a2_candidates ?? []).slice(1);
  p.ext = { note: 'Синтетический объект для демонстрации индикации (красный = подтверждённое нарушение).' };
  return p;
}

/** Synthetic: everything rejected, set complete → green. */
function greenProtocol(): Protocol {
  const p = clone(tyumen);
  p.object = { object_id: 'OBJ-SYNTH-GREEN', name: 'Синтетический объект «Школа на 550 мест» (демо)', address: 'демонстрационные данные' };
  p.protocol_no = '2026-09-26-SYNTHGREEN-1';
  p.generated_at = '2026-09-26T12:30:00Z';
  p.header.title = `ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ № ${p.protocol_no}`;
  p.header.generated_at_ru = '26 сентября 2026 г.';
  p.header.status_line = '☑️ ВЕРИФИКАЦИЯ ЗАВЕРШЕНА, ПРОТОКОЛ НЕ ФИНАЛИЗИРОВАН (дозагрузка возможна)';
  p.status = 'VERIFICATION_COMPLETED';
  p.process_status = 'COMPLETED';
  p.scenario = 'FULL';
  p.header.scenario_line = 'Тип проверки: FULL (Полный комплект (ПД, РД, ИД))';
  p.appendix2.section1_load_status.scenario_line = p.header.scenario_line;
  p.upload_status = { pd: 'PD_UPLOADED', rd: 'RD_UPLOADED', id: 'ID_UPLOADED' };
  const rejected = p.appendix2.section4_critical.rows;
  p.tz92_tables.a4_negative_verified = rejected.map((r) => ({
    card_ref: r.card_ref,
    parameter_code: r.parameter_code,
    parameter_label: r.parameter_label.replace(/\s*\[карточка Б\.\d+\]$/, ''),
    locations: r.locations ?? [],
    decided_by: 'INSPECTOR',
    reason_code: 'APPROVED_CHANGE',
    reason_ru: 'Согласованное изменение',
    comment: 'Изменение согласовано письмом проектировщика',
    ai_comment: '🤖 ИИ СОГЛАСЕН (91%). Причина обоснована.',
    decided_at: '2026-09-26T15:00:00Z',
  }));
  p.appendix2.section4_critical = { count: 0, rows: [] };
  p.appendix2.section6_ai_suspicions = { count: 0, rows: [] };
  p.appendix2.section7_resolution = { critical: [], substantial: [] };
  p.appendix2.section3_not_checked_no_id = { count: 0, rows: [] };
  p.tz92_tables.a1_completeness = [];
  p.tz92_tables.a2_candidates = [];
  p.tz92_tables.a5_hypotheses = [];
  p.evidence_cards = p.evidence_cards
    .filter((c) => c.card_no !== 'Б.2')
    .map((c) => ({ ...c, inspector: { status: 'NEGATIVE_VERIFIED', reason_code: 'APPROVED_CHANGE', comment: 'Согласованное изменение' } }));
  p.ext = { note: 'Синтетический объект для демонстрации индикации (зелёный = все кандидаты отклонены, комплект полный).' };
  return p;
}

export function buildMockObjects(): Map<string, MockObject> {
  const objects = new Map<string, MockObject>();
  objects.set(TYUMEN, {
    detail: { ...detail(TYUMEN, 'Пример нарушений на чертежах (Тюменская, 5)', 'TRAIN_PUBLIC', 58), files_by_stage: { PD: 47, RD: 0, ID: 0, RD_ID_MIXED: 10, UNKNOWN: 1 } },
    protocols: [
      { runId: RUN_IDS.tyumenV2, batchRunId: 'd1-fixture-tyumen', protocol: clone(tyumen), groups: clone(tyumenGroups), formats: ['json', 'docx', 'pdf'] },
      { runId: RUN_IDS.tyumenV1, batchRunId: 'd1-fixture-tyumen-v1', protocol: tyumenV1(), groups: clone(tyumenGroups), formats: ['json'] },
    ],
  });
  objects.set('OBJ-SYNTH-RED', {
    detail: detail('OBJ-SYNTH-RED', 'Синтетический объект «Северный», корпус 2 (демо)', 'TRAIN_PUBLIC', 40),
    protocols: [{ runId: RUN_IDS.red, batchRunId: 'synthetic-red', protocol: redProtocol(), groups: clone(tyumenGroups), formats: ['json'] }],
  });
  objects.set('OBJ-SYNTH-GREEN', {
    detail: detail('OBJ-SYNTH-GREEN', 'Синтетический объект «Школа на 550 мест» (демо)', 'TRAIN_PUBLIC', 36),
    protocols: [{ runId: RUN_IDS.green, batchRunId: 'synthetic-green', protocol: greenProtocol(), groups: [], formats: ['json', 'pdf'] }],
  });
  objects.set('OBJ-SYNTH-NEW', { detail: detail('OBJ-SYNTH-NEW', 'Синтетический объект без протокола (демо)', 'TRAIN_PUBLIC', 12), protocols: [] });
  objects.set('OBJ-SYNTH-HIDDEN', { detail: detail('OBJ-SYNTH-HIDDEN', 'Синтетическая скрытая выборка (демо)', 'TEST_HIDDEN', 213), protocols: [] });
  return objects;
}

export function versionsOf(o: MockObject): Array<S['ProtocolVersion']> {
  const chronological = [...o.protocols].sort((a, b) => Date.parse(a.protocol.generated_at) - Date.parse(b.protocol.generated_at));
  const latest = chronological.at(-1)?.runId;
  return chronological
    .map((x, i) => {
      const p = x.protocol;
      return {
        run_id: x.runId,
        batch_run_id: x.batchRunId,
        object_id: p.object.object_id,
        protocol_no: p.protocol_no,
        version: p.version,
        web_version: i + 1,
        is_latest: x.runId === latest,
        generated_at: new Date(p.generated_at).toISOString(),
        status: p.status as S['ProtocolStatus'],
        is_final: p.is_final,
        scenario: p.scenario as S['LoadScenario'],
        status_line: p.header.status_line,
        counts: {
          critical: p.appendix2.section4_critical.count,
          substantial: p.appendix2.section5_substantial.count,
          suspicions: p.appendix2.section6_ai_suspicions.count,
          not_checked_no_id: p.appendix2.section3_not_checked_no_id.count,
          cards: p.evidence_cards.length,
        },
        formats: x.formats,
        pipeline_version: p.versions.pipeline_version,
        matrix_version: p.versions.matrix_version ?? null,
        input_manifest_hash: p.input_manifest_hash,
        content_sha256: p.content_sha256 ?? null,
      };
    })
    .reverse();
}

const moscowDate = (iso: string) => new Date(Date.parse(iso) + 3 * 3600_000).toISOString().slice(0, 10);

/** Same semantics as DashboardService (apps/api/src/modules/dashboard/dashboard.service.ts). */
export function dashboardOf(objects: Map<string, MockObject>, q: URLSearchParams): S['Dashboard'] {
  const list = (k: string) => (q.get(k) ?? '').split(',').filter(Boolean);
  const text = q.get('q')?.toLowerCase();
  const colors = new Set(list('color'));
  const sections = new Set(list('section'));
  const statuses = new Set(list('status'));
  const rows = [...objects.values()]
    .sort((a, b) => a.detail.object_id.localeCompare(b.detail.object_id))
    .map((o) => {
      const hidden = o.detail.split === 'TEST_HIDDEN';
      const latestVersion = hidden ? null : (versionsOf(o)[0] ?? null);
      const latest = latestVersion ? o.protocols.find((x) => x.runId === latestVersion.run_id)!.protocol : null;
      const tally = latest ? tallyProtocol(latest as never) : null;
      const counters = tally?.counters ?? {
        confirmed: 0, pending: 0, pending_high: 0, clarification: 0, rejected: 0, missing_evidence: 0, not_comparable: 0, suspicions: 0, suspicions_pending: 0,
      };
      const indicator = computeIndicator({ hasProtocol: latest !== null, hiddenInventoryOnly: hidden, scenario: latest?.scenario ?? null, counters });
      return {
        o,
        latest,
        tally,
        item: {
          object_id: o.detail.object_id,
          name: o.detail.name,
          split: o.detail.split,
          indicator: indicator as S['Indicator'],
          latest_protocol: latestVersion,
          counters,
          sections: tally ? [...tally.bySection.keys()].sort() : [],
          upload_status: {
            pd: (latest?.upload_status?.pd ?? null) as S['StageUploadStatusOrNull'],
            rd: (latest?.upload_status?.rd ?? null) as S['StageUploadStatusOrNull'],
            id: (latest?.upload_status?.id ?? null) as S['StageUploadStatusOrNull'],
          },
          files_total: o.detail.files_total,
          updated_at: latest ? new Date(latest.generated_at).toISOString() : o.detail.updated_at,
        } satisfies S['DashboardObject'],
      };
    })
    .filter((r) => {
      if (text && !r.item.object_id.toLowerCase().includes(text) && !(r.item.name ?? '').toLowerCase().includes(text)) return false;
      if (q.get('scenario') && r.latest?.scenario !== q.get('scenario')) return false;
      const from = q.get('date_from');
      const to = q.get('date_to');
      if (from || to) {
        if (!r.latest) return false;
        const day = moscowDate(r.latest.generated_at);
        if ((from && day < from) || (to && day > to)) return false;
      }
      if (sections.size || statuses.size) {
        const hit = (r.tally?.statuses ?? []).some(
          (s) => (!sections.size || sections.has(s.section_ru)) && (!statuses.size || statuses.has(s.status)),
        );
        if (!hit) return false;
      }
      return true;
    });
  const tiles = { total: rows.length, RED: 0, YELLOW: 0, GREEN: 0, NONE: 0, awaiting_decision: 0 };
  for (const r of rows) {
    tiles[r.item.indicator.color] += 1;
    tiles.awaiting_decision += r.item.counters.pending + r.item.counters.clarification;
  }
  const visible = colors.size ? rows.filter((r) => colors.has(r.item.indicator.color)) : rows;
  const bySection = new Map<string, S['SectionSummary']>();
  for (const r of visible) {
    for (const [section, c] of r.tally?.bySection ?? []) {
      const s = bySection.get(section) ?? { section_ru: section, confirmed: 0, pending: 0, clarification: 0, rejected: 0, suspicions: 0 };
      s.confirmed += c.confirmed;
      s.pending += c.pending;
      s.clarification += c.clarification;
      s.rejected += c.rejected;
      bySection.set(section, s);
    }
    if (r.item.counters.suspicions > 0) {
      const s = bySection.get('Вне матрицы') ?? { section_ru: 'Вне матрицы', confirmed: 0, pending: 0, clarification: 0, rejected: 0, suspicions: 0 };
      s.suspicions += r.item.counters.suspicions;
      bySection.set('Вне матрицы', s);
    }
  }
  return { generated_at: TS, tiles, items: visible.map((r) => r.item), sections: [...bySection.values()] };
}

// ── Page geometry of the gold pages (visible size in pt, from the PDFs) ──
const PAGE_PT: Record<string, [number, number]> = {
  'F0171#104': [2384, 842],
  'F0171#99': [4212, 1191],
  'F0171#88': [2384, 1684],
  'F0171#11': [595, 842],
  'F0201#17': [2384, 3370],
  'F0201#18': [2384, 3370],
  'F0201#20': [2384, 3370],
  'F0202#17': [2384, 3370],
};

const LAYERS_F0202: Array<[string, boolean]> = [
  ['A-DOORS', false],
  ['G-ANNO-TEXT', false],
  ['M-EQPM', false],
  ['PDF _Геометрия', false],
  ['PDF2_Text', false],
  ['S_оси', false],
  ['S_перегородки', false],
  ['ОВ-Отопление', false],
  ['ОВ-Отопление-Изм. №3', true],
  ['ОВ-Отопление-Текст', false],
  ['ОВ-Вентиляция-Шахты-Изм. №1', true],
  ['АР-Стены', false],
];

/** PageView of AG-00's render service (getPageView) for the gold pages; F0202 also carries CAD layers. */
export function pageViewOf(fileId: string, page: number): PageView {
  const [wPt, hPt] = PAGE_PT[`${fileId}#${page}`] ?? [2384, 1684];
  const dpi = 150;
  const width = Math.round((wPt / 72) * dpi);
  const height = Math.round((hPt / 72) * dpi);
  const maxLevel = Math.ceil(Math.log2(Math.max(width, height)));
  const base = `/api/v1/files/${encodeURIComponent(fileId)}/pages/${page}`;
  return {
    file_id: fileId,
    object_id: TYUMEN,
    page_no: page,
    pdf_pages: fileId === 'F0171' ? 177 : fileId === 'F0201' ? 676 : 36,
    width_pt: wPt,
    height_pt: hPt,
    rotation: 0,
    max_dpi: dpi,
    width_px: width,
    height_px: height,
    tile_size: 512,
    tile_overlap: 0,
    min_level: Math.max(0, maxLevel - 6),
    max_level: maxLevel,
    tile_url_template: `${base}/tiles/{level}/{x}/{y}`,
    image_url: `${base}/image`,
    layers:
      fileId === 'F0202'
        ? LAYERS_F0202.map(([name, rev], i) => ({ number: i + 1, name, on: true, locked: false, is_revision: rev }))
        : undefined,
  };
}

export function annotationsOf(fileId: string, page: number): S['PageAnnotations'] {
  const layout = f0202Layout as unknown as {
    revision_clouds: Array<{ pdf_page_number: number; bbox: number[]; source: string; layer?: string; revision_label?: string; rooms_covered?: string[] }>;
    rooms: Array<{ pdf_page_number: number; room_token: string; bbox: number[]; name?: string | null }>;
  };
  if (fileId !== 'F0202') return { file_id: fileId, page, run_id: null, batch_run_id: null, revision_clouds: [], rooms: [] };
  return {
    file_id: fileId,
    page,
    run_id: RUN_IDS.tyumenV2,
    batch_run_id: 'd1-fixture-tyumen',
    revision_clouds: layout.revision_clouds
      .filter((c) => c.pdf_page_number === page)
      .map((c) => ({ bbox: c.bbox, source: c.source, layer: c.layer ?? null, revision_label: c.revision_label ?? null, rooms_covered: c.rooms_covered ?? [] })),
    rooms: layout.rooms.filter((r) => r.pdf_page_number === page).map((r) => ({ room_token: r.room_token, bbox: r.bbox, name: r.name ?? null })),
  };
}

export function filesOf(objectId: string): FileItem[] {
  if (objectId !== TYUMEN) return [];
  const base = (id: string, name: string, stage: FileItem['manifest_stage'], pages: number, sha: string): FileItem => ({
    file_id: id,
    object_id: TYUMEN,
    file_name: name,
    relative_path: `Пример нарушений на чертежах/${name}`,
    extension: '.pdf',
    size_bytes: pages * 180_000,
    pdf_pages: pages,
    sha256: sha,
    manifest_stage: stage,
    stage_resolved: stage === 'PD' ? 'PD' : 'RD',
    manifest_section: 'OV',
    dataset_role: 'GOLD_SEED',
    split: 'TRAIN_PUBLIC',
    annotation_status: 'LABELED',
    duplicate_group: null,
    local_status: 'PRESENT',
    sha256_verified: true,
    last_run_id: null,
    updated_at: TS,
  });
  return tyumen.input_registry.files.map((f) =>
    base(f.file_id, f.file_name ?? f.file_id, f.stage === 'PD' ? 'PD' : 'RD_ID_MIXED', f.pages ?? 1, f.sha256),
  );
}
