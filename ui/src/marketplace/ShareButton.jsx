import { useCallback, useState } from 'react';

/** Deep-link to /marketplace; optional locationId opens that location detail popup. */
export function buildMarketplaceShareUrl(locationId) {
  if (typeof window === 'undefined') {
    const path = locationId
      ? `/marketplace?marketplaceLocation=${encodeURIComponent(String(locationId))}`
      : '/marketplace';
    return path;
  }
  const url = new URL(`${window.location.origin}/marketplace`);
  if (locationId) {
    url.searchParams.set('marketplaceLocation', String(locationId));
  }
  return url.toString();
}

export default function ShareButton({ t, locationId = null, className = '', compact = false }) {
  const [copied, setCopied] = useState(false);

  const copyLink = useCallback(async () => {
    const url = buildMarketplaceShareUrl(locationId);
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [locationId]);

  const label = copied ? t('marketplaceShareCopied') : t('marketplaceShareBtn');

  if (compact) {
    return (
      <button
        type="button"
        className={className || 'marketplace-share-btn marketplace-share-btn--compact'}
        onClick={() => void copyLink()}
        aria-label={label}
        title={label}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
          <path
            fill="currentColor"
            d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"
          />
        </svg>
      </button>
    );
  }

  return (
    <div className="marketplace-share-row">
      <button type="button" className={className || 'marketplace-share-btn'} onClick={() => void copyLink()}>
        {label}
      </button>
    </div>
  );
}
