import { useCallback, useEffect, useRef, useState } from 'react';
import { HUB_PARTNER_FLIP_MS, HUB_PARTNER_PROMOTIONS } from './partnerPromotions';

const DOUBLE_CLICK_MS = 280;

export default function PartnerHubLogo({ t, flowEndsHere = false }) {
  const [index, setIndex] = useState(0);
  const [flipping, setFlipping] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return true;
    return !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });
  const [logoTick, setLogoTick] = useState(0);
  const clickTimerRef = useRef(null);

  const partner = HUB_PARTNER_PROMOTIONS[index] ?? HUB_PARTNER_PROMOTIONS[0];
  const hubLabel = partner.hubLabelKey ? t(partner.hubLabelKey) : partner.name;
  const logoWide = Boolean(partner.logoWide);

  useEffect(() => {
    if (!flipping) return undefined;
    const id = window.setInterval(() => {
      setIndex(i => (i + 1) % HUB_PARTNER_PROMOTIONS.length);
      setLogoTick(tick => tick + 1);
    }, HUB_PARTNER_FLIP_MS);
    return () => window.clearInterval(id);
  }, [flipping]);

  useEffect(
    () => () => {
      if (clickTimerRef.current) window.clearTimeout(clickTimerRef.current);
    },
    [],
  );

  const openPartnerSite = useCallback(() => {
    window.open(partner.url, '_blank', 'noopener,noreferrer');
  }, [partner.url]);

  const handleClick = useCallback(() => {
    if (clickTimerRef.current) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
      openPartnerSite();
      return;
    }
    clickTimerRef.current = window.setTimeout(() => {
      clickTimerRef.current = null;
      setFlipping(f => !f);
    }, DOUBLE_CLICK_MS);
  }, [openPartnerSite]);

  const handleKeyDown = useCallback(
    e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleClick();
      }
    },
    [handleClick],
  );

  const brandClass = flowEndsHere
    ? 'pf-hub-brand pf-hub-brand--flow-ends-here pf-hub-brand--partner-carousel'
    : 'pf-hub-brand pf-hub-brand--partner-carousel';
  const pausedClass = flipping ? '' : ' pf-hub-brand--partner-paused';

  return (
    <>
      <button
        type="button"
        className={`${brandClass}${pausedClass}`}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        aria-label={
          flipping
            ? t('hubPartnerCarouselAria', { name: partner.name })
            : t('hubPartnerPausedAria', { name: partner.name })
        }
        aria-live="polite"
      >
        <span
          className={`pf-hub-logo-stage${logoWide ? ' pf-hub-logo-stage--wide' : ''}`}
          aria-hidden="true"
        >
          <img
            key={`${partner.id}-${logoTick}`}
            className={`pf-hub-logo${logoWide ? ' pf-hub-logo--wide' : ''}${flipping ? ' pf-hub-logo--flip-in' : ''}`}
            src={partner.logoSrc}
            alt=""
            width={logoWide ? 100 : 44}
            height={logoWide ? 50 : 44}
            loading="lazy"
            decoding="async"
            draggable={false}
          />
        </span>
      </button>
      <span className="pf-hub-label">{hubLabel}</span>
    </>
  );
}
