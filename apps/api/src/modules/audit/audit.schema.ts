/**
 * Audit_Log (ТЗ §10 #12, owner AG-00; 09 §3.9, 90 §3.3.3 #12): append-only.
 *
 * ТЗ key fields first (id, user_id, action, object_id, details, timestamp, ip_address, user_agent), then the
 * 09 extensions. A trigger (migration 0003) raises on UPDATE, DELETE and TRUNCATE; rows leave the table only
 * through `audit_purge_expired()` (retention classes, 09 §3.4.3).
 */
import { sql } from 'drizzle-orm';
import { bigserial, char, index, inet, integer, jsonb, pgTable, text, timestamp, uuid, varchar } from 'drizzle-orm/pg-core';

const tstz = (name: string) => timestamp(name, { withTimezone: true, mode: 'date' });

export const auditLog = pgTable(
  'audit_log',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    userId: uuid('user_id'),
    /** AuditAction */
    action: varchar('action', { length: 64 }).notNull(),
    /** Affected entity id (ТЗ §10 #12), typed by object_type. */
    objectId: text('object_id'),
    details: jsonb('details').notNull().default(sql`'{}'::jsonb`),
    timestamp: tstz('timestamp').notNull().defaultNow(),
    ipAddress: inet('ip_address'),
    userAgent: text('user_agent'),
    // Extensions (09 §3.9).
    /** AuditActorType */
    actorType: varchar('actor_type', { length: 16 }).notNull(),
    /** Role codes of the actor at the time of the action, comma-separated. */
    actorRole: varchar('actor_role', { length: 128 }),
    actorLogin: varchar('actor_login', { length: 64 }),
    /** AuditCategory */
    category: varchar('category', { length: 16 }).notNull(),
    /** AuditResult */
    result: varchar('result', { length: 8 }).notNull(),
    /** AuditObjectType */
    objectType: varchar('object_type', { length: 32 }),
    /** objects.id of the construction object the action concerns. */
    constructionObjectId: varchar('construction_object_id', { length: 64 }),
    processId: uuid('process_id'),
    protocolVersion: integer('protocol_version'),
    requestId: varchar('request_id', { length: 128 }),
    /** First 16 hex chars of sha256(session token): links rows of one session without storing the token. */
    sessionRef: char('session_ref', { length: 16 }),
    httpMethod: varchar('http_method', { length: 8 }),
    /** OpenAPI path template, e.g. /admin/batch-runs/import */
    route: text('route'),
    statusCode: integer('status_code'),
    durationMs: integer('duration_ms'),
    /** RetentionClass */
    retentionClass: varchar('retention_class', { length: 12 }).notNull(),
  },
  (t) => [
    index('audit_log_timestamp_idx').on(t.timestamp),
    index('audit_log_user_idx').on(t.userId, t.timestamp),
    index('audit_log_object_idx').on(t.objectType, t.objectId),
    index('audit_log_process_idx').on(t.processId, t.timestamp),
    index('audit_log_action_idx').on(t.action, t.timestamp),
    index('audit_log_construction_object_idx').on(t.constructionObjectId, t.timestamp),
    index('audit_log_request_idx').on(t.requestId),
  ],
);

export type AuditRow = typeof auditLog.$inferSelect;
export type NewAuditRow = typeof auditLog.$inferInsert;
