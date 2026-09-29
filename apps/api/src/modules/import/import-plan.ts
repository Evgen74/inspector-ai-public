/**
 * Pure mapping of validated run artifacts to table rows (no I/O): FindingGroup → evidence_groups (+ suspicions for
 * FREE_SEARCH), Finding → checks, EvidenceRef → evidence_fragments, Protocol → protocols, Submission → submission_exports.
 * The contract shapes were validated by RunArtifactsReader; the interfaces below only name the fields used.
 */
import { canonicalJson, sha256Hex } from '../../common/hashing';

export type StageValue = string | number | boolean | null;

export interface EvidenceRef {
  stage: string;
  file_id: string;
  pdf_page_number: number;
  document_sheet_number?: string | number | null;
  file_sha256?: string;
  page_basis?: string;
  role?: string;
  is_anchor?: boolean;
  geometry?: Record<string, unknown>;
  geometry_space?: string;
  localization?: string;
  document_code?: string | null;
  revision?: string | null;
  extracted_value_id?: string | null;
  note?: string | null;
}

export interface Recommendation {
  text: string;
  [k: string]: unknown;
}

export interface FindingGroupDoc {
  finding_group_id: string;
  object_id: string;
  matrix_scope: string;
  parameter_code: string;
  parameter_id?: number | null;
  parameter_mapping_status?: string;
  alt_parameter_codes?: string[];
  hedge_kind?: string | null;
  hedge_of_group_id?: string | null;
  title?: string | null;
  element_noun?: string | null;
  axis?: string;
  comparison_result: string;
  discrepancy_type?: string | null;
  location_type: string;
  locations: string[];
  pd_value?: StageValue;
  rd_value?: StageValue;
  id_value?: StageValue;
  violation_label: string;
  protocol_status: string;
  criticality: string | null;
  criticality_level?: string | null;
  finding_status?: string | null;
  risk_level?: string;
  confidence?: number;
  anchor_evidence: EvidenceRef[];
  evidence?: EvidenceRef[];
  location_pages?: Record<string, EvidenceRef[]>;
  finding_ids: string[];
  discovery_method?: string | null;
  evidence_bind_status?: string | null;
  rule_code?: string | null;
  rule_version?: string | null;
  rationale?: string | null;
  recommendation?: Recommendation | null;
  card_no?: string | null;
}

export interface FindingDoc {
  finding_id: string;
  finding_group_id?: string | null;
  object_id: string;
  matrix_scope: string;
  parameter_code: string;
  parameter_id?: number | null;
  parameter_mapping_status?: string;
  alt_parameter_codes?: string[];
  hedge_of_finding_id?: string | null;
  location: string;
  location_type: string;
  pd_value?: StageValue;
  rd_value?: StageValue;
  id_value?: StageValue;
  axis?: string;
  comparison_result?: string | null;
  discrepancy_type?: string | null;
  violation_type?: string | null;
  completeness_status?: string;
  completeness_basis?: string | null;
  finding_status?: string | null;
  inspector_status?: string | null;
  violation_label: string;
  protocol_status: string;
  criticality: string | null;
  criticality_level?: string | null;
  review_priority?: string;
  risk_level?: string;
  document_status?: string | null;
  confidence?: number;
  evidence: EvidenceRef[];
  hedge_kind?: string | null;
  element_noun?: string | null;
  discovery_method?: string | null;
  evidence_bind_status?: string | null;
  recommendation?: Recommendation | null;
  card_no?: string | null;
  rule_code?: string | null;
  rule_version?: string | null;
  sub_id?: string | null;
  delta?: Record<string, unknown> | null;
  rationale?: string | null;
  decision_trace?: Record<string, unknown> | null;
}

export interface ProtocolDoc {
  protocol_no: string;
  version: number;
  is_final: boolean;
  status: string;
  generated_at: string;
  scenario: string;
  scenario_base?: string | null;
  upload_status?: Record<string, unknown>;
  versions: { pipeline_version: string; matrix_version?: string | null; dataset_version?: string | null; model_version?: string | null; engine_versions?: Record<string, string> };
  input_manifest_hash: string;
  appendix2: {
    section2_summary?: unknown;
    section6_ai_suspicions?: {
      rows?: Array<{ finding_group_id?: string | null; method?: string | null; description?: string; card_ref?: string; confidence?: number }>;
    };
    [k: string]: unknown;
  };
  [k: string]: unknown;
}

export interface SubmissionDoc {
  object_id: string;
  checks: unknown[];
}

