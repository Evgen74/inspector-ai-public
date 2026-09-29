/**
 * Pure verification rules (AG-05): decision body rules, the 90 §3.2.4 action mapping, process transitions, the
 * finalize gate, the AI rejection validator, the ТЗ §9.4 wording, the FINAL protocol snapshot and GOLD records —
 * checked against the contract JSON Schemas where one exists.
 */
import { describe, expect, it } from 'vitest';
import { loadEnums } from '../../src/contracts/contracts';
import { canonicalJson, sha256Hex } from '../../src/common/hashing';
import { DecisionCodes } from '../../src/modules/verification/domain/codes';
import { datasetSplit, goldLabelOf, goldRecord } from '../../src/modules/verification/domain/gold';
import {
  checkDecisionBody,
  compareQueue,
  computeGate,
  defaultConfirmBasis,
  effectOf,
  isReviewable,
  nextPending,
  nextProcessStatus,
  transitionAllowed,
  workingProtocolStatus,
} from '../../src/modules/verification/domain/rules';
import { aggregateStatus, applyDecisions, dateRu, partialGroupProgress, sealProtocol, type SnapshotDecision } from '../../src/modules/verification/domain/snapshot';
import {
  aiComment,
  confirmComment,
  DECISION_MARKER,
  rejectComment,
  sourceRef,
  STATUS_LINE,
  systemCommentRejected,
  SYSTEM_COMMENT_DISPUTE,
} from '../../src/modules/verification/domain/templates';
import { distribution, usabilityReport } from '../../src/modules/verification/domain/usability';
import { agreeConfidence, validateRejection, type ValidatorInput } from '../../src/modules/verification/domain/validator';
import { contractSchemas, REPO_CONTRACTS } from '../helpers';
import { d1Fixture, TYUMEN } from './harness';

const codes = DecisionCodes.load(REPO_CONTRACTS);
const FP = 'a'.repeat(64);

