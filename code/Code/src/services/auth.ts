import api from './axios';
import type { LoginParams, LoginResponse, User } from '../types/auth';

/** 登录（首次登录自动注册） */
export async function login(params: LoginParams): Promise<LoginResponse> {
  const { data } = await api.post<LoginResponse>('/auth/login', {
    email: params.email,
    password: params.password,
  });
  return data;
}

/** 获取当前用户信息 */
export async function getProfile(): Promise<User> {
  const { data } = await api.get<User>('/user/profile');
  return data;
}

/** 更新用户信息 */
export async function updateProfile(profile: Record<string, unknown>): Promise<User> {
  const { data } = await api.put<User>('/user/profile', profile);
  return data;
}