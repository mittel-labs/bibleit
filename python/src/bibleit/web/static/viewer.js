const verses = document.getElementById("verses");
const status = document.getElementById("status");
const fontSize = document.getElementById("font-size");
const historyToggle = document.getElementById("history-toggle");
const historyPanel = document.getElementById("history-panel");
const presentation = document.getElementById("presentation");
const translationFilter = document.getElementById("translation-filter");
const translationFilterLabel = document.getElementById("translation-filter-label");
const translationFilterOptions = document.getElementById("translation-filter-options");
const theme = document.getElementById("theme");
const live = document.getElementById("live");
const splashStatus = document.getElementById("splash-status");
const splashQr = document.getElementById("splash-qr");
const qrDialog = document.getElementById("qr-dialog");
const qrDialogCode = document.getElementById("qr-dialog-code");
const qrDialogClose = document.getElementById("qr-dialog-close");
let isLiveMode = false;
let lastVerseData = null;
let verseHistory = [];
let selectedTranslations = loadSelectedTranslations();
let presentationPreviousScaleIndex = null;
let restorePresentationOnLive = localStorage.getItem("bibleit-presentation") === "true";
let presentationFitFrame = null;
let wakeLock = null;

async function requestWakeLock() {
  if (!("wakeLock" in navigator)) return;
  if (!isLiveMode || document.visibilityState !== "visible" || wakeLock) return;

  try {
    wakeLock = await navigator.wakeLock.request("screen");
    wakeLock.addEventListener("release", () => {
      wakeLock = null;
      if (isLiveMode && document.visibilityState === "visible") {
        setTimeout(requestWakeLock, 0);
      }
    });
  } catch (_error) {
    wakeLock = null;
  }
}

function releaseWakeLock() {
  if (!wakeLock) return;

  const lock = wakeLock;
  wakeLock = null;
  lock.release().catch(() => {});
}

function updateWakeLock() {
  if (isLiveMode && document.visibilityState === "visible") {
    requestWakeLock();
  } else {
    releaseWakeLock();
  }
}

function ensureLargeQr() {
  if (qrDialogCode.childElementCount) return;

  const source = splashQr?.querySelector(".qr-code");
  if (!source) return;

  const clone = source.cloneNode(true);
  qrDialogCode.append(clone);
}

function openQrDialog() {
  ensureLargeQr();
  qrDialog.hidden = false;
  qrDialogClose.focus({ preventScroll: true });
}

function closeQrDialog() {
  if (qrDialog.hidden) return;

  qrDialog.hidden = true;
  splashQr.focus({ preventScroll: true });
}

function applyMode(isLive) {
  isLiveMode = Boolean(isLive);
  document.documentElement.dataset.live = isLiveMode ? "true" : "false";
  if (!isLive) {
    restorePresentationOnLive = false;
    setPresentationMode(false);
    verses.replaceChildren();
    translationFilterOptions.replaceChildren();
    translationFilter.hidden = true;
    status.textContent = "Waiting for presenter";
    splashStatus.textContent = "Waiting for presenter";
  } else if (lastVerseData) {
    if (restorePresentationOnLive) setPresentationMode(true, { persist: false });
    status.textContent = "Live";
    renderLiveVerses();
  } else {
    if (restorePresentationOnLive) setPresentationMode(true, { persist: false });
    status.textContent = "Live";
    splashStatus.textContent = "Live";
  }
  updateWakeLock();
}

function setTheme(value) {
  document.documentElement.dataset.theme = value;
  localStorage.setItem("bibleit-theme", value);
  theme.textContent = value === "dark" ? "☀" : "☾";
}

