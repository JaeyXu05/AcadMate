import { NavLink } from 'react-router-dom';
import Logo from '../Logo';
import UserAvatarDropdown from '../UserAvatarDropdown';
import { NAV_ITEMS } from './nav';

interface SidebarProps {
  onNavigate?: () => void;
}

function Sidebar({ onNavigate }: SidebarProps) {
  return (
    <aside className="flex h-full min-h-0 flex-col rounded-2xl border border-white/60 bg-white/60 px-5 py-6 shadow-xl shadow-indigo-100 backdrop-blur-2xl">
      <div className="mb-8 px-1">
        <Logo />
        <p className="mt-2 text-[11px] font-medium tracking-[0.18em] text-slate-500">
          RESEARCH WORKBENCH
        </p>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto pr-1">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) =>
              [
                'flex items-baseline gap-2 rounded-full px-3 py-2',
                isActive
                  ? 'border border-indigo-100 bg-indigo-50 text-indigo-600'
                  : 'border border-transparent text-slate-600 hover:bg-white/50',
              ].join(' ')
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={[
                    'pointer-events-none select-none text-base font-light',
                    isActive ? 'text-indigo-600' : 'text-slate-400',
                  ].join(' ')}
                >
                  {item.index}
                </span>
                <span className="text-sm font-medium">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="mt-6 flex items-center gap-3 border-t border-white/60 pt-5">
        <UserAvatarDropdown />
        <div className="min-w-0">
          <div className="truncate text-xs font-medium text-slate-700">账户</div>
          <div className="truncate text-[11px] text-slate-500">设置 · 收藏 · 退出</div>
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;
