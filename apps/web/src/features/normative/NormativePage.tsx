/** Module 8 «Нормативная база»: 132 parameters (search, filters, editing of thresholds/activity), documents, versions. */
import { useState } from 'react';
import { App, Button, Card, Checkbox, Descriptions, Flex, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import { ProblemAlert } from '../../components/ProblemAlert';
import { enumLabel } from '../../contracts/enums';
import { confidenceLabel } from '../../contracts/labels';
import { formatDateTime } from '../../format';
import { hasPermission, useAuthSession } from '../verification/api';
import { type MatrixVersion, type NormDocument, type NormParam, type NormRef, useMatrixVersions, useNormDocuments, useNormParams, useUpdateParam } from './api';

const REF_KIND: Record<string, string> = { sp: 'СП', gost: 'ГОСТ', fz: 'Закон', other: 'Иное' };
const REF_STATUS: Record<string, { label: string; color: string }> = {
  CONFIRMED: { label: 'подтверждена', color: 'green' },
  ADDED: { label: 'добавлена', color: 'blue' },
  CORRECTED: { label: 'исправлена', color: 'gold' },
  OUTDATED: { label: 'устарела', color: 'red' },
};

const fmt = (v: number | null, unit: string | null) =>
  v === null ? <Typography.Text type="secondary">не задан</Typography.Text> : `${v}${unit ? ` ${unit}` : ''}`;

function RefTags({ refs }: { refs: NormRef[] }) {
  if (!refs.length) return <Typography.Text type="secondary">—</Typography.Text>;
  return (
    <Flex gap={4} wrap>
      {refs.slice(0, 3).map((r, i) => {
        const st = REF_STATUS[r.status ?? ''];
        return (
          <Tooltip key={i} title={[r.clause, r.edition].filter(Boolean).join(' · ')}>
            <Tag color={st?.color} data-code={r.status ?? undefined}>
              {r.designation}
              {r.status ? ` · ${st?.label ?? r.status}` : ''}
              {r.confidence ? ` · уверенность: ${confidenceLabel(r.confidence).toLowerCase()}` : ''}
            </Tag>
          </Tooltip>
        );
      })}
      {refs.length > 3 && <Tag>+{refs.length - 3}</Tag>}
    </Flex>
  );
}

function EditModal({ param, csrf, onClose }: { param: NormParam; csrf: string | null | undefined; onClose: () => void }) {
  const { message } = App.useApp();
  const update = useUpdateParam(csrf);
  const [min, setMin] = useState<number | null>(param.min_value);
  const [max, setMax] = useState<number | null>(param.max_value);
  const [active, setActive] = useState(param.is_active);
  const [reason, setReason] = useState('');
  const save = () =>
    update.mutate(
      { code: param.code, patch: { min_value: min, max_value: max, is_active: active, reason: reason || null } },
      {
        onSuccess: (r) => {
          void message.success(r.unchanged ? 'Изменений нет' : `Сохранено. Версия матрицы ${r.matrix_version}`);
          onClose();
        },
      },
    );
  return (
    <Modal open title={`${param.code} · ${param.name}`} onCancel={onClose} onOk={save} okText="Сохранить" cancelText="Отмена" confirmLoading={update.isPending} destroyOnHidden>
      <Flex vertical gap={12}>
        {update.isError && <ProblemAlert error={update.error} />}
        <Space>
          <span>Минимум{param.unit ? `, ${param.unit}` : ''}</span>
          <InputNumber aria-label="Минимум" value={min} onChange={setMin} />
          <span>Максимум</span>
          <InputNumber aria-label="Максимум" value={max} onChange={setMax} />
        </Space>
        <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)}>
          Параметр активен (участвует в проверке)
        </Checkbox>
        <Input.TextArea placeholder="Основание изменения (попадёт в журнал аудита)" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
        <Typography.Text type="secondary">Каждое сохранение создаёт новую версию матрицы и запись в журнале аудита.</Typography.Text>
      </Flex>
    </Modal>
  );
}

