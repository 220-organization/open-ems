import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import SharePageModal from "./SharePageModal";
import { buildSharePageModalPayload } from "./sharePageQr";
import { navigateOpenEmsHomeResetSource } from "./essSelection";
import { OPEN_EMS_SITE_URL } from "./seoContent";
import { useLongPressNavigate } from "./useLongPressNavigate";
import { EMS_WORDMARK_SRC } from "./vyriiEmsLogo";
import "./power-flow.css";
import "./landing.css";

const SITE_220KM = "https://220-km.com/";
const HEADER_LANG_LABELS = { en: "EN", uk: "UA", es: "ES" };

/** Hold on Open EMS opens 220-km.com. Hold on 220-km.com opens the EMS on :9220. */
function otherBrandUrl() {
  try {
    const { hostname, port } = window.location;
    const onOpenEms =
      port === "9220" || hostname === "localhost" || hostname === "127.0.0.1";
    if (onOpenEms) return SITE_220KM;
    return `${OPEN_EMS_SITE_URL.replace(/\/$/, "")}/`;
  } catch {
    return SITE_220KM;
  }
}

/** Spain DAM view uses the 220 EMS lockup instead of the locale brand name. */
function isEmsVppBrandUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const market = (params.get("market") || "").trim().toLowerCase();
    const zone = (params.get("zone") || "").trim().toUpperCase();
    return market === "oree" && zone === "ES";
  } catch {
    return false;
  }
}

function themeToggleLabels(theme) {
  if (theme === "dark") {
    return {
      aria: "Switch to system theme",
      title: "Dark theme (click for system)",
    };
  }
  if (theme === "light") {
    return {
      aria: "Switch to dark theme",
      title: "Light theme (click for dark)",
    };
  }
  return {
    aria: "Switch to light theme",
    title: "System theme (click for light)",
  };
}

