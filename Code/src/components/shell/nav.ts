import type { LucideIcon } from 'lucide-react';
import {
  Search,
  Orbit,
  LayoutGrid,
  FileText,
  Calendar,
  Mail,
  File,
  Sparkles,
  User,
  Microscope,
} from 'lucide-react';

export interface NavItem {
  index: string;
  label: string;
  to: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { index: '01', label: '检索', to: '/search', icon: Search },
  { index: '02', label: '云图', to: '/cloud', icon: Orbit },
  { index: '03', label: '报告', to: '/reports', icon: FileText },
  { index: '04', label: '计划', to: '/plans', icon: Calendar },
  { index: '05', label: '邮件', to: '/email', icon: Mail },
  { index: '06', label: 'PDF', to: '/pdf', icon: File },
  { index: '07', label: '猜你喜欢', to: '/recommend', icon: Sparkles },
  { index: '08', label: '画像', to: '/profile', icon: User },
  { index: '09', label: '科研', to: '/research', icon: Microscope },
  { index: '10', label: '其他', to: '/other', icon: LayoutGrid },
];
