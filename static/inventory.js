const state = {
  dataset: "latest",
  page: 1,
  perPage: 25,
  search: "",
  sortBy: "product_name",
  sortOrder: "asc",
  totalPages: 0,
  total: 0,
  seeding: false,
  rows: [],
};

const datasetSelect = document.getElementById("dataset");
const perPageSelect = document.getElementById("per-page");
const tableHead = document.getElementById("table-head");
const tableBody = document.getElementById("table-body");
const tableTitle = document.getElementById("table-title");
const metaText = document.getElementById("meta-text");
const pageLabel = document.getElementById("page-label");
const firstBtn = document.getElementById("first-btn");
const prevBtn = document.getElementById("prev-btn");
const nextBtn = document.getElementById("next-btn");
const lastBtn = document.getElementById("last-btn");
const searchInput = document.getElementById("search-input");
const sortBySelect = document.getElementById("sort-by");
const sortOrderSelect = document.getElementById("sort-order");
const applyFilterBtn = document.getElementById("apply-filter-btn");
const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");
const chatStatus = document.getElementById("chat-status");
const promptButtons = document.querySelectorAll(".chip[data-prompt]");
const refreshBtn = document.getElementById("refresh-products-seo-btn");
const refreshStatus = document.getElementById("refresh-status");
const seoMaxInput = document.getElementById("seo-max-products");
const postSocialBtn = document.getElementById("post-social-btn");

function endpointForDataset() {
  return state.dataset === "history" ? "/api/inventory/history" : "/api/inventory/latest";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderTextWithLinks(value) {
  const text = String(value ?? "");
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  const singleUrlRegex = /^https?:\/\/[^\s]+$/i;
  const parts = text.split(urlRegex);
  return parts
    .map((part) => {
      if (singleUrlRegex.test(part)) {
        const safeUrl = escapeHtml(part);
        return `<a class="cell-link" href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>`;
      }
      return escapeHtml(part);
    })
    .join("");
}

function renderTable() {
  const rows = state.rows || [];
  const hiddenColumns = new Set(["scraped_at_utc"]);
  const headers = rows.length ? Object.keys(rows[0]).filter((h) => !hiddenColumns.has(h)) : [];

  tableHead.innerHTML = headers.length
    ? `<tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr>`
    : "<tr><th>No data</th></tr>";

  if (!rows.length) {
    tableBody.innerHTML = '<tr><td colspan="100%">No rows found.</td></tr>';
    return;
  }

  const html = rows
    .map((row) => {
      const tds = headers
        .map((key) => {
          const val = row[key] ?? "";
          if (key === "image_url" && String(val).startsWith("http")) {
            return `<td><img class="thumb" src="${escapeHtml(val)}" alt="product image"></td>`;
          }
          if (key === "stock_text") {
            const count = Number.parseInt(row.in_stock || "0", 10) || 0;
            const stockClass = count <= 0 ? "stock-red" : count < 10 ? "stock-yellow" : "stock-green";
            return `<td><span class="stock-pill ${stockClass}">${escapeHtml(val)}</span></td>`;
          }
          if ((key === "product_url" || key === "image_url") && String(val).startsWith("http")) {
            return `<td><a class="cell-link" href="${escapeHtml(val)}" target="_blank" rel="noopener noreferrer">open</a></td>`;
          }
          return `<td>${escapeHtml(val)}</td>`;
        })
        .join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");
  tableBody.innerHTML = html;
}

function updatePaginationUi() {
  const page = state.totalPages ? state.page : 0;
  pageLabel.textContent = `Page ${page} / ${state.totalPages || 0}`;
  if (state.seeding && state.total === 0) {
    metaText.textContent = "Initial sync in progress... data will appear automatically.";
  } else {
    metaText.textContent = `${state.total.toLocaleString()} rows total`;
  }
  tableTitle.textContent = state.dataset === "history" ? "Inventory History" : "Latest Inventory";

  const disabledAtStart = state.page <= 1 || state.totalPages === 0;
  const disabledAtEnd = state.page >= state.totalPages || state.totalPages === 0;

  firstBtn.disabled = disabledAtStart;
  prevBtn.disabled = disabledAtStart;
  nextBtn.disabled = disabledAtEnd;
  lastBtn.disabled = disabledAtEnd;
}

async function fetchPage() {
  const params = new URLSearchParams({
    page: String(state.page),
    per_page: String(state.perPage),
    search: state.search,
    sort_by: state.sortBy,
    sort_order: state.sortOrder,
  });
  const url = `${endpointForDataset()}?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load table data: ${res.status}`);
  }
  const data = await res.json();
  state.rows = data.rows || [];
  state.totalPages = data.total_pages || 0;
  state.total = data.total || 0;
  state.seeding = Boolean(data.seeding);
  state.page = data.page || 1;
  renderTable();
  updatePaginationUi();

  if (state.seeding && state.total === 0) {
    setTimeout(() => {
      fetchPage().catch((err) => {
        metaText.textContent = err.message;
      });
    }, 5000);
  }
}

async function reloadToFirstPage() {
  state.page = 1;
  await fetchPage();
}

datasetSelect.addEventListener("change", async () => {
  state.dataset = datasetSelect.value;
  await reloadToFirstPage();
});

perPageSelect.addEventListener("change", async () => {
  state.perPage = Number.parseInt(perPageSelect.value, 10) || 25;
  await reloadToFirstPage();
});

async function applyFilters() {
  state.search = (searchInput?.value || "").trim();
  state.sortBy = sortBySelect?.value || "product_name";
  state.sortOrder = sortOrderSelect?.value || "asc";
  await reloadToFirstPage();
}

if (applyFilterBtn) {
  applyFilterBtn.addEventListener("click", applyFilters);
}

if (searchInput) {
  searchInput.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      await applyFilters();
    }
  });
}

