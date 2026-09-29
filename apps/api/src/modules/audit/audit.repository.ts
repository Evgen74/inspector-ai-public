/** Append-only access to audit_log: insert and filtered, paged reads (no update or delete exists). */
import { Injectable } from '@nestjs/common';
import { and, count, desc, eq, gte, lt, type SQL } from 'drizzle-orm';
import { Database, type Db } from '../../db/database';
import { auditLog, type AuditRow, type NewAuditRow } from './audit.schema';

/** Anything that can run an INSERT: the Database or a Drizzle transaction (domain audit in the same transaction). */
export type AuditExecutor = Pick<Db, 'insert'>;

export interface AuditQuery {
  page: number;
  pageSize: number;
  userId?: string;
  action?: string;
  category?: string;
  objectType?: string;
  objectId?: string;
  constructionObjectId?: string;
  processId?: string;
  result?: string;
  requestId?: string;
  from?: Date;
  to?: Date;
}

export abstract class AuditRepository {
  abstract insert(rows: NewAuditRow[], executor?: AuditExecutor): Promise<void>;
  abstract list(query: AuditQuery): Promise<{ items: AuditRow[]; total: number }>;
}

@Injectable()
export class DrizzleAuditRepository extends AuditRepository {
  constructor(private readonly database: Database) {
    super();
  }

  async insert(rows: NewAuditRow[], executor?: AuditExecutor): Promise<void> {
    if (!rows.length) return;
    await (executor ?? this.database.db).insert(auditLog).values(rows);
  }

  async list(query: AuditQuery): Promise<{ items: AuditRow[]; total: number }> {
    const conditions: SQL[] = [];
    if (query.userId) conditions.push(eq(auditLog.userId, query.userId));
    if (query.action) conditions.push(eq(auditLog.action, query.action));
    if (query.category) conditions.push(eq(auditLog.category, query.category));
    if (query.objectType) conditions.push(eq(auditLog.objectType, query.objectType));
    if (query.objectId) conditions.push(eq(auditLog.objectId, query.objectId));
    if (query.constructionObjectId) conditions.push(eq(auditLog.constructionObjectId, query.constructionObjectId));
    if (query.processId) conditions.push(eq(auditLog.processId, query.processId));
    if (query.result) conditions.push(eq(auditLog.result, query.result));
    if (query.requestId) conditions.push(eq(auditLog.requestId, query.requestId));
    if (query.from) conditions.push(gte(auditLog.timestamp, query.from));
    if (query.to) conditions.push(lt(auditLog.timestamp, query.to));
    const where = conditions.length ? and(...conditions) : undefined;
    const db = this.database.db;
    const [totalRow] = await db.select({ n: count() }).from(auditLog).where(where);
    const items = await db
      .select()
      .from(auditLog)
      .where(where)
      .orderBy(desc(auditLog.id))
      .limit(query.pageSize)
      .offset((query.page - 1) * query.pageSize);
    return { items, total: Number(totalRow?.n ?? 0) };
  }
}
