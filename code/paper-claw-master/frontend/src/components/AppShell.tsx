import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

export type AppPage = 'chat' | 'paper' | 'report' | 'memory' | 'task' | 'setting';
export type NavMode = 'icon' | 'title';

interface AppShellProps {
  activePage: AppPage;
  navMode: NavMode;
  activeRunLabel?: string;
  activePaperLabel?: string;
  onSelectPage: (page: AppPage) => void;
  onToggleNavMode: () => void;
  children: ReactNode;
}

const navItems: Array<{ id: AppPage; label: string; icon: string }> = [
  { id: 'chat', label: 'Chat', icon: 'C' },
  { id: 'paper', label: 'Paper', icon: 'P' },
  { id: 'report', label: 'Report', icon: 'R' },
  { id: 'memory', label: 'Memory', icon: 'M' },
  { id: 'task', label: 'Task', icon: 'T' },
  { id: 'setting', label: 'Setting', icon: 'S' },
];

function activePageLabel(activePage: AppPage): string {
  return navItems.find((item) => item.id === activePage)?.label ?? 'Workspace';
}

export function AppShell({
  activePage,
  navMode,
  activeRunLabel = 'no active run',
  activePaperLabel = 'no paper pinned',
  onSelectPage,
  onToggleNavMode,
  children,
}: AppShellProps) {
  const expanded = navMode === 'title';
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [isMobileNavViewport, setIsMobileNavViewport] = useState(() => {
    if (typeof window === 'undefined') {
      return false;
    }

    return window.matchMedia('(max-width: 760px)').matches;
  });
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const isMobileNavModal = mobileNavOpen && isMobileNavViewport;
  const wasMobileNavModalRef = useRef(isMobileNavModal);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 760px)');

    const updateMobileNavViewport = (event: MediaQueryListEvent | MediaQueryList) => {
      setIsMobileNavViewport(event.matches);
      if (!event.matches) {
        setMobileNavOpen(false);
      }
    };

    updateMobileNavViewport(mediaQuery);
    mediaQuery.addEventListener('change', updateMobileNavViewport);

    return () => {
      mediaQuery.removeEventListener('change', updateMobileNavViewport);
    };
  }, []);

  useEffect(() => {
    if (isMobileNavModal) {
      closeButtonRef.current?.focus();
    }

    if (wasMobileNavModalRef.current && !isMobileNavModal && isMobileNavViewport) {
      menuButtonRef.current?.focus();
    }

    wasMobileNavModalRef.current = isMobileNavModal;
  }, [isMobileNavModal, isMobileNavViewport]);

  const closeMobileNavOnEscape = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      setMobileNavOpen(false);
    }
  };

  const selectPage = (page: AppPage) => {
    onSelectPage(page);
    setMobileNavOpen(false);
  };

  return (
    <div className={`app-shell app-shell--${navMode}`}>
      <header className="mobile-top-bar" inert={isMobileNavModal ? true : undefined}>
        <button ref={menuButtonRef} className="mobile-menu-button" type="button" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation">
          Menu
        </button>
        <div>
          <p className="eyebrow">Paper Claw</p>
          <strong>{activePageLabel(activePage)}</strong>
        </div>
      </header>
      {isMobileNavModal && (
        <button
          className="mobile-nav-backdrop"
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileNavOpen(false)}
          onKeyDown={closeMobileNavOnEscape}
        />
      )}
      <aside
        className={`activity-bar activity-bar--${navMode} ${isMobileNavModal ? 'is-mobile-open' : ''}`}
        aria-label="Primary navigation"
        onKeyDown={closeMobileNavOnEscape}
      >
        <div className="activity-bar__brand">
          <span className="activity-bar__mark">PC</span>
          <div className="activity-bar__brand-text">
            <p className="eyebrow">Paper Claw</p>
            <strong>Workspace</strong>
          </div>
        </div>
        <button
          ref={closeButtonRef}
          className="activity-bar__mobile-close"
          type="button"
          onClick={() => setMobileNavOpen(false)}
          aria-label="Close navigation"
        >
          Close
        </button>
        <button
          className="activity-bar__toggle"
          type="button"
          onClick={onToggleNavMode}
          aria-label={expanded ? 'Collapse navigation labels' : 'Expand navigation labels'}
        >
          {expanded ? '«' : '»'}
        </button>
        <nav className="activity-nav">
          {navItems.map((item) => (
            <button
              className={`activity-item ${activePage === item.id ? 'is-active' : ''}`}
              type="button"
              key={item.id}
              onClick={() => selectPage(item.id)}
              aria-current={activePage === item.id ? 'page' : undefined}
              aria-label={expanded ? undefined : item.label}
              title={item.label}
            >
              <span className="activity-item__icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="activity-item__label">{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="activity-bar__status" aria-label="Workspace status">
          <span title={activeRunLabel}>{activeRunLabel}</span>
          <span title={activePaperLabel}>{activePaperLabel}</span>
        </div>
      </aside>
      <main className="page-frame" inert={isMobileNavModal ? true : undefined}>
        {children}
      </main>
    </div>
  );
}
