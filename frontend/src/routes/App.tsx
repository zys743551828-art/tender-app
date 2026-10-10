import { lazy, Suspense, type ReactNode } from 'react';
import { Link, Navigate, Route, Routes } from 'react-router-dom';
import { EmptyState, Loading } from '../components/ui';
import { Button } from '../components/ui/button';
import { RequireAuth } from '../features/auth/auth';
import { LoginPage } from '../features/auth/LoginPage';
import { EvidencePage, FileViewerPage } from '../features/evidence/EvidencePage';
import { SearchPage } from '../features/evidence/SearchPage';
import { FindingsPage } from '../features/findings/FindingsPage';
import { MaterialsPage } from '../features/materials/MaterialsPage';
import { ProjectsPage } from '../features/projects/ProjectsPage';
import { SettingsPage } from '../features/projects/SettingsPage';
import { SubmitPage } from '../features/submit/SubmitPage';
import { BasisPage } from '../features/basis/BasisPage';
import { ReportPage } from '../features/report/ReportPage';
import { AppShell } from './AppShell';
import { ProjectLayout } from './ProjectLayout';

// 图表库只在报价与度量两页用到，按需加载，首屏不带。
const PricePage = lazy(() =>
  import('../features/price/PricePage').then((m) => ({ default: m.PricePage })),
);
const MetricsPage = lazy(() =>
  import('../features/metrics/MetricsPage').then((m) => ({ default: m.MetricsPage })),
);

function Deferred({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Loading />}>{children}</Suspense>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route
          path="/metrics"
          element={
            <Deferred>
              <MetricsPage />
            </Deferred>
          }
        />
        <Route path="/projects/:projectId" element={<ProjectLayout />}>
          <Route index element={<ReportPage />} />
          <Route path="findings" element={<FindingsPage />} />
          <Route path="basis" element={<BasisPage />} />
          <Route
            path="price"
            element={
              <Deferred>
                <PricePage />
              </Deferred>
            }
          />
          <Route path="submit" element={<SubmitPage />} />
          <Route path="materials" element={<MaterialsPage />} />
          <Route path="files/:versionId" element={<FileViewerPage />} />
          <Route path="evidence/:evidenceId" element={<EvidencePage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route
          path="*"
          element={
            <EmptyState
              title="页面不存在"
              action={
                <Button asChild>
                  <Link to="/projects">回到全部项目</Link>
                </Button>
              }
            >
              地址可能有误，或该页面已被移动。
            </EmptyState>
          }
        />
      </Route>
    </Routes>
  );
}
