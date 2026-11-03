'use strict';

const TOKEN_KEY = 'its_token';
const REVIEW_PAGE_SIZE = 25;
let reviewOffset = 0;

const STATUS = {
  IN_PARKING: ['Đang trong bãi', 'info'],
  COMPLETED: ['Đã hoàn tất', 'success'],
  NEEDS_REVIEW: ['Cần kiểm tra', 'warning'],
  CANCELLED: ['Đã hủy', 'danger'],
};
const MATCH = {
  MATCH: ['Khớp', 'success'],
  MISMATCH: ['Lệch biển', 'danger'],
  PENDING: ['Chờ đối chiếu', 'warning'],
  RESOLVED_MATCH: ['Đã xác nhận khớp', 'success'],
  RESOLVED_APPROVED: ['Đã duyệt ra', 'success'],
  RESOLVED_REJECTED: ['Từ chối ra', 'danger'],
};
const ROLE = { admin: 'Quản trị viên', operator: 'Điều hành', viewer: 'Quan sát' };

const state = { token: localStorage.getItem(TOKEN_KEY) || '', user: null, sessionExpired: false, view: 'dashboard', viewVersion: 0, controller: null, motionPaused: false, theme: localStorage.getItem('its_theme') === 'light' ? 'light' : 'dark' };