function MenuIcon({ children }) {
  return (
    <svg
      width="36"
      height="36"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

function ShareMenuIcon() {
  return (
    <MenuIcon>
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </MenuIcon>
  );
}

function ThemeToggleIcon({ theme }) {
  if (theme === "dark") {
    return (
      <MenuIcon>
        <path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z" />
      </MenuIcon>
    );
  }
  if (theme === "light") {
    return (
      <MenuIcon>
        <circle cx="12" cy="12" r="4" />
        <line x1="12" y1="2" x2="12" y2="4" />
        <line x1="12" y1="20" x2="12" y2="22" />
        <line x1="4.93" y1="4.93" x2="6.34" y2="6.34" />
        <line x1="17.66" y1="17.66" x2="19.07" y2="19.07" />
        <line x1="2" y1="12" x2="4" y2="12" />
        <line x1="20" y1="12" x2="22" y2="12" />
        <line x1="4.93" y1="19.07" x2="6.34" y2="17.66" />
        <line x1="17.66" y1="6.34" x2="19.07" y2="4.93" />
      </MenuIcon>
    );
  }
  return (
    <MenuIcon>
      <rect x="3" y="4" width="18" height="12" rx="2" ry="2" />
      <line x1="8" y1="20" x2="16" y2="20" />
      <line x1="12" y1="16" x2="12" y2="20" />
    </MenuIcon>
  );
}

/**
 * Site-wide sticky header (brand, nav, language).
 * @param {'power' | 'landing' | 'evTv' | 'evSound' | 'marketplace' | 'orderBess' | 'buyHomeCharger' | 'buyCommercialCharger' | 'rdnConsultation' | 'admin'} activePage
 */
export default function OpenEmsHeader({
  t,
  locale,
  SUPPORTED,
  LOCALE_NAMES,
  onLangSelectChange,
  activePage,
  theme,
  cycleTheme,
  chromeHidden = false,
}) {
  const logoSrc = EMS_WORDMARK_SRC;
  const [spainDam, setSpainDam] = useState(isEmsVppBrandUrl);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareModalUrl, setShareModalUrl] = useState("");
  const [shareModalCopied, setShareModalCopied] = useState(false);
  const [shareModalCopyFailed, setShareModalCopyFailed] = useState(false);

  const [menuOpen, setMenuOpen] = useState(false);
  const themeLabels = themeToggleLabels(theme);
  const navItems = [
    { page: "power", href: "/", label: t("landingNavDemo") },
    { page: "landing", href: "/about", label: t("landingNavHome") },
    {
      page: "buyCommercialCharger",
      href: "/buy-commercial-charger",
      label: t("chargerCatalogNavLabel"),
    },
    { page: "marketplace", href: "/marketplace", label: t("marketplaceNavLabel") },
    { page: "orderBess", href: "/order-bess", label: t("orderBessNavLabel") },
    {
      page: "rdnConsultation",
      href: "/rdn-consultation",
      label: t("rdnConsultationNavLabel"),
    },
    { page: "evTv", href: "/ev-tv", label: t("evTvNavLabel") },
    { page: "evSound", href: "/ev-sound", label: t("evSoundNavLabel") },
    { page: "admin", href: "/admin", label: t("adminNavLabel") },
  ];

  const isNavActive = (page) => {
    if (page === "buyCommercialCharger") {
      return (
        activePage === "buyHomeCharger" || activePage === "buyCommercialCharger"
      );
    }
    return activePage === page;
  };

  const closeMenu = useCallback(() => setMenuOpen(false), []);
  const toggleMenu = useCallback(() => setMenuOpen((open) => !open), []);

  const selectLocale = useCallback(
    (code) => {
      onLangSelectChange({ target: { value: code } });
      setMenuOpen(false);
    },
    [onLangSelectChange]
  );

  const handleSharePage = useCallback(async () => {
    const payload = await buildSharePageModalPayload();
    if (!payload) return;
    setShareModalUrl(payload.url);
    setShareModalCopied(payload.copied);
    setShareModalCopyFailed(payload.copyFailed);
    setShareModalOpen(true);
  }, []);

  const closeShareModal = useCallback(() => {
    setShareModalOpen(false);
  }, []);

  const openOtherBrand = useCallback(() => {
    window.location.assign(otherBrandUrl());
  }, []);

  const {
    holding: brandHolding,
    holdHandlers: brandHoldHandlers,
    consumeClick: consumeBrandHoldClick,
  } = useLongPressNavigate(openOtherBrand);

  const handleBrandClick = useCallback(
    (e) => {
      if (consumeBrandHoldClick(e)) return;
      e.preventDefault();
      navigateOpenEmsHomeResetSource();
    },
    [consumeBrandHoldClick]
  );

  const shellRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    const onPointer = (event) => {
      const shell = shellRef.current;
      if (shell && event.target instanceof Node && !shell.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [menuOpen]);

  useEffect(() => {
    const syncBrand = () => setSpainDam(isEmsVppBrandUrl());
    syncBrand();
    window.addEventListener("popstate", syncBrand);
    return () => window.removeEventListener("popstate", syncBrand);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("open-ems-tron", spainDam);
    return () => {
      document.documentElement.classList.remove("open-ems-tron");
    };
  }, [spainDam]);

  useEffect(() => {
    const el = shellRef.current;
    if (!el) return undefined;

    const syncHeaderOffset = () => {
      const headerInner = el.querySelector(".landing-header");
      const naturalH = headerInner
        ? Math.ceil(headerInner.getBoundingClientRect().height)
        : 0;
      document.documentElement.style.setProperty(
        "--open-ems-site-header-h",
        chromeHidden ? "0px" : `${naturalH}px`,
      );
    };

    const headerInner = el.querySelector(".landing-header");

    syncHeaderOffset();
    const ro = new ResizeObserver(syncHeaderOffset);
    ro.observe(el);
    if (headerInner) ro.observe(headerInner);
    window.addEventListener("resize", syncHeaderOffset);

    return () => {
      ro.disconnect();
      window.removeEventListener("resize", syncHeaderOffset);
      document.documentElement.style.removeProperty("--open-ems-site-header-h");
    };
  }, [locale, activePage, chromeHidden]);

  return (
    <>
      <div ref={shellRef} className="open-ems-header-shell">
        <header className="landing-header open-ems-header">
          <button
            type="button"
            className={
              "landing-header__burger" +
              (menuOpen ? " landing-header__burger--open" : "")
            }
            aria-label={t("landingNavAria")}
            aria-expanded={menuOpen}
            aria-controls="open-ems-header-menu"
            onClick={toggleMenu}
          />
          <a
            className={
              "landing-header__brand landing-header__brand--ems-vpp" +
              (brandHolding ? " landing-header__brand--holding" : "")
            }
            href={`${OPEN_EMS_SITE_URL}/`}
            aria-label="220 EMS"
            draggable={false}
            {...brandHoldHandlers}
            onClick={handleBrandClick}
          >
            <span className="landing-header__logo-slot">
              <img
                className="landing-header__logo"
                src={logoSrc}
                alt=""
                width={109}
                height={59}
                decoding="async"
                draggable={false}
              />
            </span>
            {brandHolding ? (
              <span className="landing-header__logo-progress" aria-hidden="true" />
            ) : null}
          </a>
          <button
            type="button"
            className="landing-header__share"
            aria-label={t("sharePageModalTitle")}
            title={t("sharePageModalTitle")}
            onClick={() => {
              closeMenu();
              void handleSharePage();
            }}
          >
            <ShareMenuIcon />
          </button>
          {menuOpen ? (
            <div id="open-ems-header-menu" className="landing-header__menu">
              <nav className="landing-nav" aria-label={t("landingNavAria")}>
                {navItems.map((item) => (
                  <a
                    key={item.page}
                    className={
                      "landing-nav__link" +
                      (isNavActive(item.page) ? " landing-nav__link--active" : "")
                    }
                    href={item.href}
                  >
                    {item.label}
                  </a>
                ))}
              </nav>
              <div
                className="landing-header__langs"
                role="group"
                aria-label={t("langSelectAria")}
              >
                {SUPPORTED.map((code, index) => (
                  <Fragment key={code}>
                    {index > 0 ? (
                      <span className="landing-header__lang-mark" aria-hidden="true">
                        /
                      </span>
                    ) : null}
                    <button
                      type="button"
                      className={code === locale ? "is-active" : undefined}
                      aria-label={LOCALE_NAMES[code] || code}
                      onClick={() => selectLocale(code)}
                    >
                      {HEADER_LANG_LABELS[code] || code.toUpperCase()}
                    </button>
                  </Fragment>
                ))}
              </div>
              <div className="landing-header__menu-tools">
                <button
                  type="button"
                  className="landing-header__menu-action"
                  onClick={() => {
                    cycleTheme();
                    closeMenu();
                  }}
                  aria-label={themeLabels.aria}
                  title={themeLabels.title}
                >
                  <ThemeToggleIcon theme={theme} />
                </button>
              </div>
            </div>
          ) : null}
        </header>
      </div>
      <SharePageModal
        open={shareModalOpen}
        url={shareModalUrl}
        copied={shareModalCopied}
        copyFailed={shareModalCopyFailed}
        onClose={closeShareModal}
        t={t}
      />
    </>
  );
}
