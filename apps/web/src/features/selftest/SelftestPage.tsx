/** «Самопроверка» (module 12): negative scenarios run against the live API; pass / fail in Russian. */
import { PlayCircleOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Empty, Flex, Statistic, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { Link } from 'react-router';
import { ProblemAlert } from '../../components/ProblemAlert';
import { formatDateTime, formatInt } from '../../format';
import { useAuthSession } from '../verification/api';
import { type SelftestReport, useRunSelftest } from './api';

type Result = SelftestReport['results'][number];

export const SELFTEST_STATUS: Record<string, { text: string; color: string }> = {
  PASS: { text: 'Пройдена', color: 'green' },
  FAIL: { text: 'Не пройдена', color: 'red' },
  NOT_IMPLEMENTED: { text: 'не реализовано', color: 'default' },
  SKIPPED: { text: 'Пропущена', color: 'gold' },
};

export function SelftestPage() {
  const session = useAuthSession();
  const run = useRunSelftest(session.data?.csrf_token);
  const report = run.data;

  const columns: TableColumnsType<Result> = [
    { title: 'Группа', dataIndex: 'group', width: 130 },
    { title: 'Сценарий', dataIndex: 'title' },
    { title: 'Ожидается', dataIndex: 'expected', width: 190 },
    { title: 'Получено', dataIndex: 'actual', width: 190, render: (a: string) => <Typography.Text code>{a}</Typography.Text> },
    {
      title: 'Результат',
      dataIndex: 'status',
      width: 140,
      render: (s: string) => (
        <Tag data-code={s} color={SELFTEST_STATUS[s]?.color}>
          {SELFTEST_STATUS[s]?.text ?? s}
        </Tag>
      ),
    },
    { title: 'Пояснение', dataIndex: 'detail', render: (d: string | null) => d ?? '—' },
  ];

  return (
    <Flex vertical gap={16} data-testid="selftest-page">
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Самопроверка
        </Typography.Title>
        <Link to="/admin/monitoring">Мониторинг</Link>
      </Flex>
      <Typography.Text type="secondary">
        Негативные сценарии выполняются на работающем API: недопустимые файлы и размеры, запросы без прав, решения после
        финализации, недоступная очередь. Данные не изменяются.
      </Typography.Text>
      <Flex>
        <Button type="primary" icon={<PlayCircleOutlined />} loading={run.isPending} onClick={() => run.mutate()}>
          Запустить проверки
        </Button>
      </Flex>
      {run.isError && <ProblemAlert error={run.error} />}
      {report ? (
        <>
          {report.summary.fail > 0 ? (
            <Alert type="error" showIcon title={`Не пройдено сценариев: ${report.summary.fail}`} />
          ) : (
            <Alert type="success" showIcon title="Ни один сценарий не провален" />
          )}
          <Flex gap={32} wrap>
            <Statistic title="Всего" value={report.summary.total} />
            <Statistic title="Пройдено" value={report.summary.pass} styles={{ content: { color: '#2E7D32' } }} />
            <Statistic title="Не пройдено" value={report.summary.fail} styles={{ content: { color: report.summary.fail ? '#C62828' : undefined } }} />
            <Statistic title="Не реализовано" value={report.summary.not_implemented} />
            <Statistic title="Пропущено" value={report.summary.skipped} />
          </Flex>
          <Card size="small" extra={<Typography.Text type="secondary">{formatDateTime(report.started_at)} · {formatInt(report.duration_ms)} мс</Typography.Text>}>
            <Table<Result> rowKey="id" size="small" columns={columns} dataSource={report.results} pagination={false} scroll={{ x: 1000 }} />
          </Card>
        </>
      ) : (
        !run.isPending && <Empty description="Проверки ещё не запускались" />
      )}
    </Flex>
  );
}
