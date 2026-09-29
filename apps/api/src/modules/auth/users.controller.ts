/** GET /admin/users and GET /admin/roles (users.manage; 90 §3.4 A). */
import { Controller, Get, Query } from '@nestjs/common';
import type { Page } from '../../api-types';
import { optionalString, parsePage } from '../../common/pagination';
import { Rbac } from './rbac';
import { UsersRepository } from './users.repository';

export interface UserItemDto {
  id: string;
  login: string;
  full_name: string;
  position: string | null;
  email: string | null;
  roles: string[];
  is_active: boolean;
  is_demo: boolean;
  must_change_password: boolean;
  locked_until: string | null;
  last_login_at: string | null;
  assigned_object_ids: string[];
  created_at: string;
}

export interface RoleMatrixDto {
  rbac_version: string;
  roles: string[];
  permissions: Array<{ code: string; label_ru: string; reauth: boolean; grants: Record<string, string> }>;
}

@Controller('admin')
export class UsersController {
  constructor(
    private readonly users: UsersRepository,
    private readonly rbac: Rbac,
  ) {}

  @Get('users')
  async listUsers(@Query() query: Record<string, unknown>): Promise<Page<UserItemDto>> {
    const { page, pageSize } = parsePage(query);
    const { items, total } = await this.users.list({
      page,
      pageSize,
      q: optionalString(query.q),
      role: optionalString(query.role),
    });
    const dtos = await Promise.all(
      items.map(async (u) => ({
        id: u.id,
        login: u.login,
        full_name: u.fullName,
        position: u.position,
        email: u.email,
        roles: u.roles,
        is_active: u.isActive,
        is_demo: u.isDemo,
        must_change_password: u.mustChangePassword,
        locked_until: u.lockedUntil && u.lockedUntil.getTime() > Date.now() ? u.lockedUntil.toISOString() : null,
        last_login_at: u.lastLoginAt ? u.lastLoginAt.toISOString() : null,
        assigned_object_ids: await this.users.assignedObjectIds(u.id),
        created_at: u.createdAt.toISOString(),
      })),
    );
    return { items: dtos, total, page, page_size: pageSize };
  }

  @Get('roles')
  getRoles(): RoleMatrixDto {
    return { rbac_version: this.rbac.version, roles: [...this.rbac.roles], permissions: this.rbac.matrix() };
  }
}
