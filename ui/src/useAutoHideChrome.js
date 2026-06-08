import { useEffect, useRef, useState } from 'react';

const MOBILE_MQ = '(max-width: 720px)';

/**
 * Hide the site header as soon as the user scrolls down on mobile.
 * The inverter bar (pf-top-bar) stays visible. Header reveals only at scrollY = 0.
 */
export function useAutoHideChrome() {
  const [hidden, setHidden] = useState(false);
  const hiddenRef = useRef(false);
  const lastScrollYRef = useRef(0);
  const touchStartYRef = useRef(0);
  const mobileEnabledRef = useRef(false);

  useEffect(() => {
    const mq = window.matchMedia(MOBILE_MQ);

    const setChromeHidden = next => {
      if (hiddenRef.current === next) return;
      hiddenRef.current = next;
      setHidden(next);
    };

    const syncMobileEnabled = () => {
      const enabled = mq.matches;
      mobileEnabledRef.current = enabled;
      document.documentElement.classList.toggle('open-ems-chrome-autohide', enabled);
      if (!enabled) {
        hiddenRef.current = false;
        setHidden(false);
      }
      lastScrollYRef.current = window.scrollY;
    };

    syncMobileEnabled();
    mq.addEventListener('change', syncMobileEnabled);
    lastScrollYRef.current = window.scrollY;

    const applyScrollPosition = (delta, scrollY) => {
      if (scrollY <= 0) {
        setChromeHidden(false);
        return;
      }
      if (delta > 0) {
        setChromeHidden(true);
      }
    };

    const onTouchStart = e => {
      touchStartYRef.current = e.touches[0]?.clientY ?? 0;
    };

    const onTouchMove = e => {
      if (!mobileEnabledRef.current) return;
      const touchY = e.touches[0]?.clientY;
      if (touchY == null) return;
      const fingerDelta = touchStartYRef.current - touchY;
      if (fingerDelta > 0 && window.scrollY > 0) {
        setChromeHidden(true);
      }
    };

    const onScroll = () => {
      if (!mobileEnabledRef.current) return;
      const y = window.scrollY;
      const delta = y - lastScrollYRef.current;
      applyScrollPosition(delta, y);
      lastScrollYRef.current = y;
    };

    window.addEventListener('touchstart', onTouchStart, { passive: true });
    window.addEventListener('touchmove', onTouchMove, { passive: true });
    window.addEventListener('scroll', onScroll, { passive: true });

    return () => {
      mq.removeEventListener('change', syncMobileEnabled);
      window.removeEventListener('touchstart', onTouchStart);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('scroll', onScroll);
      document.documentElement.classList.remove('open-ems-chrome-autohide');
    };
  }, []);

  return hidden;
}
