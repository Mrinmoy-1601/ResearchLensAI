/**
 * app.js — ResearchLens AI Frontend v3.0
 * Modules: Auth | Dashboard | Upload/Analysis | Chat | Review | Discover
 */

const API = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" 
  ? "http://localhost:8000" 
  : "https://<YOUR-DEPLOYED-BACKEND-URL>"; // Replace this with your actual Docker container's deployment URL

const LS_TOKEN    = "rl_token";
const LS_USER     = "rl_user";
const LS_SESSIONS = "rl_sessions";
const LS_STATS    = "rl_stats";
const LS_CACHE    = "rl_analysis_cache"; // full analysis data keyed by session_id

// ══════════════════════════════════════════════════════════════════════════════
// STATE
// ══════════════════════════════════════════════════════════════════════════════
let currentUser  = null;   // { id, name, email, papers_analyzed, ... } | null
let currentToken = null;   // JWT string | null
let isGuest      = false;

let paperState = {
  sessionId: null, title: "", numPages: 0, numChunks: 0,
  summary: "", reviewLoaded: false, discoverLoaded: false,
  backendExpired: false,  // true when session restored from local cache only
};

// ══════════════════════════════════════════════════════════════════════════════
// DOM HELPERS
// ══════════════════════════════════════════════════════════════════════════════
const $ = (id) => document.getElementById(id);
const toast = $("toast");

function showToast(msg, type = "") {
  toast.textContent = msg;
  toast.className = `toast show ${type}`;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { toast.className = "toast"; }, 3200);
}

// ══════════════════════════════════════════════════════════════════════════════
// SCREEN MANAGER
// ══════════════════════════════════════════════════════════════════════════════
const SCREENS = ["auth-screen", "dashboard-screen", "landing-screen", "analysis-screen"];

function showScreen(name) {
  SCREENS.forEach(s => {
    const el = $(s);
    if (el) el.classList.remove("active");
  });
  const target = $(`${name}-screen`);
  if (target) target.classList.add("active");
  window.scrollTo(0, 0);

  // Update header user info whenever screen changes
  updateAllHeaders();

  // Activate dashboard nav link
  document.querySelectorAll(".dash-nav-link").forEach(l => l.classList.remove("active"));
  if (name === "dashboard") $("dash-nav-link-dash")?.classList.add("active");
}

