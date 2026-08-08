import { create } from 'zustand';
import type { User } from '../types/auth';
import * as authApi from '../services/auth';
import { clearToken } from '../services/axios';

interface AuthState {
  user: User | null;
  token: string | null;
  isLoggedIn: boolean;
  isLoggingIn: boolean;

  /** 登录（首次登录自动注册），成功后根据 rememberMe 存 token */
  login: (email: string, password: string, rememberMe: boolean) => Promise<void>;
  /** 登出 */
  logout: () => void;
  /** 从 storage 恢复登录态 */
  restoreSession: () => void;
  /** 更新个人信息 */
  updateProfile: (profile: Partial<User>) => Promise<void>;
}

function saveToken(token: string, rememberMe: boolean): void {
  clearToken();
  if (rememberMe) {
    localStorage.setItem('token', token);
    sessionStorage.removeItem('token');
  } else {
    sessionStorage.setItem('token', token);
    localStorage.removeItem('token');
  }
}

function loadToken(): string | null {
  return localStorage.getItem('token') || sessionStorage.getItem('token') || null;
}

/** 判断错误是否为 401（token 失效） */
function isUnauthorized(err: unknown): boolean {
  if (err && typeof err === 'object' && 'response' in err) {
    return (err as { response?: { status?: number } }).response?.status === 401;
  }
  return false;
}

function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const axiosErr = err as { response?: { data?: { message?: string } } };
    return axiosErr.response?.data?.message || fallback;
  }
  return fallback;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: loadToken(),
  isLoggedIn: false,
  isLoggingIn: false,

  login: async (email, password, rememberMe) => {
    set({ isLoggingIn: true });
    try {
      const res = await authApi.login({ email, password, rememberMe });
      saveToken(res.token, rememberMe);
      set({ user: res.user, token: res.token, isLoggedIn: true, isLoggingIn: false });
    } catch (err: unknown) {
      set({ isLoggingIn: false });
      throw new Error(extractErrorMessage(err, '登录失败，请检查邮箱和密码'));
    }
  },

  logout: () => {
    clearToken();
    set({ user: null, token: null, isLoggedIn: false });
  },

  updateProfile: async (profile) => {
    try {
      const updated = await authApi.updateProfile(profile);
      const currentUser = get().user;
      if (currentUser) {
        set({ user: { ...currentUser, ...updated } });
      }
    } catch {
      throw new Error('更新个人信息失败');
    }
  },

  restoreSession: () => {
    const token = loadToken();
    if (token) {
      set({ token, isLoggedIn: true });
      authApi.getProfile()
        .then((user) => set({ user }))
        .catch((err: unknown) => {
          // 仅当确认为 401（token 失效）才登出；瞬时网络错误不应误登出、清空有效会话。
          if (isUnauthorized(err)) {
            get().logout();
          }
        });
    }
  },
}));