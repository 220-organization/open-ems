import { useEffect } from 'react';
import { OPEN_EMS_SITE_URL } from './seoContent';

function upsertMeta(attr, key, content) {
  if (content == null || content === '') return;
  let el = document.querySelector(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
}

function upsertLink(rel, href, extraAttrs = {}) {
  if (!href) return;
  const selectorParts = [`link[rel="${rel}"]`];
  if (extraAttrs.hreflang) selectorParts.push(`[hreflang="${extraAttrs.hreflang}"]`);
  let el = document.querySelector(selectorParts.join(''));
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', rel);
    document.head.appendChild(el);
  }
  el.setAttribute('href', href);
  Object.entries(extraAttrs).forEach(([k, v]) => {
    if (v != null) el.setAttribute(k, v);
  });
}

/**
 * Syncs document title, html lang, and SEO meta tags for Open EMS SPA routes.
 * @param {string} pageTitle — document.title
 * @param {string} locale — uk | en | …
 * @param {Function} t — i18n translate
 * @param {{ variant?: 'default' | 'dam' | 'landing', canonicalPath?: string }} [options]
 */
export function useOpenEmsSeo(pageTitle, locale, t, options = {}) {
  const { variant = 'default', canonicalPath } = options;

  useEffect(() => {
    const htmlLang = locale === 'uk' ? 'uk' : locale;
    document.documentElement.lang = htmlLang;
    document.title = pageTitle;

    const descKey =
      variant === 'dam'
        ? 'damSeoMetaDescription'
        : variant === 'landing'
          ? 'landingSeoMetaDescription'
          : 'seoMetaDescription';
    const ogTitleKey =
      variant === 'dam' ? 'damSeoOgTitle' : variant === 'landing' ? 'landingSeoOgTitle' : 'seoOgTitle';
    const desc = t(descKey);
    const kw = t('seoMetaKeywords');
    const ogTitle = t(ogTitleKey) || pageTitle;

    const origin =
      typeof window !== 'undefined' && window.location?.origin
        ? window.location.origin
        : OPEN_EMS_SITE_URL;
    const path = canonicalPath ?? (typeof window !== 'undefined' ? window.location.pathname : '/');
    const canonicalUrl = `${origin}${path === '/' ? '/' : path}`;
    const ogImage = `${origin}/static/open-ems-og.png`;
    const ogLocale = locale === 'uk' ? 'uk_UA' : 'en_US';

    upsertMeta('name', 'description', desc);
    upsertMeta('name', 'keywords', kw);
    upsertMeta('name', 'robots', 'index, follow, max-image-preview:large');
    upsertMeta('name', 'author', '220-km.com');

    upsertMeta('property', 'og:type', 'website');
    upsertMeta('property', 'og:site_name', 'Open EMS');
    upsertMeta('property', 'og:title', ogTitle);
    upsertMeta('property', 'og:description', desc);
    upsertMeta('property', 'og:url', canonicalUrl);
    upsertMeta('property', 'og:image', ogImage);
    upsertMeta('property', 'og:locale', ogLocale);
    upsertMeta('property', 'og:locale:alternate', locale === 'uk' ? 'en_US' : 'uk_UA');

    upsertMeta('name', 'twitter:card', 'summary_large_image');
    upsertMeta('name', 'twitter:site', '@220kmua');
    upsertMeta('name', 'twitter:title', ogTitle);
    upsertMeta('name', 'twitter:description', desc);
    upsertMeta('name', 'twitter:image', ogImage);

    upsertLink('canonical', canonicalUrl);
    upsertLink('alternate', `${origin}/?lang=uk`, { hreflang: 'uk' });
    upsertLink('alternate', `${origin}/?lang=en`, { hreflang: 'en' });
    upsertLink('alternate', `${origin}/`, { hreflang: 'x-default' });
  }, [pageTitle, locale, t, variant, canonicalPath]);
}
