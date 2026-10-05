export const MIN_RENT_YEAR_OPTIONS = ["1", "2", "3", "5", "5+"];
export const LANDLORD_LEGAL_FORMS = ["FOP", "TOV"];

const MIN_RENT_LABEL_KEYS = {
  1: "marketplaceLeadFormMinRent1",
  2: "marketplaceLeadFormMinRent2",
  3: "marketplaceLeadFormMinRent3",
  5: "marketplaceLeadFormMinRent5",
  "5+": "marketplaceLeadFormMinRent5Plus",
};

export function formatMinRentYears(value, t) {
  const key = MIN_RENT_LABEL_KEYS[String(value)];
  return key ? t(key) : String(value ?? "");
}

export function formatLandlordLegalForm(value, t) {
  if (value === "FOP") return t("marketplaceLeadFormLandlordFop");
  if (value === "TOV") return t("marketplaceLeadFormLandlordTov");
  return "";
}