// ══════════════════════════════════════════════════════════════════════════════
// MARKDOWN RENDERER
// ══════════════════════════════════════════════════════════════════════════════
function renderMarkdown(text) {
  if (!text) return "";
  let html = text
    .replace(/^#### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^### (.+)$/gm,  "<h3>$1</h3>")
    .replace(/^## (.+)$/gm,   "<h2>$1</h2>")
    .replace(/^# (.+)$/gm,    "<h1>$1</h1>")
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g,     "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g,         "<em>$1</em>")
    .replace(/`([^`]+)`/g,    "<code>$1</code>")
    .replace(/^> (.+)$/gm,    "<blockquote>$1</blockquote>")
    .replace(/^\s*[-*•]\s+(.+)$/gm, "<li>$1</li>")
    .replace(/^\s*\d+\.\s+(.+)$/gm, "<li>$1</li>")
    .replace(/^---+$/gm, "<hr/>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br/>");
  html = html.replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>");
  html = `<p>${html}</p>`;
  html = html.replace(/<p>\s*<\/p>/g, "");
  html = html.replace(/<p>(<h[1-6]>)/g, "$1");
  html = html.replace(/(<\/h[1-6]>)<\/p>/g, "$1");
  return html;
}

function formatApiError(msg) {
  if (!msg) return msg;
  if (msg.includes("[QUOTA_EXCEEDED]"))
    return `⚠️ **API Quota Reached**\n\nThe Gemini free-tier quota has been reached. Please wait ~1 minute and try again.\n\n[Check your quota & upgrade plan](https://ai.google.dev/pricing)`;
  if ((msg.includes("429") || msg.includes("quota")) && msg.includes("generativelanguage")) {
    const m = msg.match(/seconds:\s*(\d+)/);
    const eta = m ? ` (retry in ~${Math.ceil(Number(m[1]) / 60)} min)` : "";
    return `⚠️ **API Quota Exceeded**${eta}\n\nThe Gemini API free-tier rate limit was hit. Please wait and try again.`;
  }
  if (msg.startsWith("[AI error:"))
    return "⚠️ " + msg.replace("[AI error: ", "").replace(/]$/, "");
  return msg;
}

// ══════════════════════════════════════════════════════════════════════════════
// AUTH MODULE
// ══════════════════════════════════════════════════════════════════════════════
function switchAuthTab(tab) {
  $("signin-form").style.display   = tab === "signin"   ? "flex" : "none";
  $("register-form").style.display = tab === "register" ? "flex" : "none";
  $("tab-signin").classList.toggle("active",   tab === "signin");
  $("tab-register").classList.toggle("active", tab === "register");
  clearAuthErrors();
}

function clearAuthErrors() {
  ["login-error", "register-error"].forEach(id => {
    const el = $(id);
    if (el) { el.textContent = ""; el.classList.remove("visible"); }
  });
}

function showAuthError(id, msg) {
  const el = $(id);
  if (el) { el.textContent = msg; el.classList.add("visible"); }
}

function togglePassword(inputId, btn) {
  const inp = $(inputId);
  if (!inp) return;
  if (inp.type === "password") { inp.type = "text"; btn.textContent = "🙈"; }
  else                         { inp.type = "password"; btn.textContent = "👁"; }
}

// Password strength meter
$("reg-password")?.addEventListener("input", () => {
  const pw  = $("reg-password").value;
  const bar = $("pwd-strength-bar");
  const lbl = $("pwd-strength-label");
  const str = $("pwd-strength");
  if (!pw) { str.style.display = "none"; return; }
  str.style.display = "flex";
  let score = 0;
  if (pw.length >= 8)          score++;
  if (/[A-Z]/.test(pw))        score++;
  if (/[0-9]/.test(pw))        score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  const colors = ["#ff5252", "#ffb020", "#00e5b8", "#22d45e"];
  const widths  = ["25%", "50%", "75%", "100%"];
  const labels  = ["Weak", "Fair", "Good", "Strong"];
  bar.style.width      = widths[score - 1] || "10%";
  bar.style.background = colors[score - 1] || "#ff5252";
  lbl.textContent      = labels[score - 1] || "Too short";
  lbl.style.color      = colors[score - 1] || "#ff5252";
});

function setAuthBtnLoading(btnId, loading) {
  const btn  = $(btnId);
  if (!btn) return;
  const txt  = btn.querySelector(".btn-auth-text");
  const spin = btn.querySelector(".btn-spinner");
  btn.disabled = loading;
  if (txt)  txt.style.display  = loading ? "none" : "inline";
  if (spin) spin.style.display = loading ? "block" : "none";
}

async function handleLogin(e) {
  e.preventDefault();
  clearAuthErrors();
  const email    = $("login-email").value.trim();
  const password = $("login-password").value;
  setAuthBtnLoading("login-btn", true);
  try {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Login failed.");
    onAuthSuccess(data.access_token, data.user);
  } catch (err) {
    showAuthError("login-error", err.message);
  } finally {
    setAuthBtnLoading("login-btn", false);
  }
}

async function handleRegister(e) {
  e.preventDefault();
  clearAuthErrors();
  const name     = $("reg-name").value.trim();
  const email    = $("reg-email").value.trim();
  const password = $("reg-password").value;
  setAuthBtnLoading("register-btn", true);
  try {
    const res = await fetch(`${API}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Registration failed.");
    onAuthSuccess(data.access_token, data.user);
  } catch (err) {
    showAuthError("register-error", err.message);
  } finally {
    setAuthBtnLoading("register-btn", false);
  }
}

function onAuthSuccess(token, user) {
  currentToken = token;
  currentUser  = user;
  isGuest      = false;
  localStorage.setItem(LS_TOKEN, token);
  localStorage.setItem(LS_USER,  JSON.stringify(user));
  updateAllHeaders();
  showScreen("dashboard");
  renderDashboard();
  showToast(`Welcome, ${user.name}! 🎉`, "success");
}

function continueAsGuest() {
  isGuest      = true;
  currentUser  = null;
  currentToken = null;
  updateAllHeaders();
  showScreen("dashboard");
  renderDashboard();
}

function handleLogout() {
  currentToken = null;
  currentUser  = null;
  isGuest      = false;
  localStorage.removeItem(LS_TOKEN);
  localStorage.removeItem(LS_USER);
  closeAllDropdowns();
  showScreen("auth");
  showToast("Signed out successfully.");
}

async function tryRestoreSession() {
  const token = localStorage.getItem(LS_TOKEN);
  const user  = localStorage.getItem(LS_USER);
  if (!token) { showScreen("auth"); return; }
  try {
    const res = await fetch(`${API}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const data   = await res.json();
      currentToken = token;
      currentUser  = data;
      localStorage.setItem(LS_USER, JSON.stringify(data));
      updateAllHeaders();
      showScreen("dashboard");
      renderDashboard();
    } else {
      // Token expired — try parsing saved user as fallback
      if (user) {
        currentToken = token;
        currentUser  = JSON.parse(user);
        updateAllHeaders();
        showScreen("dashboard");
        renderDashboard();
      } else {
        localStorage.removeItem(LS_TOKEN);
        showScreen("auth");
      }
    }
  } catch {
    // Server offline — still restore from localStorage
    if (user) {
      currentToken = token;
      currentUser  = JSON.parse(user);
      updateAllHeaders();
      showScreen("dashboard");
      renderDashboard();
    } else {
      showScreen("auth");
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// USER DROPDOWN
// ══════════════════════════════════════════════════════════════════════════════
const DROPDOWNS = {
  "": "user-dropdown",
  "landing":  "user-dropdown-landing",
  "analysis": "user-dropdown-analysis",
};

function toggleUserDropdown(suffix = "") {
  const id = DROPDOWNS[suffix] || "user-dropdown";
  const el = $(id);
  if (!el) return;
  const isOpen = el.classList.contains("open");
  closeAllDropdowns();
  if (!isOpen) el.classList.add("open");
}

function closeAllDropdowns() {
  Object.values(DROPDOWNS).forEach(id => $(id)?.classList.remove("open"));
}

document.addEventListener("click", (e) => {
  const insideMenu = e.target.closest(".user-menu");
  if (!insideMenu) closeAllDropdowns();
});

// ══════════════════════════════════════════════════════════════════════════════
// HEADER / AVATAR UPDATES
// ══════════════════════════════════════════════════════════════════════════════
function getInitials(name) {
  if (!name) return "G";
  return name.trim().split(/\s+/).map(w => w[0]).join("").toUpperCase().slice(0, 2);
}

function updateAllHeaders() {
  const user = currentUser;
  const suffixes = ["", "landing", "analysis"];

  if (!user || isGuest) {
    // Guest mode — hide user menus, show sign-in buttons
    suffixes.forEach(s => {
      const menuId  = s ? `user-menu-${s}` : "user-menu";
      const guestId = s ? `guest-header-${s}` : "guest-header-dash";
      $(menuId) && ($(menuId).style.display  = "none");
      $(guestId) && ($(guestId).style.display = "flex");
    });
    $("greeting-name") && ($("greeting-name").textContent = "Researcher");
    return;
  }

  const initials = getInitials(user.name);

  // Dashboard header
  $("user-menu") && ($("user-menu").style.display = "flex");
  $("guest-header-dash") && ($("guest-header-dash").style.display = "none");
  $("user-avatar-circle") && ($("user-avatar-circle").textContent = initials);
  $("user-avatar-name") && ($("user-avatar-name").textContent = user.name.split(" ")[0]);
  $("ud-avatar") && ($("ud-avatar").textContent = initials);
  $("ud-name") && ($("ud-name").textContent = user.name);
  $("ud-email") && ($("ud-email").textContent = user.email);
  $("greeting-name") && ($("greeting-name").textContent = user.name.split(" ")[0]);

  // Landing header
  $("user-menu-landing") && ($("user-menu-landing").style.display = "flex");
  $("guest-header-landing") && ($("guest-header-landing").style.display = "none");
  $("user-avatar-circle-landing") && ($("user-avatar-circle-landing").textContent = initials);
  $("user-avatar-name-landing") && ($("user-avatar-name-landing").textContent = user.name.split(" ")[0]);
  $("ud-avatar-landing") && ($("ud-avatar-landing").textContent = initials);
  $("ud-name-landing") && ($("ud-name-landing").textContent = user.name);
  $("ud-email-landing") && ($("ud-email-landing").textContent = user.email);

  // Analysis header
  $("user-menu-analysis") && ($("user-menu-analysis").style.display = "flex");
  $("guest-header-analysis") && ($("guest-header-analysis").style.display = "none");
  $("user-avatar-circle-analysis") && ($("user-avatar-circle-analysis").textContent = initials);
  $("ud-avatar-analysis") && ($("ud-avatar-analysis").textContent = initials);
  $("ud-name-analysis") && ($("ud-name-analysis").textContent = user.name);
  $("ud-email-analysis") && ($("ud-email-analysis").textContent = user.email);
}

// ══════════════════════════════════════════════════════════════════════════════
// LOCAL STORAGE HELPERS
// ══════════════════════════════════════════════════════════════════════════════
function getSessions() {
  try { return JSON.parse(localStorage.getItem(LS_SESSIONS) || "[]"); }
  catch { return []; }
}
function saveSessions(arr) { localStorage.setItem(LS_SESSIONS, JSON.stringify(arr.slice(0, 12))); }

function getStats() {
  try { return JSON.parse(localStorage.getItem(LS_STATS) || '{"papers":0,"chats":0,"reviews":0,"discovers":0}'); }
  catch { return { papers: 0, chats: 0, reviews: 0, discovers: 0 }; }
}
function saveStats(s) { localStorage.setItem(LS_STATS, JSON.stringify(s)); }

function incrementStat(field) {
  const s = getStats();
  s[field] = (s[field] || 0) + 1;
  saveStats(s);
}

function pushSession(data) {
  const sessions = getSessions();
  const filtered = sessions.filter(s => s.id !== data.session_id);
  filtered.unshift({
    id:              data.session_id,
    title:           data.title,
    pages:           data.num_pages,
    chunks:          data.num_chunks,
    has_images:      data.has_images  || false,
    has_tables:      data.has_tables  || false,
    summary_preview: (data.summary || "").slice(0, 220),
    date:            new Date().toISOString(),
  });
  saveSessions(filtered);

  // Cache full analysis data so history cards can restore it
  try {
    const cache = JSON.parse(localStorage.getItem(LS_CACHE) || "{}");
    cache[data.session_id] = {
      session_id: data.session_id,
      title:      data.title,
      num_pages:  data.num_pages,
      num_chunks: data.num_chunks,
      has_images: data.has_images || false,
      has_tables: data.has_tables || false,
      summary:    data.summary || "",
    };
    // Keep only the latest 12 cached analyses to avoid storage bloat
    const keys = Object.keys(cache);
    if (keys.length > 12) delete cache[keys[0]];
    localStorage.setItem(LS_CACHE, JSON.stringify(cache));
  } catch(e) { console.warn("Cache write failed:", e); }
}

// ══════════════════════════════════════════════════════════════════════════════
// DASHBOARD MODULE
// ══════════════════════════════════════════════════════════════════════════════
function renderDashboard() {
  const stats = getStats();
  const s = getSessions();

  // Stats counters (animate)
  animateCounter("stat-papers",    stats.papers    || 0);
  animateCounter("stat-chats",     stats.chats     || 0);
  animateCounter("stat-reviews",   stats.reviews   || 0);
  animateCounter("stat-discovers", stats.discovers || 0);

  // Sessions grid
  const grid = $("sessions-grid");
  const clearBtn = $("btn-clear-history");
  if (!grid) return;

  if (s.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📄</div>
        <h3>No papers analyzed yet</h3>
        <p>Upload your first research paper to get started with AI analysis.</p>
        <button class="btn-empty-cta" onclick="showScreen('landing')">Analyze Your First Paper →</button>
      </div>`;
    if (clearBtn) clearBtn.style.display = "none";
  } else {
    grid.innerHTML = s.map(sess => buildSessionCard(sess)).join("");
    if (clearBtn) clearBtn.style.display = "block";
  }
}

function buildSessionCard(sess) {
  const date     = new Date(sess.date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const imgBadge = sess.has_images ? `<span class="session-badge img">🖼️ Images</span>` : "";
  const tblBadge = sess.has_tables ? `<span class="session-badge tbl">📊 Tables</span>` : "";
  const preview  = sess.summary_preview
    ? `<div class="session-card-preview">${sess.summary_preview.replace(/[<>]/g, "")}…</div>`
    : "";
  return `
    <div class="session-card" onclick="reopenSession(${JSON.stringify(sess.id).replace(/"/g, '&quot;')})">
      <div class="session-card-top">
        <div class="session-card-icon">📄</div>
        <div class="session-card-title">${escapeHtml(sess.title)}</div>
      </div>
      ${preview}
      <div class="session-card-meta">
        <span>📅 ${date}</span>
        <span>·</span>
        <span>${sess.pages} pages</span>
        <span>·</span>
        <span>${sess.chunks} chunks</span>
      </div>
      <div class="session-card-badges">${imgBadge}${tblBadge}</div>
    </div>`;
}

function reopenSession(sessionId) {
  // Try to restore from local cache first
  try {
    const cache = JSON.parse(localStorage.getItem(LS_CACHE) || "{}");
    const cached = cache[sessionId];
    if (cached && cached.summary) {
      // Restore full analysis from cache (summary only — backend session is gone)
      paperState.sessionId      = cached.session_id;
      paperState.title          = cached.title;
      paperState.numPages       = cached.num_pages;
      paperState.numChunks      = cached.num_chunks;
      paperState.summary        = cached.summary;
      paperState.reviewLoaded   = false;
      paperState.discoverLoaded = false;
      paperState.backendExpired = true;  // session lives in cache only

      resetAnalysisUI();
      showScreen("analysis");
      populateSummary(cached);
      showToast("Summary restored from cache ✅", "success");
      return;
    }
  } catch(e) { console.warn("Cache read failed:", e); }

  // No cache — ask to re-upload
  showToast("Analysis not cached. Please re-upload the paper.", "");
  setTimeout(() => showScreen("landing"), 1200);
}

function clearHistory() {
  if (!confirm("Clear all session history? This cannot be undone.")) return;
  localStorage.removeItem(LS_SESSIONS);
  renderDashboard();
  showToast("History cleared.");
}

function animateCounter(id, target) {
  const el = $(id);
  if (!el) return;
  const duration = 800;
  const start    = performance.now();
  const from     = parseInt(el.textContent) || 0;
  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const ease     = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(from + (target - from) * ease);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function escapeHtml(str) {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ══════════════════════════════════════════════════════════════════════════════
// UPLOAD / ANALYSIS MODULE
// ══════════════════════════════════════════════════════════════════════════════
const fileInput      = $("file-input");
const uploadZone     = $("upload-zone");
const uploadInner    = $("upload-inner");
const uploadProgress = $("upload-progress");
const progressBar    = $("progress-bar");
const progressTitle  = $("progress-title");
const progressSub    = $("progress-sub");
const chatInput      = $("chat-input");
const chatSendBtn    = $("chat-send-btn");
const chatMessages   = $("chat-messages");

// Drag and drop
uploadZone?.addEventListener("dragover", (e) => { e.preventDefault(); uploadZone.classList.add("drag-over"); });
uploadZone?.addEventListener("dragleave", () => uploadZone.classList.remove("drag-over"));
uploadZone?.addEventListener("drop", (e) => {
  e.preventDefault(); uploadZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) handleFileUpload(file);
});

fileInput?.addEventListener("change", () => {
  if (fileInput.files[0]) handleFileUpload(fileInput.files[0]);
});

async function handleFileUpload(file) {
  if (!file.name.toLowerCase().endsWith(".pdf")) { showToast("Please upload a PDF file.", "error"); return; }
  if (file.size > 50 * 1024 * 1024) { showToast("File too large (max 50 MB).", "error"); return; }

  uploadInner.style.display    = "none";
  uploadProgress.style.display = "flex";

  const steps         = ["ps-1", "ps-2", "ps-3", "ps-4"];
  const progressVals  = [15, 35, 60, 85];

  for (let i = 0; i < steps.length; i++) {
    if (i > 0) { $(steps[i-1]).classList.remove("active"); $(steps[i-1]).classList.add("done"); }
    $(steps[i]).classList.add("active");
    progressBar.style.width = progressVals[i] + "%";
    await sleep(750);
  }

  progressTitle.textContent = "Generating AI summary…";
  progressSub.textContent   = "This may take 15–30 seconds for long papers";

  try {
    const fd = new FormData();
    fd.append("file", file);

    const headers = {};
    if (currentToken) headers["Authorization"] = `Bearer ${currentToken}`;

    const res  = await fetch(`${API}/upload`, { method: "POST", body: fd, headers });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "Upload failed"); }
    const data = await res.json();

    steps.forEach(s => { $(s).classList.remove("active"); $(s).classList.add("done"); });
    progressBar.style.width   = "100%";
    progressTitle.textContent = "Analysis complete! ✨";
    await sleep(600);

    // Persist session + cache full analysis
    pushSession(data);
    incrementStat("papers");

    paperState.sessionId      = data.session_id;
    paperState.title          = data.title;
    paperState.numPages       = data.num_pages;
    paperState.numChunks      = data.num_chunks;
    paperState.summary        = data.summary;
    paperState.reviewLoaded   = false;
    paperState.discoverLoaded = false;
    paperState.backendExpired = false; // fresh upload — backend session is live

    // IMPORTANT: reset first, then populate — otherwise resetAnalysisUI() wipes the summary
    resetAnalysisUI();
    showScreen("analysis");
    populateSummary(data);
    showToast("Paper analyzed successfully! 🎉", "success");

    // Refresh dashboard stats
    if ($("stat-papers")) renderDashboard();

  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
    uploadInner.style.display    = "flex";
    uploadProgress.style.display = "none";
    progressBar.style.width      = "0%";
    steps.forEach(s => $(s).classList.remove("active", "done"));
    fileInput.value = "";
  }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function populateSummary(data) {
  $("paper-title-badge").textContent = data.title;
  $("paper-pages-badge").textContent = `${data.num_pages} pages`;

  const sc = $("summary-content");
  sc.className = "summary-content glass-card prose-content";
  sc.innerHTML = renderMarkdown(formatApiError(data.summary));

  $("meta-pages-val").textContent  = data.num_pages;
  $("meta-chunks-val").textContent = data.num_chunks;

  // Bug fix: show image/table pills when present
  if (data.has_images) $("meta-img").style.display = "flex";
  if (data.has_tables) $("meta-tbl").style.display = "flex";
}

function resetAnalysisUI() {
  // Chat
  chatMessages.innerHTML = buildWelcomeHTML();
  chatInput.value = "";
  // Review
  $("review-loading").style.display = "flex";
  $("review-loading").innerHTML = `<div class="spinner-ring"></div><p>Generating expert peer review…</p>`;
  $("review-body").style.display = "none";
  $("review-body").innerHTML = "";
  // Discover
  $("conference-loading").style.display = "flex";
  $("conference-content").style.display = "none";
  $("similar-loading").style.display    = "flex";
  $("similar-content").style.display    = "none";
  // Meta pills
  $("meta-img").style.display = "none";
  $("meta-tbl").style.display = "none";
  // Tabs
  switchTab("summary");
  // Upload zone
  uploadInner.style.display    = "flex";
  uploadProgress.style.display = "none";
  progressBar.style.width      = "0%";
  uploadZone?.classList.remove("drag-over");
  // Skeleton
  $("summary-content").innerHTML  = skeletonHTML();
  $("summary-content").className  = "summary-content glass-card";
  if (fileInput) fileInput.value  = "";
}

function skeletonHTML() {
  return `<div class="skeleton-lines">
    <div class="sk-line wide"></div><div class="sk-line"></div>
    <div class="sk-line medium"></div><div class="sk-line"></div>
    <div class="sk-line wide"></div><div class="sk-line short"></div>
  </div>`;
}

function buildWelcomeHTML() {
  return `<div class="chat-welcome">
    <div class="cw-icon">💬</div>
    <h3>Ask anything about the paper</h3>
    <p>I have full context of the paper including all images and tables.</p>
    <div class="cw-suggestions" id="chat-suggestions">
      <button class="suggestion-chip" onclick="sendSuggestion(this)">What is the main contribution?</button>
      <button class="suggestion-chip" onclick="sendSuggestion(this)">Summarize the methodology</button>
      <button class="suggestion-chip" onclick="sendSuggestion(this)">What are the key results?</button>
      <button class="suggestion-chip" onclick="sendSuggestion(this)">What are the limitations?</button>
    </div>
  </div>`;
}

function addHeadingIcons(html) {
  return html
    .replace(/<(h[2-4])>([^<]*Strengths?[^<]*)<\/\1>/gi, '<$1>💪 $2</$1>')
    .replace(/<(h[2-4])>([^<]*Weaknesses?[^<]*)<\/\1>/gi, '<$1>⚠️ $2</$1>')
    .replace(/<(h[2-4])>([^<]*Recommendations?[^<]*)<\/\1>/gi, '<$1>💡 $2</$1>')
    .replace(/<(h[2-4])>([^<]*Methodology[^<]*)<\/\1>/gi, '<$1>🔬 $2</$1>')
    .replace(/<(h[2-4])>([^<]*Contributions?[^<]*)<\/\1>/gi, '<$1>✨ $2</$1>')
    .replace(/<(h[2-4])>([^<]*Relevance[^<]*)<\/\1>/gi, '<$1>🎯 $2</$1>')
    .replace(/<(h[2-4])>(?!.*?[\u2600-\u27BF|💪|⚠️|💡|🔬|✨|🎯])([^<]+)<\/\1>/gi, '<$1>📌 $2</$1>');
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB MANAGER
// ══════════════════════════════════════════════════════════════════════════════
function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelector(`[data-tab="${tabName}"]`)?.classList.add("active");
  $(`panel-${tabName}`)?.classList.add("active");

  if (tabName === "review" && !paperState.reviewLoaded && paperState.sessionId) loadReview();
  if (tabName === "discover" && !paperState.discoverLoaded && paperState.sessionId) loadDiscover();
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// ══════════════════════════════════════════════════════════════════════════════
// CHAT MODULE
// ══════════════════════════════════════════════════════════════════════════════
function sendSuggestion(btn) { chatInput.value = btn.textContent; sendMessage(); }

chatSendBtn?.addEventListener("click", sendMessage);
chatInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
chatInput?.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + "px";
});

async function sendMessage() {
  const msg = chatInput?.value.trim();
  if (!msg || !paperState.sessionId) return;

  chatMessages.querySelector(".chat-welcome")?.remove();
  chatInput.value = "";
  chatInput.style.height = "auto";
  chatSendBtn.disabled = true;

  appendBubble("user", msg);
  const typingId = appendTyping();

  try {
    const res = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: paperState.sessionId, message: msg }),
    });
    removeTyping(typingId);
    if (!res.ok) { const e = await res.json(); appendBubble("assistant", `⚠️ ${e.detail}`, []); }
    else         { const d = await res.json(); appendBubble("assistant", d.reply, d.page_refs || []); }
    incrementStat("chats");
  } catch (err) {
    removeTyping(typingId);
    appendBubble("assistant", `⚠️ Network error: ${err.message}`, []);
  }

  chatSendBtn.disabled = false;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendBubble(role, text, pageRefs = []) {
  const div    = document.createElement("div");
  div.className = `msg ${role}`;
  const avatar  = role === "user" ? "👤" : "🤖";
  const refs    = pageRefs.length
    ? `<div class="page-refs">${pageRefs.map(p => `<span class="page-ref">p.${p}</span>`).join("")}</div>` : "";
  const display = role === "assistant" ? formatApiError(text) : text;
  div.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div>
      <div class="msg-bubble">${renderMarkdown(display)}</div>
      ${refs}
    </div>`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendTyping() {
  const id  = "typing-" + Date.now();
  const div = document.createElement("div");
  div.className = "msg assistant"; div.id = id;
  div.innerHTML = `
    <div class="msg-avatar">🤖</div>
    <div class="msg-bubble">
      <div class="typing-indicator">
        <div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>
      </div>
    </div>`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return id;
}
function removeTyping(id) { document.getElementById(id)?.remove(); }

// ══════════════════════════════════════════════════════════════════════════════
// REVIEW MODULE
// ══════════════════════════════════════════════════════════════════════════════
function sessionExpiredCard(featureName) {
  return `
    <div class="session-expired-card">
      <div class="se-icon">⏳</div>
      <h3>Session No Longer Active</h3>
      <p>The backend session for this paper has expired (the server may have restarted). The <strong>${featureName}</strong> feature requires a live backend session.</p>
      <button class="btn-reupload" onclick="showScreen('landing')">
        📄 Re-upload Paper to Continue
      </button>
    </div>`;
}

async function loadReview() {
  if (!paperState.sessionId) return;
  paperState.reviewLoaded = true;

  // If session was restored from cache only, skip the API call
  if (paperState.backendExpired) {
    $("review-loading").style.display = "none";
    const body = $("review-body");
    body.style.display = "flex";
    body.innerHTML = sessionExpiredCard("Peer Review");
    return;
  }

  try {
    const res  = await fetch(`${API}/review/${paperState.sessionId}`);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: "Unknown error" }));
      const msg = errData.detail || "Failed to load review.";
      if (res.status === 404) {
        paperState.backendExpired = true;
        $("review-loading").style.display = "none";
        const body = $("review-body");
        body.style.display = "flex";
        body.innerHTML = sessionExpiredCard("Peer Review");
      } else {
        $("review-loading").innerHTML = `<div class="discover-error">⚠️ ${msg}</div>`;
      }
      return;
    }
    const data = await res.json();
    renderReview(data.raw_review);
    incrementStat("reviews");
  } catch (err) {
    $("review-loading").innerHTML = `<div class="discover-error">⚠️ ${err.message}</div>`;
  }
}