export interface PlannedGroup {
  evidenceGroupId: string;
  row: Record<string, unknown>;
  groupSha256: string;
  isFree: boolean;
}

export interface PlannedCheck {
  findingId: string;
  groupId: string | null;
  isFree: boolean;
  findingSha256: string;
  /** Machine columns (rewritten on every import). */
  row: Record<string, unknown>;
  /** InspectorStatus set only when the check is first inserted. */
  inspectorStatusOnInsert: string | null;
}

export interface PlannedFragment {
  fragmentKey: string;
  findingId: string | null;
  evidenceGroupId: string | null;
  /** FREE-* group fragments are bound to the group's suspicion. */
  suspicionKey: string | null;
  row: Record<string, unknown>;
}

export interface PlannedSuspicion {
  suspicionKey: string;
  findingIds: string[];
  row: Record<string, unknown>;
  /** CONVERTED_TO_CANDIDATE when its checks were created (bound evidence), else PENDING (set on insert only). */
  inspectorStatusOnInsert: string;
  promotedBy: string | null;
}

export function sha256OfJson(value: unknown): string {
  return sha256Hex(canonicalJson(value));
}

/** The reference and the checked stage value of a check, by comparison axis (ТЗ key fields expected/actual). */
export function expectedActual(f: Pick<FindingDoc, 'axis' | 'pd_value' | 'rd_value' | 'id_value'>): [StageValue, StageValue] {
  const pd = f.pd_value ?? null;
  const rd = f.rd_value ?? null;
  const id = f.id_value ?? null;
  switch (f.axis) {
    case 'RD_ID':
      return [rd, id];
    case 'PD_ID':
      return [pd, id];
    case 'NORM_PD':
      return [null, pd];
    case 'NORM_RD':
      return [null, rd];
    case 'NORM_ID':
      return [null, id];
    default:
      return [pd, rd];
  }
}

/** «л. 4 / стр. 18» (90 §3.3.6 sheet_page), or «стр. 18» without a printed sheet number. */
export function sheetPage(ref: EvidenceRef): string {
  const sheet = ref.document_sheet_number;
  return sheet === undefined || sheet === null || sheet === '' ? `стр. ${ref.pdf_page_number}` : `л. ${sheet} / стр. ${ref.pdf_page_number}`;
}

function refText(ref: EvidenceRef | undefined): string | null {
  return ref ? `${ref.file_id}, ${sheetPage(ref)}` : null;
}

function jsonValue(v: StageValue | undefined): StageValue {
  return v === undefined ? null : v;
}

export function planGroup(g: FindingGroupDoc): PlannedGroup {
  return {
    evidenceGroupId: g.finding_group_id,
    isFree: g.matrix_scope === 'FREE_SEARCH',
    groupSha256: sha256OfJson(g),
    row: {
      objectId: g.object_id,
      matrixScope: g.matrix_scope,
      paramId: g.parameter_id ?? null,
      paramCode: g.parameter_code,
      parameterMappingStatus: g.parameter_mapping_status ?? null,
      altParamCodes: g.alt_parameter_codes ?? [],
      hedgeKind: g.hedge_kind ?? null,
      hedgeOfGroupId: g.hedge_of_group_id ?? null,
      title: g.title ?? null,
      elementNoun: g.element_noun ?? null,
      axis: g.axis ?? null,
      comparisonResult: g.comparison_result,
      discrepancyType: g.discrepancy_type ?? null,
      locationType: g.location_type,
      locations: g.locations,
      pdValue: jsonValue(g.pd_value),
      rdValue: jsonValue(g.rd_value),
      idValue: jsonValue(g.id_value),
      violationLabel: g.violation_label,
      protocolStatus: g.protocol_status,
      criticality: g.criticality,
      criticalityLevel: g.criticality_level ?? null,
      findingStatus: g.finding_status ?? null,
      riskLevel: g.risk_level ?? null,
      confidence: g.confidence ?? null,
      anchorEvidence: g.anchor_evidence,
      locationPages: g.location_pages ?? null,
      findingIds: g.finding_ids,
      discoveryMethod: g.discovery_method ?? null,
      evidenceBindStatus: g.evidence_bind_status ?? null,
      ruleCode: g.rule_code ?? null,
      ruleVersion: g.rule_version ?? null,
      rationale: g.rationale ?? null,
      recommendation: g.recommendation ?? null,
      cardNo: g.card_no ?? null,
      groupJson: g,
    },
  };
}

