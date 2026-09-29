import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// OpenSeadragon needs a canvas; jsdom has none. UI tests get the recording fake (test/osd-fake.ts).
vi.mock('openseadragon', async () => await import('./osd-fake'));

// findBy*/waitFor default to 1 s; on a loaded CI runner (API and web suites side by side) antd screens take longer.
configure({ asyncUtilTimeout: 5000 });

// antd relies on these browser APIs; jsdom does not implement them. Node-environment test files skip this.
const hasWindow = typeof window !== 'undefined';
if (hasWindow && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}
if (hasWindow && !('ResizeObserver' in window)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(window, 'ResizeObserver', { writable: true, value: ResizeObserverStub });
}
if (hasWindow) {
  const originalGetComputedStyle = window.getComputedStyle.bind(window);
  window.getComputedStyle = (elt: Element, pseudo?: string | null) => originalGetComputedStyle(elt, pseudo ? undefined : pseudo);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
