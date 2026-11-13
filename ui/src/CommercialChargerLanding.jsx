import { useState } from "react";
import "./commercial-charger.css";

const BENEFIT_KEYS = [
  "Ocpp",
  "Dlm",
  "Warranty",
  "Manager",
  "Bess",
  "Install",
  "Cert",
  "Service",
];

const TRUST_KEYS = ["Ce", "Ocpp", "Ukraine", "Brands"];

const PARTNER_WHO_KEYS = ["Installers", "Dealers", "Developers", "Fleets"];

const PARTNER_TERM_KEYS = ["Prices", "Support", "Region"];

const FAQ_KEYS = ["LeadTime", "Vat", "Downtime", "Ocpp", "Install", "Payment"];

const BILLING_POINT_KEYS = ["Qr", "Rdn", "Reports"];

/**
 * Marketing hero for the commercial DC charger catalog (Ampera-style structure, 220-km brand).
 */
export function CommercialHero({ t, onBrowseCatalog, onRequestQuote }) {
  return (
    <header className="cc-hero">
      <p className="cc-hero__eyebrow">{t("commercialLandingEyebrow")}</p>
      <h1 className="cc-hero__title">{t("commercialChargerPageTitle")}</h1>
      <p className="cc-hero__sub">{t("commercialChargerPageSubtitle")}</p>
      <ul
        className="cc-hero__stats"
        aria-label={t("commercialLandingStatsAria")}
      >
        <li>
          <strong>{t("commercialLandingStatPowerValue")}</strong>
          <span>{t("commercialLandingStatPowerLabel")}</span>
        </li>
        <li>
          <strong>{t("commercialLandingStatWarrantyValue")}</strong>
          <span>{t("commercialLandingStatWarrantyLabel")}</span>
        </li>
        <li>
          <strong>{t("commercialLandingStatOcppValue")}</strong>
          <span>{t("commercialLandingStatOcppLabel")}</span>
        </li>
        <li>
          <strong>{t("commercialLandingStatBrandsValue")}</strong>
          <span>{t("commercialLandingStatBrandsLabel")}</span>
        </li>
      </ul>
      <div className="cc-hero__actions">
        <button
          type="button"
          className="cc-btn cc-btn--primary"
          onClick={onBrowseCatalog}
        >
          {t("commercialLandingCtaBrowse")}
        </button>
        <button
          type="button"
          className="cc-btn cc-btn--ghost"
          onClick={onRequestQuote}
        >
          {t("commercialLandingCtaQuote")}
        </button>
      </div>
    </header>
  );
}

function FaqItem({ t, faqKey, open, onToggle }) {
  const panelId = `cc-faq-${faqKey}`;
  const btnId = `cc-faq-btn-${faqKey}`;
  return (
    <div className={`cc-faq__item${open ? " cc-faq__item--open" : ""}`}>
      <h3 className="cc-faq__q">
        <button
          type="button"
          id={btnId}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
        >
          {t(`commercialLandingFaq${faqKey}Q`)}
        </button>
      </h3>
      <div
        id={panelId}
        role="region"
        aria-labelledby={btnId}
        hidden={!open}
        className="cc-faq__a"
      >
        <p>{t(`commercialLandingFaq${faqKey}A`)}</p>
      </div>
    </div>
  );
}

/**
 * Why / billing / partners / FAQ / final CTA blocks below the product grid.
 */
