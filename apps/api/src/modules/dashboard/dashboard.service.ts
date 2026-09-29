/**
 * Dashboard (ТЗ §7 модуль 7; 08 §3.5–3.6 S-02): every object with its colour computed from the latest
 * protocol by the strict rule (indicator.ts), tiles per colour, filters by section, inspector decision,
 * scenario and protocol date, and the findings-by-section summary.
 *
 * The colour is computed on read from the run artifacts (a handful of objects in D1; each protocol read is
 * cached by mtime). AG-05's decisions will be applied through `DecisionOverlay` (same function).
 */
import { Injectable } from '@nestjs/common';
import { CatalogLookup, type ObjectRecord } from '../shared/lookup.repository';
import { type LoadedProtocol, ProtocolsService, isHiddenSplit, type ProtocolVersionDto } from '../protocols/protocols.service';
import {
  computeIndicator,
  emptyCounters,
  type FindingCounters,
  type Indicator,
  type IndicatorColor,
  tallyProtocol,
} from './indicator';

export interface DashboardQuery {
  q?: string;
  color?: IndicatorColor[];
  section?: string[];
  status?: string[];
  scenario?: string;
  dateFrom?: string;
  dateTo?: string;
  /** Archived objects («Архивировать») are hidden unless true. */
  includeArchived?: boolean;
}

export interface DashboardObjectDto {
  object_id: string;
  name: string | null;
  split: string | null;
  indicator: Indicator;
  latest_protocol: ProtocolVersionDto | null;
  counters: FindingCounters;
  sections: string[];
  upload_status: { pd: string | null; rd: string | null; id: string | null };
  files_total: number;
  updated_at: string;
}

export interface SectionSummaryDto {
  section_ru: string;
  confirmed: number;
  pending: number;
  clarification: number;
  rejected: number;
  suspicions: number;
}

export interface DashboardDto {
  generated_at: string;
  tiles: { total: number; RED: number; YELLOW: number; GREEN: number; NONE: number; awaiting_decision: number };
  items: DashboardObjectDto[];
  sections: SectionSummaryDto[];
}

/** Label of suspicions (FREE-*, outside the 132-parameter matrix) in the section summary. */
export const OUTSIDE_MATRIX_SECTION = 'Вне матрицы';

/** Calendar date (YYYY-MM-DD) of an instant in Europe/Moscow (UTC+3, no DST). */
export function moscowDate(iso: string): string {
  return new Date(Date.parse(iso) + 3 * 3600_000).toISOString().slice(0, 10);
}

/** The protocol's own object name (what the inspector reads in the document) beats the registry's technical label. */
function displayName(object: ObjectRecord, loaded: LoadedProtocol | null): string | null {
  // An uploaded set carries the name the user typed in the form: it stays.
  if (object.objectId.startsWith('OBJ-UPLOAD-') && object.name) return object.name;
  const fromProtocol = loaded?.protocol.object.name?.trim();
  return fromProtocol || object.name;
}

interface Row {
  object: ObjectRecord;
  loaded: LoadedProtocol | null;
  dto: DashboardObjectDto;
  statuses: Array<{ section_ru: string; status: string }>;
  bySection: Map<string, { confirmed: number; pending: number; clarification: number; rejected: number }>;
}

@Injectable()
export class DashboardService {
  constructor(
    private readonly lookup: CatalogLookup,
    private readonly protocols: ProtocolsService,
  ) {}

  private async row(object: ObjectRecord): Promise<Row> {
    const hidden = isHiddenSplit(object.split);
    // Hidden-test objects: inventory only, their artifacts are never read (CLAUDE.md rule 4).
    const loaded = hidden ? null : await this.protocols.latest(object.objectId);
    // Live decisions of the verification (AG-05) override the protocol's own status: a confirmation turns red.
    const decisions = loaded ? await this.lookup.decisionsForRun(object.objectId, loaded.run.id) : undefined;
    const tally = loaded ? tallyProtocol(loaded.protocol as never, decisions) : null;
    const counters = tally?.counters ?? emptyCounters();
    const indicator = computeIndicator({
      hasProtocol: loaded !== null,
      hiddenInventoryOnly: hidden,
      scenario: loaded?.protocol.scenario ?? null,
      counters,
    });
    const upload = loaded?.protocol.upload_status ?? {};
    const sections = tally ? [...tally.bySection.keys()].sort((a, b) => a.localeCompare(b, 'ru')) : [];
    return {
      object,
      loaded,
      statuses: tally?.statuses ?? [],
      bySection: tally?.bySection ?? new Map(),
      dto: {
        object_id: object.objectId,
        name: displayName(object, loaded),
        split: object.split,
        indicator,
        latest_protocol: loaded?.version ?? null,
        counters,
        sections,
        upload_status: { pd: upload.pd ?? null, rd: upload.rd ?? null, id: upload.id ?? null },
        files_total: object.filesTotal,
        updated_at: (loaded ? new Date(loaded.protocol.generated_at) : object.updatedAt).toISOString(),
      },
    };
  }

