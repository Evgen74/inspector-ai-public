/**
 * Side-by-side evidence of one card (05 §3.17.2, VER-02/VER-09): ПД (эталон) on the left, РД (факт) on the
 * right, ИД when present; each pane opens zoomed to its regions. Pages where a location is drawn apart from the
 * anchor page (room 314: anchor p18, drawn on p20) are one click away in the same pane.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Flex, Popover, Segmented, Space, Switch, Tag, Tooltip, Typography } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import type { BBoxNorm, CardSource, EvidenceCard, EvidenceRef, FindingGroup } from '../../contracts/protocol';
import { enumLabel } from '../../contracts/enums';
import { EvidencePane, type EvidencePaneHandle, type PaneRegion, type PaneView } from './EvidencePane';
import { roleColor } from './geometry';
import { buildLocationLinks, stepLocation } from './linking';
import { shortFileName } from './cardText';

export interface PageEvidence {
  key: string;
  stage: string;
  fileId: string;
  page: number;
  sheet: string | number | null | undefined;
  /** anchor (EXPECTED/ACTUAL of the card) or supporting */
  primary: boolean;
  /** «опорная» tab: the page a role marks as the card's anchor (never for value-conflict pages, which are equals) */
  anchor: boolean;
  /** Document name (manifest / registry), when known. */
  fileName: string | null;
  /** Value-conflict cards: the value this page supports. */
  valueText: string | null;
  note: string | null;
  documentCode: string | null;
  revision: string | null;
  regions: PaneRegion[];
}

const STAGE_ORDER = ['PD', 'RD', 'ID'];

function roleShort(role: string | undefined): string {
  if (role === 'EXPECTED') return 'эталон';
  if (role === 'ACTUAL') return 'факт';
  if (role === 'SUPPORTING_EXPECTED' || role === 'SUPPORTING_ACTUAL') return 'доп.';
  if (role === 'APPROVED_CHANGE') return 'согл. изменение';
  return 'контекст';
}

/** Pages of a card (+ per-location pages of its finding group), grouped by stage in ПД → РД → ИД order. */
export function evidencePages(
  card: EvidenceCard,
  group?: FindingGroup | null,
  names?: Record<string, string | null | undefined>,
): Map<string, PageEvidence[]> {
  const byKey = new Map<string, PageEvidence>();
  const valued = card.sources.some((x) => x.value_text);
  const add = (
    s: { stage: string; file_id: string; pdf_page_number: number; role?: string; geometry?: CardSource['geometry'] },
    extra: {
      sheet?: string | number | null;
      note?: string | null;
      documentCode?: string | null;
      revision?: string | null;
      fileName?: string | null;
      valueText?: string | null;
    },
  ) => {
    const key = `${s.file_id}#${s.pdf_page_number}`;
    const primary = s.role === 'EXPECTED' || s.role === 'ACTUAL' || s.role === undefined;
    // pages of a value conflict are equal witnesses of different values: none of them is the anchor
    const anchor = primary && !valued;
    const pe =
      byKey.get(key) ??
      ({
        key,
        stage: s.stage,
        fileId: s.file_id,
        page: s.pdf_page_number,
        sheet: extra.sheet,
        primary,
        anchor,
        fileName: extra.fileName ?? names?.[s.file_id] ?? null,
        valueText: extra.valueText ?? null,
        note: extra.note ?? null,
        documentCode: extra.documentCode ?? null,
        revision: extra.revision ?? null,
        regions: [],
      } satisfies PageEvidence);
    pe.primary ||= primary;
    pe.anchor ||= anchor;
    if (extra.valueText && !pe.valueText) pe.valueText = extra.valueText;
    if (extra.note && !pe.note) pe.note = extra.note;
    const color = roleColor(s.role, s.stage);
    const label = `${enumLabel('DocStage', s.stage)} л.${extra.sheet ?? '—'} · ${roleShort(s.role)}${extra.note ? ` · ${extra.note}` : ''}`;
    for (const box of s.geometry?.boxes ?? []) {
      if (!pe.regions.some((r) => r.box.join() === box.join())) {
        pe.regions.push({ box, color, label, dashed: !primary });
      }
    }
    byKey.set(key, pe);
  };
  for (const s of card.sources) {
    add(s, { sheet: s.sheet_number, documentCode: s.document_code ?? null, revision: s.revision ?? null, fileName: s.file_name ?? null, valueText: s.value_text ?? null });
  }
  for (const [location, refs] of Object.entries(group?.location_pages ?? {})) {
    for (const ref of refs as EvidenceRef[]) {
      add(
        { ...ref, role: ref.role ?? (ref.stage === 'PD' ? 'SUPPORTING_EXPECTED' : 'SUPPORTING_ACTUAL') },
        { sheet: ref.document_sheet_number, note: `пом. ${location}`, documentCode: ref.document_code ?? null, revision: ref.revision ?? null },
      );
    }
  }
  const out = new Map<string, PageEvidence[]>();
  for (const stage of STAGE_ORDER) {
    const pages = [...byKey.values()].filter((p) => p.stage === stage).sort((a, b) => Number(b.primary) - Number(a.primary) || a.page - b.page);
    if (pages.length) out.set(stage, pages);
  }
  return out;
}

