import { useNavigate } from 'react-router-dom';
import { CloseOutlined } from '@ant-design/icons';

/**
 * 浮动关闭按钮：固定在页面右上角，点击返回上一页（"关闭"当前页面）。
 * 用于个人信息 / 收藏夹 / 设置等从头像下拉菜单进入的次级页面，
 * 让用户随时能离开而无需点顶部导航。
 */
function PageCloseButton() {
  const navigate = useNavigate();

  const handleClose = () => {
    // 优先返回上一页；若无浏览历史则回到检索页
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
      style={{
        position: 'fixed',
        top: 76,
        right: 24,
        zIndex: 50,
        width: 36,
        height: 36,
        borderRadius: 8,
        border: '1px solid rgba(255, 255, 255, 0.12)',
        background: 'rgba(255, 255, 255, 0.06)',
        color: 'rgba(255, 255, 255, 0.75)',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 16,
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        transition: 'background 0.2s, color 0.2s, border-color 0.2s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.12)';
        e.currentTarget.style.color = '#fff';
        e.currentTarget.style.borderColor = 'rgba(102, 126, 234, 0.5)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)';
        e.currentTarget.style.color = 'rgba(255, 255, 255, 0.75)';
        e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.12)';
      }}
    >
      <CloseOutlined />
    </button>
  );
}

export default PageCloseButton;