// Work in progress stays in this tab's memory, never in localStorage.
const workflowDrafts = {
  entry: { file: null, plate: '', vehicle_type: 'motorcycle' },
  exit: { file: null, plate: '', ticket: '', search: '' },
};
const logFilters = { query: '', status: '', offset: 0 };
const LOG_PAGE_SIZE = 50;

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  entry: '<path d="M3 12h14m-5-5 5 5-5 5M20 4v16"/>',
  exit: '<path d="M21 12H7m5-5-5 5 5 5M4 4v16"/>',
  review: '<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3v.2"/>',
  logs: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6m-6 4h6m-6 4h4"/>',
  users: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m1-16a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 5"/>',
  logout: '<path d="M9 4H4v16h5m4-13 5 5-5 5m-5-5h13"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5m11-1a8 8 0 0 0-14-5M4 13a8 8 0 0 0 14 5"/>',
  car: '<path d="m5 7 2-4h10l2 4 2 3v8H3v-8l2-3Zm0 0h14M3 14h18M6 18v3m12-3v3m-12-10h2m8 0h2"/>',
  check: '<path d="m5 12 4 4L19 6"/><circle cx="12" cy="12" r="10"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  snow: '<path d="M12 2v20M3.3 7l17.4 10M3.3 17 20.7 7M8 4l4 3 4-3M8 20l4-3 4 3M3 11l4-2V5m14 8-4 2v4M3 13l4 2v4m14-8-4-2V5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  moon: '<path d="M20.5 13.2A9 9 0 0 1 10.8 3.5a9 9 0 1 0 9.7 9.7Z"/>',
  sparkle: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
  camera: '<path d="m8 6 2-3h4l2 3h5v14H3V6h5Z"/><circle cx="12" cy="13" r="4"/>',
  play: '<path d="m8 4 12 8-12 8V4Z"/>',
  pause: '<path d="M8 4v16M16 4v16"/>',
};
function icon(name) { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.car}</svg>`; }
function winterImage(name, className = '') {
  return `<img class="${className}" src="${themeAsset(name)}" data-winter-art="${name}" alt="" aria-hidden="true" />`;
}
function themeAsset(name) {
  const lightAssets = { 'winter-scene': 'halloween-scene', 'winter-snowman': 'halloween-ghost', 'pixel-car': 'halloween-car' };
  const resolved = state.theme === 'light' ? (lightAssets[name] || name) : name;
  return `/static/assets/${resolved}${state.motionPaused ? '-still' : ''}.svg`;
}
function seasonLabel() { return state.theme === 'light' ? 'PIXEL / HALLOWEEN' : 'PIXEL / WINTER'; }
function applyTheme(theme, persist = true) {
  state.theme = theme === 'light' ? 'light' : 'dark';
  clearWinterEggs();
  document.documentElement.dataset.theme = state.theme;
  if (persist) localStorage.setItem('its_theme', state.theme);
  document.querySelectorAll('[data-winter-art]').forEach(img => { img.src = themeAsset(img.dataset.winterArt); });
  document.querySelectorAll('.winter-label, .winter-caption').forEach(el => { el.textContent = seasonLabel(); });
  document.querySelectorAll('[data-theme-set]').forEach(btn => btn.setAttribute('aria-pressed', String(btn.dataset.themeSet === state.theme)));
  const toggle = $('#theme-toggle');
  const label = state.theme === 'light' ? 'Chuyển sang giao diện tối mùa đông' : 'Chuyển sang giao diện sáng Halloween';
  toggle.setAttribute('aria-label', label); toggle.title = label;
  toggle.innerHTML = icon(state.theme === 'light' ? 'moon' : 'sun');
  $('#motion-toggle').innerHTML = icon(state.theme === 'light' ? 'sparkle' : 'snow');
  $('#car-easter-hit').hidden = state.theme !== 'dark';
  $('#turbo-toggle').hidden = state.theme !== 'dark';
}
function initThemeControls() {
  applyTheme(state.theme, false);
  document.querySelectorAll('[data-theme-set]').forEach(btn => btn.addEventListener('click', () => applyTheme(btn.dataset.themeSet)));
  $('#theme-toggle').addEventListener('click', () => applyTheme(state.theme === 'light' ? 'dark' : 'light'));
}
function emptyState(name, title, description = '') { return `<div class="empty-state">${name === 'car' ? winterImage('winter-snowman', 'winter-mascot') : icon(name)}<strong>${esc(title)}</strong>${description ? `<p>${esc(description)}</p>` : ''}</div>`; }
function formatTime(value) {
  if (!value) return '—';
  const text=String(value),local=/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(text);
  const date = new Date(local?text.replace(' ','T')+'+07:00':text);
  return Number.isNaN(date.getTime()) ? esc(value) : esc(date.toLocaleString('vi-VN', { timeZone:'Asia/Ho_Chi_Minh',hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }));
}
function canWrite() { return ['admin', 'operator'].includes(state.user && state.user.role); }
function updateReviewCount(count) {
  $('#review-badge').hidden = !count;
  $('#review-badge').textContent = count;
}
function syncIcons() { document.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); }); }

function toast(msg, tone = 'success') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast ' + tone;
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.hidden = true), tone === 'error' ? 6500 : 3200);
}

async function api(path, opts = {}) {
  if (state.sessionExpired && path !== '/auth/login') throw new Error('Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục; ảnh đã chọn vẫn được giữ.');
  const requestToken = state.token;
  const headers = { ...(opts.headers || {}) };
  if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
  const signal = !opts.method || opts.method === 'GET' ? state.controller?.signal : undefined;
  const isVehicleWrite = opts.method === 'POST' && (['/vehicle/entry', '/vehicle/exit'].includes(path) || /^\/tickets\/[^/]+\/payment$/.test(path));
  const uncertainWrite=opts.method&&!['GET','HEAD'].includes(opts.method)&&!['/ocr','/auth/login'].includes(path);
  const requestController = new AbortController();
  const sourceSignal = opts.signal || signal;
  const cancelRequest = () => requestController.abort();
  if (!isVehicleWrite && sourceSignal) {
    if (sourceSignal.aborted) cancelRequest();
    else sourceSignal.addEventListener('abort', cancelRequest, {once:true});
  }
  let timedOut = false;
  const deadline = setTimeout(() => { timedOut = true; requestController.abort(); }, isVehicleWrite || path === '/ocr' ? 90000 : 30000);
  const timeoutMessage = isVehicleWrite ? 'Máy chủ phản hồi quá lâu. Kiểm tra Nhật ký trước khi gửi lại vì lượt xe có thể đã được ghi nhận.' : opts.method && !['GET','HEAD'].includes(opts.method) && !['/ocr','/auth/login'].includes(path) ? 'Máy chủ phản hồi quá lâu. Kiểm tra trạng thái trước khi gửi lại vì thay đổi có thể đã được lưu.' : 'Máy chủ phản hồi quá lâu. Kiểm tra kết nối rồi thử lại.';
  let res, data = null;
  try {
    try { res = await fetch(path, { ...opts, headers, signal:requestController.signal }); }
    catch (ex) {
      if (timedOut) throw new Error(timeoutMessage);
      if (ex.name === 'AbortError') throw ex;
      throw new Error(isVehicleWrite ? 'Không nhận được kết quả. Kiểm tra kết nối và Nhật ký trước khi gửi lại để tránh tạo trùng vé.' : uncertainWrite?'Không nhận được kết quả. Kiểm tra trạng thái trước khi gửi lại vì thay đổi có thể đã được lưu.':'Không kết nối được máy chủ. Kiểm tra kết nối rồi thử lại.');
    }
    try { data = await res.json(); }
    catch (error) {
      if (timedOut) throw new Error(timeoutMessage);
      if (error.name === 'AbortError') throw error;
      if (res.ok && isVehicleWrite) throw new Error('Chưa xác định được kết quả. Kiểm tra Nhật ký trước khi gửi lại vì lượt xe có thể đã được ghi nhận.');
      if (res.ok && uncertainWrite) throw new Error('Chưa xác định được kết quả. Kiểm tra trạng thái trước khi gửi lại vì thay đổi có thể đã được lưu.');
      if (res.ok) throw new Error('Máy chủ trả về dữ liệu không hợp lệ. Vui lòng thử lại.');
    }
  } finally { clearTimeout(deadline); if (!isVehicleWrite) sourceSignal?.removeEventListener('abort',cancelRequest); }
  if (res.ok && (!data || typeof data !== 'object' || Array.isArray(data))) throw new Error(uncertainWrite?'Chưa xác định được kết quả. Kiểm tra trạng thái trước khi gửi lại.':'Máy chủ trả về dữ liệu không hợp lệ. Vui lòng thử lại.');
  if (!res.ok || data?.ok===false) {
    if (res.status === 401) {
      if (path === '/auth/login') throw new Error('Tên đăng nhập hoặc mật khẩu không đúng.');
      if (requestToken === state.token || state.sessionExpired) requestReauthentication();
      throw new Error('Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục; ảnh đã chọn vẫn được giữ.');
    }
    const fields={plate_text:'biển số',ticket_id:'mã vé',file:'ảnh',username:'tên đăng nhập',password:'mật khẩu',amount:'số tiền',vehicle_type:'loại xe',reason:'lý do'};
    const invalid=Array.isArray(data?.detail)?[...new Set(data.detail.map(item=>fields[item.loc?.at(-1)]).filter(Boolean))]:[];
    const msg = data?.error?.message || (typeof data?.detail==='string'?data.detail:invalid.length?'Kiểm tra lại '+invalid.join(', ')+'.':res.status===429?'Thao tác quá nhanh. Chờ một chút rồi thử lại.':res.status===403?'Tài khoản không có quyền thực hiện thao tác này.':'Yêu cầu thất bại. Kiểm tra dữ liệu rồi thử lại.');
    const reference=res.headers?.get?.('X-Request-ID');
    throw new Error(msg+(res.status>=500&&reference?' Mã tra cứu: '+reference:''));
  }
  if(path!=='/auth/login'&&requestToken!==state.token){const changed=new Error('Phiên đăng nhập đã thay đổi.');changed.name='AbortError';throw changed;}
  return data;
}

function badge(label, tone) { return `<span class="badge ${tone}">${esc(label)}</span>`; }
function statusBadge(s) { const [l, t] = STATUS[s] || [s || 'Chờ xử lý', 'neutral']; return badge(l, t); }
function matchBadge(m) { const [l, t] = MATCH[m] || [m || 'Chờ đối chiếu', 'warning']; return badge(l, t); }

/* ====== LOGIN ====== */
function requestReauthentication() {
  if (!state.user || state.sessionExpired) return;
  state.sessionExpired = true; state.token = '';
  localStorage.removeItem(TOKEN_KEY);
  cameraClosers.forEach(close => close());
  $('#session-username').value = state.user.username;
  $('#session-password').value = '';
  $('#session-error').hidden = true;
  const dialog = $('#session-dialog');
  if (!dialog.open) dialog.showModal();
  $('#session-password').focus();
}
async function doSessionLogin(event) {
  event.preventDefault();
  const button = $('#session-submit'), error = $('#session-error');
  if (button.disabled) return;
  const original = button.innerHTML;
  button.disabled = true; button.innerHTML = '<span class="spinner"></span>Đang đăng nhập…'; error.hidden = true;
  try {
    const data = await api('/auth/login', { method: 'POST', body: new URLSearchParams({
      username: $('#session-username').value.trim(), password: $('#session-password').value,
    }) });
    if (typeof data.access_token !== 'string' || !data.access_token || !data.user || data.user.username !== $('#session-username').value.trim()) throw new Error('Phản hồi đăng nhập không hợp lệ. Vui lòng thử lại.');
    const changedUser=state.user?.username!==data.user.username;
    if(changedUser)clearUserWork();
    state.token = data.access_token; state.user = data.user; state.sessionExpired = false;
    localStorage.setItem(TOKEN_KEY, state.token);
    $('#session-dialog').close();
    document.querySelectorAll('[data-session-error]').forEach(result => { result.hidden = true; result.textContent = ''; delete result.dataset.sessionError; });
    syncUserShell();
    const entry = $('#entry-submit'), exit = $('#exit-submit');
    if (entry) entry.disabled = !canWrite();
    if (exit) exit.disabled = !canWrite() || !!$('#exit-ticket') && $('#exit-ticket').options.length <= 1;
    if (changedUser||!canView(state.view)) await showView('dashboard');
    toast(changedUser?'Đã đổi tài khoản. Bản nháp của tài khoản trước đã được xóa.':'Đã đăng nhập lại. Bạn có thể tiếp tục thao tác với ảnh đã chọn.');
  } catch (ex) { error.textContent = ex.message; error.hidden = false; }
  finally { $('#session-password').value = ''; button.disabled = false; button.innerHTML = original; }
}
function setPasswordVisible(visible) {
  const input = $('#login-password');
  const start = input.selectionStart, end = input.selectionEnd;
  input.type = visible ? 'text' : 'password';
  if (start !== null && end !== null) input.setSelectionRange(start, end);
  $('#password-field').classList.toggle('lamp-on', visible);
  const button = $('#password-toggle');
  const label = visible ? 'Tắt đèn, ẩn mật khẩu' : 'Bật đèn, hiện mật khẩu';
  button.setAttribute('aria-pressed', String(visible));
  button.setAttribute('aria-label', label);
  button.title = label;
}
function initPasswordLamp() {
  $('#password-toggle').addEventListener('click', () => setPasswordVisible($('#login-password').type === 'password'));
}
async function doLogin(e) {
  e.preventDefault();
  const err = $('#login-error'), button = $('#login-form button[type="submit"]');
  if (button.disabled) return;
  const label = button.innerHTML;
  button.disabled = true; button.innerHTML = '<span class="spinner"></span>Đang đăng nhập…';
  err.hidden = true;
  try {
    const data = await api('/auth/login', {
      method: 'POST',
      body: new URLSearchParams({
        username: $('#login-username').value.trim(),
        password: $('#login-password').value,
      }),
    });
    state.token = data.access_token;
    state.user = data.user;
    localStorage.setItem(TOKEN_KEY, state.token);
    $('#login-password').value = '';
    enterApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  } finally { button.disabled = false; button.innerHTML = label; }
}

/* ====== APP SHELL ====== */
function enterApp() {
  state.sessionExpired = false;
  setPasswordVisible(false);
  clearWinterEggs();
  $('#login-view').hidden = true;
  $('#app-view').hidden = false;
  syncUserShell();
  showView('dashboard');
}
function syncUserShell() {
  $('#side-username').textContent = state.user.username;
  $('#side-role').textContent = ROLE[state.user.role] || state.user.role;
  $('#user-avatar').textContent = state.user.username.slice(0, 1).toUpperCase();
  $('#nav-admin').hidden = state.user.role !== 'admin';
  $('#nav-pricing').hidden = state.user.role !== 'admin';
  $('#nav-mb').hidden = state.user.role !== 'admin';
  document.querySelectorAll('.nav-item').forEach(button => { button.hidden = !canView(button.dataset.view); });
}

function canView(name) {
  if (['admin','pricing','mb'].includes(name)) return state.user?.role === 'admin';
  if (['entry','exit'].includes(name)) return canWrite();
  return !!state.user;
}

function clearUserWork() {
  closeTicketPass();closeQuickPaymentQR();
  previewCleanups.splice(0).forEach(cleanup=>cleanup());state.controller?.abort();
  for(const draft of Object.values(workflowDrafts))for(const key of Object.keys(draft))delete draft[key];
  Object.assign(workflowDrafts.entry,{file:null,plate:'',vehicle_type:'motorcycle'});
  Object.assign(workflowDrafts.exit,{file:null,plate:'',ticket:'',search:'',ticketManual:false});
  Object.assign(logFilters,{query:'',status:'',offset:0});reviewOffset=0;
}
function logout() {
  if(state.workflowPending){toast('Đang ghi nhận lượt xe. Chờ kết quả trước khi đổi tài khoản.','error');return;}
  state.token = '';
  state.user = null;
  clearUserWork();
  localStorage.removeItem(TOKEN_KEY);
  location.reload();
}

const VIEW_TITLES = {
  dashboard: 'Tổng quan',
  entry: 'Xe vào',
  exit: 'Xe ra',
  review: 'Cần kiểm tra',
  logs: 'Nhật ký nhận diện',
  admin: 'Quản lý tài khoản',
  pricing: 'Biểu phí gửi xe',
  payments: 'Thanh toán & phiếu thu',
  mb: 'Kết nối MB',
};

async function showView(name) {
  if (!RENDER[name]) return;
  if (!canView(name)) name = 'dashboard';
  if (state.workflowPending) { toast('Đang ghi nhận lượt xe. Vui lòng chờ kết quả trước khi chuyển mục.', 'error'); return; }
  closeTicketPass();
  closeQuickPaymentQR();
  previewCleanups.splice(0).forEach(cleanup => cleanup());
  state.controller?.abort();
  state.controller = new AbortController();
  state.view = name;
  const version = ++state.viewVersion;
  $('#view-title').textContent = VIEW_TITLES[name] || name;
  document.querySelectorAll('.nav-item').forEach((b) => {
    b.classList.toggle('active', b.dataset.view === name);
    if (b.dataset.view === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  const el = $('#view-content');
  el.innerHTML = '<div class="loading-state"><span class="spinner"></span>Đang tải dữ liệu…</div>';
  try {
    await RENDER[name]();
  } catch (ex) {
    if (version !== state.viewVersion || ex.name === 'AbortError') return;
    el.innerHTML = `<div class="card">${emptyState('review', 'Không tải được dữ liệu', ex.message)}<button class="btn btn-primary" id="retry-view">Thử lại</button></div>`;
    $('#retry-view').addEventListener('click', () => showView(name));
  }
}

/* ====== RENDERERS ====== */
const RENDER = {
  async payments() { await renderPayments(); },
  async mb() { await renderMB(); },
  async pricing() { await renderPricing(); },
  async dashboard() {
    const version=state.viewVersion;
    const [summary, logs, active] = await Promise.all([
      api('/operations/summary'), api('/logs?limit=6'), api('/tickets/active?limit=6'),
    ]);
    if (state.view !== 'dashboard' || state.viewVersion!==version) return;
    const k = summary.kpis || {}, items = logs.items || [];
    const reviewCount = k.review_tickets || 0;
    updateReviewCount(reviewCount);
    const cards = [
      ['car', 'blue', 'Đang trong bãi', k.active_tickets ?? 0],
      ['logs', 'purple', 'Tổng vé', k.total_tickets ?? 0],
      ['check', 'green', 'Đã hoàn tất', k.completed_tickets ?? 0],
      ['review', 'orange', 'Cần kiểm tra', reviewCount],
    ];
    const stats = cards.map(([name, tone, label, value]) => `<div class="card stat"><div class="stat-top"><span class="stat-label">${label}</span><span class="stat-icon ${tone}">${icon(name)}</span></div><div class="stat-value">${esc(value)}</div></div>`).join('');
    const health = summary.health || {};
    const healthLabel = { NORMAL: 'Bình thường', ATTENTION_REQUIRED: 'Cần kiểm tra', OCR_DEGRADED: 'Cần rà soát OCR' }[health.code] || 'Chưa xác định';
    const recentRows = items.map(r => `<tr><td class="ticket-id">${esc(r.ticket_id)}</td><td class="plate">${esc(r.plate_entry || r.plate_exit || '—')}</td><td>${statusBadge(r.status)}</td><td>${matchBadge(r.match_result)}</td><td class="time-cell">${formatTime(r.entry_time)}</td></tr>`).join('');
    const activeItems = active.items || [];
    $('#view-content').innerHTML = `
      <section class="winter-banner"><div class="banner-copy"><span class="winter-label">${seasonLabel()}</span><h2>Chào, ${esc(state.user.username)}</h2><p>${esc(new Date().toLocaleDateString('vi-VN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Ho_Chi_Minh' }))}</p></div><div class="winter-banner-art" aria-hidden="true">${winterImage('winter-scene')}</div><div class="banner-spark" aria-hidden="true"></div></section>
      <div class="grid grid-4 stats-grid">${stats}</div>
      <div class="quick-actions">
        ${canWrite() ? `<button class="quick-action" data-open="entry"><span class="action-icon blue">${icon('entry')}</span><span><strong>Ghi nhận xe vào</strong><small>Tạo vé từ ảnh biển số</small></span>${icon('entry')}</button><button class="quick-action" data-open="exit"><span class="action-icon purple">${icon('exit')}</span><span><strong>Ghi nhận xe ra</strong><small>Đối chiếu và hoàn tất vé</small></span>${icon('exit')}</button>` : `<button class="quick-action" data-open="logs"><span class="action-icon blue">${icon('logs')}</span><span><strong>Nhật ký lượt xe</strong><small>Tra cứu biển số và trạng thái vé</small></span>${icon('entry')}</button>`}
      </div>
      <div class="dashboard-grid">
        <section class="card activity-card"><div class="card-heading"><h3>Hoạt động gần đây</h3><button class="text-btn" data-open="logs">Xem tất cả ${icon('entry')}</button></div>
          ${items.length ? `<div class="table-wrap"><table><thead><tr><th>Mã vé</th><th>Biển số</th><th>Trạng thái</th><th>Đối chiếu</th><th>Thời gian vào</th></tr></thead><tbody>${recentRows}</tbody></table></div>` : emptyState('car', 'Chưa có lượt xe', 'Các lượt xe vào và ra sẽ xuất hiện tại đây.')}
        </section>
        <section class="card system-card"><div class="card-heading"><h3>Vận hành</h3><span class="status-dot ${health.tone === 'warning' ? 'warning' : ''}"></span></div>
          <div class="system-row"><span>Trạng thái</span>${badge(healthLabel, health.tone === 'warning' ? 'warning' : 'neutral')}</div>
          <div class="system-row"><span>Vé cần kiểm tra</span><strong>${esc(reviewCount)}</strong></div>
          <div class="system-row"><span>Lệch biển số</span><strong>${esc(k.mismatch_tickets || 0)}</strong></div>
          <button class="btn btn-soft btn-block" data-open="review">Xem vé cần kiểm tra ${icon('entry')}</button>
          <div class="updated-at">${icon('clock')}Cập nhật ${new Date().toLocaleTimeString('vi-VN')}</div>
        </section>
      </div>
      ${activeItems.length ? `<section class="card active-card"><div class="card-heading"><h3>Vé đang mở</h3><span class="count-chip">${active.total ?? activeItems.length}</span></div><div class="table-wrap"><table><thead><tr><th>Mã vé</th><th>Biển số</th><th>Trạng thái</th><th>Thời gian vào</th></tr></thead><tbody>${activeItems.map(r => `<tr><td class="ticket-id">${esc(r.ticket_id)}</td><td class="plate">${esc(r.plate_entry || '—')}</td><td>${statusBadge(r.status)}</td><td>${formatTime(r.entry_time)}</td></tr>`).join('')}</tbody></table></div></section>` : ''}`;
    document.querySelectorAll('[data-open]').forEach(btn => btn.addEventListener('click', () => showView(btn.dataset.open)));
  },

  async entry() {
    $('#view-content').innerHTML = `
      <div class="workflow-grid" id="entry-workflow" tabindex="-1">
        <section class="card upload-card"><div class="card-heading"><h3>Ảnh biển số xe vào</h3><span class="step-chip">01</span></div>${uploadMarkup('entry')}</section>
        <section class="card details-card"><div class="card-heading"><h3>Thông tin vé</h3><span class="step-chip">02</span></div>
          <div class="form-row vertical"><label>Loại xe<select id="entry-vehicle-type"><option value="motorcycle">Xe máy</option><option value="car">Ô tô</option></select></label><label>Biển số <span class="optional">· tự điền, có thể sửa</span><input id="entry-plate" placeholder="Chọn ảnh để tự đọc biển số" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="24" /></label></div>
          <p class="field-help">Ảnh được quét tự động. Kiểm tra biển số trên ảnh rồi xác nhận một lần.</p>
          <p class="workflow-error" id="entry-error" role="alert" hidden></p>
          <button class="btn btn-primary btn-block" id="entry-submit" ${canWrite() ? '' : 'disabled'}>${icon('entry')}Xác nhận xe vào</button>
          ${workflowTools('entry')}
          ${canWrite() ? '' : '<p class="field-help">Tài khoản này có quyền xem dữ liệu.</p>'}
        </section>
      </div><div id="entry-result" class="operation-result" role="status"></div>`;
    const upload = bindUpload('entry',{autoScan:true});
    bindWorkflow('entry', upload);
    $('#entry-submit').addEventListener('click', async () => {
      if (!canWrite()) return;
      if(upload.isScanning()){workflowError('entry','Đang quét ảnh. Chờ kết quả hoặc dừng quét để nhập tay.',$('#entry-scan-result'));return;}
      const f = upload.getFile();
      if (!f) { workflowError('entry', 'Chọn ảnh hoặc chụp biển số trước khi tạo vé.', $('#entry-drop')); return; }
      const submittedPlate = $('#entry-plate').value.trim();
      if(!submittedPlate){workflowError('entry','Kiểm tra biển số tự điền hoặc nhập tay trước khi xác nhận.',$('#entry-plate'));return;}
      const submittedType = $('#entry-vehicle-type').value || 'motorcycle';
      const fd = new FormData();
      fd.append('file', f);
      fd.append('vehicle_type', submittedType);
      const cachedScan=upload.getScan();
      fd.append('ai_review_confirmed','true');
      if(cachedScan?.token)fd.append('scan_token',cachedScan.token);else fd.append('manual_only','true');
      if ($('#entry-plate').value.trim()) fd.append('plate_text', $('#entry-plate').value.trim());
      const btn = $('#entry-submit'), version = state.viewVersion;
      await runWorkflow('entry', btn, 'Đang tạo vé…', async () => {
        const data = await api('/vehicle/entry', { method: 'POST', body: fd });
        if (version !== state.viewVersion) return;
        const r = data.result || {};
        $('#entry-result').innerHTML = `<div class="card result-card"><div class="result-icon">${icon('check')}</div><div><h3>Đã tạo vé ${esc(r.ticket_id)}</h3><span class="plate">${esc(r.plate_entry || '—')}</span> ${r.review_required ? badge('Cần đối chiếu ảnh', 'warning') : statusBadge(r.status || 'IN_PARKING')}<div class="row-actions">${ticketAction(r.ticket_id,'Xem / in vé QR')}</div></div></div>`;
        toast('Đã tạo vé xe vào');
        if (upload.getFile() === f && $('#entry-plate').value.trim() === submittedPlate && ($('#entry-vehicle-type').value || 'motorcycle') === submittedType) {
          upload.reset(); $('#entry-plate').value = ''; workflowDrafts.entry.plate = ''; $('#entry-drop').focus();
        }
      });
    });
  },

  async exit() {
    const version=state.viewVersion;
    const active = await api('/tickets/active?limit=50&status=IN_PARKING');
    if (state.view !== 'exit' || state.viewVersion!==version) return;
    const items = (active.items || []).filter(t => t.status === 'IN_PARKING');
    $('#view-content').innerHTML = `
      <div class="workflow-grid" id="exit-workflow" tabindex="-1">
        <section class="card upload-card"><div class="card-heading"><h3>Ảnh biển số xe ra</h3><span class="step-chip">01</span></div>${uploadMarkup('exit')}</section>
        <section class="card details-card"><div class="card-heading"><h3>Đối chiếu vé</h3><span class="step-chip">02</span></div>
          <div class="form-row ticket-search-tools"><label>Tìm biển số / mã vé<input id="exit-ticket-search" type="search" placeholder="Biển số / mã vé" autocomplete="off" maxlength="100" aria-describedby="exit-ticket-count" /></label><button type="button" class="btn btn-soft" id="exit-ticket-refresh">${icon('refresh')}Làm mới vé</button></div>
          <details class="workflow-alternatives"><summary>Tìm bằng mã QR</summary>${qrLookupMarkup()}</details>
          <div class="form-row vertical"><label>Vé trong bãi<select id="exit-ticket" aria-label="Chọn vé"><option value="">${items.length ? 'Ảnh sẽ tự tìm vé khớp biển số' : 'Chưa có vé đang trong bãi'}</option>${items.map(t => `<option value="${esc(t.ticket_id)}">${esc(t.plate_entry)} · ${esc(t.ticket_id)}</option>`).join('')}</select></label>
          <p id="exit-ticket-count" class="ticket-search-status" role="status"></p>
          <div class="ticket-pages"><button type="button" class="text-btn" id="exit-ticket-prev" disabled>Vé trước</button><button type="button" class="text-btn" id="exit-ticket-next" disabled>Vé tiếp</button></div>
          <p id="exit-match-note" class="ticket-search-status" role="status"></p>
          <label>Biển số <span class="optional">· tự điền, có thể sửa</span><input id="exit-plate" placeholder="Chọn ảnh để tự đọc biển số" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="24" /></label></div>
          <p class="field-help">Tự chọn khi chỉ có một vé khớp chính xác. Kiểm tra ảnh rồi xác nhận. <button type="button" class="text-btn" id="exit-review-link">Vé cần kiểm tra</button></p>
          <p class="workflow-error" id="exit-error" role="alert" hidden></p>
          <button class="btn btn-primary btn-block" id="exit-submit" ${canWrite() && items.length ? '' : 'disabled'}>${icon('exit')}Xác nhận xe ra</button>
          ${workflowTools('exit')}
        </section>
      </div><div id="exit-result" class="operation-result" role="status"></div>`;
    const ticketSearch = bindLiveTicketSearch({...active,items});
    const upload = bindUpload('exit',{autoScan:true,onPlate:ticketSearch.matchPlate});
    bindWorkflow('exit', upload, ticketSearch.clear);
    $('#exit-plate').addEventListener('input',()=>ticketSearch.matchPlate($('#exit-plate').value,{debounce:true}));
    bindQRLookup(async ticket => {
      if (ticket.status==='IN_PARKING' && await ticketSearch.choose(ticket.ticket_id)) {
        $('#exit-plate').focus();
      } else {
        ticketSearch.clear();
        await openTicketPass(ticket.ticket_id);
      }
    });
    $('#exit-review-link').addEventListener('click', () => showView('review'));
    $('#exit-submit').addEventListener('click', async () => {
      if (!canWrite()) return;
      if(upload.isScanning()){workflowError('exit','Đang quét ảnh. Chờ kết quả hoặc dừng quét để nhập tay.',$('#exit-scan-result'));return;}
      if(ticketSearch.isPending()){workflowError('exit','Đang tìm vé trên máy chủ. Chờ kết quả trước khi xác nhận.',$('#exit-ticket-count'));return;}
      const tid = $('#exit-ticket').value, f = upload.getFile();
      const submittedPlate = $('#exit-plate').value.trim();
      if(!submittedPlate){workflowError('exit','Kiểm tra biển số tự điền hoặc nhập tay trước khi xác nhận.',$('#exit-plate'));return;}
      if (!tid) { workflowError('exit', 'Chọn vé trong bãi hoặc mở phần tìm bằng mã/QR.', $('#exit-ticket')); return; }
      if (!f) { workflowError('exit', 'Chọn ảnh hoặc chụp biển số xe ra để đối chiếu.', $('#exit-drop')); return; }
      const fd = new FormData(); fd.append('ticket_id', tid); fd.append('file', f);
      const cachedScan=upload.getScan();
      fd.append('ai_review_confirmed','true');
      if(cachedScan?.token)fd.append('scan_token',cachedScan.token);else fd.append('manual_only','true');
      if ($('#exit-plate').value.trim()) fd.append('plate_text', $('#exit-plate').value.trim());
      const btn = $('#exit-submit'), version = state.viewVersion;
      await runWorkflow('exit', btn, 'Đang đối chiếu…', async () => {
        const data = await api('/vehicle/exit', { method: 'POST', body: fd });
        if (version !== state.viewVersion) return;
        const r = data.result || {};
        const needsReview = r.status === 'NEEDS_REVIEW';
        const heading = needsReview ? 'Chờ kiểm tra — chưa duyệt xe ra' : 'Đã ghi nhận xe ra';
        $('#exit-result').innerHTML = `<div class="card result-card"><div><h3>${heading}</h3><span class="plate">${esc(r.plate_exit || '—')}</span> ${matchBadge(r.match_result)} ${statusBadge(r.status)}${needsReview ? '<p>Đối chiếu ảnh và xử lý vé trong mục Cần kiểm tra.</p><button class="btn btn-soft" id="exit-open-review">Kiểm tra vé ngay</button>' : ''}<div class="row-actions">${ticketAction(tid,'Xem vé / thu phí')}</div></div></div>`;
        if (needsReview) $('#exit-open-review').addEventListener('click', () => showView('review'));
        toast(heading, needsReview ? 'warning' : 'success');
        const sameDraft = upload.getFile() === f && $('#exit-plate').value.trim() === submittedPlate && $('#exit-ticket').value === tid;
        if (sameDraft) upload.reset();
        if (sameDraft) {
          $('#exit-ticket').value = ''; $('#exit-plate').value = ''; $('#exit-ticket-search').value = '';
          Object.assign(workflowDrafts.exit, {plate:'', ticket:'', search:''});
          ticketSearch.clear();
        }
        if (r.status && r.status !== 'IN_PARKING') ticketSearch.remove(tid);
        btn.dataset.keepDisabled = String(!canWrite() || ticketSearch.remaining() === 0);
        if (sameDraft) $(needsReview ? '#exit-open-review' : '#exit-drop').focus();
      });
    });
  },

  async review() {
    const version=state.viewVersion;
    const logs = await api('/logs?status=NEEDS_REVIEW&limit='+REVIEW_PAGE_SIZE+'&offset='+reviewOffset);
    if (state.view !== 'review' || state.viewVersion!==version) return;
    const items = logs.items || [];
    const total=logs.total??items.length;
    if(reviewOffset>0&&reviewOffset>=total){reviewOffset=Math.max(0,Math.ceil(total/REVIEW_PAGE_SIZE)-1)*REVIEW_PAGE_SIZE;return RENDER.review();}
    updateReviewCount(logs.total ?? items.length);
    $('#view-content').innerHTML = `<section class="card"><div class="card-heading"><h3>Vé cần kiểm tra</h3><span class="count-chip">${items.length} / ${total} vé</span></div><p class="field-help">Mở ảnh để đối chiếu trước khi duyệt. Tất cả vé đang chờ đều có thể tra cứu qua các trang.</p></section>` + (items.length ? `
      <div class="grid" style="grid-template-columns:1fr">${items.map((r) => `
        <div class="card" data-ticket="${esc(r.ticket_id)}">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <h3 style="margin:0">Vé ${esc(r.ticket_id)}</h3>
            <span>${matchBadge(r.match_result)}</span>
          </div>
          ${ticketAction(r.ticket_id)}
          <div class="grid grid-2" style="margin:12px 0">
            <div>Biển vào: <span class="plate">${esc(r.plate_entry || '—')}</span></div>
            <div>Biển ra: <span class="plate">${esc(r.plate_exit || '—')}</span></div>
          </div>
          <div style="color:var(--muted);font-size:13px">Lý do: ${esc(r.review_reason || '')}</div>
          <details class="review-evidence" data-review-photos="${esc(r.ticket_id)}"><summary>Xem ảnh vào / ra để đối chiếu</summary><div class="review-photo-grid">${['entry','exit'].map(side => `<figure><img data-review-image="${side}" alt="Ảnh ${side === 'entry' ? 'xe vào' : 'xe ra'}" hidden /><figcaption>${side === 'entry' ? 'Ảnh xe vào' : 'Ảnh xe ra'}<span data-image-status="${side}"> · Mở để tải ảnh</span></figcaption></figure>`).join('')}</div></details>
          ${canWrite() ? `<div class="row-actions" style="margin-top:18px">
            <button class="btn btn-success btn-sm" data-action="APPROVE_EXIT">Duyệt ra</button>
            <button class="btn btn-primary btn-sm" data-action="MARK_MATCH">Đánh dấu khớp</button>
            <button class="btn btn-warning btn-sm" data-action="REJECT_EXIT">Từ chối</button>
            ${state.user.role === 'admin' ? '<button class="btn btn-danger btn-sm" data-action="CANCEL">Hủy vé</button>' : ''}
          </div>` : ''}
        </div>`).join('')}</div>` : `<div class="card">${emptyState('check', 'Không có vé cần kiểm tra', 'Các vé cần đối chiếu sẽ xuất hiện tại đây.')}</div>`) + `<div class="log-pagination"><button class="btn btn-soft" id="review-prev" type="button" ${reviewOffset===0?'disabled':''}>Trang trước</button><span role="status">Trang ${Math.floor(reviewOffset/REVIEW_PAGE_SIZE)+1} / ${Math.max(1,Math.ceil(total/REVIEW_PAGE_SIZE))}</span><button class="btn btn-soft" id="review-next" type="button" ${reviewOffset+REVIEW_PAGE_SIZE>=total?'disabled':''}>Trang sau</button></div>`;
    $('#review-prev').addEventListener('click',()=>{reviewOffset=Math.max(0,reviewOffset-REVIEW_PAGE_SIZE);return showView('review');});
    $('#review-next').addEventListener('click',()=>{reviewOffset+=REVIEW_PAGE_SIZE;return showView('review');});

    bindReviewEvidence();
    document.querySelectorAll('[data-action]').forEach((btn) => btn.addEventListener('click', async () => {
      const ticket = btn.closest('[data-ticket]').dataset.ticket;
      const action = btn.dataset.action;
      if (!canWrite()) return;
      let reason = '';
      if (action === 'CANCEL') {
        reason = prompt('Lý do hủy vé:')?.trim() || '';
        if (!reason) return;
      }
      await runPending(btn, 'Đang xử lý…', async () => {
        if (action === 'CANCEL') {
          await api(`/tickets/${encodeURIComponent(ticket)}/cancel`, { method: 'POST', body: new URLSearchParams({ reason }) });
        } else {
          await api(`/tickets/${encodeURIComponent(ticket)}/resolve`, { method: 'POST', body: new URLSearchParams({ resolution: action, note: '' }) });
        }
        toast('Đã xử lý');
        if (state.view === 'review') await showView('review');
      });
    }));
  },

  async logs() {
    const version=state.viewVersion;
    const params = new URLSearchParams({limit:String(LOG_PAGE_SIZE)});
    if (logFilters.offset) params.set('offset', String(logFilters.offset));
    if (logFilters.status) params.set('status', logFilters.status);
    if (logFilters.query) params.set('q', logFilters.query);
    const logs = await api('/logs?' + params);
    if (state.view !== 'logs' || state.viewVersion!==version) return;
    const items = logs.items || [];
    $('#view-content').innerHTML = `
      <div class="card">
        <div class="card-heading"><h3>Nhật ký lượt xe</h3><span class="count-chip" id="log-count">${items.length} / ${esc(logs.total ?? items.length)} vé</span></div>
        <div class="form-row" style="margin-bottom:14px">
          <label>Lọc trạng thái
            <select id="log-filter">
              <option value="">Tất cả</option>
              <option value="IN_PARKING">Đang trong bãi</option>
              <option value="NEEDS_REVIEW">Cần kiểm tra</option>
              <option value="COMPLETED">Đã hoàn tất</option>
              <option value="CANCELLED">Đã hủy</option>
            </select>
          </label>
          <label>Tìm kiếm<input id="log-search" placeholder="Biển số vào, ra hoặc mã vé" type="search" maxlength="100" /></label>
          <button type="button" class="btn btn-soft log-clear" id="log-clear">Xóa bộ lọc</button>
        </div>
        <div class="table-wrap log-table" tabindex="0" role="region" aria-label="Danh sách vé"><table>
          <thead><tr><th>Vé</th><th>Biển vào</th><th>Biển ra</th><th>Trạng thái</th><th>Đối chiếu</th><th>Thời gian vào</th></tr></thead>
          <tbody id="log-tbody"></tbody>
        </table></div>
        <div class="log-pagination"><button type="button" class="btn btn-soft" id="log-prev" disabled>Trang trước</button><span id="log-page" role="status">Trang 1</span><button type="button" class="btn btn-soft" id="log-next">Trang sau</button></div>
      </div>`;

    const render = (list) => {
      $('#log-tbody').innerHTML = list.map((r) => `
        <tr><td><button class="text-btn ticket-id" type="button" data-ticket-pass="${esc(r.ticket_id)}">${esc(r.ticket_id)}</button></td><td class="plate">${esc(r.plate_entry || '—')}</td><td class="plate">${esc(r.plate_exit || '—')}</td>
        <td>${statusBadge(r.status)}</td><td>${matchBadge(r.match_result)}</td><td class="time-cell">${formatTime(r.entry_time)}</td></tr>`).join('') || `<tr><td colspan="6">${emptyState('search', 'Không tìm thấy vé')}</td></tr>`;
    };
    $('#log-filter').value = logFilters.status; $('#log-search').value = logFilters.query;
    render(items);
    let offset = logFilters.offset, total = logs.total ?? items.length, request = 0, controller, disposed = false, searchTimer;
    let loading = false;
    const clearButton = () => { $('#log-clear').disabled = !$('#log-search').value && !$('#log-filter').value; };
    clearButton();
    const pagination = () => {
      $('#log-prev').disabled = loading || offset === 0;
      $('#log-next').disabled = loading || offset + LOG_PAGE_SIZE >= total;
      $('#log-page').textContent = `Trang ${Math.floor(offset / LOG_PAGE_SIZE) + 1} / ${Math.max(1, Math.ceil(total / LOG_PAGE_SIZE))}`;
    };
    pagination();
    const load = async nextOffset => {
      clearTimeout(searchTimer); loading = true;
      controller?.abort(); controller = new AbortController();
      const current = ++request;
      Object.assign(logFilters, {query:$('#log-search').value.trim(), status:$('#log-filter').value, offset:nextOffset});
      clearButton();
      const params = new URLSearchParams({limit:String(LOG_PAGE_SIZE), offset:String(nextOffset)});
      if ($('#log-filter').value) params.set('status', $('#log-filter').value);
      if ($('#log-search').value.trim()) params.set('q', $('#log-search').value.trim());
      $('#log-prev').disabled = $('#log-next').disabled = true;
      $('#log-tbody').innerHTML = '<tr><td colspan="6">Đang tìm vé…</td></tr>';
      try {
        const data = await api('/logs?' + params, {signal:controller.signal});
        if (disposed || version !== state.viewVersion || current !== request) return;
        offset = nextOffset; total = data.total ?? (data.items || []).length;
        render(data.items || []);
        $('#log-count').textContent = `${(data.items || []).length} / ${total} vé`;
      } catch (error) {
        if (disposed || current !== request || error.name === 'AbortError') return;
        $('#log-tbody').innerHTML = `<tr><td colspan="6">${esc(error.message)}</td></tr>`;
      } finally { if (!disposed && current === request && version === state.viewVersion) { loading = false; pagination(); } }
    };
    $('#log-filter').addEventListener('change', () => load(0));
    $('#log-search').addEventListener('input', () => {
      clearTimeout(searchTimer); controller?.abort(); request++;
      Object.assign(logFilters, {query:$('#log-search').value.trim(), status:$('#log-filter').value, offset:0});
      loading = true; pagination(); clearButton();
      $('#log-page').textContent = 'Đang tìm…';
      searchTimer = setTimeout(() => load(0), 250);
    });
    $('#log-search').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); return load(0); } });
    $('#log-clear').addEventListener('click', () => {
      $('#log-search').value = ''; $('#log-filter').value = ''; $('#log-search').focus(); return load(0);
    });
    $('#log-prev').addEventListener('click', () => load(Math.max(0, offset - LOG_PAGE_SIZE)));
    $('#log-next').addEventListener('click', () => load(offset + LOG_PAGE_SIZE));
    previewCleanups.push(() => { disposed = true; clearTimeout(searchTimer); controller?.abort(); });
  },

  async admin() {
    const version=state.viewVersion;
    const users = await api('/admin/users');
    if (state.view !== 'admin' || state.viewVersion!==version) return;
    const items = users.items || [];
    $('#view-content').innerHTML = `
      <div class="card">
        <h3>Tạo tài khoản</h3>
        <div class="form-row">
          <label>Tên đăng nhập<input id="u-username" /></label>
          <label>Mật khẩu<input id="u-password" type="password" /></label>
          <label>Vai trò
            <select id="u-role">${Object.entries(ROLE).reverse().map(([role, label]) => `<option value="${role}">${label}</option>`).join('')}</select>
          </label>
        </div>
        <button class="btn btn-primary" id="u-create">${icon('users')}Tạo tài khoản</button>
      </div>
      <div class="card" style="margin-top:16px">
        <h3>Danh sách tài khoản</h3>
        <p class="ticket-note">Bạn không thể tự đổi vai trò, khóa hoặc xóa tài khoản đang đăng nhập. Luôn giữ ít nhất một quản trị viên hoạt động.</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Tên đăng nhập</th><th>Vai trò</th><th>Trạng thái</th><th>Thao tác</th></tr></thead>
          <tbody id="u-tbody"></tbody>
        </table></div>
      </div>`;

    const protectedAccount = u => u.username === state.user.username || (u.role === 'admin' && u.is_active && items.filter(account => account.role === 'admin' && account.is_active).length === 1);
    const render = () => {
      $('#u-tbody').innerHTML = items.map((u) => `
        <tr><td class="ticket-id">${esc(u.username)}</td><td><select class="role-select" aria-label="Vai trò của ${esc(u.username)}" data-role-user="${esc(u.username)}" ${protectedAccount(u) ? 'disabled' : ''}>${Object.entries(ROLE).map(([role, label]) => `<option value="${role}" ${u.role === role ? 'selected' : ''}>${label}</option>`).join('')}</select></td>
        <td>${badge(u.is_active ? 'Hoạt động' : 'Khóa', u.is_active ? 'success' : 'neutral')}</td>
        <td><div class="row-actions">
          <button class="btn btn-sm btn-soft" data-u="${esc(u.username)}" data-op="role" ${protectedAccount(u) ? 'disabled' : ''}>Lưu vai trò</button>
          <button class="btn btn-sm ${u.is_active ? 'btn-warning' : 'btn-success'}" data-u="${esc(u.username)}" data-op="active" ${protectedAccount(u) ? 'disabled' : ''}>${u.is_active ? 'Khóa' : 'Mở khóa'}</button>
          <button class="btn btn-sm btn-danger" data-u="${esc(u.username)}" data-op="delete" ${protectedAccount(u) ? 'disabled' : ''}>Xóa</button>
        </div></td></tr>`).join('') || '<tr><td colspan="4" class="empty">Chưa có tài khoản</td></tr>';
    };
    render();

    $('#u-create').addEventListener('click', async () => {
      const username = $('#u-username').value.trim(), password = $('#u-password').value, role = $('#u-role').value;
      if (!username || !password) { toast('Nhập tên đăng nhập và mật khẩu', 'error'); return; }
      await runPending($('#u-create'), 'Đang tạo…', async () => {
        await api('/admin/users', { method: 'POST', body: new URLSearchParams({ username, password, role }) });
        toast('Đã tạo tài khoản');
        if (state.view === 'admin') await showView('admin');
      });
    });

    document.querySelectorAll('[data-op]').forEach((btn) => btn.addEventListener('click', async () => {
      const u = btn.dataset.u, op = btn.dataset.op;
      const account = items.find(item => item.username === u);
      if (!account || protectedAccount(account)) return;
      const selectedRole = [...document.querySelectorAll('[data-role-user]')].find(el => el.dataset.roleUser === u)?.value;
      if (op === 'delete' && !confirm(`Xóa tài khoản ${u}?`)) return;
      await runPending(btn, 'Đang lưu…', async () => {
        if (op === 'delete') {
          await api(`/admin/users/${encodeURIComponent(u)}`, { method: 'DELETE' });
        } else if (op === 'role') {
          await api(`/admin/users/${encodeURIComponent(u)}/role`, { method: 'PATCH', body: new URLSearchParams({ role: selectedRole }) });
        } else if (op === 'active') {
          await api(`/admin/users/${encodeURIComponent(u)}/active`, { method: 'PATCH', body: new URLSearchParams({ is_active: String(!account.is_active) }) });
        }
        toast('Đã cập nhật');
        if (state.view === 'admin') await showView('admin');
      });
    }));
  },
};

function bindReviewEvidence() {
  document.querySelectorAll('[data-review-photos]').forEach(details => {
    let disposed = false, loaded = false;
    const controller = new AbortController(), urls = [];
    previewCleanups.push(() => { disposed = true; controller.abort(); urls.forEach(url => URL.revokeObjectURL(url)); });
    details.addEventListener('toggle', () => {
      if (!details.open || loaded || disposed) return;
      loaded = true;
      ['entry', 'exit'].forEach(async side => {
        const status = details.querySelector(`[data-image-status="${side}"]`);
        const image = details.querySelector(`[data-review-image="${side}"]`);
        const requestToken = state.token;
        status.textContent = ' · Đang tải…';
        try {
          const response = await fetch(`/tickets/${encodeURIComponent(details.dataset.reviewPhotos)}/images/${side}`, {
            headers:{Authorization:'Bearer ' + requestToken}, signal:controller.signal,
          });
          if (response.status === 401 && requestToken === state.token) requestReauthentication();
          if (!response.ok) throw new Error(response.status === 404 ? 'Không có ảnh lưu' : 'Chưa tải được ảnh. Đóng rồi mở lại để thử lại.');
          const blob = await response.blob();
          if (disposed) return;
          const url = URL.createObjectURL(blob); urls.push(url);
          image.src = url; image.hidden = false; status.textContent = '';
        } catch (error) {
          if (!disposed && error.name !== 'AbortError') { status.textContent = ' · ' + error.message; loaded = false; }
        }
      });
    });
  });
}

function uploadMarkup(prefix) {
  return `<button type="button" class="drop-zone" id="${prefix}-drop">${icon('upload')}<strong>Chọn ảnh biển số</strong><span>Hoặc kéo thả ảnh vào đây</span><small>JPG, PNG, WEBP · Tối đa 10 MB</small></button><input type="file" id="${prefix}-file" accept=".jpg,.jpeg,.png,.webp" hidden />
    <div class="preview" id="${prefix}-preview"></div><div class="file-meta" id="${prefix}-meta" hidden><span id="${prefix}-filename"></span><span class="file-actions"><button class="text-btn" type="button" id="${prefix}-replace">Đổi ảnh</button><button class="text-btn" type="button" id="${prefix}-remove">Bỏ ảnh</button></span></div>
    <div class="camera-actions"><button type="button" class="btn btn-soft" id="${prefix}-camera-open">${icon('camera')}Mở camera</button><button type="button" class="btn btn-soft" id="${prefix}-camera-phone">${icon('camera')}Camera điện thoại</button></div>
    <input type="file" id="${prefix}-camera-native" accept="image/jpeg,image/png,image/webp" capture="environment" hidden />
    <div class="camera-panel" id="${prefix}-camera-panel" hidden>
      <label>Chọn camera<select id="${prefix}-camera-devices"><option value="">Camera mặc định</option></select></label>
      <div class="camera-feed"><video id="${prefix}-camera-video" autoplay muted playsinline></video><div class="camera-guide" aria-hidden="true"></div></div>
      <p class="camera-message" id="${prefix}-camera-message" role="status"></p><p class="camera-tip">Đưa biển số vào khung, giữ máy đứng yên và tránh ánh sáng phản chiếu.</p>
      <div class="camera-actions"><button type="button" class="btn btn-primary" id="${prefix}-camera-shutter" disabled>${icon('camera')}Chụp ảnh</button><button type="button" class="btn btn-soft" id="${prefix}-camera-close">Đóng camera</button></div>
    </div>
    <button type="button" class="btn btn-soft btn-block camera-scan" id="${prefix}-scan" hidden>${icon('search')}Quét biển số</button><div id="${prefix}-scan-result" class="camera-scan-result" role="status" hidden></div>`;
}

const previewCleanups = [];
const cameraClosers = new Set();

const winterEggs = { clicks: 0, lastClick: 0, turboTimer: null, friendTimer: null };
function setWinterTurbo(active) {
  $('#login-view').classList.toggle('winter-turbo', active);
  // Change playback speed without restarting the 180-second route at a new position.
  $('.pixel-landscape')?.getAnimations?.().forEach(animation => animation.updatePlaybackRate(active ? 3 : 1));
  const button = $('#turbo-toggle');
  button.setAttribute('aria-pressed', String(active));
  button.textContent = active ? 'Turbo 3×' : 'Turbo';
}
function clearWinterEggs() {
  clearTimeout(winterEggs.turboTimer); clearTimeout(winterEggs.friendTimer);
  winterEggs.clicks = 0;
  setWinterTurbo(false);
  $('#winter-secret').hidden = true;
  $('#winter-aurora').hidden = true;
  $('#winter-egg-status').textContent = '';
}
function initWinterEasterEggs() {
  $('.turbo-snow').innerHTML = Array.from({ length: 14 }, (_, i) => `<i style="--spray-y:${(i % 7 - 3) * 14}px;--spray-delay:${i * .09}s;--spray-size:${3 + i % 3 * 2}px"></i>`).join('');
  const startTurbo = () => {
    if (state.theme !== 'dark' || $('#login-view').classList.contains('winter-turbo')) return;
    if (state.motionPaused) {
      $('#winter-egg-status').textContent = 'Bật chuyển động để dùng Turbo.';
      return;
    }
    setWinterTurbo(true);
    $('#winter-egg-status').textContent = 'Turbo mùa đông đã bật!';
    winterEggs.turboTimer = setTimeout(() => {
      setWinterTurbo(false);
      $('#winter-egg-status').textContent = '';
    }, 3000);
  };
  $('#car-easter-hit').addEventListener('click', startTurbo);
  $('#turbo-toggle').addEventListener('click', startTurbo);
  document.querySelectorAll('.winter-secret-logo').forEach(logo => logo.addEventListener('click', () => {
    if (state.theme !== 'dark') return;
    const now = Date.now();
    winterEggs.clicks = now - winterEggs.lastClick < 1800 ? winterEggs.clicks + 1 : 1;
    winterEggs.lastClick = now;
    if (winterEggs.clicks < 3) return;
    winterEggs.clicks = 0;
    clearTimeout(winterEggs.friendTimer);
    $('#winter-secret').hidden = false;
    $('#winter-aurora').hidden = false;
    winterEggs.friendTimer = setTimeout(() => {
      $('#winter-secret').hidden = true; $('#winter-aurora').hidden = true;
    }, 8000);
  }));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') clearWinterEggs(); });
}

function initWinterEffects() {
  let journeyStage=0;
  $('#journey-next')?.addEventListener('click', () => {
    journeyStage=(journeyStage+1)%6;
    const landscape=$('.pixel-landscape');
    const animation=landscape?.getAnimations?.()[0];
    if(animation) animation.currentTime=journeyStage*30000;
    else landscape?.style.setProperty('animation-delay', `${-journeyStage*30}s`);
    window.dispatchEvent(new CustomEvent('its:journey-next',{detail:journeyStage}));
  });
  document.addEventListener('visibilitychange', () => {
    $('#login-view').classList.toggle('journey-hidden', document.hidden);
  });
  document.querySelectorAll('.snowfield').forEach(field => {
    field.innerHTML = Array.from({ length: 30 }, (_, i) => `<i style="--x:${(i * 37 + 11) % 100}%;--drift:${(i % 5 - 2) * 28}px;--duration:${12 + i % 13}s;--delay:-${i * 2.3}s;--size:${i % 3 + 2}px;--alpha:${.2 + i % 4 * .12}"></i>`).join('');
  });
  const buttons = [$('#motion-toggle'), $('#login-motion-toggle')].filter(Boolean);
  const applyMotion = paused => {
    state.motionPaused = paused;
    if (paused) clearWinterEggs();
    document.body.classList.toggle('motion-paused', paused);
    document.querySelectorAll('[data-winter-art]').forEach(img => { img.src = themeAsset(img.dataset.winterArt); });
    buttons.forEach(button => {
      button.setAttribute('aria-pressed', String(paused));
      button.setAttribute('aria-label', paused ? 'Bật chuyển động' : 'Tạm dừng chuyển động');
      button.title = paused ? 'Bật chuyển động' : 'Tạm dừng chuyển động';
    });
    if ($('#login-motion-toggle')) $('#login-motion-toggle').innerHTML = `${icon(paused ? 'play' : 'pause')}<span>${paused ? 'Bật chuyển động' : 'Tạm dừng'}</span>`;
  };
  const preference = localStorage.getItem('its_reduce_motion');
  applyMotion(preference === 'true' || (preference === null && window.matchMedia('(prefers-reduced-motion: reduce)').matches));
  buttons.forEach(button => button.addEventListener('click', () => {
    applyMotion(!state.motionPaused);
    localStorage.setItem('its_reduce_motion', String(state.motionPaused));
  }));
}
function bindUpload(prefix,options={}) {
  const drop = $(`#${prefix}-drop`), input = $(`#${prefix}-file`);
  const preview = $(`#${prefix}-preview`), meta = $(`#${prefix}-meta`);
  const scanButton = $(`#${prefix}-scan`), scanResult = $(`#${prefix}-scan-result`);
  let selectedFile = null, previewUrl = '', scanController = null, scanVersion = 0, disposed = false,scanData=null,scanning=false;
  const restoredScan=workflowDrafts[prefix].scanData;
  const automatic=options.autoScan===true;
  $(`#${prefix}-plate`).value=workflowDrafts[prefix].plate;
  const scanLabel = `${icon('search')}${automatic?'Quét lại':'Quét biển số'}`;
  const resetScan = () => {
    scanController?.abort(); scanVersion++;
    scanning=false;
    scanData=null;workflowDrafts[prefix].scanData=null;
    scanButton.disabled = false; scanButton.innerHTML = scanLabel;
    scanResult.hidden = true; scanResult.innerHTML = '';
    delete scanResult.dataset.sessionError;
  };
  const reset = () => {
    camera.close(); resetScan(); scanButton.hidden = true;
    selectedFile = null; workflowDrafts[prefix].file = null; input.value = ''; preview.innerHTML = ''; meta.hidden = true; drop.hidden = false;
    if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = ''; }
  };
  const select = (file,restoring=false) => {
    if (!file) return false;
    if (!/\.(jpe?g|png|webp)$/i.test(file.name) || (file.type && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))) {
      input.value = ''; toast('Vui lòng chọn ảnh JPG, PNG hoặc WEBP', 'error'); return false;
    }
    if (!file.size || file.size > 10 * 1024 * 1024) {
      input.value = ''; toast(file.size ? 'Ảnh vượt quá 10 MB. Vui lòng chọn ảnh nhỏ hơn.' : 'Tệp ảnh trống. Vui lòng chọn ảnh khác.', 'error'); return false;
    }
    camera.close();
    if (selectedFile && selectedFile !== file) {
      // A correction for the previous photo must not be submitted with another vehicle.
      $(`#${prefix}-plate`).value = '';
      workflowDrafts[prefix].plate = '';
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    selectedFile = file; workflowDrafts[prefix].file = file; previewUrl = URL.createObjectURL(file);
    $(`#${prefix}-error`).hidden = true;
    preview.innerHTML = `<img src="${esc(previewUrl)}" alt="Ảnh biển số đã chọn" />`;
    $(`#${prefix}-filename`).textContent = file.name;
    meta.hidden = false; drop.hidden = true;
    resetScan(); scanButton.hidden = false;
    if(restoring && restoredScan?.file===file && Date.now()-restoredScan.at<540000){
      scanData=restoredScan;workflowDrafts[prefix].scanData=restoredScan;displayScan(restoredScan.ocr,false,'');
    }else if(automatic && canWrite()){
      scan();
    }
    return true;
  };
  const camera = bindCameraCapture(prefix, select, active => {
    drop.hidden = active || !!selectedFile; preview.hidden = active;
    meta.hidden = active || !selectedFile; scanButton.hidden = active || !selectedFile;
  });
  cameraClosers.add(camera.close);
  function displayScan(ocr,apply,startedPlate){
    const plate=(ocr.text||'').trim(),field=$(`#${prefix}-plate`);
    const usable=ocr.is_usable===true&&!ocr.ambiguous&&!ocr.ocr_disagreement;
    const shownFile=selectedFile,shownVersion=scanVersion;
    scanResult.innerHTML=plate
      ? `<span class="plate">${esc(plate)}</span> ${badge(usable?'Cần đối chiếu ảnh':'OCR chưa chắc chắn','warning')}${usable?'':'<p>Đối chiếu ảnh và nhập tay; không tự dùng kết quả chưa chắc chắn.</p>'}${!automatic&&usable?`<button type="button" class="btn btn-soft" id="${prefix}-use-scan">Dùng biển số đã đối chiếu</button>`:''}`
      : '<p>Chưa đọc chắc biển số. Nhập tay sau khi đối chiếu ảnh hoặc chụp lại rõ hơn.</p>';
    scanResult.hidden=false;
    if(automatic && apply && usable && plate && !startedPlate.trim() && field.value===startedPlate){
      field.value=plate;workflowDrafts[prefix].plate=plate;
      if(document.activeElement===document.body||document.activeElement===drop||document.activeElement===input){
        $(`#${prefix}-workflow`).focus({preventScroll:true});
      }
    }
    if(ocr.ai_analysis){
      const analysis=ocr.ai_analysis,details=[...(analysis.image_issues||[]),...(analysis.uncertain_characters||[])];
      const note=analysis.notes||ocr.quality_note||'';
      scanResult.innerHTML+=`<details class="ai-scan-analysis"${analysis.uncertain_characters?.length?' open':''}><summary>Chi tiết phân tích AI</summary><strong>${esc(ocr.model||'Phân tích ảnh')}</strong>${details.length?`<p>${esc(details.join(' · '))}</p>`:''}${note?`<p>${esc(note)}</p>`:''}</details>`;
    }
    if(!ocr.ai_analysis&&ocr.quality_note)scanResult.innerHTML+=`<p>${esc(ocr.quality_note)}</p>`;
    if(ocr.ai_status==='unavailable')scanResult.innerHTML+='<p>AI chưa kết nối được. Kết quả dự phòng cần đối chiếu trực tiếp với ảnh.</p>';
    if(!automatic && usable && plate)$(`#${prefix}-use-scan`).addEventListener('click',()=>{
      if(disposed||shownFile!==selectedFile||shownVersion!==scanVersion)return;field.value=plate;workflowDrafts[prefix].plate=plate;field.focus();
      $(`#${prefix}-use-scan`).textContent='Đã điền biển số';
    });
    options.onPlate?.(field.value);
  }
  const scan=async () => {
    if (!selectedFile || disposed || scanButton.disabled) return;
    const file = selectedFile, version = state.viewVersion, request = ++scanVersion;
    const startedPlate=$(`#${prefix}-plate`).value;
    scanController?.abort(); scanController = new AbortController();
    scanning=true;scanData=null;workflowDrafts[prefix].scanData=null;
    const body = new FormData(); body.append('file', file);
    scanButton.disabled = true; scanButton.innerHTML = '<span class="spinner"></span>Đang quét biển số…';
    scanResult.hidden = false;
    scanResult.innerHTML=`<p>Đang đọc biển số từ ảnh…</p><button type="button" class="btn btn-soft" id="${prefix}-cancel-scan">Dừng quét, nhập tay</button>`;
    $(`#${prefix}-cancel-scan`).addEventListener('click',()=>{
      if(request!==scanVersion)return;
      resetScan();scanResult.hidden=false;scanResult.textContent='Đã dừng quét. Đối chiếu ảnh rồi nhập biển số để xác nhận.';
      $(`#${prefix}-plate`).focus();
    });
    try {
      const data = await api('/ocr', { method: 'POST', body, signal: scanController.signal });
      if (disposed || request !== scanVersion || version !== state.viewVersion || file !== selectedFile) return;
      scanData={file,ocr:data.ocr||{},token:data.scan_token||'',at:Date.now()};
      workflowDrafts[prefix].scanData=scanData;
      displayScan(scanData.ocr,true,startedPlate);
    } catch (error) {
      if (!disposed && request === scanVersion && version === state.viewVersion && error.name !== 'AbortError') {
        scanResult.textContent = error.message; scanResult.hidden = false;
        if (state.sessionExpired) scanResult.dataset.sessionError = 'true';
      }
    } finally {
      if (!disposed && request === scanVersion) { scanning=false;scanButton.disabled = false; scanButton.innerHTML = scanLabel; }
    }
  };
  scanButton.addEventListener('click',scan);
  drop.addEventListener('click', () => input.click());
  $(`#${prefix}-replace`).addEventListener('click', () => { input.value = ''; input.click(); });
  input.addEventListener('change', () => select(input.files[0]));
  const zone = drop.closest('.upload-card');
  zone.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
  zone.addEventListener('dragleave', () => drop.classList.remove('drag'));
  zone.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); select(e.dataTransfer.files[0]); });
  $(`#${prefix}-remove`).addEventListener('click', reset);
  previewCleanups.push(() => {
    disposed = true; scanController?.abort(); camera.dispose();
    cameraClosers.delete(camera.close);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  });
  if (workflowDrafts[prefix].file) select(workflowDrafts[prefix].file,true);
  return { getFile: () => selectedFile, getScan:()=>scanData&&Date.now()-scanData.at<540000?scanData:null, isScanning:()=>scanning, reset };
}


