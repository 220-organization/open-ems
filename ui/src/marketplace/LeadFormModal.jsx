import { useRef, useState } from "react";
import MarketplaceModal from "./MarketplaceModal";
import LocationMapPicker from "./LocationMapPicker";
import {
  DISTANCE_METER_OPTIONS,
  buildTelegramUrl,
  buildWhatsAppUrl,
  formatDistanceMeters,
  formatLocationLine,
  formatRegionRadiusKm,
} from "./messengerLinks";
import {
  isMarketplaceApiConfigured,
  resolveMarketplaceAssetUrl,
  submitMarketplaceLocation,
  uploadMarketplaceFile,
} from "./marketplaceApi";
import {
  KW_DEFAULT,
  KW_MAX,
  KW_MIN,
  KW_SLIDER_MAX_INDEX,
  formatKwLabel,
  kwFromSliderIndex,
  sliderIndexFromKw,
} from "./marketplaceKw";
import {
  LANDLORD_LEGAL_FORMS,
  MIN_RENT_YEAR_OPTIONS,
  formatLandlordLegalForm,
  formatMinRentYears,
} from "./marketplaceLease";
const PRICE_KWH_EXTRA_MIN = 0.5;
const PRICE_KWH_EXTRA_MAX = 5;
const PRICE_KWH_EXTRA_STEP = 0.1;
const PRICE_KWH_EXTRA_DEFAULT = 1;
const MONTHLY_PARKING_MIN = 0;
const MONTHLY_PARKING_MAX = 20000;
const MONTHLY_PARKING_STEP = 100;
const MONTHLY_PARKING_DEFAULT = 0;

const formatCount = (value) =>
  Number.isFinite(value)
    ? new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 0 }).format(value)
    : "";

function ChoiceField({ id, label, value, options, error, onChange }) {
  return (
    <fieldset
      id={id}
      className={`marketplace-lead-fieldset${error ? " marketplace-lead-fieldset--error" : ""}`}
    >
      <legend className="marketplace-lead-label">
        {label}
        <span className="marketplace-lead-required">*</span>
      </legend>
      <div
        className="marketplace-lead-options"
        role="radiogroup"
        aria-label={label}
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={value === option.value}
            className={`marketplace-lead-option${value === option.value ? " marketplace-lead-option--active" : ""}`}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {error ? <p className="marketplace-lead-error">{error}</p> : null}
    </fieldset>
  );
}