/** Tab captions of one stage column: «АР 2024 · стр. 8 · 1,7 %», «стр. 18 · опорная» (a single file needs no name). */
export function tabLabels(pages: PageEvidence[]): Array<{ value: string; label: string }> {
  const files = new Set(pages.map((p) => p.fileId));
  const shorts = new Map<string, string>();
  for (const p of pages) if (!shorts.has(p.fileId)) shorts.set(p.fileId, shortFileName(p.fileName) ?? p.fileId);
  // two files with the same short name are told apart by their id
  const counts = new Map<string, number>();
  for (const [, v] of shorts) counts.set(v, (counts.get(v) ?? 0) + 1);
  return pages.map((p) => {
    let name = shorts.get(p.fileId)!;
    if ((counts.get(name) ?? 0) > 1 && name !== p.fileId) name = `${name} (${p.fileId})`;
    const parts = [files.size > 1 ? `${name} · стр. ${p.page}` : `стр. ${p.page}`];
    if (p.valueText) parts.push(p.valueText);
    if (p.anchor) parts.push('опорная');
    if (p.note) parts.push(p.note);
    return { value: p.key, label: parts.join(' · ') };
  });
}

function StageColumn({
  stage,
  pages,
  paneRef,
  onUserView,
  current,
  onPage,
  activeBoxes,
  onStep,
  stepInfo,
}: {
  stage: string;
  pages: PageEvidence[];
  paneRef: (h: EvidencePaneHandle | null) => void;
  onUserView: (view: PaneView) => void;
  current: string | undefined;
  onPage: (key: string) => void;
  activeBoxes?: BBoxNorm[] | null;
  onStep?: (delta: number) => void;
  stepInfo?: { index: number; total: number } | null;
}) {
  const pe = pages.find((p) => p.key === current) ?? pages[0]!;
  const color = stage === 'PD' ? '#1D4ED8' : '#C62828';
  const tabsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Keep the selected page tab visible in the scrolled strip (e.g. after a room chip switched the page).
    const el = tabsRef.current?.querySelector('.ant-segmented-item-selected');
    void (el as HTMLElement | null)?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [pe.key]);
  const title = (
    <Flex vertical gap={2} style={{ minWidth: 0, maxWidth: '100%' }}>
      <Space size={6} wrap>
        <Tag color={stage === 'PD' ? 'blue' : 'red'} style={{ marginInlineEnd: 0 }}>
          {enumLabel('DocStage', stage)} · {stage === 'PD' ? 'эталон' : 'факт'}
        </Tag>
        {pe.fileName ? (
          <>
            <Typography.Text strong style={{ color }} title={pe.fileName}>
              {pe.fileName}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {pe.fileId}, л. {pe.sheet ?? '—'} / стр. {pe.page}
            </Typography.Text>
          </>
        ) : (
          <Typography.Text strong style={{ color }}>
            {pe.fileId}, л. {pe.sheet ?? '—'} / стр. {pe.page}
          </Typography.Text>
        )}
      </Space>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {pe.documentCode ? `Шифр ${pe.documentCode}` : 'Шифр не определён'}
        {pe.revision ? ` · ред. ${pe.revision}` : ''}
      </Typography.Text>
      {pages.length > 1 && (
        // Many cited pages (value conflicts cite a dozen files) must not spill over the neighbouring pane:
        // the tab strip scrolls horizontally inside its own column and keeps the selected tab in view.
        <div ref={tabsRef} data-testid="page-tabs" style={{ maxWidth: '100%', overflowX: 'auto', paddingBottom: 4 }}>
          <Segmented
            size="small"
            value={pe.key}
            onChange={(v) => onPage(String(v))}
            options={tabLabels(pages)}
          />
        </div>
      )}
    </Flex>
  );
  return (
    <EvidencePane
      key={pe.key}
      ref={paneRef}
      fileId={pe.fileId}
      page={pe.page}
      title={title}
      regions={pe.regions}
      onUserView={onUserView}
      activeBoxes={activeBoxes}
      onStep={onStep}
      stepInfo={stepInfo}
    />
  );
}

