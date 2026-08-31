import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Avatar, Dropdown, App } from 'antd';
import type { MenuProps } from 'antd';
import { User, Star, Settings, LogOut, Trash2 } from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import { deleteAccount } from '../services/user';

function UserAvatarDropdown() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const { modal } = App.useApp();
  const [open, setOpen] = useState(false);

  const email = user?.email || '';
  const firstLetter = email ? email.charAt(0).toUpperCase() : 'U';

  const handleLogout = () => {
    modal.confirm({
      title: '退出登录',
      content: '确定要退出当前账号吗？',
      okText: '退出',
      cancelText: '取消',
      centered: true,
      onOk: () => {
        logout();
        navigate('/welcome', { replace: true });
      },
    });
  };

  const handleDeleteAccount = () => {
    modal.confirm({
      title: '注销账号',
      content: '确定要注销当前账号吗？此操作不可撤销，所有个人数据（收藏、历史记录、设置等）将被永久删除。',
      okText: '确认注销',
      cancelText: '我再想想',
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          await deleteAccount();
        } catch {
          /* 即使后端调用失败，也允许本地登出 */
        }
        logout();
        navigate('/welcome', { replace: true });
      },
    });
  };

  const menuItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <User size={14} strokeWidth={1.5} className="text-slate-600" />,
      label: '个人信息',
      onClick: () => navigate('/profile'),
    },
    {
      key: 'favorites',
      icon: <Star size={14} strokeWidth={1.5} className="text-slate-600" />,
      label: '收藏夹',
      onClick: () => navigate('/favorites'),
    },
    {
      key: 'settings',
      icon: <Settings size={14} strokeWidth={1.5} className="text-slate-600" />,
      label: '设置',
      onClick: () => navigate('/settings'),
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogOut size={14} strokeWidth={1.5} className="text-slate-600" />,
      label: '退出登录',
      onClick: handleLogout,
    },
    {
      key: 'deleteAccount',
      icon: <Trash2 size={14} strokeWidth={1.5} className="text-slate-600" />,
      label: '注销账号',
      danger: true,
      onClick: handleDeleteAccount,
    },
  ];

  return (
    <Dropdown
      menu={{
        items: menuItems,
        onClick: () => setOpen(false),
      }}
      placement="topLeft"
      trigger={['click']}
      open={open}
      onOpenChange={setOpen}
    >
      <Avatar
        size={36}
        style={{
          backgroundColor: '#f1f5f9',
          color: '#64748b',
          cursor: 'pointer',
          flexShrink: 0,
        }}
      >
        {firstLetter}
      </Avatar>
    </Dropdown>
  );
}

export default UserAvatarDropdown;