function renderReview(rawText) {
  $("review-loading").style.display = "none";
  const body = $("review-body");
  body.style.display = "flex";

  const verdictMatch = rawText.match(/VERDICT[\s\S]{0,60}?(ACCEPT|MINOR\s+REVISION|MAJOR\s+REVISION|REJECT)/i);
  const verdict      = verdictMatch ? verdictMatch[1].replace(/\s+/g, " ").toUpperCase().trim() : "UNKNOWN";
  const vClass       = verdict.includes("ACCEPT") ? "accept" : verdict.includes("MINOR") ? "minor" : verdict.includes("MAJOR") ? "major" : "reject";
  const vEmoji       = { accept:"✅", minor:"🔄", major:"⚠️", reject:"❌" }[vClass] || "📋";

  const scoreRE = /(Novelty|Methodology|Clarity|Results|Overall):\s*(\d+)\/10/gi;
  let scores = [], m;
  while ((m = scoreRE.exec(rawText)) !== null) scores.push({ label: m[1], value: parseInt(m[2]) });

  const iconMap = { Novelty: "✨", Methodology: "🔬", Clarity: "📖", Results: "📈", Overall: "🌟" };
  const scoreCards = scores.map(({ label, value }) => {
    const cls = value >= 7 ? "good" : value >= 5 ? "mid" : "bad";
    const icon = iconMap[label] || "⭐";
    return `<div class="score-card vertical-score">
      <div class="score-label">${icon} ${label}</div>
      <div class="score-value ${cls}">${value}<span style="font-size:1rem;color:var(--text-muted)">/10</span></div>
    </div>`;
  }).join("");

  // Remove the verbose VERDICT and SCORES sections so they don't duplicate below into the boxes
  let cleanedText = rawText
    .replace(/## VERDICT[\s\S]*?(ACCEPT|MINOR\s+REVISION|MAJOR\s+REVISION|REJECT)\s*/i, "")
    .replace(/## SCORES[\s\S]*?Overall:\s*\d+\/10\s*/i, "");

  // Split remainder into sections based on ## or ### markdown headers
  const sections = cleanedText.split(/(?=^#{2,3} )/m).filter(s => s.trim());
  let sectionsHTML = "";
  sections.forEach(sec => {
    sectionsHTML += `<div class="glass-card prose-content structured-box">
      ${addHeadingIcons(renderMarkdown(sec))}
    </div>`;
  });

  // If no sections were found (fallback), just wrap the whole thing
  if (!sectionsHTML) {
    sectionsHTML = `<div class="glass-card prose-content structured-box">${addHeadingIcons(renderMarkdown(cleanedText))}</div>`;
  }

  body.innerHTML = `
    <div class="review-verdict-section">
      <div>
        <div class="verdict-label">Final Decision</div>
        <div class="verdict-badge ${vClass}">${vEmoji} ${verdict}</div>
      </div>
      ${scores.length ? `<div style="text-align:right;">
        <div class="verdict-label">Overall Score</div>
        <div style="font-family:var(--font-display);font-size:2.8rem;font-weight:900;letter-spacing:-0.05em;line-height:1;color:${scores.find(s=>s.label==='Overall')?.value>=7?'var(--success)':scores.find(s=>s.label==='Overall')?.value>=5?'var(--warning)':'var(--error)'}">
          ${scores.find(s=>s.label==='Overall')?.value ?? '?'}<span style="font-size:1.2rem;color:var(--text-muted)">/10</span>
        </div>
      </div>` : ""}
    </div>

    ${scores.length ? `
    <div class="review-scores-section">
      <div class="scores-label">Evaluation Scores</div>
      <div class="review-summary-card">${scoreCards}</div>
    </div>` : ""}
    
    <div class="review-sections-container">
      ${sectionsHTML}
    </div>
    
    <button class="btn-copy" id="copy-review-inner-btn" style="align-self:flex-start; margin-top:10px;">⎘ Copy Full Review</button>`;

  $("copy-review-inner-btn")?.addEventListener("click", () => {
    navigator.clipboard.writeText(rawText).then(() => showToast("Review copied!", "success"));
  });
}

$("copy-review-btn")?.addEventListener("click", () => {
  if (!paperState.sessionId) return;
  showToast("Switch to Review tab first, then copy.", "");
});

// ══════════════════════════════════════════════════════════════════════════════
// DISCOVER MODULE
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Wraps rendered discover content (markdown HTML) into styled venue cards.
 * Each bold heading (## or **Name**) becomes a card header.
 */
function formatDiscoverContent(html) {
  // Split on h2/h3 headings and treat each block as a card
  const parts = html.split(/(?=<h[23][^>]*>)/);
  if (parts.length <= 1) {
    // No headings — return as single card body
    return `<div class="discover-item">${html}</div>`;
  }
  return parts.filter(p => p.trim()).map(part => {
    return `<div class="discover-item">${part}</div>`;
  }).join("");
}

async function loadDiscover() {
  if (!paperState.sessionId) return;
  paperState.discoverLoaded = true;

  // If session was restored from cache only, skip the API call
  if (paperState.backendExpired) {
    const expCard = sessionExpiredCard("Venue Finder & Similar Papers");
    $("conference-loading").style.display = "none";
    const cc = $("conference-content");
    cc.style.display = "block";
    cc.innerHTML = expCard;
    $("similar-loading").style.display = "none";
    const sc = $("similar-content");
    sc.style.display = "block";
    sc.innerHTML = expCard;
    return;
  }

  await Promise.allSettled([fetchConferences(), fetchSimilarPapers()]);
  incrementStat("discovers");
}

async function fetchConferences() {
  try {
    const res  = await fetch(`${API}/conferences/${paperState.sessionId}`);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: "Unknown error" }));
      const msg = errData.detail || "Failed to load conferences.";
      if (res.status === 404) {
        paperState.backendExpired = true;
        $("conference-loading").style.display = "none";
        const c = $("conference-content");
        c.style.display = "block";
        c.innerHTML = sessionExpiredCard("Venue Finder");
      } else {
        $("conference-loading").innerHTML = `<div class="discover-error">⚠️ ${msg}</div>`;
      }
      return;
    }
    const data = await res.json();
    const raw  = data.conferences[0]?.raw || "No venue suggestions found.";
    $("conference-loading").style.display = "none";
    const c = $("conference-content"); c.style.display = "block";
    c.innerHTML = formatDiscoverContent(renderMarkdown(formatApiError(raw)));
  } catch (err) {
    $("conference-loading").innerHTML = `<div class="discover-error">⚠️ ${err.message}</div>`;
  }
}

async function fetchSimilarPapers() {
  try {
    const res  = await fetch(`${API}/similar/${paperState.sessionId}`);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: "Unknown error" }));
      const msg = errData.detail || "Failed to load similar papers.";
      if (res.status === 404) {
        paperState.backendExpired = true;
        $("similar-loading").style.display = "none";
        const s = $("similar-content");
        s.style.display = "block";
        s.innerHTML = sessionExpiredCard("Similar Papers");
      } else {
        $("similar-loading").innerHTML = `<div class="discover-error">⚠️ ${msg}</div>`;
      }
      return;
    }
    const data = await res.json();
    const raw  = data.similar_papers[0]?.raw || "No similar papers found.";
    $("similar-loading").style.display = "none";
    const s = $("similar-content"); s.style.display = "block";
    s.innerHTML = formatDiscoverContent(renderMarkdown(formatApiError(raw)));
  } catch (err) {
    $("similar-loading").innerHTML = `<div class="discover-error">⚠️ ${err.message}</div>`;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// COPY SUMMARY
// ══════════════════════════════════════════════════════════════════════════════
$("copy-summary-btn")?.addEventListener("click", () => {
  if (!paperState.summary) return;
  navigator.clipboard.writeText(paperState.summary).then(() => showToast("Summary copied!", "success"));
});

// ══════════════════════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ══════════════════════════════════════════════════════════════════════════════
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeAllDropdowns();
    const analysis = $("analysis-screen");
    if (analysis?.classList.contains("active")) showScreen("dashboard");
  }
});

// ══════════════════════════════════════════════════════════════════════════════
// FEATURE CARD CLICK (landing page)
// ══════════════════════════════════════════════════════════════════════════════
function featureCardClick(tab) {
  if (paperState.sessionId) {
    // Paper already loaded — go straight to the relevant tab
    showScreen("analysis");
    switchTab(tab);
  } else {
    // No paper yet — scroll to upload or go to landing
    showScreen("landing");
    $("upload-zone")?.scrollIntoView({ behavior: "smooth", block: "center" });
    showToast("Upload a paper first to use this feature.", "");
  }
}

// Keyboard accessibility for feature cards
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.classList.contains("feature-card")) {
    e.target.click();
  }
});

// ══════════════════════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════════════════════
document.addEventListener("DOMContentLoaded", () => {
  tryRestoreSession();
});