/** «Как читать карточку»: what the panes, tabs, buttons and hotkeys mean. */
export function CardHelp() {
  return (
    <Popover
      trigger="click"
      placement="bottomRight"
      title="Как читать карточку"
      content={
        <Flex vertical gap={6} style={{ maxWidth: 420, fontSize: 13 }} data-testid="card-help">
          <span>
            <b>Эталон (ПД)</b> — проектное решение, с которым сравниваем (синяя рамка). <b>Факт (РД / ИД)</b> — то, что
            выполнено или заложено в рабочей и исполнительной документации (красная рамка).
          </span>
          <span>
            <b>Вкладки страниц</b> над панелью: «опорная» — страница, на которой найдено расхождение; остальные — другие
            листы, где нарисовано то же помещение или узел.
          </span>
          <span>
            <b>Кнопки панели</b>: «Показать фрагмент» — приблизить к отмеченной зоне; «Вся страница»; «+» / «−» — масштаб;
            стрелки — соседние фрагменты (при включённой связи панелей — соседнее помещение сразу в обеих панелях); глаз — скрыть или показать разметку.
          </span>
          <span>
            <b>Метки на рамках</b> — компактные номера; полная подпись появляется при наведении или фокусе.
          </span>
          <span>
            <b>Клавиши</b> (при фокусе на панели): 0 — вся страница, + / − — масштаб, [ и ] — фрагменты или помещения, O — разметка.
            Клавиша ? открывает все горячие клавиши верификации.
          </span>
        </Flex>
      }
    >
      <a role="button" style={{ fontSize: 12, whiteSpace: 'nowrap' }} aria-label="Как читать карточку">
        <QuestionCircleOutlined /> Как читать карточку
      </a>
    </Popover>
  );
}

