/**
 * In-memory implementations of the platform repositories (AG-00): users, audit, run import v2, render files and
 * the ml-api client. Same interfaces as the Drizzle/HTTP ones, for DB-free tests.
 */
import type { NewAuditRow, AuditRow } from '../src/modules/audit/audit.schema';
import { type AuditQuery, AuditRepository } from '../src/modules/audit/audit.repository';
import { hashPassword } from '../src/modules/auth/passwords';
import { type SeedUser, type UserListQuery, type UserRecord, UsersRepository } from '../src/modules/auth/users.repository';
import {
  type ArtifactsImportPlan,
  type ObjectImportResult,
  RunImportRepository,
} from '../src/modules/import/run-import.repository';
import { MlApiClient, type MlPageInfo, type MlPng } from '../src/modules/render/ml-api.client';
import { type RenderFile, RenderFilesRepository } from '../src/modules/render/render.service';
import { ApiProblem } from '../src/common/problem';
import { uuidv7 } from '../src/common/ids';

export class InMemoryUsers extends UsersRepository {
  readonly users = new Map<string, UserRecord>();
  readonly assignments = new Map<string, Set<string>>();

  async add(u: { login: string; password: string; roles: string[]; fullName?: string; mustChangePassword?: boolean; isActive?: boolean; objects?: string[] }): Promise<UserRecord> {
    const now = new Date();
    const record: UserRecord = {
      id: uuidv7(),
      login: u.login,
      passwordHash: await hashPassword(u.password),
      fullName: u.fullName ?? `Пользователь ${u.login}`,
      position: null,
      email: null,
      isActive: u.isActive ?? true,
      mustChangePassword: u.mustChangePassword ?? false,
      failedLoginCount: 0,
      lockedUntil: null,
      lastLoginAt: null,
      passwordHistory: [],
      isDemo: true,
      roles: [...u.roles].sort(),
      createdAt: now,
      updatedAt: now,
    };
    this.users.set(record.id, record);
    this.assignments.set(record.id, new Set(u.objects ?? []));
    return record;
  }

  async findByLogin(login: string): Promise<UserRecord | null> {
    return [...this.users.values()].find((u) => u.login === login.trim().toLowerCase()) ?? null;
  }

  async findById(id: string): Promise<UserRecord | null> {
    return this.users.get(id) ?? null;
  }

  async recordFailure(userId: string, threshold: number, lockMinutes: number): Promise<{ count: number; lockedUntil: Date | null }> {
    const u = this.users.get(userId);
    if (!u) return { count: 0, lockedUntil: null };
    u.failedLoginCount += 1;
    if (u.failedLoginCount >= threshold) {
      u.failedLoginCount = 0;
      u.lockedUntil = new Date(Date.now() + lockMinutes * 60_000);
      return { count: threshold, lockedUntil: u.lockedUntil };
    }
    return { count: u.failedLoginCount, lockedUntil: null };
  }

  async recordSuccess(userId: string): Promise<void> {
    const u = this.users.get(userId);
    if (u) Object.assign(u, { failedLoginCount: 0, lockedUntil: null, lastLoginAt: new Date() });
  }

  async setPassword(userId: string, passwordHash: string, history: string[], mustChange: boolean): Promise<void> {
    const u = this.users.get(userId);
    if (u) Object.assign(u, { passwordHash, passwordHistory: history, mustChangePassword: mustChange });
  }

  async list(query: UserListQuery): Promise<{ items: UserRecord[]; total: number }> {
    const rows = [...this.users.values()]
      .filter((u) => !query.role || u.roles.includes(query.role))
      .filter((u) => !query.q || u.login.includes(query.q.toLowerCase()) || u.fullName.toLowerCase().includes(query.q.toLowerCase()))
      .sort((a, b) => (a.login < b.login ? -1 : 1));
    return { total: rows.length, items: rows.slice((query.page - 1) * query.pageSize, query.page * query.pageSize) };
  }

  async assignedObjectIds(userId: string): Promise<string[]> {
    return [...(this.assignments.get(userId) ?? [])].sort();
  }

  async isAssigned(userId: string, objectId: string): Promise<boolean> {
    return this.assignments.get(userId)?.has(objectId) ?? false;
  }

  async setAssignments(userId: string, objectIds: string[]): Promise<void> {
    this.assignments.set(userId, new Set(objectIds));
  }

  async upsertSeedUser(user: SeedUser): Promise<{ id: string; created: boolean }> {
    const existing = await this.findByLogin(user.login);
    if (existing) {
      existing.roles = [...user.roles].sort();
      if (user.resetPassword) existing.passwordHash = user.passwordHash;
      return { id: existing.id, created: false };
    }
    const now = new Date();
    const id = uuidv7();
    this.users.set(id, {
      id,
      login: user.login,
      passwordHash: user.passwordHash,
      fullName: user.fullName,
      position: user.position,
      email: user.email,
      isActive: true,
      mustChangePassword: user.mustChangePassword,
      failedLoginCount: 0,
      lockedUntil: null,
      lastLoginAt: null,
      passwordHistory: [],
      isDemo: user.isDemo,
      roles: [...user.roles].sort(),
      createdAt: now,
      updatedAt: now,
    });
    return { id, created: true };
  }
}

