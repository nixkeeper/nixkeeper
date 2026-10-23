// Applies the saved theme before the page draws, so it doesn't flash the
// default one first: loaded by index.html's <head>, before the styles. The
// same rule as logic.js's themeFor (the visitor's choice, then the page's
// default, then classic and the system's light or dark), which app.js uses
// for the Theme menu; unknown values match no style, so this one doesn't
// check them.
{
  const root = document.documentElement;
  try {
    const palette =
      localStorage.getItem('nixkeeper-palette') ||
      localStorage.getItem(`nixkeeper-site-palette:${location.pathname}`);
    const mode = localStorage.getItem('nixkeeper-mode');
    if (palette) root.dataset.palette = palette;
    if (mode) root.dataset.mode = mode;
  } catch {
    // Storage blocked (a private window, say): the defaults.
  }
}
// And which skeleton shows while the data loads (index.html): the overview's
// for the address with nothing after it (nixkeeper.com's first page), a
// list's for any other. app.js switches to a list's once index.json says
// this instance lists its own packages, whose first page is a list.
document.documentElement.dataset.start = location.search ? 'list' : 'overview';
