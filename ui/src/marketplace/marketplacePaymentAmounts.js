export const MARKETPLACE_LOOKING_INFO_AMOUNT_UAH = 99;
export const MARKETPLACE_PROPOSE_INFO_AMOUNT_UAH = 999;

export function infoPaymentAmountUah(requestType) {
  return requestType === 'LOOKING' ? MARKETPLACE_LOOKING_INFO_AMOUNT_UAH : MARKETPLACE_PROPOSE_INFO_AMOUNT_UAH;
}

export const PAYMENT_SUCCESS = 'SUCCESS';
export const PAYMENT_FAILED = new Set(['FAILURE', 'EXPIRED', 'REVERSED']);
