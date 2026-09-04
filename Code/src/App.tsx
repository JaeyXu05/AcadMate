import { lazy, Suspense, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { ConfigProvider, theme, App as AntdApp } from 'antd';
import AppLayout from './components/AppLayout';
import GuestGuard from './components/GuestGuard';
import AuthGuard from './components/AuthGuard';
import { useAuthStore } from './stores/authStore';
import { SESSION_EXPIRED_EVENT, API_NOTICE_EVENT } from './services/axios';

const WelcomePage = lazy(() => import('./pages/WelcomePage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const CloudPage = lazy(() => import('./pages/CloudPage'));
const OtherPage = lazy(() => import('./pages/OtherPage'));
const ProfilePage = lazy(() => import('./pages/ProfilePage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ApiSettingsPage = lazy(() => import('./pages/ApiSettingsPage'));
const FavoritesPage = lazy(() => import('./pages/FavoritesPage'));
const AdvisorDetailPage = lazy(() => import('./pages/AdvisorDetailPage'));
const EmailPage = lazy(() => import('./pages/EmailPage'));
const ComparePage = lazy(() => import('./pages/ComparePage'));
const PdfPage = lazy(() => import('./pages/PdfPage'));
const RecommendPage = lazy(() => import('./pages/RecommendPage'));
const ReportsPage = lazy(() => import('./pages/ReportsPage'));
const PlansPage = lazy(() => import('./pages/PlansPage'));
const ResearchPage = lazy(() => import('./pages/ResearchPage'));
const SkillsPage = lazy(() => import('./pages/SkillsPage'));
const IntegrationsPage = lazy(() => import('./pages/IntegrationsPage'));

function AppRoutes() {
  const { message: antdMessage } = AntdApp.useApp();
  const restoreSession = useAuthStore((s) => s.restoreSession);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();

  useEffect(() => {
    restoreSession();
  }, [restoreSession]);

  useEffect(() => {
    const onExpired = () => {
      logout();
      antdMessage.warning('登录已过期，请重新登录');
      if (!window.location.pathname.startsWith('/welcome')) {
        navigate('/welcome', { replace: true });
      }
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, [logout, navigate, antdMessage]);

  useEffect(() => {
    const onNotice = (e: Event) => {
      const detail = (e as CustomEvent<{ text: string }>).detail;
      antdMessage.error(detail?.text ?? '网络连接异常');
    };
    window.addEventListener(API_NOTICE_EVENT, onNotice);
    return () => window.removeEventListener(API_NOTICE_EVENT, onNotice);
  }, [antdMessage]);

  return (
    <Suspense
      fallback={
        <div className="grid min-h-screen place-items-center bg-gradient-to-br from-slate-100 via-white to-stone-50 text-stone-400">
          加载中…
        </div>
      }
    >
      <Routes>
        <Route
          path="/welcome"
          element={
            <GuestGuard>
              <WelcomePage />
            </GuestGuard>
          }
        />

        <Route
          element={
            <AuthGuard>
              <AppLayout />
            </AuthGuard>
          }
        >
          <Route index element={<Navigate to="/search" replace />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/cloud" element={<CloudPage />} />
          <Route path="/other" element={<OtherPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/api-settings" element={<ApiSettingsPage />} />
          <Route path="/favorites" element={<FavoritesPage />} />
          <Route path="/advisor/:id" element={<AdvisorDetailPage />} />
          <Route path="/email" element={<EmailPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/pdf" element={<PdfPage />} />
          <Route path="/recommend" element={<RecommendPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/plans" element={<PlansPage />} />
          <Route path="/research" element={<ResearchPage />} />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/integrations" element={<IntegrationsPage />} />
        </Route>

        <Route path="*" element={<Navigate to="/welcome" replace />} />
      </Routes>
    </Suspense>
  );
}

function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1c1917',
          borderRadius: 6,
          fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
          colorText: '#1c1917',
          colorBgContainer: '#ffffff',
        },
      }}
    >
      <AntdApp>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}

export default App;