  /**
   * The colour and scenario of one object by the very same computation as the dashboard rows (one function
   * for the dashboard, the objects list and the object header). null when the object does not exist.
   */
  async indicatorOf(
    objectId: string,
  ): Promise<{ color: IndicatorColor; scenario: string | null; name: string | null; address: string | null } | null> {
    const object = await this.lookup.getObject(objectId);
    if (!object) return null;
    const { dto, loaded } = await this.row(object);
    const o = loaded?.protocol.object as { name?: string | null; address?: string | null } | undefined;
    return {
      color: dto.indicator.color,
      scenario: loaded?.protocol.scenario ?? null,
      name: dto.name,
      address: o?.address ?? null,
    };
  }

  async dashboard(query: DashboardQuery): Promise<DashboardDto> {
    const objects = await this.lookup.listObjects(query.includeArchived === true);
    const rows = await Promise.all(objects.map((o) => this.row(o)));
    const q = query.q?.toLowerCase();
    const sections = query.section?.length ? new Set(query.section) : null;
    const statuses = query.status?.length ? new Set(query.status) : null;
    const filtered = rows.filter((r) => {
      if (q && !r.object.objectId.toLowerCase().includes(q) && !(r.object.name ?? '').toLowerCase().includes(q)) {
        return false;
      }
      if (query.scenario && r.loaded?.protocol.scenario !== query.scenario) return false;
      if (query.dateFrom || query.dateTo) {
        if (!r.loaded) return false;
        const day = moscowDate(r.loaded.protocol.generated_at);
        if (query.dateFrom && day < query.dateFrom) return false;
        if (query.dateTo && day > query.dateTo) return false;
      }
      if (sections || statuses) {
        // «Объекты, у которых есть находки выбранных статусов в выбранных разделах» (08 §3.6 S-02).
        const hit = r.statuses.some(
          (s) => (!sections || sections.has(s.section_ru)) && (!statuses || statuses.has(s.status)),
        );
        if (!hit) return false;
      }
      return true;
    });
    const tiles = { total: filtered.length, RED: 0, YELLOW: 0, GREEN: 0, NONE: 0, awaiting_decision: 0 };
    for (const r of filtered) {
      tiles[r.dto.indicator.color] += 1;
      tiles.awaiting_decision += r.dto.counters.pending + r.dto.counters.clarification;
    }
    const colors = query.color?.length ? new Set(query.color) : null;
    const visible = colors ? filtered.filter((r) => colors.has(r.dto.indicator.color)) : filtered;
    const bySection = new Map<string, SectionSummaryDto>();
    for (const r of visible) {
      for (const [section, c] of r.bySection) {
        const s = bySection.get(section) ?? {
          section_ru: section,
          confirmed: 0,
          pending: 0,
          clarification: 0,
          rejected: 0,
          suspicions: 0,
        };
        s.confirmed += c.confirmed;
        s.pending += c.pending;
        s.clarification += c.clarification;
        s.rejected += c.rejected;
        bySection.set(section, s);
      }
      if (r.dto.counters.suspicions > 0) {
        const s = bySection.get(OUTSIDE_MATRIX_SECTION) ?? {
          section_ru: OUTSIDE_MATRIX_SECTION,
          confirmed: 0,
          pending: 0,
          clarification: 0,
          rejected: 0,
          suspicions: 0,
        };
        s.suspicions += r.dto.counters.suspicions;
        bySection.set(OUTSIDE_MATRIX_SECTION, s);
      }
    }
    const order = (s: string) => (s === OUTSIDE_MATRIX_SECTION ? 1 : 0);
    return {
      generated_at: new Date().toISOString(),
      tiles,
      items: visible.map((r) => r.dto),
      sections: [...bySection.values()].sort(
        (a, b) => order(a.section_ru) - order(b.section_ru) || a.section_ru.localeCompare(b.section_ru, 'ru'),
      ),
    };
  }
}
