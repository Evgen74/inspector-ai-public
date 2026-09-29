/** Browser mock mode (`VITE_API_MOCK=1`, `pnpm --filter @inspector/web dev:mock`): the UI without the API. */
import { setupWorker } from 'msw/browser';
import { createHandlers } from './handlers';

export async function startMockWorker(): Promise<void> {
  const worker = setupWorker(...createHandlers());
  await worker.start({ onUnhandledRequest: 'bypass', quiet: true });
  console.info('[Инспектор ИИ] режим демонстрационных данных (MSW): API не вызывается');
}