export class InMemoryAudit extends AuditRepository {
  readonly rows: AuditRow[] = [];
  failWith: Error | null = null;

  async insert(rows: NewAuditRow[]): Promise<void> {
    if (this.failWith) throw this.failWith;
    for (const r of rows) {
      this.rows.push({
        id: this.rows.length + 1,
        timestamp: new Date(),
        userId: r.userId ?? null,
        action: r.action,
        objectId: r.objectId ?? null,
        details: r.details ?? {},
        ipAddress: r.ipAddress ?? null,
        userAgent: r.userAgent ?? null,
        actorType: r.actorType,
        actorRole: r.actorRole ?? null,
        actorLogin: r.actorLogin ?? null,
        category: r.category,
        result: r.result,
        objectType: r.objectType ?? null,
        constructionObjectId: r.constructionObjectId ?? null,
        processId: r.processId ?? null,
        protocolVersion: r.protocolVersion ?? null,
        requestId: r.requestId ?? null,
        sessionRef: r.sessionRef ?? null,
        httpMethod: r.httpMethod ?? null,
        route: r.route ?? null,
        statusCode: r.statusCode ?? null,
        durationMs: r.durationMs ?? null,
        retentionClass: r.retentionClass,
      });
    }
  }

  async list(q: AuditQuery): Promise<{ items: AuditRow[]; total: number }> {
    const rows = [...this.rows]
      .reverse()
      .filter((r) => !q.userId || r.userId === q.userId)
      .filter((r) => !q.action || r.action === q.action)
      .filter((r) => !q.category || r.category === q.category)
      .filter((r) => !q.objectType || r.objectType === q.objectType)
      .filter((r) => !q.objectId || r.objectId === q.objectId)
      .filter((r) => !q.result || r.result === q.result)
      .filter((r) => !q.requestId || r.requestId === q.requestId);
    return { total: rows.length, items: rows.slice((q.page - 1) * q.pageSize, q.page * q.pageSize) };
  }
}

/** Records the plans it was given; results mimic a first import. */
export class InMemoryRunImport extends RunImportRepository {
  readonly plans: ArtifactsImportPlan[] = [];

  async saveArtifacts(plan: ArtifactsImportPlan): Promise<ObjectImportResult[]> {
    this.plans.push(plan);
    return plan.objects.map((o) => ({
      object_id: o.objectId,
      process_id: uuidv7(),
      process_created: true,
      process_status: o.protocol ? 'READY' : 'PARSING',
      protocol: o.protocol ? { id: uuidv7(), version: 1, created: true, status: o.protocol.status, content_sha256: o.protocol.contentSha256 } : null,
      finding_groups: o.groups.length,
      checks: { total: o.checks.length, inserted: o.checks.length, updated: 0, unchanged: 0, superseded: 0 },
      evidence_fragments: o.fragments.length,
      suspicions: o.suspicions.length,
      submissions: o.submissions.map((s) => s.variant),
    }));
  }
}

export class InMemoryRenderFiles extends RenderFilesRepository {
  readonly files = new Map<string, RenderFile>();

  async find(fileId: string): Promise<RenderFile | null> {
    return this.files.get(fileId) ?? null;
  }
}

/** Fake ml-api: deterministic PNG-like bytes; counts calls; can be switched off. */
export class FakeMlApi extends MlApiClient {
  calls: Array<{ route: string; body: Record<string, unknown> }> = [];
  down = false;
  sha256 = '';
  /** Per-file hash (falls back to `sha256`). */
  readonly shaByFile = new Map<string, string>();
  delayMs = 0;

  private check(): void {
    if (this.down) throw new ApiProblem('PAGE_RENDERER_UNAVAILABLE', { reason: 'http://127.0.0.1:8090 не отвечает (ECONNREFUSED)' });
  }

  async pageInfo(fileId: string, pageNo: number): Promise<MlPageInfo> {
    this.check();
    this.calls.push({ route: 'page-info', body: { file_id: fileId, page_no: pageNo } });
    return {
      file_id: fileId,
      object_id: 'OBJ-SYNTH-A',
      sha256: this.shaByFile.get(fileId) ?? this.sha256,
      page_no: pageNo,
      pdf_pages: 3,
      width_pt: 2384,
      height_pt: 3370,
      rotation: 0,
      max_dpi: 288,
      width_px: 9536,
      height_px: 13480,
      tile_size: 512,
      tile_overlap: 0,
      min_level: 0,
      max_level: 14,
    };
  }

  async renderPng(route: 'page' | 'crop' | 'tile', body: Record<string, unknown>): Promise<MlPng> {
    this.check();
    this.calls.push({ route, body });
    if (this.delayMs) await new Promise((r) => setTimeout(r, this.delayMs));
    const png = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from(JSON.stringify(body))]);
    const sha = this.shaByFile.get(String(body.file_id)) ?? this.sha256;
    return { bytes: png, headers: { 'x-file-sha256': sha, 'x-render-ms': '1' } };
  }
}
