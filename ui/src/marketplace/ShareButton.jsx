import { useCallback, useState } from 'react';

export function buildMarketplaceShareUrl() {
  if (typeof window === 'undefined') return '/marketplace';
  return `${window.location.origin}/marketplace`;
}

export default function ShareButton({ t }) {
  const [copied, setCopied] = useState(false);

  const copyLink = useCallback(async () => {
    const url = buildMarketplaceShareUrl();
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, []);

  return (
    <div className="marketplace-share-row">
      <button type="button" className="marketplace-share-btn" onClick={() => void copyLink()}>
        {copied ? t('marketplaceShareCopied') : t('marketplaceShareBtn')}
      </button>
    </div>
  );
}
