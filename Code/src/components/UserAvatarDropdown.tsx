import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Avatar, Dropdown, App } from 'antd';
import type { MenuProps } from 'antd';
import {
  UserOutlined,
  StarOutlined,
  SettingOutlined,
  LogoutOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '../stores/authStore';
import { deleteAccount } from '../services/user';

function UserAvatarDropdown() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const { modal } = App.useApp();
  // 受控展开状态：点击菜单项后主动收起，避免停留在打开状态
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
          // 即使后端调用失败，也允许本地登出，避免账号卡死
        }
        logout();
        navigate('/welcome', { replace: true });
      },
    });
  };

  const menuItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人信息',
      onClick: () => navigate('/profile'),
    },
    {
      key: 'favorites',
      icon: <StarOutlined />,
      label: '收藏夹',
      onClick: () => navigate('/favorites'),
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: '设置',
      onClick: () => navigate('/settings'),
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: handleLogout,
    },
    {
      key: 'deleteAccount',
      icon: <DeleteOutlined />,
      label: '注销账号',
      danger: true,
      onClick: handleDeleteAccount,
    },
  ];

  return (
    <Dropdown
      menu={{
        items: menuItems,
        // 受控模式下，点击任意菜单项后主动收起下拉
        onClick: () => setOpen(false),
      }}
      placement="bottomRight"
      trigger={['click']}
      open={open}
      onOpenChange={setOpen}
    >
      <Avatar
        size={36}
        style={{
          backgroundColor: '#667eea',
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