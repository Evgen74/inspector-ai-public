/**
 * D1 web modules of AG-08 (protocol viewer, dashboard, page annotations): controllers and providers, spread
 * into AppModule so they share its config, contracts and database providers.
 */
import type { Provider, Type } from '@nestjs/common';
import { AnnotationsController, AnnotationsService } from './annotations/annotations.controller';
import { DashboardController } from './dashboard/dashboard.controller';
import { DashboardService } from './dashboard/dashboard.service';
import { ProtocolsController } from './protocols/protocols.controller';
import { ProtocolsService } from './protocols/protocols.service';
import { CatalogLookup, DrizzleCatalogLookup } from './shared/lookup.repository';
import { RunArtifacts } from './shared/run-artifacts';

export const D1_CONTROLLERS: Type<unknown>[] = [DashboardController, ProtocolsController, AnnotationsController];

export const D1_PROVIDERS: Provider[] = [
  { provide: CatalogLookup, useClass: DrizzleCatalogLookup },
  RunArtifacts,
  ProtocolsService,
  DashboardService,
  AnnotationsService,
];
