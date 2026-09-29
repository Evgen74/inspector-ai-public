/** Upload wizard: files (drag-and-drop) → object and optional registry → result. Limits of ТЗ §9.1 are shown up front. */
import { useMemo, useState } from 'react';
import { Alert, Button, Descriptions, Flex, Form, Input, List, Modal, Steps, Tag, Typography, Upload } from 'antd';
import type { UploadFile } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router';
import { ProblemAlert } from '../../components/ProblemAlert';
import { formatBytes, formatInt, pluralRu } from '../../format';
import { DEFAULT_LIMITS, useUploadDocuments, useUploadLimits, type UploadResult, validateClientFiles } from './api';

const REGISTRY_EXT = ['.csv', '.xlsx', '.json'];

export function UploadWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const limitsQuery = useUploadLimits(open);
  const limits = limitsQuery.data ?? DEFAULT_LIMITS;
  const mutation = useUploadDocuments();
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [registry, setRegistry] = useState<UploadFile[]>([]);
  const [objectName, setObjectName] = useState('');
  const [address, setAddress] = useState('');
  const [result, setResult] = useState<UploadResult | null>(null);

  const check = useMemo(
    () => validateClientFiles(files.map((f) => ({ name: f.name, size: f.size ?? 0 })), limits),
    [files, limits],
  );
  const registryError = useMemo(() => {
    const r = registry[0];
    if (!r) return null;
    const ext = r.name.slice(r.name.lastIndexOf('.')).toLowerCase();
    return REGISTRY_EXT.includes(ext) ? null : 'Реестр: допустимы форматы CSV, XLSX, JSON.';
  }, [registry]);
  const valid = files.length > 0 && check.errors.size === 0 && !check.packageError;

  const reset = () => {
    setStep(0);
    setFiles([]);
    setRegistry([]);
    setObjectName('');
    setAddress('');
    setResult(null);
    mutation.reset();
  };
  const close = () => {
    reset();
    onClose();
  };

  const submit = async () => {
    const res = await mutation
      .mutateAsync({
        files: files.flatMap((f) => (f.originFileObj ? [f.originFileObj as File] : [])),
        registry: registry[0]?.originFileObj as File | undefined,
        objectName,
        address,
      })
      .catch(() => null);
    if (res) {
      setResult(res);
      setStep(2);
    }
  };

  const footer =
    step === 0
      ? [
          <Button key="c" onClick={close}>
            Отмена
          </Button>,
          <Button key="n" type="primary" disabled={!valid} onClick={() => setStep(1)}>
            Далее
          </Button>,
        ]
      : step === 1
        ? [
            <Button key="b" onClick={() => setStep(0)}>
              Назад
            </Button>,
            <Button key="s" type="primary" loading={mutation.isPending} disabled={!!registryError} onClick={() => void submit()}>
              Загрузить и проверить
            </Button>,
          ]
        : [
            <Button key="c" onClick={close}>
              Закрыть
            </Button>,
            <Button
              key="o"
              type="primary"
              onClick={() => {
                const id = result?.process_id;
                close();
                if (id) navigate(`/processes/${id}`);
              }}
            >
              Открыть проверку
            </Button>,
          ];

  return (
    <Modal open={open} onCancel={close} title="Загрузка комплекта документов" width={720} footer={footer} destroyOnHidden>
      <Flex vertical gap={16}>
        <Steps
          size="small"
          current={step}
          items={[{ title: 'Файлы' }, { title: 'Объект и реестр' }, { title: 'Проверка' }]}
        />
        {step === 0 && (
          <>
            <Alert
              type="info"
              showIcon
              title="Требования к загрузке"
              description={`PDF, DOCX, XML и архивы ZIP, 7z, RAR. Не более ${formatBytes(limits.max_file_bytes)} на файл и ${formatBytes(
                limits.max_package_bytes,
              )} на весь пакет. Стадия (ПД, РД, ИД) определяется по реестру, а без него — по названиям папок и файлов.`}
            />
            <Upload.Dragger
              multiple
              fileList={files}
              beforeUpload={() => false}
              onChange={(info) => setFiles(info.fileList)}
              // No `accept`: unsupported files must stay in the list with a Russian reason instead of being dropped silently.
              itemRender={(node, file) => {
                const err = check.errors.get(file.name);
                return (
                  <div>
                    {node}
                    {err && <Typography.Text type="danger">{err}</Typography.Text>}
                  </div>
                );
              }}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">Перетащите файлы сюда или нажмите для выбора</p>
              <p className="ant-upload-hint">Можно выбрать несколько файлов сразу</p>
            </Upload.Dragger>
            <Typography.Text type="secondary">
              Выбрано: {formatInt(files.length)} {pluralRu(files.length, ['файл', 'файла', 'файлов'])}, {formatBytes(check.totalBytes)} из{' '}
              {formatBytes(limits.max_package_bytes)}
            </Typography.Text>
            {check.packageError && <Alert type="error" showIcon title={check.packageError} />}
            {check.errors.size > 0 && (
              <Alert
                type="error"
                showIcon
                title={`Не принимаются файлов: ${check.errors.size}. Удалите их из списка или замените.`}
              />
            )}
          </>
        )}
        {step === 1 && (
          <>
            <Form layout="vertical">
              <Form.Item label="Наименование объекта">
                <Input aria-label="Наименование объекта" value={objectName} onChange={(e) => setObjectName(e.target.value)} maxLength={200} placeholder="Например: Жилой дом, ул. Тестовая 7" />
              </Form.Item>
              <Form.Item label="Адрес (необязательно)">
                <Input aria-label="Адрес" value={address} onChange={(e) => setAddress(e.target.value)} maxLength={300} />
              </Form.Item>
              <Form.Item
                label="Реестр комплекта (необязательно)"
                extra="CSV, XLSX или JSON со столбцами «файл» и «стадия» (ПД / РД / ИД), при желании «раздел»."
                validateStatus={registryError ? 'error' : undefined}
                help={registryError}
              >
                <Upload maxCount={1} fileList={registry} beforeUpload={() => false} onChange={(i) => setRegistry(i.fileList)} accept={REGISTRY_EXT.join(',')}>
                  <Button>Выбрать файл реестра</Button>
                </Upload>
              </Form.Item>
            </Form>
            {mutation.isError && <ProblemAlert error={mutation.error} />}
          </>
        )}
        {step === 2 && result && (
          <>
            <Alert
              type="success"
              showIcon
              title="Комплект принят, проверка поставлена в очередь"
              description="Статус обновляется автоматически на странице проверки. Когда протокол будет готов, появится ссылка на него."
            />
            <Descriptions size="small" column={1} items={[
              { key: 'p', label: 'Идентификатор проверки', children: <Typography.Text copyable>{result.process_id}</Typography.Text> },
              { key: 'o', label: 'Объект', children: result.object_id },
              { key: 'a', label: 'Принято файлов', children: formatInt(result.accepted.length) },
            ]} />
            {result.rejected.length > 0 && (
              <List
                size="small"
                header={<Typography.Text type="danger">Отклонено файлов: {result.rejected.length}</Typography.Text>}
                dataSource={result.rejected}
                renderItem={(r) => (
                  <List.Item>
                    <Flex vertical>
                      <Typography.Text strong>{r.name} <Tag color="red">{r.code}</Tag></Typography.Text>
                      <Typography.Text type="secondary">{r.detail}</Typography.Text>
                    </Flex>
                  </List.Item>
                )}
              />
            )}
          </>
        )}
      </Flex>
    </Modal>
  );
}
