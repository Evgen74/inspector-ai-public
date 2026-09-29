/** Sync status with ИАИС «РиН» on the protocol page (ТЗ module 6): status, attempts log, manual send. */
import { Alert, Button, Card, Descriptions, Flex, Space, Table, Tag, Tooltip, Typography } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { ProblemAlert } from '../../components/ProblemAlert';
import { formatDateTime } from '../../format';
import { useObjectVerification } from '../verification/api';
import { hasPermission, useAuthSession } from '../verification/api';
import { type RinDelivery, useRinStatus, useSendToRin } from './api';

const COLORS: Record<string, string> = { PENDING_SYNC: 'gold', SYNCED: 'green', SYNC_FAILED: 'red' };
const OUTCOME: Record<string, string> = { SUCCESS: 'успех', RETRYABLE_HTTP: 'ошибка, повтор', NON_RETRYABLE: 'ошибка, без повтора' };

export function RinSyncCard({ objectId, runId }: { objectId: string; runId: string }) {
  const verification = useObjectVerification(objectId);
  const process = verification.data?.processes.find((p) => p.run.run_id === runId);
  const processId = process?.process_id;
  const status = useRinStatus(processId);
  const session = useAuthSession();
  const send = useSendToRin(processId ?? '', session.data?.csrf_token);
  if (!process) return null;
  const finalized = process.status === 'FINALIZED';
  const canSend = hasPermission(session.data, 'rin.send');
  const d: RinDelivery | undefined = status.data;
  const log = d?.attempts_log ?? [];
  const blockedReason = !finalized ? 'Отправка доступна только для утверждённого протокола (PROTOCOL_FINALIZED)' : !canSend ? 'Нет права на отправку в РиН' : null;
  return (
    <Card size="small" title="Синхронизация с ИАИС «РиН»" data-testid="rin-card">
      <Flex vertical gap={8}>
        <Flex justify="space-between" align="center" wrap gap={8}>
          <Space>
            {d?.status ? (
              <Tag color={COLORS[d.status]} data-code={d.status}>
                {d.status_label}
              </Tag>
            ) : (
              <Tag>Не отправлялось</Tag>
            )}
            {d?.status && (
              <Typography.Text type="secondary">
                попыток {d.attempts}
                {d.max_attempts ? ` из ${d.max_attempts}` : ''}
                {d.violations !== undefined ? ` · нарушений в пакете: ${d.violations}` : ''}
              </Typography.Text>
            )}
          </Space>
          <Tooltip title={blockedReason}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              disabled={Boolean(blockedReason) || d?.status === 'PENDING_SYNC'}
              loading={send.isPending}
              onClick={() => send.mutate({ force: d?.status === 'SYNCED' || d?.status === 'SYNC_FAILED' })}
            >
              {d?.status === 'SYNCED' ? 'Отправить повторно' : 'Отправить в РиН'}
            </Button>
          </Tooltip>
        </Flex>
        {!finalized && <Alert type="info" showIcon title="Протокол ещё не утверждён: результаты уйдут в РиН после финализации." />}
        {(status.isError || send.isError) && <ProblemAlert error={send.error ?? status.error} />}
        {d?.status === 'SYNCED' && (
          <Descriptions size="small" column={2}>
            <Descriptions.Item label="Идентификатор в РиН">{d.external_id}</Descriptions.Item>
            <Descriptions.Item label="Синхронизировано">{formatDateTime(d.synced_at)}</Descriptions.Item>
          </Descriptions>
        )}
        {d?.status === 'PENDING_SYNC' && d.last_error && (
          <Alert type="warning" showIcon title={`Повтор запланирован: ${formatDateTime(d.next_attempt_at)}`} description={d.last_error} />
        )}
        {d?.status === 'SYNC_FAILED' && <Alert type="error" showIcon title="Не удалось передать данные в РиН" description={d.last_error} />}
        {log.length > 0 && (
          <Table
            size="small"
            pagination={false}
            rowKey="attempt_no"
            dataSource={log}
            columns={[
              { title: '№', dataIndex: 'attempt_no', width: 50 },
              { title: 'Время', dataIndex: 'started_at', width: 150, render: formatDateTime },
              { title: 'Результат', dataIndex: 'outcome', width: 150, render: (o: string) => OUTCOME[o] ?? o },
              { title: 'HTTP', dataIndex: 'http_status', width: 70, render: (v: number | null) => v ?? '—' },
              { title: 'Сообщение', dataIndex: 'detail', render: (v: string | null) => v ?? '—' },
            ]}
          />
        )}
      </Flex>
    </Card>
  );
}
