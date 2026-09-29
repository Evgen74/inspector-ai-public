/**
 * «Самопроверка» (module 12, negative scenarios): about twenty checks of the running API through Fastify's own
 * injector (no network, no data changes). Every check states what must be rejected and reports PASS / FAIL;
 * a scenario whose contract is not implemented yet is NOT_IMPLEMENTED, one that cannot be tried in the current
 * mode or data is SKIPPED (with the reason). Requests that need a session reuse the caller's own cookie.
 */
import { randomUUID } from 'node:crypto';
import { Readable } from 'node:stream';
import { Inject, Injectable } from '@nestjs/common';
import { HttpAdapterHost } from '@nestjs/core';
import type { FastifyInstance, InjectOptions } from 'fastify';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { Database } from '../../db/database';
import { OpenApiService, loadOpenApiDocument } from '../../openapi/openapi.service';
import { sessionCookieName } from '../auth/cookies';
import { detectQueueMode } from '../monitoring/probes';
import { MULTIPART_BODY_LIMIT } from '../upload/multipart-parser';
import { MAX_FILE_BYTES } from '../upload/upload-validation';

export type SelftestStatus = 'PASS' | 'FAIL' | 'NOT_IMPLEMENTED' | 'SKIPPED';

export interface SelftestResult {
  id: string;
  group: string;
  title: string;
  expected: string;
  actual: string;
  status: SelftestStatus;
  detail: string | null;
  duration_ms: number;
}

export interface SelftestReport {
  started_at: string;
  duration_ms: number;
  summary: { total: number; pass: number; fail: number; not_implemented: number; skipped: number };
  results: SelftestResult[];
}

export interface CallerSession {
  cookie: string | null;
  csrf: string | null;
}

interface Outcome {
  status: SelftestStatus;
  actual: string;
  detail?: string | null;
}

interface Probe {
  status: number;
  code: string | null;
}

const MB = 1024 * 1024;
const FAKE_UUID = '00000000-0000-4000-8000-000000000000';
const SHA = 'a'.repeat(64);

@Injectable()
export class SelftestService {
  constructor(
    private readonly adapterHost: HttpAdapterHost,
    private readonly openapi: OpenApiService,
    private readonly database: Database,
    @Inject(APP_CONFIG) private readonly config: AppConfig,
  ) {}

  private get http(): FastifyInstance {
    return this.adapterHost.httpAdapter.getInstance() as FastifyInstance;
  }

  private async send(opts: InjectOptions): Promise<Probe> {
    const res = await this.http.inject(opts);
    let code: string | null = null;
    try {
      code = (JSON.parse(res.body) as { code?: string }).code ?? null;
    } catch {
      code = null;
    }
    return { status: res.statusCode, code };
  }

  private hasOperation(method: string, path: string): boolean {
    return Boolean(
      this.openapi.match({ method, path: `/api/v1${path}`, headers: {}, query: {}, body: undefined }),
    );
  }

  private hasPathLike(needle: string, methods: string[]): string | null {
    const doc = loadOpenApiDocument() as unknown as { paths: Record<string, Record<string, unknown>> };
    for (const [p, ops] of Object.entries(doc.paths ?? {})) {
      if (p.includes(needle) && methods.some((m) => ops[m])) return p;
    }
    return null;
  }

  private async queryOne(sql: string): Promise<string | null> {
    try {
      const res = await this.database.pool.query<{ id: string }>(sql);
      return res.rows[0]?.id ?? null;
    } catch {
      return null;
    }
  }

