/** Providers (antd ru_RU, TanStack Query) and routes. `AppRoutes` is router-agnostic for tests. */
import { App as AntApp, ConfigProvider } from 'antd';
import ruRU from 'antd/locale/ru_RU';
import dayjs from 'dayjs';
import 'dayjs/locale/ru';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import { ApiError } from './api/client';
import { lazy, Suspense } from 'react';
import { Flex, Spin } from 'antd';
import { AppShell } from './layout/AppShell';
import { NotFoundPage } from './pages/NotFoundPage';
import { ObjectPage } from './pages/ObjectPage';
import { ObjectsPage } from './pages/ObjectsPage';

// Route-level code splitting: the evidence viewer (OpenSeadragon) and the protocol renderer load on demand.
const DashboardPage = lazy(() => import('./features/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const ProtocolPage = lazy(() => import('./features/protocol/ProtocolPage').then((m) => ({ default: m.ProtocolPage })));
const EvidencePage = lazy(() => import('./features/evidence/EvidencePage').then((m) => ({ default: m.EvidencePage })));
const MonitoringPage = lazy(() => import('./features/monitoring/MonitoringPage').then((m) => ({ default: m.MonitoringPage })));
const SelftestPage = lazy(() => import('./features/selftest/SelftestPage').then((m) => ({ default: m.SelftestPage })));
const ProcessesPage = lazy(() => import('./features/processes/ProcessesPage').then((m) => ({ default: m.ProcessesPage })));
const ProcessPage = lazy(() => import('./features/processes/ProcessPage').then((m) => ({ default: m.ProcessPage })));
const ProtocolsPage = lazy(() => import('./pages/ProtocolsPage').then((m) => ({ default: m.ProtocolsPage })));
const NormativePage = lazy(() => import('./features/normative/NormativePage').then((m) => ({ default: m.NormativePage })));
const MlReportPage = lazy(() => import('./features/ml/MlReportPage').then((m) => ({ default: m.MlReportPage })));
const VerificationPage = lazy(() =>
  import('./features/verification').then((m) => ({ default: m.VerificationPage })),
);

function Lazy({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <Flex align="center" justify="center" style={{ minHeight: 240 }}>
          <Spin />
        </Flex>
      }
    >
      {children}
    </Suspense>
  );
}
import { SectionPlaceholder } from './pages/SectionPlaceholder';
import { appTheme } from './theme';

dayjs.locale('ru');

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        refetchOnWindowFocus: false,
        refetchIntervalInBackground: false,
        // GET retries ×2 for network/5xx only (08 §3.7); 4xx are final.
        retry: (count, error) =>
          count < 2 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ client, children }: { client: QueryClient; children: React.ReactNode }) {
  return (
    <ConfigProvider locale={ruRU} theme={appTheme}>
      <AntApp>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Lazy><DashboardPage /></Lazy>} />
        <Route path="objects" element={<ObjectsPage />} />
        <Route path="objects/:objectId" element={<ObjectPage />} />
        <Route path="objects/:objectId/protocols/:runId" element={<Lazy><ProtocolPage /></Lazy>} />
        <Route path="objects/:objectId/protocols/:runId/cards/:cardNo" element={<Lazy><EvidencePage /></Lazy>} />
        <Route path="protocols" element={<Lazy><ProtocolsPage /></Lazy>} />
        <Route path="processes" element={<Lazy><ProcessesPage /></Lazy>} />
        <Route path="processes/:processId" element={<Lazy><ProcessPage /></Lazy>} />
        <Route path="verification" element={<Lazy><VerificationPage /></Lazy>} />
        <Route path="verification/:processId" element={<Lazy><VerificationPage /></Lazy>} />
        <Route path="verification/:processId/:findingId" element={<Lazy><VerificationPage /></Lazy>} />
        <Route path="objects/:objectId/verify" element={<Lazy><VerificationPage /></Lazy>} />
        <Route path="admin/normative" element={<Lazy><NormativePage /></Lazy>} />
        <Route path="admin/ml-report" element={<Lazy><MlReportPage /></Lazy>} />
        <Route path="admin/monitoring" element={<Lazy><MonitoringPage /></Lazy>} />
        <Route path="admin/selftest" element={<Lazy><SelftestPage /></Lazy>} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

const queryClient = createQueryClient();

export function App() {
  return (
    <Providers client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </Providers>
  );
}