function ParamsTab({ canEdit, csrf }: { canEdit: boolean; csrf: string | null | undefined }) {
  const [q, setQ] = useState('');
  const [section, setSection] = useState<string>();
  const [criticality, setCriticality] = useState<string>();
  const [active, setActive] = useState<string>();
  const [editing, setEditing] = useState<NormParam | null>(null);
  const query = useNormParams({ q, section, criticality, active });
  const data = query.data;
  const columns: TableColumnsType<NormParam> = [
    { title: 'Код', dataIndex: 'code', width: 130, render: (c: string) => <Typography.Text code style={{ whiteSpace: 'nowrap' }}>{c}</Typography.Text> },
    { title: 'Параметр', dataIndex: 'name', width: 240 },
    { title: 'Раздел', dataIndex: 'section', width: 80 },
    {
      title: 'Критичность',
      dataIndex: 'criticality_level',
      width: 130,
      render: (c: string) => <Tag color={c === 'CRITICAL_SUSPEND' ? 'red' : 'gold'}>{enumLabel('CriticalityLevel', c)}</Tag>,
    },
    {
      title: 'Порог мин.',
      width: 110,
      render: (_: unknown, r) => (
        <span>
          {fmt(r.min_value, r.unit)}
          {r.overridden && r.min_value !== r.base_min_value && <Tag color="purple" style={{ marginLeft: 4 }}>правка</Tag>}
        </span>
      ),
    },
    {
      title: 'Порог макс.',
      width: 110,
      render: (_: unknown, r) => (
        <span>
          {fmt(r.max_value, r.unit)}
          {r.overridden && r.max_value !== r.base_max_value && <Tag color="purple" style={{ marginLeft: 4 }}>правка</Tag>}
        </span>
      ),
    },
    { title: 'Нормативные ссылки', width: 320, render: (_: unknown, r) => <RefTags refs={r.refs} /> },
    { title: 'Активен', dataIndex: 'is_active', width: 90, fixed: 'right' as const, render: (a: boolean) => <Tag color={a ? 'green' : 'default'}>{a ? 'да' : 'нет'}</Tag> },
    ...(canEdit
      ? [{ title: '', width: 60, fixed: 'right' as const, render: (_: unknown, r: NormParam) => <Button size="small" icon={<EditOutlined />} aria-label={`Изменить ${r.code}`} onClick={() => setEditing(r)} /> }]
      : []),
  ];
  return (
    <Flex vertical gap={12}>
      <Flex gap={8} wrap>
        <Input.Search allowClear placeholder="Поиск по коду, названию, документу" style={{ width: 320 }} onSearch={setQ} />
        <Select allowClear placeholder="Раздел" style={{ width: 130 }} value={section} onChange={setSection} options={(data?.sections ?? []).map((s) => ({ value: s, label: s }))} />
        <Select
          allowClear
          placeholder="Критичность"
          style={{ width: 170 }}
          value={criticality}
          onChange={setCriticality}
          options={['CRITICAL_SUSPEND', 'SUBSTANTIAL_ORDER'].map((c) => ({ value: c, label: enumLabel('CriticalityLevel', c) }))}
        />
        <Select allowClear placeholder="Активность" style={{ width: 140 }} value={active} onChange={setActive} options={[{ value: 'true', label: 'Активные' }, { value: 'false', label: 'Отключённые' }]} />
        {data && (
          <Typography.Text type="secondary" style={{ alignSelf: 'center' }}>
            Показано {data.items.length} из {data.total} · версия матрицы {data.matrix_version} · правок: {data.overrides}
          </Typography.Text>
        )}
      </Flex>
      {query.isError ? (
        <ProblemAlert error={query.error} />
      ) : (
        <Table<NormParam>
          rowKey="code"
          size="small"
          loading={query.isLoading}
          dataSource={data?.items ?? []}
          columns={columns}
          pagination={{ pageSize: 25, showSizeChanger: false }}
          scroll={{ x: 1350 }}
          expandable={{
            expandedRowRender: (r) => (
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="Источник порога">{r.threshold_source ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="Примечание">{r.threshold_note ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="Нормативные ссылки">
                  {r.refs.map((x, i) => (
                    <div key={i}>
                      {REF_KIND[x.kind]} · {x.designation}
                      {x.clause ? `, ${x.clause}` : ''} — {REF_STATUS[x.status ?? '']?.label ?? x.status ?? '—'} (уверенность: {x.confidence ? confidenceLabel(x.confidence).toLowerCase() : '—'})
                    </div>
                  ))}
                </Descriptions.Item>
              </Descriptions>
            ),
          }}
        />
      )}
      {editing && <EditModal param={editing} csrf={csrf} onClose={() => setEditing(null)} />}
    </Flex>
  );
}

function DocumentsTab() {
  const q = useNormDocuments();
  const columns: TableColumnsType<NormDocument> = [
    { title: 'Документ', dataIndex: 'designation', width: 260 },
    { title: 'Вид', dataIndex: 'kind', width: 90, render: (k: string) => REF_KIND[k] ?? k },
    {
      title: 'Редакция',
      dataIndex: 'edition',
      width: 300,
      ellipsis: { showTitle: false },
      render: (e: string | null) =>
        e ? (
          <Tooltip title={e} placement="topLeft" styles={{ root: { maxWidth: 520 } }}>
            <span>{e}</span>
          </Tooltip>
        ) : (
          '—'
        ),
    },
    { title: 'Статус', dataIndex: 'status', width: 130, render: (s: string | null) => (s ? <Tag color={REF_STATUS[s]?.color}>{REF_STATUS[s]?.label ?? s}</Tag> : '—') },
    { title: 'Параметров', dataIndex: 'params_count', width: 110, align: 'right' },
  ];
  return q.isError ? <ProblemAlert error={q.error} /> : <Table<NormDocument> rowKey="designation" size="small" loading={q.isLoading} dataSource={q.data?.items ?? []} columns={columns} pagination={{ pageSize: 25, showSizeChanger: false }} scroll={{ x: 900 }} />;
}

function VersionsTab() {
  const q = useMatrixVersions();
  const columns: TableColumnsType<MatrixVersion> = [
    { title: 'Версия матрицы', dataIndex: 'matrix_version', width: 170, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
    { title: 'Когда', dataIndex: 'created_at', width: 160, render: formatDateTime },
    { title: 'Кто', dataIndex: 'created_by_login', width: 130, render: (v: string | null) => v ?? '—' },
    {
      title: 'Изменения',
      render: (_: unknown, r) =>
        r.changes.map((c, i) => (
          <div key={i}>
            {c.param_code}: {Object.entries(c.fields).map(([f, v]) => `${f} ${String(v.from ?? '—')} → ${String(v.to ?? '—')}`).join('; ')}
          </div>
        )),
    },
    { title: 'Основание', dataIndex: 'reason', render: (v: string | null) => v ?? '—' },
  ];
  return q.isError ? <ProblemAlert error={q.error} /> : <Table<MatrixVersion> rowKey="version" size="small" loading={q.isLoading} dataSource={q.data?.items ?? []} columns={columns} locale={{ emptyText: `Правок нет: действует базовая версия ${q.data?.base_version ?? ''}` }} pagination={false} />;
}

export function NormativePage() {
  const session = useAuthSession();
  const canEdit = hasPermission(session.data, 'params.manage');
  return (
    <Flex vertical gap={12}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Нормативная база
      </Typography.Title>
      <Card size="small">
        <Tabs
          items={[
            { key: 'params', label: 'Параметры (матрица 132)', children: <ParamsTab canEdit={canEdit} csrf={session.data?.csrf_token} /> },
            { key: 'docs', label: 'Нормативные документы', children: <DocumentsTab /> },
            { key: 'versions', label: 'Версии матрицы', children: <VersionsTab /> },
          ]}
        />
      </Card>
    </Flex>
  );
}

