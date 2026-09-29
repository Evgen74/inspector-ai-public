import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/golos-text/400.css';
import '@fontsource/golos-text/500.css';
import '@fontsource/golos-text/600.css';
import './global.css';
import { App } from './App';

async function bootstrap(): Promise<void> {
  // Mock mode: MSW answers /api/v1 from the contract-typed handlers (no API needed). Excluded from normal builds.
  if (import.meta.env.VITE_API_MOCK === '1') {
    const { startMockWorker } = await import('./mocks/browser');
    await startMockWorker();
  }
  const root = document.getElementById('root');
  if (!root) throw new Error('#root not found');
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