async function setPresentationMode(enabled, options = {}) {
  const persist = options.persist !== false;
  const value = enabled ? "true" : "false";
  document.documentElement.dataset.presentation = value;
  if (persist) {
    localStorage.setItem("bibleit-presentation", value);
    restorePresentationOnLive = enabled;
  }
  presentation.textContent = "▤";

  try {
    if (enabled && !document.fullscreenElement) {
      await document.documentElement.requestFullscreen();
    }

    if (!enabled && document.fullscreenElement) {
      await document.exitFullscreen();
    }
  } catch (_error) {
    // Fullscreen is best-effort. Some mobile browsers may block it.
  }

  if (enabled) {
    if (presentationPreviousScaleIndex === null) {
      presentationPreviousScaleIndex = currentVerseScaleIndex();
    }
    setVerseScaleIndex(verseScales.length - 1, { persist: false });
  } else if (presentationPreviousScaleIndex !== null) {
    setVerseScaleIndex(presentationPreviousScaleIndex, { persist: false });
    presentationPreviousScaleIndex = null;
  }

  schedulePresentationFit();
}

function loadSelectedTranslations() {
  const stored = localStorage.getItem("bibleit-selected-translations");
  if (!stored) return null;

  try {
    const values = JSON.parse(stored);
    if (!Array.isArray(values) || !values.length) return null;
    return new Set(values.filter((value) => typeof value === "string" && value));
  } catch (_error) {
    return null;
  }
}

function saveSelectedTranslations(values, available) {
  if (!values.length || values.length === available.length) {
    selectedTranslations = null;
    localStorage.removeItem("bibleit-selected-translations");
  } else {
    selectedTranslations = new Set(values);
    localStorage.setItem("bibleit-selected-translations", JSON.stringify(values));
  }

  document.documentElement.dataset.filtered = selectedTranslations ? "true" : "false";
}

function availableTranslations(data) {
  return [...new Set(normalizeVerses(data).map((verse) => verse.translation || "bibleit"))];
}

function renderTranslationOption(value, label, checked) {
  const wrapper = document.createElement("label");
  const input = document.createElement("input");
  const text = document.createElement("span");

  input.type = "checkbox";
  input.value = value;
  input.checked = checked;
  text.textContent = label;

  wrapper.append(input, text);
  return wrapper;
}

function selectedTranslationValues() {
  return [...translationFilterOptions.querySelectorAll("input:checked")].map((input) => input.value);
}

function updateTranslationFilterLabel(available) {
  if (!selectedTranslations) {
    translationFilterLabel.ariaLabel = "All translations";
    translationFilterLabel.title = "All translations";
    return;
  }

  const selected = available.filter((translation) => selectedTranslations.has(translation));
  const label = selected.length ? `Selected translations: ${selected.join(", ")}` : "All translations";
  translationFilterLabel.ariaLabel = label;
  translationFilterLabel.title = label;
}

function updateTranslationFilterOptions(data) {
  const available = availableTranslations(data);
  const stillAvailable = selectedTranslations
    ? available.filter((translation) => selectedTranslations.has(translation))
    : available;

  if (selectedTranslations && !stillAvailable.length) {
    selectedTranslations = null;
    localStorage.removeItem("bibleit-selected-translations");
  }

  if (selectedTranslations && stillAvailable.length === available.length) {
    selectedTranslations = null;
    localStorage.removeItem("bibleit-selected-translations");
  }

  translationFilterOptions.replaceChildren(
    ...available.map((translation) =>
      renderTranslationOption(translation, translation, !selectedTranslations || selectedTranslations.has(translation))
    )
  );

  updateTranslationFilterLabel(available);
  translationFilter.hidden = available.length <= 1;
  document.documentElement.dataset.filtered = selectedTranslations ? "true" : "false";
}

const verseScales = [0.85, 1, 1.2, 1.4];

function closestVerseScaleIndex(value) {
  const scale = Number.parseFloat(value);
  const safeScale = Number.isFinite(scale) ? scale : 1;
  return verseScales.reduce((bestIndex, candidate, index) => {
    const bestDistance = Math.abs(verseScales[bestIndex] - safeScale);
    const candidateDistance = Math.abs(candidate - safeScale);
    return candidateDistance < bestDistance ? index : bestIndex;
  }, 1);
}

function currentVerseScaleIndex() {
  const current = Number.parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue("--verse-scale")
  );
  return closestVerseScaleIndex(current);
}

