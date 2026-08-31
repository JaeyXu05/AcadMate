import { X } from 'lucide-react';
import Sidebar from './Sidebar';

interface MobileDrawerProps {
  open: boolean;
  onClose: () => void;
}

function MobileDrawer({ open, onClose }: MobileDrawerProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <button
        type="button"
        className="absolute inset-0 bg-stone-900/20"
        aria-label="关闭导航"
        onClick={onClose}
      />
      <div className="absolute bottom-0 left-0 top-0 w-[min(280px,86vw)] p-4">
        <div className="relative h-full">
          <button
            type="button"
            className="absolute right-3 top-3 z-10 rounded-lg p-1 text-slate-400 hover:bg-slate-50 hover:text-slate-700"
            onClick={onClose}
            aria-label="关闭"
          >
            <X size={18} strokeWidth={1.5} className="text-slate-600" />
          </button>
          <Sidebar onNavigate={onClose} />
        </div>
      </div>
    </div>
  );
}

export default MobileDrawer;
