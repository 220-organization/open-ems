import { useEffect } from 'react';

/**
 * Syncs document title, html lang, and primary SEO meta tags for Open EMS SPA routes.
 */
export function useOpenEmsSeo(pageTitle, locale, t) {
  useEffect(() => {
    document.title = pageTitle;
    document.documentElement.lang = locale === 'uk' ? 'uk' : locale;
    const desc = t('seoMetaDescription');
    const kw = t('seoMetaKeywords');
    const setNamedMeta = (name, content) => {
      let el = document.querySelector(`meta[name="${name}"]`);
      if (!el) {
        el = document.createElement('meta');
        el.setAttribute('name', name);
        document.head.appendChild(el);
      }
      el.setAttribute('content', content);
    };
    setNamedMeta('description', desc);
    setNamedMeta('keywords', kw);
  }, [pageTitle, locale, t]);
}
