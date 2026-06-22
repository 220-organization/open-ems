import { v4 as uuidv4 } from 'uuid';

const STORAGE_KEY = 'clientId';

function newCompactClientId() {
  return uuidv4().replace(/-/g, '');
}

export function getClientId() {
  if (typeof window === 'undefined') return null;
  try {
    let id = localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = newCompactClientId();
      localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    return newCompactClientId();
  }
}
