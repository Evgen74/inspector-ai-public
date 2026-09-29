/**
 * Object card (08 S-04): tabs «Обзор» (indicator, latest protocol, summary), «Документы» (file registry,
 * server-paginated, filterable by stage and presence), «Протоколы» (version history, downloads), «Запуски».
 */
import { useState } from 'react';
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Descriptions,
  Flex,
  Input,
  Result,
  Segmented,
  Select,
  Skeleton,
  Space,
  Table,
  Tabs,
  Tooltip,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { Link, useParams, useSearchParams } from 'react-router';
import { ApiError } from '../api/client';
import { useObject, useObjectFiles } from '../api/hooks';
import { type FileItem, MANIFEST_STAGES, type ManifestStage } from '../api/types';
import { ProblemAlert } from '../components/ProblemAlert';
import { HashText, IndicatorBadge, LocalStatusTag, SplitTag, StageTag } from '../components/tags';
import { enumCodes, enumLabel } from '../contracts/enums';
import { formatBytes, formatDateTime, formatInt } from '../format';
import { ObjectOverview, ObjectProtocols, ObjectRuns } from './ObjectTabs';

const STAGE_SHORT: Record<ManifestStage, string> = {
  PD: 'ПД',
  RD: 'РД',
  ID: 'ИД',
  RD_ID_MIXED: 'РД/ИД',
  UNKNOWN: 'Без стадии',
};

