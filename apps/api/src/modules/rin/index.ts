/** Module 6 «ИАИС РиН» stub (AG-08): wiring `...RIN_CONTROLLERS` / `...RIN_PROVIDERS` in AppModule. */
import type { Provider, Type } from '@nestjs/common';
import { RinController } from './rin.controller';
import { PgRinRepository, RinRepository } from './rin.repository';
import { MockRinTransport, RIN_TRANSPORT, RinService } from './rin.service';

export { RinService, MockRinTransport, RIN_TRANSPORT, mockRinReceive } from './rin.service';
export { InMemoryRinRepository, RinRepository } from './rin.repository';

export const RIN_CONTROLLERS: Type<unknown>[] = [RinController];
export const RIN_PROVIDERS: Provider[] = [
  { provide: RinRepository, useClass: PgRinRepository },
  { provide: RIN_TRANSPORT, useClass: MockRinTransport },
  RinService,
];
