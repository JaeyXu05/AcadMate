import { useNavigate, useLocation } from 'react-router-dom';
import { X } from 'lucide-react';

function PageCloseButton() {
  const navigate = useNavigate();
  const location = useLocation();
  const onCloud = location.pathname.startsWith('/cloud');

  const handleClose = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/search', { replace: true });
    }
  };

  return (
    <button
      onClick={handleClose}
      aria-label="关闭"
      title="返回"
      className={[
        'absolute right-2 top-2 z-20 flex h-8 w-8 items-center justify-center',
        onCloud ? 'text-white/55 hover:text-white' : 'text-slate-600 hover:text-slate-800',
      ].join(' ')}
    >
      <X size={16} strokeWidth={1.5} className={onCloud ? 'text-white/55' : 'text-slate-600'} />
    </button>
  );
}

export default PageCloseButton;
