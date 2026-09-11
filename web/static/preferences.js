"use strict";

(() => {
  try {
    const root = document.documentElement;
    if (localStorage.getItem("zenitick.theme") === "light") {
      root.dataset.theme = "light";
    }
    if (localStorage.getItem("zenitick.locationVisible") === "true") {
      root.dataset.locationVisible = "true";
    }
  } catch (_) {
    // Storage can be unavailable in hardened/private browser contexts.
  }
})();
