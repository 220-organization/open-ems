import { useCallback, useEffect, useState } from 'react';
import './landing.css';
import './marketplace.css';
import { useOpenEmsSeo } from './useOpenEmsSeo';
import { useTheme } from './useTheme';
import MarketplaceMap from './marketplace/MarketplaceMap';
import ShareButton from './marketplace/ShareButton';
import LeadFormModal from './marketplace/LeadFormModal';
import { isMarketplaceApiConfigured } from './marketplace/marketplaceApi';

function readPaymentReturnFromUrl() {
  try {
    const u = new URLSearchParams(window.location.search);
    return {
      paymentReturnId: u.get('marketplacePayment') || '',
      paymentReturnLocationId: u.get('marketplaceLocation') || '',
      heatmapPaymentReturnId: u.get('marketplaceHeatmapPayment') || '',
    };
  } catch {
    return { paymentReturnId: '', paymentReturnLocationId: '', heatmapPaymentReturnId: '' };
  }
}

function clearLocationPaymentReturnInUrl() {
  try {
    const u = new URL(window.location.href);
    u.searchParams.delete('marketplacePayment');
    u.searchParams.delete('marketplaceLocation');
    window.history.replaceState({}, '', u);
  } catch {
    /* ignore */
  }
}

function clearHeatmapPaymentReturnInUrl() {
  try {
    const u = new URL(window.location.href);
    u.searchParams.delete('marketplaceHeatmapPayment');
    window.history.replaceState({}, '', u);
  } catch {
    /* ignore */
  }
}

export default function LocationMarketplacePage({ t, locale }) {
  useTheme();
  useOpenEmsSeo(t('marketplacePageTitle'), locale, t, {
    variant: 'landing',
    canonicalPath: '/marketplace',
  });

  const [publishSuccess, setPublishSuccess] = useState(false);
  const [leadModal, setLeadModal] = useState({
    open: false,
    message: '',
    titleKey: 'marketplaceMessengerChoiceTitle',
    formType: null,
  });
  const [paymentReturn, setPaymentReturn] = useState(readPaymentReturnFromUrl);

  const openLeadModal = (message, titleKey, formType) => {
    setLeadModal({ open: true, message, titleKey, formType });
  };

  const closeLeadModal = () => {
    setLeadModal({ open: false, message: '', titleKey: 'marketplaceMessengerChoiceTitle', formType: null });
  };

  const handlePaymentReturnHandled = useCallback(() => {
    clearLocationPaymentReturnInUrl();
    setPaymentReturn(prev => ({ ...prev, paymentReturnId: '', paymentReturnLocationId: '' }));
  }, []);

  const handleHeatmapPaymentReturnHandled = useCallback(() => {
    clearHeatmapPaymentReturnInUrl();
    setPaymentReturn(prev => ({ ...prev, heatmapPaymentReturnId: '' }));
  }, []);

  useEffect(() => {
    const sync = () => setPaymentReturn(readPaymentReturnFromUrl());
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);

  if (!isMarketplaceApiConfigured()) {
    return (
      <div className="landing-page marketplace-page">
        <main className="landing-main">
          <section className="landing-hero" aria-labelledby="marketplace-hero-title">
            <h1 id="marketplace-hero-title" className="landing-hero__title">
              {t('marketplacePageTitle')}
            </h1>
            <p className="landing-hero__subtitle">{t('marketplaceApiNotConfigured')}</p>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="landing-page marketplace-page">
      <main className="landing-main">
        <section className="landing-hero marketplace-hero" aria-labelledby="marketplace-hero-title">
          <h1 id="marketplace-hero-title" className="landing-hero__title">
            {t('marketplacePageTitle')}
          </h1>
        </section>

        <section className="marketplace-section" aria-label={t('marketplacePageTitle')}>
          {publishSuccess ? (
            <p className="marketplace-publish-success" role="status">
              {t('marketplaceMessengerPublishSuccess')}
            </p>
          ) : null}

          <ShareButton t={t} />

          <div className="marketplace-action-buttons">
            <button
              type="button"
              className="landing-btn landing-btn--secondary marketplace-action-btn"
              onClick={() =>
                openLeadModal(
                  `${t('marketplaceTelegramGreeting')}\n\n#ЗапропонуватиЛокацію`,
                  'marketplaceProposeLocationBtn',
                  'proposeLocation'
                )
              }
            >
              {t('marketplaceProposeLocationBtn')}
            </button>
            <button
              type="button"
              className="landing-btn landing-btn--secondary marketplace-action-btn"
              onClick={() =>
                openLeadModal(
                  `${t('marketplaceTelegramLookingForLocationGreeting')}\n\n#ШукаюЛокацію`,
                  'marketplaceLookingForLocationBtn',
                  'lookingForLocation'
                )
              }
            >
              {t('marketplaceLookingForLocationBtn')}
            </button>
          </div>

          <MarketplaceMap
            t={t}
            locale={locale}
            requestType="PROPOSE"
            hideHeader
            loadEvuaHeatmap
            showLookingMarkers
            paymentReturnId={paymentReturn.paymentReturnId}
            paymentReturnLocationId={paymentReturn.paymentReturnLocationId}
            onPaymentReturnHandled={handlePaymentReturnHandled}
            heatmapPaymentReturnId={paymentReturn.heatmapPaymentReturnId}
            onHeatmapPaymentReturnHandled={handleHeatmapPaymentReturnHandled}
          />
        </section>
      </main>

      <LeadFormModal
        t={t}
        locale={locale}
        open={leadModal.open}
        message={leadModal.message}
        titleKey={leadModal.titleKey}
        formType={leadModal.formType}
        onClose={closeLeadModal}
        onPublishSuccess={() => {
          setPublishSuccess(true);
          closeLeadModal();
        }}
      />
    </div>
  );
}
