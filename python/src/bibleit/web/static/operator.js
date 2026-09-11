const API = "/api/v1";
const RECONNECT_MS = 1000;
const FIND_DEBOUNCE_MS = 220;
const RESOLVE_DEBOUNCE_MS = 140;
const TOAST_MS = 4000;

const SHORTCUTS = [
  ["↑ ↓", "Previous / next verse"],
  [", .", "Previous / next chapter"],
  ["Home / End", "Start / end of chapter"],
  ["g", "Go to a reference"],
  ["l", "Go live or stop"],
  ["t", "Library"],
  ["b", "Books"],
  ["f", "Find text"],
  ["s", "Share"],
  ["h", "Show Strong's numbers"],
  ["d", "Light or dark"],
  ["?", "This list"],
  ["Esc", "Close"],
];

const PANELS = {
  library: { title: "Library", open: loadLibrary },
  books: { title: "Books", open: loadBooks },
  find: { title: "Find", open: () => el("find-input").focus() },
  share: { title: "Share", open: loadShare },
  settings: { title: "Settings", open: loadSettings },
  help: { title: "Shortcuts", open: renderShortcuts },
};

const state = {
  snapshot: null,
  catalogue: null,
  books: [],
  book: null,
  panel: null,
  candidates: [],
  candidate: -1,
  searched: false,
};

let socket = null;
let findTimer = null;
let resolveTimer = null;

const el = (id) => document.getElementById(id);