function workflowTools(prefix) {
  return `<p class="workflow-hint">Ảnh và thông tin được giữ khi chuyển mục trong tab này.</p>
    <div class="workflow-tools"><span><kbd>Ctrl</kbd> + <kbd>Enter</kbd> để gửi</span><button type="button" class="text-btn" id="${prefix}-reset">Làm lại</button></div>`;
}
function workflowError(prefix, message, focus) {
  const target = $(`#${prefix}-error`);
  target.textContent = message; target.hidden = false;
  if (state.sessionExpired) target.dataset.sessionError = 'true';
  focus?.focus();
}
function bindWorkflow(prefix, upload, resetSelection = () => {}) {
  const draft = workflowDrafts[prefix], plate = $(`#${prefix}-plate`);
  plate.value = draft.plate;
  if (prefix==='entry') $('#entry-vehicle-type').value=draft.vehicle_type || 'motorcycle';
  const remember = () => {
    draft.plate = plate.value;
    if (prefix==='entry') draft.vehicle_type=$('#entry-vehicle-type').value || 'motorcycle';
    if (prefix === 'exit') { draft.ticket = $('#exit-ticket').value; draft.search = $('#exit-ticket-search').value; }
  };
  plate.addEventListener('input', () => { remember(); $(`#${prefix}-error`).hidden = true; });
  if (prefix==='entry') $('#entry-vehicle-type').addEventListener('change',remember);
  previewCleanups.push(remember);
  $(`#${prefix}-reset`).addEventListener('click', () => {
    if (state.workflowPending) return;
    upload.reset(); plate.value = ''; draft.plate = '';
    $(`#${prefix}-result`).innerHTML = ''; $(`#${prefix}-error`).hidden = true;
    resetSelection();
    $(`#${prefix}-drop`).focus();
  });
  $(`#${prefix}-workflow`).addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.repeat && !event.isComposing && !state.sessionExpired) {
      event.preventDefault(); $(`#${prefix}-submit`).click();
    }
  });
}
async function runWorkflow(prefix, btn, label, action) {
  if (btn.disabled || state.workflowPending) return;
  $(`#${prefix}-error`).hidden = true; state.workflowPending = true;
  try {
    await runPending(btn, label, async () => {
      try { await action(); }
      catch (error) { workflowError(prefix, error.message); }
    });
  } finally { state.workflowPending = false; }
}
function bindLiveTicketSearch(page) {
  const local=bindTicketSearch(page.items||[]),input=$('#exit-ticket-search'),select=$('#exit-ticket');
  const count=$('#exit-ticket-count'),refresh=$('#exit-ticket-refresh'),previous=$('#exit-ticket-prev'),next=$('#exit-ticket-next');
  const version=state.viewVersion;
  let total=page.total??(page.items||[]).length,offset=0,query='',exact='',pending=false,failed=false,disposed=false,request=0,controller,timer;
  const key=value=>String(value||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
  const alive=()=>!disposed&&state.view==='exit'&&state.viewVersion===version;
  const controls=()=>{
    refresh.disabled=pending;previous.disabled=pending||offset===0;next.disabled=pending||failed||offset+50>=total;
    const button=$('#exit-submit');button.dataset.keepDisabled=String(!canWrite()||!total||pending);
    if(!state.workflowPending)button.disabled=button.dataset.keepDisabled==='true';
    if(!pending)count.textContent=failed?'Chưa tải được danh sách vé. Bấm Làm mới vé để thử lại.':total?`${Math.min(offset+1,total)}–${Math.min(offset+local.remaining(),total)} / ${total} vé · Trang ${Math.floor(offset/50)+1}`:'Không có vé phù hợp. Thử biển số, mã vé khác hoặc làm mới danh sách.';
  };
  const invalidate=()=>{clearTimeout(timer);controller?.abort();request++;pending=false;};
  async function load(q='',plate='',position=0,match=false) {
    invalidate();const current=request;query=q;exact=plate;offset=position;pending=true;failed=false;
    controller=new AbortController();select.disabled=true;count.textContent='Đang tìm vé trên máy chủ…';controls();
    const params=new URLSearchParams({limit:'50',status:'IN_PARKING'});
    if(q)params.set('q',q);if(plate)params.set('plate',plate);if(position)params.set('offset',String(position));
    try{
      const result=await api('/tickets/active?'+params,{signal:controller.signal});
      if(!alive()||current!==request)return false;
      const records=(result.items||[]).filter(item=>item.status==='IN_PARKING');
      total=result.total??records.length;
      if(total&&position>=total)return load(q,plate,Math.floor((total-1)/50)*50,match);
      local.replace(records);
      if(match)local.matchPlate($('#exit-plate').value);
      return true;
    }catch(error){
      if(alive()&&current===request&&error.name!=='AbortError'){
        failed=true;
        $('#exit-match-note').textContent=error.message+' Bấm Làm mới vé để thử lại; ảnh và biển số vẫn được giữ.';
        local.replace([]);
      }
      return false;
    }finally{if(alive()&&current===request){pending=false;controls();}}
  }
  const search=()=>{
    invalidate();local.search();pending=true;select.disabled=true;count.textContent='Đang tìm vé trên máy chủ…';controls();
    timer=setTimeout(()=>load(input.value.trim()),250);
  };
  input.addEventListener('input',search);
  refresh.addEventListener('click',()=>load(input.value.trim()||(workflowDrafts.exit.ticketManual?workflowDrafts.exit.ticket:''),
    !input.value.trim()&&!workflowDrafts.exit.ticketManual?key($('#exit-plate').value):'',0,true));
  previous.addEventListener('click',()=>load(query,exact,Math.max(0,offset-50)));
  next.addEventListener('click',()=>load(query,exact,offset+50));
  previewCleanups.push(()=>{disposed=true;invalidate();});
  controls();
  return {
    isPending:()=>pending,
    remaining:()=>total,
    remove:id=>{local.remove(id);total=Math.max(0,total-1);controls();},
    clear:()=>{invalidate();local.clear();return load();},
    choose:async id=>{
      invalidate();if(local.has(id)){controls();return local.choose(id);}
      if(!await load(id))return false;
      return local.choose(id);
    },
    matchPlate:(plate,options={})=>{
      if(workflowDrafts.exit.ticketManual||input.value.trim()){local.matchPlate(plate);return;}
      invalidate();select.value='';workflowDrafts.exit.ticket='';
      if(!key(plate)){local.matchPlate('');controls();return;}
      pending=true;select.disabled=true;count.textContent='Đang tìm vé khớp chính xác…';controls();
      if(options.debounce)timer=setTimeout(()=>load('',key(plate),0,true),250);
      else return load('',key(plate),0,true);
    },
  };
}

function bindTicketSearch(initialItems) {
  let items = initialItems;
  const input = $('#exit-ticket-search'), select = $('#exit-ticket'), count = $('#exit-ticket-count');
  const draft = workflowDrafts.exit;
  let manualChoice=!!draft.ticketManual,userSearch=false;
  const key = value => String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  input.value = draft.search;
  select.value = draft.ticket;
  const render = () => {
    const selected = select.value, query = key(input.value);
    const filtered = items.filter(item => key(item.plate_entry).includes(query) || key(item.ticket_id).includes(query));
    select.innerHTML = `<option value="">${!items.length ? 'Chưa có vé đang trong bãi' : filtered.length ? 'Chọn vé để đối chiếu' : 'Không tìm thấy vé phù hợp'}</option>` + filtered.map(item => `<option value="${esc(item.ticket_id)}">${esc(item.plate_entry || 'Chưa rõ biển')} · ${esc(item.ticket_id)}</option>`).join('');
    select.value = filtered.some(item => item.ticket_id === selected) ? selected : '';
    if(selected&&!select.value){manualChoice=false;draft.ticketManual=false;}
    draft.ticket = select.value; draft.search = input.value;
    select.disabled = !filtered.length;
    count.textContent = items.length ? `${filtered.length} / ${items.length} vé${query && !filtered.length ? ' · Thử một phần biển số hoặc mã vé.' : ''}` : 'Chưa có xe trong bãi. Ghi nhận xe vào trước khi xử lý xe ra.';
  };
  const search=()=>{userSearch=!!input.value.trim();render();if(!select.value)manualChoice=false;};
  input.addEventListener('input',search);
  select.addEventListener('change', () => { draft.ticket = select.value;manualChoice=!!select.value;draft.ticketManual=manualChoice; $('#exit-error').hidden = true;actions.matchPlate($('#exit-plate').value); });
  render();
  const actions = {
    search,
    has:id=>items.some(item=>item.ticket_id===id),
    replace:records=>{items=records;render();},
    remaining: () => items.length,
    remove: id => { items = items.filter(item => item.ticket_id !== id); render(); },
    clear: () => { input.value = ''; select.value = '';manualChoice=false;userSearch=false;draft.ticketManual=false;render();$('#exit-match-note').textContent=''; },
    choose: id => { input.value=''; render(); select.value=items.some(item=>item.ticket_id===id)?id:''; draft.ticket=select.value;manualChoice=!!select.value;draft.ticketManual=manualChoice;return !!select.value; },
    matchPlate:plate=>{
      const compact=key(plate),matches=items.filter(item=>key(item.plate_entry)===compact);
      if(!manualChoice&&!userSearch){
        input.value='';render();select.value=compact&&matches.length===1?matches[0].ticket_id:'';draft.ticket=select.value;
      }
      const chosen=items.find(item=>item.ticket_id===select.value);
      $('#exit-match-note').textContent=!compact?'':chosen?(key(chosen.plate_entry)===compact?'Biển số khớp vé đang chọn.':'Biển số ảnh khác vé đang chọn. Kiểm tra lại; nếu tiếp tục, vé cần duyệt.'):
        matches.length>1?'Có nhiều vé cùng biển số. Chọn đúng vé bên dưới.':'Chưa tìm được vé khớp chính xác. Bạn có thể chọn vé hoặc tìm bằng mã/QR.';
    },
  };
  return actions;
}

async function runPending(btn, label, action) {
  if (btn.disabled) return;
  const original = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>${esc(label)}`;
  try { await action(); } catch (ex) { toast(ex.message, 'error'); }
  finally { btn.disabled = btn.dataset.keepDisabled === 'true'; btn.innerHTML = original; }
}

/* ====== INIT ====== */
document.addEventListener('DOMContentLoaded', async () => {
  syncIcons();
  initThemeControls();
  initPasswordLamp();
  initWinterEffects();
  initWinterEasterEggs();
  initTicketTools();
  $('#refresh-btn').addEventListener('click', () => showView(state.view));
  const tickClock = () => { $('#clock').textContent = new Date().toLocaleTimeString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh'}); };
  tickClock();
  setInterval(tickClock, 1000);

  $('#login-form').addEventListener('submit', doLogin);
  $('#session-form').addEventListener('submit', doSessionLogin);
  $('#session-switch').addEventListener('click',logout);
  $('#session-dialog').addEventListener('cancel', event => { if (state.sessionExpired) event.preventDefault(); });
  $('#logout-btn').addEventListener('click', logout);
  document.querySelectorAll('.nav-item').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));

  if (state.token) {
    try {
      const me = await api('/auth/me');
      state.user = me.user;
      enterApp();
      return;
    } catch (_) { localStorage.removeItem(TOKEN_KEY); state.token = ''; }
  }
  $('#login-view').hidden = false;
});

