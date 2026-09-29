/**
 * Role → permission matrix from packages/contracts/rbac.yaml (90 §3.10). Never defined in code: the API and the
 * web (through GET /auth/me) read the same file.
 */
import path from 'node:path';
import { enumCodes, loadEnums, readYaml } from '../../contracts/contracts';
import type { PermissionScope } from '../../common/request-context';

export interface PermissionDef {
  code: string;
  label_ru: string;
  reauth: boolean;
  grants: Record<string, PermissionScope>;
}

/** Widest scope first. */
const SCOPE_RANK: Record<PermissionScope, number> = { ALL: 3, ASSIGNED: 2, OWN: 1 };

export class Rbac {
  private readonly byCode: Map<string, PermissionDef>;

  constructor(
    readonly version: string,
    readonly permissions: readonly PermissionDef[],
    readonly roles: readonly string[],
  ) {
    this.byCode = new Map(permissions.map((p) => [p.code, p]));
  }

  static load(contractsDir: string): Rbac {
    const raw = readYaml<{
      rbac_version: string;
      permissions: Array<{ code: string; label_ru: string; reauth?: boolean; grants: Record<string, string> }>;
    }>(path.join(contractsDir, 'rbac.yaml'));
    const enums = loadEnums(contractsDir);
    const roles = enumCodes(enums, 'Role');
    const scopes = new Set(enumCodes(enums, 'PermissionScope'));
    const permissions = raw.permissions.map((p) => {
      for (const [role, scope] of Object.entries(p.grants)) {
        if (!roles.includes(role)) throw new Error(`rbac.yaml ${p.code}: unknown role ${role}`);
        if (!scopes.has(scope)) throw new Error(`rbac.yaml ${p.code}: unknown scope ${scope}`);
      }
      return { code: p.code, label_ru: p.label_ru, reauth: Boolean(p.reauth), grants: p.grants as Record<string, PermissionScope> };
    });
    return new Rbac(String(raw.rbac_version), permissions, roles);
  }

  has(code: string): boolean {
    return this.byCode.has(code);
  }

  get(code: string): PermissionDef | undefined {
    return this.byCode.get(code);
  }

  /** Effective permissions of a set of roles: the widest scope any of them grants. */
  effective(roles: readonly string[]): Map<string, PermissionScope> {
    const out = new Map<string, PermissionScope>();
    for (const p of this.permissions) {
      let best: PermissionScope | undefined;
      for (const role of roles) {
        const scope = p.grants[role];
        if (scope && (!best || SCOPE_RANK[scope] > SCOPE_RANK[best])) best = scope;
      }
      if (best) out.set(p.code, best);
    }
    return out;
  }

  /** Permission rows of GET /admin/roles. */
  matrix(): Array<{ code: string; label_ru: string; reauth: boolean; grants: Record<string, PermissionScope> }> {
    return this.permissions.map((p) => ({ code: p.code, label_ru: p.label_ru, reauth: p.reauth, grants: { ...p.grants } }));
  }
}