firstBtn.addEventListener("click", async () => {
  if (state.page <= 1) return;
  state.page = 1;
  await fetchPage();
});

prevBtn.addEventListener("click", async () => {
  if (state.page <= 1) return;
  state.page -= 1;
  await fetchPage();
});

nextBtn.addEventListener("click", async () => {
  if (state.page >= state.totalPages) return;
  state.page += 1;
  await fetchPage();
});

lastBtn.addEventListener("click", async () => {
  if (state.totalPages === 0 || state.page >= state.totalPages) return;
  state.page = state.totalPages;
  await fetchPage();
});

fetchPage().catch((err) => {
  metaText.textContent = err.message;
  tableHead.innerHTML = "<tr><th>Error</th></tr>";
  tableBody.innerHTML = `<tr><td>${escapeHtml(err.message)}</td></tr>`;
});

function appendChatMessage(role, text) {
  if (!chatLog) return;
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  const label = role === "user" ? "Customer" : "AI Assistant";
  div.innerHTML = `<b>${escapeHtml(label)}:</b> ${renderTextWithLinks(text)}`;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function sendChatMessage(message) {
  appendChatMessage("user", message);
  chatStatus.textContent = "Thinking...";
  chatSend.disabled = true;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90000);
    let res;
    try {
      res = await fetch(`${window.location.origin}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
    } catch (_firstErr) {
      // Fallback alias for proxies routing only /api/*.
      res = await fetch(`${window.location.origin}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeoutId);
    }

    if (!res) {
      throw new Error("Chat request could not be created.");
    }

    let data = null;
    try {
      data = await res.json();
    } catch (_jsonErr) {
      data = {};
    }
    if (!res.ok) {
      throw new Error(data.error || `Chat request failed (${res.status})`);
    }
    appendChatMessage("assistant", data.answer || "No answer returned.");
    chatStatus.textContent = "Response received.";
  } catch (err) {
    const msg = err?.name === "AbortError"
      ? "Request timed out. Please try again."
      : (err?.message || "Network error contacting chat service.");
    appendChatMessage("assistant", `Error: ${msg}`);
    chatStatus.textContent = "Chat failed.";
  } finally {
    chatSend.disabled = false;
  }
}