export function EvidenceViewer({
  card,
  group,
  summary,
  names,
}: {
  card: EvidenceCard;
  group?: FindingGroup | null;
  summary?: string | null;
  /** file_id → document name (input registry), for pages that do not carry their own file name. */
  names?: Record<string, string | null | undefined>;
}) {
  const stages = useMemo(() => evidencePages(card, group, names), [card, group, names]);
  const links = useMemo(() => buildLocationLinks(card, group), [card, group]);
  const [sync, setSync] = useState<'independent' | 'coords'>('independent');
  const [linked, setLinked] = useState(true);
  const [sel, setSel] = useState(0);
  const pagesFor = (index: number): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const [stage, pages] of stages) {
      const key = links[index]?.targets[stage]?.pageKey;
      if (key && pages.some((p) => p.key === key)) out[stage] = key;
    }
    return out;
  };
  const [pageByStage, setPageByStage] = useState<Record<string, string>>(() => pagesFor(0));
  const panes = useRef(new Map<string, EvidencePaneHandle>());
  const onUserView = (from: string) => (view: PaneView) => {
    if (sync !== 'coords' || linked) return;
    for (const [stage, pane] of panes.current) if (stage !== from) pane.setView(view);
  };
  const select = (index: number) => {
    const i = stepLocation(index, 0, links.length);
    setSel(i);
    if (linked) setPageByStage(pagesFor(i));
  };
  const step = (delta: number) => select(stepLocation(sel, delta, links.length));
  const toggleLinked = (on: boolean) => {
    setLinked(on);
    if (on) setPageByStage(pagesFor(sel));
  };
  if (stages.size === 0) {
    return <Typography.Text type="secondary">В карточке нет страниц-источников.</Typography.Text>;
  }
  const active = links[sel];
  const canLink = linked && links.length > 0;
  const line = links.length > 1 && active?.summary ? active.summary : summary;
  return (
    <Flex vertical gap={8} style={{ height: '100%' }}>
      {line && (
        <Typography.Text data-testid="compare-summary" title={line} style={{ fontSize: 13 }}>
          <b>Что сравнивали:</b> {line}
        </Typography.Text>
      )}
      {links.length > 1 && (
        <Flex align="center" gap={8} wrap data-testid="location-chips">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {group?.location_type === 'ROOM' ? 'Помещения:' : 'Элементы:'}
          </Typography.Text>
          <Space size={4} wrap>
            {links.map((l, i) => (
              <Tag.CheckableTag key={l.id} checked={i === sel} onChange={() => select(i)} style={{ marginInlineEnd: 0, fontSize: 12.5 }} aria-pressed={i === sel}>
                {l.label}
              </Tag.CheckableTag>
            ))}
          </Space>
          <Tooltip title="Выбор помещения переключает обе панели на его страницы и приближает к его фрагментам; ‹ › и [ ] листают помещения синхронно">
            <span style={{ fontSize: 12 }}>
              <Switch size="small" checked={linked} onChange={toggleLinked} aria-label="Связать панели" /> Связать панели
            </span>
          </Tooltip>
        </Flex>
      )}
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Space size={12} wrap style={{ fontSize: 12 }}>
          <span>
            <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid #1D4ED8', background: 'rgba(29,78,216,.12)', verticalAlign: -2 }} />{' '}
            ПД — проектное решение, база сравнения
          </span>
          <span>
            <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid #C62828', background: 'rgba(198,40,40,.12)', verticalAlign: -2 }} />{' '}
            РД — зона отсутствующего или изменённого решения
          </span>
        </Space>
        <Space size={12}>
          <CardHelp />
          {!canLink && (
            <Tooltip title="Дополнительно: «По координатам» — одинаковые центр и масштаб во всех панелях (для планов одного этажа)">
              <Segmented
                size="small"
                value={sync}
                onChange={(v) => setSync(v as typeof sync)}
                options={[
                  { value: 'independent', label: 'Независимо' },
                  { value: 'coords', label: 'По координатам' },
                ]}
              />
            </Tooltip>
          )}
        </Space>
      </Flex>
      <Flex gap={8} style={{ flex: 1, minHeight: 0 }} wrap={false}>
        {[...stages.entries()].map(([stage, pages]) => {
          const current = pageByStage[stage] ?? pages[0]!.key;
          const target = active?.targets[stage];
          return (
            <StageColumn
              key={stage}
              stage={stage}
              pages={pages}
              current={current}
              onPage={(key) => setPageByStage((m) => ({ ...m, [stage]: key }))}
              activeBoxes={canLink && target?.pageKey === current ? target.boxes : null}
              onStep={canLink && links.length > 1 ? step : undefined}
              stepInfo={canLink && links.length > 1 ? { index: sel, total: links.length } : null}
              paneRef={(h) => {
                if (h) panes.current.set(stage, h);
                else panes.current.delete(stage);
              }}
              onUserView={onUserView(stage)}
            />
          );
        })}
      </Flex>
    </Flex>
  );
}
