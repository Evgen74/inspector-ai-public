/**
 * «Дашборд» (ТЗ §7 модуль 7; 08 S-02): objects coloured by the strict rule (red only for confirmed
 * violations), KPI tiles, filters by matrix section, inspector decision, check type and protocol date — all in
 * the URL — and the findings-by-section summary.
 */
import { useMemo } from 'react';
import { Button, Card, DatePicker, Empty, Flex, Input, Select, Space, Table, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { type DashboardFilter, type DashboardObject, type SectionSummary, useDashboard } from '../../api/d1';
import { ProblemAlert } from '../../components/ProblemAlert';
import { CountCell, INDICATOR_STYLE, IndicatorTag, UploadChips } from '../../components/indicator';
import { SplitTag } from '../../components/tags';
import { MATRIX_SECTIONS, sectionOrder } from '../../contracts/codes';
import { enumCodes, enumLabel } from '../../contracts/enums';
import { protocolStatusText } from '../../contracts/labels';
import { formatDateTime, formatInt, pluralRu } from '../../format';

const COLORS = ['RED', 'YELLOW', 'GREEN', 'NONE'] as const;

/** KPI tile captions (08 S-02): short, one line each. */
const TILE_TEXT: Record<(typeof COLORS)[number], string> = {
  RED: 'С нарушениями',
  YELLOW: 'Требуют действий',
  GREEN: 'Без нарушений',
  NONE: 'Нет результата',
};

function listParam(sp: URLSearchParams, key: string): string[] {
  return (sp.get(key) ?? '').split(',').filter(Boolean);
}

export function readDashboardFilter(sp: URLSearchParams): DashboardFilter {
  return {
    q: sp.get('q') ?? undefined,
    color: listParam(sp, 'color'),
    section: listParam(sp, 'section'),
    status: listParam(sp, 'status'),
    scenario: sp.get('scenario') ?? undefined,
    dateFrom: sp.get('date_from') ?? undefined,
    dateTo: sp.get('date_to') ?? undefined,
  };
}

function Tile({
  title,
  value,
  color,
  icon,
  active,
  onClick,
  hint,
}: {
  title: string;
  value: number;
  color?: string;
  icon?: string;
  active?: boolean;
  onClick?: () => void;
  hint?: string;
}) {
  const body = (
    <Card
      size="small"
      hoverable={Boolean(onClick)}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      aria-pressed={onClick ? Boolean(active) : undefined}
      style={{
        minWidth: 150,
        flex: 1,
        whiteSpace: 'nowrap',
        borderColor: active ? color : undefined,
        boxShadow: active ? `0 0 0 2px ${color}33` : undefined,
        borderTop: color ? `3px solid ${color}` : undefined,
      }}
    >
      <Typography.Text type="secondary" style={{ fontSize: 12.5 }}>
        {icon ? `${icon} ` : ''}
        {title}
      </Typography.Text>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.2 }}>{formatInt(value)}</div>
    </Card>
  );
  return hint ? <Tooltip title={hint}>{body}</Tooltip> : body;
}

const SERIES: Array<{ key: keyof Omit<SectionSummary, 'section_ru'>; label: string; color: string }> = [
  { key: 'confirmed', label: 'Подтверждено', color: '#C62828' },
  { key: 'pending', label: 'Ожидает решения', color: '#F2A900' },
  { key: 'clarification', label: 'Требует уточнения', color: '#2F54EB' },
  { key: 'rejected', label: 'Отклонено', color: '#389E0D' },
  { key: 'suspicions', label: 'Подозрения ИИ', color: '#722ED1' },
];

