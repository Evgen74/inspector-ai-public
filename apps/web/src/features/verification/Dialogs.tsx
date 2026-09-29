/**
 * Finalization (ТЗ §9.3 п.4–5; 97 ruling 20: password confirmation = the inspector's simple e-signature),
 * un-finalization (reason ≥ 20 characters), sign-in and the hotkey help.
 */
import { useState } from 'react';
import { Alert, Button, Flex, Form, Input, List, Modal, Select, Space, Statistic, Table, Typography } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import { ApiError } from '../../api/client';
import { ProblemAlert } from '../../components/ProblemAlert';
import { formatDateTime, shortHash } from '../../format';
import { newKey, postFinalize, postUnfinalize, reauthToken, useLogin } from './api';
import { HOTKEY_HELP } from './hotkeys';
import type { DecisionCodes, FinalizeResult, UnfinalizeResult, VerificationSummary } from './types';

const BLOCKER_TEXT: Record<string, string> = {
  PENDING_CANDIDATE: 'Кандидаты без решения',
  OPEN_DISPUTE: 'Открытые споры с ИИ — примите повторное решение',
  PROCESS_NOT_COMPLETED: 'Верификация не завершена',
  RECHECK_IN_PROGRESS: 'Идёт инкрементальная проверка',
  RECHECK_FAILED: 'Инкрементальная проверка завершилась ошибкой',
};

const WARNING_TEXT: Record<string, string> = {
  CLARIFICATION_KEPT: 'Останутся «Требует уточнения» (явный перенос по п. 9.3.4)',
  MISSING_EVIDENCE: 'Параметры без обязательных документов (в протоколе отдельно)',
  NOT_COMPARABLE: 'Сравнение невозможно',
  PENDING_SUSPICIONS: 'Гипотезы ИИ без решения (в протоколе «не рассмотрено»)',
};

export function FinalizeDialog({
  open,
  summary,
  csrf,
  onClose,
  onDone,
  onJump,
}: {
  open: boolean;
  summary: VerificationSummary;
  csrf: string | null;
  onClose(): void;
  onDone(result: FinalizeResult): void;
  onJump(findingId: string): void;
}) {
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [key] = useState(newKey);
  const gate = summary.gate;
  const drafts = summary.counts.confirmed + summary.counts.negative;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const token = await reauthToken(password, csrf);
      const result = await postFinalize(summary.process_id, token, { ifMatch: summary.row_version, csrf, key });
      setPassword('');
      onDone(result);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title="Завершить верификацию и финализировать протокол" footer={null} width={640} destroyOnHidden>
      <Flex vertical gap={12} data-testid="finalize-dialog">
        <Flex gap={24} wrap>
          <Statistic title="Подтверждено" value={summary.counts.confirmed} />
          <Statistic title="Отклонено" value={summary.counts.negative} />
          <Statistic title="Требует уточнения" value={summary.counts.clarification} />
          <Statistic title="Ожидают решения" value={summary.counts.pending} />
        </Flex>
        {gate.blockers.length > 0 ? (
          <Alert
            type="error"
            showIcon
            title="Финализация пока невозможна"
            description={
              <List
                size="small"
                dataSource={gate.blockers}
                renderItem={(b) => (
                  <List.Item>
                    <Flex vertical gap={2}>
                      <span>
                        {BLOCKER_TEXT[b.code] ?? b.code}
                        {b.count && b.finding_ids.length ? `: ${b.count}` : ''}
                      </span>
                      <Space wrap size={4}>
                        {b.finding_ids.slice(0, 12).map((id) => (
                          <Button key={id} size="small" type="link" onClick={() => onJump(id)} style={{ padding: 0 }}>
                            {id.split('-').slice(-3).join('-')}
                          </Button>
                        ))}
                      </Space>
                    </Flex>
                  </List.Item>
                )}
              />
            }
          />
        ) : (
          <Alert type="success" showIcon title="Все кандидаты обработаны или явно переведены в «Требует уточнения»" />
        )}
        {gate.warnings.map((w) => (
          <Alert key={w.code} type="warning" showIcon title={`${WARNING_TEXT[w.code] ?? w.code}: ${w.count}`} />
        ))}
        <Alert
          type="info"
          showIcon
          title={`В ИАИС «РиН» будет передано: ${summary.counts.confirmed} подтверждённых нарушений + версии матрицы, модели, набора данных и реестр входных файлов`}
          description={`Черновиков набора данных (GOLD) из финальных решений: ${drafts}. В ответ для организаторов решения инспектора не попадают.`}
        />
        <Form layout="vertical" onFinish={() => void submit()}>
          <Form.Item label="Подтвердите паролем (простая электронная подпись решения)" required>
            <Input.Password
              prefix={<LockOutlined />}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              aria-label="Пароль для подтверждения"
              disabled={!gate.can_finalize}
            />
          </Form.Item>
          {error ? <ProblemAlert error={error} /> : null}
          <Flex justify="end" gap={8} style={{ marginTop: 8 }}>
            <Button onClick={onClose}>Отмена</Button>
            <Button type="primary" htmlType="submit" disabled={!gate.can_finalize || !password} loading={busy} data-testid="finalize-submit">
              Подписать и завершить
            </Button>
          </Flex>
        </Form>
      </Flex>
    </Modal>
  );
}

