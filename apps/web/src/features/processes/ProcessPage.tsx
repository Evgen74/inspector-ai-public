/** One process: stage list, per-file progress and the event log. */
import { Alert, Button, Card, Descriptions, Flex, Progress, Space, Spin, Table, Tag, Timeline, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useParams } from 'react-router';
import { ProblemAlert } from '../../components/ProblemAlert';
import { formatBytes, formatDateTime, formatInt } from '../../format';
import { type ProcessFileItem, useProcess } from './api';
import { durationText, FILE_STATE_LABEL, STAGE_LABEL, STATUS_COLOR, STATUS_LABEL, STEP_STATE_LABEL, recognitionProgressText, stepLabel } from './labels';

const STEP_COLOR = { PENDING: 'gray', RUNNING: 'blue', DONE: 'green', FAILED: 'red' } as const;
const LOG_COLOR = { info: 'gray', warn: 'orange', error: 'red' } as const;

export function ProcessPage() {
  const { processId = '' } = useParams();
  const query = useProcess(processId);
  const p = query.data;
  const fileColumns: TableColumnsType<ProcessFileItem> = [
    { title: 'Файл', dataIndex: 'name', ellipsis: true, render: (n: string, f) => (
      <Flex vertical>
        <span>{n}</span>
        {f.from_archive && <Typography.Text type="secondary" style={{ fontSize: 12 }}>из архива {f.from_archive}</Typography.Text>}
        {f.problems.map((x) => <Typography.Text key={x} type="danger" style={{ fontSize: 12 }}>{x}</Typography.Text>)}
      </Flex>
    ) },
    { title: 'ID', dataIndex: 'file_id', width: 130, render: (v: string | null) => v ?? '—' },
    { title: 'Стадия', dataIndex: 'stage', width: 120, render: (v: string | null) => (v ? (STAGE_LABEL[v] ?? v) : '—') },
    { title: 'Страниц', dataIndex: 'pages', width: 90, align: 'right', render: (v: number | null) => formatInt(v) },
    { title: 'Размер', dataIndex: 'size_bytes', width: 100, align: 'right', render: (v: number) => (v ? formatBytes(v) : '—') },
    { title: 'Состояние', dataIndex: 'status', width: 140, render: (s: ProcessFileItem['status']) => (
      <Tag color={s === 'REJECTED' ? 'error' : s === 'DONE' ? 'success' : s === 'PROCESSING' ? 'processing' : 'default'}>{FILE_STATE_LABEL[s]}</Tag>
    ) },
  ];
  return (
    <Flex vertical gap={16}>
      <Link to="/processes"><ArrowLeftOutlined /> Все проверки</Link>
      {query.isError ? (
        <ProblemAlert error={query.error} />
      ) : !p ? (
        <Spin />
      ) : (
        <>
          <Flex justify="space-between" align="center" wrap gap={12}>
            <div>
              <Typography.Title level={3} style={{ margin: 0 }}>{p.object_name}</Typography.Title>
              <Typography.Text type="secondary">{p.object_id} · {p.process_id}</Typography.Text>
            </div>
            <Space>
              <Tag color={STATUS_COLOR[p.status]} style={{ fontSize: 14, padding: '2px 10px' }}>{STATUS_LABEL[p.status]}</Tag>
              {p.status === 'READY' && p.protocol && (
                <Link to={`/objects/${encodeURIComponent(p.protocol.object_id)}/protocols/${p.protocol.run_id}`}><Button type="primary">Открыть протокол</Button></Link>
              )}
              {p.status === 'READY' && p.verification_process_id && (
                <Link to={`/verification/${p.verification_process_id}`}><Button>Верификация</Button></Link>
              )}
            </Space>
          </Flex>
          {p.status === 'FAILED' && <Alert type="error" showIcon title="Обработка не завершена" description={p.error ?? 'Причина не указана.'} />}
          <Card>
            <Progress percent={p.progress.percent} status={p.status === 'FAILED' ? 'exception' : p.status === 'READY' ? 'success' : 'active'} />
            {p.status === 'PARSING' && recognitionProgressText(p.progress.stage) && (
              <Typography.Text type="secondary" data-testid="recognition-progress">{recognitionProgressText(p.progress.stage)}</Typography.Text>
            )}
            <Descriptions size="small" column={{ xs: 1, md: 3 }} items={[
              { key: 'c', label: 'Создана', children: formatDateTime(p.created_at) },
              { key: 'd', label: 'Длительность', children: durationText(p.started_at, p.finished_at) },
              { key: 'q', label: 'Очередь', children: p.queue === 'rabbitmq' ? 'RabbitMQ' : p.queue === 'in-process' ? 'в процессе API' : '—' },
              { key: 'f', label: 'Файлов / страниц', children: `${formatInt(p.files_total)} / ${formatInt(p.pages_total)}` },
              ...(p.address ? [{ key: 'a', label: 'Адрес', children: p.address }] : []),
            ]} />
          </Card>
          <Flex gap={16} wrap align="flex-start">
            <Card title="Этапы" style={{ flex: '1 1 320px' }}>
              <Timeline items={p.steps.map((s) => ({
                color: STEP_COLOR[s.status],
                content: (
                  <span>
                    {stepLabel(s.step)} <Typography.Text type="secondary">— {STEP_STATE_LABEL[s.status]}
                      {s.started_at ? `, ${durationText(s.started_at, s.finished_at)}` : ''}</Typography.Text>
                  </span>
                ),
              }))} />
            </Card>
            <Card title="Журнал" style={{ flex: '2 1 420px' }}>
              <Timeline items={[...p.log].reverse().slice(0, 30).map((l) => ({
                color: LOG_COLOR[l.level],
                content: <span><Typography.Text type="secondary">{formatDateTime(l.ts)}</Typography.Text> {l.message}</span>,
              }))} />
            </Card>
          </Flex>
          <Card title="Файлы">
            <Table<ProcessFileItem> rowKey={(f) => `${f.file_id ?? ''}${f.name}`} columns={fileColumns} dataSource={p.files} size="small" pagination={{ pageSize: 25, hideOnSinglePage: true }} scroll={{ x: 800 }} />
          </Card>
        </>
      )}
    </Flex>
  );
}
