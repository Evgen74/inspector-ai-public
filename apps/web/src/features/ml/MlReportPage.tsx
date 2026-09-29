/** Module 10 «Отчёт по дообучению»: inspector decisions by parameter, section, reason; precision trend; recommendations. */
import { useState } from 'react';
import { Alert, Button, Card, DatePicker, Flex, List, Statistic, Table, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { DownloadOutlined, PrinterOutlined } from '@ant-design/icons';
import type { Dayjs } from 'dayjs';
import { ProblemAlert } from '../../components/ProblemAlert';
import { formatDate, formatInt } from '../../format';
import { type Bucket, type MlReport, reportUrls, useMlReport } from './api';

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);

function Trend({ data }: { data: MlReport['trend'] }) {
  const known = data.filter((d) => d.precision !== null);
  // One point (or none) does not make a trend: state the number instead of drawing an empty chart.
  if (known.length <= 1) {
    const d = known[0];
    return d ? (
      <Flex align="center" gap={24} wrap data-testid="trend-single">
        <Statistic title={`Точность за неделю с ${formatDate(d.week_start)}`} value={pct(d.precision)} />
        <Typography.Text type="secondary">
          Подтверждено {d.confirmed} из {d.confirmed + d.rejected} решений. Для динамики нужны данные минимум за две недели.
        </Typography.Text>
      </Flex>
    ) : (
      <Typography.Text type="secondary">Решений за последние 8 недель нет.</Typography.Text>
    );
  }
  const W = 960;
  const H = 180;
  const pts = data.map((d, i) => ({ x: 30 + (i * (W - 60)) / Math.max(1, data.length - 1), y: d.precision === null ? null : H - 30 - d.precision * (H - 60), d }));
  const line = pts.filter((p) => p.y !== null).map((p) => `${p.x},${p.y}`).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Динамика точности по неделям" style={{ width: '100%', height: 'auto' }}>
      <line x1="30" y1={H - 30} x2={W - 30} y2={H - 30} stroke="#d9d9d9" />
      <polyline points={line} fill="none" stroke="#1677ff" strokeWidth="2.5" />
      {pts.map((p) => (
        <g key={p.d.week_start}>
          {p.y !== null && (
            <>
              <circle cx={p.x} cy={p.y} r="5" fill="#1677ff">
                <title>{`${formatDate(p.d.week_start)}: ${pct(p.d.precision)} (${p.d.confirmed}/${p.d.confirmed + p.d.rejected})`}</title>
              </circle>
              <text x={p.x} y={p.y - 10} fontSize="13" textAnchor="middle" fill="#1f1f1f">
                {pct(p.d.precision)}
              </text>
            </>
          )}
          <text x={p.x} y={H - 8} fontSize="12" textAnchor="middle" fill="#8c8c8c">
            {formatDate(p.d.week_start).slice(0, 5)}
          </text>
        </g>
      ))}
    </svg>
  );
}

const bucketColumns = <T extends Bucket>(): TableColumnsType<T> => [
  { title: 'Подтверждено', dataIndex: 'confirmed', width: 120, align: 'right' },
  { title: 'Отклонено', dataIndex: 'rejected', width: 110, align: 'right' },
  { title: 'Точность', dataIndex: 'precision', width: 100, align: 'right', render: pct },
];

export function MlReportPage() {
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const from = range?.[0].startOf('day').toISOString();
  const to = range?.[1].endOf('day').toISOString();
  const q = useMlReport(from, to);
  const r = q.data;
  const urls = reportUrls(from, to);
  return (
    <Flex vertical gap={12}>
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Отчёт по дообучению
        </Typography.Title>
        <Flex gap={8} wrap>
          <DatePicker.RangePicker
            aria-label="Период отчёта"
            format="DD.MM.YYYY"
            placeholder={['Начало периода', 'Конец периода']}
            style={{ minWidth: 300 }}
            onChange={(v) => setRange(v && v[0] && v[1] ? [v[0], v[1]] : null)} />
          <Button icon={<PrinterOutlined />} href={urls.html} target="_blank" rel="noreferrer">
            Печатная версия
          </Button>
          <Button icon={<DownloadOutlined />} href={urls.json} target="_blank" rel="noreferrer">
            JSON
          </Button>
        </Flex>
      </Flex>
      <Typography.Text type="secondary">
        Отчёт составлен по решениям инспекторов (подтверждено или отклонено) и служит исходными данными для дообучения
        моделей и правил сравнения. Дообучение запускается отдельно и автоматически не выполняется.
      </Typography.Text>
      {q.isError ? (
        <ProblemAlert error={q.error} action={<Button onClick={() => void q.refetch()}>Повторить</Button>} />
      ) : !r ? (
        <Card loading />
      ) : (
        <>
          <Typography.Text type="secondary">
            Период: {formatDate(r.period.from)} — {formatDate(r.period.to)} (по умолчанию последние 7 дней)
          </Typography.Text>
          <Flex gap={12} wrap>
            {[
              ['Решений', formatInt(r.totals.decided)],
              ['Подтверждено', formatInt(r.totals.confirmed)],
              ['Отклонено', formatInt(r.totals.rejected)],
              ['Точность кандидатов', pct(r.totals.precision)],
              ['Споров с ИИ', formatInt(r.totals.disputes)],
            ].map(([t, v]) => (
              <Card key={t} size="small" style={{ minWidth: 150 }}>
                <Statistic title={t} value={v} />
              </Card>
            ))}
          </Flex>
          <Card size="small" title="Рекомендации">
            <List
              size="small"
              dataSource={r.recommendations}
              renderItem={(x) => (
                <List.Item>
                  <Alert type={x.severity === 'warning' ? 'warning' : 'info'} showIcon title={x.text} style={{ width: '100%' }} />
                </List.Item>
              )}
            />
          </Card>
          <Flex gap={12} wrap align="flex-start">
            <Card size="small" title="Динамика точности (8 недель)" style={{ flex: '1 1 100%' }}>
              <Trend data={r.trend} />
            </Card>
            <Card size="small" title="Причины отклонения" style={{ flex: '1 1 100%' }}>
              <Table
                size="small"
                pagination={false}
                rowKey="reason_code"
                dataSource={r.by_reason}
                locale={{ emptyText: 'Отклонений нет' }}
                columns={[
                  { title: 'Причина', dataIndex: 'label' },
                  { title: 'Кол-во', dataIndex: 'count', width: 80, align: 'right' },
                  { title: 'Доля', dataIndex: 'share', width: 80, align: 'right', render: pct },
                ]}
              />
            </Card>
          </Flex>
          <Card size="small" title="По разделам">
            <Table size="small" pagination={false} rowKey="section" dataSource={r.by_section} columns={[{ title: 'Раздел', dataIndex: 'section', width: 120 }, ...bucketColumns<Bucket & { section: string }>()]} locale={{ emptyText: 'Нет решений за период' }} />
          </Card>
          <Card size="small" title="По параметрам">
            <Table
              size="small"
              rowKey="param_code"
              dataSource={r.by_param}
              pagination={{ pageSize: 15, showSizeChanger: false }}
              locale={{ emptyText: 'Нет решений за период' }}
              columns={[{ title: 'Параметр', dataIndex: 'name', render: (n: string, r: Bucket & { param_code: string; name: string; section: string }) => <span>{n} <Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.param_code}</Typography.Text></span> }, { title: 'Раздел', dataIndex: 'section', width: 130 }, ...bucketColumns<Bucket & { param_code: string; name: string; section: string }>()]}
            />
          </Card>
        </>
      )}
    </Flex>
  );
}
