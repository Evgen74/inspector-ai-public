/** App shell (08 §3.3): collapsible left menu in Russian, top bar with the product name, routed content. */
import { useState } from 'react';
import { Button, Layout, Menu, Modal, Space, Tag, theme, Typography } from 'antd';
import type { MenuProps } from 'antd';
import {
  AuditOutlined,
  BankOutlined,
  BookOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FundProjectionScreenOutlined,
  FileProtectOutlined,
  LineChartOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Link, Outlet, useLocation } from 'react-router';
import { apiFetch } from '../api/client';
import { enumLabel } from '../contracts/enums';
import { hasPermission, useAuthSession, vKeys } from '../features/verification/api';
import { LoginPanel } from '../features/verification/Dialogs';
import type { AuthSession } from '../features/verification/types';

/** «Фамилия И. О. · Инспектор» — the roles come from enums.yaml (Role). */
export function sessionLabel(session: AuthSession): { name: string; role: string } {
  const role = session.roles.map((r) => enumLabel('Role', r)).join(', ');
  return { name: session.user.full_name || session.user.login, role };
}

export function UserMenu() {
  const client = useQueryClient();
  const session = useAuthSession();
  const [busy, setBusy] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  if (session.isPending) return null;
  if (!session.data) {
    return (
      <>
        <Button size="small" type="primary" onClick={() => setLoginOpen(true)} data-testid="login-button">
          Войти
        </Button>
        <Modal open={loginOpen} onCancel={() => setLoginOpen(false)} footer={null} title="Вход в систему" destroyOnHidden>
          <LoginPanel />
        </Modal>
      </>
    );
  }
  const { name, role } = sessionLabel(session.data);
  const logout = async () => {
    setBusy(true);
    try {
      await apiFetch('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': session.data!.csrf_token } });
    } catch {
      /* the session is dropped locally either way */
    } finally {
      client.setQueryData(vKeys.me, null);
      void client.invalidateQueries();
      setBusy(false);
    }
  };
  return (
    <Space size={8} data-testid="user-menu">
      <span style={{ lineHeight: 1.2, textAlign: 'right' }}>
        <Typography.Text strong style={{ display: 'block', fontSize: 13 }}>{name}</Typography.Text>
        <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>{role}</Typography.Text>
      </span>
      <Button size="small" onClick={() => void logout()} loading={busy}>
        Выйти
      </Button>
    </Space>
  );
}

export interface NavItem {
  key: string;
  path: string;
  label: string;
  icon: React.ReactNode;
  /** rbac.yaml permission of the page's main read; items the signed-in role lacks are hidden (the API would answer 403). */
  permission?: string;
}

export const NAV_ITEMS: NavItem[] = [
  { key: 'dashboard', path: '/dashboard', label: 'Дашборд', icon: <FundProjectionScreenOutlined /> },
  { key: 'objects', path: '/objects', label: 'Объекты', icon: <BankOutlined /> },
  { key: 'processes', path: '/processes', label: 'Проверки', icon: <AuditOutlined /> },
  { key: 'protocols', path: '/protocols', label: 'Протоколы', icon: <FileProtectOutlined /> },
  { key: 'verification', path: '/verification', label: 'Верификация', icon: <SafetyCertificateOutlined /> },
  { key: 'normative', path: '/admin/normative', label: 'Нормативная база', icon: <BookOutlined />, permission: 'matrix.read' },
  { key: 'ml-report', path: '/admin/ml-report', label: 'Отчёт по дообучению', icon: <LineChartOutlined />, permission: 'retraining.read' },
  { key: 'monitoring', path: '/admin/monitoring', label: 'Мониторинг', icon: <DashboardOutlined />, permission: 'monitoring.read' },
  { key: 'selftest', path: '/admin/selftest', label: 'Самопроверка', icon: <ExperimentOutlined />, permission: 'ops.run' },
];

const SIDER_KEY = 'inspector.sider.collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDER_KEY) === '1';
  } catch {
    return false;
  }
}

export function AppShell() {
  const location = useLocation();
  const { token } = theme.useToken();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const selected = NAV_ITEMS.filter((i) => location.pathname.startsWith(i.path)).map((i) => i.key);
  const session = useAuthSession();
  // Without a session (local optional-auth mode) every item stays visible; a signed-in role sees only what it may open.
  const visible = NAV_ITEMS.filter((i) => !i.permission || !session.data || hasPermission(session.data, i.permission));
  const items: MenuProps['items'] = visible.map((i) => ({
    key: i.key,
    icon: i.icon,
    label: <Link to={i.path}>{i.label}</Link>,
  }));

  const onCollapse = (value: boolean) => {
    setCollapsed(value);
    try {
      window.localStorage.setItem(SIDER_KEY, value ? '1' : '0');
    } catch {
      /* UI preference only */
    }
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        collapsible
        collapsed={collapsed}
        onCollapse={onCollapse}
        breakpoint="lg"
        width={232}
        theme="light"
        style={{ borderRight: `1px solid ${token.colorBorderSecondary}` }}
      >
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: collapsed ? '0 24px' : '0 20px',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <span
            aria-hidden
            style={{
              width: 28,
              height: 28,
              borderRadius: 6,
              background: token.colorPrimary,
              color: '#fff',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              flex: '0 0 auto',
            }}
          >
            И
          </span>
          {!collapsed && (
            <Typography.Text strong style={{ fontSize: 16, whiteSpace: 'nowrap' }}>
              Инспектор ИИ
            </Typography.Text>
          )}
        </div>
        <nav aria-label="Основное меню">
          <Menu mode="inline" selectedKeys={selected} items={items} style={{ borderInlineEnd: 0 }} />
        </nav>
      </Layout.Sider>
      <Layout>
        <Layout.Header
          style={{
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            padding: '0 24px',
            height: 56,
            lineHeight: '56px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Typography.Text type="secondary">
            Сверка проектной, рабочей и исполнительной документации по матрице 132 параметров
          </Typography.Text>
          <Space size={12}>
            <Tag color="default" style={{ marginInlineEnd: 0 }}>Локальный контур</Tag>
            <UserMenu />
          </Space>
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
