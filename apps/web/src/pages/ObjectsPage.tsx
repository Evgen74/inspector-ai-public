/** «Объекты»: objects imported from inspector-batch runs, with file counts per manifest stage. */
import { useState } from 'react';
import { Button, Card, Empty, Flex, Input, Popconfirm, Space, Table, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { CloudUploadOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link, useNavigate } from 'react-router';
import { useObjects } from '../api/hooks';
import type { ManifestStage, ObjectSummary } from '../api/types';
import { useArchive } from '../features/processes/api';
import { UploadWizard } from '../features/processes/UploadWizard';
import { ImportRunModal } from '../components/ImportRunModal';
import { ProblemAlert } from '../components/ProblemAlert';
import { IndicatorBadge, SplitTag } from '../components/tags';
import { enumLabel } from '../contracts/enums';
import { formatDateTime, formatInt } from '../format';

/** Column headers (short UI text); the full contract label is in the header tooltip. */
const STAGE_COLUMNS: Array<{ stage: ManifestStage; title: string }> = [
  { stage: 'PD', title: 'ПД' },
  { stage: 'RD', title: 'РД' },
  { stage: 'ID', title: 'ИД' },
  { stage: 'RD_ID_MIXED', title: 'РД/ИД' },
  { stage: 'UNKNOWN', title: 'Без стадии' },
];

function stageCount(n: number) {
  return n === 0 ? <Typography.Text type="secondary">0</Typography.Text> : <Typography.Text strong>{formatInt(n)}</Typography.Text>;
}

export function ObjectsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [q, setQ] = useState<string | undefined>();
  const [importOpen, setImportOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const query = useObjects({ page, pageSize, q });
  const archive = useArchive();

  const columns: TableColumnsType<ObjectSummary> = [
    {
      title: 'Индикация',
      dataIndex: 'indicator_color',
      width: 130,
      render: (color: string) => <IndicatorBadge color={color} />,
    },
    {
      title: 'Объект',
      dataIndex: 'object_id',
      render: (_: string, o) => (
        <Space orientation="vertical" size={2}>
          <Link to={`/objects/${encodeURIComponent(o.object_id)}`} onClick={(e) => e.stopPropagation()}>
            <Typography.Text strong>{o.name ?? o.object_id}</Typography.Text>
          </Link>
          <Space size={8} wrap>
            {o.name && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {o.object_id}
              </Typography.Text>
            )}
            <SplitTag split={o.split} />
          </Space>
        </Space>
      ),
    },
    {
      title: 'Файлов',
      dataIndex: 'files_total',
      align: 'right',
      width: 110,
      render: (n: number, o) => (
        <Space orientation="vertical" size={0} style={{ alignItems: 'flex-end' }}>
          <Typography.Text strong>{formatInt(n)}</Typography.Text>
          {o.files_missing_on_disk > 0 && (
            <Typography.Text type="danger">нет на диске: {formatInt(o.files_missing_on_disk)}</Typography.Text>
          )}
        </Space>
      ),
    },
    ...STAGE_COLUMNS.map(({ stage, title }) => ({
      title: (
        <Tooltip title={`${enumLabel('ManifestStage', stage)} (${stage})`}>
          <span data-code={stage}>{title}</span>
        </Tooltip>
      ),
      key: stage,
      align: 'right' as const,
      width: 84,
      render: (_: unknown, o: ObjectSummary) => stageCount(o.files_by_stage[stage]),
    })),
    {
      title: 'Последний импорт',
      dataIndex: 'last_run',
      width: 160,
      render: (run: ObjectSummary['last_run']) =>
        run ? (
          <Tooltip title={`Запуск ${run.batch_run_id}`}>
            <span>{formatDateTime(run.imported_at)}</span>
          </Tooltip>
        ) : (
          '—'
        ),
    },
    {
      title: 'Действия',
      key: 'actions',
      width: 130,
      render: (_: unknown, o: ObjectSummary) => (
        <span onClick={(e) => e.stopPropagation()}>
          <Popconfirm
            title="Архивировать объект?"
            description="Объект исчезнет из списка и с дашборда; данные сохранятся."
            okText="Архивировать"
            cancelText="Отмена"
            onConfirm={() => archive.mutate({ kind: 'object', id: o.object_id })}
          >
            <Button size="small" loading={archive.isPending && archive.variables?.id === o.object_id}>
              Архивировать
            </Button>
          </Popconfirm>
        </span>
      ),
    },
  ];

  return (
    <Flex vertical gap={16}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Объекты
          </Typography.Title>
          <Typography.Text type="secondary">
            Объекты надзора, их документы и результаты проверки
          </Typography.Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void query.refetch()} loading={query.isFetching}>
            Обновить
          </Button>
          <Button icon={<CloudUploadOutlined />} onClick={() => setImportOpen(true)}>
            Импорт запуска
          </Button>
          <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setUploadOpen(true)}>
            Загрузить комплект
          </Button>
        </Space>
      </Flex>
      <Card>
        <Flex vertical gap={16}>
          <Input.Search
            placeholder="Поиск по наименованию или коду объекта"
            allowClear
            style={{ maxWidth: 420 }}
            onSearch={(value) => {
              setPage(1);
              setQ(value.trim() || undefined);
            }}
          />
          {archive.isError && <ProblemAlert error={archive.error} />}
          {query.isError ? (
            <ProblemAlert error={query.error} action={<Button onClick={() => void query.refetch()}>Повторить</Button>} />
          ) : (
            <Table<ObjectSummary>
              rowKey="object_id"
              columns={columns}
              dataSource={query.data?.items ?? []}
              loading={query.isLoading}
              size="middle"
              scroll={{ x: 1000 }}
              onRow={(o) => ({
                onClick: () => void navigate(`/objects/${encodeURIComponent(o.object_id)}`),
                style: { cursor: 'pointer' },
              })}
              locale={{
                emptyText: (
                  <Empty
                    description={
                      q
                        ? 'Ничего не найдено'
                        : 'Объектов пока нет. Загрузите комплект документов кнопкой «Загрузить комплект».'
                    }
                  />
                ),
              }}
              pagination={{
                current: page,
                pageSize,
                total: query.data?.total ?? 0,
                showSizeChanger: true,
                pageSizeOptions: [20, 50, 100, 200],
                showTotal: (total) => `Всего: ${formatInt(total)}`,
                onChange: (p, size) => {
                  setPage(size !== pageSize ? 1 : p);
                  setPageSize(size);
                },
              }}
            />
          )}
        </Flex>
      </Card>
      <ImportRunModal open={importOpen} onClose={() => setImportOpen(false)} />
      <UploadWizard open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </Flex>
  );
}
