/** Module 8 «Нормативная база» (AG-08): wiring `...NORMATIVE_CONTROLLERS` / `...NORMATIVE_PROVIDERS` in AppModule. */
import type { Provider, Type } from '@nestjs/common';
import { NormativeController } from './normative.controller';
import { NormativeRepository, PgNormativeRepository } from './normative.repository';
import { NormativeService } from './normative.service';

export { NormativeService } from './normative.service';
export { InMemoryNormativeRepository, NormativeRepository } from './normative.repository';

export const NORMATIVE_CONTROLLERS: Type<unknown>[] = [NormativeController];
export const NORMATIVE_PROVIDERS: Provider[] = [{ provide: NormativeRepository, useClass: PgNormativeRepository }, NormativeService];