export function UnfinalizeDialog({
  open,
  summary,
  codes,
  csrf,
  onClose,
  onDone,
}: {
  open: boolean;
  summary: VerificationSummary;
  codes: DecisionCodes;
  csrf: string | null;
  onClose(): void;
  onDone(result: UnfinalizeResult): void;
}) {
  const [reasonCode, setReasonCode] = useState<string | undefined>();
  const [text, setText] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [key] = useState(newKey);
  const min = codes.limits.unfinalize_reason_min;
  const ok = Boolean(reasonCode) && text.trim().length >= min && Boolean(password);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const token = await reauthToken(password, csrf);
      onDone(await postUnfinalize(summary.process_id, { reason_code: reasonCode!, reason_text: text.trim(), reauth_token: token }, { ifMatch: summary.row_version, csrf, key }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title="Отменить финализацию" footer={null} destroyOnHidden>
      <Flex vertical gap={10} data-testid="unfinalize-dialog">
        <Typography.Text type="secondary">
          Окончательная версия протокола сохранится в истории; будет создана рабочая версия в статусе «Верификация
          завершена». Черновики набора данных этой версии будут приостановлены. Действие записывается в журнал аудита.
        </Typography.Text>
        <Select aria-label="Причина отмены" placeholder="Причина" value={reasonCode} onChange={setReasonCode} options={codes.unfinalize.map((c) => ({ value: c.code, label: c.label_ru }))} />
        <Input.TextArea aria-label="Описание причины" rows={3} placeholder={`Описание причины — не короче ${min} символов`} value={text} onChange={(e) => setText(e.target.value)} />
        <Input.Password aria-label="Пароль для подтверждения" placeholder="Пароль" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        {error ? <ProblemAlert error={error} /> : null}
        <Flex justify="end" gap={8}>
          <Button onClick={onClose}>Отмена</Button>
          <Button danger type="primary" disabled={!ok} loading={busy} onClick={() => void submit()} data-testid="unfinalize-submit">
            Отменить финализацию
          </Button>
        </Flex>
      </Flex>
    </Modal>
  );
}

export function LoginPanel() {
  const login = useLogin();
  const [form] = Form.useForm<{ login: string; password: string }>();
  const error = login.error instanceof ApiError ? login.error : login.error ? new ApiError(0, null, '') : null;
  return (
    <Alert
      type="info"
      showIcon
      title="Войдите, чтобы принимать решения"
      description={
        <Form form={form} layout="inline" onFinish={(v) => login.mutate(v)} style={{ marginTop: 6, rowGap: 6 }}>
          <Form.Item name="login" rules={[{ required: true, message: 'Логин' }]}>
            <Input placeholder="Логин" autoComplete="username" aria-label="Логин" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: 'Пароль' }]}>
            <Input.Password placeholder="Пароль" autoComplete="current-password" aria-label="Пароль" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={login.isPending}>
            Войти
          </Button>
          {error && <Typography.Text type="danger">{error.detail}</Typography.Text>}
        </Form>
      }
    />
  );
}

export function HelpModal({ open, onClose }: { open: boolean; onClose(): void }) {
  return (
    <Modal open={open} onCancel={onClose} footer={null} title="Клавиши верификации">
      <Table
        size="small"
        pagination={false}
        rowKey={(r) => r[0]}
        dataSource={HOTKEY_HELP}
        columns={[
          { title: 'Клавиша', key: 'k', render: (_, r) => <Typography.Text keyboard>{r[0]}</Typography.Text>, width: 150 },
          { title: 'Действие', key: 'a', render: (_, r) => r[1] },
        ]}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
        Замер юзабилити (п. 9.3 ТЗ): клики считаются от показа карточки до сохранения решения по элементам
        управления; перемещение и масштаб документа и набор текста кликами не считаются; клавиши учитываются
        отдельно. Переход к следующей карточке — автоматический.
      </Typography.Paragraph>
    </Modal>
  );
}

export function FinalizedBanner({ summary }: { summary: VerificationSummary }) {
  const p = summary.protocol;
  return (
    <Alert
      type="success"
      showIcon
      icon={<LockOutlined />}
      data-testid="finalized-banner"
      title={`Протокол финализирован ${formatDateTime(p?.finalized_at ?? summary.finalized_at)}${p?.finalized_by ? `, ${p.finalized_by.full_name}` : ''}`}
      description={`Версия ${p?.version ?? '—'} (окончательная) · SHA-256 ${shortHash(p?.content_sha256, 12)} · изменения и дозагрузка невозможны`}
    />
  );
}