function setVerseScaleIndex(index, options = {}) {
  const persist = options.persist !== false;
  const clampedIndex = Math.max(0, Math.min(index, verseScales.length - 1));
  const safeScale = verseScales[clampedIndex];
  document.documentElement.style.setProperty("--verse-scale", safeScale.toString());
  if (persist) localStorage.setItem("bibleit-verse-scale", safeScale.toString());
  const label = `Font size ${clampedIndex + 1}/${verseScales.length}`;
  fontSize.setAttribute("aria-label", label);
  fontSize.title = label;
  fontSize.textContent = clampedIndex === 0 ? "A" : `A${clampedIndex + 1}`;
  fitPresentationText();
}

function setVerseScale(value) {
  setVerseScaleIndex(closestVerseScaleIndex(value));
}

const savedTheme = localStorage.getItem("bibleit-theme");
setTheme(savedTheme || "light");

const savedVerseScale = localStorage.getItem("bibleit-verse-scale");
setVerseScale(savedVerseScale || "1");

document.documentElement.dataset.filtered = selectedTranslations ? "true" : "false";
document.documentElement.dataset.live = "false";
document.documentElement.dataset.hasHistory = "false";

theme.addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

historyToggle.addEventListener("click", () => {
  const enabled = document.documentElement.dataset.history !== "true";
  document.documentElement.dataset.history = enabled ? "true" : "false";
  renderHistory();
});

presentation.addEventListener("click", () => {
  const enabled = document.documentElement.dataset.presentation !== "true";
  setPresentationMode(enabled);
});

fontSize.addEventListener("click", () => {
  setVerseScaleIndex((currentVerseScaleIndex() + 1) % verseScales.length);
});

translationFilterOptions.addEventListener("change", () => {
  const available = availableTranslations(lastVerseData || {});
  const values = selectedTranslationValues();
  saveSelectedTranslations(values, available);
  updateTranslationFilterLabel(available);
  renderLiveVerses();
});

function normalizeVerses(data) {
  if (Array.isArray(data.translations) && data.translations.length) return data.translations;
  return data.text ? [data] : [];
}

function verseHistoryKey(data) {
  return normalizeVerses(data)
    .map((verse) => [
      verse.translation || "bibleit",
      verse.book || "",
      verse.chapter || "",
      verse.verse || "",
    ].join(":"))
    .join("|");
}

function verseHistoryReference(verse) {
  const translation = verse.translation || "bibleit";
  const reference = verse.reference || [verse.book, `${verse.chapter}:${verse.verse}`].filter(Boolean).join(" ");
  return `${translation} · ${reference}`;
}

function recordHistory(data) {
  const key = verseHistoryKey(data);
  if (!key) return;

  verseHistory = verseHistory.filter((entry) => entry.key !== key);
  verseHistory.unshift({ key, data });
  verseHistory = verseHistory.slice(0, 24);
  renderHistory();
}

function renderHistory() {
  if (!verseHistory.length) {
    document.documentElement.dataset.hasHistory = "false";
    document.documentElement.dataset.history = "false";
    historyPanel.replaceChildren();
    return;
  }

  document.documentElement.dataset.hasHistory = "true";
  historyPanel.replaceChildren(
    ...verseHistory.map((entry) => {
      const primary = normalizeVerses(entry.data)[0] || {};
      const button = document.createElement("button");
      const reference = document.createElement("span");
      const text = document.createElement("span");

      button.type = "button";
      button.className = "history-item";
      reference.className = "history-ref";
      text.className = "history-text";
      reference.textContent = verseHistoryReference(primary);
      text.textContent = primary.text || "";

      button.append(reference, text);
      button.addEventListener("click", () => {
        document.documentElement.dataset.history = "false";
        showVerse(entry.data, "History");
      });

      return button;
    })
  );
}

