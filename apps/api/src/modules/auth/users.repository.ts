/** Users, roles and object assignments (09 §3.9). */
import { Injectable } from '@nestjs/common';
import { and, asc, count, eq, ilike, inArray, or, sql } from 'drizzle-orm';
import { uuidv7 } from '../../common/ids';
import { Database } from '../../db/database';
import { objectAssignments, userRoles, users } from './auth.schema';

export interface UserRecord {
  id: string;
  login: string;
  passwordHash: string;
  fullName: string;
  position: string | null;
  email: string | null;
  isActive: boolean;
  mustChangePassword: boolean;
  failedLoginCount: number;
  lockedUntil: Date | null;
  lastLoginAt: Date | null;
  passwordHistory: string[];
  isDemo: boolean;
  roles: string[];
  createdAt: Date;
  updatedAt: Date;
}

export interface UserListQuery {
  page: number;
  pageSize: number;
  q?: string;
  role?: string;
}

export interface SeedUser {
  login: string;
  passwordHash: string;
  fullName: string;
  position: string | null;
  email: string | null;
  roles: string[];
  isDemo: boolean;
  mustChangePassword: boolean;
  /** Overwrite the password of an existing account. */
  resetPassword: boolean;
}

export abstract class UsersRepository {
  abstract findByLogin(login: string): Promise<UserRecord | null>;
  abstract findById(id: string): Promise<UserRecord | null>;
  /** Count a failed password; at `threshold` the account is locked for `lockMinutes` and the counter restarts. */
  abstract recordFailure(userId: string, threshold: number, lockMinutes: number): Promise<{ count: number; lockedUntil: Date | null }>;
  abstract recordSuccess(userId: string): Promise<void>;
  abstract setPassword(userId: string, passwordHash: string, history: string[], mustChange: boolean): Promise<void>;
  abstract list(query: UserListQuery): Promise<{ items: UserRecord[]; total: number }>;
  abstract assignedObjectIds(userId: string): Promise<string[]>;
  abstract isAssigned(userId: string, objectId: string): Promise<boolean>;
  abstract setAssignments(userId: string, objectIds: string[], assignedBy: string | null): Promise<void>;
  abstract upsertSeedUser(user: SeedUser): Promise<{ id: string; created: boolean }>;
}

type Row = typeof users.$inferSelect;

function toRecord(row: Row, roles: string[]): UserRecord {
  return {
    id: row.id,
    login: row.login,
    passwordHash: row.passwordHash,
    fullName: row.fullName,
    position: row.position,
    email: row.email,
    isActive: row.isActive,
    mustChangePassword: row.mustChangePassword,
    failedLoginCount: row.failedLoginCount,
    lockedUntil: row.lockedUntil,
    lastLoginAt: row.lastLoginAt,
    passwordHistory: Array.isArray(row.passwordHistory) ? (row.passwordHistory as string[]) : [],
    isDemo: row.isDemo,
    roles: [...roles].sort(),
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
  };
}

@Injectable()
export class DrizzleUsersRepository extends UsersRepository {
  constructor(private readonly database: Database) {
    super();
  }

  private async rolesOf(ids: string[]): Promise<Map<string, string[]>> {
    const out = new Map<string, string[]>();
    if (!ids.length) return out;
    const rows = await this.database.db
      .select({ userId: userRoles.userId, role: userRoles.roleCode })
      .from(userRoles)
      .where(inArray(userRoles.userId, ids));
    for (const r of rows) out.set(r.userId, [...(out.get(r.userId) ?? []), r.role]);
    return out;
  }

  private async one(where: ReturnType<typeof eq>): Promise<UserRecord | null> {
    const [row] = await this.database.db.select().from(users).where(where).limit(1);
    if (!row) return null;
    const roles = await this.rolesOf([row.id]);
    return toRecord(row, roles.get(row.id) ?? []);
  }

  findByLogin(login: string): Promise<UserRecord | null> {
    return this.one(eq(users.login, login.trim().toLowerCase()));
  }

  findById(id: string): Promise<UserRecord | null> {
    return this.one(eq(users.id, id));
  }

  async recordFailure(userId: string, threshold: number, lockMinutes: number): Promise<{ count: number; lockedUntil: Date | null }> {
    const [row] = await this.database.db
      .update(users)
      .set({
        failedLoginCount: sql`CASE WHEN ${users.failedLoginCount} + 1 >= ${threshold} THEN 0 ELSE ${users.failedLoginCount} + 1 END`,
        lockedUntil: sql`CASE WHEN ${users.failedLoginCount} + 1 >= ${threshold}
          THEN now() + make_interval(mins => ${lockMinutes}) ELSE ${users.lockedUntil} END`,
        updatedAt: sql`now()`,
      })
      .where(eq(users.id, userId))
      .returning({ failed: users.failedLoginCount, lockedUntil: users.lockedUntil });
    if (!row) return { count: 0, lockedUntil: null };
    const locked = row.failed === 0 && row.lockedUntil !== null && row.lockedUntil.getTime() > Date.now();
    return { count: locked ? threshold : row.failed, lockedUntil: locked ? row.lockedUntil : null };
  }

