import { useCallback, useEffect, useMemo, useState } from "react";
import { useOpenEmsSeo } from "./useOpenEmsSeo";
import AdminWeekCalendar from "./admin/AdminWeekCalendar";
import BuyRequestCrud from "./admin/BuyRequestCrud";
import MarketplaceModeration from "./admin/MarketplaceModeration";
import RdnConsultationCrud from "./admin/RdnConsultationCrud";
import styles from "./AdminPage.module.css";

const TOKEN_KEY = "openEmsAdminToken";
const SECTIONS = ["marketplace", "rdn", "buy"];

function apiBase() {
  return (process.env.REACT_APP_API_BASE_URL || "").replace(/\/$/, "");
}

function isLocalAdmin() {
  if (typeof window === "undefined") return false;
  const host = window.location.hostname;
  return host === "localhost" || host === "127.0.0.1";
}

function sectionLabel(t, section) {
  if (section === "rdn") return t("adminSectionRdn");
  if (section === "buy") return t("adminSectionBuyRequest");
  return t("adminSectionMarketplace");
}

export default function AdminPage({ t, locale }) {
  useOpenEmsSeo(t("adminPageTitle"), locale, t, {
    variant: "landing",
    canonicalPath: "/admin",
  });

  const localOpen = isLocalAdmin();
  const [token, setToken] = useState(() => {
    if (isLocalAdmin()) return "local";
    try {
      return window.localStorage.getItem(TOKEN_KEY) || "";
    } catch {
      return "";
    }
  });
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [requestedConsultationCount, setRequestedConsultationCount] = useState(0);
  const [requestedBuyCount, setRequestedBuyCount] = useState(0);
  const [consultationItems, setConsultationItems] = useState([]);
  const [buyItems, setBuyItems] = useState([]);
  const [section, setSection] = useState("rdn");
  const [calendarTick, setCalendarTick] = useState(0);

  const logout = useCallback(() => {
    if (isLocalAdmin()) return;
    setToken("");
    try {
      window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const handleLogin = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${apiBase()}/api/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!response.ok) {
        throw new Error(t("adminLoginFailed"));
      }
      const data = await response.json();
      const nextToken = data.token || "";
      if (!nextToken) throw new Error(t("adminLoginFailed"));
      setToken(nextToken);
      try {
        window.localStorage.setItem(TOKEN_KEY, nextToken);
      } catch {
        /* ignore */
      }
      setPassword("");
    } catch (err) {
      setError(err.message || t("adminLoginFailed"));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!token) {
      setPendingCount(0);
      setRequestedConsultationCount(0);
      setRequestedBuyCount(0);
      setConsultationItems([]);
      setBuyItems([]);
      return undefined;
    }
    let cancelled = false;
    const countRequested = (items) =>
      (Array.isArray(items) ? items : []).filter(
        (row) => String(row.status || "").toLowerCase() === "requested",
      ).length;
    const loadPending = async () => {
      try {
        const [marketRes, rdnRes, buyRes] = await Promise.all([
          fetch(`${apiBase()}/api/marketplace/locations/admin/pending-count`, {
            headers: { token },
          }),
          fetch(`${apiBase()}/api/rdn-consultation/admin`, {
            headers: { token },
            cache: "no-store",
          }),
          fetch(`${apiBase()}/api/sales-buy-request/admin`, {
            headers: { token },
            cache: "no-store",
          }),
        ]);
        if (marketRes.status === 401 || rdnRes.status === 401 || buyRes.status === 401) {
          logout();
          return;
        }
        if (marketRes.ok) {
          const data = await marketRes.json();
          if (!cancelled) setPendingCount(Number(data.pending_count) || 0);
        }
        if (rdnRes.ok) {
          const data = await rdnRes.json();
          const items = Array.isArray(data.items) ? data.items : [];
          if (!cancelled) {
            setConsultationItems(items);
            setRequestedConsultationCount(countRequested(items));
          }
        }
        if (buyRes.ok) {
          const data = await buyRes.json();
          const items = Array.isArray(data.items) ? data.items : [];
          if (!cancelled) {
            setBuyItems(items);
            setRequestedBuyCount(countRequested(items));
          }
        }
      } catch {
        /* ignore */
      }
    };
    loadPending();
    const timer = window.setInterval(loadPending, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [token, logout, section, calendarTick]);

  const headerBadgeCount = pendingCount + requestedConsultationCount + requestedBuyCount;

  const calendarItems = useMemo(
    () => [
      ...consultationItems.map((row) => ({
        ...row,
        calendar_group: "consultation",
        source: "consultation",
      })),
      ...buyItems.map((row) => ({
        ...row,
        source: "buy",
      })),
    ],
    [consultationItems, buyItems],
  );

  const calendarMetaLabel = useCallback(
    (row) => {
      if (row.source === "buy") {
        if (row.kind === "bess") return t("adminBuyKindBess");
        if (row.kind === "bess_discount") return t("adminBuyKindBessDiscount");
        return t("adminBuyKindStation");
      }
      return row.kind === "callback" ? t("rdnAdminKindCallback") : t("rdnAdminKindPayment");
    },
    [t],
  );

  const onCalendarSelect = useCallback((row) => {
    if (row.source === "buy") setSection("buy");
    else setSection("rdn");
  }, []);

  const refreshCalendar = useCallback(() => {
    setCalendarTick((n) => n + 1);
  }, []);

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <header className={styles.header}>
          <div>
            <h1 className={styles.title}>
              {t("adminPageTitle")}
              {headerBadgeCount > 0 ? (
                <span className={styles.badge}>{headerBadgeCount}</span>
              ) : null}
            </h1>
            <p className={styles.lead}>{t("adminPageLead")}</p>
          </div>
          {token && !localOpen ? (
            <button type="button" className={styles.logout} onClick={logout}>
              {t("adminLogout")}
            </button>
          ) : null}
        </header>

        {!token ? (
          <form className={styles.login} onSubmit={handleLogin}>
            <label className={styles.label}>
              {t("adminPasswordLabel")}
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={styles.input}
              />
            </label>
            {error ? <p className={styles.error}>{error}</p> : null}
            <button
              type="submit"
              className={styles.submit}
              disabled={busy || !password.trim()}
            >
              {busy ? t("adminLoggingIn") : t("adminLogin")}
            </button>
          </form>
        ) : (
          <>
            <div className={styles.tabs} role="tablist" aria-label={t("adminSectionsAria")}>
              {SECTIONS.map((id) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={section === id}
                  className={section === id ? styles.tabActive : styles.tab}
                  onClick={() => setSection(id)}
                >
                  {sectionLabel(t, id)}
                  {id === "marketplace" && pendingCount > 0 ? (
                    <span className={styles.badge}>{pendingCount}</span>
                  ) : null}
                  {id === "rdn" && requestedConsultationCount > 0 ? (
                    <span className={styles.badge}>{requestedConsultationCount}</span>
                  ) : null}
                  {id === "buy" && requestedBuyCount > 0 ? (
                    <span className={styles.badge}>{requestedBuyCount}</span>
                  ) : null}
                </button>
              ))}
            </div>
            <section className={styles.calendarAlways} aria-label={t("adminWeekAria")}>
              <AdminWeekCalendar
                t={t}
                locale={locale}
                items={calendarItems}
                onSelect={onCalendarSelect}
                metaLabel={calendarMetaLabel}
              />
            </section>
            {section === "marketplace" ? (
              <MarketplaceModeration
                t={t}
                token={token}
                onLogout={logout}
                onPendingCountChange={setPendingCount}
              />
            ) : null}
            {section === "rdn" ? (
              <RdnConsultationCrud
                t={t}
                token={token}
                locale={locale}
                hideCalendar
                onDataChanged={refreshCalendar}
              />
            ) : null}
            {section === "buy" ? (
              <BuyRequestCrud
                t={t}
                token={token}
                locale={locale}
                hideCalendar
                onDataChanged={refreshCalendar}
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
