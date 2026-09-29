/** Object card tabs: «Обзор» (indicator + latest protocol), «Протоколы» (version history), «Запуски». */
import { useState } from 'react';
import { Alert, Button, Card, Descriptions, Empty, Flex, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { Link, useNavigate } from 'react-router';
import { ApiError } from '../api/client';
import { type ProtocolVersion, useDashboard, useProtocolVersions } from '../api/d1';
import type { ObjectDetail } from '../api/types';
import { ProblemAlert } from '../components/ProblemAlert';
import { CountCell, IndicatorTag, UploadChips } from '../components/indicator';
import { enumLabel } from '../contracts/enums';
import { protocolStatusColor, protocolStatusText } from '../contracts/labels';
import { UploadWizard } from '../features/processes/UploadWizard';
import { ExportButtons } from '../features/protocol/ExportButtons';
import { formatDateTime } from '../format';

const hidden = (o: ObjectDetail) => o.split === 'TEST_HIDDEN';

function HiddenNotice() {
  return (
    <Alert
      type="warning"
      showIcon
      title="Протоколы скрытой выборки не показываются"
      description="До отправки итогового ответа организаторам результаты по этому объекту закрыты (правило целостности скрытой выборки)."
    />
  );
}

export function ObjectOverview({ object }: { object: ObjectDetail }) {
  const dash = useDashboard({ q: object.object_id });
  const item = dash.data?.items.find((i) => i.object_id === object.object_id);
  const latest = item?.latest_protocol ?? null;
  const [uploadOpen, setUploadOpen] = useState(false);
  return (
    <Card size="small" title="Текущее состояние проверки">
      {dash.isError ? (
        <ProblemAlert error={dash.error} />
      ) : !item ? (
        <Typography.Text type="secondary">{dash.isLoading ? 'Загрузка…' : 'Результатов проверки пока нет'}</Typography.Text>
      ) : (
        <Flex gap={24} wrap align="flex-start">
          <Flex vertical gap={8} style={{ minWidth: 260 }}>
            <IndicatorTag indicator={item.indicator} />
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {item.indicator.reasons.map((r) => (
                <li key={r.code} data-code={r.code}>
                  {r.text}
                </li>
              ))}
            </ul>
          </Flex>
          {latest ? (
            <Descriptions size="small" column={{ xs: 1, md: 2 }} style={{ flex: 1, minWidth: 320 }}>
              <Descriptions.Item label="Последний протокол">
                <Link to={`/objects/${encodeURIComponent(object.object_id)}/protocols/${latest.run_id}`}>№ {latest.protocol_no}</Link>
              </Descriptions.Item>
              <Descriptions.Item label="Сформирован">{formatDateTime(latest.generated_at)}</Descriptions.Item>
              <Descriptions.Item label="Статус">
                <Tag color={protocolStatusColor(latest.status)}>{protocolStatusText(latest.status, latest.web_version)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Тип проверки">{enumLabel('LoadScenario', latest.scenario)}</Descriptions.Item>
              <Descriptions.Item label="Загрузка">
                <UploadChips status={item.upload_status} />
              </Descriptions.Item>
              <Descriptions.Item label="Находки">
                <Space size={12} wrap>
                  <span>
                    Критических: <CountCell n={latest.counts.critical} warn />
                  </span>
                  <span>
                    Существенных: <CountCell n={latest.counts.substantial} warn />
                  </span>
                  <span>
                    Подозрений ИИ: <CountCell n={latest.counts.suspicions} />
                  </span>
                  <span>
                    Подтверждено: <CountCell n={item.counters.confirmed} danger />
                  </span>
                </Space>
              </Descriptions.Item>
            </Descriptions>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                hidden(object)
                  ? 'Скрытая выборка: только инвентаризация'
                  : 'Протокол ещё не сформирован. Загрузите документы объекта, и система выполнит проверку.'
              }
            >
              {!hidden(object) && (
                <>
                  <Button type="primary" onClick={() => setUploadOpen(true)}>
                    Загрузить документы
                  </Button>
                  <UploadWizard open={uploadOpen} onClose={() => setUploadOpen(false)} />
                </>
              )}
            </Empty>
          )}
        </Flex>
      )}
    </Card>
  );
}

export function ObjectProtocols({ object }: { object: ObjectDetail }) {
  const navigate = useNavigate();
  const versions = useProtocolVersions(object.object_id, !hidden(object));
  if (hidden(object)) return <HiddenNotice />;
  if (versions.isError) {
    if (versions.error instanceof ApiError && versions.error.status === 403) return <HiddenNotice />;
    return <ProblemAlert error={versions.error} action={<Button onClick={() => void versions.refetch()}>Повторить</Button>} />;
  }
  const open = (v: ProtocolVersion) => navigate(`/objects/${encodeURIComponent(object.object_id)}/protocols/${v.run_id}`);
  const columns: TableColumnsType<ProtocolVersion> = [
    {
      title: 'Версия',
      key: 'v',
      width: 110,
      render: (_, v) => (
        <Space size={4}>
          <Typography.Text strong>v{v.web_version}</Typography.Text>
          {v.is_latest && <Tag color="blue">текущая</Tag>}
        </Space>
      ),
    },
    { title: '№ протокола', dataIndex: 'protocol_no', render: (no: string, v) => <Link to={`/objects/${encodeURIComponent(object.object_id)}/protocols/${v.run_id}`}>{no}</Link> },
    { title: 'Сформирован', dataIndex: 'generated_at', width: 140, render: (t: string) => formatDateTime(t) },
    {
      title: 'Статус',
      key: 'status',
      width: 190,
      render: (_, v) => (
        <Tooltip title={v.status_line}>
          <Tag color={protocolStatusColor(v.status)} data-code={v.status}>
            {protocolStatusText(v.status)}
          </Tag>
        </Tooltip>
      ),
    },
    { title: 'Тип проверки', dataIndex: 'scenario', width: 170, render: (s: string) => enumLabel('LoadScenario', s) },
    {
      title: <Tooltip title="Критических / существенных / подозрений ИИ / карточек">Разделы 4 · 5 · 6 · Б</Tooltip>,
      key: 'counts',
      width: 150,
      render: (_, v) => `${v.counts.critical} · ${v.counts.substantial} · ${v.counts.suspicions} · ${v.counts.cards}`,
    },
    {
      title: 'Запуск',
      key: 'run',
      width: 220,
      render: (_, v) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text code style={{ fontSize: 12 }}>
            {v.batch_run_id}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {v.pipeline_version}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: 'Выгрузка',
      key: 'export',
      width: 200,
      render: (_, v) => (
        <span onClick={(e) => e.stopPropagation()}>
          <ExportButtons objectId={object.object_id} version={v} />
        </span>
      ),
    },
  ];
  return (
    <Table<ProtocolVersion>
      rowKey="run_id"
      size="small"
      columns={columns}
      dataSource={versions.data?.items ?? []}
      loading={versions.isLoading}
      pagination={false}
      scroll={{ x: 1200 }}
      onRow={(v) => ({ onClick: () => open(v), style: { cursor: 'pointer' } })}
      locale={{ emptyText: <Empty description="Протоколов нет: импортируйте запуск inspector-batch с командой export" /> }}
    />
  );
}

interface RunRow {
  key: string;
  batch_run_id: string;
  kind: string;
  at: string;
  detail: string;
}

export function ObjectRuns({ object }: { object: ObjectDetail }) {
  const versions = useProtocolVersions(object.object_id, !hidden(object));
  const rows: RunRow[] = [];
  if (object.last_run) {
    rows.push({
      key: `inv-${object.last_run.id}`,
      batch_run_id: object.last_run.batch_run_id,
      kind: 'Инвентаризация (последний импорт)',
      at: object.last_run.imported_at,
      detail: `${object.files_total} файлов в реестре`,
    });
  }
  for (const v of versions.data?.items ?? []) {
    rows.push({
      key: v.run_id,
      batch_run_id: v.batch_run_id,
      kind: `Протокол v${v.web_version}`,
      at: v.generated_at,
      detail: `конвейер ${v.pipeline_version}${v.matrix_version ? ` · матрица ${v.matrix_version}` : ''}`,
    });
  }
  return (
    <Table<RunRow>
      rowKey="key"
      size="small"
      pagination={false}
      dataSource={rows}
      loading={versions.isLoading}
      columns={[
        { title: 'Запуск', dataIndex: 'batch_run_id', render: (r: string) => <Typography.Text code>{r}</Typography.Text> },
        { title: 'Результат', dataIndex: 'kind', width: 280 },
        { title: 'Время', dataIndex: 'at', width: 150, render: (t: string) => formatDateTime(t) },
        { title: 'Версии', dataIndex: 'detail' },
      ]}
      locale={{ emptyText: <Empty description="Запусков нет" /> }}
    />
  );
}
