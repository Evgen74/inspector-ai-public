/** M2 backlog #4: the protocol view shows the decisions of the same process as the verification workspace. */
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { VerificationService } from '../../src/modules/verification/verification.service';
import { confirm, createVerificationApp, d1Fixture, FID, login, seedTyumen, seedUsers, TYUMEN, type Session, type VerificationTestApp } from './harness';

type Json = Record<string, any>;

describe('decisions overlay for the protocol view', () => {
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
    t.sessions.sessions.clear();
    pid = seedTyumen(t.repo);
    inspector = await login(t.http, 'inspector');
  });

  it('turns «Ожидает» into the inspector decision and keeps the version of the base document', async () => {
    const service = t.app.get(VerificationService);
    const base = d1Fixture().protocol as unknown as Json;
    const runId = t.repo.state.processes.find((p) => p.id === pid)!.activeRunId;
    const before = (await service.decisionsOverlay(runId, TYUMEN, base)) as Json;
    expect(before.evidence_cards.every((c: Json) => c.inspector.status === 'PENDING')).toBe(true);

    const f012 = FID('IOS4-079-PDRD-012');
    expect((await confirm(t.http, inspector, pid, f012)).statusCode).toBe(201);
    const after = (await service.decisionsOverlay(runId, TYUMEN, base)) as Json;
    const decided = after.evidence_cards.filter((c: Json) => c.inspector.status === 'CONFIRMED_VIOLATION');
    expect(decided.length).toBeGreaterThanOrEqual(1);
    expect(after.version).toBe(base.version);
    expect(after.is_final).toBe(false);
    // the source document is untouched
    expect(base.evidence_cards.some((c: Json) => c.inspector?.status === 'CONFIRMED_VIOLATION')).toBe(false);
  });

  it('returns null for a run without a process of the object', async () => {
    const service = t.app.get(VerificationService);
    expect(await service.decisionsOverlay('00000000-0000-4000-8000-000000000000', TYUMEN, d1Fixture().protocol as unknown as Json)).toBeNull();
  });
});
