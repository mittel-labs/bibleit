(() => {
  const root = document.documentElement;
  const splashTitle = document.querySelector("#splash-title");
  const splashStatus = document.querySelector("#connection-status");
  const splashLiveName = document.querySelector("#splash-live-name");
  const viewerLiveName = document.querySelector("#viewer-live-name");
  const versesElement = document.querySelector("#verses");
  const secretForm = document.querySelector("#secret-form");
  const query = new URLSearchParams(location.search);
  const route = location.pathname.match(/^\/lives\/([0-9A-Za-z]+)$/);
  const liveID = route?.[1] || query.get("live");
  const widgetMode = query.has("widget");
  const requestedTheme = query.get("theme");
  const initialTheme = ["dark", "light"].includes(requestedTheme)
    ? requestedTheme
    : localStorage.getItem("bibleit-theme") || "dark";
  const selectedTranslations = new Set([
    ...query.getAll("translation"),
    ...(query.get("translations") || "").split(","),
  ].map((translation) => translation.trim().toLowerCase()).filter(Boolean));
  const scaleValues = [.85, 1, 1.18, 1.36];
  let scaleIndex = Number(localStorage.getItem("bibleit-verse-scale") || 1);
  let current = null;
  let reconnectDelay = 1000;
  let awaitingSecret = false;
  let terminal = false;
  let disconnected = false;
  let liveStatus = null;

  root.dataset.widget = widgetMode ? "true" : "false";
  root.dataset.theme = initialTheme;
  applyScale();

  document.querySelector("#theme").onclick = () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("bibleit-theme", root.dataset.theme);
  };
  document.querySelector("#font-size").onclick = () => {
    scaleIndex = (scaleIndex + 1) % scaleValues.length;
    localStorage.setItem("bibleit-verse-scale", scaleIndex);
    applyScale();
  };
  document.querySelector("#presentation").onclick = () => setPresentation(root.dataset.presentation !== "true");
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root.dataset.presentation === "true") setPresentation(false);
  });
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) {
      root.dataset.presentation = "false";
      fitPresentation();
    }
  });
  secretForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new URLSearchParams(new FormData(secretForm));
    const response = await fetch(`/auth/${encodeURIComponent(liveID)}`, { method: "POST", body: data, headers: { "Content-Type": "application/x-www-form-urlencoded" } });
    if (response.ok) location.reload();
    else splashStatus.textContent = "That secret is not valid for this live.";
  });
  window.addEventListener("resize", () => requestAnimationFrame(fitPresentation));

  if (!liveID) {
    splashStatus.textContent = "Open a live link such as /lives/<id>.";
    return;
  }
  connect();

  function applyScale() {
    scaleIndex = Math.max(0, Math.min(scaleValues.length - 1, scaleIndex));
    root.style.setProperty("--scale", scaleValues[scaleIndex]);
  }

  function setLiveName(name) {
    const label = String(name || "").trim();
    if (!label) return;
    document.title = `${label} · bibleit live`;
    splashLiveName.textContent = label;
    splashLiveName.hidden = false;
    viewerLiveName.textContent = label;
  }

  async function setPresentation(enabled) {
    root.dataset.presentation = enabled ? "true" : "false";
    if (enabled && document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen().catch(() => {});
    if (!enabled && document.fullscreenElement) await document.exitFullscreen().catch(() => {});
    requestAnimationFrame(fitPresentation);
  }

  function connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${location.host}/ws?live=${encodeURIComponent(liveID)}`);
    splashStatus.textContent = "Connecting to the live session…";
    socket.onopen = () => { reconnectDelay = 1000; };
    socket.onmessage = ({ data }) => {
      try {
        const message = JSON.parse(data);
        if (message.name !== undefined) setLiveName(message.name);
        if (message.type === "live" || message.type === "live_state") applyLiveState(message);
        if (message.type === "verse" && message.verse) applyVerse(message.verse);
        if (message.type === "clear") clearVerses();
        if (message.type === "paused") livePaused();
        if (message.type === "closed") liveClosed();
        if (message.type === "revoked") accessRevoked();
        if (message.type === "not_found") liveNotFound();
        if (message.type === "error" && !awaitingSecret && showError(message.line || "Unable to join this session.")) {
          awaitingSecret = true;
          socket.close();
        }
      } catch { /* Ignore malformed upstream messages. */ }
    };
    socket.onclose = () => {
      if (awaitingSecret || terminal) return;
      connectionLost();
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    };
  }

  function applyVerse(payload) {
    current = payload;
    root.dataset.live = "true";
    render(payload);
  }

  function clearVerses() {
    current = null;
    root.dataset.live = "false";
    versesElement.replaceChildren();
    splashStatus.textContent = "Waiting for the presenter to share a verse.";
  }

  function applyLiveState(message) {
    const previousStatus = liveStatus;
    liveStatus = message.status || liveStatus;
    if (message.status === "stopped") liveStopped();
    else if (message.paused === true) livePaused();
    else if (disconnected || previousStatus === "stopped") liveWaiting();
    disconnected = false;
  }

  function liveWaiting() {
    current = null;
    root.dataset.live = "false";
    versesElement.replaceChildren();
    splashTitle.textContent = "Waiting for the next verse.";
    splashStatus.textContent = "Waiting for the presenter to share a verse.";
    secretForm.hidden = true;
  }

  function livePaused() {
    current = null;
    root.dataset.live = "false";
    versesElement.replaceChildren();
    splashTitle.textContent = "This live is paused.";
    splashStatus.textContent = "We’ll be right back.";
    secretForm.hidden = true;
  }

  function liveStopped() {
    current = null;
    root.dataset.live = "false";
    versesElement.replaceChildren();
    splashTitle.textContent = "This live is currently stopped.";
    splashStatus.textContent = "The presenter will start it again when it is ready.";
    secretForm.hidden = true;
  }

  function connectionLost() {
    disconnected = true;
    current = null;
    root.dataset.live = "false";
    versesElement.replaceChildren();
    splashTitle.textContent = "Connection lost.";
    splashStatus.textContent = "Trying to reconnect to this live…";
  }

  function liveClosed() {
    terminal = true;
    current = null;
    root.dataset.live = "false";
    versesElement.replaceChildren();
    splashTitle.textContent = "This live has ended.";
    splashStatus.textContent = "This live has ended.";
    secretForm.hidden = true;
  }

  function liveNotFound() {
    terminal = true;
    current = null;
    root.dataset.live = "false";
    versesElement.replaceChildren();
    splashTitle.textContent = "Live not found.";
    splashStatus.textContent = "This live does not exist or has been removed.";
    secretForm.hidden = true;
  }

  function accessRevoked() {
    terminal = true;
    current = null;
    root.dataset.live = "false";
    versesElement.replaceChildren();
    splashTitle.textContent = "Access revoked.";
    splashStatus.textContent = "The live secret was changed.";
    secretForm.hidden = true;
  }

  function showError(message) {
    if (/ERR (forbidden|unauthorized)/.test(message)) {
      splashStatus.textContent = "This live requires a secret. Enter it to join.";
      secretForm.hidden = false;
      return true;
    }
    splashStatus.textContent = message;
    return false;
  }

  function allVerses(payload) {
    const verses = Array.isArray(payload.translations) && payload.translations.length ? payload.translations : [payload];
    if (!selectedTranslations.size) return verses;
    return verses.filter((verse) => selectedTranslations.has((verse.translation || "").toLowerCase()));
  }

  function render(payload) {
    const cards = allVerses(payload);
    versesElement.replaceChildren(...cards.map((verse) => {
      const card = document.createElement("article");
      card.className = "verse-card";
      const heading = document.createElement("div");
      heading.className = "verse-heading";
      const translation = document.createElement("div");
      translation.className = "translation";
      translation.textContent = verse.translation || "Bible";
      heading.append(translation);
      const reference = document.createElement("div");
      reference.className = "reference";
      reference.textContent = verse.reference || [verse.book, `${verse.chapter || ""}:${verse.verse || ""}`].filter(Boolean).join(" ");
      const text = document.createElement("div");
      text.className = "verse";
      text.textContent = cleanVerseText(verse.text || "");
      card.append(heading, reference, text);
      return card;
    }));
    requestAnimationFrame(fitPresentation);
  }

  function cleanVerseText(text) {
    return text.replace(/<S>\d+<\/S>/gi, "");
  }

  function fitPresentation() {
    const cards = [...versesElement.querySelectorAll(".verse-card")];
    if (widgetMode) {
      versesElement.style.gridTemplateRows = "";
      cards.forEach((card) => { card.querySelector(".verse").style.fontSize = ""; });
      return;
    }
    if (root.dataset.presentation !== "true" || !cards.length) {
      versesElement.style.gridTemplateRows = "";
      cards.forEach((card) => { card.querySelector(".verse").style.fontSize = ""; });
      return;
    }
    versesElement.style.gridTemplateRows = `repeat(${cards.length}, minmax(0, 1fr))`;
    cards.forEach((card) => {
      const verse = card.querySelector(".verse");
      const height = Math.floor(card.getBoundingClientRect().height);
      if (!height) return;
      let low = 14;
      let high = Math.max(low, Math.floor(height * 0.6));
      while (low < high) {
        const middle = Math.ceil((low + high) / 2);
        verse.style.fontSize = `${middle}px`;
        if (card.scrollHeight <= card.clientHeight + 1 && verse.scrollWidth <= verse.clientWidth + 1) low = middle;
        else high = middle - 1;
      }
      verse.style.fontSize = `${low}px`;
    });
  }

})();