/* ---------------- transport ---------------- */

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}${API}/operator`);

  socket.addEventListener("message", (event) => {
    let payload;

    try {
      payload = JSON.parse(event.data);
    } catch (_error) {
      return;
    }

    receive(payload);
  });

  socket.addEventListener("close", () => {
    socket = null;
    setTimeout(connect, RECONNECT_MS);
  });
}

async function send(command, params = {}) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ command, params }));
    return;
  }

  const response = await fetch(`${API}/command`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ command, params }),
  });

  if (!response.ok) {
    toast(await errorText(response), "error");
    return;
  }

  applySnapshot(await response.json());
}

async function errorText(response) {
  try {
    const payload = await response.json();
    return payload.error || response.statusText;
  } catch (_error) {
    return response.statusText || "Something went wrong";
  }
}

function receive(payload) {
  if (payload.type === "state") applySnapshot(payload.state);
  if (payload.type === "error") toast(payload.message, "error");
  if (payload.type === "install") installed(payload);
}

/* ---------------- state ---------------- */

function slugsOf(snapshot) {
  return snapshot.translations.map((entry) => entry.slug).join(",");
}

function applySnapshot(snapshot) {
  const previous = state.snapshot;
  state.snapshot = snapshot;
  renderBar();

  if (!previous || slugsOf(previous) !== slugsOf(snapshot)) {
    loadVerses();
    return;
  }

  if (!highlight(snapshot.ref)) loadVerses();
}

function renderBar() {
  const snapshot = state.snapshot;
  const open = snapshot.translations.length > 0;

  el("now").textContent = open ? snapshot.ref.reference : "No translation open";
  el("welcome").hidden = open;

  const live = el("live-toggle");
  live.dataset.live = snapshot.live ? "true" : "false";
  live.textContent = snapshot.live ? "Live" : "Go live";

  const viewers = el("viewers");
  const counts = snapshot.viewer_counts || {};
  viewers.hidden = !snapshot.live;
  viewers.textContent = `${snapshot.viewers} ${snapshot.viewers === 1 ? "viewer" : "viewers"}`;
  viewers.title =
    Object.entries(counts)
      .map(([name, count]) => `${name}: ${count}`)
      .join(" · ") || "No viewers yet";

  el("strongs-toggle").setAttribute("aria-pressed", snapshot.strongs ? "true" : "false");
  document.body.dataset.strongs = snapshot.strongs ? "true" : "false";

  const share = el("share-state");
  if (share) share.textContent = shareState(snapshot);
}

function shareState(snapshot) {
  if (!snapshot.live) return "Not live yet — viewers see a waiting screen.";

  const counts = Object.entries(snapshot.viewer_counts || {})
    .map(([name, count]) => `${count} on ${name}`)
    .join(", ");

  return counts ? `Live · ${counts}.` : "Live.";
}

/* ---------------- verses ---------------- */

async function loadVerses() {
  const snapshot = state.snapshot;

  if (!snapshot || !snapshot.translations.length) {
    el("columns").replaceChildren();
    return;
  }

  const response = await fetch(`${API}/verses`);

  if (!response.ok) {
    toast(await errorText(response), "error");
    return;
  }

  renderColumns(await response.json());
  highlight(snapshot.ref);
}

function renderColumns(payload) {
  const active = state.snapshot.active;

  el("columns").replaceChildren(
    ...payload.columns.map((column) => {
      const section = document.createElement("section");
      section.className = "column";
      section.dataset.translation = column.translation;
      section.dataset.active = column.translation === active ? "true" : "false";

      const head = document.createElement("header");
      head.className = "column-head";

      const slug = document.createElement("span");
      slug.className = "column-slug";
      slug.textContent = column.translation;

      const name = document.createElement("span");
      name.className = "column-name";
      name.textContent = column.name;

      const close = document.createElement("button");
      close.type = "button";
      close.className = "column-close";
      close.title = `Close ${column.translation}`;
      close.setAttribute("aria-label", `Close ${column.translation}`);
      close.textContent = "×";
      close.addEventListener("click", () => send("close_translation", { slug: column.translation }));

      head.append(slug, name, close);

      const rows = document.createElement("div");
      rows.className = "rows";
      rows.append(...column.rows.map(renderRow));

      section.append(head, rows);

      section.addEventListener("click", () => {
        if (state.snapshot.active !== column.translation) {
          send("set_active", { slug: column.translation });
        }
      });

      return section;
    })
  );
}

function renderRow(row) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "row";
  button.dataset.bookid = row.bookid;
  button.dataset.chapter = row.chapter;
  button.dataset.verse = row.verse;

  const reference = document.createElement("span");
  reference.className = "ref";
  reference.textContent = row.reference;

  const text = document.createElement("span");
  // Server-rendered: reader.render_html escapes the verse and emits only
  // <b>, <i>, <sup>, <br> and the Strong's span.
  text.innerHTML = row.html;

  button.append(reference, text);

  button.addEventListener("click", (event) => {
    const strong = event.target.closest(".strong");

    if (strong) {
      event.stopPropagation();
      openStrong(strong.dataset.code);
      return;
    }

    send("goto_ref", {
      bookid: row.bookid,
      chapter: row.chapter,
      verse: row.verse,
      history: true,
    });
  });

  return button;
}

function highlight(ref) {
  let found = false;

  for (const row of document.querySelectorAll(".row")) {
    const matches =
      Number(row.dataset.bookid) === ref.bookid &&
      Number(row.dataset.chapter) === ref.chapter &&
      Number(row.dataset.verse) === ref.verse;

    if (matches) {
      row.setAttribute("aria-current", "true");
      row.scrollIntoView({ block: "center" });
      found = true;
    } else {
      row.removeAttribute("aria-current");
    }
  }

  return found;
}

/* ---------------- go to ---------------- */

async function resolve(value) {
  const response = await fetch(`${API}/resolve?q=${encodeURIComponent(value)}`);

  if (!response.ok) return;

  const payload = await response.json();
  state.candidates = payload.candidates || [];
  state.candidate = -1;
  renderCandidates();
}

function renderCandidates() {
  const box = el("candidates");
  const value = el("goto-input").value.trim();

  if (!value || state.candidates.length === 0) {
    box.hidden = true;
    box.replaceChildren();
    return;
  }

  box.hidden = false;
  box.replaceChildren(
    ...state.candidates.slice(0, 12).map((candidate, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.role = "option";
      button.textContent = candidate;
      button.setAttribute("aria-selected", index === state.candidate ? "true" : "false");
      button.addEventListener("click", () => {
        el("goto-input").value = `${candidate} `;
        el("goto-input").focus();
        hideCandidates();
      });
      return button;
    })
  );
}

function hideCandidates() {
  state.candidates = [];
  state.candidate = -1;
  el("candidates").hidden = true;
}

function moveCandidate(delta) {
  if (!state.candidates.length) return false;

  const count = Math.min(state.candidates.length, 12);
  state.candidate = (state.candidate + delta + count + 1) % (count + 1) - 1;

  if (state.candidate < 0) state.candidate = state.candidates.length ? count - 1 : -1;

  renderCandidates();
  return true;
}

async function submitGoto(event) {
  event.preventDefault();
  const input = el("goto-input");

  if (state.candidate >= 0 && state.candidates[state.candidate]) {
    input.value = `${state.candidates[state.candidate]} `;
    hideCandidates();
    return;
  }

  const value = input.value.trim();
  if (!value) return;

  hideCandidates();
  await send("goto", { value });
  input.select();
}

/* ---------------- library ---------------- */

async function loadLibrary() {
  renderOpen();

  const hint = el("library-hint");
  hint.hidden = false;
  hint.textContent = "Loading the catalogue…";

  const response = await fetch(`${API}/translations`);

  if (!response.ok) {
    hint.textContent = await errorText(response);
    return;
  }

  state.catalogue = await response.json();
  hint.hidden = true;
  renderCatalogue();
}

function renderOpen() {
  const snapshot = state.snapshot;
  const target = el("library-open");

  if (!snapshot || !snapshot.translations.length) {
    target.replaceChildren();
    return;
  }

  const title = document.createElement("p");
  title.className = "group-title";
  title.textContent = "Open now";

  target.replaceChildren(
    title,
    ...snapshot.translations.map((entry) =>
      renderEntry(entry.slug, entry.name, "Close", () => send("close_translation", { slug: entry.slug }))
    )
  );
}

function renderCatalogue() {
  const installed = new Set(state.catalogue.installed);
  const open = new Set((state.snapshot?.translations || []).map((entry) => entry.slug));
  const groups = [];

  for (const language of state.catalogue.languages) {
    const entries = language.translations.filter((entry) => !open.has(entry.slug));

    if (!entries.length) continue;

    const title = document.createElement("p");
    title.className = "group-title";
    title.textContent = language.name;
    groups.push(title);

    for (const entry of entries) {
      const isInstalled = installed.has(entry.slug);
      groups.push(
        renderEntry(entry.slug, entry.name, isInstalled ? "Open" : "Install", (button) => {
          if (isInstalled) {
            send("open_translation", { slug: entry.slug });
            closePanel();
            return;
          }

          install(entry.slug, button);
        })
      );
    }
  }

  el("library-catalogue").replaceChildren(...groups);
}

function renderEntry(slug, name, label, action) {
  const row = document.createElement("div");
  row.className = "entry";
  row.dataset.slug = slug;

  const text = document.createElement("div");
  text.className = "entry-name";

  const strong = document.createElement("b");
  strong.textContent = slug;

  const caption = document.createElement("span");
  caption.textContent = name;

  text.append(strong, caption);

  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", () => action(button));

  row.append(text, button);
  return row;
}

async function install(slug, button) {
  button.disabled = true;
  button.textContent = "Installing…";

  const response = await fetch(`${API}/translations/${encodeURIComponent(slug)}`, { method: "POST" });

  if (!response.ok) {
    button.disabled = false;
    button.textContent = "Install";
    toast(await errorText(response), "error");
    return;
  }

  toast(`Downloading ${slug}. This happens once.`);
}

function installed(event) {
  if (event.state === "installed") {
    toast(`${event.slug} is ready.`);
    send("open_translation", { slug: event.slug });
    if (state.panel === "library") loadLibrary();
  }

  if (event.state === "failed") {
    toast(`${event.slug} could not be installed: ${event.error}`, "error");
    if (state.panel === "library") loadLibrary();
  }

  if (event.state === "removed" && state.panel === "library") loadLibrary();
}

/* ---------------- books ---------------- */

async function loadBooks() {
  const response = await fetch(`${API}/books`);

  if (!response.ok) {
    el("books-grid").replaceChildren();
    toast(await errorText(response), "error");
    return;
  }

  const payload = await response.json();
  state.books = payload.books;
  state.book = state.books.find((book) => book.bookid === state.snapshot?.ref.bookid) || null;
  renderBooks();
}

function renderBooks() {
  el("books-grid").replaceChildren(
    ...state.books.map((book) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = book.name;
      button.title = book.name;
      button.dataset.bookid = book.bookid;
      button.dataset.active = state.book && state.book.bookid === book.bookid ? "true" : "false";
      button.addEventListener("click", () => {
        state.book = book;
        renderBooks();
      });
      return button;
    })
  );

  renderChapters();
}

function renderChapters() {
  const grid = el("chapters-grid");

  if (!state.book) {
    grid.hidden = true;
    return;
  }

  grid.hidden = false;
  grid.replaceChildren(
    ...Array.from({ length: state.book.chapters }, (_unused, index) => {
      const chapter = index + 1;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = String(chapter);
      button.addEventListener("click", () => {
        send("goto_ref", { bookid: state.book.bookid, chapter, verse: 1, history: true });
        closePanel();
      });
      return button;
    })
  );
}

/* ---------------- find ---------------- */

async function runFind() {
  const query = el("find-input").value.trim();
  const hint = el("find-hint");
  const results = el("find-results");

  if (query.length < 2) {
    results.replaceChildren();
    hint.textContent = "Type at least two letters.";
    return;
  }

  hint.textContent = state.searched ? "Searching…" : "Searching… the first search builds an index.";

  const response = await fetch(`${API}/find?q=${encodeURIComponent(query)}`);

  if (!response.ok) {
    hint.textContent = await errorText(response);
    return;
  }

  const payload = await response.json();
  state.searched = true;

  hint.textContent = payload.results.length
    ? `${payload.results.length} in ${payload.translation}`
    : `Nothing in ${payload.translation} for “${query}”.`;

  results.replaceChildren(
    ...payload.results.map((result) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "result";

      const reference = document.createElement("b");
      reference.textContent = result.reference;

      const text = document.createElement("span");
      text.textContent = result.text;

      button.append(reference, text);
      button.addEventListener("click", () => {
        send("goto_ref", {
          bookid: result.bookid,
          chapter: result.chapter,
          verse: result.verse,
          history: true,
        });
        closePanel();
      });

      return button;
    })
  );
}

/* ---------------- share ---------------- */

async function loadShare() {
  const response = await fetch(`${API}/addresses`);
  const fallback = `${location.origin}/`;

  if (!response.ok) {
    el("share-url").textContent = fallback;
    return;
  }

  const payload = await response.json();
  el("share-url").textContent = payload.audience[payload.audience.length - 1] || fallback;
  el("share-state").textContent = shareState(state.snapshot);
  // The reachable address can change with the network, so ask again each time.
  el("share-qr").src = `${API}/qr.svg?t=${Date.now()}`;
}

async function copyShare() {
  const url = el("share-url").textContent;

  try {
    await navigator.clipboard.writeText(url);
    toast("Address copied.");
  } catch (_error) {
    toast("Copy it by hand — the browser blocked the clipboard.", "error");
  }
}

/* ---------------- settings ---------------- */

async function loadSettings() {
  const hint = el("settings-hint");
  const response = await fetch(`${API}/config`);

  if (response.status === 403) {
    hint.textContent = "Settings are only available on the machine running bibleit.";
    return;
  }

  if (!response.ok) {
    hint.textContent = await errorText(response);
    return;
  }

  const payload = await response.json();

  for (const [name, value] of Object.entries(payload.values)) {
    const input = el(`config-${name}`);
    if (input) input.value = value;
  }

  hint.textContent = payload.environment.length
    ? `Set in the environment, so saving will not change them: ${payload.environment.join(", ")}.`
    : "Saved to ~/.bibleit/config.";
}

async function saveSettings(event) {
  event.preventDefault();

  const values = {};
  for (const input of el("settings-form").querySelectorAll("input[name]")) {
    values[input.name] = input.value.trim();
  }

  const response = await fetch(`${API}/config`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(values),
  });

  if (!response.ok) {
    toast(await errorText(response), "error");
    return;
  }

  toast("Settings saved.");
  await loadSettings();
}

/* ---------------- Strong's ---------------- */

async function openStrong(code) {
  if (!code) return;

  const card = el("strong-card");
  const body = el("strong-body");
  card.hidden = false;
  body.textContent = `Looking up ${code}…`;

  const response = await fetch(`${API}/strongs/${encodeURIComponent(code)}`);

  if (!response.ok) {
    body.textContent = await errorText(response);
    return;
  }

  const entry = await response.json();
  const title = document.createElement("h3");
  title.textContent = `${entry.code} ${entry.lemma || ""}`.trim();

  const list = document.createElement("dl");

  for (const [label, value] of [
    ["Transliteration", entry.transliteration],
    ["Definition", entry.definition],
    ["Description", entry.description],
  ]) {
    if (!value) continue;

    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    list.append(term, detail);
  }

  body.replaceChildren(title, list);
}

/* ---------------- panels, toasts, chrome ---------------- */

function openPanel(name) {
  const panel = PANELS[name];
  if (!panel) return;

  state.panel = name;
  el("panel").hidden = false;
  el("panel-title").textContent = panel.title;

  for (const key of Object.keys(PANELS)) {
    el(`panel-${key}`).hidden = key !== name;
  }

  for (const button of document.querySelectorAll("[data-panel]")) {
    button.dataset.active = button.dataset.panel === name ? "true" : "false";
  }

  panel.open();
}

function closePanel() {
  state.panel = null;
  el("panel").hidden = true;

  for (const button of document.querySelectorAll("[data-panel]")) {
    button.dataset.active = "false";
  }
}

function togglePanel(name) {
  if (state.panel === name) {
    closePanel();
    return;
  }

  openPanel(name);
}

function renderShortcuts() {
  el("shortcuts").replaceChildren(
    ...SHORTCUTS.flatMap(([keys, description]) => {
      const term = document.createElement("dt");
      term.textContent = keys;
      const detail = document.createElement("dd");
      detail.textContent = description;
      return [term, detail];
    })
  );
}

function toast(message, kind = "info") {
  const node = document.createElement("div");
  node.className = "toast";
  node.dataset.kind = kind;
  node.textContent = message;
  el("toasts").append(node);
  setTimeout(() => node.remove(), TOAST_MS);
}

function setTheme(value) {
  document.documentElement.dataset.theme = value;

  try {
    localStorage.setItem("bibleit-operator-theme", value);
  } catch (_error) {
    /* private windows refuse storage; the theme just will not persist */
  }
}

function storedTheme() {
  try {
    return localStorage.getItem("bibleit-operator-theme");
  } catch (_error) {
    return null;
  }
}

function toggleTheme() {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
}

/* ---------------- keyboard ---------------- */

const KEYS = {
  ArrowDown: () => send("next_verse"),
  ArrowUp: () => send("previous_verse"),
  j: () => send("next_verse"),
  k: () => send("previous_verse"),
  ",": () => send("previous_chapter"),
  ".": () => send("next_chapter"),
  Home: () => send("chapter_start"),
  End: () => send("chapter_end"),
  l: toggleLive,
  t: () => togglePanel("library"),
  b: () => togglePanel("books"),
  f: () => togglePanel("find"),
  s: () => togglePanel("share"),
  h: toggleStrongs,
  d: toggleTheme,
  "?": () => togglePanel("help"),
};

function toggleLive() {
  send("set_live", { live: !state.snapshot?.live });
}

function toggleStrongs() {
  send("set_strongs", { strongs: !state.snapshot?.strongs });
}

function onKeyDown(event) {
  if (event.metaKey || event.altKey) return;

  const typing = event.target.closest("input, textarea, select");

  if (typing) {
    if (event.key === "Escape") {
      hideCandidates();
      event.target.blur();
    }

    if (event.target === el("goto-input") && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      if (moveCandidate(event.key === "ArrowDown" ? 1 : -1)) event.preventDefault();
    }

    return;
  }

  if (event.key === "Escape") {
    el("strong-card").hidden = true;
    closePanel();
    return;
  }

  if (event.key === "g" || event.key === ":" || event.key === "@" || event.key === "/") {
    event.preventDefault();
    el("goto-input").focus();
    el("goto-input").select();
    return;
  }

  if (event.ctrlKey) {
    if (event.key === "f") {
      event.preventDefault();
      togglePanel("find");
    }

    if (event.key === "g") {
      event.preventDefault();
      toggleStrongs();
    }

    return;
  }

  const action = KEYS[event.key];

  if (action) {
    event.preventDefault();
    action();
  }
}

/* ---------------- wiring ---------------- */

function start() {
  setTheme(storedTheme() || "light");

  el("goto-form").addEventListener("submit", submitGoto);
  el("goto-input").addEventListener("input", (event) => {
    clearTimeout(resolveTimer);
    const value = event.target.value;

    if (!value.trim()) {
      hideCandidates();
      return;
    }

    resolveTimer = setTimeout(() => resolve(value), RESOLVE_DEBOUNCE_MS);
  });

  el("live-toggle").addEventListener("click", toggleLive);
  el("strongs-toggle").addEventListener("click", toggleStrongs);
  el("theme-toggle").addEventListener("click", toggleTheme);
  el("panel-close").addEventListener("click", closePanel);
  el("share-copy").addEventListener("click", copyShare);
  el("settings-form").addEventListener("submit", saveSettings);
  el("strong-close").addEventListener("click", () => {
    el("strong-card").hidden = true;
  });

  el("find-input").addEventListener("input", () => {
    clearTimeout(findTimer);
    findTimer = setTimeout(runFind, FIND_DEBOUNCE_MS);
  });

  el("find-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runFind();
  });

  for (const button of document.querySelectorAll("[data-panel]")) {
    button.addEventListener("click", () => togglePanel(button.dataset.panel));
  }

  for (const button of document.querySelectorAll("[data-command]")) {
    button.addEventListener("click", () => send(button.dataset.command));
  }

  document.addEventListener("keydown", onKeyDown);

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".goto")) hideCandidates();
  });

  connect();
}

start();
