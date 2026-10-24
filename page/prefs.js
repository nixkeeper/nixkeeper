// What this browser keeps for the page (localStorage: nothing is sent
// anywhere): read and written, quietly doing without when storage is
// blocked.

export const stored = (key) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage blocked: nothing is remembered
  }
};

export const remember = (key, value) => {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // storage blocked: it lasts until the page is left
  }
};
