const resultsContainer = document.getElementById("resultsContainer");
const statusText = document.getElementById("statusText");

// --- Filter state (only committed to `activeFilters` when Apply Filters is clicked) ---

let activeFilters = null;
let oldestLoadedId = null; // for scroll-up pagination
let newestLoadedId = null; // for live mode polling
let isLoadingMore = false;
let reachedStart = false;
let liveModeTimer = null;
let selectedMemberId = null;
let selectedMemberDisplay = null;

// Rows currently displayed, oldest first -- kept as the single source of truth so toggling
// Old School mode can re-render without losing what's already loaded or re-fetching.
let loadedRows = [];

function resultsListEl() {
  return document.getElementById("resultsList");
}

function currentDateRange() {
  const active = document.querySelector("#datePresets button.active");
  const preset = active ? active.dataset.preset : "all";
  const now = new Date();

  function startOfDay(d) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
  }

  switch (preset) {
    case "today":
      return { date_from: startOfDay(now).toISOString(), date_to: null };
    case "yesterday": {
      const y = new Date(now);
      y.setDate(y.getDate() - 1);
      const start = startOfDay(y);
      const end = startOfDay(now);
      return { date_from: start.toISOString(), date_to: end.toISOString() };
    }
    case "7days": {
      const from = new Date(now);
      from.setDate(from.getDate() - 7);
      return { date_from: from.toISOString(), date_to: null };
    }
    case "30days": {
      const from = new Date(now);
      from.setDate(from.getDate() - 30);
      return { date_from: from.toISOString(), date_to: null };
    }
    case "ytd": {
      const from = new Date(now.getFullYear(), 0, 1);
      return { date_from: from.toISOString(), date_to: null };
    }
    case "custom": {
      const fromVal = document.getElementById("dateFromInput").value;
      const toVal = document.getElementById("dateToInput").value;
      return {
        date_from: fromVal ? new Date(fromVal).toISOString() : null,
        date_to: toVal ? new Date(toVal + "T23:59:59").toISOString() : null,
      };
    }
    default:
      return { date_from: null, date_to: null };
  }
}

function buildFiltersFromForm() {
  const range = currentDateRange();
  return {
    query: document.getElementById("queryInput").value.trim() || null,
    regex: document.getElementById("regexToggle").checked,
    member_id: selectedMemberId,
    exclude_broadcasts: document.getElementById("excludeBroadcastsToggle").checked,
    date_from: range.date_from,
    date_to: range.date_to,
  };
}

function filtersToQueryParams(filters, extra) {
  const params = new URLSearchParams();
  if (filters.query) params.set("q", filters.query);
  if (filters.regex) params.set("regex", "true");
  if (filters.member_id) params.set("member_id", filters.member_id);
  if (filters.exclude_broadcasts) params.set("exclude_broadcasts", "true");
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      if (v !== null && v !== undefined) params.set(k, v);
    }
  }
  return params;
}

// --- Date preset buttons ---

document.getElementById("datePresets").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  document.querySelectorAll("#datePresets button").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("customRange").classList.toggle("visible", btn.dataset.preset === "custom");
});

// --- RSN typeahead ---

const rsnInput = document.getElementById("rsnInput");
const rsnResults = document.getElementById("rsnResults");
let typeaheadDebounce = null;