export function planCheck(f: FindingDoc): PlannedCheck {
  const [expected, actual] = expectedActual(f);
  const isFree = f.matrix_scope === 'FREE_SEARCH';
  return {
    findingId: f.finding_id,
    groupId: f.finding_group_id ?? null,
    isFree,
    findingSha256: sha256OfJson(f),
    inspectorStatusOnInsert: f.inspector_status ?? (f.violation_label === 'VIOLATION_PRESENT' ? 'PENDING' : null),
    row: {
      paramId: f.parameter_id ?? null,
      objectId: f.object_id,
      expectedValue: expected,
      actualValue: actual,
      completenessStatus: f.completeness_status ?? null,
      findingStatus: f.finding_status ?? null,
      reviewPriority: f.review_priority ?? null,
      evidenceGroupId: f.finding_group_id ?? null,
      kind: isFree ? 'SUSPICION_CONVERTED' : 'MATRIX',
      matrixScope: f.matrix_scope,
      paramCode: f.parameter_code,
      subId: f.sub_id ?? null,
      ruleCode: f.rule_code ?? null,
      ruleVersion: f.rule_version ?? null,
      parameterMappingStatus: f.parameter_mapping_status ?? null,
      altParamCodes: f.alt_parameter_codes ?? [],
      hedgeOfFindingId: f.hedge_of_finding_id ?? null,
      hedgeKind: f.hedge_kind ?? null,
      location: f.location,
      locationType: f.location_type,
      pdValue: jsonValue(f.pd_value),
      rdValue: jsonValue(f.rd_value),
      idValue: jsonValue(f.id_value),
      axis: f.axis ?? null,
      comparisonResult: f.comparison_result ?? null,
      discrepancyType: f.discrepancy_type ?? null,
      violationType: f.violation_type ?? null,
      completenessBasis: f.completeness_basis ?? null,
      violationLabel: f.violation_label,
      protocolStatus: f.protocol_status,
      criticality: f.criticality,
      criticalityLevel: f.criticality_level ?? null,
      riskLevel: f.risk_level ?? null,
      documentStatus: f.document_status ?? null,
      confidence: f.confidence ?? null,
      elementNoun: f.element_noun ?? null,
      discoveryMethod: f.discovery_method ?? null,
      evidenceBindStatus: f.evidence_bind_status ?? null,
      recommendation: f.recommendation ?? null,
      cardNo: f.card_no ?? null,
      delta: f.delta ?? null,
      rationale: f.rationale ?? null,
      decisionTrace: f.decision_trace ?? null,
      findingJson: f,
    },
  };
}

function fragment(
  ref: EvidenceRef,
  scope: { evidenceGroupId: string | null; findingId: string | null; location: string | null; suspicionKey: string | null; anchor?: boolean },
): PlannedFragment {
  const isAnchor = scope.anchor ?? Boolean(ref.is_anchor);
  const fragmentKey = sha256OfJson({ g: scope.evidenceGroupId, f: scope.findingId, l: scope.location, a: isAnchor, r: ref });
  return {
    fragmentKey,
    findingId: scope.findingId,
    evidenceGroupId: scope.evidenceGroupId,
    suspicionKey: scope.suspicionKey,
    row: {
      evidenceGroupId: scope.evidenceGroupId,
      fileId: ref.file_id,
      stage: ref.stage,
      sheetPage: sheetPage(ref),
      bboxPolygonNorm: ref.geometry ?? null,
      extractedValue: null,
      roleExpectedActual: ref.role ?? null,
      findingId: scope.findingId,
      location: scope.location,
      isAnchor,
      fileSha256: ref.file_sha256 ?? null,
      pageNo: ref.pdf_page_number,
      sheetNo: ref.document_sheet_number === undefined || ref.document_sheet_number === null ? null : String(ref.document_sheet_number),
      pageBasis: ref.page_basis ?? null,
      geometrySpace: ref.geometry_space ?? null,
      localization: ref.localization ?? null,
      documentCode: ref.document_code ?? null,
      revision: ref.revision ?? null,
      extractedValueId: ref.extracted_value_id ?? null,
      note: ref.note ?? null,
      origin: 'SYSTEM',
    },
  };
}

interface ProtocolOnlySuspicion {
  suspicionKey: string;
  objectId: string;
  row: { method?: string | null; description?: string; card_ref?: string; confidence?: number };
  card: { parameter_code?: string; review_priority?: string; rationale?: string | null; sources?: Array<Record<string, unknown>> };
  refs: EvidenceRef[];
}