export function CommercialMarketingSections({
  t,
  onRequestQuote,
  onPartnerRequest,
}) {
  const [openFaq, setOpenFaq] = useState(FAQ_KEYS[0]);
  const openPartner = onPartnerRequest || onRequestQuote;

  return (
    <div className="cc-marketing">
      <section className="cc-section" aria-labelledby="cc-why-title">
        <h2 id="cc-why-title" className="cc-section__title">
          {t("commercialLandingWhyTitle")}
        </h2>
        <p className="cc-section__lead">{t("commercialLandingWhyLead")}</p>
        <div className="cc-benefit-grid">
          {BENEFIT_KEYS.map((key) => (
            <article key={key} className="cc-benefit">
              <h3 className="cc-benefit__title">
                {t(`commercialLandingBenefit${key}Title`)}
              </h3>
              <p className="cc-benefit__text">
                {t(`commercialLandingBenefit${key}Text`)}
              </p>
            </article>
          ))}
        </div>
        <ul className="cc-trust" aria-label={t("commercialLandingTrustAria")}>
          {TRUST_KEYS.map((key) => (
            <li key={key}>{t(`commercialLandingTrust${key}`)}</li>
          ))}
        </ul>
      </section>

      <section
        className="cc-section cc-billing"
        aria-labelledby="cc-billing-title"
      >
        <h2 id="cc-billing-title" className="cc-section__title">
          {t("commercialLandingBillingTitle")}
        </h2>
        <p className="cc-section__lead">{t("commercialLandingBillingLead")}</p>
        <ul className="cc-billing__points">
          {BILLING_POINT_KEYS.map((key) => (
            <li key={key}>
              <strong>{t(`commercialLandingBilling${key}Title`)}</strong>
              <span>{t(`commercialLandingBilling${key}Text`)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="cc-section" aria-labelledby="cc-partner-title">
        <h2 id="cc-partner-title" className="cc-section__title">
          {t("commercialLandingPartnerTitle")}
        </h2>
        <p className="cc-section__lead">{t("commercialLandingPartnerLead")}</p>
        <div className="cc-partner-cols">
          <div>
            <h3 className="cc-partner__h">
              {t("commercialLandingPartnerWhoTitle")}
            </h3>
            <ul className="cc-list">
              {PARTNER_WHO_KEYS.map((key) => (
                <li key={key}>{t(`commercialLandingPartnerWho${key}`)}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="cc-partner__h">
              {t("commercialLandingPartnerTermsTitle")}
            </h3>
            <ul className="cc-list">
              {PARTNER_TERM_KEYS.map((key) => (
                <li key={key}>{t(`commercialLandingPartnerTerm${key}`)}</li>
              ))}
            </ul>
          </div>
        </div>
        <button
          type="button"
          className="cc-btn cc-btn--primary"
          onClick={openPartner}
        >
          {t("commercialLandingPartnerCta")}
        </button>
      </section>

      <section className="cc-section" aria-labelledby="cc-faq-title">
        <h2 id="cc-faq-title" className="cc-section__title">
          {t("commercialLandingFaqTitle")}
        </h2>
        <div className="cc-faq">
          {FAQ_KEYS.map((key) => (
            <FaqItem
              key={key}
              t={t}
              faqKey={key}
              open={openFaq === key}
              onToggle={() => setOpenFaq(openFaq === key ? "" : key)}
            />
          ))}
        </div>
      </section>

      <section
        className="cc-section cc-final-cta"
        aria-labelledby="cc-final-title"
      >
        <h2 id="cc-final-title" className="cc-section__title">
          {t("commercialLandingFinalTitle")}
        </h2>
        <p className="cc-section__lead">{t("commercialLandingFinalLead")}</p>
        <div className="cc-hero__actions">
          <button
            type="button"
            className="cc-btn cc-btn--primary"
            onClick={onRequestQuote}
          >
            {t("commercialLandingCtaQuote")}
          </button>
        </div>
      </section>
    </div>
  );
}

/** FAQ entries for FAQPage JSON-LD (same keys as the accordion). */
export function commercialLandingFaqJsonLd(t) {
  return FAQ_KEYS.map((key) => ({
    "@type": "Question",
    name: t(`commercialLandingFaq${key}Q`),
    acceptedAnswer: {
      "@type": "Answer",
      text: t(`commercialLandingFaq${key}A`),
    },
  }));
}
