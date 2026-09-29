/** Page rendering for the evidence viewer (AG-00): Node endpoints + disk cache over the internal ml-api. */
import type { Provider } from '@nestjs/common';
import { HttpMlApiClient, MlApiClient } from './ml-api.client';
import { RenderController } from './render.controller';
import { DrizzleRenderFilesRepository, RenderFilesRepository, RenderService } from './render.service';

export { MlApiClient } from './ml-api.client';
export { RenderFilesRepository, RenderService } from './render.service';

export const RENDER_CONTROLLERS = [RenderController];

export const RENDER_PROVIDERS: Provider[] = [
  { provide: MlApiClient, useClass: HttpMlApiClient },
  { provide: RenderFilesRepository, useClass: DrizzleRenderFilesRepository },
  RenderService,
];
