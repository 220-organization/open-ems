import { useCallback, useEffect, useState } from "react";
import { useOpenEmsSeo } from "./useOpenEmsSeo";
import BessLeadCrud from "./admin/BessLeadCrud";
import MarketplaceModeration from "./admin/MarketplaceModeration";
import RdnConsultationCrud from "./admin/RdnConsultationCrud";
import styles from "./AdminPage.module.css";

const TOKEN_KEY = "openEmsAdminToken";
const SECTIONS = ["marketplace", "rdn", "bess"];

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
  if (section === "bess") return t("adminSectionBess");
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
  const [section, setSection] = useState("rdn");

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
      return undefined;
    }
    let cancelled = false;
    const loadPending = async () => {
      try {
        const response = await fetch(
          `${apiBase()}/api/marketplace/locations/admin/pending-count`,
          {
            headers: { token },
          },
        );
        if (response.status === 401) {
          logout();
          return;
        }
        if (!response.ok) return;
        const data = await response.json();
        if (!cancelled) setPendingCount(Number(data.pending_count) || 0);
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
  }, [token, logout]);

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <header className={styles.header}>
          <div>
            <h1 className={styles.title}>
              {t("adminPageTitle")}
              {pendingCount > 0 ? (
                <span className={styles.badge}>{pendingCount}</span>
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
                </button>
              ))}
            </div>
            {section === "marketplace" ? (
              <MarketplaceModeration
                t={t}
                token={token}
                onLogout={logout}
                onPendingCountChange={setPendingCount}
              />
            ) : null}
            {section === "rdn" ? (
              <RdnConsultationCrud t={t} token={token} locale={locale} />
            ) : null}
            {section === "bess" ? <BessLeadCrud t={t} token={token} /> : null}
          </>
        )}
      </div>
    </div>
  );
}