/**
 * Suspicions that exist only in Раздел 6 (no FREE finding group; e.g. contradicting values inside one stage, AG-07):
 * a row without ``finding_group_id`` plus its evidence card (Приложение Б) with the cited file pages.
 */
function protocolOnlySuspicions(protocol: ProtocolDoc | null): ProtocolOnlySuspicion[] {
  if (!protocol) return [];
  const objectId = (protocol.object as { object_id?: string } | undefined)?.object_id;
  const cards = (protocol.evidence_cards as Array<{ card_no?: string } & Record<string, unknown>> | undefined) ?? [];
  const out: ProtocolOnlySuspicion[] = [];
  for (const row of protocol.appendix2.section6_ai_suspicions?.rows ?? []) {
    if (row.finding_group_id || !row.card_ref || !objectId) continue;
    const card = cards.find((c) => c.card_no === row.card_ref) as ProtocolOnlySuspicion['card'] | undefined;
    if (!card?.sources?.length) continue;
    const refs = card.sources.map(
      (src) =>
        ({
          stage: src.stage,
          file_id: src.file_id,
          pdf_page_number: src.pdf_page_number,
          document_sheet_number: src.sheet_number ?? null,
          file_sha256: src.file_sha256 ?? null,
          geometry: src.geometry ?? null,
          geometry_space: src.geometry_space ?? null,
          document_code: src.document_code ?? null,
          revision: src.revision ?? null,
        }) as unknown as EvidenceRef,
    );
    const suspicionKey = `${objectId}-SUSP-${sha256OfJson({ objectId, description: row.description ?? '' }).slice(0, 16)}`;
    out.push({ suspicionKey, objectId, row, card, refs });
  }
  return out;
}

/** Fragments of a group (anchor pages, supporting evidence, per-location pages) and of its atomic findings. */
export function planFragments(groups: FindingGroupDoc[], findings: FindingDoc[], protocol: ProtocolDoc | null = null): PlannedFragment[] {
  const out = new Map<string, PlannedFragment>();
  const add = (p: PlannedFragment) => out.set(p.fragmentKey, p);
  for (const g of groups) {
    const suspicionKey = g.matrix_scope === 'FREE_SEARCH' ? g.finding_group_id : null;
    for (const ref of g.anchor_evidence) add(fragment(ref, { evidenceGroupId: g.finding_group_id, findingId: null, location: null, suspicionKey, anchor: true }));
    for (const ref of g.evidence ?? []) add(fragment(ref, { evidenceGroupId: g.finding_group_id, findingId: null, location: null, suspicionKey }));
    for (const [location, refs] of Object.entries(g.location_pages ?? {})) {
      for (const ref of refs) add(fragment(ref, { evidenceGroupId: g.finding_group_id, findingId: null, location, suspicionKey }));
    }
  }
  for (const f of findings) {
    for (const ref of f.evidence) {
      add(fragment(ref, { evidenceGroupId: f.finding_group_id ?? null, findingId: f.finding_id, location: f.location, suspicionKey: null }));
    }
  }
  for (const p of protocolOnlySuspicions(protocol)) {
    for (const ref of p.refs) add(fragment(ref, { evidenceGroupId: null, findingId: null, location: null, suspicionKey: p.suspicionKey, anchor: false }));
  }
  return [...out.values()];
}

/** FREE_SEARCH groups become suspicions (Приложение 2 §6); their atomic checks are the converted candidates. */
export function planSuspicions(groups: FindingGroupDoc[], findings: FindingDoc[], protocol: ProtocolDoc | null): PlannedSuspicion[] {
  const rows = new Map(
    (protocol?.appendix2.section6_ai_suspicions?.rows ?? [])
      .filter((r) => r.finding_group_id)
      .map((r) => [r.finding_group_id as string, r]),
  );
  const findingIds = new Set(findings.map((f) => f.finding_id));
  const protocolOnly: PlannedSuspicion[] = protocolOnlySuspicions(protocol).map((p) => ({
    suspicionKey: p.suspicionKey,
    findingIds: [],
    inspectorStatusOnInsert: 'PENDING',
    promotedBy: null,
    row: {
      objectId: p.objectId,
      discoveryMethod: p.row.method ?? null,
      confidence: p.row.confidence ?? null,
      description: p.row.description ?? p.card.rationale ?? p.suspicionKey,
      paramCode: p.card.parameter_code ?? null,
      evidenceStatus: p.refs.every((r) => r.geometry) ? 'BOUND' : 'PARTIAL',
      expectedValue: null,
      actualValue: null,
      pdReference: refText(p.refs.find((r) => r.stage === 'PD')),
      rdReference: refText(p.refs.find((r) => r.stage === 'RD')),
      idReference: refText(p.refs.find((r) => r.stage === 'ID')),
      reviewPriority: p.card.review_priority ?? null,
      explanation: { kind: 'VALUE_CONFLICT', section6_row: p.row, evidence_card: p.card },
    },
  }));
  return [...planFreeSuspicions(groups, findings, rows, findingIds), ...protocolOnly];
}

