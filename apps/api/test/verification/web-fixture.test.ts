/**
 * The web workspace is tested against real API responses, not invented mocks: this test replays one verification
 * session of Тюменская 5 through the real AppModule (auth required, OpenAPI request AND response validation on)
 * and records every response the web uses into apps/web/src/features/verification/fixtures/tyumen.api.json.
 *
 * Volatile values are normalized (UUIDs by order of appearance, timestamps created during the run, the hash of
 * the sealed protocol, the wall-clock protocol time), so the recording is deterministic and the committed file is
 * a drift guard: when the API changes a response, this test fails until the fixture is re-recorded:
 *
 *   cd apps/api && UPDATE_WEB_FIXTURE=1 pnpm exec vitest run test/verification/web-fixture.test.ts
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  call,
  confirm,
  createVerificationApp,
  decide,
  FID,
  getCard,
  login,
  reauth,
  seedTyumen,
  seedUsers,
  TYUMEN,
  type VerificationTestApp,
} from './harness';

type Json = Record<string, any>;

const OUT = path.resolve(__dirname, '..', '..', '..', 'web', 'src', 'features', 'verification', 'fixtures', 'tyumen.api.json');
const D1 = path.resolve(__dirname, '..', '..', 'fixtures', 'd1');

const F012 = FID('IOS4-079-PDRD-012');
const F140 = FID('IOS4-078-PDRD-140');
const F147 = FID('IOS4-078-PDRD-147');
const F198 = FID('IOS4-078-PDRD-198');

/** Client metrics the recorded decisions carry (the usability report is computed from them). */
const METRICS = {
  keyboard: { time_on_card_ms: 9_000, clicks: 0, keys: 2, input: 'KEYBOARD' },
  mouse: { time_on_card_ms: 21_000, clicks: 2, keys: 0, input: 'MOUSE' },
  reject: { time_on_card_ms: 34_000, clicks: 3, keys: 0, input: 'MOUSE' },
};

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
const ISO_RE = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g;
export const FIXED_TIME = '2026-09-28T09:00:00.000Z';
const SEALED_SHA256 = 'a'.repeat(64);

/** Deterministic form of a recording (see the header). `stableSha` = the imported protocol's content hash. */
export function normalizeRecording(recording: Json, stableTimes: ReadonlySet<string>, stableSha: string): Json {
  const walk = (v: unknown, key: string | null): unknown => {
    if (Array.isArray(v)) return v.map((x) => walk(x, null));
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v as Json).map(([k, x]) => [k, walk(x, k)]));
    if (key === 'content_sha256' && typeof v === 'string' && v !== stableSha) return SEALED_SHA256;
    if (key === 'protocol_time_ms' && typeof v === 'number') return 754_000;
    if (key === 'csrf_token' && typeof v === 'string') return 'fixture-csrf-token';
    return v;
  };
  let text = JSON.stringify(walk(recording, null), null, 2);
  const ids = new Map<string, string>();
  text = text.replace(UUID_RE, (u) => {
    const lower = u.toLowerCase();
    if (!ids.has(lower)) ids.set(lower, `00000000-0000-4000-8000-${(ids.size + 1).toString(16).padStart(12, '0')}`);
    return ids.get(lower)!;
  });
  text = text.replace(ISO_RE, (t) => (stableTimes.has(t) ? t : FIXED_TIME));
  return JSON.parse(text) as Json;
}

