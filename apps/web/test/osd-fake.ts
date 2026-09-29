/**
 * OpenSeadragon stand-in for jsdom (no canvas): records viewers, their tile sources and viewport calls, maps
 * viewport rectangles to element pixels ×1000, and fires `open` on the next microtask like a loaded image.
 */
import { vi } from 'vitest';

type Handler = (event?: unknown) => void;

export class FakeRect {
  constructor(
    public x: number,
    public y: number,
    public width: number,
    public height: number,
  ) {}
}

export class FakePoint {
  constructor(
    public x: number,
    public y: number,
  ) {}
}

class FakeViewport {
  bounds = new FakeRect(0, 0, 1, 1);
  zoom = 1;
  fitBounds = vi.fn((r: FakeRect) => {
    this.bounds = r;
  });
  zoomBy = vi.fn();
  zoomTo = vi.fn();
  panTo = vi.fn();
  viewportToViewerElementRectangle(r: FakeRect) {
    return new FakeRect(r.x * 1000, r.y * 1000, r.width * 1000, r.height * 1000);
  }
  getBounds() {
    return this.bounds;
  }
  getCenter() {
    return new FakePoint(this.bounds.x + this.bounds.width / 2, this.bounds.y + this.bounds.height / 2);
  }
  getZoom() {
    return this.zoom;
  }
}

export class FakeViewer {
  readonly handlers = new Map<string, Handler[]>();
  readonly viewport = new FakeViewport();
  destroyed = false;
  constructor(readonly options: { tileSources: { getTileUrl: (l: number, x: number, y: number) => string; width: number; height: number } }) {}
  addHandler(name: string, fn: Handler) {
    this.handlers.set(name, [...(this.handlers.get(name) ?? []), fn]);
  }
  raise(name: string, event?: unknown) {
    for (const fn of this.handlers.get(name) ?? []) fn(event);
  }
  destroy() {
    this.destroyed = true;
  }
}

export const osd = { viewers: [] as FakeViewer[] };

function OpenSeadragon(options: FakeViewer['options']) {
  const viewer = new FakeViewer(options);
  osd.viewers.push(viewer);
  queueMicrotask(() => {
    if (!viewer.destroyed) viewer.raise('open');
  });
  return viewer;
}
OpenSeadragon.Rect = FakeRect;
OpenSeadragon.Point = FakePoint;

export default OpenSeadragon;
