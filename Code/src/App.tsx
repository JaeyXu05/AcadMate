import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { ConfigProvider, theme, App as AntdApp } from 'antd';
import WelcomePage from './pages/WelcomePage';
import SearchPage from './pages/SearchPage';
import CloudPage from './pages/CloudPage';
import OtherPage from './pages/OtherPage';
import ProfilePage from './pages/ProfilePage';
import SettingsPage from './pages/SettingsPage';
import FavoritesPage from './pages/FavoritesPage';
import AdvisorDetailPage from './pages/AdvisorDetailPage';
import EmailPage from './pages/EmailPage';
import ComparePage from './pages/ComparePage';
import PdfPage from './pages/PdfPage';
import RecommendPage from './pages/RecommendPage';
import AppLayout from './components/AppLayout';
import GuestGuard from './components/GuestGuard';
import AuthGuard from './components/AuthGuard';
import { useAuthStore } from './stores/authStore';
import { SESSION_EXPIRED_EVENT, API_NOTICE_EVENT } from './services/axios';

function AppRoutes() {
  const { message: antdMessage } = AntdApp.useApp();
  const restoreSession = useAuthStore((s) => s.restoreSession);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();

  useEffect(() => {
    restoreSession();
  }, [restoreSession]);

  // 监听"会话过期"事件：应用内跳转欢迎页 + 提示，避免整页刷新丢失 SPA 状态。
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

  // 监听"网络层错误"事件：axios 拦截器检测到超时/断网/代理不可达时统一提示。
  useEffect(() => {
    const onNotice = (e: Event) => {
      const detail = (e as CustomEvent<{ text: string }>).detail;
      antdMessage.error(detail?.text ?? '网络连接异常');
    };
    window.addEventListener(API_NOTICE_EVENT, onNotice);
    return () => window.removeEventListener(API_NOTICE_EVENT, onNotice);
  }, [antdMessage]);

  return (
    <Routes>
      {/* 欢迎页：独立，无 AppLayout */}
      <Route
        path="/welcome"
        element={
          <GuestGuard>
            <WelcomePage />
          </GuestGuard>
        }
      />

      {/* 主界面：包裹在 AppLayout 中 */}
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
        <Route path="/favorites" element={<FavoritesPage />} />
        <Route path="/advisor/:id" element={<AdvisorDetailPage />} />
        <Route path="/email" element={<EmailPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/pdf" element={<PdfPage />} />
        <Route path="/recommend" element={<RecommendPage />} />
      </Route>

      {/* 默认重定向到欢迎页 */}
      <Route path="*" element={<Navigate to="/welcome" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#667eea',
          borderRadius: 6,
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