export default function LeadFormModal({
  t,
  locale,
  open,
  message,
  titleKey,
  formType,
  onClose,
  onPublishSuccess,
}) {
  const [leadName, setLeadName] = useState("");
  const [leadPhone, setLeadPhone] = useState("");
  const [leadKwAvailable, setLeadKwAvailable] = useState(String(KW_DEFAULT));
  const [leadDistributionContract, setLeadDistributionContract] = useState("");
  const [leadLocations, setLeadLocations] = useState([]);
  const [leadParkingPhotos, setLeadParkingPhotos] = useState([]);
  const [leadConnectionPhotos, setLeadConnectionPhotos] = useState([]);
  const [leadDistributionContractPhotos, setLeadDistributionContractPhotos] =
    useState([]);
  const [leadDistanceMeters, setLeadDistanceMeters] = useState("");
  const [leadPriceKwhExtra, setLeadPriceKwhExtra] = useState(
    PRICE_KWH_EXTRA_DEFAULT,
  );
  const [leadMonthlyParkingPrice, setLeadMonthlyParkingPrice] = useState(
    MONTHLY_PARKING_DEFAULT,
  );
  const [leadMinRentYears, setLeadMinRentYears] = useState("");
  const [leadRestroomCoffee, setLeadRestroomCoffee] = useState("");
  const [leadMoreStations, setLeadMoreStations] = useState("");
  const [leadParkingSpacesNow, setLeadParkingSpacesNow] = useState("");
  const [leadParkingSpacesFuture, setLeadParkingSpacesFuture] = useState("");
  const [leadLandlord, setLeadLandlord] = useState("");
  const [leadPhotoUploading, setLeadPhotoUploading] = useState(false);
  const [leadPhotoError, setLeadPhotoError] = useState("");
  const [leadFormErrors, setLeadFormErrors] = useState({});
  const [marketplacePublishing, setMarketplacePublishing] = useState(false);

  const leadNameInputRef = useRef(null);
  const leadPhoneInputRef = useRef(null);

  const isLocationLeadForm =
    formType === "proposeLocation" || formType === "lookingForLocation";
  const showMarketplacePublish =
    isLocationLeadForm && isMarketplaceApiConfigured();
  const showMessengerChannels = !isLocationLeadForm || !showMarketplacePublish;

  const resetForm = () => {
    setLeadName("");
    setLeadPhone("");
    setLeadKwAvailable(String(KW_DEFAULT));
    setLeadDistributionContract("");
    setLeadLocations([]);
    setLeadParkingPhotos([]);
    setLeadConnectionPhotos([]);
    setLeadDistributionContractPhotos([]);
    setLeadDistanceMeters("");
    setLeadPriceKwhExtra(PRICE_KWH_EXTRA_DEFAULT);
    setLeadMonthlyParkingPrice(MONTHLY_PARKING_DEFAULT);
    setLeadMinRentYears("");
    setLeadRestroomCoffee("");
    setLeadMoreStations("");
    setLeadParkingSpacesNow("");
    setLeadParkingSpacesFuture("");
    setLeadLandlord("");
    setLeadPhotoUploading(false);
    setLeadPhotoError("");
    setLeadFormErrors({});
    setMarketplacePublishing(false);
  };

  const handleClose = () => {
    resetForm();
    onClose?.();
  };

  const buildLeadContactSuffix = () => {
    const n = (leadNameInputRef.current?.value ?? leadName).trim();
    const p = (leadPhoneInputRef.current?.value ?? leadPhone).trim();
    const lines = [];
    if (n) lines.push(`${t("marketplaceLeadFormNameLabel")}: ${n}`);
    if (p) lines.push(`${t("marketplaceLeadFormPhoneLabel")}: ${p}`);
    if (isLocationLeadForm) {
      if (leadKwAvailable)
        lines.push(
          `${t("marketplaceLeadFormKwLabel")}: ${formatKwLabel(leadKwAvailable)}`,
        );
      if (formType === "proposeLocation" && leadDistributionContract) {
        const distributionValue =
          leadDistributionContract === "yes"
            ? t("marketplaceLeadFormYes")
            : t("marketplaceLeadFormNo");
        lines.push(
          `${t("marketplaceLeadFormDistributionLabel")}: ${distributionValue}`,
        );
      }
      if (leadLocations.length) {
        const locationsLabelKey =
          formType === "lookingForLocation"
            ? "marketplaceLeadFormRegionLabel"
            : "marketplaceLeadFormLocationsLabel";
        const locationLines = leadLocations.map((loc, index) => {
          let line = formatLocationLine(index, loc.label, loc.lat, loc.lng);
          if (loc.radius_km != null) {
            line += `\n${t("marketplaceLeadFormRegionRadiusLabel")}: ${formatRegionRadiusKm(loc.radius_km, t)}`;
          }
          return line;
        });
        lines.push(`${t(locationsLabelKey)}:\n${locationLines.join("\n")}`);
      }
      if (leadParkingPhotos.length) {
        lines.push(
          `${t("marketplaceLeadFormParkingPhotosLabel")}:\n${leadParkingPhotos.join("\n")}`,
        );
      }
      if (leadConnectionPhotos.length) {
        lines.push(
          `${t("marketplaceLeadFormConnectionPhotosLabel")}:\n${leadConnectionPhotos.join("\n")}`,
        );
      }
      if (leadDistributionContractPhotos.length) {
        lines.push(
          `${t("marketplaceLeadFormDistributionContractPhotosLabel")}:\n${leadDistributionContractPhotos.join("\n")}`,
        );
      }
      if (leadDistanceMeters) {
        lines.push(
          `${t("marketplaceLeadFormDistanceLabel")}: ${formatDistanceMeters(leadDistanceMeters, t)}`,
        );
      }
      if (formType === "proposeLocation") {
        lines.push(
          `${t("marketplaceLeadFormPriceKwhExtraLabel")}: ${leadPriceKwhExtra.toFixed(1)} ₴`,
        );
        lines.push(
          `${t("marketplaceLeadFormMonthlyParkingLabel")}: ${formatCount(leadMonthlyParkingPrice)} ₴`,
        );
        if (leadMinRentYears) {
          lines.push(
            `${t("marketplaceLeadFormMinRentLabel")}: ${formatMinRentYears(leadMinRentYears, t)}`,
          );
        }
        if (leadRestroomCoffee) {
          lines.push(
            `${t("marketplaceLeadFormRestroomCoffeeLabel")}: ${leadRestroomCoffee === "yes" ? t("marketplaceLeadFormYes") : t("marketplaceLeadFormNo")}`,
          );
        }
        if (leadMoreStations) {
          lines.push(
            `${t("marketplaceLeadFormMoreStationsLabel")}: ${leadMoreStations === "yes" ? t("marketplaceLeadFormYes") : t("marketplaceLeadFormNo")}`,
          );
        }
        if (leadParkingSpacesNow) {
          lines.push(
            `${t("marketplaceLeadFormParkingSpacesNowLabel")}: ${leadParkingSpacesNow}`,
          );
        }
        if (leadParkingSpacesFuture) {
          lines.push(
            `${t("marketplaceLeadFormParkingSpacesFutureLabel")}: ${leadParkingSpacesFuture}`,
          );
        }
        if (leadLandlord) {
          lines.push(
            `${t("marketplaceLeadFormLandlordLabel")}: ${formatLandlordLegalForm(leadLandlord, t)}`,
          );
        }
      }
    }
    return lines.length ? `\n\n${lines.join("\n")}` : "";
  };

  const validateLeadForm = () => {
    const name = (leadNameInputRef.current?.value ?? leadName).trim();
    const phone = (leadPhoneInputRef.current?.value ?? leadPhone).trim();
    const errors = {};
    if (!name) errors.name = t("marketplaceLeadFormRequired");
    if (!phone) errors.phone = t("marketplaceLeadFormRequired");
    if (isLocationLeadForm) {
      if (!leadKwAvailable) errors.kw = t("marketplaceLeadFormRequired");
      if (formType === "proposeLocation" && !leadDistributionContract) {
        errors.distribution = t("marketplaceLeadFormRequired");
      }
      if (!leadLocations.length) {
        errors.locations = t(
          formType === "lookingForLocation"
            ? "marketplaceLeadFormRegionRequired"
            : "marketplaceLeadFormLocationsRequired",
        );
      }
      if (formType === "proposeLocation") {
        if (!leadParkingPhotos.length) {
          errors.parkingPhotos = t("marketplaceLeadFormRequired");
        }
        if (!leadMinRentYears)
          errors.minRent = t("marketplaceLeadFormRequired");
        if (!leadRestroomCoffee)
          errors.restroomCoffee = t("marketplaceLeadFormRequired");
        if (!leadMoreStations)
          errors.moreStations = t("marketplaceLeadFormRequired");
        const spacesNow = Number.parseInt(leadParkingSpacesNow, 10);
        const spacesFuture = Number.parseInt(leadParkingSpacesFuture, 10);
        if (!Number.isFinite(spacesNow) || spacesNow < 1) {
          errors.parkingNow = t("marketplaceLeadFormRequired");
        }
        if (!Number.isFinite(spacesFuture) || spacesFuture < 1) {
          errors.parkingFuture = t("marketplaceLeadFormRequired");
        } else if (Number.isFinite(spacesNow) && spacesFuture < spacesNow) {
          errors.parkingFuture = t("marketplaceLeadFormParkingFutureTooSmall");
        }
        if (!leadLandlord) errors.landlord = t("marketplaceLeadFormRequired");
      }
    }
    return errors;
  };

  const buildFullLeadMessage = () =>
    `${message || ""}${buildLeadContactSuffix()}`;

  const scrollToFirstLeadFormError = (errors) => {
    const order = [
      "name",
      "phone",
      "kw",
      "distribution",
      "locations",
      "parkingPhotos",
      "minRent",
      "restroomCoffee",
      "moreStations",
      "parkingNow",
      "parkingFuture",
      "landlord",
    ];
    const targetKey = order.find((key) => errors[key]);
    const targetId =
      targetKey === "name"
        ? "marketplace-lead-name"
        : targetKey === "phone"
          ? "marketplace-lead-phone"
          : targetKey === "kw"
            ? "marketplace-lead-kw"
            : targetKey === "distribution"
              ? "marketplace-lead-distribution"
              : targetKey === "locations"
                ? "marketplace-lead-locations"
                : targetKey === "parkingPhotos"
                  ? "marketplace-lead-parking-photos-field"
                  : targetKey === "minRent"
                    ? "marketplace-lead-min-rent"
                    : targetKey === "restroomCoffee"
                      ? "marketplace-lead-restroom-coffee"
                      : targetKey === "moreStations"
                        ? "marketplace-lead-more-stations"
                        : targetKey === "parkingNow"
                          ? "marketplace-lead-parking-now"
                          : targetKey === "parkingFuture"
                            ? "marketplace-lead-parking-future"
                            : targetKey === "landlord"
                              ? "marketplace-lead-landlord"
                              : null;
    if (!targetId) return;
    document
      .getElementById(targetId)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const uploadLeadPhotos = async (files, setter) => {
    const fileList = Array.from(files || []);
    if (!fileList.length) return;
    setLeadPhotoUploading(true);
    setLeadPhotoError("");
    try {
      const uploaded = [];
      for (const file of fileList) {
        const url = await uploadMarketplaceFile(file);
        if (url) uploaded.push(url);
      }
      if (uploaded.length) {
        setter((prev) => [...prev, ...uploaded]);
        if (setter === setLeadParkingPhotos) {
          setLeadFormErrors((prev) => {
            if (!prev.parkingPhotos) return prev;
            const next = { ...prev };
            delete next.parkingPhotos;
            return next;
          });
        }
      }
      if (!uploaded.length) {
        setLeadPhotoError(t("marketplaceLeadFormPhotoUploadError"));
      }
    } catch {
      setLeadPhotoError(t("marketplaceLeadFormPhotoUploadError"));
    } finally {
      setLeadPhotoUploading(false);
    }
  };

  const buildMarketplaceSubmissionPayload = (messenger) => {
    const name = (leadNameInputRef.current?.value ?? leadName).trim();
    const phone = (leadPhoneInputRef.current?.value ?? leadPhone).trim();
    return {
      request_type: formType === "proposeLocation" ? "PROPOSE" : "LOOKING",
      name,
      phone,
      kw_available: leadKwAvailable,
      distribution_contract:
        formType === "proposeLocation"
          ? leadDistributionContract === "yes"
          : null,
      messenger,
      locations: leadLocations.map(({ label, lat, lng, radius_km, bbox }) => ({
        label,
        lat,
        lng,
        ...(radius_km != null ? { radius_km } : {}),
        ...(bbox ? { bbox } : {}),
      })),
      parking_photos: leadParkingPhotos,
      connection_point_photos: leadConnectionPhotos,
      distribution_contract_photos: leadDistributionContractPhotos,
      distance_meters: leadDistanceMeters
        ? Number.parseInt(leadDistanceMeters, 10)
        : null,
      price_per_kwh_extra:
        formType === "proposeLocation" ? leadPriceKwhExtra : null,
      monthly_price_parking:
        formType === "proposeLocation" ? leadMonthlyParkingPrice : null,
      min_rent_years: formType === "proposeLocation" ? leadMinRentYears : null,
      restroom_coffee_nearby:
        formType === "proposeLocation" ? leadRestroomCoffee === "yes" : null,
      more_stations_possible:
        formType === "proposeLocation" ? leadMoreStations === "yes" : null,
      parking_spaces_now:
        formType === "proposeLocation"
          ? Number.parseInt(leadParkingSpacesNow, 10)
          : null,
      parking_spaces_future:
        formType === "proposeLocation"
          ? Number.parseInt(leadParkingSpacesFuture, 10)
          : null,
      landlord_legal_form: formType === "proposeLocation" ? leadLandlord : null,
    };
  };

  const pickMessenger = async (channel) => {
    if (!message) return;
    const errors = validateLeadForm();
    if (Object.keys(errors).length) {
      setLeadFormErrors(errors);
      scrollToFirstLeadFormError(errors);
      return;
    }
    setLeadFormErrors({});
    const fullMessage = buildFullLeadMessage();
    if (isLocationLeadForm) {
      try {
        await submitMarketplaceLocation(
          buildMarketplaceSubmissionPayload(channel),
        );
      } catch {
        /* best-effort */
      }
    }
    const url =
      channel === "telegram"
        ? buildTelegramUrl(fullMessage)
        : buildWhatsAppUrl(fullMessage);
    window.open(url, "_blank");
    handleClose();
  };

  const publishToMarketplace = async () => {
    if (!message || marketplacePublishing) return;
    const errors = validateLeadForm();
    if (Object.keys(errors).length) {
      setLeadFormErrors(errors);
      scrollToFirstLeadFormError(errors);
      return;
    }
    setLeadFormErrors({});
    setMarketplacePublishing(true);
    try {
      await submitMarketplaceLocation(
        buildMarketplaceSubmissionPayload("marketplace"),
      );
      onPublishSuccess?.();
    } catch {
      setLeadFormErrors({ submit: t("marketplaceMessengerPublishError") });
    } finally {
      setMarketplacePublishing(false);
    }
  };

  return (
    <MarketplaceModal
      open={open}
      onClose={handleClose}
      ariaLabel={t(titleKey)}
      closeAriaLabel={t("marketplaceClose")}
    >
      <div
        className={`marketplace-lead-modal${isLocationLeadForm ? " marketplace-lead-modal--wide" : ""}`}
        aria-labelledby="marketplace-lead-title"
      >
        <p id="marketplace-lead-title" className="marketplace-lead-title">
          {t(titleKey)}
        </p>

        <div className="marketplace-lead-fields">
          <label
            className="marketplace-lead-label"
            htmlFor="marketplace-lead-name"
          >
            {t("marketplaceLeadFormNameLabel")}
            <span className="marketplace-lead-required">*</span>
          </label>
          <input
            id="marketplace-lead-name"
            ref={leadNameInputRef}
            className={`marketplace-lead-input${leadFormErrors.name ? " marketplace-lead-input--error" : ""}`}
            type="text"
            autoComplete="name"
            value={leadName}
            onChange={(e) => {
              setLeadName(e.target.value);
              if (leadFormErrors.name) {
                setLeadFormErrors((prev) => {
                  const next = { ...prev };
                  delete next.name;
                  return next;
                });
              }
            }}
            placeholder={t("marketplaceLeadFormNamePlaceholder")}
          />
          {leadFormErrors.name ? (
            <p className="marketplace-lead-error">{leadFormErrors.name}</p>
          ) : null}

          <label
            className="marketplace-lead-label"
            htmlFor="marketplace-lead-phone"
          >
            {t("marketplaceLeadFormPhoneLabel")}
            <span className="marketplace-lead-required">*</span>
          </label>
          <input
            id="marketplace-lead-phone"
            ref={leadPhoneInputRef}
            className={`marketplace-lead-input${leadFormErrors.phone ? " marketplace-lead-input--error" : ""}`}
            type="tel"
            autoComplete="tel"
            inputMode="tel"
            value={leadPhone}
            onChange={(e) => {
              setLeadPhone(e.target.value);
              if (leadFormErrors.phone) {
                setLeadFormErrors((prev) => {
                  const next = { ...prev };
                  delete next.phone;
                  return next;
                });
              }
            }}
            placeholder={t("marketplaceLeadFormPhonePlaceholder")}
          />
          {leadFormErrors.phone ? (
            <p className="marketplace-lead-error">{leadFormErrors.phone}</p>
          ) : null}

          {isLocationLeadForm ? (
            <>
              <fieldset
                id="marketplace-lead-kw"
                className={`marketplace-lead-fieldset${leadFormErrors.kw ? " marketplace-lead-fieldset--error" : ""}`}
              >
                <legend className="marketplace-lead-label">
                  {t("marketplaceLeadFormKwLabel")}
                  <span className="marketplace-lead-required">*</span>
                </legend>
                <label
                  className="marketplace-lead-slider-header"
                  htmlFor="marketplace-lead-kw-slider"
                >
                  <span className="marketplace-lead-slider-value">
                    {formatKwLabel(leadKwAvailable || KW_DEFAULT)}
                  </span>
                </label>
                <input
                  id="marketplace-lead-kw-slider"
                  className="marketplace-lead-slider"
                  type="range"
                  min={0}
                  max={KW_SLIDER_MAX_INDEX}
                  step={1}
                  value={sliderIndexFromKw(leadKwAvailable)}
                  aria-label={t("marketplaceLeadFormKwLabel")}
                  aria-valuemin={KW_MIN}
                  aria-valuemax={KW_MAX}
                  aria-valuenow={kwFromSliderIndex(
                    sliderIndexFromKw(leadKwAvailable),
                  )}
                  aria-valuetext={formatKwLabel(leadKwAvailable || KW_DEFAULT)}
                  onChange={(e) => {
                    setLeadKwAvailable(
                      String(kwFromSliderIndex(e.target.value)),
                    );
                    if (leadFormErrors.kw) {
                      setLeadFormErrors((prev) => {
                        const next = { ...prev };
                        delete next.kw;
                        return next;
                      });
                    }
                  }}
                />
                <div className="marketplace-lead-slider-scale">
                  <span>{formatKwLabel(KW_MIN)}</span>
                  <span>{formatKwLabel(KW_MAX)}</span>
                </div>
                {leadFormErrors.kw ? (
                  <p className="marketplace-lead-error">{leadFormErrors.kw}</p>
                ) : null}
              </fieldset>

              {formType === "proposeLocation" ? (
                <fieldset
                  id="marketplace-lead-distribution"
                  className={`marketplace-lead-fieldset${leadFormErrors.distribution ? " marketplace-lead-fieldset--error" : ""}`}
                >
                  <legend className="marketplace-lead-label">
                    {t("marketplaceLeadFormDistributionLabel")}
                    <span className="marketplace-lead-required">*</span>
                  </legend>
                  <div
                    className="marketplace-lead-options"
                    role="radiogroup"
                    aria-label={t("marketplaceLeadFormDistributionLabel")}
                  >
                    {[
                      { value: "yes", label: t("marketplaceLeadFormYes") },
                      { value: "no", label: t("marketplaceLeadFormNo") },
                    ].map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        role="radio"
                        aria-checked={leadDistributionContract === option.value}
                        className={`marketplace-lead-option${leadDistributionContract === option.value ? " marketplace-lead-option--active" : ""}`}
                        onClick={() => {
                          setLeadDistributionContract(option.value);
                          if (leadFormErrors.distribution) {
                            setLeadFormErrors((prev) => {
                              const next = { ...prev };
                              delete next.distribution;
                              return next;
                            });
                          }
                        }}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                  {leadFormErrors.distribution ? (
                    <p className="marketplace-lead-error">
                      {leadFormErrors.distribution}
                    </p>
                  ) : null}
                </fieldset>
              ) : null}

              <div
                id="marketplace-lead-locations"
                className={`marketplace-lead-fieldset${leadFormErrors.locations ? " marketplace-lead-fieldset--error" : ""}`}
              >
                <span className="marketplace-lead-label">
                  {t(
                    formType === "lookingForLocation"
                      ? "marketplaceLeadFormRegionLabel"
                      : "marketplaceLeadFormLocationsLabel",
                  )}
                  <span className="marketplace-lead-required">*</span>
                </span>
                <LocationMapPicker
                  t={t}
                  locale={locale}
                  selectionMode={
                    formType === "lookingForLocation" ? "region" : "point"
                  }
                  locations={leadLocations}
                  onChange={(nextLocations) => {
                    setLeadLocations(nextLocations);
                    if (leadFormErrors.locations && nextLocations.length) {
                      setLeadFormErrors((prev) => {
                        const next = { ...prev };
                        delete next.locations;
                        return next;
                      });
                    }
                  }}
                />
                {leadFormErrors.locations ? (
                  <p className="marketplace-lead-error">
                    {leadFormErrors.locations}
                  </p>
                ) : null}
              </div>

              {formType === "proposeLocation" ? (
                <>
                  <div
                    id="marketplace-lead-parking-photos-field"
                    className={`marketplace-lead-fieldset${leadFormErrors.parkingPhotos ? " marketplace-lead-fieldset--error" : ""}`}
                  >
                    <label
                      className="marketplace-lead-label"
                      htmlFor="marketplace-lead-parking-photos"
                    >
                      {t("marketplaceLeadFormParkingPhotosLabel")}
                      <span className="marketplace-lead-required">*</span>
                    </label>
                    <input
                      id="marketplace-lead-parking-photos"
                      type="file"
                      accept="image/*"
                      multiple
                      disabled={leadPhotoUploading}
                      onChange={(e) => {
                        uploadLeadPhotos(e.target.files, setLeadParkingPhotos);
                        e.target.value = "";
                      }}
                    />
                    {leadParkingPhotos.length ? (
                      <div className="marketplace-lead-photo-row">
                        {leadParkingPhotos.map((url) => (
                          <div
                            key={url}
                            className="marketplace-lead-photo-item"
                          >
                            <img
                              src={resolveMarketplaceAssetUrl(url)}
                              alt=""
                              className="marketplace-lead-photo-img"
                            />
                            <button
                              type="button"
                              className="marketplace-lead-photo-remove"
                              onClick={() =>
                                setLeadParkingPhotos((prev) =>
                                  prev.filter((item) => item !== url),
                                )
                              }
                            >
                              ×
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {leadFormErrors.parkingPhotos ? (
                      <p className="marketplace-lead-error">
                        {leadFormErrors.parkingPhotos}
                      </p>
                    ) : null}
                  </div>

                  <div className="marketplace-lead-fieldset">
                    <label
                      className="marketplace-lead-label"
                      htmlFor="marketplace-lead-connection-photos"
                    >
                      {t("marketplaceLeadFormConnectionPhotosLabel")}
                    </label>
                    <input
                      id="marketplace-lead-connection-photos"
                      type="file"
                      accept="image/jpeg,image/png,image/webp,image/*"
                      multiple
                      disabled={leadPhotoUploading}
                      onChange={(e) => {
                        uploadLeadPhotos(
                          e.target.files,
                          setLeadConnectionPhotos,
                        );
                        e.target.value = "";
                      }}
                    />
                    {leadConnectionPhotos.length ? (
                      <div className="marketplace-lead-photo-row">
                        {leadConnectionPhotos.map((url) => (
                          <div
                            key={url}
                            className="marketplace-lead-photo-item"
                          >
                            <img
                              src={resolveMarketplaceAssetUrl(url)}
                              alt=""
                              className="marketplace-lead-photo-img"
                            />
                            <button
                              type="button"
                              className="marketplace-lead-photo-remove"
                              onClick={() =>
                                setLeadConnectionPhotos((prev) =>
                                  prev.filter((item) => item !== url),
                                )
                              }
                            >
                              ×
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="marketplace-lead-fieldset">
                    <label
                      className="marketplace-lead-label"
                      htmlFor="marketplace-lead-distribution-contract-photos"
                    >
                      {t("marketplaceLeadFormDistributionContractPhotosLabel")}
                    </label>
                    <input
                      id="marketplace-lead-distribution-contract-photos"
                      type="file"
                      accept="image/jpeg,image/png,image/webp,image/*"
                      multiple
                      disabled={leadPhotoUploading}
                      onChange={(e) => {
                        uploadLeadPhotos(
                          e.target.files,
                          setLeadDistributionContractPhotos,
                        );
                        e.target.value = "";
                      }}
                    />
                    {leadDistributionContractPhotos.length ? (
                      <div className="marketplace-lead-photo-row">
                        {leadDistributionContractPhotos.map((url) => (
                          <div
                            key={url}
                            className="marketplace-lead-photo-item"
                          >
                            <img
                              src={resolveMarketplaceAssetUrl(url)}
                              alt=""
                              className="marketplace-lead-photo-img"
                            />
                            <button
                              type="button"
                              className="marketplace-lead-photo-remove"
                              onClick={() =>
                                setLeadDistributionContractPhotos((prev) =>
                                  prev.filter((item) => item !== url),
                                )
                              }
                            >
                              ×
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  {leadPhotoError ? (
                    <p className="marketplace-lead-error">{leadPhotoError}</p>
                  ) : null}

                  <label
                    className="marketplace-lead-label"
                    htmlFor="marketplace-lead-distance"
                  >
                    {t("marketplaceLeadFormDistanceLabel")}
                  </label>
                  <select
                    id="marketplace-lead-distance"
                    className="marketplace-lead-input"
                    value={leadDistanceMeters}
                    onChange={(e) => setLeadDistanceMeters(e.target.value)}
                  >
                    <option value="">
                      {t("marketplaceLeadFormDistancePlaceholder")}
                    </option>
                    {DISTANCE_METER_OPTIONS.map((option) => (
                      <option key={option} value={String(option)}>
                        {formatDistanceMeters(option, t)}
                      </option>
                    ))}
                  </select>

                  <div className="marketplace-lead-fieldset">
                    <label
                      className="marketplace-lead-slider-header"
                      htmlFor="marketplace-lead-price-kwh"
                    >
                      <span className="marketplace-lead-label">
                        {t("marketplaceLeadFormPriceKwhExtraLabel")}
                      </span>
                      <span className="marketplace-lead-slider-value">
                        {leadPriceKwhExtra.toFixed(1)} ₴
                      </span>
                    </label>
                    <input
                      id="marketplace-lead-price-kwh"
                      className="marketplace-lead-slider"
                      type="range"
                      min={PRICE_KWH_EXTRA_MIN}
                      max={PRICE_KWH_EXTRA_MAX}
                      step={PRICE_KWH_EXTRA_STEP}
                      value={leadPriceKwhExtra}
                      onChange={(e) =>
                        setLeadPriceKwhExtra(Number.parseFloat(e.target.value))
                      }
                    />
                    <div className="marketplace-lead-slider-scale">
                      <span>{PRICE_KWH_EXTRA_MIN.toFixed(1)} ₴</span>
                      <span>{PRICE_KWH_EXTRA_MAX.toFixed(1)} ₴</span>
                    </div>
                  </div>

                  <ChoiceField
                    id="marketplace-lead-min-rent"
                    label={t("marketplaceLeadFormMinRentLabel")}
                    value={leadMinRentYears}
                    error={leadFormErrors.minRent}
                    options={MIN_RENT_YEAR_OPTIONS.map((value) => ({
                      value,
                      label: formatMinRentYears(value, t),
                    }))}
                    onChange={(value) => {
                      setLeadMinRentYears(value);
                      if (leadFormErrors.minRent) {
                        setLeadFormErrors((prev) => {
                          const next = { ...prev };
                          delete next.minRent;
                          return next;
                        });
                      }
                    }}
                  />

                  <ChoiceField
                    id="marketplace-lead-restroom-coffee"
                    label={t("marketplaceLeadFormRestroomCoffeeLabel")}
                    value={leadRestroomCoffee}
                    error={leadFormErrors.restroomCoffee}
                    options={[
                      { value: "yes", label: t("marketplaceLeadFormYes") },
                      { value: "no", label: t("marketplaceLeadFormNo") },
                    ]}
                    onChange={(value) => {
                      setLeadRestroomCoffee(value);
                      if (leadFormErrors.restroomCoffee) {
                        setLeadFormErrors((prev) => {
                          const next = { ...prev };
                          delete next.restroomCoffee;
                          return next;
                        });
                      }
                    }}
                  />

                  <ChoiceField
                    id="marketplace-lead-more-stations"
                    label={t("marketplaceLeadFormMoreStationsLabel")}
                    value={leadMoreStations}
                    error={leadFormErrors.moreStations}
                    options={[
                      { value: "yes", label: t("marketplaceLeadFormYes") },
                      { value: "no", label: t("marketplaceLeadFormNo") },
                    ]}
                    onChange={(value) => {
                      setLeadMoreStations(value);
                      if (leadFormErrors.moreStations) {
                        setLeadFormErrors((prev) => {
                          const next = { ...prev };
                          delete next.moreStations;
                          return next;
                        });
                      }
                    }}
                  />

                  <div className="marketplace-lead-fieldset">
                    <label
                      className="marketplace-lead-slider-header"
                      htmlFor="marketplace-lead-monthly-parking"
                    >
                      <span className="marketplace-lead-label">
                        {t("marketplaceLeadFormMonthlyParkingLabel")}
                      </span>
                      <span className="marketplace-lead-slider-value">
                        {formatCount(leadMonthlyParkingPrice)} ₴
                      </span>
                    </label>
                    <input
                      id="marketplace-lead-monthly-parking"
                      className="marketplace-lead-slider"
                      type="range"
                      min={MONTHLY_PARKING_MIN}
                      max={MONTHLY_PARKING_MAX}
                      step={MONTHLY_PARKING_STEP}
                      value={leadMonthlyParkingPrice}
                      onChange={(e) =>
                        setLeadMonthlyParkingPrice(
                          Number.parseInt(e.target.value, 10),
                        )
                      }
                    />
                    <div className="marketplace-lead-slider-scale">
                      <span>{formatCount(MONTHLY_PARKING_MIN)} ₴</span>
                      <span>{formatCount(MONTHLY_PARKING_MAX)} ₴</span>
                    </div>
                  </div>

                  <label
                    className="marketplace-lead-label"
                    htmlFor="marketplace-lead-parking-now"
                  >
                    {t("marketplaceLeadFormParkingSpacesNowLabel")}
                    <span className="marketplace-lead-required">*</span>
                  </label>
                  <input
                    id="marketplace-lead-parking-now"
                    className={`marketplace-lead-input${leadFormErrors.parkingNow ? " marketplace-lead-input--error" : ""}`}
                    type="number"
                    min={1}
                    step={1}
                    inputMode="numeric"
                    value={leadParkingSpacesNow}
                    onChange={(e) => {
                      setLeadParkingSpacesNow(e.target.value);
                      if (leadFormErrors.parkingNow) {
                        setLeadFormErrors((prev) => {
                          const next = { ...prev };
                          delete next.parkingNow;
                          return next;
                        });
                      }
                    }}
                  />
                  {leadFormErrors.parkingNow ? (
                    <p className="marketplace-lead-error">
                      {leadFormErrors.parkingNow}
                    </p>
                  ) : null}

                  <label
                    className="marketplace-lead-label"
                    htmlFor="marketplace-lead-parking-future"
                  >
                    {t("marketplaceLeadFormParkingSpacesFutureLabel")}
                    <span className="marketplace-lead-required">*</span>
                  </label>
                  <input
                    id="marketplace-lead-parking-future"
                    className={`marketplace-lead-input${leadFormErrors.parkingFuture ? " marketplace-lead-input--error" : ""}`}
                    type="number"
                    min={1}
                    step={1}
                    inputMode="numeric"
                    value={leadParkingSpacesFuture}
                    onChange={(e) => {
                      setLeadParkingSpacesFuture(e.target.value);
                      if (leadFormErrors.parkingFuture) {
                        setLeadFormErrors((prev) => {
                          const next = { ...prev };
                          delete next.parkingFuture;
                          return next;
                        });
                      }
                    }}
                  />
                  {leadFormErrors.parkingFuture ? (
                    <p className="marketplace-lead-error">
                      {leadFormErrors.parkingFuture}
                    </p>
                  ) : null}

                  <ChoiceField
                    id="marketplace-lead-landlord"
                    label={t("marketplaceLeadFormLandlordLabel")}
                    value={leadLandlord}
                    error={leadFormErrors.landlord}
                    options={LANDLORD_LEGAL_FORMS.map((value) => ({
                      value,
                      label: formatLandlordLegalForm(value, t),
                    }))}
                    onChange={(value) => {
                      setLeadLandlord(value);
                      if (leadFormErrors.landlord) {
                        setLeadFormErrors((prev) => {
                          const next = { ...prev };
                          delete next.landlord;
                          return next;
                        });
                      }
                    }}
                  />
                </>
              ) : null}
            </>
          ) : null}
        </div>

        <div className="marketplace-lead-preview" aria-live="polite">
          <p className="marketplace-lead-preview-label">
            {t("marketplaceLeadFormMessagePreview")}
          </p>
          <pre className="marketplace-lead-preview-text">
            {buildFullLeadMessage()}
          </pre>
        </div>

        {leadFormErrors.submit ? (
          <p className="marketplace-lead-submit-error" role="alert">
            {leadFormErrors.submit}
          </p>
        ) : Object.keys(leadFormErrors).length ? (
          <p className="marketplace-lead-submit-error" role="alert">
            {t("marketplaceLeadFormSubmitError")}
          </p>
        ) : null}

        {isLocationLeadForm && showMarketplacePublish ? (
          <p className="marketplace-lead-hint">
            {t("marketplaceLeadFormPublishHint")}
          </p>
        ) : showMessengerChannels ? (
          <p className="marketplace-lead-hint">
            {t("marketplaceLeadFormMessengerHint")}
          </p>
        ) : null}

        {showMessengerChannels ? (
          <div className="marketplace-messenger-actions">
            <button
              type="button"
              className="marketplace-messenger-btn marketplace-messenger-btn--telegram"
              onClick={() => pickMessenger("telegram")}
            >
              {t("marketplaceMessengerTelegram")}
            </button>
            <button
              type="button"
              className="marketplace-messenger-btn marketplace-messenger-btn--whatsapp"
              onClick={() => pickMessenger("whatsapp")}
            >
              {t("marketplaceMessengerWhatsApp")}
            </button>
          </div>
        ) : null}

        {showMarketplacePublish ? (
          <button
            type="button"
            className="landing-btn landing-btn--primary marketplace-publish-btn"
            onClick={publishToMarketplace}
            disabled={marketplacePublishing}
          >
            {marketplacePublishing
              ? t("marketplaceLeadFormMapLoading")
              : t("marketplaceMessengerPublish")}
          </button>
        ) : null}
      </div>
    </MarketplaceModal>
  );
}
