/**
 * One deep-zoom pane (OpenSeadragon over AG-00's tiles) with an SVG overlay of normalized regions:
 * blue = ПД / эталон, red = РД / ИД / факт (the organizers' markup legend), purple dashed = revision clouds from
 * the layout artifact, grey = room labels. Zoom-to-region on open (region ⊕ 25 %, at least 8 % of the page),
 * `[`/`]` cycle regions, `0` fits the page, `O` toggles overlays, `+`/`−` zoom.
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Flex, Input, Popover, Space, Spin, Switch, Tag, Tooltip, Typography } from 'antd';
import {
  AimOutlined,
  BorderOuterOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  LeftOutlined,
  MinusOutlined,
  PlusOutlined,
  RightOutlined,
  BlockOutlined,
} from '@ant-design/icons';
import OpenSeadragon from 'openseadragon';
import type { BBoxNorm } from '../../contracts/protocol';
import { usePageAnnotations } from '../../api/d1';
import { ApiError } from '../../api/client';
import { bboxLabel, bboxToViewport, fitRect, ROLE_COLORS, type VRect } from './geometry';
import { groupLayers, osdTileSource, type PageLayer, type PageView, revisionOnlyHidden, usePageView } from './pageSource';

export interface PaneRegion {
  box: BBoxNorm;
  color: string;
  label: string;
  /** Supporting / context regions are dashed. */
  dashed?: boolean;
}

export interface PaneView {
  /** Viewport center in page-width units and zoom (OSD viewport zoom: 1 = whole page width). */
  center: { x: number; y: number };
  zoom: number;
}

export interface EvidencePaneHandle {
  fitRegions(): void;
  fitPage(): void;
  setView(view: PaneView): void;
}

export interface EvidencePaneProps {
  fileId: string;
  page: number;
  title: React.ReactNode;
  regions: PaneRegion[];
  /** Called on user-driven viewport changes (for the synchronized mode). */
  onUserView?: (view: PaneView) => void;
  /** Boxes of the selected location (linked mode): highlighted more strongly and zoomed to. */
  activeBoxes?: BBoxNorm[] | null;
  /** Linked mode: ‹ › and [ ] step through locations (both panes together) instead of this pane's own regions. */
  onStep?: (delta: number) => void;
  stepInfo?: { index: number; total: number } | null;
}

interface Placed {
  key: string;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  label: string;
  /** Compact marker drawn on the box; the full label shows on hover / focus. */
  short: string;
  dashed: boolean;
  kind: 'region' | 'cloud' | 'room';
  active: boolean;
  dim?: boolean;
}

type Viewer = OpenSeadragon.Viewer;

function toOsdRect(r: VRect) {
  return new OpenSeadragon.Rect(r.x, r.y, r.width, r.height);
}

