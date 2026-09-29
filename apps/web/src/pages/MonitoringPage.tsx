/** Imported inspector-batch runs (M0 table), shown at the bottom of the «Мониторинг» page. */
import { useState } from 'react';
import { Card, Table, Tag, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { useBatchRuns } from '../api/hooks';
import type { BatchRun } from '../api/types';
import { ProblemAlert } from '../components/ProblemAlert';
import { HashText } from '../components/tags';
import { runStatusLabel } from '../contracts/labels';
import { formatDateTime, formatInt } from '../format';

export function BatchRunsPanel() {
  const [page, setPage] = useState(1);
  const runs = useBatchRuns(page, 20);

  const columns: TableColumnsType<BatchRun> = [
    {
      title: 'Запуск',
      dataIndex: 'batch_run_id',
      width: 280,
      render: (id: string) => (
        <Typography.Text code style={{ whiteSpace: 'nowrap' }}>
          {id}
        </Typography.Text>
      ),
    },
    { title: 'Статус', dataIndex: 'status', width: 120, render: (s: string) => <Tag data-code={s} color={s === 'FAILED' ? 'error' : 'success'}>{runStatusLabel(s)}</Tag> },
    { title: 'Объектов', dataIndex: 'objects_count', width: 100, align: 'right', render: formatInt },
    { title: 'Файлов', dataIndex: 'files_count', width: 100, align: 'right', render: formatInt },
    {
      title: 'Предупреждений',
      dataIndex: 'warnings_count',
      width: 140,
      align: 'right',
      render: (n: number) => (n > 0 ? <Typography.Text type="warning">{formatInt(n)}</Typography.Text> : '0'),
    },
    { title: 'Конфигурация', dataIndex: 'config_hash', width: 190, render: (v: string) => <HashText value={v} /> },
    {
      title: 'Версия конвейера',
      dataIndex: 'versions',
      width: 200,
      render: (v: Record<string, unknown>) => String(v.pipeline_version ?? '—'),
    },
    {
      title: 'Импортирован',
      dataIndex: 'imported_at',
      width: 160,
      render: (iso: string, r) => (
        <Tooltip title={r.manifest_ref}>
          <span>{formatDateTime(iso)}</span>
        </Tooltip>
      ),
    },
  ];

  return (
      <Card title="Импортированные запуски inspector-batch">
        {runs.isError ? (
          <ProblemAlert error={runs.error} />
        ) : (
          <Table<BatchRun>
            rowKey="id"
            size="small"
            columns={columns}
            dataSource={runs.data?.items ?? []}
            loading={runs.isLoading}
            scroll={{ x: 1100 }}
            pagination={{ current: page, pageSize: 20, total: runs.data?.total ?? 0, onChange: setPage }}
          />
        )}
      </Card>
  );
}
