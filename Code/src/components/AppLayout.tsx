import { Outlet, NavLink } from 'react-router-dom';
import Logo from './Logo';
import UserAvatarDropdown from './UserAvatarDropdown';
import { useSettingsStore } from '../stores/settingsStore';
import styles from './AppLayout.module.css';

function AppLayout() {
  const bgColor = useSettingsStore((s) => s.bgColor);

  return (
    <div className={styles.layout} style={{ backgroundColor: bgColor }}>
      {/* 顶部导航栏 */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Logo />
        </div>

        <nav className={styles.tabs}>
          <NavLink
            to="/search"
            className={({ isActive }) =>
              `${styles.tab} ${isActive ? styles.tabActive : ''}`
            }
          >
            检索
          </NavLink>
          <NavLink
            to="/cloud"
            className={({ isActive }) =>
              `${styles.tab} ${isActive ? styles.tabActive : ''}`
            }
          >
            云图
          </NavLink>
          <NavLink
            to="/other"
            className={({ isActive }) =>
              `${styles.tab} ${isActive ? styles.tabActive : ''}`
            }
          >
            其他
          </NavLink>
        </nav>

        <div className={styles.headerRight}>
          <UserAvatarDropdown />
        </div>
      </header>

      {/* 内容区 */}
      <main className={styles.content}>
        <Outlet />
      </main>

      {/* 底部 Footer */}
      <footer className={styles.footer}>
        © 2026 科研导师推荐平台 | USTC
      </footer>
    </div>
  );
}

export default AppLayout;