describe('web fixture recorded from the real verification API', () => {
  let t: VerificationTestApp;

  beforeAll(async () => {
    t = await createVerificationApp();
  });
  afterAll(async () => {
    await t.close();
  });

  it('matches apps/web/src/features/verification/fixtures/tyumen.api.json (UPDATE_WEB_FIXTURE=1 re-records)', async () => {
    await seedUsers(t.users);
    const pid = seedTyumen(t.repo);
    const inspector = await login(t.http, 'inspector');
    const get = async (url: string, session = inspector): Promise<Json> => {
      const res = await call(t.http, { url, session });
      expect(res.statusCode, `${url}: ${res.body}`).toBe(200);
      return res.json() as Json;
    };
    const ok = (res: { statusCode: number; body: string }, status = 201): Json => {
      expect(res.statusCode, res.body).toBe(status);
      return JSON.parse(res.body) as Json;
    };

    // Initial state: an imported protocol, 10 candidates pending.
    const queue0 = await get(`/processes/${pid}/findings`);
    const ids: string[] = queue0.items.map((i: Json) => i.finding_id);
    const cards0: Json = {};
    for (const id of ids) cards0[id] = await get(`/processes/${pid}/findings/${encodeURIComponent(id)}`);
    const recording: Json = {
      process_id: pid,
      object_id: TYUMEN,
      finding_ids: ids,
      sessions: { inspector: await get('/auth/me') },
      codes: await get('/dictionaries/decision-codes'),
      object: await get(`/objects/${TYUMEN}/verification`),
      initial: {
        summary: await get(`/processes/${pid}/verification`),
        queue: queue0,
        cards: cards0,
        completeness: await get(`/processes/${pid}/completeness`),
        usability: await get(`/processes/${pid}/usability`),
      },
    };

    // Confirm (C, Enter): READY → VERIFYING, auto-advance.
    const c012 = await getCard(t.http, inspector, pid, F012);
    const confirmed = ok(
      await call(t.http, {
        method: 'POST',
        url: `/processes/${pid}/findings/${encodeURIComponent(F012)}/decisions`,
        session: inspector,
        ifMatch: c012.row_version,
        body: {
          decision: 'CONFIRMED_VIOLATION',
          basis_code: c012.prefill.confirm_basis_code,
          comment: c012.prefill.confirm_comment,
          comment_source: 'TEMPLATE',
          seen_fingerprint: c012.evidence_fingerprint,
          client_metrics: METRICS.keyboard,
        },
      }),
    );
    // Reject with the AI agreeing (R, 3, Enter).
    const c140 = await getCard(t.http, inspector, pid, F140);
    const rejected = ok(
      await decide(t.http, inspector, pid, F140, {
        decision: 'NEGATIVE_VERIFIED',
        reason_code: 'LINKING_ERROR',
        comment: c140.prefill.reject_comments.LINKING_ERROR,
        comment_source: 'TEMPLATE',
        client_metrics: METRICS.reject,
      }),
    );
    // Reject that the AI disputes (WITHIN_TOLERANCE on a configuration change → R-TOL-1, Dispute_Log OPEN).
    const c147 = await getCard(t.http, inspector, pid, F147);
    const disputed = ok(
      await decide(t.http, inspector, pid, F147, {
        decision: 'NEGATIVE_VERIFIED',
        reason_code: 'WITHIN_TOLERANCE',
        comment: c147.prefill.reject_comments.WITHIN_TOLERANCE,
        comment_source: 'TEMPLATE',
        client_metrics: METRICS.reject,
      }),
    );
    recording.after_dispute = {
      summary: await get(`/processes/${pid}/verification`),
      queue: await get(`/processes/${pid}/findings`),
      card: await get(`/processes/${pid}/findings/${encodeURIComponent(F147)}`),
    };
    // «Подтвердить нарушение» in the dispute banner (AI_UPHELD).
    const d147 = await getCard(t.http, inspector, pid, F147);
    const resolved = ok(
      await call(t.http, {
        method: 'POST',
        url: `/disputes/${disputed.dispute.dispute_id}/resolve`,
        session: inspector,
        ifMatch: d147.row_version,
        body: { resolution: 'AI_UPHELD', seen_fingerprint: d147.evidence_fingerprint },
      }),
      200,
    );
    // Clarify (U, 5, Enter) and confirm the rest with the mouse (2 clicks each).
    const c198 = await getCard(t.http, inspector, pid, F198);
    const clarified = ok(
      await decide(t.http, inspector, pid, F198, {
        decision: 'CLARIFICATION_REQUIRED',
        clarify_code: 'AWAITING_DOCUMENT',
        comment: c198.prefill.clarify_comments.AWAITING_DOCUMENT,
        comment_source: 'TEMPLATE',
        client_metrics: METRICS.keyboard,
      }),
    );
    for (const id of ids.filter((x) => ![F012, F140, F147, F198].includes(x))) {
      const card = await getCard(t.http, inspector, pid, id);
      ok(
        await call(t.http, {
          method: 'POST',
          url: `/processes/${pid}/findings/${encodeURIComponent(id)}/decisions`,
          session: inspector,
          ifMatch: card.row_version,
          body: { decision: 'CONFIRMED_VIOLATION', comment: card.prefill.confirm_comment, comment_source: 'TEMPLATE', seen_fingerprint: card.evidence_fingerprint, client_metrics: METRICS.mouse },
        }),
      );
    }
    recording.results = { confirmed, rejected, disputed, resolved, clarified };
    const completed = await get(`/processes/${pid}/verification`);
    expect(completed).toMatchObject({ status: 'COMPLETED', gate: { can_finalize: true } });
    recording.completed = {
      summary: completed,
      queue: await get(`/processes/${pid}/findings`),
      card: await get(`/processes/${pid}/findings/${encodeURIComponent(F012)}`),
      usability: await get(`/processes/${pid}/usability`),
    };

    // Finalization with the password confirmation (simple e-signature).
    const token = await reauth(t.http, inspector);
    const finalized = ok(
      await call(t.http, { method: 'POST', url: `/processes/${pid}/finalize`, session: inspector, ifMatch: completed.row_version, body: { reauth_token: token } }),
      200,
    );
    recording.finalized = {
      result: finalized,
      summary: await get(`/processes/${pid}/verification`),
      queue: await get(`/processes/${pid}/findings`),
      card: await get(`/processes/${pid}/findings/${encodeURIComponent(F012)}`),
    };

    const stableTimes = new Set<string>();
    for (const f of [`${TYUMEN}.protocol.json`, `${TYUMEN}.groups.jsonl`, `${TYUMEN}.findings.jsonl`]) {
      for (const m of readFileSync(path.join(D1, f), 'utf8').matchAll(ISO_RE)) stableTimes.add(m[0]);
    }
    const normalized = normalizeRecording(recording, stableTimes, recording.initial.summary.protocol.content_sha256);

    if (process.env.UPDATE_WEB_FIXTURE) {
      mkdirSync(path.dirname(OUT), { recursive: true });
      writeFileSync(OUT, `${JSON.stringify(normalized, null, 2)}\n`);
    }
    expect(existsSync(OUT), `${OUT} is missing: re-record with UPDATE_WEB_FIXTURE=1`).toBe(true);
    const committed = JSON.parse(readFileSync(OUT, 'utf8')) as Json;
    // A mismatch means the API changed a response the web relies on: re-record (see the header) and re-run the web tests.
    expect(normalized).toEqual(committed);
  });

  it('normalizes ids by first appearance, run-time timestamps and the sealed hash only', () => {
    const out = normalizeRecording(
      {
        a: '0192f3a4-1111-7abc-8def-0123456789ab',
        b: ['0192f3a4-2222-7abc-8def-0123456789ab', '0192f3a4-1111-7abc-8def-0123456789ab'],
        at: '2026-09-28T19:03:11.123Z',
        kept: '2026-09-27T10:00:00Z',
        content_sha256: 'b'.repeat(64),
        initial: { content_sha256: 'c'.repeat(64) },
        protocol_time_ms: 12,
      },
      new Set(['2026-09-27T10:00:00Z']),
      'c'.repeat(64),
    );
    expect(out).toEqual({
      a: '00000000-0000-4000-8000-000000000001',
      b: ['00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001'],
      at: FIXED_TIME,
      kept: '2026-09-27T10:00:00Z',
      content_sha256: 'a'.repeat(64),
      initial: { content_sha256: 'c'.repeat(64) },
      protocol_time_ms: 754_000,
    });
  });
});