function visibleVerses(data) {
  const normalized = normalizeVerses(data);
  updateTranslationFilterOptions(data);

  if (!selectedTranslations) return normalized;

  const filtered = normalized.filter((verse) => selectedTranslations.has(verse.translation || "bibleit"));

  if (filtered.length) return filtered;

  selectedTranslations = null;
  localStorage.removeItem("bibleit-selected-translations");
  return normalized;
}

function renderVerseCard(data) {
  const card = document.createElement("section");
  card.className = "verse-card";

  const translation = document.createElement("div");
  translation.className = "translation";
  translation.textContent = data.translation || "bibleit";

  const reference = document.createElement("div");
  reference.className = "reference";
  reference.textContent = data.reference || "";

  const verse = document.createElement("div");
  verse.className = "verse";
  verse.textContent = data.text || "";

  card.append(translation, reference, verse);
  return card;
}

function fitPresentationText() {
  const verseText = [...document.querySelectorAll(".verse-card .verse")];

  verseText.forEach((element) => {
    element.style.fontSize = "";
  });

  if (document.documentElement.dataset.presentation !== "true") return;

  requestAnimationFrame(() => {
    const cards = [...document.querySelectorAll(".verse-card")];

    cards.forEach((card) => {
      const verse = card.querySelector(".verse");
      if (!verse) return;

      let low = 6;
      let high = window.innerWidth <= 600 ? 42 : 120;

      const fits = () =>
        card.scrollHeight <= card.clientHeight + 1 &&
        verses.scrollHeight <= verses.clientHeight + 1;

      for (let i = 0; i < 24; i += 1) {
        const mid = (low + high) / 2;
        verse.style.fontSize = `${mid}px`;

        if (fits()) {
          low = mid;
        } else {
          high = mid;
        }
      }

      verse.style.fontSize = `${low}px`;
    });
  });
}

function schedulePresentationFit() {
  if (presentationFitFrame !== null) {
    cancelAnimationFrame(presentationFitFrame);
  }

  presentationFitFrame = requestAnimationFrame(() => {
    presentationFitFrame = null;
    fitPresentationText();
    setTimeout(fitPresentationText, 80);
    setTimeout(fitPresentationText, 250);
  });
}

function showVerse(data, label) {
  lastVerseData = data;
  if (isLiveMode) {
    renderLiveVerses();
    status.textContent = label;
  }
}

function applyVerse(data) {
  if (data.history === true) {
    recordHistory(data);
  }

  showVerse(data, "Live");
}

function renderLiveVerses() {
  const renderedVerses = visibleVerses(lastVerseData || {});
  document.documentElement.style.setProperty("--visible-count", Math.max(renderedVerses.length, 1).toString());
  verses.replaceChildren(...renderedVerses.map(renderVerseCard));
  schedulePresentationFit();
}

window.addEventListener("resize", schedulePresentationFit);
window.addEventListener("orientationchange", schedulePresentationFit);
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", schedulePresentationFit);
}
document.addEventListener("visibilitychange", updateWakeLock);

splashQr.addEventListener("click", (event) => {
  event.preventDefault();
  openQrDialog();
});

qrDialogClose.addEventListener("click", closeQrDialog);

qrDialog.addEventListener("click", (event) => {
  if (event.target === qrDialog) {
    closeQrDialog();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !qrDialog.hidden) {
    event.stopPropagation();
    closeQrDialog();
  }
});

if (document.fonts) {
  document.fonts.ready.then(schedulePresentationFit);
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);

  socket.addEventListener("open", () => {
    status.textContent = "Connected";
    splashStatus.textContent = "Connected";
  });

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "mode") applyMode(message.live);
    if (message.type === "verse") applyVerse(message.verse);
  });

  socket.addEventListener("close", () => {
    status.textContent = "Reconnecting...";
    splashStatus.textContent = "Reconnecting...";
    setTimeout(connect, 1000);
  });
}

connect();
renderHistory();

document.addEventListener("click", (event) => {
  if (!translationFilter.contains(event.target)) {
    translationFilter.removeAttribute("open");
  }

  if (!historyPanel.contains(event.target) && event.target !== historyToggle) {
    document.documentElement.dataset.history = "false";
  }
});
