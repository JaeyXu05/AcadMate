import { useEffect } from 'react';

export function usePolling(callback: () => void | Promise<void>, intervalMs: number, enabled: boolean): void {
  useEffect(() => {
    if (!enabled) {
      return;
    }
    let active = true;
    const tick = () => {
      if (!active) {
        return;
      }
      void callback();
    };
    const interval = window.setInterval(tick, intervalMs);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [callback, enabled, intervalMs]);
}
