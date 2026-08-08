import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';

interface GuestGuardProps {
  children: React.ReactNode;
}

/** 访客路由守卫：已登录 → 跳转 /search */
function GuestGuard({ children }: GuestGuardProps) {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);

  if (isLoggedIn) {
    return <Navigate to="/search" replace />;
  }

  return <>{children}</>;
}

export default GuestGuard;