export function SectionChart({ sections }: { sections: SectionSummary[] }) {
  const rows = [...sections].sort((a, b) => sectionOrder(a.section_ru) - sectionOrder(b.section_ru));
  const total = (s: SectionSummary) => SERIES.reduce((acc, x) => acc + s[x.key], 0);
  const max = Math.max(1, ...rows.map(total));
  if (rows.length === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Находок нет" />;
  return (
    <Flex vertical gap={6}>
      <Space size={12} wrap style={{ fontSize: 12 }}>
        {SERIES.map((s) => (
          <span key={s.key}>
            <span style={{ display: 'inline-block', width: 10, height: 10, background: s.color, marginRight: 4, borderRadius: 2 }} />
            {s.label}
          </span>
        ))}
      </Space>
      <table style={{ width: '100%', borderCollapse: 'collapse' }} aria-label="Находки по разделам и решениям">
        <tbody>
          {rows.map((r) => (
            <tr key={r.section_ru}>
              <th scope="row" style={{ width: 110, textAlign: 'left', fontWeight: 500, fontSize: 13, padding: '3px 8px 3px 0' }}>
                {r.section_ru}
              </th>
              <td style={{ padding: '3px 0' }}>
                <div style={{ display: 'flex', height: 16, width: `${(total(r) / max) * 100}%`, minWidth: 4 }}>
                  {SERIES.filter((s) => r[s.key] > 0).map((s) => (
                    <Tooltip key={s.key} title={`${s.label}: ${r[s.key]}`}>
                      <div style={{ flex: r[s.key], background: s.color }} aria-label={`${s.label}: ${r[s.key]}`} />
                    </Tooltip>
                  ))}
                </div>
              </td>
              <td style={{ width: 40, textAlign: 'right', fontSize: 13 }}>{total(r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Flex>
  );
}

export function DashboardPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const filter = useMemo(() => readDashboardFilter(sp), [sp]);
  const query = useDashboard(filter);
  const data = query.data;

  const update = (patch: Record<string, string | string[] | undefined | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      const value = Array.isArray(v) ? v.join(',') : v;
      if (value) next.set(k, value);
      else next.delete(k);
    }
    setSp(next, { replace: true });
  };
  const toggleColor = (c: string) => {
    const set = new Set(filter.color);
    if (set.has(c)) set.delete(c);
    else set.add(c);
    update({ color: [...set] });
  };

  const columns: TableColumnsType<DashboardObject> = [
    {
      title: 'Индикация',
      key: 'indicator',
      width: 190,
      render: (_, o) => <IndicatorTag indicator={o.indicator} />,
    },
    {
      title: 'Объект',
      key: 'object',
      width: 300,
      render: (_, o) => (
        <Flex vertical gap={2}>
          <Link to={`/objects/${encodeURIComponent(o.object_id)}`} onClick={(e) => e.stopPropagation()}>
            <Typography.Text strong>{o.name ?? o.object_id}</Typography.Text>
          </Link>
          <Flex gap={6} wrap align="center">
            <Typography.Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
              {o.object_id}
            </Typography.Text>
            {o.split === 'TEST_HIDDEN' && <SplitTag split={o.split} />}
          </Flex>
        </Flex>
      ),
    },
    {
      title: 'Протокол',
      key: 'protocol',
      width: 250,
      render: (_, o) =>
        o.latest_protocol ? (
          <Space orientation="vertical" size={0}>
            <Link
              to={`/objects/${encodeURIComponent(o.object_id)}/protocols/${o.latest_protocol.run_id}`}
              onClick={(e) => e.stopPropagation()}
            >
              № {o.latest_protocol.protocol_no}
            </Link>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {protocolStatusText(o.latest_protocol.status, o.latest_protocol.web_version)} · {formatDateTime(o.latest_protocol.generated_at)}
            </Typography.Text>
          </Space>
        ) : (
          <Typography.Text type="secondary">нет</Typography.Text>
        ),
    },
    {
      title: 'Тип проверки',
      key: 'scenario',
      width: 150,
      render: (_, o) =>
        o.latest_protocol ? (
          <span data-code={o.latest_protocol.scenario}>{enumLabel('LoadScenario', o.latest_protocol.scenario)}</span>
        ) : (
          '—'
        ),
    },
    { title: 'Загрузка', key: 'upload', width: 150, render: (_, o) => <UploadChips status={o.upload_status} /> },
    {
      title: <Tooltip title="Групп находок, подтверждённых инспектором (одна группа может объединять несколько атомарных находок в верификации)">Подтв. групп</Tooltip>,
      key: 'confirmed',
      width: 96,
      align: 'right',
      render: (_, o) => <CountCell n={o.counters.confirmed} danger />,
    },
    {
      title: <Tooltip title="Кандидаты, ожидающие решения (в скобках — критические)">Ожидают</Tooltip>,
      key: 'pending',
      width: 90,
      align: 'right',
      render: (_, o) => (
        <span>
          <CountCell n={o.counters.pending} warn />
          {o.counters.pending_high > 0 && <Typography.Text type="secondary"> ({o.counters.pending_high})</Typography.Text>}
        </span>
      ),
    },
    {
      title: <Tooltip title="Требуют уточнения">Уточн.</Tooltip>,
      key: 'clar',
      width: 70,
      align: 'right',
      render: (_, o) => <CountCell n={o.counters.clarification} />,
    },
    {
      title: <Tooltip title="Нет обязательных документов (параметров)">Нет док.</Tooltip>,
      key: 'missing',
      width: 78,
      align: 'right',
      render: (_, o) => <CountCell n={o.counters.missing_evidence} />,
    },
    {
      title: <Tooltip title="Подозрения ИИ — не входят в число нарушений и не меняют цвет">Подозр.</Tooltip>,
      key: 'susp',
      width: 72,
      align: 'right',
      render: (_, o) => <CountCell n={o.counters.suspicions} />,
    },
    { title: 'Обновлён', dataIndex: 'updated_at', width: 130, render: (v: string) => formatDateTime(v) },
  ];

  const tiles = data?.tiles;
  const anyFilter = [...sp.keys()].length > 0;

  return (
    <Flex vertical gap={16}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Дашборд инспектора
          </Typography.Title>
          <Typography.Text type="secondary">
            Красный — только подтверждённые инспектором нарушения; уровень риска и подозрения ИИ цвет не меняют.
          </Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void query.refetch()} loading={query.isFetching}>
          Обновить
        </Button>
      </Flex>
      <Flex gap={12} wrap>
        <Tile title="Объектов" value={tiles?.total ?? 0} />
        {COLORS.map((c) => {
          const s = INDICATOR_STYLE[c]!;
          return (
            <Tile
              key={c}
              title={TILE_TEXT[c]}
              icon={s.icon}
              value={tiles?.[c] ?? 0}
              color={s.bg}
              active={filter.color?.includes(c)}
              onClick={() => toggleColor(c)}
              hint={`${s.text}: показать только эти объекты`}
            />
          );
        })}
        <Tile
          title="Ожидают решения"
          value={tiles?.awaiting_decision ?? 0}
          hint="Групп находок, ожидающих решения инспектора или уточнения"
        />
      </Flex>
      <Card size="small">
        <Flex wrap gap={8} align="center">
          <Input.Search
            allowClear
            placeholder="Объект: код или наименование"
            defaultValue={filter.q}
            style={{ width: 260 }}
            onSearch={(v) => update({ q: v.trim() || undefined })}
          />
          <Select
            mode="multiple"
            allowClear
            placeholder="Индикация"
            style={{ minWidth: 180 }}
            value={filter.color}
            onChange={(v: string[]) => update({ color: v })}
            options={COLORS.map((c) => ({ value: c, label: `${INDICATOR_STYLE[c]!.icon} ${INDICATOR_STYLE[c]!.text}` }))}
            aria-label="Индикация"
          />
          <Select
            mode="multiple"
            allowClear
            placeholder="Разделы матрицы"
            style={{ minWidth: 200 }}
            value={filter.section}
            onChange={(v: string[]) => update({ section: v })}
            options={MATRIX_SECTIONS.map((s) => ({ value: s.code, label: `${s.code} · ${s.params} ${pluralRu(s.params, ['параметр', 'параметра', 'параметров'])}` }))}
            maxTagCount="responsive"
            aria-label="Разделы матрицы"
          />
          <Select
            mode="multiple"
            allowClear
            placeholder="Решение инспектора"
            style={{ minWidth: 200 }}
            value={filter.status}
            onChange={(v: string[]) => update({ status: v })}
            options={enumCodes('InspectorStatus').map((c) => ({ value: c, label: enumLabel('InspectorStatus', c) }))}
            maxTagCount="responsive"
            aria-label="Решение инспектора"
          />
          <Select
            allowClear
            placeholder="Тип проверки"
            style={{ minWidth: 200 }}
            value={filter.scenario}
            onChange={(v?: string) => update({ scenario: v })}
            options={enumCodes('LoadScenario').map((c) => ({ value: c, label: enumLabel('LoadScenario', c) }))}
            aria-label="Тип проверки"
          />
          <DatePicker.RangePicker
            format="DD.MM.YYYY"
            placeholder={['Протокол с', 'по']}
            value={[filter.dateFrom ? dayjs(filter.dateFrom) : null, filter.dateTo ? dayjs(filter.dateTo) : null]}
            onChange={(range) =>
              update({
                date_from: range?.[0] ? range[0].format('YYYY-MM-DD') : undefined,
                date_to: range?.[1] ? range[1].format('YYYY-MM-DD') : undefined,
              })
            }
            allowEmpty={[true, true]}
          />
          {anyFilter && (
            <Button type="link" onClick={() => setSp(new URLSearchParams(), { replace: true })}>
              Сбросить
            </Button>
          )}
        </Flex>
      </Card>
      {query.isError ? (
        <ProblemAlert error={query.error} action={<Button onClick={() => void query.refetch()}>Повторить</Button>} />
      ) : (
        <Flex vertical gap={16}>
          <Card size="small" title="Объекты">
            <Table<DashboardObject>
              rowKey="object_id"
              size="small"
              columns={columns}
              dataSource={data?.items ?? []}
              loading={query.isLoading}
              pagination={false}
              scroll={{ x: 1250 }}
              onRow={(o) => ({
                onClick: () =>
                  navigate(
                    o.latest_protocol
                      ? `/objects/${encodeURIComponent(o.object_id)}/protocols/${o.latest_protocol.run_id}`
                      : `/objects/${encodeURIComponent(o.object_id)}`,
                  ),
                style: { cursor: 'pointer' },
              })}
              locale={{
                emptyText: (
                  <Empty
                    description={anyFilter ? 'Нет объектов под выбранные фильтры' : 'Объектов пока нет: импортируйте запуск inspector-batch'}
                  />
                ),
              }}
            />
          </Card>
          <Card size="small" title="Находки по разделам × решение инспектора" style={{ maxWidth: 760 }}>
            <SectionChart sections={data?.sections ?? []} />
          </Card>
        </Flex>
      )}
    </Flex>
  );
}
