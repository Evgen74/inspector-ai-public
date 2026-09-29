/** «Проверки»: processes of uploaded packages with status, progress and links to the protocol. */
import { useState } from 'react';
import { Button, Card, Flex, Popconfirm, Progress, Space, Switch, Table, Tag, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { CloudUploadOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link } from 'react-router';
import { ProblemAlert } from '../../components/ProblemAlert';
import { formatDateTime, formatInt } from '../../format';
import { isActive, type ProcessSummary, useArchive, useProcesses } from './api';
import { durationText, STATUS_COLOR, STATUS_LABEL, stepLabel } from './labels';
import { UploadWizard } from './UploadWizard';

export function ProcessesPage() {
  const [showArchived, setShowArchived] = useState(false);
  const query = useProcesses(showArchived);
  const archive = useArchive();
  const [uploadOpen, setUploadOpen] = useState(false);
  const columns: TableColumnsType<ProcessSummary> = [
    {
      title: 'Статус',
      key: 'status',
      width: 130,
      render: (_, p) => (
        <Tooltip title={p.error ?? undefined}>
          <Tag color={STATUS_COLOR[p.status]}>{STATUS_LABEL[p.status]}</Tag>
        </Tooltip>
      ),
    },
    {
      title: 'Проверка',
      key: 'name',
      render: (_, p) => (
        <Flex vertical>
          <Link to={`/processes/${p.process_id}`}>{p.object_name}</Link>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {p.object_id}
            {p.archived_at && <Tag style={{ marginLeft: 8 }}>В архиве</Tag>}
          </Typography.Text>
        </Flex>
      ),
    },
    {
      title: 'Файлов / страниц',
      key: 'files',
      align: 'right',
      width: 150,
      render: (_, p) => (
        <span>
          {formatInt(p.files_total)} / {formatInt(p.pages_total)}
          {p.files_rejected > 0 && <Typography.Text type="danger"> (отклонено {p.files_rejected})</Typography.Text>}
        </span>
      ),
    },
    {
      title: 'Прогресс',
      key: 'progress',
      width: 260,
      render: (_, p) => (
        <Flex vertical gap={2}>
          <Progress
            percent={p.progress.percent}
            size="small"
            status={p.status === 'FAILED' ? 'exception' : p.status === 'READY' ? 'success' : 'active'}
          />
          {isActive(p.status) && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{stepLabel(p.stage)}</Typography.Text>}
        </Flex>
      ),
    },
    { title: 'Создана', key: 'created', width: 140, render: (_, p) => formatDateTime(p.created_at) },
    { title: 'Длительность', key: 'dur', width: 120, render: (_, p) => durationText(p.started_at, p.finished_at) },
    {
      title: 'Результат',
      key: 'result',
      width: 220,
      render: (_, p) =>
        p.status === 'READY' && p.protocol ? (
          <Space size="middle">
            <Link to={`/objects/${encodeURIComponent(p.protocol.object_id)}/protocols/${p.protocol.run_id}`}>Протокол</Link>
            {p.verification_process_id && <Link to={`/verification/${p.verification_process_id}`}>Верификация</Link>}
          </Space>
        ) : (
          '—'
        ),
    },
    {
      title: 'Действия',
      key: 'actions',
      width: 150,
      render: (_, p) =>
        p.archived_at ? (
          <Button size="small" loading={archive.isPending} onClick={() => archive.mutate({ kind: 'process', id: p.process_id, archived: false })}>
            Вернуть из архива
          </Button>
        ) : (
          <Popconfirm
            title="Архивировать проверку?"
            description="Она исчезнет из списка; данные сохранятся, вернуть можно из режима «Показать архивные»."
            okText="Архивировать"
            cancelText="Отмена"
            disabled={isActive(p.status)}
            onConfirm={() => archive.mutate({ kind: 'process', id: p.process_id })}
          >
            <Button size="small" disabled={isActive(p.status)}>
              Архивировать
            </Button>
          </Popconfirm>
        ),
    },
  ];
  return (
    <Flex vertical gap={16}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Проверки
          </Typography.Title>
          <Typography.Text type="secondary">Загруженные комплекты ПД, РД и ИД: статус обработки и готовые протоколы</Typography.Text>
        </div>
        <Space>
          <Space size={6}>
            <Switch size="small" checked={showArchived} onChange={setShowArchived} aria-label="Показать архивные" />
            <Typography.Text type="secondary">Показать архивные</Typography.Text>
          </Space>
          <Button icon={<ReloadOutlined />} onClick={() => void query.refetch()} loading={query.isFetching}>
            Обновить
          </Button>
          <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setUploadOpen(true)}>
            Загрузить комплект
          </Button>
        </Space>
      </Flex>
      <Card>
        {query.isError ? (
          <ProblemAlert error={query.error} action={<Button onClick={() => void query.refetch()}>Повторить</Button>} />
        ) : (
          <Table<ProcessSummary>
            rowKey="process_id"
            columns={columns}
            dataSource={query.data?.items ?? []}
            loading={query.isLoading}
            size="middle"
            scroll={{ x: 1000 }}
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            locale={{ emptyText: 'Проверок пока нет. Загрузите комплект документов, чтобы начать.' }}
          />
        )}
        {archive.isError && <ProblemAlert error={archive.error} />}
      </Card>
      <UploadWizard open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </Flex>
  );
}
