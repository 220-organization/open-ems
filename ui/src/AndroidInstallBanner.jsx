import { useCallback, useEffect, useRef, useState } from 'react';
import './android-install-banner.css';

const SHOW_MS = 3000;
const PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=com.km220.openems';
const APK_PATH = '/download/open-ems.apk';

function isAndroidMobileBrowser() {
  if (typeof navigator === 'undefined') return false;
  try {
    if (window.Capacitor?.isNativePlatform?.()) return false;
  } catch {
    /* ignore */
  }
  const ua = navigator.userAgent || '';
  return /Android/i.test(ua) && !/Windows/i.test(ua);
}

export default function AndroidInstallBanner({ t }) {
  const [visible, setVisible] = useState(() => isAndroidMobileBrowser());
  const [leaving, setLeaving] = useState(false);
  const hideTimerRef = useRef(null);
  const removeTimerRef = useRef(null);

  const dismiss = useCallback(() => {
    if (hideTimerRef.current != null) window.clearTimeout(hideTimerRef.current);
    if (removeTimerRef.current != null) window.clearTimeout(removeTimerRef.current);
    setLeaving(true);
    removeTimerRef.current = window.setTimeout(() => setVisible(false), 320);
  }, []);

  useEffect(() => {
    if (!visible) return undefined;
    hideTimerRef.current = window.setTimeout(() => dismiss(), SHOW_MS);
    return () => {
      if (hideTimerRef.current != null) window.clearTimeout(hideTimerRef.current);
      if (removeTimerRef.current != null) window.clearTimeout(removeTimerRef.current);
    };
  }, [visible, dismiss]);

  const onInstallClick = useCallback(() => {
    try {
      window.open(PLAY_STORE_URL, '_blank', 'noopener,noreferrer');
    } catch {
      const base = (process.env.PUBLIC_URL || '').replace(/\/$/, '');
      window.location.href = `${base}${APK_PATH}`;
    }
    dismiss();
  }, [dismiss]);

  if (!visible) return null;

  return (
    <div
      className={`pf-android-install-banner${leaving ? ' pf-android-install-banner--hide' : ''}`}
      role="dialog"
      aria-modal="false"
      aria-label={t('androidInstallBannerAria')}
    >
      <div className="pf-android-install-banner__card">
        <button
          type="button"
          className="pf-android-install-banner__close"
          onClick={dismiss}
          aria-label={t('androidInstallBannerClose')}
        >
          ×
        </button>
        <button type="button" className="pf-android-install-banner__btn" onClick={onInstallClick}>
          {t('androidInstallBannerLabel')}
        </button>
      </div>
    </div>
  );
}
