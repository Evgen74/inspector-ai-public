/**
 * Security tables (owner AG-00; 09 §3.9, 90 §3.3.4 B09): users, user_roles, object_assignments.
 *
 * Enum-valued columns hold codes of packages/contracts/enums.yaml (noted per column); the role → permission
 * matrix is packages/contracts/rbac.yaml and is never stored in the database.
 * M1 deviation from 09 §3.3.4: PII columns (full_name, email, position) are stored in plain text — the system
 * runs locally on train data with demo accounts only; encryption at rest is listed as open work.
 */
import { sql } from 'drizzle-orm';
import { boolean, index, integer, jsonb, pgTable, primaryKey, text, timestamp, uuid, varchar } from 'drizzle-orm/pg-core';

const tstz = (name: string) => timestamp(name, { withTimezone: true, mode: 'date' });

export const users = pgTable('users', {
  /** UUID v7 */
  id: uuid('id').primaryKey(),
  /** Unique login (lower-case ASCII). */
  login: varchar('login', { length: 64 }).notNull().unique(),
  /** argon2id PHC string (m=19456 KiB, t=2, p=1). */
  passwordHash: text('password_hash').notNull(),
  fullName: text('full_name').notNull(),
  position: text('position'),
  email: text('email'),
  isActive: boolean('is_active').notNull().default(true),
  /** Forced password change on next login (09 §3.3.1); false for seeded demo accounts. */
  mustChangePassword: boolean('must_change_password').notNull().default(false),
  failedLoginCount: integer('failed_login_count').notNull().default(0),
  lockedUntil: tstz('locked_until'),
  lastLoginAt: tstz('last_login_at'),
  passwordChangedAt: tstz('password_changed_at'),
  /** argon2id hashes of the last 5 passwords (reuse is refused). */
  passwordHistory: jsonb('password_history').notNull().default(sql`'[]'::jsonb`),
  /** Seeded demo account (db:seed); shown in the admin list. */
  isDemo: boolean('is_demo').notNull().default(false),
  createdAt: tstz('created_at').notNull().defaultNow(),
  updatedAt: tstz('updated_at').notNull().defaultNow(),
  deactivatedAt: tstz('deactivated_at'),
});

export const userRoles = pgTable(
  'user_roles',
  {
    userId: uuid('user_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    /** Role */
    roleCode: varchar('role_code', { length: 32 }).notNull(),
    grantedBy: uuid('granted_by'),
    grantedAt: tstz('granted_at').notNull().defaultNow(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.roleCode] })],
);

/** Inspector visibility (90 U-08): ASSIGNED-scoped permissions reach only these objects. */
export const objectAssignments = pgTable(
  'object_assignments',
  {
    /** objects.id; no foreign key — an assignment may precede the first import of the object. */
    objectId: varchar('object_id', { length: 64 }).notNull(),
    userId: uuid('user_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    assignedBy: uuid('assigned_by'),
    assignedAt: tstz('assigned_at').notNull().defaultNow(),
  },
  (t) => [primaryKey({ columns: [t.objectId, t.userId] }), index('object_assignments_user_idx').on(t.userId)],
);

export type UserRow = typeof users.$inferSelect;
export type NewUserRow = typeof users.$inferInsert;
