/**
 * Object colour indication (ТЗ §7 модуль 7; 08 §3.5, strict rule). Pure functions, no framework imports: the
 * web mocks import this file too, so the dashboard, its tooltips and the mocks can never disagree.
 *
 *   RED    ⇐ at least one CONFIRMED_VIOLATION (only an inspector's confirmation turns an object red);
 *   YELLOW ⇐ an inspector action or data is needed: candidates awaiting a decision, clarification required,
 *            missing mandatory evidence, not comparable, partial upload, no registry;
 *   GREEN  ⇐ none of the above (all candidates decided as NEGATIVE_VERIFIED / not applicable, complete set);
 *   NONE   ⇐ no protocol yet (or an object of the hidden split: inventory only).
 *
 * Risk level / review priority and AI suspicions never change the colour (ТЗ §9.2: «уровень риска … не равен
 * статусу нарушения»; §9.5: подозрения не входят в число нарушений).
 */

export type IndicatorColor = 'RED' | 'YELLOW' | 'GREEN' | 'NONE';

export type IndicatorReasonCode =
  | 'CONFIRMED_VIOLATIONS'
  | 'CANDIDATES_PENDING'
  | 'CLARIFICATION_REQUIRED'
  | 'MISSING_EVIDENCE'
  | 'NOT_COMPARABLE'
  | 'PARTIAL_UPLOAD'
  | 'REGISTRY_MISSING'
  | 'NO_VIOLATIONS_COMPLETE'
  | 'NO_PROTOCOL'
  | 'HIDDEN_TEST_INVENTORY_ONLY';

export interface IndicatorReason {
  code: IndicatorReasonCode;
  count: number;
  text: string;
}

export interface Indicator {
  color: IndicatorColor;
  reasons: IndicatorReason[];
}

export interface FindingCounters {
  confirmed: number;
  pending: number;
  /** Pending groups of criticality «Критическое» (shown in the tooltip only; never changes the colour). */
  pending_high: number;
  clarification: number;
  rejected: number;
  missing_evidence: number;
  not_comparable: number;
  suspicions: number;
  suspicions_pending: number;
}

export interface IndicatorInput {
  hasProtocol: boolean;
  hiddenInventoryOnly?: boolean;
  /** LoadScenario of the latest protocol. */
  scenario?: string | null;
  registryMissing?: boolean;
  counters: FindingCounters;
}

export function emptyCounters(): FindingCounters {
  return {
    confirmed: 0,
    pending: 0,
    pending_high: 0,
    clarification: 0,
    rejected: 0,
    missing_evidence: 0,
    not_comparable: 0,
    suspicions: 0,
    suspicions_pending: 0,
  };
}

const pluralRules = new Intl.PluralRules('ru-RU');

export function pluralRu(n: number, forms: [one: string, few: string, many: string]): string {
  const rule = pluralRules.select(n);
  return rule === 'one' ? forms[0] : rule === 'few' ? forms[1] : forms[2];
}

const n = (value: number, forms: [string, string, string]) => `${value} ${pluralRu(value, forms)}`;

export function computeIndicator(input: IndicatorInput): Indicator {
  if (input.hiddenInventoryOnly) {
    return {
      color: 'NONE',
      reasons: [{ code: 'HIDDEN_TEST_INVENTORY_ONLY', count: 0, text: 'Скрытая тестовая выборка: только инвентаризация' }],
    };
  }
  if (!input.hasProtocol) {
    return { color: 'NONE', reasons: [{ code: 'NO_PROTOCOL', count: 0, text: 'Нет результата: протокол не сформирован' }] };
  }
  const c = input.counters;
  if (c.confirmed > 0) {
    return {
      color: 'RED',
      reasons: [
        {
          code: 'CONFIRMED_VIOLATIONS',
          count: c.confirmed,
          text: `Подтверждено инспектором: ${n(c.confirmed, ['нарушение', 'нарушения', 'нарушений'])}`,
        },
      ],
    };
  }
  const reasons: IndicatorReason[] = [];
  if (c.pending > 0) {
    const high = c.pending_high > 0 ? ` (критических: ${c.pending_high})` : '';
    reasons.push({
      code: 'CANDIDATES_PENDING',
      count: c.pending,
      text: `Ожидают решения инспектора: ${n(c.pending, ['кандидат', 'кандидата', 'кандидатов'])}${high}`,
    });
  }
  if (c.clarification > 0) {
    reasons.push({
      code: 'CLARIFICATION_REQUIRED',
      count: c.clarification,
      text: `Требуют уточнения: ${c.clarification}`,
    });
  }
  if (c.missing_evidence > 0) {
    reasons.push({
      code: 'MISSING_EVIDENCE',
      count: c.missing_evidence,
      text: `Нет обязательных документов: ${n(c.missing_evidence, ['параметр', 'параметра', 'параметров'])}`,
    });
  }
  if (c.not_comparable > 0) {
    reasons.push({
      code: 'NOT_COMPARABLE',
      count: c.not_comparable,
      text: `Сравнение невозможно: ${n(c.not_comparable, ['параметр', 'параметра', 'параметров'])}`,
    });
  }
  if (input.scenario === 'PARTIALLY_LOADED') {
    reasons.push({ code: 'PARTIAL_UPLOAD', count: 0, text: 'Комплект документов загружен частично' });
  }
  if (input.registryMissing) {
    reasons.push({ code: 'REGISTRY_MISSING', count: 0, text: 'Нет реестра файлов (статус CLARIFICATION_REQUIRED)' });
  }
  if (reasons.length > 0) return { color: 'YELLOW', reasons };
  return {
    color: 'GREEN',
    reasons: [{ code: 'NO_VIOLATIONS_COMPLETE', count: 0, text: 'Нарушений не выявлено; комплект полный' }],
  };
}