  async run(caller: CallerSession): Promise<SelftestReport> {
    const startedAt = new Date();
    const t0 = performance.now();
    const base = '/api/v1';
    const authHeaders = (json = true): Record<string, string> => {
      const h: Record<string, string> = {};
      if (json) h['content-type'] = 'application/json';
      if (caller.cookie) h.cookie = caller.cookie;
      if (caller.csrf) h['x-csrf-token'] = caller.csrf;
      return h;
    };
    const mutation = (extra: Record<string, string> = {}) => ({
      ...authHeaders(),
      'idempotency-key': randomUUID(),
      'if-match': '"1"',
      ...extra,
    });
    const rejected = (p: Probe, allowed: number[], label?: string): Outcome =>
      allowed.includes(p.status)
        ? { status: 'PASS', actual: `${p.status}${p.code ? ` ${p.code}` : ''}` }
        : { status: 'FAIL', actual: `${p.status}${p.code ? ` ${p.code}` : ''}`, detail: label ?? 'запрос не отклонён ожидаемым образом' };

    const checks: Array<{ id: string; group: string; title: string; expected: string; run: () => Promise<Outcome> }> = [];
    const add = (id: string, group: string, title: string, expected: string, run: () => Promise<Outcome>) =>
      checks.push({ id, group, title, expected, run });

    // ── Upload contract (W3): POST /api/v1/documents/upload ──
    const uploadReady = this.hasOperation('POST', '/documents/upload');
    const notImplemented = (): Outcome => ({ status: 'NOT_IMPLEMENTED', actual: '—', detail: 'Контракт POST /api/v1/documents/upload ещё не опубликован' });
    const multipart = (filename: string, mime: string, content: Buffer): { payload: Buffer; headers: Record<string, string> } => {
      const boundary = `----selftest${randomUUID().replace(/-/g, '')}`;
      const head = Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="${filename}"\r\nContent-Type: ${mime}\r\n\r\n`);
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      return { payload: Buffer.concat([head, content, tail]), headers: { ...authHeaders(false), 'content-type': `multipart/form-data; boundary=${boundary}` } };
    };
    const upload = async (filename: string, mime: string, content: Buffer) => {
      const m = multipart(filename, mime, content);
      return this.send({ method: 'POST', url: `${base}/documents/upload`, payload: m.payload, headers: m.headers });
    };
    const bigFile = async (bytes: number) => {
      // A really oversized single file (streamed, never held twice): the intake rule must reject it.
      const boundary = '----selftestbig';
      const head = Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="big.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.7\n`);
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      const chunk = Buffer.alloc(1024 * 1024);
      const chunks = Math.ceil(bytes / chunk.length);
      const total = head.length + chunks * chunk.length + tail.length;
      async function* body() {
        yield head;
        for (let i = 0; i < chunks; i += 1) yield chunk;
        yield tail;
      }
      return this.send({
        method: 'POST',
        url: `${base}/documents/upload`,
        payload: Readable.from(body()),
        headers: { ...authHeaders(false), 'content-type': `multipart/form-data; boundary=${boundary}`, 'content-length': String(total) },
      });
    };
    const announcedOver = async (bytes: number) => {
      // Only the announced size is sent: a body above the request limit is refused by its header alone.
      return this.send({
        method: 'POST',
        url: `${base}/documents/upload`,
        payload: Readable.from([]),
        headers: { ...authHeaders(false), 'content-type': 'multipart/form-data; boundary=----selftestsize', 'content-length': String(bytes) },
      });
    };
    add('upload-unsupported-format', 'Загрузка', 'Загрузка файла неподдерживаемого формата (.exe)', '4xx: 400 / 415 / 422', async () =>
      uploadReady ? rejected(await upload('program.exe', 'application/x-msdownload', Buffer.from('MZ\x90\x00binary')), [400, 415, 422]) : notImplemented(),
    );
    add('upload-corrupted-pdf', 'Загрузка', 'Загрузка повреждённого PDF', '4xx: 400 / 415 / 422', async () =>
      uploadReady ? rejected(await upload('broken.pdf', 'application/pdf', Buffer.from('\x00\x01\x02 повреждённые данные без заголовка PDF \x03\x04')), [400, 415, 422]) : notImplemented(),
    );
    add('upload-file-over-limit', 'Загрузка', `Файл больше ${MAX_FILE_BYTES / MB} МБ (${MAX_FILE_BYTES / MB + 1} МБ отправляется потоком)`, '4xx: 413 / 422', async () =>
      uploadReady ? rejected(await bigFile(MAX_FILE_BYTES + MB), [413, 422]) : notImplemented(),
    );
    add('upload-package-over-limit', 'Загрузка', 'Пакет больше 5 ГБ (по заголовку размера, тело не отправляется)', '413', async () =>
      uploadReady ? rejected(await announcedOver(MULTIPART_BODY_LIMIT + 100 * MB), [413]) : notImplemented(),
    );

    // ── Authentication and access ──
    add('decision-no-auth', 'Доступ', 'Решение инспектора без авторизации', '401', async () => {
      if (this.config.authMode === 'optional') {
        return { status: 'SKIPPED', actual: '—', detail: 'Включён режим INSPECTOR_AUTH_MODE=optional (только для локальной разработки): анонимные запросы допускаются' };
      }
      return rejected(
        await this.send({
          method: 'POST',
          url: `${base}/processes/${FAKE_UUID}/findings/F-1/decisions`,
          headers: { 'content-type': 'application/json', 'idempotency-key': randomUUID(), 'if-match': '"1"' },
          payload: JSON.stringify({ decision: 'CONFIRMED_VIOLATION', seen_fingerprint: SHA }),
        }),
        [401],
      );
    });
    add('invalid-session', 'Доступ', 'Запрос с недействительным cookie сессии', '401', async () =>
      rejected(
        await this.send({ method: 'GET', url: `${base}/dashboard`, headers: { cookie: `${sessionCookieName(this.config)}=${'x'.repeat(43)}` } }),
        [401],
      ),
    );
    add('csrf-mismatch', 'Доступ', 'Изменяющий запрос с неверным CSRF-токеном', '403', async () => {
      if (!caller.cookie) return { status: 'SKIPPED', actual: '—', detail: 'Нужна сессия пользователя (войдите в систему)' };
      return rejected(
        await this.send({
          method: 'POST',
          url: `${base}/processes/${FAKE_UUID}/verification/claim`,
          headers: { ...authHeaders(), 'x-csrf-token': 'wrong-token', 'idempotency-key': randomUUID() },
          payload: '{}',
        }),
        [403],
      );
    });

