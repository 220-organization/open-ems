import { useEffect } from 'react';

export default function MarketplaceModal({ open, onClose, children, ariaLabel }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => {
      if (e.key === 'Escape') onClose?.();
    };
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="marketplace-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="marketplace-modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        onClick={e => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