async function postSocialUpdate() {
  if (!postSocialBtn || !refreshStatus) return;
  postSocialBtn.disabled = true;
  refreshStatus.textContent = "Refreshing products and posting social update...";
  try {
    const res = await fetch("/automation/post-social-update", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });
    if (res.status === 401 || res.status === 403) {
      const token = window.prompt("Enter AUTOMATION_API_TOKEN:");
      if (!token) {
        refreshStatus.textContent = "Social update cancelled.";
        postSocialBtn.disabled = false;
        return;
      }
      const retry = await fetch("/automation/post-social-update", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({}),
      });
      const retryData = await retry.json();
      if (!retry.ok) {
        throw new Error(retryData.error || `Social update failed (${retry.status})`);
      }
      const mode = retryData.posted ? "posted live" : "generated (dry-run)";
      refreshStatus.textContent = `Social update ${mode}. Asset file: ${retryData.asset_file}`;
      await reloadToFirstPage();
      return;
    }
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `Social update failed (${res.status})`);
    }
    const mode = data.posted ? "posted live" : "generated (dry-run)";
    refreshStatus.textContent = `Social update ${mode}. Asset file: ${data.asset_file}`;
    await reloadToFirstPage();
  } catch (err) {
    refreshStatus.textContent = `Social update error: ${err.message}`;
  } finally {
    postSocialBtn.disabled = false;
  }
}

if (chatLog && chatForm && chatInput && chatSend) {
  appendChatMessage(
    "assistant",
    "Welcome to MiningCave AI support. Ask me about stock, prices, shipping, and product recommendations."
  );

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    chatInput.value = "";
    await sendChatMessage(message);
  });

  promptButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const msg = btn.getAttribute("data-prompt") || "";
      if (!msg) return;
      await sendChatMessage(msg);
    });
  });
}

async function refreshProductsAndSeo() {
  if (!refreshBtn || !refreshStatus) return;

  const maxSeoProducts = Number.parseInt(seoMaxInput?.value || "50", 10) || 50;
  refreshBtn.disabled = true;
  refreshStatus.textContent = "Refreshing products and SEO CSV... this may take a while.";
  try {
    const res = await fetch("/automation/refresh-products-seo", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ max_seo_products: maxSeoProducts }),
    });
    if (res.status === 401 || res.status === 403) {
      const token = window.prompt("Enter AUTOMATION_API_TOKEN:");
      if (!token) {
        refreshStatus.textContent = "Refresh cancelled.";
        refreshBtn.disabled = false;
        return;
      }
      const retry = await fetch("/automation/refresh-products-seo", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ max_seo_products: maxSeoProducts }),
      });
      const retryData = await retry.json();
      if (!retry.ok) {
        throw new Error(retryData.error || `Refresh failed (${retry.status})`);
      }
      refreshStatus.textContent = `Refresh done. SEO rows: ${retryData.seo_rows_written}. Output: ${retryData.seo_output_csv}`;
      await reloadToFirstPage();
      return;
    }
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `Refresh failed (${res.status})`);
    }
    refreshStatus.textContent = `Refresh done. SEO rows: ${data.seo_rows_written}. Output: ${data.seo_output_csv}`;
    await reloadToFirstPage();
  } catch (err) {
    refreshStatus.textContent = `Refresh error: ${err.message}`;
  } finally {
    refreshBtn.disabled = false;
  }
}

if (refreshBtn) {
  refreshBtn.addEventListener("click", refreshProductsAndSeo);
}

if (postSocialBtn) {
  postSocialBtn.addEventListener("click", postSocialUpdate);
}
