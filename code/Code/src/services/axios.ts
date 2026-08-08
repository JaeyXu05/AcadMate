import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

/** 获取 token（按记住我逻辑从对应 storage 读取） */
function getToken(): string | null {
  return (
    localStorage.getItem('token') ||
    sessionStorage.getItem('token') ||
    null
  );
}

/** 清除所有 storage 中的 token */
export function clearToken(): void {
  localStorage.removeItem('token');
  sessionStorage.removeItem('token');
}

/**
 * 登录态失效时发出的事件名。
 * 顶层 App（main.tsx / App.tsx）监听它做"应用内跳转欢迎页 + 提示"，避免整页刷新丢失 SPA 状态。
 */
export const SESSION_EXPIRED_EVENT = 'auth:session-expired';

export function emitSessionExpired(): void {
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
}

// 请求拦截器：自动注入 token
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截器：401 清除 token 并发出"会话过期"事件（由顶层 App 做应用内跳转+提示，保留 SPA 状态）
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      clearToken();
      emitSessionExpired();
    } else if (!error.response) {
      // 网络层错误（超时/断网/代理不可达）：多数页面未单独处理，这里统一上报，
      // 避免静默失败。HTTP 层错误（4xx/5xx 带响应）由各页面自行处理，不重复提示。
      emitApiNotice('网络连接异常，请检查后端服务是否已启动');
    }
    return Promise.reject(error);
  },
);

/** 全局网络错误提示事件：axios 响应拦截器检测到网络层失败时广播，由 App 层用 antd message 弹出 */
export const API_NOTICE_EVENT = 'api:notice';

function emitApiNotice(text: string): void {
  window.dispatchEvent(
    new CustomEvent(API_NOTICE_EVENT, { detail: { text } }),
  );
}

export default api;