describe('decision body rules (Decision contract, ТЗ §9.3 п.2)', () => {
  const ok = (body: Record<string, unknown>) => checkDecisionBody({ seen_fingerprint: FP, ...body } as never, codes);
  const code = (body: Record<string, unknown>) => {
    const r = ok(body);
    return 'violation' in r ? r.violation.code : 'OK';
  };

  it('accepts the three actions and the v1.0 aliases CONFIRMED / REJECTED', () => {
    expect(ok({ decision: 'CONFIRMED_VIOLATION', comment: 'Подтверждаю' })).toEqual({ decision: 'CONFIRMED_VIOLATION' });
    expect(ok({ decision: 'confirmed', comment: 'Подтверждаю' })).toEqual({ decision: 'CONFIRMED_VIOLATION' });
    expect(ok({ decision: 'REJECTED', reason_code: 'OCR_ERROR', comment: 'Ошибка OCR' })).toEqual({ decision: 'NEGATIVE_VERIFIED' });
    expect(ok({ decision: 'CLARIFICATION_REQUIRED', clarify_code: 'REVISION_CONFLICT', comment: 'Конфликт' })).toEqual({ decision: 'CLARIFICATION_REQUIRED' });
    expect(ok({ decision: 'REVERT_TO_PENDING' })).toEqual({ decision: 'REVERT_TO_PENDING' });
  });

  it('never accepts PARTIALLY_CONFIRMED (I2) and names «Разделить»', () => {
    expect(code({ decision: 'PARTIALLY_CONFIRMED', comment: 'x' })).toBe('STATUS_NOT_ALLOWED');
  });

  it('rejection needs only a reason code: the comment and the extra fields are optional', () => {
    expect(code({ decision: 'NEGATIVE_VERIFIED', comment: 'x' })).toBe('REASON_CODE_REQUIRED');
    expect(code({ decision: 'NEGATIVE_VERIFIED' })).toBe('REASON_CODE_REQUIRED');
    expect(code({ decision: 'NEGATIVE_VERIFIED', reason_code: 'NO_SUCH', comment: 'x' })).toBe('VALIDATION_ERROR');
    expect(code({ decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR' })).toBe('OK');
    expect(code({ decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: '   ' })).toBe('OK');
    expect(code({ decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: null, comment_source: null })).toBe('OK');
    for (const reason of ['WRONG_REVISION', 'APPROVED_CHANGE', 'NOT_APPLICABLE_PARAM', 'DUPLICATE', 'OTHER']) {
      expect(code({ decision: 'NEGATIVE_VERIFIED', reason_code: reason })).toBe('OK');
    }
    expect(codes.reject.every((r) => r.requires.length === 0)).toBe(true);
  });

  it('keeps the code families apart (contract allOf)', () => {
    expect(code({ decision: 'CONFIRMED_VIOLATION', comment: 'x', reason_code: 'OCR_ERROR' })).toBe('VALIDATION_ERROR');
    expect(code({ decision: 'CONFIRMED_VIOLATION', comment: 'x', basis_code: 'NOPE' })).toBe('VALIDATION_ERROR');
    expect(code({ decision: 'CLARIFICATION_REQUIRED', comment: 'x' })).toBe('VALIDATION_ERROR');
    expect(code({ decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: 'x', basis_code: 'CV_DEVIATION_PD_RD' })).toBe('VALIDATION_ERROR');
    expect(code({ decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: 'x', planned_action: 'ISSUE_ORDER' })).toBe('VALIDATION_ERROR');
    expect(code({ decision: 'CONFIRMED_VIOLATION', comment: 'x', planned_action: 'ISSUE_ORDER' })).toBe('OK');
  });

  it('reads every requirable field and label from enums.yaml (no vocabulary in code)', () => {
    const enums = loadEnums(REPO_CONTRACTS);
    expect(codes.reject.map((r) => r.code)).toEqual(enums.DecisionRejectReason!.values.map((v) => v.code));
    expect(codes.aliases).toEqual({ CONFIRMED: 'CONFIRMED_VIOLATION', REJECTED: 'NEGATIVE_VERIFIED' });
    expect(codes.label('DecisionClarifyBasis', 'REVISION_CONFLICT')).toBe('Конфликт редакций');
  });
});

describe('action mapping (90 §3.2.4) and transitions', () => {
  it('maps every action to the four axes', () => {
    expect(effectOf('CONFIRMED_VIOLATION', null, 'CANDIDATE', false)).toEqual({
      effectiveStatus: 'CONFIRMED_VIOLATION', findingStatus: 'CONFIRMED_VIOLATION', decidedBy: 'INSPECTOR', goldEffect: 'POSITIVE_DRAFT', opensDispute: false,
    });
    expect(effectOf('NEGATIVE_VERIFIED', 'AGREE', 'CANDIDATE', false)).toMatchObject({ effectiveStatus: 'NEGATIVE_VERIFIED', decidedBy: 'INSPECTOR', goldEffect: 'NEGATIVE_DRAFT' });
    expect(effectOf('NEGATIVE_VERIFIED', 'UNCERTAIN', 'CANDIDATE', false)).toMatchObject({ effectiveStatus: 'NEGATIVE_VERIFIED' });
    expect(effectOf('NEGATIVE_VERIFIED', 'DISAGREE', 'CANDIDATE', false)).toEqual({
      effectiveStatus: 'CLARIFICATION_REQUIRED', findingStatus: 'CANDIDATE', decidedBy: 'SYSTEM', goldEffect: 'NONE', opensDispute: true,
    });
    expect(effectOf('CLARIFICATION_REQUIRED', null, 'SUSPICION', true)).toMatchObject({ effectiveStatus: 'CLARIFICATION_REQUIRED', findingStatus: 'SUSPICION', goldEffect: 'WITHDRAW' });
    expect(effectOf('REVERT_TO_PENDING', null, 'CANDIDATE', true)).toMatchObject({ effectiveStatus: 'PENDING', decidedBy: 'SYSTEM', goldEffect: 'WITHDRAW' });
  });

  it('CONFIRMED_VIOLATION is only ever produced by the inspector (I1)', () => {
    for (const d of ['CONFIRMED_VIOLATION', 'NEGATIVE_VERIFIED', 'CLARIFICATION_REQUIRED', 'REVERT_TO_PENDING'] as const) {
      for (const v of ['AGREE', 'UNCERTAIN', 'DISAGREE', null] as const) {
        const e = effectOf(d, v, 'CANDIDATE', false);
        if (e.findingStatus === 'CONFIRMED_VIOLATION' || e.effectiveStatus === 'CONFIRMED_VIOLATION') expect(e.decidedBy).toBe('INSPECTOR');
      }
    }
  });

  it('allows changes before finalization but no revert of a pending card', () => {
    expect(transitionAllowed('PENDING', 'REVERT_TO_PENDING')).toBe(false);
    expect(transitionAllowed('PENDING', 'CONFIRMED_VIOLATION')).toBe(true);
    expect(transitionAllowed('CONFIRMED_VIOLATION', 'NEGATIVE_VERIFIED')).toBe(true);
    expect(transitionAllowed('CLARIFICATION_REQUIRED', 'REVERT_TO_PENDING')).toBe(true);
    expect(transitionAllowed(null, 'CONFIRMED_VIOLATION')).toBe(false);
  });

  it('moves the process automatically (90 §3.2.2)', () => {
    expect(nextProcessStatus('READY', 3, 0)).toBe('VERIFYING');
    expect(nextProcessStatus('READY', 0, 0)).toBe('COMPLETED');
    expect(nextProcessStatus('VERIFYING', 0, 1)).toBe('VERIFYING');
    expect(nextProcessStatus('VERIFYING', 0, 0)).toBe('COMPLETED');
    expect(nextProcessStatus('COMPLETED', 1, 0)).toBe('VERIFYING');
    expect(nextProcessStatus('FINALIZED', 1, 0)).toBe('FINALIZED');
    expect(workingProtocolStatus('READY')).toBe('IN_VERIFICATION');
    expect(workingProtocolStatus('COMPLETED')).toBe('VERIFICATION_COMPLETED');
  });

  it('needs a decision only for ACTIVE checks with an inspector status and complete data', () => {
    expect(isReviewable({ lifecycleState: 'ACTIVE', inspectorStatus: 'PENDING', completenessStatus: null })).toBe(true);
    expect(isReviewable({ lifecycleState: 'ACTIVE', inspectorStatus: null, completenessStatus: null })).toBe(false);
    expect(isReviewable({ lifecycleState: 'SUPERSEDED', inspectorStatus: 'PENDING', completenessStatus: 'COMPLETE' })).toBe(false);
    expect(isReviewable({ lifecycleState: 'ACTIVE', inspectorStatus: 'PENDING', completenessStatus: 'MISSING_EVIDENCE' })).toBe(false);
  });

  it('defaults the GOLD expert_reason_code from the discrepancy (05 §3.6.2)', () => {
    expect(defaultConfirmBasis({ axis: 'PD_RD', comparisonResult: 'CONFIGURATION_MISMATCH' })).toBe('CV_DEVIATION_PD_RD');
    expect(defaultConfirmBasis({ axis: 'PD_RD', comparisonResult: 'MISSING_DESIGN_ELEMENT' })).toBe('CV_MISSING_IN_RD');
    expect(defaultConfirmBasis({ axis: 'RD_ID', comparisonResult: 'TOLERANCE_EXCEEDED' })).toBe('CV_TOLERANCE_EXCEEDED');
    expect(defaultConfirmBasis({ axis: 'RD_ID', comparisonResult: 'VALUE_MISMATCH' })).toBe('CV_NOT_PER_RD');
    expect(defaultConfirmBasis({ axis: 'NORM_RD', comparisonResult: 'VALUE_MISMATCH' })).toBe('CV_NORM_VIOLATION');
  });
});

describe('finalize gate (ТЗ §9.3 п.4)', () => {
  const base = { nonReviewable: [], pendingSuspicionKeys: [] as string[] };
  it('blocks on pending candidates, open disputes and an unfinished verification', () => {
    const g = computeGate({
      ...base,
      processStatus: 'VERIFYING',
      reviewable: [
        { findingId: 'a', inspectorStatus: 'PENDING' },
        { findingId: 'b', inspectorStatus: 'CLARIFICATION_REQUIRED' },
      ],
      openDisputeFindingIds: ['b'],
    });
    expect(g.can_finalize).toBe(false);
    expect(g.blockers.map((b) => b.code)).toEqual(['PENDING_CANDIDATE', 'OPEN_DISPUTE', 'PROCESS_NOT_COMPLETED']);
    expect(g.blockers[0]!.finding_ids).toEqual(['a']);
  });
  it('lets an explicit clarification through with a warning (п. 9.3.4 «или переведён»)', () => {
    const g = computeGate({
      processStatus: 'COMPLETED',
      reviewable: [
        { findingId: 'a', inspectorStatus: 'CONFIRMED_VIOLATION' },
        { findingId: 'b', inspectorStatus: 'CLARIFICATION_REQUIRED' },
      ],
      openDisputeFindingIds: [],
      nonReviewable: [{ findingId: 'm', protocolStatus: 'ID_MISSING', violationLabel: 'MISSING_DOCUMENT' }],
      pendingSuspicionKeys: ['FREE-X'],
    });
    expect(g.can_finalize).toBe(true);
    expect(g.blockers).toEqual([]);
    expect(g.warnings.map((w) => w.code)).toEqual(['CLARIFICATION_KEPT', 'MISSING_EVIDENCE', 'PENDING_SUSPICIONS']);
  });
});

describe('queue order (risk orders, never decides — ТЗ §9.2)', () => {
  const k = (id: string, crit: string | null, card: string, loc: string, status = 'PENDING') => ({
    findingId: id, criticalityLevel: crit, protocolStatus: crit === 'CRITICAL_SUSPEND' ? 'CRITICAL' : 'WARNING', riskLevel: 'HIGH', reviewPriority: null, cardNo: card, location: loc, inspectorStatus: status,
  });
  it('sorts critical first, then card, then location naturally, and finds the next pending with wrap-around', () => {
    const items = [k('f1', 'SUBSTANTIAL_ORDER', 'Б.2', '267'), k('c2', 'CRITICAL_SUSPEND', 'Б.3', '142'), k('c1', 'CRITICAL_SUSPEND', 'Б.1', '012', 'CONFIRMED_VIOLATION'), k('c3', 'CRITICAL_SUSPEND', 'Б.10', '9')];
    const sorted = [...items].sort(compareQueue).map((x) => x.findingId);
    expect(sorted).toEqual(['c1', 'c2', 'c3', 'f1']);
    const ordered = [...items].sort(compareQueue);
    expect(nextPending(ordered, 'c2')).toBe('c3');
    expect(nextPending(ordered, 'f1')).toBe('c2');
    expect(nextPending(ordered, null)).toBe('c2');
    expect(nextPending(ordered.map((x) => ({ ...x, inspectorStatus: 'CONFIRMED_VIOLATION' })), 'c1')).toBeNull();
  });
});

describe('AI rejection validator (05 §3.7)', () => {
  const finding = {
    findingId: 'F-314', paramCode: 'IOS4-078', location: '314', locationType: 'ROOM', axis: 'PD_RD', comparisonResult: 'CONFIGURATION_MISMATCH',
    criticalityLevel: 'CRITICAL_SUSPEND', riskLevel: 'HIGH', confidence: 0.8, groupLocations: ['147', '198', '314'],
    evidence: [
      { stage: 'PD', file_id: 'F0171', pdf_page_number: 88, role: 'EXPECTED', geometry: { boxes: [[0.1, 0.1, 0.2, 0.2]] } },
      { stage: 'RD', file_id: 'F0201', pdf_page_number: 18, role: 'ACTUAL', geometry: { boxes: [[0.3, 0.3, 0.4, 0.4]] } },
    ],
  };
  const files = new Map([
    ['F0201', { fileId: 'F0201', objectId: TYUMEN, docStage: 'RD', manifestStage: 'RD_ID_MIXED' }],
    ['F0203', { fileId: 'F0203', objectId: TYUMEN, docStage: 'RD', manifestStage: 'RD_ID_MIXED' }],
    ['F0171', { fileId: 'F0171', objectId: TYUMEN, docStage: 'PD', manifestStage: 'PD' }],
    ['F0172', { fileId: 'F0172', objectId: TYUMEN, docStage: 'PD', manifestStage: 'PD' }],
  ]);
  const run = (patch: Partial<ValidatorInput>) =>
    validateRejection({ reasonCode: 'OCR_ERROR', finding, files, label: (e, c) => codes.label(e, c), ...patch });

  it('agrees by default, with a confidence that falls as the model is surer', () => {
    const r = run({ reasonCode: 'EXTRACTION_ERROR' });
    expect(r).toMatchObject({ verdict: 'AGREE', ruleIds: [], argument: null, confidence: 0.6 });
    expect(agreeConfidence(0.2)).toBe(0.9);
    expect(agreeConfidence(0.99)).toBe(0.51);
    expect(agreeConfidence(null)).toBe(0.75);
  });
  it('R-TOL-1: a configuration change is not «within tolerance»', () => {
    const r = run({ reasonCode: 'WITHIN_TOLERANCE' });
    expect(r.verdict).toBe('DISAGREE');
    expect(r.ruleIds).toEqual(['R-TOL-1']);
    expect(r.argument).toContain('«Изменена конфигурация»');
  });
  it('R-APC-1: an RD change-registration record is not an approval; R-APC-2: an external ref is uncertain', () => {
    expect(run({ reasonCode: 'APPROVED_CHANGE', approvedChangeRef: 'Изм. 4, лист регистрации изменений РД ОВ1' }).ruleIds).toEqual(['R-APC-1']);
    expect(run({ reasonCode: 'APPROVED_CHANGE', approvedChangeRef: 'см. РД', approvedChangeFileId: 'F0201' }).verdict).toBe('DISAGREE');
    const external = run({ reasonCode: 'APPROVED_CHANGE', approvedChangeRef: 'Письмо ГАУ «Мосгосэкспертиза» № 77-1-1-2-012345-2024 от 12.03.2024' });
    expect(external).toMatchObject({ verdict: 'UNCERTAIN', ruleIds: ['R-APC-2'] });
  });
  it('R-REV-1: the «correct» revision is already the source; R-REV-2: another stage is uncertain', () => {
    expect(run({ reasonCode: 'WRONG_REVISION', correctFileId: 'F0201' }).ruleIds).toEqual(['R-REV-1']);
    expect(run({ reasonCode: 'WRONG_REVISION', correctFileId: 'F0203' }).verdict).toBe('AGREE');
    expect(run({ reasonCode: 'WRONG_REVISION', correctFileId: 'F0171' }).ruleIds).toEqual(['R-REV-1']);
    expect(run({ reasonCode: 'WRONG_REVISION', correctFileId: 'F0172' }).ruleIds).toEqual(['R-REV-2']);
  });
  it('R-DUP-1/2, R-LNK-1, R-NA-1, R-HIGH-1', () => {
    expect(run({ reasonCode: 'DUPLICATE', duplicate: { findingId: 'F-198', paramCode: 'IOS4-078', location: '198' } }).ruleIds).toEqual(['R-DUP-1']);
    expect(run({ reasonCode: 'DUPLICATE', duplicate: { findingId: 'H', paramCode: 'IOS4-077', location: '314' } }).ruleIds).toEqual(['R-DUP-2']);
    expect(run({ reasonCode: 'DUPLICATE', duplicate: { findingId: 'D', paramCode: 'IOS4-078', location: '314' } }).verdict).toBe('AGREE');
    expect(run({ reasonCode: 'LINKING_ERROR' }).ruleIds).toEqual(['R-LNK-1']);
    expect(run({ reasonCode: 'NOT_APPLICABLE_PARAM' }).ruleIds).toEqual(['R-NA-1']);
    expect(run({ reasonCode: 'EQUIVALENT_SOLUTION', finding: { ...finding, confidence: 0.97 } }).ruleIds).toEqual(['R-HIGH-1']);
  });
  it('R-OCR-1: a value from the PDF text layer cannot be an OCR error (only with text-source data)', () => {
    expect(run({ reasonCode: 'OCR_ERROR' }).verdict).toBe('AGREE');
    const layer = new Map([['F0201#18', ['TEXT_LAYER']]]);
    expect(run({ reasonCode: 'OCR_ERROR', textSources: layer }).ruleIds).toEqual(['R-OCR-1']);
    expect(run({ reasonCode: 'OCR_ERROR', textSources: new Map([['F0201#18', ['OCR']]]) }).verdict).toBe('AGREE');
  });
});

describe('wording (ТЗ §9.4 verbatim, Приложение 2, 93 §5.4)', () => {
  it('keeps the §9.4 sample comments word for word', () => {
    expect(systemCommentRejected('OCR_ERROR')).toBe(
      'Результат инспектора: NEGATIVE_VERIFIED. Причина: OCR_ERROR. Запись включена в черновик следующей версии набора данных; её использование для обучения допускается только после проверки куратором данных и выпуска dataset_version',
    );
    expect(SYSTEM_COMMENT_DISPUTE).toBe(
      'Статус: CLARIFICATION_REQUIRED. Показаны точные страницы и доказательные фрагменты. До повторного решения инспектора запись не включается в GOLD и не передаётся во внешнюю систему',
    );
  });
  it('renders the Приложение 2 AI comment and the protocol markers', () => {
    expect(aiComment('AGREE', 0.94, null, 'Добавить синонимы в словарь терминов.')).toBe(
      '🤖 ИИ СОГЛАСЕН (94%). Причина обоснована. Добавить синонимы в словарь терминов. Отправлено в дообучение (черновик набора, после проверки куратором).',
    );
    expect(aiComment('DISAGREE', 0.95, 'Допуск не применяется.', null)).toBe('🤖 ИИ НЕ СОГЛАСЕН (95%). Допуск не применяется.');
    expect(Object.values(DECISION_MARKER)).toEqual(['⏳ Ожидает', '✅ Подтверждено', '❌ Отклонено', '❓ Требует уточнения']);
    expect(STATUS_LINE.READY).toBe('⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)');
    expect(STATUS_LINE.FINALIZED).toBe('🔒 ПРОТОКОЛ ФИНАЛИЗИРОВАН (дозагрузка невозможна)');
    expect(dateRu('2026-09-28T21:30:00Z')).toBe('29 сентября 2026 г.');
  });
  it('prefills comments with the exact sources (stage, шифр, редакция, лист, страница)', () => {
    const facts = {
      paramCode: 'IOS4-078', parameterLabel: 'Воздуховоды общеобменной вентиляции (IOS4-078)', location: '314', locationType: 'ROOM',
      expected: 'Конфигурация вентиляции по листу 10 ПД', actual: 'Конфигурация вентиляции изменена',
      expectedSource: { stage: 'PD', file_id: 'F0171', pdf_page_number: 88, sheet_number: '10' },
      actualSource: { stage: 'RD', file_id: 'F0201', pdf_page_number: 18, sheet_number: '5', document_code: 'АНО-150321-1-РД-ОВ1', revision: '4' },
    };
    expect(confirmComment(facts)).toBe(
      'Подтверждаю нарушение по параметру «Воздуховоды общеобменной вентиляции (IOS4-078)», помещение 314: ожидается «Конфигурация вентиляции по листу 10 ПД» (ПД F0171, л. 10, стр. 88), фактически «Конфигурация вентиляции изменена» (РД АНО-150321-1-РД-ОВ1 ред. 4, л. 5, стр. 18). Согласованное изменение не представлено.',
    );
    expect(rejectComment('OCR_ERROR', facts)).toBe('Отклонено: ошибка распознавания значения (РД АНО-150321-1-РД-ОВ1 ред. 4, л. 5, стр. 18).');
    expect(rejectComment('OTHER', facts)).toBe('');
    expect(sourceRef(null)).toBe('источник не указан');
  });
});

describe('FINAL protocol snapshot (90 §3.2.3, protocol.schema.json)', () => {
  const f = d1Fixture();
  const decisions = new Map<string, SnapshotDecision>();
  const at = '2026-09-28T10:00:00.000Z';
  const d = (findingId: string, location: string, status: string, extra: Partial<SnapshotDecision> = {}): SnapshotDecision => ({
    findingId, location, status, decidedBy: 'INSPECTOR', reasonCode: null, basisCode: null, clarifyCode: null, comment: 'Комментарий', decidedAt: at, userId: 'u-1', aiVerdict: null, aiComment: null, ...extra,
  });
  for (const x of f.findings) decisions.set(x.finding_id, d(x.finding_id, x.location, 'CONFIRMED_VIOLATION', { basisCode: 'CV_DEVIATION_PD_RD' }));
  const rejected = `${TYUMEN}-IOS4-078-PDRD-140`;
  decisions.set(rejected, d(rejected, '140', 'NEGATIVE_VERIFIED', { reasonCode: 'LINKING_ERROR', aiVerdict: 'AGREE', aiComment: '🤖 ИИ СОГЛАСЕН (60%).' }));
  const free = f.findings.filter((x) => x.matrix_scope === 'FREE_SEARCH');
  for (const x of free) decisions.set(x.finding_id, d(x.finding_id, x.location, 'NEGATIVE_VERIFIED', { reasonCode: 'EQUIVALENT_SOLUTION', aiVerdict: 'AGREE', aiComment: '🤖 ИИ СОГЛАСЕН (55%).' }));
  const content = applyDecisions(f.protocol as unknown as Record<string, unknown>, decisions, {
    version: 2, status: 'PROTOCOL_FINALIZED', processStatus: 'FINALIZED', isFinal: true, generatedAt: '2026-09-28T12:00:00.000Z',
    signature: { inspectorName: 'Иванова Мария Сергеевна', inspectorPosition: 'Главный специалист', finalizedAt: '2026-09-28T12:00:00.000Z', finalizedBy: 'Иванова Мария Сергеевна' },
    label: (e, c) => codes.label(e, c),
  }) as Record<string, any>;

  it('stays a valid Protocol document', () => {
    const r = contractSchemas().validate('protocol', content);
    expect(r.valid ? [] : r.errors).toEqual([]);
  });
  it('writes the header, markers, А.3/А.4, cards and the signature seal', () => {
    expect(content.header.version_line).toBe('2 (окончательная)');
    expect(content.header.status_line).toBe('🔒 ПРОТОКОЛ ФИНАЛИЗИРОВАН (дозагрузка невозможна)');
    expect(content.is_final).toBe(true);
    const rows = content.appendix2.section4_critical.rows as Array<{ parameter_code: string; inspector_decision_ru: string; finding_ids: string[] }>;
    expect(rows.map((r) => r.inspector_decision_ru)).toEqual(['✅ Подтверждено', '✅ Подтверждено', '✅ Подтверждено']);
    const s6 = content.appendix2.section6_ai_suspicions.rows[0];
    expect(s6).toMatchObject({ inspector_status: 'DISMISSED', inspector_decision_ru: '❌ Отклонено', rejection_reason: 'Равнозначное решение (иное обозначение / формулировка)', ai_comment: '🤖 ИИ СОГЛАСЕН (55%).' });
    expect(content.tz92_tables.a3_confirmed.map((r: { card_ref: string }) => r.card_ref)).toEqual(['Б.1', 'Б.3', 'Б.4']);
    const inspectorNegatives = content.tz92_tables.a4_negative_verified.filter((r: { decided_by: string }) => r.decided_by === 'INSPECTOR');
    expect(inspectorNegatives.map((r: { locations: string[] }) => r.locations[0]).sort()).toEqual(['140', '267', '270', '271', '272']);
    expect(content.tz92_tables.a5_hypotheses[0].inspector_status).toBe('DISMISSED');
    const card3 = content.evidence_cards.find((c: { card_no: string }) => c.card_no === 'Б.3');
    expect(card3.inspector.status).toBe('CONFIRMED_VIOLATION');
    expect(content.signature.inspector_name).toBe('Иванова Мария Сергеевна');
    expect(content.signature.content_sha256).toBe(content.content_sha256);
    expect(sealProtocol(content)).toBe(content.content_sha256);
    const tampered = structuredClone(content);
    tampered.appendix2.section4_critical.rows[0].inspector_decision_ru = '❌ Отклонено';
    expect(sealProtocol(tampered)).not.toBe(content.content_sha256);
  });
  it('aggregates a group like the dashboard does', () => {
    expect(aggregateStatus(['NEGATIVE_VERIFIED', 'CONFIRMED_VIOLATION'])).toBe('CONFIRMED_VIOLATION');
    expect(aggregateStatus(['NEGATIVE_VERIFIED', 'CLARIFICATION_REQUIRED'])).toBe('CLARIFICATION_REQUIRED');
    expect(aggregateStatus(['NEGATIVE_VERIFIED', 'NEGATIVE_VERIFIED'])).toBe('NEGATIVE_VERIFIED');
    expect(aggregateStatus(['NEGATIVE_VERIFIED', 'PENDING'])).toBe('PENDING');
    expect(aggregateStatus([])).toBe('PENDING');
  });
});

describe('GOLD records (gold_check.schema.json, ТЗ §9.4)', () => {
  const f = d1Fixture();
  it('writes a valid organizer-format row per label; nothing for undecided or system rows (I7)', () => {
    const x = f.findings[0]!;
    const input = {
      findingId: x.finding_id, findingGroupId: x.finding_group_id ?? null, objectId: x.object_id, objectSplit: 'TRAIN_PUBLIC', matrixScope: x.matrix_scope,
      paramId: x.parameter_id ?? null, paramCode: x.parameter_code, locationType: x.location_type, location: x.location, pdValue: x.pd_value ?? null,
      rdValue: x.rd_value ?? null, idValue: x.id_value ?? null, comparisonResult: x.comparison_result ?? null, protocolStatus: x.protocol_status,
      criticality: x.criticality ?? null, documentStatus: null, evidence: x.evidence,
    };
    for (const label of ['POSITIVE', 'NEGATIVE'] as const) {
      const rec = goldRecord(input, label);
      const r = contractSchemas().validate('gold_check', rec);
      expect(r.valid ? [] : r.errors).toEqual([]);
      expect(rec.inspector_status).toBe(label === 'POSITIVE' ? 'CONFIRMED' : 'REJECTED');
      expect(rec.violation_label).toBe(label === 'POSITIVE' ? 'VIOLATION_PRESENT' : 'NO_VIOLATION');
    }
    expect(goldLabelOf('CONFIRMED_VIOLATION', 'INSPECTOR')).toBe('POSITIVE');
    expect(goldLabelOf('NEGATIVE_VERIFIED', 'INSPECTOR')).toBe('NEGATIVE');
    expect(goldLabelOf('NEGATIVE_VERIFIED', 'SYSTEM')).toBeNull();
    expect(goldLabelOf('CLARIFICATION_REQUIRED', 'SYSTEM')).toBeNull();
    expect(goldLabelOf('PENDING', null)).toBeNull();
    expect(datasetSplit('TRAIN_PUBLIC')).toBe('TRAIN');
    expect(datasetSplit('TEST_HIDDEN')).toBe('HIDDEN_TEST');
  });
});

describe('usability report (ТЗ §9.3 «Критерии юзабилити»)', () => {
  it('measures clicks per decision and the protocol time against the targets', () => {
    const t0 = Date.parse('2026-09-28T10:00:00Z');
    const decisions = [2, 3, 0, 2, 1].map((clicks, i) => ({
      decidedAt: new Date(t0 + (i + 1) * 40_000), userId: 'u', decision: 'CONFIRMED_VIOLATION', metrics: { clicks, keys: clicks === 0 ? 2 : 0, time_on_card_ms: 30_000 },
    }));
    const r = usabilityReport(decisions, [{ type: 'SESSION_START', tsClient: new Date(t0), userId: 'u' }], new Date(t0 + 10 * 60_000));
    expect(r.clicks).toEqual({ n: 5, mean: 1.6, median: 2, p90: 2.6, max: 3, share_within_target: 1 });
    expect(r.keyboard_only_share).toBe(0.2);
    expect(r.protocol_time_ms).toBe(600_000);
    expect(r.met).toEqual({ protocol_time: true, clicks: true });
    expect(distribution([])).toEqual({ n: 0, mean: null, median: null, p90: null, max: null });
  });
});

describe('hashing sanity', () => {
  it('seals with the same canonical JSON as inspector_common.hashing', () => {
    expect(sha256Hex(canonicalJson({ b: 1, a: 'ё' }))).toBe(sha256Hex('{"a":"ё","b":1}'));
  });
});

describe('partialGroupProgress (group with mixed decisions)', () => {
  it('reports only groups that are partly confirmed', () => {
    const c = (evidenceGroupId: string, inspectorStatus: string | null) => ({ evidenceGroupId, inspectorStatus });
    expect(
      partialGroupProgress([
        c('G1', 'CONFIRMED_VIOLATION'), c('G1', 'CONFIRMED_VIOLATION'), c('G1', 'NEGATIVE_VERIFIED'), c('G1', 'PENDING'),
        c('G2', 'CONFIRMED_VIOLATION'), c('G2', 'CONFIRMED_VIOLATION'),
        c('G3', 'NEGATIVE_VERIFIED'), c('G3', 'PENDING'),
        c('G4', 'CONFIRMED_VIOLATION'),
      ]),
    ).toEqual({ G1: { confirmed: 2, total: 4 } });
  });
});
