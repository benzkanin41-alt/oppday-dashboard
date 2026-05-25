const state = {
  items: [],
  filtered: [],
  selectedId: null,
  selectedSource: "",
  selectedItem: null,
  activeView: "summary",
  staticMode: false,
};

const els = {
  refreshBtn: document.querySelector("#refreshBtn"),
  searchInput: document.querySelector("#searchInput"),
  quarterSelect: document.querySelector("#quarterSelect"),
  sourceButtons: document.querySelectorAll(".segmented button"),
  results: document.querySelector("#results"),
  itemCount: document.querySelector("#itemCount"),
  symbolCount: document.querySelector("#symbolCount"),
  markdownCount: document.querySelector("#markdownCount"),
  pdfCount: document.querySelector("#pdfCount"),
  lastUpdated: document.querySelector("#lastUpdated"),
  emptyState: document.querySelector("#emptyState"),
  detailPanel: document.querySelector("#detailPanel"),
  detailMeta: document.querySelector("#detailMeta"),
  detailTitle: document.querySelector("#detailTitle"),
  detailPath: document.querySelector("#detailPath"),
  fileList: document.querySelector("#fileList"),
  summaryTab: document.querySelector("#summaryTab"),
  pdfTab: document.querySelector("#pdfTab"),
  openPdfLink: document.querySelector("#openPdfLink"),
  markdownView: document.querySelector("#markdownView"),
  pdfView: document.querySelector("#pdfView"),
  pdfFrame: document.querySelector("#pdfFrame"),
};

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("th-TH", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  return `${size.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inlineMarkdown(value) {
  let safe = escapeHtml(value);
  safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");
  safe = safe.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  safe = safe.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return safe;
}

function renderTable(lines) {
  const rows = lines
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line))
    .map((line) =>
      line
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => inlineMarkdown(cell.trim())),
    );
  if (!rows.length) return "";
  const [head, ...body] = rows;
  return `<table><thead><tr>${head.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead><tbody>${body
    .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;
}

function renderMarkdown(markdown) {
  if (!markdown) {
    return `<div class="empty-state"><h2>รายการนี้ไม่มี Markdown summary</h2><p>ใช้แท็บ PDF เพื่ออ่านไฟล์ presentation แทน</p></div>`;
  }

  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1;
      html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    if (trimmed.startsWith("|") && lines[i + 1]?.includes("|")) {
      const table = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        table.push(lines[i]);
        i += 1;
      }
      html.push(renderTable(table));
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ""));
        i += 1;
      }
      html.push(`<ul>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      html.push(`<ol>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ol>`);
      continue;
    }

    if (/^-{3,}$/.test(trimmed)) {
      html.push("<hr>");
      i += 1;
      continue;
    }

    const paragraph = [trimmed];
    i += 1;
    while (i < lines.length && lines[i].trim() && !/^(#{1,3})\s+/.test(lines[i].trim())) {
      if (lines[i].trim().startsWith("|") || /^[-*]\s+/.test(lines[i].trim()) || /^\d+\.\s+/.test(lines[i].trim())) break;
      paragraph.push(lines[i].trim());
      i += 1;
    }
    html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
  }

  return html.join("\n");
}

function setLoading(message) {
  els.lastUpdated.textContent = message;
}

async function loadIndex(refresh = false) {
  setLoading(refresh ? "กำลัง refresh index..." : "กำลังโหลด index...");
  let response = await fetch(`/api/index${refresh ? "?refresh=1" : ""}`);
  if (!response.ok) {
    response = await fetch(`data/index.json?ts=${Date.now()}`);
    state.staticMode = true;
  } else {
    state.staticMode = false;
  }
  if (!response.ok) throw new Error(`Index failed: ${response.status}`);
  const payload = await response.json();
  state.staticMode = state.staticMode || payload.mode === "static";
  state.items = payload.items || [];

  els.itemCount.textContent = payload.stats?.items ?? 0;
  els.symbolCount.textContent = payload.stats?.symbols ?? 0;
  els.markdownCount.textContent = payload.stats?.markdownItems ?? 0;
  els.pdfCount.textContent = payload.stats?.pdfItems ?? 0;
  els.lastUpdated.textContent = `อัปเดตล่าสุด ${formatDateTime(payload.updatedAt)} | ${state.staticMode ? "sync จาก OneDrive 18:00" : "auto refresh 18:00"}`;

  renderQuarterOptions(payload.stats?.quarters || []);
  applyFilters();
}

function renderQuarterOptions(quarters) {
  const current = els.quarterSelect.value;
  els.quarterSelect.innerHTML = `<option value="">ทุกไตรมาส</option>`;
  quarters.forEach((quarter) => {
    const option = document.createElement("option");
    option.value = quarter;
    option.textContent = quarter;
    els.quarterSelect.append(option);
  });
  if (quarters.includes(current)) els.quarterSelect.value = current;
}

function applyFilters() {
  const query = els.searchInput.value.trim().toLowerCase();
  const quarter = els.quarterSelect.value;
  const source = state.selectedSource;
  state.filtered = state.items.filter((item) => {
    const queryOk = !query || item.searchText.includes(query);
    const quarterOk = !quarter || item.quarter === quarter;
    const sourceOk = !source || item.source === source;
    return queryOk && quarterOk && sourceOk;
  });
  renderResults();
}

function renderResults() {
  if (!state.filtered.length) {
    els.results.innerHTML = `<div class="result-card"><div class="symbol">ไม่พบรายการ</div><div class="chips"><span class="chip">ลองเปลี่ยนคำค้นหรือไตรมาส</span></div></div>`;
    return;
  }

  els.results.innerHTML = state.filtered
    .slice(0, 400)
    .map((item) => {
      const active = item.id === state.selectedId ? " active" : "";
      const kinds = [item.hasMarkdown ? "สรุป" : null, item.hasPdf ? "PDF" : null].filter(Boolean);
      return `<button class="result-card${active}" data-id="${item.id}">
        <div class="result-top">
          <div>
            <div class="symbol">${escapeHtml(item.symbol)}</div>
            <div class="muted">${escapeHtml(item.title)}</div>
          </div>
          <span class="chip strong">${escapeHtml(item.quarter)}</span>
        </div>
        <div class="chips">
          <span class="chip">${escapeHtml(item.source)}</span>
          ${item.eventDate ? `<span class="chip">${escapeHtml(item.eventDate)}</span>` : ""}
          ${kinds.map((kind) => `<span class="chip">${kind}</span>`).join("")}
        </div>
      </button>`;
    })
    .join("");

  els.results.querySelectorAll(".result-card[data-id]").forEach((button) => {
    button.addEventListener("click", () => loadItem(button.dataset.id));
  });
}

async function loadItem(id) {
  state.selectedId = id;
  renderResults();
  let response = await fetch(`/api/item/${id}`);
  if (!response.ok && state.staticMode) {
    response = await fetch(`data/items/${id}.json?ts=${Date.now()}`);
  }
  if (!response.ok) throw new Error(`Item failed: ${response.status}`);
  const payload = await response.json();
  state.selectedItem = payload.item;
  state.activeView = payload.item.primaryMarkdownId || state.staticMode ? "summary" : "pdf";
  renderDetail();
}

function renderDetail() {
  const item = state.selectedItem;
  if (!item) return;

  els.emptyState.classList.add("hidden");
  els.detailPanel.classList.remove("hidden");
  els.detailMeta.textContent = `${item.source} | ${item.quarter}${item.eventDate ? ` | ${item.eventDate}` : ""}`;
  els.detailTitle.textContent = `${item.symbol} - ${item.period}`;
  els.detailPath.textContent = item.sourceFolder;

  els.fileList.innerHTML = item.files
    .map((file) => `<span class="file-pill">${escapeHtml(file.extension.toUpperCase())} ${escapeHtml(file.name)} · ${formatBytes(file.size)}</span>`)
    .join("");

  els.markdownView.innerHTML = renderMarkdown(item.markdown);

  const openFileId = item.primaryPdfId || item.primaryMarkdownId;
  if (item.primaryPdfId && !state.staticMode) {
    els.pdfFrame.src = `/file/${item.primaryPdfId}`;
    els.pdfTab.disabled = false;
  } else {
    els.pdfFrame.removeAttribute("src");
    els.pdfTab.disabled = true;
  }

  if (openFileId && !state.staticMode) {
    els.openPdfLink.href = `/file/${openFileId}`;
    els.openPdfLink.classList.remove("hidden");
  } else {
    els.openPdfLink.removeAttribute("href");
    els.openPdfLink.classList.add("hidden");
  }

  setActiveView(state.activeView);
}

function setActiveView(view) {
  state.activeView = view;
  els.summaryTab.classList.toggle("active", view === "summary");
  els.pdfTab.classList.toggle("active", view === "pdf");
  els.markdownView.classList.toggle("hidden", view !== "summary");
  els.pdfView.classList.toggle("hidden", view !== "pdf");
}

els.refreshBtn.addEventListener("click", async () => {
  els.refreshBtn.disabled = true;
  try {
    await loadIndex(true);
  } finally {
    els.refreshBtn.disabled = false;
  }
});

els.searchInput.addEventListener("input", applyFilters);
els.quarterSelect.addEventListener("change", applyFilters);
els.summaryTab.addEventListener("click", () => setActiveView("summary"));
els.pdfTab.addEventListener("click", () => {
  if (!els.pdfTab.disabled) setActiveView("pdf");
});

els.sourceButtons.forEach((button) => {
  button.addEventListener("click", () => {
    els.sourceButtons.forEach((candidate) => candidate.classList.remove("active"));
    button.classList.add("active");
    state.selectedSource = button.dataset.source;
    applyFilters();
  });
});

loadIndex().catch((error) => {
  console.error(error);
  setLoading(`โหลด index ไม่สำเร็จ: ${error.message}`);
});
