import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';

interface AuthGuardProps {
  children: React.ReactNode;
}

/** 需要登录的路由守卫：无 token → 跳转 /welcome */
function AuthGuard({ children }: AuthGuardProps) {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);

  if (!isLoggedIn) {
    return <Navigate to="/welcome" replace />;
  }

  return <>{children}</>;
}

export default AuthGuard;