rsnInput.addEventListener("input", () => {
  selectedMemberId = null;
  selectedMemberDisplay = null;
  const q = rsnInput.value.trim();
  clearTimeout(typeaheadDebounce);
  if (q.length < 1) {
    rsnResults.classList.remove("visible");
    return;
  }
  typeaheadDebounce = setTimeout(async () => {
    try {
      const res = await fetch(`/api/members/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) return;
      const matches = await res.json();
      rsnResults.innerHTML = "";
      if (matches.length === 0) {
        rsnResults.classList.remove("visible");
        return;
      }
      for (const m of matches) {
        const div = document.createElement("div");
        div.textContent = m.display_rsn;
        div.addEventListener("click", () => {
          selectedMemberId = m.member_id;
          selectedMemberDisplay = m.display_rsn;
          rsnInput.value = m.display_rsn;
          rsnResults.classList.remove("visible");
        });
        rsnResults.appendChild(div);
      }
      rsnResults.classList.add("visible");
    } catch {
      // ignore transient typeahead failures
    }
  }, 250);
});

document.addEventListener("click", (e) => {
  if (!rsnResults.contains(e.target) && e.target !== rsnInput) {
    rsnResults.classList.remove("visible");
  }
});

// --- Rendering ---

function formatTimestamp(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isBroadcast(row) {
  return row.sender.toLowerCase() === row.chat_name.toLowerCase() && row.rank === -2;
}

function rankIconPath(rankName) {
  if (!rankName) return null;
  const normalized = rankName.toLowerCase().replace(/[ _\-.]/g, "");
  return `static/rank-icons/${normalized}.png`;
}

// Broadcast messages embed the game client's <img=N> tag syntax for the sender's ironman-mode
// badge (e.g. "<img=41> Some Player received a drop: ..."). Only the codes actually vendored in
// static/broadcast-icons/ are rendered as images; any other code is left as literal text.
const BROADCAST_IMG_TAG = /<img=(\d+)>/g;

function appendMessageContent(container, message) {
  let lastIndex = 0;
  for (const match of message.matchAll(BROADCAST_IMG_TAG)) {
    if (match.index > lastIndex) {
      container.appendChild(document.createTextNode(message.slice(lastIndex, match.index)));
    }
    const icon = document.createElement("img");
    icon.className = "broadcast-icon";
    icon.src = `static/broadcast-icons/img${match[1]}.png`;
    icon.alt = "";
    icon.onerror = () => icon.remove();
    container.appendChild(icon);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < message.length) {
    container.appendChild(document.createTextNode(message.slice(lastIndex)));
  }
}

function buildRowElement(row) {
  const div = document.createElement("div");
  div.className = "chat-row" + (isBroadcast(row) ? " broadcast" : "");
  div.dataset.id = row.id;

  const ts = document.createElement("span");
  ts.className = "timestamp";
  ts.textContent = `[${formatTimestamp(row.message_timestamp)}]`;
  div.appendChild(ts);

  const iconPath = rankIconPath(row.sender_rank_name);
  if (iconPath) {
    const icon = document.createElement("img");
    icon.className = "rank-icon";
    icon.src = iconPath;
    icon.alt = row.sender_rank_name || "";
    icon.onerror = () => icon.remove();
    div.appendChild(icon);
  }

  const sender = document.createElement("span");
  sender.className = "sender";
  sender.textContent = row.sender + ":";
  div.appendChild(sender);

  const message = document.createElement("span");
  message.className = "message";
  appendMessageContent(message, row.message);
  div.appendChild(message);

  return div;
}

// Rebuilds the DOM container to match the current Old School toggle state, then re-renders
// every row in `loadedRows`. Used on Old School toggle and after a fresh search.
function rebuildResultsContainer() {
  const oldSchool = document.getElementById("oldSchoolToggle").checked;
  resultsContainer.classList.toggle("old-school", oldSchool);
  if (oldSchool) {
    resultsContainer.innerHTML = `
      <div class="chatbox-top"></div>
      <div class="chatbox-middle"><div class="results-list" id="resultsList"></div></div>
      <div class="chatbox-bottom"></div>
    `;
  } else {
    resultsContainer.innerHTML = '<div class="results-list" id="resultsList"></div>';
  }
}

function rerenderAll() {
  rebuildResultsContainer();
  const list = resultsListEl();
  if (loadedRows.length === 0) {
    list.innerHTML = '<div class="no-results">No messages match these filters.</div>';
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const row of loadedRows) {
    fragment.appendChild(buildRowElement(row));
  }
  list.appendChild(fragment);
}

// --- Apply Filters: single lookup, replaces current result set ---

document.getElementById("applyFiltersBtn").addEventListener("click", async () => {
  activeFilters = buildFiltersFromForm();
  await runInitialSearch();
});

async function runInitialSearch() {
  stopLiveMode();
  loadedRows = [];
  oldestLoadedId = null;
  newestLoadedId = null;
  reachedStart = false;
  statusText.textContent = "Loading...";

  try {
    const params = filtersToQueryParams(activeFilters);
    const res = await fetch(`/api/search?${params.toString()}`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      statusText.textContent = body.detail || "Search failed.";
      return;
    }
    const page = await res.json();
    // API returns newest-first; keep loadedRows oldest-first (top to bottom = chronological).
    loadedRows = [...page.results].reverse();
    rerenderAll();

    if (page.results.length > 0) {
      newestLoadedId = page.results[0].id;
      oldestLoadedId = page.results[page.results.length - 1].id;
    }
    reachedStart = page.next_cursor === null;
    resultsContainer.scrollTop = resultsContainer.scrollHeight;
    statusText.textContent = "";

    if (document.getElementById("liveModeToggle").checked) {
      startLiveMode();
    }
  } catch (err) {
    statusText.textContent = "Search failed: " + err;
  }
}

// --- Infinite scroll upward (older messages) ---

resultsContainer.addEventListener("scroll", async () => {
  if (resultsContainer.scrollTop > 80 || isLoadingMore || reachedStart || !activeFilters) return;
  isLoadingMore = true;
  const previousHeight = resultsContainer.scrollHeight;
  const list = resultsListEl();
  const loadingEl = document.createElement("div");
  loadingEl.className = "loading-more";
  loadingEl.textContent = "Loading older messages...";
  list.insertBefore(loadingEl, list.firstChild);

  try {
    const params = filtersToQueryParams(activeFilters, { before_id: oldestLoadedId });
    const res = await fetch(`/api/search?${params.toString()}`);
    const page = await res.json();
    loadingEl.remove();

    if (page.results.length === 0) {
      reachedStart = true;
    } else {
      // page.results is newest-first; prepend oldest-first so loadedRows stays chronological.
      const olderRows = [...page.results].reverse();
      loadedRows = [...olderRows, ...loadedRows];
      const fragment = document.createDocumentFragment();
      for (const row of olderRows) {
        fragment.appendChild(buildRowElement(row));
      }
      list.insertBefore(fragment, list.firstChild);
      oldestLoadedId = page.results[page.results.length - 1].id;
      reachedStart = page.next_cursor === null;
      resultsContainer.scrollTop = resultsContainer.scrollHeight - previousHeight;
    }
  } catch {
    loadingEl.remove();
  } finally {
    isLoadingMore = false;
  }
});

// --- Live mode: poll for new messages, append without pruning older ones ---

function startLiveMode() {
  stopLiveMode();
  liveModeTimer = setInterval(async () => {
    if (!activeFilters || newestLoadedId === null) return;
    try {
      const params = filtersToQueryParams(activeFilters, { after_id: newestLoadedId });
      const res = await fetch(`/api/search?${params.toString()}`);
      if (!res.ok) return;
      const page = await res.json();
      if (page.results.length === 0) return;
      const wasAtBottom =
        resultsContainer.scrollHeight - resultsContainer.scrollTop - resultsContainer.clientHeight < 40;
      loadedRows = [...loadedRows, ...page.results];
      const list = resultsListEl();
      const fragment = document.createDocumentFragment();
      for (const row of page.results) {
        fragment.appendChild(buildRowElement(row));
      }
      list.appendChild(fragment);
      newestLoadedId = page.results[page.results.length - 1].id;
      if (wasAtBottom) {
        resultsContainer.scrollTop = resultsContainer.scrollHeight;
      }
    } catch {
      // ignore transient poll failures, try again next interval
    }
  }, 10000);
}

function stopLiveMode() {
  if (liveModeTimer) {
    clearInterval(liveModeTimer);
    liveModeTimer = null;
  }
}

document.getElementById("liveModeToggle").addEventListener("change", (e) => {
  if (e.target.checked && activeFilters) {
    startLiveMode();
  } else {
    stopLiveMode();
  }
});

// --- Old School UI toggle: pure client-side re-render of the same loaded rows ---

document.getElementById("oldSchoolToggle").addEventListener("change", () => {
  rerenderAll();
});

// --- Export: full matching set, not just the loaded page ---

document.getElementById("exportBtn").addEventListener("click", () => {
  const filters = activeFilters || buildFiltersFromForm();
  const params = filtersToQueryParams(filters);
  window.location.href = `/api/export?${params.toString()}`;
});

// --- Initial load: show the most recent messages immediately, as though no filters were
// applied, so the page isn't blank before the user has touched any filter control. ---

activeFilters = buildFiltersFromForm();
runInitialSearch();
