import api from './axios';
import type { CloudData } from '../types/cloud';

/**
 * 云图数据服务。
 *
 * 从后端 `GET /api/cloud/graph` 拉取当前 RAG 派生的 3D 云图数据（当前 972 位导师，
 * 数据源为 cloud3d/build_cloud.py 生成的银河盘布局，坐标/领域/亮度已预计算）。
 * 后端路由见 server/routes/cloud.ts。
 */

/**
 * 获取云图数据。
 */
export async function getCloudData(): Promise<CloudData> {
  const res = await api.get<CloudData>('/cloud/graph');
  return res.data;
}