function planFreeSuspicions(
  groups: FindingGroupDoc[],
  findings: FindingDoc[],
  rows: Map<string, { finding_group_id?: string | null; method?: string | null; description?: string }>,
  findingIds: Set<string>,
): PlannedSuspicion[] {
  void findings;
  return groups
    .filter((g) => g.matrix_scope === 'FREE_SEARCH')
    .map((g) => {
      const row = rows.get(g.finding_group_id);
      const own = g.finding_ids.filter((id) => findingIds.has(id));
      const converted = own.length > 0 && g.evidence_bind_status === 'BOUND';
      const pd = g.anchor_evidence.find((r) => r.stage === 'PD');
      const rd = g.anchor_evidence.find((r) => r.stage === 'RD');
      const id = g.anchor_evidence.find((r) => r.stage === 'ID');
      return {
        suspicionKey: g.finding_group_id,
        findingIds: own,
        inspectorStatusOnInsert: converted ? 'CONVERTED_TO_CANDIDATE' : 'PENDING',
        promotedBy: converted ? 'SYSTEM' : null,
        row: {
          objectId: g.object_id,
          discoveryMethod: g.discovery_method ?? row?.method ?? null,
          confidence: g.confidence ?? null,
          description: g.title ?? row?.description ?? g.rationale ?? `${g.parameter_code}: ${g.locations.join(', ')}`,
          paramCode: g.parameter_code,
          evidenceStatus: g.evidence_bind_status ?? null,
          expectedValue: jsonValue(g.pd_value),
          actualValue: jsonValue(g.rd_value),
          pdReference: refText(pd),
          rdReference: refText(rd),
          idReference: refText(id),
          reviewPriority: g.risk_level ?? null,
          explanation: g,
        },
      };
    });
}

/** Referential checks between the artifacts of one object (warnings, not contract failures). */
export function crossCheck(
  objectId: string,
  groups: FindingGroupDoc[],
  findings: FindingDoc[],
  objectFileIds: ReadonlySet<string>,
): { errors: string[]; warnings: Array<{ code: string; details: Record<string, unknown> }> } {
  const errors: string[] = [];
  const warnings: Array<{ code: string; details: Record<string, unknown> }> = [];
  const groupIds = new Set<string>();
  for (const g of groups) {
    if (g.object_id !== objectId) errors.push(`группа ${g.finding_group_id} относится к объекту ${g.object_id}, а файл — к ${objectId}`);
    if (groupIds.has(g.finding_group_id)) errors.push(`группа ${g.finding_group_id} указана дважды`);
    groupIds.add(g.finding_group_id);
  }
  const findingIds = new Set<string>();
  for (const f of findings) {
    if (f.object_id !== objectId) errors.push(`находка ${f.finding_id} относится к объекту ${f.object_id}, а файл — к ${objectId}`);
    if (findingIds.has(f.finding_id)) errors.push(`находка ${f.finding_id} указана дважды`);
    findingIds.add(f.finding_id);
    if (f.finding_group_id && groups.length && !groupIds.has(f.finding_group_id)) {
      errors.push(`находка ${f.finding_id} ссылается на отсутствующую группу ${f.finding_group_id}`);
    }
  }
  const cited = new Set<string>();
  for (const g of groups) {
    for (const r of [...g.anchor_evidence, ...(g.evidence ?? []), ...Object.values(g.location_pages ?? {}).flat()]) cited.add(r.file_id);
  }
  for (const f of findings) for (const r of f.evidence) cited.add(r.file_id);
  if (objectFileIds.size) {
    for (const fileId of [...cited].sort()) {
      if (!objectFileIds.has(fileId)) warnings.push({ code: 'EVIDENCE_FILE_UNKNOWN', details: { object_id: objectId, file_id: fileId } });
    }
  }
  return { errors, warnings };
}