// ── Counters from the protocol contract (protocol.schema.json) ──

interface RowLike {
  inspector_status?: string;
  criticality_level?: string | null;
  card_ref?: string;
  finding_group_id?: string | null;
  section_ru?: string;
}

interface ProtocolLike {
  appendix2: {
    section4_critical: { rows: RowLike[] };
    section5_substantial: { rows: RowLike[] };
    section6_ai_suspicions: { rows: RowLike[] };
  };
  tz92_tables?: {
    a1_completeness?: Array<{ completeness_status?: string; protocol_status?: string }>;
    a4_negative_verified?: Array<{ card_ref?: string | null; decided_by?: string }>;
  };
}

/**
 * Effective inspector status per finding group: the protocol's own status, overridden by web decisions
 * (AG-05, keyed by finding_group_id, then card_ref) when they exist.
 */
export type DecisionOverlay = ReadonlyMap<string, string>;

function effectiveStatus(row: RowLike, decisions?: DecisionOverlay): string {
  const byGroup = row.finding_group_id ? decisions?.get(row.finding_group_id) : undefined;
  const byCard = row.card_ref ? decisions?.get(row.card_ref) : undefined;
  return byGroup ?? byCard ?? row.inspector_status ?? 'PENDING';
}

export interface ProtocolTally {
  counters: FindingCounters;
  /** Per matrix section (section_ru of Разделы 4–5): counters by inspector decision. */
  bySection: Map<string, { confirmed: number; pending: number; clarification: number; rejected: number }>;
  /** Inspector statuses present among the finding groups, per section. */
  statuses: Array<{ section_ru: string; status: string }>;
}

export function tallyProtocol(protocol: ProtocolLike, decisions?: DecisionOverlay): ProtocolTally {
  const counters = emptyCounters();
  const bySection: ProtocolTally['bySection'] = new Map();
  const statuses: ProtocolTally['statuses'] = [];
  const rejectedCards = new Set<string>();
  const rows = [
    ...protocol.appendix2.section4_critical.rows.map((r) => ({ row: r, critical: true })),
    ...protocol.appendix2.section5_substantial.rows.map((r) => ({ row: r, critical: false })),
  ];
  for (const { row, critical } of rows) {
    const status = effectiveStatus(row, decisions);
    const section = row.section_ru ?? '—';
    const bucket = bySection.get(section) ?? { confirmed: 0, pending: 0, clarification: 0, rejected: 0 };
    statuses.push({ section_ru: section, status });
    switch (status) {
      case 'CONFIRMED_VIOLATION':
        counters.confirmed += 1;
        bucket.confirmed += 1;
        break;
      case 'NEGATIVE_VERIFIED':
        counters.rejected += 1;
        bucket.rejected += 1;
        if (row.card_ref) rejectedCards.add(row.card_ref);
        break;
      case 'CLARIFICATION_REQUIRED':
        counters.clarification += 1;
        bucket.clarification += 1;
        break;
      default:
        counters.pending += 1;
        bucket.pending += 1;
        if (critical || row.criticality_level === 'CRITICAL_SUSPEND') counters.pending_high += 1;
    }
    bySection.set(section, bucket);
  }
  // Rejected matrix findings live in А.4 (Разделы 4–5 list the violations only).
  for (const neg of protocol.tz92_tables?.a4_negative_verified ?? []) {
    if (neg.decided_by === 'INSPECTOR' && !(neg.card_ref && rejectedCards.has(neg.card_ref))) counters.rejected += 1;
  }
  for (const row of protocol.tz92_tables?.a1_completeness ?? []) {
    const status =
      row.completeness_status ??
      (row.protocol_status && ['PD_MISSING', 'RD_MISSING', 'ID_MISSING'].includes(row.protocol_status)
        ? 'MISSING_EVIDENCE'
        : row.protocol_status === 'COMPARISON_IMPOSSIBLE'
          ? 'NOT_COMPARABLE'
          : undefined);
    if (status === 'MISSING_EVIDENCE') counters.missing_evidence += 1;
    else if (status === 'NOT_COMPARABLE') counters.not_comparable += 1;
    else if (status === 'CLARIFICATION_REQUIRED') counters.clarification += 1;
  }
  for (const row of protocol.appendix2.section6_ai_suspicions.rows) {
    counters.suspicions += 1;
    const status = effectiveStatus(row, decisions);
    if (status === 'PENDING' || status === 'CLARIFICATION_REQUIRED') counters.suspicions_pending += 1;
  }
  return { counters, bySection, statuses };
}
