import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { buildB2bTelegramUrl, buildB2bWhatsAppUrl } from './messengerContactUrls';

function TelegramIcon() {
  return (
    <svg
      width={32}
      height={32}
      viewBox="0 0 24 24"
      aria-hidden
      focusable="false"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Single path (avoids nonzero fill glitches from the old two-subpath “plane cutout” shape). */}
      <path
        fill="currentColor"
        d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"
      />
    </svg>
  );
}

function WhatsAppIcon() {
  return (
    <svg width={32} height={32} viewBox="0 0 24 24" aria-hidden focusable="false">
      <path
        fill="currentColor"
        d="M17.5 14.4c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.65.07-.3-.15-1.26-.46-2.4-1.47-.89-.79-1.49-1.76-1.66-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.02-.52-.07-.15-.67-1.61-.92-2.2-.24-.58-.49-.5-.67-.51l-.57-.01c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48 0 1.46 1.06 2.88 1.21 3.08.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49 1.69.62.71.23 1.36.2 1.87.12.57-.08 1.76-.72 2-1.41.25-.7.25-1.29.18-1.41-.07-.12-.27-.2-.57-.35zM12.04 2C6.58 2 2.2 6.38 2.2 11.84c0 1.9.5 3.75 1.45 5.38L2 22l4.67-1.22a9.86 9.86 0 005.37 1.58h.01c5.46 0 9.84-4.38 9.84-9.84C21.88 6.38 17.5 2 12.04 2zm0 17.67h-.01a7.82 7.82 0 01-3.98-1.1l-.29-.17-2.95.77.79-2.88-.18-.29a7.8 7.8 0 01-1.19-4.16c0-4.32 3.51-7.83 7.83-7.83s7.83 3.51 7.83 7.83-3.51 7.83-7.83 7.83z"
      />
    </svg>
  );
}

/**
 * Same pattern as 220-km.com/b2b messenger modal: Telegram / WhatsApp choice.
 */
export default function DeyeInverterMessengerModal({ open, onClose, t }) {
  const [slideIndex, setSlideIndex] = useState(0);

  const instructionSlides = [
    {
      src: '/static/deye-add-carousel/step-1.png',
      alt: t('addDeyeInstructionStep1Alt'),
    },
    {
      src: '/static/deye-add-carousel/step-2.png',
      alt: t('addDeyeInstructionStep2Alt'),
    },
    {
      src: '/static/deye-add-carousel/step-3.png',
      alt: t('addDeyeInstructionStep3Alt'),
    },
    {
      src: '/static/deye-add-carousel/step-4.png',
      alt: t('addDeyeInstructionStep4Alt'),
    },
    {
      src: '/static/deye-add-carousel/step-5.png',
      alt: t('addDeyeInstructionStep5Alt'),
    },
    {
      src: '/static/deye-add-carousel/step-6.png',
      alt: t('addDeyeInstructionStep6Alt'),
    },
  ];
  const isLastSlide = slideIndex >= instructionSlides.length - 1;

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowRight') setSlideIndex((prev) => Math.min(prev + 1, instructionSlides.length - 1));
      if (e.key === 'ArrowLeft') setSlideIndex((prev) => Math.max(prev - 1, 0));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, instructionSlides.length]);

  useEffect(() => {
    if (open) setSlideIndex(0);
  }, [open]);

  if (!open || typeof document === 'undefined') return null;

  const message = t('addDeyeMessengerPrefill');

  const openMessenger = (channel) => {
    const url =
      channel === 'telegram' ? buildB2bTelegramUrl(message) : buildB2bWhatsAppUrl(message);
    window.open(url, '_blank');
    onClose();
  };

  const node = (
    <div className="pf-messenger-scrim" role="presentation" onClick={onClose}>
      <div
        className="pf-messenger-dialog pf-messenger-dialog--deye-add"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-add-deye-messenger-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pf-messenger-panel">
          <header className="pf-messenger-deye-header">
            <p id="pf-add-deye-messenger-title" className="pf-messenger-title--deye">
              {t('addDeyeInstructionTitle')}
            </p>
            <button
              type="button"
              className="pf-messenger-close"
              aria-label={t('addDeyeModalCloseAria')}
              onClick={onClose}
            >
              <span aria-hidden>×</span>
            </button>
          </header>
          <div className="pf-add-deye-carousel" aria-live="polite">
            <img
              className="pf-add-deye-carousel__image"
              src={instructionSlides[slideIndex].src}
              alt={instructionSlides[slideIndex].alt}
              loading="eager"
              decoding="async"
            />
            <div className="pf-add-deye-carousel__progress">
              {instructionSlides.map((slide, idx) => (
                <button
                  key={slide.src}
                  type="button"
                  className={`pf-add-deye-carousel__dot${idx === slideIndex ? ' is-active' : ''}`}
                  aria-label={t('addDeyeInstructionStepAria', { step: String(idx + 1) })}
                  onClick={() => setSlideIndex(idx)}
                />
              ))}
            </div>
            <div className="pf-add-deye-carousel__controls">
              <button
                type="button"
                className="pf-add-deye-carousel__nav-btn"
                onClick={() => setSlideIndex((prev) => Math.max(prev - 1, 0))}
                disabled={slideIndex === 0}
              >
                {t('addDeyeInstructionBack')}
              </button>
              <button
                type="button"
                className="pf-add-deye-carousel__nav-btn pf-add-deye-carousel__nav-btn--primary"
                onClick={() => setSlideIndex((prev) => Math.min(prev + 1, instructionSlides.length - 1))}
                disabled={isLastSlide}
              >
                {t('addDeyeInstructionNext')}
              </button>
            </div>
          </div>

          <p className="pf-messenger-subtitle">
            {t('addDeyeMessengerSubtitle')}
          </p>
          <div className="pf-messenger-actions">
            <button
              type="button"
              className="pf-messenger-icon-btn pf-messenger-icon-btn--telegram"
              aria-label={t('addDeyeMessengerTelegramAria')}
              onClick={() => openMessenger('telegram')}
            >
              <TelegramIcon />
            </button>
            <button
              type="button"
              className="pf-messenger-icon-btn pf-messenger-icon-btn--whatsapp"
              aria-label={t('addDeyeMessengerWhatsAppAria')}
              onClick={() => openMessenger('whatsapp')}
            >
              <WhatsAppIcon />
            </button>
          </div>

          <button type="button" className="pf-messenger-close-footer" onClick={onClose}>
            {t('addDeyeModalCloseAria')}
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(node, document.body);
}
