import { useCallback, useEffect, useState } from "react";
import styles from "../AdminPage.module.css";

function apiBase() {
  return (process.env.REACT_APP_API_BASE_URL || "").replace(/\/$/, "");
}

function emptyDraft() {
  return {
    id: null,
    preset_id: "",
    business_type: "installer",
    units: "2",
    total_usd: "",
    contact: "",
  };
}

function draftFromRow(row) {
  return {
    id: row.id,
    preset_id: row.preset_id || "",
    business_type: row.business_type || "",
    units: String(row.units ?? ""),
    total_usd: row.total_usd == null ? "" : String(row.total_usd),
    contact: row.contact || "",
  };
}

export default function BessLeadCrud({ t, token }) {
  const [items, setItems] = useState([]);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${apiBase()}/api/bess-order/discount-requests/admin`, {
        headers: { token },
        cache: "no-store",
      });
      if (!response.ok) throw new Error("load");
      const data = await response.json();
      setItems(Array.isArray(data.items) ? data.items : []);
    } catch {
      setError(t("adminLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t, token]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const totalRaw = String(draft.total_usd || "").trim();
    const body = {
      preset_id: draft.preset_id.trim(),
      business_type: draft.business_type.trim(),
      units: Number.parseInt(draft.units, 10),
      total_usd: totalRaw === "" ? null : Number(totalRaw),
      contact: draft.contact,
    };
    const url = draft.id
      ? `${apiBase()}/api/bess-order/discount-requests/admin/${draft.id}`
      : `${apiBase()}/api/bess-order/discount-requests/admin`;
    try {
      const response = await fetch(url, {
        method: draft.id ? "PUT" : "POST",
        headers: { "Content-Type": "application/json", token },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error("save");
      setDraft(null);
      await load();
    } catch {
      setError(t("adminSaveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row) => {
    if (!window.confirm(t("adminDeleteConfirm"))) return;
    setError("");
    try {
      const response = await fetch(
        `${apiBase()}/api/bess-order/discount-requests/admin/${row.id}`,
        { method: "DELETE", headers: { token } },
      );
      if (!response.ok && response.status !== 204) throw new Error("delete");
      if (draft?.id === row.id) setDraft(null);
      await load();
    } catch {
      setError(t("adminDeleteFailed"));
    }
  };

  return (
    <section className={styles.crud}>
      <div className={styles.crudBar}>
        <h2 className={styles.crudTitle}>{t("adminSectionBess")}</h2>
        <div className={styles.crudActions}>
          <button type="button" className={styles.submit} onClick={() => setDraft(emptyDraft())}>
            {t("adminCreate")}
          </button>
          <button type="button" className={styles.logout} onClick={load} disabled={loading}>
            {loading ? t("adminLoading") : t("adminRefresh")}
          </button>
        </div>
      </div>
      {error ? <p className={styles.error}>{error}</p> : null}
      {draft ? (
        <form className={styles.form} onSubmit={save}>
          <label className={styles.label}>
            {t("adminFieldPreset")}
            <input
              className={styles.input}
              required
              value={draft.preset_id}
              onChange={(e) => setDraft({ ...draft, preset_id: e.target.value })}
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldBusiness")}
            <input
              className={styles.input}
              required
              value={draft.business_type}
              onChange={(e) => setDraft({ ...draft, business_type: e.target.value })}
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldUnits")}
            <input
              className={styles.input}
              required
              inputMode="numeric"
              value={draft.units}
              onChange={(e) => setDraft({ ...draft, units: e.target.value })}
            />
          </label>
          <label className={styles.label}>
            {t("adminFieldTotalUsd")}
            <input
              className={styles.input}
              inputMode="decimal"
              value={draft.total_usd}
              onChange={(e) => setDraft({ ...draft, total_usd: e.target.value })}
            />
          </label>
          <label className={`${styles.label} ${styles.span2}`}>
            {t("adminFieldContact")}
            <input
              className={styles.input}
              value={draft.contact}
              onChange={(e) => setDraft({ ...draft, contact: e.target.value })}
            />
          </label>
          <div className={styles.formButtons}>
            <button type="submit" className={styles.submit} disabled={busy}>
              {t("adminSave")}
            </button>
            <button type="button" className={styles.logout} onClick={() => setDraft(null)}>
              {t("adminCancel")}
            </button>
          </div>
        </form>
      ) : null}
      {!loading && items.length === 0 ? <p className={styles.lead}>{t("adminEmpty")}</p> : null}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>{t("adminFieldPreset")}</th>
              <th>{t("adminFieldBusiness")}</th>
              <th>{t("adminFieldUnits")}</th>
              <th>{t("adminFieldTotalUsd")}</th>
              <th>{t("adminFieldContact")}</th>
              <th>{t("adminColActions")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{row.preset_id}</td>
                <td>{row.business_type}</td>
                <td>{row.units}</td>
                <td>{row.total_usd == null ? "—" : row.total_usd}</td>
                <td>{row.contact || "—"}</td>
                <td className={styles.rowActions}>
                  <button type="button" className={styles.linkBtn} onClick={() => setDraft(draftFromRow(row))}>
                    {t("adminEdit")}
                  </button>
                  <button type="button" className={styles.linkBtn} onClick={() => remove(row)}>
                    {t("adminDelete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