export function ObjectPage() {
  const { objectId = '' } = useParams();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') ?? 'overview';
  const object = useObject(objectId);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [stage, setStage] = useState<ManifestStage | undefined>();
  const [localStatus, setLocalStatus] = useState<string | undefined>();
  const [q, setQ] = useState<string | undefined>();
  const files = useObjectFiles(objectId, { page, pageSize, stage, localStatus, q });

  if (object.isError && object.error instanceof ApiError && object.error.status === 404) {
    return (
      <Result
        status="404"
        title="Объект не найден"
        subTitle={`Объекта «${objectId}» нет в базе. Импортируйте запуск, в котором он есть.`}
        extra={
          <Link to="/objects">
            <Button type="primary">К списку объектов</Button>
          </Link>
        }
      />
    );
  }

  const o = object.data;
  const columns: TableColumnsType<FileItem> = [
    { title: 'ID', dataIndex: 'file_id', width: 90, render: (id: string) => <Typography.Text code>{id}</Typography.Text> },
    {
      title: 'Файл',
      dataIndex: 'file_name',
      render: (name: string, f) => (
        <Tooltip title={f.relative_path ?? 'Путь неизвестен: манифест организаторов не сопоставлен'}>
          <Typography.Text>{name}</Typography.Text>
        </Tooltip>
      ),
    },
    {
      title: 'Стадия',
      dataIndex: 'manifest_stage',
      width: 100,
      render: (s: string, f) => <StageTag stage={s} resolved={f.stage_resolved} />,
    },
    {
      title: 'Раздел',
      dataIndex: 'manifest_section',
      width: 90,
      render: (s: string | null) => (s ? <Typography.Text data-code={s}>{enumLabel('ManifestSection', s)}</Typography.Text> : '—'),
    },
    { title: 'Страниц', dataIndex: 'pdf_pages', width: 90, align: 'right', render: (n: number | null) => formatInt(n) },
    { title: 'Размер', dataIndex: 'size_bytes', width: 100, align: 'right', render: (n: number | null) => formatBytes(n) },
    { title: 'SHA-256', dataIndex: 'sha256', width: 170, render: (sha: string) => <HashText value={sha} /> },
    {
      title: 'Наличие',
      dataIndex: 'local_status',
      width: 170,
      render: (s: string) => <LocalStatusTag status={s} />,
    },
  ];

  const stageOptions = [
    { label: `Все (${formatInt(o?.files_total ?? 0)})`, value: 'ALL' },
    ...MANIFEST_STAGES.filter((s) => (o?.files_by_stage[s] ?? 0) > 0 || s === stage).map((s) => ({
      label: `${STAGE_SHORT[s]} (${formatInt(o?.files_by_stage[s] ?? 0)})`,
      value: s,
    })),
  ];

  return (
    <Flex vertical gap={16}>
      <Breadcrumb items={[{ title: <Link to="/objects">Объекты</Link> }, { title: o?.name ?? objectId }]} />
      {object.isError ? (
        <ProblemAlert error={object.error} action={<Button onClick={() => void object.refetch()}>Повторить</Button>} />
      ) : !o ? (
        <Card>
          <Skeleton active />
        </Card>
      ) : (
        <>
          <Flex justify="space-between" align="center" wrap gap={12}>
            <div>
              <Typography.Title level={3} style={{ margin: 0 }}>
                {o.name ?? o.object_id}
              </Typography.Title>
              {o.name && <Typography.Text type="secondary">{o.object_id}</Typography.Text>}
            </div>
            <Space>
              <IndicatorBadge color={o.indicator_color} />
              <SplitTag split={o.split} />
            </Space>
          </Flex>
          {o.split === 'TEST_HIDDEN' && (
            <Alert
              type="warning"
              showIcon
              title="Объект скрытой тестовой выборки"
              description="Доступна только инвентаризация документов. Результаты распознавания и сравнения по этому объекту не показываются до отправки итогового ответа организаторам."
            />
          )}
        </>
      )}
      {o && (
        <Tabs
          activeKey={tab}
          onChange={(key) => {
            const next = new URLSearchParams(sp);
            if (key === 'overview') next.delete('tab');
            else next.set('tab', key);
            setSp(next, { replace: true });
          }}
          items={[
            {
              key: 'overview',
              label: 'Обзор',
              children: (
                <Flex vertical gap={16}>
                  <ObjectOverview object={o} />
          <Card>
                        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
                          <Descriptions.Item label="Всего файлов">{formatInt(o.files_total)}</Descriptions.Item>
                          <Descriptions.Item label="На диске">{formatInt(o.files_present)}</Descriptions.Item>
                          <Descriptions.Item label="Нет на диске">
                            {o.files_missing_on_disk > 0 ? (
                              <Typography.Text type="danger">{formatInt(o.files_missing_on_disk)}</Typography.Text>
                            ) : (
                              '0'
                            )}
                          </Descriptions.Item>
                          <Descriptions.Item label="Сценарий">{o.scenario ? enumLabel('LoadScenario', o.scenario) : 'определится после проверки'}</Descriptions.Item>
                          <Descriptions.Item label="Адрес">{o.address ?? 'не указан'}</Descriptions.Item>
                          {MANIFEST_STAGES.map((s) => (
                            <Descriptions.Item key={s} label={<Tooltip title={enumLabel('ManifestStage', s)}>{STAGE_SHORT[s]}</Tooltip>}>
                              {formatInt(o.files_by_stage[s])}
                            </Descriptions.Item>
                          ))}
                          <Descriptions.Item label="Последний импорт">
                            {o.last_run ? `${formatDateTime(o.last_run.imported_at)} · ${o.last_run.batch_run_id}` : '—'}
                          </Descriptions.Item>
                          <Descriptions.Item label="Хэш манифеста объекта">
                            <HashText value={o.input_manifest_hash} />
                          </Descriptions.Item>
                        </Descriptions>
                      </Card>
                </Flex>
              ),
            },
            {
              key: 'documents',
              label: `Документы (${formatInt(o.files_total)})`,
              children: (
      <Card title="Документы объекта">
                <Flex vertical gap={16}>
                  <Flex wrap gap={12} align="center">
                    <Segmented
                      options={stageOptions}
                      value={stage ?? 'ALL'}
                      onChange={(v) => {
                        setPage(1);
                        setStage(v === 'ALL' ? undefined : (v as ManifestStage));
                      }}
                    />
                    <Select
                      allowClear
                      placeholder="Наличие на диске"
                      style={{ width: 240 }}
                      value={localStatus}
                      onChange={(v) => {
                        setPage(1);
                        setLocalStatus(v);
                      }}
                      options={enumCodes('LocalFileStatus').map((code) => ({ value: code, label: enumLabel('LocalFileStatus', code) }))}
                    />
                    <Input.Search
                      allowClear
                      placeholder="Поиск по ID, имени или пути"
                      style={{ maxWidth: 360 }}
                      onSearch={(v) => {
                        setPage(1);
                        setQ(v.trim() || undefined);
                      }}
                    />
                  </Flex>
                  {files.isError ? (
                    <ProblemAlert error={files.error} />
                  ) : (
                    <Table<FileItem>
                      rowKey="file_id"
                      size="small"
                      columns={columns}
                      dataSource={files.data?.items ?? []}
                      loading={files.isLoading || files.isFetching}
                      scroll={{ x: 1100 }}
                      pagination={{
                        current: page,
                        pageSize,
                        total: files.data?.total ?? 0,
                        showSizeChanger: true,
                        pageSizeOptions: [20, 50, 100, 200],
                        showTotal: (total) => `Файлов: ${formatInt(total)}`,
                        onChange: (p, size) => {
                          setPage(size !== pageSize ? 1 : p);
                          setPageSize(size);
                        },
                      }}
                    />
                  )}
                </Flex>
              </Card>
              ),
            },
            { key: 'protocols', label: 'Протоколы', children: <ObjectProtocols object={o} /> },
            { key: 'runs', label: 'Запуски', children: <ObjectRuns object={o} /> },
          ]}
        />
      )}
    </Flex>
  );
}