  async recordSuccess(userId: string): Promise<void> {
    await this.database.db
      .update(users)
      .set({ failedLoginCount: 0, lockedUntil: null, lastLoginAt: sql`now()`, updatedAt: sql`now()` })
      .where(eq(users.id, userId));
  }

  async setPassword(userId: string, passwordHash: string, history: string[], mustChange: boolean): Promise<void> {
    await this.database.db
      .update(users)
      .set({
        passwordHash,
        passwordHistory: history,
        mustChangePassword: mustChange,
        passwordChangedAt: sql`now()`,
        updatedAt: sql`now()`,
      })
      .where(eq(users.id, userId));
  }

  async list(query: UserListQuery): Promise<{ items: UserRecord[]; total: number }> {
    const db = this.database.db;
    const conditions = [];
    if (query.q) {
      const like = `%${query.q.replace(/[%_\\]/g, (c) => `\\${c}`)}%`;
      conditions.push(or(ilike(users.login, like), ilike(users.fullName, like)));
    }
    if (query.role) {
      conditions.push(
        inArray(users.id, db.select({ id: userRoles.userId }).from(userRoles).where(eq(userRoles.roleCode, query.role))),
      );
    }
    const where = conditions.length ? and(...conditions) : undefined;
    const [totalRow] = await db.select({ n: count() }).from(users).where(where);
    const rows = await db
      .select()
      .from(users)
      .where(where)
      .orderBy(asc(users.login))
      .limit(query.pageSize)
      .offset((query.page - 1) * query.pageSize);
    const roles = await this.rolesOf(rows.map((r) => r.id));
    return { total: Number(totalRow?.n ?? 0), items: rows.map((r) => toRecord(r, roles.get(r.id) ?? [])) };
  }

  async assignedObjectIds(userId: string): Promise<string[]> {
    const rows = await this.database.db
      .select({ objectId: objectAssignments.objectId })
      .from(objectAssignments)
      .where(eq(objectAssignments.userId, userId))
      .orderBy(asc(objectAssignments.objectId));
    return rows.map((r) => r.objectId);
  }

  async isAssigned(userId: string, objectId: string): Promise<boolean> {
    const [row] = await this.database.db
      .select({ one: sql<number>`1` })
      .from(objectAssignments)
      .where(and(eq(objectAssignments.userId, userId), eq(objectAssignments.objectId, objectId)))
      .limit(1);
    return Boolean(row);
  }

  async setAssignments(userId: string, objectIds: string[], assignedBy: string | null): Promise<void> {
    await this.database.db.transaction(async (tx) => {
      await tx.delete(objectAssignments).where(eq(objectAssignments.userId, userId));
      if (objectIds.length) {
        await tx
          .insert(objectAssignments)
          .values([...new Set(objectIds)].map((objectId) => ({ objectId, userId, assignedBy })));
      }
    });
  }

  async upsertSeedUser(user: SeedUser): Promise<{ id: string; created: boolean }> {
    return this.database.db.transaction(async (tx) => {
      const login = user.login.trim().toLowerCase();
      const [existing] = await tx.select({ id: users.id }).from(users).where(eq(users.login, login)).for('update');
      let id: string;
      if (existing) {
        id = existing.id;
        await tx
          .update(users)
          .set({
            fullName: user.fullName,
            position: user.position,
            email: user.email,
            isDemo: user.isDemo,
            isActive: true,
            deactivatedAt: null,
            updatedAt: sql`now()`,
            ...(user.resetPassword
              ? {
                  passwordHash: user.passwordHash,
                  mustChangePassword: user.mustChangePassword,
                  failedLoginCount: 0,
                  lockedUntil: null,
                  passwordChangedAt: sql`now()`,
                }
              : {}),
          })
          .where(eq(users.id, id));
      } else {
        id = uuidv7();
        await tx.insert(users).values({
          id,
          login,
          passwordHash: user.passwordHash,
          fullName: user.fullName,
          position: user.position,
          email: user.email,
          isDemo: user.isDemo,
          mustChangePassword: user.mustChangePassword,
          passwordChangedAt: new Date(),
        });
      }
      await tx.delete(userRoles).where(eq(userRoles.userId, id));
      if (user.roles.length) {
        await tx.insert(userRoles).values(user.roles.map((roleCode) => ({ userId: id, roleCode })));
      }
      return { id, created: !existing };
    });
  }
}
