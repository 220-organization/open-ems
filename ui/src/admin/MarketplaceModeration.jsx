import { useEffect, useState } from "react";
import styles from "./MarketplaceModeration.module.css";

const MARKETPLACE_STATUSES = ["PENDING", "PUBLISHED", "HIDDEN"];

function apiBase() {
  return (process.env.REACT_APP_API_BASE_URL || "").replace(/\/$/, "");
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  const pad = (n) => n.toString().padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function resolveAssetUrl(url) {
  if (!url) return url;
  if (/^https?:\/\//i.test(url)) return url;
  const base = apiBase();
  return `${base}${url.startsWith("/") ? url : `/${url}`}`;
}

function contractToFormValue(value) {
  if (value === true) return "true";
  if (value === false) return "false";
  return "";
}

function contractFromFormValue(value) {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

function buildEditForm(row) {
  return {
    status: row.status || "PENDING",
    name: row.name || "",
    phone: row.phone || "",
    kw_available: row.kw_available || "",
    distribution_contract: contractToFormValue(row.distribution_contract),
    distance_meters:
      row.distance_meters != null ? String(row.distance_meters) : "",
    price_per_kwh_extra:
      row.price_per_kwh_extra != null ? String(row.price_per_kwh_extra) : "",
    monthly_price_parking:
      row.monthly_price_parking != null
        ? String(row.monthly_price_parking)
        : "",
  };
}

function readEditQuery() {
  try {
    return new URLSearchParams(window.location.search).get("edit") || "";
  } catch {
    return "";
  }
}

function setEditQuery(editId) {
  try {
    const url = new URL(window.location.href);
    if (editId) url.searchParams.set("edit", String(editId));
    else url.searchParams.delete("edit");
    window.history.replaceState({}, "", url);
  } catch {
    /* ignore */
  }
}

export default function MarketplaceModeration({
  t,
  token,
  onLogout,
  onPendingCountChange,
}) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState(null);

  const tokenHeaders = {
    headers: { token, "Content-Type": "application/json" },
  };

  const fetchItems = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `${apiBase()}/api/marketplace/locations/admin`,
        {
          headers: { token },
        },
      );
      if (response.status === 401) {
        onLogout();
        return;
      }
      if (!response.ok) throw new Error(t("adminLoadFailed"));
      const data = await response.json();
      const nextItems = data?.items ?? [];
      setItems(nextItems);
      const pending = nextItems.filter(
        (row) => row.status === "PENDING",
      ).length;
      if (typeof onPendingCountChange === "function")
        onPendingCountChange(pending);
    } catch (err) {
      setError(err.message || t("adminLoadFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    const editId = readEditQuery();
    if (!editId || items.length === 0 || editingId) return;
    const row = items.find((item) => String(item.id) === String(editId));
    if (row) {
      setEditingId(row.id);
      setEditForm(buildEditForm(row));
    }
  }, [items, editingId]);

  const handleEdit = (row) => {
    setEditingId(row.id);
    setEditForm(buildEditForm(row));
    setEditQuery(row.id);
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setEditForm(null);
    setEditQuery("");
  };

  const handleEditChange = (e) => {
    const { name, value } = e.target;
    setEditForm((prev) => ({ ...prev, [name]: value }));
  };

  const handleSaveEdit = async () => {
    if (!editingId || !editForm) return;
    setError("");
    try {
      const payload = {
        status: editForm.status,
        name: editForm.name.trim(),
        phone: editForm.phone.trim(),
        kw_available: editForm.kw_available.trim(),
        distribution_contract: contractFromFormValue(
          editForm.distribution_contract,
        ),
        distance_meters: editForm.distance_meters.trim()
          ? Number(editForm.distance_meters)
          : null,
        price_per_kwh_extra: editForm.price_per_kwh_extra.trim()
          ? Number(editForm.price_per_kwh_extra)
          : null,
        monthly_price_parking: editForm.monthly_price_parking.trim()
          ? Number(editForm.monthly_price_parking)
          : null,
      };
      const response = await fetch(
        `${apiBase()}/api/marketplace/locations/${editingId}`,
        {
          method: "PUT",
          ...tokenHeaders,
          body: JSON.stringify(payload),
        },
      );
      if (response.status === 401) {
        onLogout();
        return;
      }
      if (!response.ok) throw new Error(t("adminSaveFailed"));
      handleCancelEdit();
      fetchItems();
    } catch (err) {
      setError(err.message || t("adminSaveFailed"));
    }
  };

  const handleToggleStatus = async (row) => {
    setError("");
    let nextStatus = "PUBLISHED";
    if (row.status === "PENDING") nextStatus = "PUBLISHED";
    else if (row.status === "PUBLISHED") nextStatus = "HIDDEN";
    else nextStatus = "PUBLISHED";
    try {
      const response = await fetch(
        `${apiBase()}/api/marketplace/locations/${row.id}`,
        {
          method: "PUT",
          ...tokenHeaders,
          body: JSON.stringify({ status: nextStatus }),
        },
      );
      if (response.status === 401) {
        onLogout();
        return;
      }
      if (!response.ok) throw new Error(t("adminStatusFailed"));
      fetchItems();
    } catch (err) {
      setError(err.message || t("adminStatusFailed"));
    }
  };

  const getStatusActionLabel = (status) => {
    if (status === "PENDING") return t("adminApprove");
    if (status === "PUBLISHED") return t("adminHide");
    return t("adminPublish");
  };

  const handleDelete = async (id) => {
    if (!window.confirm(t("adminDeleteConfirm"))) return;
    setError("");
    try {
      const response = await fetch(
        `${apiBase()}/api/marketplace/locations/${id}`,
        {
          method: "DELETE",
          headers: { token },
        },
      );
      if (response.status === 401) {
        onLogout();
        return;
      }
      if (!response.ok) throw new Error(t("adminDeleteFailed"));
      if (String(editingId) === String(id)) handleCancelEdit();
      fetchItems();
    } catch (err) {
      setError(err.message || t("adminDeleteFailed"));
    }
  };

  return (
    <section className={styles.section}>
      <h2 className={styles.heading}>{t("adminMarketplaceHeading")}</h2>
      <p className={styles.subtitle}>{t("adminMarketplaceSubtitle")}</p>

      {error ? <div className={styles.error}>{error}</div> : null}

      {editingId && editForm ? (
        <div className={styles.editForm}>
          <div className={styles.formRow}>
            <label>
              {t("adminFieldStatus")}
              <select
                name="status"
                value={editForm.status}
                onChange={handleEditChange}
              >
                {MARKETPLACE_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("adminFieldName")}
              <input
                name="name"
                value={editForm.name}
                onChange={handleEditChange}
              />
            </label>
            <label>
              {t("adminFieldPhone")}
              <input
                name="phone"
                value={editForm.phone}
                onChange={handleEditChange}
              />
            </label>
            <label>
              {t("adminFieldKw")}
              <input
                name="kw_available"
                value={editForm.kw_available}
                onChange={handleEditChange}
              />
            </label>
            <label>
              {t("adminFieldContract")}
              <select
                name="distribution_contract"
                value={editForm.distribution_contract}
                onChange={handleEditChange}
              >
                <option value="">—</option>
                <option value="true">{t("adminYes")}</option>
                <option value="false">{t("adminNo")}</option>
              </select>
            </label>
            <label>
              {t("adminFieldDistance")}
              <input
                name="distance_meters"
                value={editForm.distance_meters}
                onChange={handleEditChange}
              />
            </label>
            <label>
              {t("adminFieldExtraKwh")}
              <input
                name="price_per_kwh_extra"
                value={editForm.price_per_kwh_extra}
                onChange={handleEditChange}
              />
            </label>
            <label>
              {t("adminFieldParking")}
              <input
                name="monthly_price_parking"
                value={editForm.monthly_price_parking}
                onChange={handleEditChange}
              />
            </label>
          </div>
          <div className={styles.formActions}>
            <button type="button" onClick={handleSaveEdit}>
              {t("adminSave")}
            </button>
            <button type="button" onClick={handleCancelEdit}>
              {t("adminCancel")}
            </button>
          </div>
        </div>
      ) : null}

      <div className={styles.toolbar}>
        <button type="button" onClick={fetchItems} disabled={loading}>
          {t("adminRefresh")}
        </button>
      </div>

      {loading ? (
        <p>{t("adminLoading")}</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t("adminColType")}</th>
                <th>{t("adminColName")}</th>
                <th>{t("adminColPhone")}</th>
                <th>{t("adminColKw")}</th>
                <th>{t("adminColContract")}</th>
                <th>{t("adminColPoints")}</th>
                <th>{t("adminColPhotos")}</th>
                <th>{t("adminColDistance")}</th>
                <th>{t("adminColExtraKwh")}</th>
                <th>{t("adminColParking")}</th>
                <th>{t("adminColViews")}</th>
                <th>{t("adminColStatus")}</th>
                <th>{t("adminColCreated")}</th>
                <th>{t("adminColActions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={row.id}
                  className={
                    String(editingId) === String(row.id)
                      ? styles.editingRow
                      : undefined
                  }
                >
                  <td>{row.request_type}</td>
                  <td>{row.name}</td>
                  <td>{row.phone}</td>
                  <td>{row.kw_available}</td>
                  <td>
                    {row.distribution_contract == null
                      ? "—"
                      : row.distribution_contract
                        ? t("adminYes")
                        : t("adminNo")}
                  </td>
                  <td>{row.locations?.length ?? 0}</td>
                  <td className={styles.photos}>
                    {[
                      ...(row.parking_photos || []),
                      ...(row.connection_point_photos || []),
                      ...(row.distribution_contract_photos || []),
                    ]
                      .slice(0, 3)
                      .map((url) => (
                        <a
                          key={url}
                          href={resolveAssetUrl(url)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <img src={resolveAssetUrl(url)} alt="" />
                        </a>
                      ))}
                  </td>
                  <td>
                    {row.distance_meters != null
                      ? `${row.distance_meters} m`
                      : "—"}
                  </td>
                  <td>
                    {row.price_per_kwh_extra != null
                      ? `${Number(row.price_per_kwh_extra).toFixed(1)} ₴`
                      : "—"}
                  </td>
                  <td>
                    {row.monthly_price_parking != null
                      ? `${row.monthly_price_parking} ₴`
                      : "—"}
                  </td>
                  <td>{row.view_count ?? 0}</td>
                  <td>{row.status}</td>
                  <td>{formatDate(row.created_on)}</td>
                  <td className={styles.actions}>
                    <button type="button" onClick={() => handleEdit(row)}>
                      {t("adminEdit")}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleToggleStatus(row)}
                    >
                      {getStatusActionLabel(row.status)}
                    </button>
                    <button type="button" onClick={() => handleDelete(row.id)}>
                      {t("adminDelete")}
                    </button>
                  </td>
                </tr>
              ))}
              {items.length === 0 ? (
                <tr>
                  <td colSpan={14}>{t("adminEmpty")}</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
