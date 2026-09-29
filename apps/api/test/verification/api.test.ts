/**
 * Verification API through the real AppModule (auth required, OpenAPI request and response validation on) on the
 * Тюменская 5 fixture: 10 atomic findings in 4 groups (IOS4-079 · 012; FREE-HEATING-001 · 267/270/271/272;
 * IOS4-078 · 140/142 and 147/198/314). Covers 05 §9.2 AT-01…AT-17 in their DB-free form.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { contractSchemas, REPO_CONTRACTS } from '../helpers';
import {
  call,
  confirm,
  createVerificationApp,
  d1Fixture,
  decide,
  FID,
  getCard,
  idemKey,
  login,
  reauth,
  seedTyumen,
  seedUsers,
  TYUMEN,
  type Session,
  type VerificationTestApp,
} from './harness';

type Json = Record<string, any>;

const F012 = FID('IOS4-079-PDRD-012');
const F140 = FID('IOS4-078-PDRD-140');
const F142 = FID('IOS4-078-PDRD-142');
const F147 = FID('IOS4-078-PDRD-147');
const F198 = FID('IOS4-078-PDRD-198');
const F314 = FID('IOS4-078-PDRD-314');
const F267 = FID('FREE-HEATING-001-PDRD-267');
const F270 = FID('FREE-HEATING-001-PDRD-270');
const F271 = FID('FREE-HEATING-001-PDRD-271');
const F272 = FID('FREE-HEATING-001-PDRD-272');
const ALL = [F012, F140, F142, F147, F198, F314, F267, F270, F271, F272];

describe('verification API (AG-05)', () => {
  let t: VerificationTestApp;
  let inspector: Session;
  let pid: string;

  beforeAll(async () => {
    t = await createVerificationApp();
  });
  afterAll(async () => {
    await t.close();
  });
  beforeEach(async () => {
    await seedUsers(t.users);
    t.audit.rows.length = 0;
    t.sessions.sessions.clear();
    t.sessions.reauth.clear();
    pid = seedTyumen(t.repo);
    inspector = await login(t.http, 'inspector');
  });

  const summary = async (s: Session = inspector) => (await call(t.http, { url: `/processes/${pid}/verification`, session: s })).json() as Json;
  const decisionRows = () => t.repo.state.decisions;
  const checkOf = (id: string) => t.repo.state.checks.find((c) => c.findingId === id)!;

  describe('reading', () => {
    it('summary: READY, 10 candidates pending, completeness apart, gate blocked, ETag', async () => {
      const res = await call(t.http, { url: `/processes/${pid}/verification`, session: inspector });
      expect(res.statusCode).toBe(200);
      expect(res.headers.etag).toBe('"1"');
      const s = res.json() as Json;
      expect(s).toMatchObject({ status: 'READY', verification_status: 'IN_VERIFICATION', scenario: 'PD_RD_ONLY', scenario_ru: 'Только ПД и РД' });
      expect(s.upload_status).toEqual({ pd: 'PD_UPLOADED', rd: 'RD_UPLOADED', id: 'ID_MISSING' });
      expect(s.counts).toMatchObject({ reviewable: 10, pending: 10, confirmed: 0, disputes_open: 0 });
      expect(s.gate.can_finalize).toBe(false);
      expect(s.gate.blockers.map((b: Json) => b.code)).toEqual(['PENDING_CANDIDATE', 'PROCESS_NOT_COMPLETED']);
      expect(s.capabilities).toEqual({ can_decide: true, can_claim: true, can_reopen: false, can_finalize: false, can_unfinalize: false });
      expect(s.next_finding_id).toBe(F012);
    });

    it('queue: stable order (critical Б.1, Б.3, Б.4, then FREE Б.2), tab filters and counts', async () => {
      const q = (await call(t.http, { url: `/processes/${pid}/findings`, session: inspector })).json() as Json;
      expect(q.items.map((i: Json) => i.finding_id)).toEqual([F012, F140, F142, F147, F198, F314, F267, F270, F271, F272]);
      expect(q.items.map((i: Json) => i.position)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
      expect(q.items[0]).toMatchObject({ card_no: 'Б.1', parameter_label: 'Характеристики вентиляторов (IOS4-079)', location: '012', inspector_status: 'PENDING', finding_status: 'CANDIDATE' });
      expect(q.items[6]).toMatchObject({ matrix_scope: 'FREE_SEARCH', kind: 'SUSPICION_CONVERTED', finding_status: 'SUSPICION' });
      expect(q.counts).toEqual({ ALL: 10, PENDING: 10, CLARIFICATION: 0, CONFIRMED: 0, NEGATIVE: 0, DISPUTES: 0 });
      const bad = await call(t.http, { url: `/processes/${pid}/findings?tab=nope`, session: inspector });
      expect(bad.statusCode).toBe(400);
    });

    it('card of room 314: every ТЗ §9.2 п.4 field, anchor p18 and the drawn page p20, viewer contract shapes', async () => {
      const res = await call(t.http, { url: `/processes/${pid}/findings/${F314}`, session: inspector });
      expect(res.statusCode).toBe(200);
      expect(res.headers.etag).toBe('"1"');
      const c = res.json() as Json;
      expect(c.param).toMatchObject({ code: 'IOS4-078', id: 78, label: 'Воздуховоды общеобменной вентиляции (IOS4-078)', rule_version: 'IOS4-078@1' });
      expect(c.values).toMatchObject({ expected: 'Конфигурация вентиляции по листу 10 ПД', actual: 'Конфигурация вентиляции изменена', comparison_result_ru: 'Изменена конфигурация' });
      expect(c.location_text).toBe('помещение 314');
      expect(c.approved_change_ref).toBe('NONE');
      const pages = c.sources.map((s: Json) => [s.stage, s.file_id, s.pdf_page_number, s.is_anchor, s.location_page]);
      expect(pages).toEqual([
        ['PD', 'F0171', 88, true, false],
        ['RD', 'F0201', 18, true, false],
        ['RD', 'F0201', 20, false, true],
      ]);
      const rd = c.sources[1];
      expect(rd).toMatchObject({ document_code: 'АНО-150321-1-РД-ОВ1', revision: '4', sheet_number: '5', file_sha256: expect.stringMatching(/^[0-9a-f]{64}$/) });
      expect(rd.geometry.boxes.length).toBeGreaterThan(0);
      const checklist = Object.fromEntries(c.field_checklist.map((f: Json) => [f.key, f.present || f.partial]));
      for (const key of ['finding_id', 'parameter', 'expected_actual', 'file_sha256', 'stage', 'document_code', 'revision', 'sheet_page', 'geometry', 'rationale', 'risk_level']) {
        expect(checklist[key], key).toBe(true);
      }
      expect(c.navigation).toMatchObject({ position: 6, total: 10, prev_finding_id: F198, next_finding_id: F267, next_pending_finding_id: F267 });
      expect(c.prefill.confirm_basis_code).toBe('CV_DEVIATION_PD_RD');
      expect(c.prefill.confirm_comment).toContain('помещение 314');
      expect(Object.keys(c.prefill.reject_comments)).toHaveLength(12);
      expect(c.risk_note).toContain('только очерёдность');
      // AG-08's EvidenceViewer props: {card: EvidenceCard, group: FindingGroup}.
      expect(c.evidence_card).toMatchObject({ card_no: 'Б.4', finding_ids: [F314], locations: ['314'] });
      expect(c.finding_group.locations).toEqual(['314']);
      expect(c.finding_group.location_pages).toEqual({ '314': [expect.objectContaining({ file_id: 'F0201', pdf_page_number: 20 })] });
      const cardCheck = contractSchemas().validate('protocol', { ...fixtureProtocolShell(), evidence_cards: [c.evidence_card] });
      expect(cardCheck.valid ? [] : cardCheck.errors).toEqual([]);
      const groupCheck = contractSchemas().validate('finding_group', c.finding_group);
      expect(groupCheck.valid ? [] : groupCheck.errors).toEqual([]);
    });

    it('completeness is served apart from candidates (ТЗ §9.3 п.1)', async () => {
      const c = (await call(t.http, { url: `/processes/${pid}/completeness`, session: inspector })).json() as Json;
      expect(c.scenario_line).toBe('Тип проверки: PD_RD_ONLY (Только ПД и РД)');
      expect(c.load_status_rows.map((r: Json) => r.status)).toEqual(['PD_UPLOADED', 'RD_UPLOADED', 'ID_MISSING']);
      expect(c.completeness_rows.length).toBeGreaterThan(0);
      expect(c.non_reviewable).toEqual([]);
    });

    it('decision codes come from enums.yaml with hotkeys 1–9', async () => {
      const d = (await call(t.http, { url: '/dictionaries/decision-codes', session: inspector })).json() as Json;
      expect(d.reject.map((r: Json) => r.code).slice(0, 3)).toEqual(['WRONG_REVISION', 'APPROVED_CHANGE', 'OCR_ERROR']);
      expect(d.reject[0]).toMatchObject({ hotkey: '1', requires: [], family: 'MODEL_ERROR' });
      expect(d.reject[9].hotkey).toBeNull();
      expect(d.clarify).toHaveLength(8);
      expect(d.limits).toMatchObject({ other_comment_min: 30, unfinalize_reason_min: 20 });
    });
  });

  describe('decisions (ТЗ §9.3 п.2)', () => {
    it('confirm: 201, contract-valid decision, READY → VERIFYING, audit row, auto-advance, ETag', async () => {
      t.audit.rows.length = 0;
      const res = await confirm(t.http, inspector, pid, F012);
      expect(res.statusCode).toBe(201);
      expect(res.headers.etag).toBe('"2"');
      const body = res.json() as Json;
      expect(body.finding).toMatchObject({ inspector_status: 'CONFIRMED_VIOLATION', finding_status: 'CONFIRMED_VIOLATION', row_version: 2 });
      expect(body.decision).toMatchObject({ decision: 'CONFIRMED_VIOLATION', effective_status: 'CONFIRMED_VIOLATION', basis_code: 'CV_DEVIATION_PD_RD', gold_effect: 'POSITIVE_DRAFT', comment_source: 'TEMPLATE', decided_by: inspector.userId, decided_role: 'INSPECTOR' });
      expect(body.system_comment).toContain('положительный GOLD-кандидат; передача наружу только после финализации протокола');
      const valid = contractSchemas().validate('decision', body.decision);
      expect(valid.valid ? [] : valid.errors).toEqual([]);
      expect(body.process).toMatchObject({ status: 'VERIFYING', verification_status: 'IN_VERIFICATION', pending: 9, can_finalize: false });
      expect(body.next_finding_id).toBe(F140);
      const check = checkOf(F012);
      expect(check).toMatchObject({ inspectorStatus: 'CONFIRMED_VIOLATION', findingStatus: 'CONFIRMED_VIOLATION', decidedBy: 'INSPECTOR', decidedUserId: inspector.userId });
      const proc = t.repo.state.processes[0]!;
      expect(proc).toMatchObject({ status: 'VERIFYING', assignedInspectorId: inspector.userId });
      expect(t.repo.state.protocols[0]!.status).toBe('IN_VERIFICATION');
      const row = t.audit.rows.find((r) => r.action === 'FINDING_CONFIRMED')!;
      expect(row).toMatchObject({ userId: inspector.userId, objectType: 'FINDING', objectId: F012, processId: pid, constructionObjectId: TYUMEN, result: 'SUCCESS' });
      expect(row.details).toMatchObject({ decision: 'CONFIRMED_VIOLATION', gold_effect: 'POSITIVE_DRAFT' });
      // Domain rows only (in the decision's transaction): the generic per-request mutation row is skipped.
      expect(t.audit.rows.filter((r) => r.httpMethod !== null)).toHaveLength(0);
      expect(t.audit.rows.map((r) => [r.action, (r.details as Json).transition ?? null])).toEqual([
        ['FINDING_CONFIRMED', null],
        ['HTTP_POST', 'READY→VERIFYING'],
      ]);
    });

    it('reject (AGREE): NEGATIVE_VERIFIED, Rejection_Log, §9.4 sample 1 comment, «🤖 ИИ СОГЛАСЕН»', async () => {
      const card = await getCard(t.http, inspector, pid, F140);
      const res = await decide(t.http, inspector, pid, F140, { decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: card.prefill.reject_comments.OCR_ERROR, comment_source: 'TEMPLATE' });
      expect(res.statusCode).toBe(201);
      const body = res.json() as Json;
      expect(body.finding.inspector_status).toBe('NEGATIVE_VERIFIED');
      expect(body.ai).toMatchObject({ verdict: 'AGREE', rule_ids: [] });
      expect(body.ai.comment).toMatch(/^🤖 ИИ СОГЛАСЕН \(\d+%\)\. Причина обоснована\./);
      expect(body.system_comment).toBe(
        'Результат инспектора: NEGATIVE_VERIFIED. Причина: OCR_ERROR. Запись включена в черновик следующей версии набора данных; её использование для обучения допускается только после проверки куратором данных и выпуска dataset_version',
      );
      expect(t.repo.state.rejections).toHaveLength(1);
      expect(t.repo.state.rejections[0]).toMatchObject({ violationId: checkOf(F140).id, rejectionReason: 'OCR_ERROR', aiVerdict: 'AGREE', retrainingStatus: 'IN_DRAFT', curatorFlag: false });
      expect(t.repo.state.rejections[0]!.suggestedFix).toContain('OCR');
      expect(t.audit.rows.map((r) => r.action)).toContain('FINDING_REJECTED');
    });

    it('reject with only a reason code (no comment, empty comment, «Иное», no extra fields) is accepted; decision on READY needs no claim', async () => {
      expect(t.repo.state.processes[0]!.status).toBe('READY');
      const res = await decide(t.http, inspector, pid, F140, { decision: 'NEGATIVE_VERIFIED', reason_code: 'OTHER' });
      expect(res.statusCode).toBe(201);
      const body = res.json() as Json;
      expect(body.decision).toMatchObject({ decision: 'NEGATIVE_VERIFIED', reason_code: 'OTHER', comment_source: 'TEMPLATE' });
      expect(body.decision.comment).toBe('Отклонено: Иное');
      expect(contractSchemas().validate('decision', body.decision).valid).toBe(true);
      expect(t.repo.state.processes[0]).toMatchObject({ status: 'VERIFYING', assignedInspectorId: inspector.userId });
      const res2 = await decide(t.http, inspector, pid, F012, { decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: '   ' });
      expect(res2.statusCode).toBe(201);
    });

    it('422: no reason code, unknown/misplaced fields, PARTIALLY_CONFIRMED', async () => {
      const cases: Array<[Json, string, string | undefined]> = [
        [{ decision: 'NEGATIVE_VERIFIED', comment: 'Нет причины' }, 'REASON_CODE_REQUIRED', undefined],
        [{ decision: 'NEGATIVE_VERIFIED', reason_code: 'WRONG_REVISION', comment: 'Не та редакция', correct_file_id: 'F9999' }, 'VALIDATION_ERROR', 'correct_file_id'],
        [{ decision: 'NEGATIVE_VERIFIED', reason_code: 'DUPLICATE', comment: 'Дубликат', duplicate_of: F314 }, 'VALIDATION_ERROR', 'duplicate_of'],
        [{ decision: 'CLARIFICATION_REQUIRED', comment: 'Уточнить' }, 'VALIDATION_ERROR', 'clarify_code'],
        [{ decision: 'PARTIALLY_CONFIRMED', comment: 'Частично' }, 'STATUS_NOT_ALLOWED', undefined],
      ];
      for (const [body, code, field] of cases) {
        const res = await decide(t.http, inspector, pid, F314, body);
        // VALIDATION_ERROR = a Decision-schema rule (decision.schema.json allOf) → 400; the ТЗ §9.3 codes → 422.
        expect(res.statusCode, `${code} ${JSON.stringify(body)}`).toBe(code === 'VALIDATION_ERROR' ? 400 : 422);
        const p = res.json() as Json;
        expect(p.code).toBe(code);
        expect(res.headers['content-type']).toContain('application/problem+json');
        if (field) expect(p.errors.map((e: Json) => e.field)).toContain(field);
      }
      expect(decisionRows()).toHaveLength(0);
      expect(checkOf(F314).inspectorStatus).toBe('PENDING');
    });

    it('clarify: CLARIFICATION_REQUIRED with a basis, counts as processed for the gate', async () => {
      const card = await getCard(t.http, inspector, pid, F198);
      const res = await decide(t.http, inspector, pid, F198, { decision: 'CLARIFICATION_REQUIRED', clarify_code: 'AWAITING_DOCUMENT', comment: card.prefill.clarify_comments.AWAITING_DOCUMENT });
      expect(res.statusCode).toBe(201);
      const body = res.json() as Json;
      expect(body.decision).toMatchObject({ clarify_code: 'AWAITING_DOCUMENT', effective_status: 'CLARIFICATION_REQUIRED', gold_effect: 'NONE' });
      expect(body.system_comment).toContain('не включается в GOLD');
      expect(checkOf(F198)).toMatchObject({ inspectorStatus: 'CLARIFICATION_REQUIRED', decidedBy: 'SYSTEM', findingStatus: 'CANDIDATE' });
    });

    it('a changed decision appends a row (I3) and supersedes the previous one; REVERT returns the card to PENDING', async () => {
      await confirm(t.http, inspector, pid, F142);
      const res = await decide(t.http, inspector, pid, F142, { decision: 'REJECTED', reason_code: 'LINKING_ERROR', comment: 'Не то помещение' });
      expect(res.statusCode).toBe(201);
      expect((res.json() as Json).decision.decision).toBe('NEGATIVE_VERIFIED');
      const revert = await decide(t.http, inspector, pid, F142, { decision: 'REVERT_TO_PENDING' });
      expect(revert.statusCode).toBe(201);
      const rows = decisionRows().filter((d) => d.findingId === F142);
      expect(rows.map((d) => d.effectiveStatus)).toEqual(['CONFIRMED_VIOLATION', 'NEGATIVE_VERIFIED', 'PENDING']);
      expect(rows[1]!.supersedesDecisionId).toBe(rows[0]!.id);
      expect(rows[2]).toMatchObject({ goldEffect: 'WITHDRAW', supersedesDecisionId: rows[1]!.id });
      expect(checkOf(F142)).toMatchObject({ inspectorStatus: 'PENDING', decidedBy: 'SYSTEM', rowVersion: 4 });
      const history = (await call(t.http, { url: `/processes/${pid}/findings/${F142}/history`, session: inspector })).json() as Json;
      expect(history.decisions).toHaveLength(3);
      expect(history.decisions[0].user.full_name).toBe('Иванова Мария Сергеевна');
      const again = await decide(t.http, inspector, pid, F142, { decision: 'REVERT_TO_PENDING' });
      expect((again.json() as Json).code).toBe('VERIFICATION_NOT_ALLOWED_IN_STATUS');
    });
  });

  describe('AI disagrees → Dispute_Log (ТЗ §9.4 sample 2)', () => {
    it('WITHIN_TOLERANCE on a configuration change opens a dispute that blocks finalization, then the inspector insists', async () => {
      const res = await decide(t.http, inspector, pid, F147, { decision: 'NEGATIVE_VERIFIED', reason_code: 'WITHIN_TOLERANCE', comment: 'Отклонение в пределах допуска' });
      expect(res.statusCode).toBe(201);
      const body = res.json() as Json;
      expect(body.finding.inspector_status).toBe('CLARIFICATION_REQUIRED');
      expect(body.ai).toMatchObject({ verdict: 'DISAGREE', rule_ids: ['R-TOL-1'] });
      expect(body.ai.comment).toMatch(/^🤖 ИИ НЕ СОГЛАСЕН \(95%\)\./);
      expect(body.system_comment).toBe(
        'Статус: CLARIFICATION_REQUIRED. Показаны точные страницы и доказательные фрагменты. До повторного решения инспектора запись не включается в GOLD и не передаётся во внешнюю систему. Основание: ' +
          body.ai.argument,
      );
      expect(body.dispute).toMatchObject({ resolution_status: 'OPEN', rejection_reason: 'WITHIN_TOLERANCE', finding_id: F147 });
      expect(body.decision.gold_effect).toBe('NONE');
      expect(t.repo.state.rejections[0]).toMatchObject({ aiVerdict: 'DISAGREE', retrainingStatus: 'DISPUTED' });
      const s = await summary();
      expect(s.counts.disputes_open).toBe(1);
      expect(s.gate.blockers.map((b: Json) => b.code)).toContain('OPEN_DISPUTE');
      const card = await getCard(t.http, inspector, pid, F147);
      expect((card as Json).open_dispute.dispute_id).toBe(body.dispute.dispute_id);

      // Insisting needs one's own comment.
      const url = `/disputes/${body.dispute.dispute_id}/resolve`;
      const noComment = await call(t.http, { method: 'POST', url, session: inspector, ifMatch: card.row_version, body: { resolution: 'INSPECTOR_UPHELD', seen_fingerprint: card.evidence_fingerprint } });
      expect((noComment.json() as Json).code).toBe('COMMENT_REQUIRED');
      const upheld = await call(t.http, {
        method: 'POST',
        url,
        session: inspector,
        ifMatch: card.row_version,
        body: { resolution: 'INSPECTOR_UPHELD', comment: 'Изменение согласовано устно с проектировщиком, отклонение в пределах допуска', seen_fingerprint: card.evidence_fingerprint },
      });
      expect(upheld.statusCode).toBe(200);
      const after = upheld.json() as Json;
      expect(after.finding.inspector_status).toBe('NEGATIVE_VERIFIED');
      expect(after.dispute).toMatchObject({ resolution_status: 'INSPECTOR_UPHELD', resolved_by: { full_name: 'Иванова Мария Сергеевна' } });
      expect(after.decision).toMatchObject({ reason_code: 'WITHIN_TOLERANCE', comment_source: 'MANUAL', ai_verdict: 'DISAGREE', gold_effect: 'NEGATIVE_DRAFT' });
      expect(t.repo.state.rejections.at(-1)).toMatchObject({ retrainingStatus: 'IN_DRAFT', curatorFlag: true });
      expect((await summary()).counts.disputes_open).toBe(0);
    });

    it('APPROVED_CHANGE citing the RD change-registration sheet → dispute; «Оставить на уточнении» is the explicit transfer', async () => {
      const res = await decide(t.http, inspector, pid, F012, {
        decision: 'NEGATIVE_VERIFIED',
        reason_code: 'APPROVED_CHANGE',
        approved_change_ref: 'Изм. 4 — лист регистрации изменений РД ОВ1',
        comment: 'Изменение внесено в РД (Изм. 4)',
      });
      const body = res.json() as Json;
      expect(body.ai.rule_ids).toEqual(['R-APC-1']);
      const card = await getCard(t.http, inspector, pid, F012);
      const kept = await call(t.http, {
        method: 'POST',
        url: `/disputes/${body.dispute.dispute_id}/resolve`,
        session: inspector,
        ifMatch: card.row_version,
        body: { resolution: 'KEPT_CLARIFICATION', seen_fingerprint: card.evidence_fingerprint },
      });
      expect(kept.statusCode).toBe(200);
      const after = kept.json() as Json;
      expect(after.decision).toMatchObject({ decision: 'CLARIFICATION_REQUIRED', clarify_code: 'AWAITING_APPROVAL_CHECK' });
      expect(after.dispute.resolution_status).toBe('KEPT_CLARIFICATION');
      const disputes = (await call(t.http, { url: `/processes/${pid}/disputes`, session: inspector })).json() as Json;
      expect(disputes.items).toHaveLength(1);
    });

    it('validate: dry run shows the verdict without writing anything', async () => {
      const card = await getCard(t.http, inspector, pid, F314);
      const res = await call(t.http, {
        method: 'POST',
        url: `/processes/${pid}/findings/${F314}/decisions/validate`,
        session: inspector,
        body: { decision: 'NEGATIVE_VERIFIED', reason_code: 'WITHIN_TOLERANCE', comment: 'x', seen_fingerprint: card.evidence_fingerprint },
      });
      expect(res.statusCode).toBe(200);
      expect(res.json()).toMatchObject({ effective_status: 'CLARIFICATION_REQUIRED', opens_dispute: true, ai: { verdict: 'DISAGREE' }, warnings: [] });
      expect(decisionRows()).toHaveLength(0);
    });
  });

  describe('concurrency and idempotency (05 §3.13)', () => {
    it('428 without If-Match; 409 VERSION_CONFLICT with who/what/when; 409 EVIDENCE_CHANGED on a stale card', async () => {
      const card = await getCard(t.http, inspector, pid, F270);
      const base = { method: 'POST' as const, url: `/processes/${pid}/findings/${F270}/decisions`, session: inspector };
      const body = { decision: 'CONFIRMED_VIOLATION', comment: card.prefill.confirm_comment, seen_fingerprint: card.evidence_fingerprint };
      const noIfMatch = await call(t.http, { ...base, body });
      expect(noIfMatch.statusCode).toBe(428);
      expect((noIfMatch.json() as Json).code).toBe('PRECONDITION_REQUIRED');
      const stalePrint = await call(t.http, { ...base, ifMatch: 1, body: { ...body, seen_fingerprint: 'f'.repeat(64) } });
      expect((stalePrint.json() as Json).code).toBe('EVIDENCE_CHANGED');
      const other = await login(t.http, 'inspector3');
      expect((await confirm(t.http, other, pid, F270)).statusCode).toBe(201);
      const conflict = await call(t.http, { ...base, ifMatch: 1, body });
      expect(conflict.statusCode).toBe(409);
      const p = conflict.json() as Json;
      expect(p.code).toBe('VERSION_CONFLICT');
      expect(p.detail).toMatch(/^Решение по карточке уже изменено: Смирнова Ольга Павловна, Подтверждено, \d\d\.\d\d, \d\d:\d\d\.$/);
      expect(p.details).toMatchObject({ row_version: 2, inspector_status: 'CONFIRMED_VIOLATION' });
      // «Заменить своим решением»: fresh If-Match + override_of_decision_id → DECISION_OVERRIDE.
      const override = await call(t.http, {
        ...base,
        ifMatch: 2,
        body: { decision: 'NEGATIVE_VERIFIED', reason_code: 'EQUIVALENT_SOLUTION', comment: 'Решения равнозначны', seen_fingerprint: card.evidence_fingerprint, override_of_decision_id: p.details.decision_id },
      });
      expect(override.statusCode).toBe(201);
      expect(t.audit.rows.map((r) => r.action)).toContain('DECISION_OVERRIDE');
    });

    it('two parallel decisions with the same If-Match: exactly one 201 and one 409', async () => {
      const card = await getCard(t.http, inspector, pid, F271);
      const second = await login(t.http, 'inspector3');
      const send = (s: Session) =>
        call(t.http, {
          method: 'POST',
          url: `/processes/${pid}/findings/${F271}/decisions`,
          session: s,
          ifMatch: card.row_version,
          body: { decision: 'CONFIRMED_VIOLATION', comment: card.prefill.confirm_comment, seen_fingerprint: card.evidence_fingerprint },
        });
      const results = await Promise.all([send(inspector), send(second)]);
      expect(results.map((r) => r.statusCode).sort()).toEqual([201, 409]);
      expect(decisionRows().filter((d) => d.findingId === F271)).toHaveLength(1);
    });

    it('Idempotency-Key: a replay returns the stored response once; another body with the key → 422', async () => {
      const key = idemKey();
      const first = await decide(t.http, inspector, pid, F272, { decision: 'CONFIRMED_VIOLATION', comment: 'Подтверждаю' }, { key, ifMatch: 1 });
      const replay = await decide(t.http, inspector, pid, F272, { decision: 'CONFIRMED_VIOLATION', comment: 'Подтверждаю' }, { key, ifMatch: 1 });
      expect(first.statusCode).toBe(201);
      expect(replay.statusCode).toBe(201);
      expect(replay.headers['idempotency-replayed']).toBe('true');
      expect(replay.json()).toEqual(first.json());
      expect(decisionRows().filter((d) => d.findingId === F272)).toHaveLength(1);
      const reused = await decide(t.http, inspector, pid, F272, { decision: 'CONFIRMED_VIOLATION', comment: 'Другой текст' }, { key, ifMatch: 1 });
      expect(reused.statusCode).toBe(422);
      expect((reused.json() as Json).code).toBe('IDEMPOTENCY_KEY_REUSED');
      const missing = await call(t.http, { method: 'POST', url: `/processes/${pid}/findings/${F272}/decisions`, session: inspector, key: null, ifMatch: 2, body: { decision: 'CONFIRMED_VIOLATION', comment: 'x', seen_fingerprint: 'a'.repeat(64) } });
      expect(missing.statusCode).toBe(400);
    });

    it('a failed commit rolls back the decision, the check and the logs together', async () => {
      t.repo.failNextCommit = new Error('simulated commit failure');
      const res = await decide(t.http, inspector, pid, F267, { decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: 'Ошибка OCR' });
      expect(res.statusCode).toBe(500);
      expect(decisionRows()).toHaveLength(0);
      expect(t.repo.state.rejections).toHaveLength(0);
      expect(checkOf(F267)).toMatchObject({ inspectorStatus: 'PENDING', rowVersion: 1 });
    });
  });

  describe('RBAC and hidden-test integrity', () => {
    it('any inspector (scope ALL, no assignment needed) sees the process; no CSRF → 403; no session → 401', async () => {
      const card = await getCard(t.http, inspector, pid, F012);
      const other = await login(t.http, 'inspector2');
      const visible = await call(t.http, { url: `/processes/${pid}/verification`, session: other });
      expect(visible.statusCode).toBe(200);
      const noCsrf = await call(t.http, { method: 'POST', url: `/processes/${pid}/findings/${F012}/decisions`, session: { ...inspector, csrf: 'x'.repeat(43) }, ifMatch: 1, body: { decision: 'CONFIRMED_VIOLATION', comment: 'x', seen_fingerprint: card.evidence_fingerprint } });
      expect((noCsrf.json() as Json).code).toBe('CSRF_TOKEN_INVALID');
      const anonymous = await call(t.http, { url: `/processes/${pid}/verification` });
      expect(anonymous.statusCode).toBe(401);
    });

    it('a TEST_HIDDEN object is never shown or decided (CLAUDE.md rule 4)', async () => {
      pid = seedTyumen(t.repo, 'TEST_HIDDEN');
      const supervisor = await login(t.http, 'inspector2');
      for (const url of [`/processes/${pid}/verification`, `/processes/${pid}/findings`, `/processes/${pid}/findings/${F012}`, `/objects/${TYUMEN}/verification`]) {
        const res = await call(t.http, { url, session: supervisor });
        expect(res.statusCode, url).toBe(403);
        expect((res.json() as Json).code).toBe('HIDDEN_TEST_ACCESS_DENIED');
      }
    });
  });

  describe('finalization (ТЗ §9.3 п.4–5) and un-finalization', () => {
    const decideAll = async () => {
      for (const id of ALL) {
        if (id === F140) {
          const res = await decide(t.http, inspector, pid, id, { decision: 'NEGATIVE_VERIFIED', reason_code: 'LINKING_ERROR', comment: 'Сопоставлены разные помещения' });
          expect(res.statusCode).toBe(201);
        } else if (id === F198) {
          const res = await decide(t.http, inspector, pid, id, { decision: 'CLARIFICATION_REQUIRED', clarify_code: 'AWAITING_DOCUMENT', comment: 'Ожидается исполнительная схема' });
          expect(res.statusCode).toBe(201);
        } else {
          expect((await confirm(t.http, inspector, pid, id)).statusCode).toBe(201);
        }
      }
    };
    const finalize = async (s: Session, body: Json, ifMatch?: number) => {
      const current = await summary(s);
      return call(t.http, { method: 'POST', url: `/processes/${pid}/finalize`, session: s, ifMatch: ifMatch ?? current.row_version, body });
    };

    it('is blocked while candidates are pending (409 + the list), needs a password confirmation, then seals v2', async () => {
      await confirm(t.http, inspector, pid, F012);
      const blocked = await finalize(inspector, { reauth_token: await reauth(t.http, inspector) });
      expect(blocked.statusCode).toBe(409);
      const problem = blocked.json() as Json;
      expect(problem.code).toBe('FINALIZE_GATE_BLOCKED');
      expect(problem.detail).toBe('Финализация невозможна: не обработано кандидатов — 9. Примите решение или переведите их в CLARIFICATION_REQUIRED.');
      expect(problem.errors[0].details).toMatchObject({ blocker: 'PENDING_CANDIDATE', count: 9 });

      for (const id of ALL.filter((x) => x !== F012)) {
        if (id === F140) await decide(t.http, inspector, pid, id, { decision: 'NEGATIVE_VERIFIED', reason_code: 'LINKING_ERROR', comment: 'Сопоставлены разные помещения' });
        else if (id === F198) await decide(t.http, inspector, pid, id, { decision: 'CLARIFICATION_REQUIRED', clarify_code: 'AWAITING_DOCUMENT', comment: 'Ожидается исполнительная схема' });
        else await confirm(t.http, inspector, pid, id);
      }
      const s = await summary();
      expect(s).toMatchObject({ status: 'COMPLETED', verification_status: 'VERIFICATION_COMPLETED', counts: { pending: 0, confirmed: 8, negative: 1, clarification: 1 } });
      expect(s.gate).toMatchObject({ can_finalize: true, blockers: [] });
      expect(s.gate.warnings.map((w: Json) => w.code)).toEqual(['CLARIFICATION_KEPT']);
      expect(t.audit.rows.map((r) => r.action)).toContain('VERIFICATION_COMPLETED');

      const noToken = await finalize(inspector, {});
      expect(noToken.statusCode).toBe(401);
      expect((noToken.json() as Json).code).toBe('REAUTH_REQUIRED');
      const stale = await finalize(inspector, { reauth_token: await reauth(t.http, inspector) }, 1);
      expect((stale.json() as Json).code).toBe('VERSION_CONFLICT');

      const res = await finalize(inspector, { reauth_token: await reauth(t.http, inspector) });
      expect(res.statusCode).toBe(200);
      const fin = res.json() as Json;
      expect(fin).toMatchObject({ status: 'FINALIZED', verification_status: 'PROTOCOL_FINALIZED', counts: { confirmed: 8, negative: 1, clarification: 1 }, dataset_items: 9, rin: { violations: 8, transfer_allowed: true } });
      expect(fin.protocol).toMatchObject({ version: 2, status: 'PROTOCOL_FINALIZED', is_final: true, version_reason: 'FINALIZATION', finalized_by: { full_name: 'Иванова Мария Сергеевна' } });
      const [v1, v2] = t.repo.state.protocols;
      expect(v1).toMatchObject({ version: 1, status: 'SUPERSEDED', supersededReason: 'FINALIZATION' });
      const content = v2!.contentJson as Json;
      const valid = contractSchemas().validate('protocol', content);
      expect(valid.valid ? [] : valid.errors).toEqual([]);
      expect(content.header).toMatchObject({ version_line: '2 (окончательная)', status_line: '🔒 ПРОТОКОЛ ФИНАЛИЗИРОВАН (дозагрузка невозможна)' });
      expect(content.appendix2.section4_critical.rows.map((r: Json) => r.inspector_decision_ru)).toEqual(['✅ Подтверждено', '✅ Подтверждено', '✅ Подтверждено']);
      expect(content.appendix2.section6_ai_suspicions.rows[0]).toMatchObject({ inspector_status: 'CONVERTED_TO_CANDIDATE', inspector_decision_ru: '✅ Подтверждено' });
      expect(content.tz92_tables.a4_negative_verified.filter((r: Json) => r.decided_by === 'INSPECTOR')).toEqual([
        expect.objectContaining({ card_ref: 'Б.3', locations: ['140'], reason_code: 'LINKING_ERROR' }),
      ]);
      expect(content.signature).toMatchObject({ inspector_name: 'Иванова Мария Сергеевна', content_sha256: content.content_sha256 });
      // Failed attempts are audited with the attempted action (FAILURE / DENIED); one success.
      const finalizeRows = t.audit.rows.filter((r) => r.action === 'PROTOCOL_FINALIZED');
      expect(finalizeRows.map((r) => r.result)).toEqual(['FAILURE', 'DENIED', 'FAILURE', 'SUCCESS']);
      expect(finalizeRows.at(-1)!.details).toMatchObject({ sign_method: 'SIMPLE_EP_REAUTH', dataset_items: 9 });

      // Replay of the finalization is idempotent and needs no new token.
      const protocols = await call(t.http, { url: `/processes/${pid}/protocol`, session: inspector });
      expect((protocols.json() as Json).protocol.version).toBe(2);
      const v1Read = await call(t.http, { url: `/processes/${pid}/protocol?version=1`, session: inspector });
      expect((v1Read.json() as Json).protocol.status).toBe('SUPERSEDED');
    });

    it('after finalization nothing changes (423); GOLD drafts = final CONFIRMED/NEGATIVE only; РиН gets confirmed only', async () => {
      await decideAll();
      const fin = await finalize(inspector, { reauth_token: await reauth(t.http, inspector) });
      expect(fin.statusCode).toBe(200);
      const locked = await decide(t.http, inspector, pid, F314, { decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: 'x' });
      expect(locked.statusCode).toBe(423);
      expect((locked.json() as Json).code).toBe('PROTOCOL_FINALIZED');
      const s = await summary();
      const reopen = await call(t.http, { method: 'POST', url: `/processes/${pid}/verification/reopen`, session: inspector, ifMatch: s.row_version, body: {} });
      expect(reopen.statusCode).toBe(423);
      const twice = await finalize(inspector, { reauth_token: 'x'.repeat(43) });
      expect(twice.statusCode).toBe(423);

      const ml = inspector;
      const items = (await call(t.http, { url: `/ml/datasets/draft/items?process_id=${pid}`, session: ml })).json() as Json;
      expect(items.total).toBe(9);
      const labels = items.items.map((i: Json) => `${i.gold_label}:${i.gold_record.location}`).sort();
      expect(labels).toEqual(['NEGATIVE:140', 'POSITIVE:012', 'POSITIVE:142', 'POSITIVE:147', 'POSITIVE:267', 'POSITIVE:270', 'POSITIVE:271', 'POSITIVE:272', 'POSITIVE:314']);
      for (const item of items.items) {
        expect(item).toMatchObject({ status: 'DRAFT', split: 'TRAIN', source_type: 'PRODUCTION', training_eligible: true, dataset_version: null, expert: { full_name: 'Иванова Мария Сергеевна' } });
        const gold = contractSchemas().validate('gold_check', item.gold_record);
        expect(gold.valid ? [] : gold.errors).toEqual([]);
        expect(item.evidence_card.sources.length).toBeGreaterThanOrEqual(2);
        expect(item.versions).toMatchObject({ protocol_version: 2, matrix_version: '1.1.0' });
      }

      const rin = (await call(t.http, { url: `/processes/${pid}/rin-payload/preview`, session: inspector })).json() as Json;
      expect(rin.transfer_allowed).toBe(true);
      expect(rin.violations).toHaveLength(8);
      expect(rin.violations.every((v: Json) => v.decision.status === 'CONFIRMED_VIOLATION')).toBe(true);
      expect(rin.violations.map((v: Json) => v.location)).not.toContain('140');
      expect(rin.violations.map((v: Json) => v.location)).not.toContain('198');
    });

    it('un-finalize: needs a valid password token, a reason ≥ 20 chars and a password; v3 working version; drafts suspended', async () => {
      await decideAll();
      expect((await finalize(inspector, { reauth_token: await reauth(t.http, inspector) })).statusCode).toBe(200);
      const url = `/processes/${pid}/unfinalize`;
      const s = await summary();
      const byInspector = await call(t.http, { method: 'POST', url, session: inspector, ifMatch: s.row_version, body: { reason_code: 'DECISION_ERROR', reason_text: 'Ошибка в решении по помещению 140', reauth_token: 'x'.repeat(43) } });
      expect(byInspector.statusCode).toBe(401);
      expect((byInspector.json() as Json).code).toBe('REAUTH_REQUIRED');
      const supervisor = await login(t.http, 'inspector2');
      const s2 = await summary(supervisor);
      expect(s2.capabilities.can_unfinalize).toBe(true);
      const noReason = await call(t.http, { method: 'POST', url, session: supervisor, ifMatch: s2.row_version, body: { reason_code: 'DECISION_ERROR', reason_text: 'коротко' } });
      expect(noReason.statusCode).toBe(422);
      expect((noReason.json() as Json).code).toBe('UNFINALIZE_REASON_REQUIRED');
      const res = await call(t.http, {
        method: 'POST',
        url,
        session: supervisor,
        ifMatch: s2.row_version,
        body: { reason_code: 'DECISION_ERROR', reason_text: 'Ошибка в решении по помещению 140: нужна повторная проверка', reauth_token: await reauth(t.http, supervisor) },
      });
      expect(res.statusCode).toBe(200);
      const body = res.json() as Json;
      expect(body).toMatchObject({ status: 'COMPLETED', verification_status: 'VERIFICATION_COMPLETED', suspended_dataset_items: 9, protocol: { version: 3, version_reason: 'UNFINALIZATION', is_final: false } });
      const versions = t.repo.state.protocols.map((p) => [p.version, p.status, p.supersededReason]);
      expect(versions).toEqual([
        [1, 'SUPERSEDED', 'FINALIZATION'],
        [2, 'SUPERSEDED', 'UNFINALIZED'],
        [3, 'VERIFICATION_COMPLETED', null],
      ]);
      expect(t.repo.state.protocols[1]!.finalizedAt).not.toBeNull();
      expect(t.repo.state.datasetItems.every((d) => d.status === 'SUSPENDED')).toBe(true);
      const unfinalizeRows = t.audit.rows.filter((r) => r.action === 'PROTOCOL_UNFINALIZED');
      expect(unfinalizeRows.map((r) => [r.result, r.userId])).toEqual([
        ['DENIED', inspector.userId],
        ['FAILURE', supervisor.userId],
        ['SUCCESS', supervisor.userId],
      ]);
      const audit = unfinalizeRows.at(-1)!;
      expect(audit.details).toMatchObject({ reason_code: 'DECISION_ERROR' });
      const v3 = t.repo.state.protocols[2]!.contentJson as Json;
      expect(contractSchemas().validate('protocol', v3).valid).toBe(true);
      expect(v3.header.version_line).toBe('3 (предварительная)');
      expect(v3.signature).toBeNull();

      // Decisions need «Возобновить верификацию» first, then work again.
      const blocked = await decide(t.http, inspector, pid, F140, { decision: 'CONFIRMED_VIOLATION', comment: 'Подтверждаю' });
      expect((blocked.json() as Json).code).toBe('VERIFICATION_NOT_ALLOWED_IN_STATUS');
      const s3 = await summary();
      const reopen = await call(t.http, { method: 'POST', url: `/processes/${pid}/verification/reopen`, session: inspector, ifMatch: s3.row_version, body: { comment: 'Повторная проверка решений' } });
      expect(reopen.statusCode).toBe(200);
      expect(reopen.json()).toMatchObject({ status: 'VERIFYING', verification_status: 'IN_VERIFICATION' });
      const changed = await confirm(t.http, inspector, pid, F140);
      expect(changed.statusCode).toBe(201);
      expect((changed.json() as Json).process.status).toBe('COMPLETED');
    });

    it('undo within 10 s of the last decision reopens a COMPLETED verification (Ctrl+Z)', async () => {
      await decideAll();
      expect((await summary()).status).toBe('COMPLETED');
      const undo = await decide(t.http, inspector, pid, F272, { decision: 'REVERT_TO_PENDING' });
      expect(undo.statusCode).toBe(201);
      expect((undo.json() as Json).process).toMatchObject({ status: 'VERIFYING', pending: 1 });
    });

    it('claim takes a READY protocol into work and assigns the inspector', async () => {
      const res = await call(t.http, { method: 'POST', url: `/processes/${pid}/verification/claim`, session: inspector, ifMatch: 1 });
      expect(res.statusCode).toBe(200);
      expect(res.json()).toMatchObject({ status: 'VERIFYING', row_version: 2, assigned_inspector_id: inspector.userId });
      expect(res.headers.etag).toBe('"2"');
    });
  });

  describe('GOLD capture reproduces the organizers’ train gold', () => {
    const goldFile = path.resolve(REPO_CONTRACTS, '..', '..', 'data_utf8', 'ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0', 'data', 'public_train_checks.jsonl');
    it.runIf(existsSync(goldFile))('confirming the 10 Тюменская candidates yields drafts equal to public_train_checks.jsonl on every key field', async () => {
      for (const id of ALL) expect((await confirm(t.http, inspector, pid, id)).statusCode).toBe(201);
      const s = await summary();
      const fin = await call(t.http, { method: 'POST', url: `/processes/${pid}/finalize`, session: inspector, ifMatch: s.row_version, body: { reauth_token: await reauth(t.http, inspector) } });
      expect(fin.statusCode).toBe(200);
      const drafts = t.repo.state.datasetItems.map((d) => d.goldRecord as Json);
      const gold = readFileSync(goldFile, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l) as Json).filter((g) => g.object_id === TYUMEN);
      const key = (r: Json) => [r.parameter_code, r.location].join('·');
      const project = (r: Json) => ({
        parameter_code: r.parameter_code,
        location: r.location,
        location_type: r.location_type,
        matrix_scope: r.matrix_scope,
        violation_label: r.violation_label,
        protocol_status: r.protocol_status,
        criticality: r.criticality,
        inspector_status: r.inspector_status,
        evidence: (r.evidence as Json[]).map((e) => [e.stage, e.file_id, e.pdf_page_number]),
      });
      expect(drafts.map(key).sort()).toEqual(gold.map(key).sort());
      const byKey = new Map(drafts.map((d) => [key(d), project(d)]));
      for (const g of gold) expect(byKey.get(key(g)), key(g)).toEqual(project(g));
    });
  });

  describe('usability telemetry (ТЗ §9.3)', () => {
    it('records clicks and time per card from decisions and UI events; reports against 30 min / 3 clicks', async () => {
      const ev = await call(t.http, {
        method: 'POST',
        url: '/telemetry/ui-events',
        session: inspector,
        key: null,
        body: { session_id: '11111111-1111-4111-8111-111111111111', process_id: pid, events: [{ type: 'SESSION_START', ts_client: new Date(Date.now() - 60_000).toISOString(), input: 'KEYBOARD' }] },
      });
      expect(ev.statusCode).toBe(202);
      expect(ev.json()).toEqual({ accepted: 1 });
      const metrics = [
        { clicks: 2, keys: 0, time_on_card_ms: 21_000, input: 'MOUSE' },
        { clicks: 0, keys: 2, time_on_card_ms: 9_000, input: 'KEYBOARD' },
        { clicks: 3, keys: 1, time_on_card_ms: 34_000, input: 'MIXED' },
      ];
      for (const [i, id] of [F012, F140, F142].entries()) {
        const card = await getCard(t.http, inspector, pid, id);
        await call(t.http, {
          method: 'POST',
          url: `/processes/${pid}/findings/${id}/decisions`,
          session: inspector,
          ifMatch: card.row_version,
          body: { decision: 'CONFIRMED_VIOLATION', comment: card.prefill.confirm_comment, comment_source: 'TEMPLATE', seen_fingerprint: card.evidence_fingerprint, client_metrics: metrics[i] },
        });
      }
      const r = (await call(t.http, { url: `/processes/${pid}/usability`, session: inspector })).json() as Json;
      expect(r).toMatchObject({ decisions: 3, measured_decisions: 3, inspectors: 1, keyboard_only_share: 0.333, targets: { protocol_minutes: 30, clicks_per_decision: 3 }, met: { protocol_time: true, clicks: true } });
      expect(r.clicks).toMatchObject({ median: 2, max: 3, share_within_target: 1 });
      expect(r.time_on_card_ms).toMatchObject({ median: 21_000, max: 34_000 });
      expect(r.protocol_time_ms).toBeGreaterThanOrEqual(60_000);
    });
  });

  describe('object view', () => {
    it('lists the object’s verification sessions (every inspector, scope ALL)', async () => {
      const res = await call(t.http, { url: `/objects/${TYUMEN}/verification`, session: inspector });
      expect(res.statusCode).toBe(200);
      const body = res.json() as Json;
      expect(body.processes).toHaveLength(1);
      expect(body.processes[0].process_id).toBe(pid);
      // The protocol's object name beats the registry label (as on the dashboard and objects list).
      const protocolName = (d1Fixture().protocol as Json).object.name as string;
      expect(protocolName).toBeTruthy();
      expect(body.object_name).toBe(protocolName);
      expect(body.processes[0].object.name).toBe(protocolName);
      const other = await login(t.http, 'inspector2');
      expect((await call(t.http, { url: `/objects/${TYUMEN}/verification`, session: other })).statusCode).toBe(200);
    });
  });
});

describe('decisions never reach a submission (97 §1.4)', () => {
  it('the verification module neither writes run directories nor touches submission tables', () => {
    const dir = path.resolve(__dirname, '..', '..', 'src', 'modules', 'verification');
    const sources = readdirSync(dir, { recursive: true }).map(String).filter((f) => f.endsWith('.ts'));
    for (const f of sources) {
      const code = readFileSync(path.join(dir, f), 'utf8')
        .split('\n')
        .filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l))
        .join('\n');
      expect(code, f).not.toMatch(/submissionExports|submission_exports|writeFileSync|writeFile\(|runlayout|RunLayout/);
    }
  });
});

/** The minimal Protocol envelope around one card (to validate an EvidenceCard with the contract schema). */
function fixtureProtocolShell(): Json {
  const p = JSON.parse(readFileSync(path.resolve(__dirname, '..', '..', 'fixtures', 'd1', `${TYUMEN}.protocol.json`), 'utf8')) as Json;
  return p;
}
