"use strict";

// ── 設定 ──
const DATA_URL = "data/cannes_winners.json";

// ── 狀態 ──
let allData = [];
let filtered = [];

// ── DOM ──
const searchInput     = document.getElementById("search-input");
const filterYear      = document.getElementById("filter-year");
const filterAward     = document.getElementById("filter-award");
const filterCategory  = document.getElementById("filter-category");
const filterMedia     = document.getElementById("filter-media");
const clearBtn        = document.getElementById("clear-filters");
const cardsContainer  = document.getElementById("cards-container");
const resultsCount    = document.getElementById("results-count");
const totalCount      = document.getElementById("total-count");

// ── 初始化 ──
async function init() {
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    allData = await res.json();
  } catch (e) {
    cardsContainer.innerHTML = `
      <div class="no-results">
        ⚠️ 找不到資料檔案（data/cannes_winners.json）<br>
        <small>請先執行 scraper.py 抓取資料</small>
      </div>`;
    return;
  }

  totalCount.textContent = allData.length.toLocaleString();
  populateYearFilter();
  populateCategoryFilter();
  applyFilters();

  // 事件監聽
  searchInput.addEventListener("input", applyFilters);
  filterYear.addEventListener("change", applyFilters);
  filterAward.addEventListener("change", applyFilters);
  filterCategory.addEventListener("change", applyFilters);
  filterMedia.addEventListener("change", applyFilters);
  clearBtn.addEventListener("click", clearFilters);
}

// ── 填入下拉選單 ──
function populateYearFilter() {
  const years = [...new Set(allData.map(d => d.year))].sort((a, b) => b - a);
  years.forEach(y => {
    const opt = document.createElement("option");
    opt.value = y;
    opt.textContent = y;
    filterYear.appendChild(opt);
  });
}

function populateCategoryFilter() {
  const cats = [...new Set(allData.map(d => d.cannes_category).filter(Boolean))].sort();
  cats.forEach(c => {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    filterCategory.appendChild(opt);
  });
}

// ── 篩選邏輯 ──
function applyFilters() {
  const q     = searchInput.value.trim().toLowerCase();
  const year  = filterYear.value;
  const award = filterAward.value.toLowerCase();
  const cat   = filterCategory.value;
  const media = filterMedia.value;

  filtered = allData.filter(d => {
    if (year  && String(d.year) !== year)                        return false;
    if (award && (d.award_level || "").toLowerCase() !== award)  return false;
    if (cat   && d.cannes_category !== cat)                      return false;
    if (media && d.media_type !== media)                         return false;
    if (q) {
      const hay = [d.campaign_name, d.brand, d.agency, d.city,
                   d.description_zh, d.description_en].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  renderCards();
  updateResultsCount();
}

function clearFilters() {
  searchInput.value = "";
  filterYear.value = "";
  filterAward.value = "";
  filterCategory.value = "";
  filterMedia.value = "";
  applyFilters();
}

// ── 渲染卡片 ──
function renderCards() {
  if (filtered.length === 0) {
    cardsContainer.innerHTML = '<div class="no-results">找不到符合的作品 🔍</div>';
    return;
  }

  // 最多顯示 300 筆（避免 DOM 爆炸）
  const toShow = filtered.slice(0, 300);

  cardsContainer.innerHTML = toShow.map(d => cardHTML(d)).join("");

  if (filtered.length > 300) {
    cardsContainer.innerHTML += `
      <div class="no-results" style="grid-column:1/-1;padding:16px 0;font-size:.85rem;">
        ⚠️ 只顯示前 300 筆，請用搜尋或篩選縮小範圍
      </div>`;
  }
}

function awardClass(level) {
  if (!level) return "unknown";
  const l = level.toLowerCase();
  if (l.includes("grand prix")) return "grand-prix";
  if (l.includes("titanium"))   return "titanium";
  if (l.includes("gold"))       return "gold";
  if (l.includes("silver"))     return "silver";
  if (l.includes("bronze"))     return "bronze";
  return "unknown";
}

function mediaIcon(type) {
  if (type === "影片") return "▶";
  if (type === "圖片") return "🖼";
  return "🔗";
}

function cardHTML(d) {
  const urlLink = d.original_url
    ? `<a class="btn btn-primary" href="${escHtml(d.original_url)}" target="_blank" rel="noopener">
         ${mediaIcon(d.media_type)} 看作品
       </a>`
    : `<span class="btn btn-primary disabled">無連結</span>`;

  const driveLink = d.drive_path
    ? `<a class="btn btn-secondary" href="${escHtml(d.drive_path)}" target="_blank" rel="noopener">
         📁 Drive
       </a>`
    : `<span class="btn btn-secondary disabled">📁 Drive</span>`;

  const agency = [d.agency, d.city].filter(Boolean).join(", ");

  // 說明區塊：優先顯示中文，沒有則顯示英文，都沒有則不顯示
  const descText = d.description_zh || d.description_en || "";
  const descHTML = descText
    ? `<div class="card-desc">
         <span class="desc-preview">${escHtml(descText.slice(0, 80))}${descText.length > 80 ? "…" : ""}</span>
         ${descText.length > 80
           ? `<button class="desc-toggle" onclick="toggleDesc(this)">展開</button>
              <span class="desc-full" hidden>${escHtml(descText)}</span>`
           : ""}
       </div>`
    : "";

  return `
    <div class="card">
      <div class="card-header">
        <span class="badge-year">${d.year}</span>
        <span class="badge-award ${awardClass(d.award_level)}">${escHtml(d.award_level || "?")}</span>
        <span class="badge-category">${escHtml(d.cannes_category || "")}</span>
      </div>
      <div class="card-title">${escHtml(d.campaign_name || "—")}</div>
      <div class="card-meta">
        <span class="brand">${escHtml(d.brand || "")}</span>
        <span class="sep">·</span>
        <span>${escHtml(agency)}</span>
      </div>
      ${descHTML}
      <div class="card-actions">
        ${urlLink}
        ${driveLink}
      </div>
    </div>`;
}

function toggleDesc(btn) {
  const preview = btn.previousElementSibling;
  const full = btn.nextElementSibling;
  if (full.hidden) {
    full.hidden = false;
    preview.hidden = true;
    btn.textContent = "收起";
  } else {
    full.hidden = true;
    preview.hidden = false;
    btn.textContent = "展開";
  }
}

function escHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateResultsCount() {
  if (filtered.length === allData.length) {
    resultsCount.textContent = "";
  } else {
    resultsCount.textContent = `顯示 ${filtered.length.toLocaleString()} / ${allData.length.toLocaleString()} 筆`;
  }
}

// ── 啟動 ──
init();
