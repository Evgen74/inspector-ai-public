/** Audit module (AG-00): append-only audit_log, mutation audit hook, GET /audit. */
import type { Provider } from '@nestjs/common';
import { AuditController } from './audit.controller';
import { AuditRepository, DrizzleAuditRepository } from './audit.repository';
import { AuditService } from './audit.service';

export { AuditRepository } from './audit.repository';
export { AuditService } from './audit.service';

export const AUDIT_CONTROLLERS = [AuditController];

export const AUDIT_PROVIDERS: Provider[] = [{ provide: AuditRepository, useClass: DrizzleAuditRepository }, AuditService];
