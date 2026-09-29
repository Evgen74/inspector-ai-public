/** Auth module (AG-00): local login/password, Redis sessions, RBAC from packages/contracts/rbac.yaml. */
import type { Provider } from '@nestjs/common';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { AuthController } from './auth.controller';
import { AuthService } from './auth.service';
import { Rbac } from './rbac';
import { RedisSessionStore, SessionStore } from './session-store';
import { UsersController } from './users.controller';
import { DrizzleUsersRepository, UsersRepository } from './users.repository';

export { AuthGuard } from './auth.guard';
export { AuthService } from './auth.service';
export { Rbac } from './rbac';
export { SessionStore } from './session-store';
export { UsersRepository } from './users.repository';

export const AUTH_CONTROLLERS = [AuthController, UsersController];

export const AUTH_PROVIDERS: Provider[] = [
  { provide: Rbac, useFactory: (config: AppConfig) => Rbac.load(config.contractsDir), inject: [APP_CONFIG] },
  { provide: SessionStore, useClass: RedisSessionStore },
  { provide: UsersRepository, useClass: DrizzleUsersRepository },
  AuthService,
];