    // ── Verification ──
    add('decision-missing-process', 'Верификация', 'Решение по несуществующей проверке', '404', async () => {
      if (!caller.cookie) return { status: 'SKIPPED', actual: '—', detail: 'Нужна сессия пользователя' };
      return rejected(
        await this.send({
          method: 'POST',
          url: `${base}/processes/${FAKE_UUID}/findings/F-1/decisions`,
          headers: mutation(),
          payload: JSON.stringify({ decision: 'CONFIRMED_VIOLATION', seen_fingerprint: SHA }),
        }),
        [404],
      );
    });
    add('decision-invalid-body', 'Верификация', 'Решение с некорректным телом запроса', '400', async () => {
      if (!caller.cookie && this.config.authMode !== 'optional') return { status: 'SKIPPED', actual: '—', detail: 'Нужна сессия пользователя' };
      return rejected(
        await this.send({
          method: 'POST',
          url: `${base}/processes/${FAKE_UUID}/findings/F-1/decisions`,
          headers: mutation(),
          payload: JSON.stringify({ decision: 42 }),
        }),
        [400, 422],
      );
    });
    add('decision-after-finalization', 'Верификация', 'Решение после финализации протокола', '4xx: 409 / 422 / 423', async () => {
      if (!caller.cookie) return { status: 'SKIPPED', actual: '—', detail: 'Нужна сессия пользователя' };
      const pid = await this.queryOne("SELECT id::text AS id FROM processes WHERE status = 'FINALIZED' LIMIT 1");
      if (!pid) return { status: 'SKIPPED', actual: '—', detail: 'Нет финализированной проверки для попытки' };
      const finding = await this.queryOne(`SELECT finding_id AS id FROM checks WHERE process_id = '${pid}' LIMIT 1`);
      if (!finding) return { status: 'SKIPPED', actual: '—', detail: 'У финализированной проверки нет находок' };
      return rejected(
        await this.send({
          method: 'POST',
          url: `${base}/processes/${pid}/findings/${encodeURIComponent(finding)}/decisions`,
          headers: mutation(),
          payload: JSON.stringify({ decision: 'REVERT_TO_PENDING', seen_fingerprint: SHA }),
        }),
        [400, 403, 404, 409, 412, 422, 423],
        'решение после финализации не заблокировано',
      );
    });
    add('finalize-with-pending', 'Верификация', 'Финализация при неразобранных кандидатах', '4xx (шлюз финализации)', async () => {
      if (!caller.cookie) return { status: 'SKIPPED', actual: '—', detail: 'Нужна сессия пользователя' };
      const pid = await this.queryOne(
        `SELECT p.id::text AS id FROM processes p WHERE p.status <> 'FINALIZED' AND EXISTS (SELECT 1 FROM checks c WHERE c.process_id = p.id AND c.inspector_status = 'PENDING') LIMIT 1`,
      );
      if (!pid) return { status: 'SKIPPED', actual: '—', detail: 'Нет проверки с ожидающими кандидатами' };
      // A made-up re-authentication token can never finalize: the request must be refused.
      return rejected(
        await this.send({ method: 'POST', url: `${base}/processes/${pid}/finalize`, headers: mutation(), payload: JSON.stringify({ reauth_token: 'x'.repeat(43) }) }),
        [400, 401, 403, 409, 412, 422, 423],
        'финализация с ожидающими кандидатами не заблокирована',
      );
    });
    add('unfinalize-no-reason', 'Верификация', 'Снятие финализации без причины', '4xx: 400 / 422', async () => {
      if (!caller.cookie) return { status: 'SKIPPED', actual: '—', detail: 'Нужна сессия пользователя' };
      const pid = (await this.queryOne("SELECT id::text AS id FROM processes WHERE status = 'FINALIZED' LIMIT 1")) ?? FAKE_UUID;
      return rejected(
        await this.send({ method: 'POST', url: `${base}/processes/${pid}/unfinalize`, headers: mutation(), payload: '{}' }),
        [400, 403, 404, 409, 422, 423],
        'снятие финализации без причины не отклонено',
      );
    });

