/** «Протоколы»: the latest protocol of every object (versions are on the object card). */
import { Card, Empty, Flex, Table, Tag, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { Link, useNavigate } from 'react-router';
import { type DashboardObject, useDashboard } from '../api/d1';
import { ProblemAlert } from '../components/ProblemAlert';
import { IndicatorTag } from '../components/indicator';
import { enumLabel } from '../contracts/enums';
import { protocolStatusColor, protocolStatusText } from '../contracts/labels';
import { ExportButtons } from '../features/protocol/ExportButtons';
import { formatDateTime } from '../format';

export function ProtocolsPage() {
  const navigate = useNavigate();
  const dash = useDashboard({});
  const rows = (dash.data?.items ?? []).filter((o) => o.latest_protocol);
  const columns: TableColumnsType<DashboardObject> = [
    { title: 'Индикация', key: 'ind', width: 190, render: (_, o) => <IndicatorTag indicator={o.indicator} /> },
    {
      title: 'Протокол',
      key: 'no',
      render: (_, o) => (
        <Flex vertical>
          <Link to={`/objects/${encodeURIComponent(o.object_id)}/protocols/${o.latest_protocol!.run_id}`}>
            № {o.latest_protocol!.protocol_no}
          </Link>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {o.name ?? o.object_id}
            {o.name ? ` · ${o.object_id}` : ''}
          </Typography.Text>
        </Flex>
      ),
    },
    { title: 'Сформирован', key: 'at', width: 140, render: (_, o) => formatDateTime(o.latest_protocol!.generated_at) },
    {
      title: 'Статус',
      key: 'st',
      width: 220,
      render: (_, o) => (
        <Tooltip title={o.latest_protocol!.status_line}>
          <Tag color={protocolStatusColor(o.latest_protocol!.status)}>
            {protocolStatusText(o.latest_protocol!.status, o.latest_protocol!.web_version)}
          </Tag>
        </Tooltip>
      ),
    },
    { title: 'Тип проверки', key: 'sc', width: 170, render: (_, o) => enumLabel('LoadScenario', o.latest_protocol!.scenario) },
    {
      title: 'Выгрузка',
      key: 'exp',
      width: 200,
      render: (_, o) => (
        <span onClick={(e) => e.stopPropagation()}>
          <ExportButtons objectId={o.object_id} version={o.latest_protocol!} />
        </span>
      ),
    },
  ];
  return (
    <Flex vertical gap={16}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Протоколы
      </Typography.Title>
      {dash.isError ? (
        <ProblemAlert error={dash.error} />
      ) : (
        <Card size="small">
          <Table<DashboardObject>
            rowKey="object_id"
            size="small"
            dataSource={rows}
            columns={columns}
            loading={dash.isLoading}
            pagination={false}
            onRow={(o) => ({
              onClick: () => navigate(`/objects/${encodeURIComponent(o.object_id)}/protocols/${o.latest_protocol!.run_id}`),
              style: { cursor: 'pointer' },
            })}
            locale={{ emptyText: <Empty description="Протоколов пока нет: они появятся после проверки загруженных документов" /> }}
          />
        </Card>
      )}
    </Flex>
  );
}