function LayerPanel({
  layers,
  hidden,
  onChange,
}: {
  layers: PageLayer[];
  hidden: number[];
  onChange: (hidden: number[]) => void;
}) {
  const [q, setQ] = useState('');
  const groups = useMemo(() => groupLayers(layers.filter((l) => !q || l.name.toLowerCase().includes(q.toLowerCase()))), [layers, q]);
  const hiddenSet = new Set(hidden);
  const revisions = layers.filter((l) => l.is_revision);
  return (
    <Flex vertical gap={8} style={{ width: 360 }}>
      <Space wrap size={6}>
        <Button size="small" onClick={() => onChange([])}>
          Все слои
        </Button>
        <Button size="small" disabled={revisions.length === 0} onClick={() => onChange(revisionOnlyHidden(layers))}>
          Только слои изменений ({revisions.length})
        </Button>
      </Space>
      <Input.Search size="small" allowClear placeholder="Поиск слоя" onChange={(e) => setQ(e.target.value)} />
      <div style={{ maxHeight: 320, overflow: 'auto' }}>
        {groups.map((g) => (
          <div key={g.group} style={{ marginBottom: 6 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {g.group}
            </Typography.Text>
            {g.layers.map((l) => (
              <div key={l.number}>
                <Checkbox
                  checked={l.on && !hiddenSet.has(l.number)}
                  disabled={!l.on || l.locked}
                  onChange={(e) =>
                    onChange(e.target.checked ? hidden.filter((n) => n !== l.number) : [...hidden, l.number])
                  }
                >
                  <span style={{ fontSize: 12.5 }}>{l.name}</span>
                  {l.is_revision && (
                    <Tag color="purple" style={{ marginLeft: 6, fontSize: 11 }}>
                      изменение
                    </Tag>
                  )}
                </Checkbox>
              </div>
            ))}
          </div>
        ))}
        {groups.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Слои не найдены" />}
      </div>
    </Flex>
  );
}

export const EvidencePane = forwardRef<EvidencePaneHandle, EvidencePaneProps>(function EvidencePane(
  { fileId, page, title, regions, onUserView, activeBoxes, onStep, stepInfo },
  ref,
) {
  const meta = usePageView(fileId, page);
  const annotations = usePageAnnotations(fileId, page);
  const host = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const aspectRef = useRef(1);
  const remote = useRef(false);
  const [placed, setPlaced] = useState<Placed[]>([]);
  const [showRegions, setShowRegions] = useState(true);
  const [showClouds, setShowClouds] = useState(true);
  const [showRooms, setShowRooms] = useState(false);
  const [active, setActive] = useState(0);
  const [hidden, setHidden] = useState<number[]>([]);
  const [tileError, setTileError] = useState(false);
  const activeKeys = useMemo(() => new Set((activeBoxes ?? []).map((b) => b.join(','))), [activeBoxes]);
  const activeSig = [...activeKeys].join('|');
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const cloudCount = annotations.data?.revision_clouds.length ?? 0;
  const m: PageView | undefined = meta.data;
  const aspect = m ? m.height_px / m.width_px : 1;
  aspectRef.current = aspect;

  const regionBoxes = useMemo(() => regions.map((r) => r.box), [regions]);

  const layout = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const a = aspectRef.current;
    const items: Placed[] = [];
    const place = (key: string, box: BBoxNorm, extra: Omit<Placed, 'key' | 'x' | 'y' | 'width' | 'height'>) => {
      const r = viewer.viewport.viewportToViewerElementRectangle(toOsdRect(bboxToViewport(box, a)));
      items.push({ key, x: r.x, y: r.y, width: r.width, height: r.height, ...extra });
    };
    const linked = activeKeys.size > 0;
    regions.forEach((r, i) => {
      const on = linked ? activeKeys.has(r.box.join(',')) : i === active;
      place(`r${i}`, r.box, { color: r.color, label: r.label, short: String(i + 1), dashed: Boolean(r.dashed), kind: 'region', active: on, dim: linked && !on });
    });
    (annotations.data?.revision_clouds ?? []).forEach((c, i) =>
      place(`c${i}`, c.bbox as BBoxNorm, {
        color: ROLE_COLORS.CLOUD,
        label: `${c.revision_label ?? 'Облако изменения'}${c.layer ? ` · ${c.layer}` : ''}${c.rooms_covered.length ? ` · пом. ${c.rooms_covered.join(', ')}` : ''}`,
        short: '≈',
        dashed: true,
        kind: 'cloud',
        active: false,
      }),
    );
    (annotations.data?.rooms ?? []).forEach((room, i) =>
      place(`m${i}`, room.bbox as BBoxNorm, {
        color: ROLE_COLORS.ROOM,
        label: `пом. ${room.room_token}${room.name ? ` · ${room.name}` : ''}`,
        short: room.room_token,
        dashed: false,
        kind: 'room',
        active: false,
      }),
    );
    setPlaced(items);
  }, [regions, annotations.data, active, activeKeys]);

  const layoutRef = useRef(layout);
  layoutRef.current = layout;

  const fitRegions = useCallback(
    (index?: number) => {
      const viewer = viewerRef.current;
      if (!viewer) return;
      const own = activeBoxes && activeBoxes.length ? activeBoxes : null;
      const boxes = index === undefined ? (own ?? regionBoxes) : [regionBoxes[index]!].filter(Boolean);
      viewer.viewport.fitBounds(toOsdRect(fitRect(boxes, aspectRef.current)), true);
    },
    [regionBoxes, activeBoxes],
  );

  const fitPage = useCallback(() => {
    viewerRef.current?.viewport.fitBounds(toOsdRect({ x: 0, y: 0, width: 1, height: aspectRef.current }), true);
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      fitRegions: () => fitRegions(),
      fitPage,
      setView: (view: PaneView) => {
        const viewer = viewerRef.current;
        if (!viewer) return;
        remote.current = true;
        viewer.viewport.zoomTo(view.zoom, undefined, true);
        viewer.viewport.panTo(new OpenSeadragon.Point(view.center.x, view.center.y * aspectRef.current), true);
        remote.current = false;
      },
    }),
    [fitRegions, fitPage],
  );

  // Create the viewer once the page geometry is known; re-open the tiles when the hidden layers change.
  const fitRegionsRef = useRef(fitRegions);
  fitRegionsRef.current = fitRegions;
  const onUserViewRef = useRef(onUserView);
  onUserViewRef.current = onUserView;
  useEffect(() => {
    if (!m || !host.current) return;
    const saved = viewerRef.current?.viewport.getBounds();
    viewerRef.current?.destroy();
    setTileError(false);
    const viewer = OpenSeadragon({
      element: host.current,
      tileSources: osdTileSource(m, hidden),
      showNavigationControl: false,
      showNavigator: false,
      animationTime: 0.4,
      maxZoomPixelRatio: 2.5,
      visibilityRatio: 0.4,
      constrainDuringPan: false,
      gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
      crossOriginPolicy: false,
    });
    viewerRef.current = viewer;
    const relayout = () => layoutRef.current();
    const el = host.current;
    const hasSize = () => Boolean(el && el.clientWidth > 0 && el.clientHeight > 0);
    // Race: OSD may open while the container still has no size (first card, layout not settled) and stays blank.
    // Remember whether the initial fit happened at a real size and redo it (plus a resize) when the size arrives.
    let opened = false;
    let fitted = false;
    const initialFit = () => {
      if (saved) viewer.viewport.fitBounds(saved, true);
      else fitRegionsRef.current();
      fitted = hasSize();
    };
    viewer.addHandler('open', () => {
      opened = true;
      initialFit();
      relayout();
    });
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined' && el) {
      observer = new ResizeObserver(() => {
        if (!hasSize()) return;
        viewer.viewport?.resize?.(new OpenSeadragon.Point(el.clientWidth, el.clientHeight), false);
        if (opened && !fitted) initialFit();
        viewer.forceRedraw?.();
        relayout();
      });
      observer.observe(el);
    }
    let retried = false;
    const retryTimer = window.setTimeout(() => {
      // Still nothing drawn after a second: nudge the viewer once.
      if (viewerRef.current === viewer && opened && !fitted && hasSize()) {
        initialFit();
        viewer.forceRedraw?.();
        relayout();
      }
    }, 1000);
    viewer.addHandler('animation', relayout);
    viewer.addHandler('resize', relayout);
    viewer.addHandler('update-viewport', relayout);
    viewer.addHandler('tile-load-failed', () => setTileError(true));
    viewer.addHandler('open-failed', () => {
      if (!retried && viewerRef.current === viewer) {
        retried = true;
        window.setTimeout(() => {
          if (viewerRef.current === viewer) viewer.open?.(osdTileSource(m, hidden) as never);
        }, 600);
        return;
      }
      setTileError(true);
    });
    viewer.addHandler('animation-finish', () => {
      if (remote.current) return;
      const c = viewer.viewport.getCenter();
      onUserViewRef.current?.({ center: { x: c.x, y: c.y / aspectRef.current }, zoom: viewer.viewport.getZoom() });
    });
    return () => {
      window.clearTimeout(retryTimer);
      observer?.disconnect();
      viewer.destroy();
      if (viewerRef.current === viewer) viewerRef.current = null;
    };
    // hidden layers and the page geometry define the tile source
  }, [fileId, page, m, hidden]);

  useEffect(() => {
    layout();
  }, [layout]);

  // Linked mode: another location selected on the same page zooms this pane to its boxes (a page change remounts).
  const firstSig = useRef(activeSig);
  useEffect(() => {
    if (firstSig.current === activeSig) return;
    firstSig.current = activeSig;
    if (activeSig) fitRegionsRef.current();
  }, [activeSig]);

  const cycle = (delta: number) => {
    if (onStep) {
      onStep(delta);
      return;
    }
    if (regions.length === 0) return;
    const next = (active + delta + regions.length) % regions.length;
    setActive(next);
    fitRegions(next);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    if (e.key === '0') fitPage();
    else if (e.key === '+' || e.key === '=') viewer.viewport.zoomBy(1.4);
    else if (e.key === '-') viewer.viewport.zoomBy(1 / 1.4);
    else if (e.key === ']') cycle(1);
    else if (e.key === '[') cycle(-1);
    else if (e.key === 'o' || e.key === 'O' || e.key === 'щ' || e.key === 'Щ') setShowRegions((v) => !v);
    else return;
    e.preventDefault();
  };

  const layers = m?.layers ?? [];
  const metaError = meta.error instanceof ApiError ? meta.error : null;
  const visible = placed.filter(
    (p) => (p.kind === 'region' && showRegions) || (p.kind === 'cloud' && showClouds) || (p.kind === 'room' && showRooms),
  );

  return (
    <Flex vertical style={{ minWidth: 0, flex: 1, border: '1px solid #d9dde3', borderRadius: 4, background: '#fff' }}>
      <Flex
        align="center"
        justify="space-between"
        gap={8}
        wrap
        style={{ padding: '6px 8px', borderBottom: '1px solid #eef0f3' }}
      >
        {/* flex-basis 0 + hidden overflow: a long title (page tab strip) scrolls inside the pane, never over its neighbour */}
        <div style={{ flex: '1 1 0', minWidth: 0, overflow: 'hidden' }}>{title}</div>
        <Space size={2} wrap>
          <Tooltip title="Показать фрагмент">
            <Button size="small" type="text" icon={<AimOutlined />} aria-label="Показать фрагмент" onClick={() => fitRegions()} />
          </Tooltip>
          <Tooltip title="Вся страница (0)">
            <Button size="small" type="text" icon={<BorderOuterOutlined />} aria-label="Вся страница" onClick={fitPage} />
          </Tooltip>
          <Tooltip title="Приблизить (+)">
            <Button size="small" type="text" icon={<PlusOutlined />} aria-label="Приблизить" onClick={() => viewerRef.current?.viewport.zoomBy(1.4)} />
          </Tooltip>
          <Tooltip title="Отдалить (−)">
            <Button size="small" type="text" icon={<MinusOutlined />} aria-label="Отдалить" onClick={() => viewerRef.current?.viewport.zoomBy(1 / 1.4)} />
          </Tooltip>
          {(onStep ? Boolean(stepInfo && stepInfo.total > 1) : regions.length > 1) && (
            <>
              <Tooltip title={onStep ? 'Предыдущее помещение ([)' : 'Предыдущий фрагмент ([)'}>
                <Button size="small" type="text" icon={<LeftOutlined />} aria-label="Предыдущий фрагмент" onClick={() => cycle(-1)} />
              </Tooltip>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {onStep && stepInfo ? `${stepInfo.index + 1}/${stepInfo.total}` : `${active + 1}/${regions.length}`}
              </Typography.Text>
              <Tooltip title={onStep ? 'Следующее помещение (])' : 'Следующий фрагмент (])'}>
                <Button size="small" type="text" icon={<RightOutlined />} aria-label="Следующий фрагмент" onClick={() => cycle(1)} />
              </Tooltip>
            </>
          )}
          <Tooltip title="Разметка (O)">
            <Button
              size="small"
              type="text"
              icon={showRegions ? <EyeOutlined /> : <EyeInvisibleOutlined />}
              aria-label={showRegions ? 'Скрыть разметку' : 'Показать разметку'}
              aria-pressed={showRegions}
              onClick={() => setShowRegions((v) => !v)}
            />
          </Tooltip>
          {layers.length > 0 && (
            <Popover
              trigger="click"
              placement="bottomRight"
              title={`Слои САПР на странице (${layers.length})`}
              content={<LayerPanel layers={layers} hidden={hidden} onChange={setHidden} />}
            >
              <Button size="small" icon={<BlockOutlined />} aria-label="Слои САПР">
                Слои{hidden.length ? ` · скрыто ${hidden.length}` : ''}
              </Button>
            </Popover>
          )}
        </Space>
      </Flex>
      <Flex gap={12} align="center" wrap style={{ padding: '4px 8px', fontSize: 12, borderBottom: '1px solid #eef0f3' }}>
        {/* The cloud switch (and its legend swatch) exists only when this page really has revision clouds. */}
        {cloudCount > 0 && (
          <Space size={4}>
            <Switch size="small" checked={showClouds} onChange={setShowClouds} aria-label="Облака изменений" />
            <span style={{ display: 'inline-block', width: 12, height: 12, border: `2px dashed ${ROLE_COLORS.CLOUD}`, verticalAlign: -2 }} />
            <span>Облака изменений ({cloudCount})</span>
          </Space>
        )}
        <Space size={4}>
          <Switch size="small" checked={showRooms} onChange={setShowRooms} aria-label="Номера помещений" />
          <span>Помещения{annotations.data ? ` (${annotations.data.rooms.length})` : ''}</span>
        </Space>
      </Flex>
      <div
        style={{ position: 'relative', flex: 1, minHeight: 420, background: '#f4f5f7', outline: 'none' }}
        tabIndex={0}
        role="application"
        aria-label="Просмотр страницы: 0 — вся страница, + и − — масштаб, [ и ] — фрагменты, O — разметка"
        onKeyDown={onKeyDown}
      >
        <div ref={host} style={{ position: 'absolute', inset: 0 }} data-testid="osd-host" />
        <svg
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
          aria-hidden={visible.length === 0}
          data-testid="overlay"
        >
          {visible.map((p) => (
            <g key={p.key} data-kind={p.kind} data-active={p.active ? 'true' : undefined} opacity={p.dim ? 0.4 : 1}>
              <rect
                x={p.x}
                y={p.y}
                width={Math.max(1, p.width)}
                height={Math.max(1, p.height)}
                fill={p.color}
                fillOpacity={p.kind === 'region' ? (p.active ? 0.2 : 0.1) : p.kind === 'cloud' ? 0.06 : 0}
                stroke={p.color}
                strokeWidth={p.active ? 3.5 : p.kind === 'room' ? 1 : 2}
                strokeDasharray={p.dashed ? '6 4' : undefined}
              >
                <title>{p.label}</title>
              </rect>
              <g
                data-marker={p.key}
                tabIndex={0}
                role="img"
                aria-label={p.label}
                style={{ pointerEvents: 'all', cursor: 'help', outline: 'none' }}
                onMouseEnter={() => setFocusKey(p.key)}
                onMouseLeave={() => setFocusKey((k) => (k === p.key ? null : k))}
                onFocus={() => setFocusKey(p.key)}
                onBlur={() => setFocusKey((k) => (k === p.key ? null : k))}
              >
                <rect
                  x={p.x}
                  y={Math.max(0, p.y - 15)}
                  width={Math.max(16, 7 * p.short.length + 8)}
                  height={15}
                  rx={3}
                  fill={p.color}
                />
                <text x={p.x + 4} y={Math.max(0, p.y - 15) + 11} fontSize={10.5} fill="#fff" fontWeight={600}>
                  {p.short}
                </text>
              </g>
            </g>
          ))}
          {visible
            .filter((p) => p.key === focusKey)
            .map((p) => {
              const w = Math.min(420, 6.2 * p.label.length + 12);
              const y = Math.max(0, p.y - 15) + 17;
              return (
                <g key={`tip-${p.key}`} data-testid="overlay-tip" style={{ pointerEvents: 'none' }}>
                  <rect x={p.x} y={y} width={w} height={18} rx={3} fill="#fff" stroke={p.color} />
                  <text x={p.x + 6} y={y + 13} fontSize={11} fill={p.color}>
                    {p.label}
                  </text>
                </g>
              );
            })}
        </svg>
        {meta.isLoading && (
          <Flex align="center" justify="center" style={{ position: 'absolute', inset: 0 }}>
            <Spin tip="Загрузка страницы…" />
          </Flex>
        )}
        {(meta.isError || tileError) && (
          <div style={{ position: 'absolute', left: 8, right: 8, bottom: 8 }}>
            <Alert
              type="warning"
              showIcon
              title="Изображение страницы недоступно"
              description={
                <>
                  {metaError?.status === 403
                    ? 'Просмотр страниц объекта скрытой выборки запрещён.'
                    : 'Сервис рендера страниц не ответил. Координаты фрагментов приведены ниже.'}
                  <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                    {regions.map((r, i) => (
                      <li key={i}>
                        {r.label}: {bboxLabel(r.box)}
                      </li>
                    ))}
                  </ul>
                </>
              }
            />
          </div>
        )}
      </div>
    </Flex>
  );
});