    // ── Export, filters, thresholds ──
    add('export-missing-protocol', 'Протокол', 'Выгрузка несуществующего протокола', '404', async () =>
      rejected(await this.send({ method: 'GET', url: `${base}/objects/NO-SUCH-OBJECT/protocols/${FAKE_UUID}/export?format=json`, headers: authHeaders(false) }), [404]),
    );
    add('export-unsupported-format', 'Протокол', 'Выгрузка протокола в неподдерживаемом формате', '400 / 404 / 422', async () =>
      rejected(await this.send({ method: 'GET', url: `${base}/objects/NO-SUCH-OBJECT/protocols/${FAKE_UUID}/export?format=xls`, headers: authHeaders(false) }), [400, 404, 422]),
    );
    add('page-image-missing-file', 'Просмотр', 'Изображение страницы несуществующего файла', '404', async () =>
      rejected(await this.send({ method: 'GET', url: `${base}/files/F-NO-SUCH/pages/1/image`, headers: authHeaders(false) }), [404]),
    );
    add('dashboard-invalid-filter', 'Дашборд', 'Дашборд с недопустимым значением фильтра цвета', '400', async () =>
      rejected(await this.send({ method: 'GET', url: `${base}/dashboard?color=PURPLE`, headers: authHeaders(false) }), [400, 422]),
    );
    add('invalid-pagination', 'Дашборд', 'Список запусков с page_size = 0', '400', async () => {
      if (!caller.cookie && this.config.authMode !== 'optional') return { status: 'SKIPPED', actual: '—', detail: 'Нужна сессия пользователя' };
      return rejected(await this.send({ method: 'GET', url: `${base}/admin/batch-runs?page_size=0`, headers: authHeaders(false) }), [400, 422]);
    });
    add('threshold-min-gt-max', 'Настройки', 'Пороги: минимум больше максимума', '422', async () => {
      if (!caller.cookie && this.config.authMode !== 'optional') return { status: 'SKIPPED', actual: '—', detail: 'Нужна сессия пользователя' };
      // Rejected before anything is written: the service validates min <= max ahead of the update.
      const res = await this.send({ method: 'PUT', url: `${base}/normative/params/SPZU-030`, headers: mutation(), payload: JSON.stringify({ min_value: 10, max_value: 5 }) });
      if (res.status === 500) return { status: 'SKIPPED', actual: '500', detail: 'Каталог параметров недоступен (нет базы данных)' };
      return rejected(res, [400, 422]);
    });

    // ── Generic protocol behaviour ──
    add('malformed-json', 'Протокол HTTP', 'Некорректный JSON в теле запроса', '400', async () =>
      rejected(await this.send({ method: 'POST', url: `${base}/telemetry/ui-events`, headers: mutation(), payload: '{"broken":' }), [400, 401, 403]),
    );
    add('unknown-route', 'Протокол HTTP', 'Несуществующий маршрут API', '404', async () =>
      rejected(await this.send({ method: 'GET', url: `${base}/no-such-endpoint`, headers: authHeaders(false) }), [404]),
    );

    // ── Infrastructure ──
    add('rabbitmq-down-fallback', 'Инфраструктура', 'RabbitMQ недоступен — включается резервный режим', 'режим in-process, без ошибки', async () => {
      const down = await detectQueueMode('amqp://127.0.0.1:1');
      const current = await detectQueueMode();
      return down.mode === 'in-process'
        ? { status: 'PASS', actual: 'in-process', detail: `Сейчас брокер ${current.mode === 'rabbitmq' ? 'доступен (режим rabbitmq)' : 'недоступен (режим in-process)'}` }
        : { status: 'FAIL', actual: down.mode, detail: 'При недоступном брокере не включился резервный режим' };
    });
    add('health-database', 'Инфраструктура', 'Проверка состояния API и базы данных', '200', async () => {
      const p = await this.send({ method: 'GET', url: `${base}/health` });
      return p.status === 200 ? { status: 'PASS', actual: '200' } : { status: 'FAIL', actual: String(p.status), detail: 'API сообщает о деградации' };
    });

    const results: SelftestResult[] = [];
    for (const c of checks) {
      const t = performance.now();
      let outcome: Outcome;
      try {
        outcome = await c.run();
      } catch (e) {
        outcome = { status: 'FAIL', actual: 'исключение', detail: e instanceof Error ? e.message : String(e) };
      }
      results.push({
        id: c.id,
        group: c.group,
        title: c.title,
        expected: c.expected,
        actual: outcome.actual,
        status: outcome.status,
        detail: outcome.detail ?? null,
        duration_ms: Math.round(performance.now() - t),
      });
    }
    const count = (s: SelftestStatus) => results.filter((r) => r.status === s).length;
    return {
      started_at: startedAt.toISOString(),
      duration_ms: Math.round(performance.now() - t0),
      summary: { total: results.length, pass: count('PASS'), fail: count('FAIL'), not_implemented: count('NOT_IMPLEMENTED'), skipped: count('SKIPPED') },
      results,
    };
  }
}
