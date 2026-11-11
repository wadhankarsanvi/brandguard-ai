/* BrandGuard AI — single-page frontend (vanilla JS, no build step).
   Routing: hash based. Views are functions returning HTML + an optional bind(root) for events. */
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const S = { user: null, token: localStorage.getItem('bg_token'), queue: 0 };
const STAGES = [['creator', 'Draft'], ['manager', 'Brand manager'], ['legal', 'Legal'], ['published', 'Published']];
const LABEL = { draft: 'Draft', analyzed: 'Analysed', in_review: 'In review', approved: 'Approved', changes_requested: 'Changes requested', rejected: 'Rejected' };

/* ---------- helpers & accessibility ---------- */
function initTheme() {
  const saved = localStorage.getItem('bg_theme');
  if (saved === 'dark' || saved === 'light') {
    document.documentElement.setAttribute('data-theme', saved);
  }
}
initTheme();

function isDarkMode() {
  const cur = document.documentElement.getAttribute('data-theme');
  if (cur === 'dark') return true;
  if (cur === 'light') return false;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function toggleTheme() {
  const next = isDarkMode() ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('bg_theme', next);
  updateThemeBtn();
}

function updateThemeBtn() {
  const btn = $('#theme-btn');
  if (!btn) return;
  const dark = isDarkMode();
  btn.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
  btn.setAttribute('title', dark ? 'Switch to light mode' : 'Switch to dark mode');
  btn.innerHTML = dark
    ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`
    : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
}

function toggleMobileMenu(force) {
  S.menuOpen = force !== undefined ? force : !S.menuOpen;
  const side = $('.side');
  if (side) side.classList.toggle('menu-open', S.menuOpen);
}

window.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

function toast(msg, err) {
  const t = $('#toast');
  if (!t) return;
  t.textContent = msg;
  t.setAttribute('role', err ? 'alert' : 'status');
  t.setAttribute('aria-live', err ? 'assertive' : 'polite');
  t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.className = '', 3200);
}
async function api(path, o = {}) {
  const h = { ...(S.token ? { Authorization: 'Bearer ' + S.token } : {}) };
  let body;
  if (o.json !== undefined) { h['Content-Type'] = 'application/json'; body = JSON.stringify(o.json); } else if (o.form) body = o.form;
  const r = await fetch('/api' + path, { method: o.method || (body ? 'POST' : 'GET'), headers: h, body });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && S.token && !path.startsWith('/auth/login')) { logout(); throw new Error(data.error || 'Signed out'); }
  if (!r.ok) throw new Error(data.error || 'Request failed');
  return data;
}
async function act(fn, ok) { try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, true); } }
function logout() { S.token = null; S.user = null; localStorage.removeItem('bg_token'); location.hash = '#/login'; }
function fmt(ts) { return ts ? new Date(ts.replace(' ', 'T') + 'Z').toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : ''; }
const pill = s => `<span class="pill ${s}">${LABEL[s] || s}</span>`;
const sev = s => `<span class="sev ${s}">${s}</span>`;
function ring(score) {
  const c = score >= 80 ? 'var(--green)' : score >= 60 ? '#d4a800' : 'var(--crit)';
  const s = score ?? 0;
  const r = 30, circ = Math.round(2 * Math.PI * r);
  const offset = Math.round(circ - (s / 100) * circ);
  return `<svg width="86" height="86" viewBox="0 0 86 86" aria-label="Compliance score ${score ?? '–'}">
    <circle cx="43" cy="43" r="${r}" fill="none" stroke="var(--line)" stroke-width="8"/>
    <circle cx="43" cy="43" r="${r}" fill="none" stroke="${c}" stroke-width="8" stroke-dasharray="${circ}" stroke-dashoffset="${offset}" stroke-linecap="round" transform="rotate(-90 43 43)"/>
    <text x="43" y="49" text-anchor="middle" font-size="20" font-weight="700" fill="var(--ink)">${score ?? '–'}</text>
  </svg>`;
}
const isReviewer = () => S.user && S.user.role !== 'creator';
function modal(html, bind) {
  const m = $('#modal');
  m.innerHTML = `<div class="card" role="dialog" aria-modal="true">${html}</div>`;
  m.hidden = false;
  m.onclick = e => { if (e.target === m) closeModal(); };
  bind && bind(m);
}
function closeModal() { $('#modal').hidden = true; }

/* ---------- shell ---------- */
const LOGO = `<svg width="30" height="30" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#2e7d32"/><path d="M16 6l8 3v7c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V9z" fill="#fff" opacity=".95"/><path d="M12 16l3 3 5-6" stroke="#2e7d32" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
function toggleNotifications(force) {
  S.notifOpen = force !== undefined ? force : !S.notifOpen;
  const drop = $('#ndrop');
  if (drop) {
    if (S.notifOpen) drop.removeAttribute('hidden');
    else drop.setAttribute('hidden', '');
  }
}
async function fetchNotifications() {
  if (!S.token) return;
  try {
    const data = await api('/notifications');
    S.notifications = data.notifications || [];
    S.unreadNotifications = data.unread || 0;
    const bell = $('#nbell');
    if (bell) {
      const b = bell.querySelector('.notif-badge');
      if (S.unreadNotifications) {
        if (b) b.textContent = S.unreadNotifications;
        else bell.insertAdjacentHTML('beforeend', `<span class="notif-badge">${S.unreadNotifications}</span>`);
      } else if (b) b.remove();
    }
  } catch (e) {}
}
async function readAllNotifications() {
  await api('/notifications/read-all', { method: 'POST' });
  S.unreadNotifications = 0;
  (S.notifications || []).forEach(n => n.read = 1);
  const bell = $('#nbell');
  if (bell) { const b = bell.querySelector('.notif-badge'); if (b) b.remove(); }
  route();
}
function shell(active, inner) {
  const nav = (h, t, extra = '') => `<a class="nav ${active === h ? 'active' : ''}" href="#/${h}">${t}${extra}</a>`;
  const unreadCount = S.unreadNotifications || 0;
  const notifs = S.notifications || [];
  const notifDropdown = `
    <div id="ndrop" class="notif-dropdown" ${S.notifOpen ? '' : 'hidden'}>
      <div class="notif-header">
        <b>Notifications</b>
        ${unreadCount ? `<a href="#/notifications" id="notif-read-all" class="notif-read-btn">Mark all read</a>` : ''}
      </div>
      <div>
        ${notifs.length ? notifs.map(n => `
          <a href="${n.submission_id ? `#/s/${n.submission_id}` : 'javascript:void(0)'}" class="notif-item ${n.read ? '' : 'unread'}">
            <div class="notif-title">${esc(n.message)}</div>
            <div class="notif-time">${fmt(n.created_at)}</div>
          </a>
        `).join('') : '<div class="small notif-empty">No notifications</div>'}
      </div>
    </div>`;

  const dark = isDarkMode();
  const themeSvg = dark
    ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`
    : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;

  return `<div class="shell"><aside class="side">
    <div class="brand-wrap">
      <div class="brand">${LOGO}<span>BrandGuard AI</span></div>
      <div class="row">
        <button id="theme-btn" class="theme-btn" aria-label="${dark ? 'Switch to light mode' : 'Switch to dark mode'}" title="${dark ? 'Switch to light mode' : 'Switch to dark mode'}">
          ${themeSvg}
        </button>
        <button id="nbell" class="notif-btn" aria-label="Notifications" title="Notifications">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>
          ${unreadCount ? `<span class="notif-badge">${unreadCount}</span>` : ''}
        </button>
        <button id="menu-btn" class="mobile-menu-btn" aria-label="Toggle navigation menu" title="Menu">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
        </button>
      </div>
    </div>
    ${notifDropdown}
    <div class="nav-links">
      ${nav('dashboard', 'Dashboard')}${nav('submissions', S.user ? (S.user.role === 'creator' ? 'My content' : 'All content') : 'Content')}
      ${nav('new', 'New check')}${isReviewer() ? nav('queue', 'Review queue', S.queue ? `<span class="count">${S.queue}</span>` : '') : ''}
      ${nav('kb', 'Knowledge base')}${nav('rules', 'Brand rules')}${isReviewer() ? nav('audit', 'Audit log') : ''}${nav('verify', 'Verify badge')}
      <div class="me"><b>${esc(S.user ? S.user.name : '')}</b>${esc(S.user ? S.user.role : '')} · ${esc(S.user ? (S.user.team || '') : '')}<br><button id="out">Sign out</button> <a href="#/change-password" id="change-pw-link" class="small muted change-pw-link">Change password</a></div>
    </div></aside>
    <main>${inner}</main></div>`;
}
function changePasswordModal() {
  modal(`<h2>Change password</h2><form id="cpf">
    <label>Current password</label><input type="password" id="cur_pw" required>
    <label>New password</label><input type="password" id="new_pw" required minlength="6">
    <div class="row mt"><button class="btn">Update password</button><button type="button" class="btn ghost" id="cpc">Cancel</button></div>
  </form>`, m => {
    $('#cpc', m).onclick = closeModal;
    $('#cpf', m).onsubmit = async e => {
      e.preventDefault();
      const ok = await act(() => api('/auth/change-password', {
        method: 'POST',
        json: { current_password: $('#cur_pw', m).value, new_password: $('#new_pw', m).value }
      }), 'Password updated');
      if (ok) closeModal();
    };
  });
}
function skeletonHtml() {
  return `<div aria-busy="true" aria-label="Loading page">
    <div class="head"><div><div class="skeleton-bar skeleton-title"></div><div class="skeleton-bar skeleton-sub"></div></div></div>
    <div class="grid g4 mb-16"><div class="card"><div class="skeleton-bar skeleton-kpi-val"></div><div class="skeleton-bar skeleton-kpi-lbl"></div></div>
      <div class="card"><div class="skeleton-bar skeleton-kpi-val"></div><div class="skeleton-bar skeleton-kpi-lbl"></div></div>
      <div class="card"><div class="skeleton-bar skeleton-kpi-val"></div><div class="skeleton-bar skeleton-kpi-lbl"></div></div>
      <div class="card"><div class="skeleton-bar skeleton-kpi-val"></div><div class="skeleton-bar skeleton-kpi-lbl"></div></div></div>
    <div class="card mt"><div class="skeleton-box skeleton-card-body"></div></div>
  </div>`;
}
async function render(active, loader) {
  const app = $('#app');
  const main = app ? app.querySelector('main') : null;
  if (main) {
    main.innerHTML = skeletonHtml();
  } else if (app && S.token) {
    app.innerHTML = shell(active, skeletonHtml());
    updateThemeBtn();
  }
  try {
    const { html, bind } = await loader();
    app.innerHTML = shell(active, html);
    updateThemeBtn();
    $('#out') && ($('#out').onclick = logout);
    bind && bind(app);
    window.scrollTo(0, 0);
  } catch (e) {
    app.innerHTML = shell(active, `<div class="card empty empty-card">
      <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="var(--crit)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="empty-icon"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      <h2>Unable to load page</h2>
      <p class="muted mb-16">${esc(e.message || 'An unexpected error occurred.')}</p>
      <button class="btn sm" id="err-retry">Try again</button>
    </div>`);
    updateThemeBtn();
    $('#err-retry') && ($('#err-retry').onclick = () => route());
    $('#out') && ($('#out').onclick = logout);
  }
}

/* ---------- login ---------- */
function loginView() {
  const demos = [['creator@brandguard.ai', 'Creator · Aisha (Marketing)'], ['creator2@brandguard.ai', 'Creator · Dev (Social)'], ['manager@brandguard.ai', 'Brand manager · Maya'], ['legal@brandguard.ai', 'Legal reviewer · Rohan']];
  $('#app').innerHTML = `<div class="login"><div class="card"><div class="row mb-14">${LOGO}<h1>BrandGuard AI</h1></div>
    <p class="muted mb-6">Pre-publication brand governance with explainable, cited feedback.</p>
    <form id="lf"><label>Email</label><input type="email" id="em" required value="creator@brandguard.ai"><label>Password</label><input type="password" id="pw" required value="BrandGuard@123">
    <button class="btn mt w-full jc-center">Sign in</button></form>
    <div class="demo"><span class="small muted">Demo accounts (password <code>BrandGuard@123</code>)</span>${demos.map(d => `<button data-e="${d[0]}">${d[1]}</button>`).join('')}</div></div></div>`;
  $$('.demo button').forEach(b => b.onclick = () => $('#em').value = b.dataset.e);
  $('#lf').onsubmit = async e => {
    e.preventDefault();
    const r = await act(() => api('/auth/login', { json: { email: $('#em').value, password: $('#pw').value } }));
    if (r) { S.token = r.token; S.user = r.user; localStorage.setItem('bg_token', r.token); location.hash = '#/dashboard'; }
  };
}

/* ---------- dashboard ---------- */
const hbar = (label, n, max, extra = '') => {
  const pct = max ? Math.max(3, Math.round(n / max * 100)) : 0;
  return `<div class="hbar-wrap"><div class="row small"><span>${esc(label)}</span><span class="right muted">${n}${extra}</span></div><div class="bar"><svg width="100%" height="9" class="bar-svg"><rect width="100%" height="9" rx="4.5" fill="var(--line)"/><rect width="${pct}%" height="9" rx="4.5" fill="var(--green)"/></svg></div></div>`;
};
function trendSvg(t) {
  if (t.length < 2) return '<div class="empty small">Not enough history yet</div>';
  const W = 520, H = 120, xs = t.map((_, i) => 10 + i * (W - 20) / (t.length - 1)), ys = t.map(p => H - 12 - (p.avg_score / 100) * (H - 28));
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Average compliance score by day"><polyline fill="none" stroke="#2e7d32" stroke-width="2.5" points="${xs.map((x, i) => x + ',' + ys[i]).join(' ')}"/>
    ${xs.map((x, i) => `<circle cx="${x}" cy="${ys[i]}" r="4" fill="#2e7d32"><title>${t[i].day}: ${t[i].avg_score}</title></circle>`).join('')}</svg>
    <div class="row small muted"><span>${t[0].day}</span><span class="right">${t[t.length - 1].day}</span></div>`;
}
async function dashboard() {
  const a = await api('/analytics'), k = a.kpis, mx = Math.max(1, ...a.by_rule.map(r => r.count));
  const cm = Math.max(1, ...a.by_category.map(c => c.n));
  return {
    html: `<div class="head"><div><h1>Brand health</h1><p>${S.user.role === 'creator' ? 'Your compliance at a glance.' : 'Governance telemetry across all teams.'}</p></div><a class="btn" href="#/new">Check new content</a></div>
    <div class="grid g4"><div class="card kpi"><div class="v">${k.submissions}</div><div class="l">Assets checked</div></div>
      <div class="card kpi"><div class="v">${k.avg_score ?? '–'}</div><div class="l">Average compliance score</div></div>
      <div class="card kpi"><div class="v">${k.approved}<span class="muted kpi-sub"> / ${k.in_review} in review</span></div><div class="l">Approved & published</div></div>
      <div class="card kpi"><div class="v">${k.issues_fixed}<span class="muted kpi-sub"> / ${k.issues_detected}</span></div><div class="l">Issues fixed before publishing</div></div></div>
    <div class="grid g2 mt"><div class="card"><h2>Most violated rules</h2>${a.by_rule.map(r => hbar(r.name, r.count, mx, ` · ${r.creators} creator${r.creators > 1 ? 's' : ''}`)).join('') || '<div class="empty">No data yet</div>'}</div>
      <div class="card"><h2>Compliance trend</h2><div class="mt">${trendSvg(a.trend)}</div><h2 class="mt">Issues by category</h2>${a.by_category.map(c => hbar(c.category || 'other', c.n, cm)).join('')}</div></div>
    <div class="grid g2 mt"><div class="card"><h2>Team scorecard</h2><div class="table-wrap"><table><tr><th>Team</th><th>Assets</th><th>Approved</th><th>Avg score</th></tr>
      ${a.by_team.map(t => `<tr><td>${esc(t.team)}</td><td>${t.submissions}</td><td>${t.approved}</td><td><b>${t.avg_score ?? '–'}</b></td></tr>`).join('')}</table></div></div>
      <div class="card"><h2>Guideline feedback loop</h2><p class="muted small mt-4">Rules that many creators trip over <i>and</i> often dismiss are probably unclear — fix the guideline, not the people.</p>
      ${a.ambiguous_guidelines.length ? a.ambiguous_guidelines.map(g => `<div class="issue medium"><b>${esc(g.name)}</b> <span class="chip">ambiguity ${g.ambiguity}</span>
        <div class="small muted">${g.count} hits · ${g.creators} creators · ${g.dismissed} dismissed</div><div class="small">${esc(g.hint)}</div></div>`).join('')
        : '<div class="empty small">No ambiguous guidelines detected yet. As creators dismiss flags, unclear rules surface here.</div>'}</div></div>`
  };
}

/* ---------- lists ---------- */
function subTable(rows) {
  if (!rows.length) return `<div class="empty empty-card">
    <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" class="empty-icon"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="12" y1="18" x2="12" y2="12"></line><line x1="9" y1="15" x2="15" y2="15"></line></svg>
    <h3 class="mb-6">No content here yet</h3>
    <p class="muted small mb-16">Upload copy or assets to run automatic brand governance checks.</p>
    <a class="btn sm" href="#/new">+ New check</a>
  </div>`;
  return `<div class="table-wrap"><table><tr><th>Title</th><th>Type</th><th>Creator</th><th>Status</th><th>Score</th><th>Updated</th></tr>${rows.map(r => `<tr class="click" data-id="${r.id}" tabindex="0" role="link" aria-label="Open ${esc(r.title)}">
    <td><b>${esc(r.title)}</b>${r.requires_legal ? ' <span class="chip">legal</span>' : ''}</td><td>${r.kind}</td><td>${esc(r.creator_name)}<div class="small muted">${esc(r.team || '')}</div></td>
    <td>${pill(r.status)}${r.status === 'in_review' ? `<div class="small muted">waiting: ${r.stage}</div>` : ''}</td><td><b>${r.score ?? '–'}</b></td><td class="small muted">${fmt(r.updated_at)}</td></tr>`).join('')}</table></div>`;
}
const bindRows = root => $$('tr.click', root).forEach(tr => {
  tr.onclick = () => location.hash = '#/s/' + tr.dataset.id;
  tr.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); location.hash = '#/s/' + tr.dataset.id; } };
});
async function submissions(queue) {
  const rows = await api('/submissions' + (queue ? '?queue=1' : ''));
  S.queue = queue ? rows.length : S.queue;
  return { html: `<div class="head"><div><h1>${queue ? 'Review queue' : S.user.role === 'creator' ? 'My content' : 'All content'}</h1><p>${queue ? 'Items waiting for your sign-off.' : 'Every asset with its latest compliance score.'}</p></div>
    ${queue ? '' : '<a class="btn" href="#/new">New check</a>'}</div><div class="card">${subTable(rows)}</div>`, bind: bindRows };
}

/* ---------- new check ---------- */
function newCheck() {
  return {
    html: `<div class="head"><div><h1>New compliance check</h1><p>Paste copy, or upload a Markdown/TXT/PDF document or a PNG/JPEG asset. Text and image engines run automatically.</p></div></div>
    <div class="card"><form id="nf"><label>Title</label><input type="text" id="t" placeholder="e.g. Spring campaign launch post">
    <label>Copy / text content</label><textarea id="x" rows="9" placeholder="Paste your draft here…"></textarea>
    <div class="grid g2"><div><label>…or upload a file (.md .txt .pdf .png .jpg)</label><input type="file" id="f" accept=".md,.txt,.pdf,.png,.jpg,.jpeg"></div>
    <div><label>Alt text (for images)</label><input type="text" id="alt" placeholder="Describe what the image conveys"></div></div>
    <p class="disclose">Privacy shield: files stay on this server. If an external AI model is configured, personal data is masked before any text leaves the platform.</p>
    <div class="row"><button class="btn">Run governance check</button><button type="button" class="btn ghost" id="demo">Load sample draft</button></div></form></div>`,
    bind: r => {
      $('#demo', r).onclick = () => { $('#t').value = 'Spring launch post'; $('#x').value = 'Meet the NEW Verdant Everyday Bottle!! It is our most revolutionary product ever.\n\nVerdantCo guys made it 100% eco-friendly and it keeps drinks cold for 36 hours. Our customers love how cheap it is.\n\nGet 30% off this week. Email me at priya.sharma@gmail.com or call 98765 43210. Click here to buy.'; };
      $('#nf', r).onsubmit = async e => {
        e.preventDefault();
        const fd = new FormData(); fd.append('title', $('#t').value); fd.append('text', $('#x').value); fd.append('alt_text', $('#alt').value);
        if ($('#f').files[0]) fd.append('file', $('#f').files[0]);
        const btn = $('#nf button'); btn.disabled = true; btn.textContent = 'Analysing…';
        const res = await act(() => api('/submissions', { form: fd }));
        if (res) location.hash = '#/s/' + res.id; else { btn.disabled = false; btn.textContent = 'Run governance check'; }
      };
    }
  };
}

/* ---------- submission detail ---------- */
let SEL = null, TAB = 'analysis';
function annotate(text, issues, pageMap) {
  if (pageMap && pageMap.length > 1) {
    return pageMap.map(pm => {
      const pText = text.slice(pm.start, pm.end);
      const pIssues = issues.filter(i => i.start != null && i.start >= pm.start && i.start < pm.end).map(i => ({
        ...i,
        start: i.start - pm.start,
        end: Math.min(i.end - pm.start, pText.length)
      }));
      return `<div class="page-sep">— Page ${pm.page} —</div>` + annotateText(pText, pIssues);
    }).join('');
  }
  return annotateText(text, issues);
}
function annotateText(text, issues) {
  const spans = issues.filter(i => i.start != null && i.end > i.start).sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));
  let out = '', cur = 0;
  for (const i of spans) {
    if (i.start < cur) continue;
    out += esc(text.slice(cur, i.start)) + `<mark class="${i.status === 'open' ? i.severity : i.status}" data-i="${i.id}" title="${esc(i.message)}">${esc(text.slice(i.start, i.end))}</mark>`;
    cur = i.end;
  }
  out += esc(text.slice(cur));
  const zero = issues.filter(i => i.start != null && i.end === i.start && i.status === 'open');
  return out + zero.map(i => `<span class="endmark" data-i="${i.id}">＋ ${esc(i.suggestion.trim())}</span>`).join('');
}
function drawImage(d) {
  const c = $('#cv'); if (!c) return;
  const img = new Image();
  img.onload = () => {
    c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.drawImage(img, 0, 0);
    const col = { critical: '#b3261e', high: '#e8590c', medium: '#d4a800', minor: '#3d5a80' };
    d.issues.filter(i => i.bbox && i.status === 'open').forEach(i => {
      const [bx, by, bw, bh] = i.bbox; x.lineWidth = Math.max(3, img.width / 220); x.strokeStyle = col[i.severity] || '#d00';
      x.strokeRect(bx, by, bw, bh); x.fillStyle = x.strokeStyle; x.font = `bold ${Math.max(14, img.width / 50)}px sans-serif`;
      x.fillText('#' + i.id, bx + 4, Math.max(16, by - 6));
    });
  };
  fetch(d.submission.image_url, { headers: { Authorization: 'Bearer ' + S.token } }).then(r => r.blob()).then(b => img.src = URL.createObjectURL(b));
}
function issueCard(i, editable) {
  const c = i.citation || {}, off = i.status !== 'open';
  return `<div class="issue ${i.severity} ${off ? 'off' : ''} ${SEL === i.id ? 'sel' : ''}" id="is${i.id}" data-i="${i.id}" tabindex="0" role="region" aria-label="Issue #${i.id}: ${esc(i.rule_key || i.category)} (${i.severity})">
    <div class="row">${sev(i.severity)}<span class="chip">${esc(i.category)}</span>${i.page ? `<span class="chip">p.${i.page}</span>` : ''}${i.bbox ? `<span class="chip">#${i.id} region</span>` : ''}${off ? `<span class="chip">${i.status}</span>` : ''}</div>
    <div class="mt-6">${esc(i.message)}</div>
    ${i.excerpt && !i.bbox ? `<div class="small muted mt-4">“${esc(i.excerpt)}”</div>` : ''}
    ${c.quote ? `<div class="cite"><b>${esc(c.source || '')}</b>${c.doc_title ? ` <span class="muted">· ${esc(c.doc_title)}</span>` : ''}${c.score ? ` <span class="chip">match ${c.score}</span>` : ''}<q>${esc(c.quote)}</q></div>` : ''}
    ${i.suggestion != null && i.start != null ? `<div class="fix"><del>${esc(i.match || '∅')}</del> → <ins>${esc(i.suggestion.trim() || '(remove)')}</ins></div>` : (i.suggestion ? `<div class="fix">${esc(i.suggestion)}</div>` : '')}
    <div class="row">${editable && i.status === 'open' && i.suggestion != null && i.start != null ? `<button class="btn sm" data-apply="${i.id}">Apply fix</button>` : ''}
      ${editable && i.status === 'open' ? `<button class="btn sm ghost" data-dismiss="${i.id}">Dismiss</button>` : ''}
      ${editable && i.status === 'dismissed' ? `<button class="btn sm ghost" data-reopen="${i.id}">Reopen</button>` : ''}
      <button class="btn sm ghost" data-discuss="${i.id}">Discuss / escalate</button></div></div>`;
}
function commentsHtml(d) {
  const by = {}; d.comments.forEach(c => (by[c.parent_id || 0] ||= []).push(c));
  const one = (c, reply) => `<div class="comment ${reply ? 'reply' : ''}"><div class="row small"><b>${esc(c.author)}</b><span class="chip">${c.author_role}</span>${c.issue_id ? `<span class="chip">issue #${c.issue_id}</span>` : ''}<span class="muted right">${fmt(c.created_at)}</span></div>
    <div>${esc(c.body)}</div><a href="#" class="small" data-reply="${c.id}">Reply</a></div>` + (by[c.id] || []).map(r => one(r, true)).join('');
  return (by[0] || []).map(c => one(c)).join('') || '<div class="empty small">No comments yet.</div>';
}
function stepper(s) {
  const idx = s.status === 'approved' ? 3 : s.status === 'in_review' ? (s.stage === 'legal' ? 2 : 1) : 0;
  return `<ul class="steps">${STAGES.map((st, i) => `<li class="${i < idx || (s.status === 'approved') ? 'done' : i === idx ? 'now' : ''}">${st[1]}</li>`).join('')}</ul>`;
}
async function detail(id) {
  const d = await api('/submissions/' + id), s = d.submission, me = S.user;
  const editable = (me.role !== 'creator' || ['draft', 'analyzed', 'changes_requested', 'rejected'].includes(s.status));
  const isImg = !!s.image_url, open = d.issues.filter(i => i.status === 'open');
  const canReview = s.status === 'in_review' && me.role === s.stage;
  const tm = d.text_metrics, im = d.image_metrics;
  const categories = [...new Set(d.issues.map(i => i.category).filter(Boolean))].sort();
  const filterBar = `
    <div class="card filter-bar">
      <span class="filter-heading">Filter:</span>
      <select id="if-sev" class="filter-select" aria-label="Filter by severity">
        <option value="all">All severities</option>
        <option value="critical">Critical</option>
        <option value="high">High</option>
        <option value="medium">Medium</option>
        <option value="minor">Minor</option>
      </select>
      <select id="if-cat" class="filter-select" aria-label="Filter by category">
        <option value="all">All categories</option>
        ${categories.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('')}
      </select>
      <select id="if-st" class="filter-select" aria-label="Filter by status">
        <option value="all">All statuses</option>
        <option value="open">Open</option>
        <option value="fixed">Fixed</option>
        <option value="dismissed">Dismissed</option>
      </select>
      <label class="filter-label">
        <input type="checkbox" id="if-open" class="select-auto"> Show only open
      </label>
      <span class="right muted small filter-count" id="if-count"></span>
    </div>`;

  const analysis = `<div class="grid g23"><div>
      ${isImg ? `<div class="canvaswrap"><canvas id="cv"></canvas></div><div class="small muted mt">Boxes mark detected regions (colour, contrast, logo). Alt text: <i>${esc(s.alt_text || 'none')}</i></div>` : ''}
      ${(s.content_text || '').trim() ? `<h3 class="${isImg ? 'mt ' : ''}mb-8">${isImg ? 'Copy attached to the image' : 'Annotated content'}</h3><div class="doc" id="doc">${annotate(s.content_text, d.issues, s.page_map)}</div>` : ''}
      ${editable && (s.content_text || '').trim() ? `<div class="row mt"><button class="btn ghost sm" id="edit">Edit text</button><button class="btn ghost sm" id="rw">Preview AI-assisted rewrite</button><button class="btn ghost sm" id="re">Re-run checks</button></div>` : ''}
      ${tm ? `<div class="small muted mt">${tm.words} words · ${tm.sentences} sentences · avg ${tm.avg_sentence_words} words/sentence</div>` : ''}
      ${im ? `<h3 class="mt">Visual analysis</h3><div class="small muted">${im.width}×${im.height}px · ${im.text_regions_checked} text regions contrast-checked${im.contrast_ratios.length ? ' (' + im.contrast_ratios.join(', ') + ':1)' : ''}</div>
        <div class="mt">${im.dominant_colors.map(c => `<div class="row small my-3"><svg class="swatch-svg" width="16" height="16"><rect width="16" height="16" rx="4" fill="${c.hex}"/></svg>${c.hex} <span class="muted">${c.pct}%</span>
          <span class="chip">${c.neutral ? 'neutral' : c.ok ? 'on-brand' : 'off-palette (ΔE ' + c.delta_e + ')'}</span></div>`).join('')}</div>` : ''}
      ${(d.verified_claims || []).length ? `<h3 class="mt">✔ Verified claims</h3>${d.verified_claims.map(v => `<div class="cite"><b>“${esc(v.sentence)}”</b><br><span class="muted">Supported by ${esc(v.evidence.doc_title)} — ${esc(v.evidence.heading || '')}</span><q>${esc(v.evidence.text.slice(0, 220))}</q></div>`).join('')}` : ''}
    </div><div>
      <div class="row mb-10"><h2>Issues (${open.length} open)</h2><span class="muted small right">${d.issues.length - open.length} fixed/dismissed</span></div>
      ${d.issues.length ? filterBar : ''}
      <div id="issue-list-container">
        ${d.issues.length ? d.issues.map(i => issueCard(i, editable)).join('') : '<div class="card empty">✅ No issues found. This content looks on-brand.</div>'}
      </div>
    </div></div>`;
  const review = `<div class="grid g2"><div><h2>Discussion</h2><div class="mt" id="cl">${commentsHtml(d)}</div>
      <label>Add a comment</label><textarea id="cb" rows="3" placeholder="Context, question or escalation note…"></textarea><div class="row mt"><button class="btn sm" id="cs">Post comment</button><span class="small muted" id="cref"></span></div></div>
    <div><h2>Sign-off trail</h2><div class="mt">${d.approvals.map(a => `<div class="comment"><div class="row small"><b>${esc(a.reviewer)}</b><span class="chip">${a.stage}</span>${pill(a.decision === 'approve' ? 'approved' : a.decision === 'changes' ? 'changes_requested' : 'rejected')}<span class="muted right">${fmt(a.created_at)}</span></div>${esc(a.note || '')}</div>`).join('') || '<div class="empty small">No decisions yet.</div>'}</div>
      ${s.badge ? `<h3 class="mt">🛡 Compliance badge</h3><div class="badge">${esc(s.badge)}</div><div class="row mt"><a class="btn sm ghost" href="#/verify?token=${encodeURIComponent(s.badge)}">Verify</a></div>` : ''}</div></div>`;
  const history = `<div class="row"><h2>Revision history</h2><span class="right row"><select id="df" class="select-auto">${d.revisions.map(r => `<option value="${r.version}">v${r.version}</option>`).join('')}</select><span>→</span>
      <select id="dt" class="select-auto">${d.revisions.map(r => `<option value="${r.version}">v${r.version}</option>`).join('')}</select><button class="btn sm" id="dgo">Compare</button></span></div>
    <div class="mt">${d.revisions.map(r => `<div class="row small py-6 border-b"><b>v${r.version}</b> ${esc(r.note || '')}<span class="muted right">${esc(r.author || '')} · ${fmt(r.created_at)}</span></div>`).join('')}</div>
    <div class="diff doc mt" id="dout" hidden></div>`;
  const audit = d.audit.map(a => `<div class="row small py-6 border-b"><b>${esc(a.action)}</b><span>${esc(a.detail || '')}</span><span class="muted right">${esc(a.actor_name)} · ${fmt(a.ts)}</span></div>`).join('');
  const pages = s.pdf_pages && s.pdf_pages.length
    ? `<div class="grid g2">${s.pdf_pages.map((url, idx) => `<div class="card card-center"><div class="small muted mb-6">Page ${idx + 1}</div><img src="${url}" class="pdf-page-img" alt="Page ${idx + 1}"></div>`).join('')}</div>`
    : `<div class="card empty"><p>PDF page image preview is unavailable (requires optional <code>pypdfium2</code> library).</p><p class="small muted">Text extracted from the PDF and page-level issue mapping are available in the <b>Analysis</b> tab.</p></div>`;
  const tabList = [['analysis', 'Analysis']];
  if (s.kind === 'pdf') tabList.push(['pages', 'Page preview']);
  tabList.push(['review', `Review & comments (${d.comments.length})`], ['history', 'History & diff'], ['audit', 'Audit trail']);
  return {
    html: `<div class="head"><div><div class="small"><a href="#/submissions">← All content</a></div><h1>${esc(s.title)}</h1><p>${s.kind} · by ${esc(s.creator_name)} (${esc(s.team || '')}) · v${s.current_version} ${pill(s.status)} ${s.requires_legal ? '<span class="chip">legal review required</span>' : ''}</p></div>
      <div class="row">${ring(s.score)}<div class="small muted">Compliance<br>score</div></div></div>
    <div class="card mb-14">${stepper(s)}
      <div class="row mt">${me.role === 'creator' && editable ? `<button class="btn" id="sub" ${open.some(i => i.severity === 'critical') ? 'disabled title="Resolve critical issues first"' : ''}>Submit for review</button>` : ''}
      ${canReview ? `<label class="m-0">Decision note</label><input type="text" id="rn" class="decision-input" placeholder="Required when requesting changes">
        <button class="btn" id="ap">Approve${s.stage === 'manager' && s.requires_legal ? ' → send to Legal' : ''}</button><button class="btn ghost" id="ch">Request changes</button><button class="btn danger" id="rj">Reject</button>` : ''}
      ${s.status === 'in_review' && !canReview ? `<span class="muted small">Waiting for a <b>${s.stage}</b> reviewer.</span>` : ''}
      ${s.status === 'approved' ? '<span class="small text-green"><b>✔ Approved & published</b> — cryptographic badge issued (see Review tab).</span>' : ''}</div></div>
    <div class="tabs">${tabList.map(t => `<button data-tab="${t[0]}" class="${TAB === t[0] ? 'on' : ''}">${t[1]}</button>`).join('')}</div>
    <div>${{ analysis, pages, review, history, audit }[TAB]}</div>`,
    bind: r => bindDetail(r, d, id)
  };
}
function bindDetail(r, d, id) {
  const s = d.submission, reload = () => route();
  $$('[data-tab]', r).forEach(b => b.onclick = () => { TAB = b.dataset.tab; reload(); });
  if (s.image_url && TAB === 'analysis') drawImage(d);
  const focus = iid => { SEL = iid; $$('.sel', r).forEach(e => e.classList.remove('sel')); $('#is' + iid, r)?.classList.add('sel'); $(`mark[data-i="${iid}"]`, r)?.classList.add('sel'); $('#is' + iid, r)?.scrollIntoView({ block: 'center', behavior: 'smooth' }); };
  $$('mark[data-i],.endmark', r).forEach(m => m.onclick = () => focus(+m.dataset.i));
  const post = (p, body, ok) => act(() => api(`/submissions/${id}/${p}`, { json: body || {} }), ok).then(x => x && reload());

  const bindCards = root => {
    $$('.issue', root).forEach(c => {
      c.onclick = e => { if (!e.target.closest('button')) focus(+c.dataset.i); };
      c.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); focus(+c.dataset.i); } };
    });
    $$('[data-apply]', root).forEach(b => b.onclick = () => post(`issues/${b.dataset.apply}/apply`, {}, 'Fix applied · new revision saved'));
    $$('[data-dismiss]', root).forEach(b => b.onclick = () => { const reason = prompt('Why is this flag not applicable? (helps improve the guidelines)', ''); if (reason !== null) post(`issues/${b.dataset.dismiss}/dismiss`, { reason }, 'Dismissed'); });
    $$('[data-reopen]', root).forEach(b => b.onclick = () => post(`issues/${b.dataset.reopen}/reopen`, {}, 'Reopened'));
    $$('[data-discuss]', root).forEach(b => b.onclick = () => { TAB = 'review'; SEL = +b.dataset.discuss; window._ref = SEL; reload(); });
  };

  const applyFilter = () => {
    const sevVal = $('#if-sev', r)?.value || 'all';
    const catVal = $('#if-cat', r)?.value || 'all';
    const stVal = $('#if-st', r)?.value || 'all';
    const onlyOpen = $('#if-open', r)?.checked;

    const filtered = d.issues.filter(i => {
      if (sevVal !== 'all' && i.severity !== sevVal) return false;
      if (catVal !== 'all' && i.category !== catVal) return false;
      if (stVal !== 'all' && i.status !== stVal) return false;
      if (onlyOpen && i.status !== 'open') return false;
      return true;
    });

    const cnt = $('#if-count', r);
    if (cnt) cnt.textContent = `Showing ${filtered.length} of ${d.issues.length}`;

    const listEl = $('#issue-list-container', r);
    if (listEl) {
      listEl.innerHTML = filtered.length
        ? filtered.map(i => issueCard(i, editable)).join('')
        : '<div class="card empty small">No issues match the current filter.</div>';
      bindCards(listEl);
    }
  };

  ['#if-sev', '#if-cat', '#if-st'].forEach(sel => {
    const el = $(sel, r);
    if (el) el.onchange = applyFilter;
  });
  const openChk = $('#if-open', r);
  if (openChk) openChk.onchange = applyFilter;

  bindCards(r);
  applyFilter();

  $('#re', r) && ($('#re', r).onclick = () => post('analyze', {}, 'Re-analysed'));
  $('#sub', r) && ($('#sub', r).onclick = () => post('submit-review', {}, 'Submitted for review'));
  const decide = (decision) => post('review', { decision, note: $('#rn').value }, decision === 'approve' ? 'Approved' : 'Decision recorded');
  $('#ap', r) && ($('#ap', r).onclick = () => decide('approve')); $('#ch', r) && ($('#ch', r).onclick = () => decide('changes')); $('#rj', r) && ($('#rj', r).onclick = () => decide('reject'));
  $('#edit', r) && ($('#edit', r).onclick = () => {
    $('#doc').outerHTML = `<textarea id="ta" rows="12">${esc(s.content_text)}</textarea>`; $('#edit').textContent = 'Save & re-check';
    $('#edit').onclick = () => act(() => api(`/submissions/${id}/content`, { method: 'PUT', json: { text: $('#ta').value, note: 'Manual edit' } }), 'Saved · re-analysed').then(x => x && reload());
  });
  $('#rw', r) && ($('#rw', r).onclick = async () => {
    const rw = await act(() => api(`/submissions/${id}/rewrite`)); if (!rw) return;
    modal(`<h2>Suggested rewrite</h2><p class="disclose">${esc(rw.ai_disclosure)} Intent-preserving: only the flagged problems are changed. Unsupported claims you still need to substantiate are left for you.</p>
      <div class="grid g2"><div><h3>Current</h3><div class="doc">${esc(rw.original)}</div></div><div><h3>Suggested</h3><div class="doc">${esc(rw.rewrite)}</div></div></div>
      <div class="row mt"><button class="btn" id="aa">Apply as new revision</button><button class="btn ghost" id="cl2">Cancel</button></div>`, m => {
      $('#cl2', m).onclick = closeModal; $('#aa', m).onclick = () => { closeModal(); post('apply-all', {}, 'Rewrite applied'); };
    });
  });
  if (TAB === 'review') {
    let ref = window._ref || null, parent = null; const cref = $('#cref', r); if (ref) cref.textContent = `Commenting on issue #${ref}`;
    $$('[data-reply]', r).forEach(a => a.onclick = e => { e.preventDefault(); parent = +a.dataset.reply; cref.textContent = 'Replying in thread'; $('#cb').focus(); });
    $('#cs', r).onclick = async () => { const x = await act(() => api(`/submissions/${id}/comments`, { json: { body: $('#cb').value, issue_id: ref, parent_id: parent } }), 'Comment posted'); window._ref = null; if (x) reload(); };
  }
  if (TAB === 'history') $('#dgo', r).onclick = async () => {
    const x = await act(() => api(`/submissions/${id}/diff?from=${$('#df').value}&to=${$('#dt').value}`)); if (!x) return;
    const o = $('#dout'); o.hidden = false;
    o.innerHTML = x.ops.map(p => p.op === 'equal' ? esc(p.a) : (p.a ? `<del>${esc(p.a)}</del>` : '') + (p.b ? `<ins>${esc(p.b)}</ins>` : '')).join('') || 'No differences';
  };
}

/* ---------- knowledge base ---------- */
async function kb() {
  const [docs, settings, logos] = await Promise.all([
    api('/kb/documents'),
    api('/settings'),
    api('/kb/logos').catch(() => [])
  ]);
  const mgr = S.user && S.user.role === 'manager';
  return {
    html: `<div class="head"><div><h1>Knowledge base</h1><p>Stage 1 · Guidelines, product facts and glossaries are chunked and indexed. Claims are verified against this corpus.</p></div></div>
    <div class="grid g2"><div class="card"><h2>Indexed documents</h2><div class="table-wrap"><table class="mt"><tr><th>Document</th><th>Type</th><th>Chunks</th><th></th></tr>
      ${docs.map(d => `<tr><td><b>${esc(d.title)}</b><div class="small muted">${fmt(d.created_at)}</div></td><td><span class="chip">${esc(d.doc_type)}</span></td><td>${d.chunks}</td>
      <td>${mgr ? `<button class="btn sm ghost" data-del="${d.id}">Delete</button>` : ''}</td></tr>`).join('')}</table></div>
      <h3 class="mt">Brand palette</h3>
      ${mgr ? `
      <div id="pal-list" class="mt">
        ${settings.palette.map(p => `
          <div class="pal-item row">
            <input type="color" class="pal-color" value="${p.hex}">
            <input type="text" class="pal-name" value="${esc(p.name)}" placeholder="Colour name">
            <span class="pal-hex small muted">${p.hex}</span>
            <button type="button" class="btn sm ghost danger del-color" title="Remove colour">✕</button>
          </div>
        `).join('')}
      </div>
      <div class="row mt">
        <button type="button" class="btn sm ghost" id="add-color">+ Add colour</button>
        <button type="button" class="btn sm" id="save-palette">Save palette</button>
      </div>
      ` : `
      <div class="mt">${settings.palette.map(p => `<span class="row small pal-swatch-item"><svg class="swatch-svg" width="16" height="16"><rect width="16" height="16" rx="4" fill="${p.hex}"/></svg>${esc(p.name)} ${p.hex}</span>`).join('')}</div>
      `}
      <h3 class="mt">Brand logos</h3>
      <div class="mt logo-list">
        ${logos.length ? logos.map(l => `
          <div class="logo-item">
            <img src="${l.url}" class="logo-thumb" alt="${esc(l.name)}">
            <div class="small logo-name" title="${esc(l.name)}">${esc(l.name)}</div>
            ${mgr ? `<button type="button" class="btn sm ghost danger mt del-logo-btn" data-del-logo="${esc(l.name)}">Delete</button>` : ''}
          </div>
        `).join('') : '<div class="small muted">No logos uploaded yet.</div>'}
      </div>
      ${mgr ? `
      <form id="logof" class="row mt logo-form">
        <input type="file" id="logofile" accept=".png,.jpg,.jpeg" required class="logo-file-input">
        <button class="btn sm">Upload logo</button>
      </form>
      ` : ''}
    </div>
    <div class="grid"><div class="card"><h2>Retrieval tester</h2><p class="muted small">See exactly which passages the RAG engine retrieves for a claim.</p><div class="row"><input type="text" id="q" placeholder="e.g. keeps drinks cold for 36 hours" class="input-flex"><button class="btn" id="qs">Search</button></div><div id="qr" class="mt"></div></div>
    ${mgr ? `<div class="card"><h2>Ingest a document</h2><form id="uf"><label>Title</label><input type="text" id="ut"><label>Type</label><select id="uty"><option value="guideline">Brand guideline</option><option value="product_facts">Product facts</option><option value="glossary">Terminology glossary</option><option value="legal">Legal / disclaimers</option></select>
      <label>File (.pdf .md .txt) or paste text</label><input type="file" id="uf1" accept=".pdf,.md,.txt"><textarea id="utx" rows="4" class="mt-8" placeholder="Or paste text…"></textarea><button class="btn mt">Ingest</button></form></div>` : ''}</div></div>`,
    bind: r => {
      $('#qs', r).onclick = async () => { const q = $('#q').value; if (!q) return; const h = await act(() => api('/kb/search?q=' + encodeURIComponent(q))); if (h) $('#qr').innerHTML = h.map(x => `<div class="cite"><b>${esc(x.doc_title)}</b> · ${esc(x.heading || '')} <span class="chip">score ${x.score}</span><q>${esc(x.text.slice(0, 260))}</q></div>`).join('') || '<div class="empty small">No relevant passage found.</div>'; };
      $$('[data-del]', r).forEach(b => b.onclick = async () => { if (confirm('Delete this document and its index entries?')) { await act(() => api('/kb/documents/' + b.dataset.del, { method: 'DELETE' }), 'Deleted'); route(); } });
      $('#uf', r) && ($('#uf', r).onsubmit = async e => {
        e.preventDefault(); const fd = new FormData(); fd.append('title', $('#ut').value); fd.append('doc_type', $('#uty').value); fd.append('text', $('#utx').value); if ($('#uf1').files[0]) fd.append('file', $('#uf1').files[0]);
        const x = await act(() => api('/kb/documents', { form: fd })); if (x) { toast(`Indexed ${x.chunks} chunks`); route(); }
      });
      $$('.pal-color', r).forEach(inp => inp.oninput = e => {
        const row = e.target.closest('.pal-item');
        if (row) $('.pal-hex', row).textContent = e.target.value.toUpperCase();
      });
      $$('.del-color', r).forEach(btn => btn.onclick = () => btn.closest('.pal-item')?.remove());
      $('#add-color', r) && ($('#add-color', r).onclick = () => {
        const list = $('#pal-list', r);
        const row = document.createElement('div');
        row.className = 'pal-item row';
        row.innerHTML = `<input type="color" class="pal-color" value="#2e7d32">
          <input type="text" class="pal-name" value="New colour" placeholder="Colour name">
          <span class="pal-hex small muted">#2E7D32</span>
          <button type="button" class="btn sm ghost danger del-color" title="Remove colour">✕</button>`;
        $('.pal-color', row).oninput = e => $('.pal-hex', row).textContent = e.target.value.toUpperCase();
        $('.del-color', row).onclick = () => row.remove();
        list.appendChild(row);
      });
      $('#save-palette', r) && ($('#save-palette', r).onclick = async () => {
        const rows = $$('.pal-item', r);
        const palette = rows.map(row => ({
          name: $('.pal-name', row).value.trim() || 'Untitled',
          hex: $('.pal-color', row).value.toUpperCase()
        }));
        const res = await act(() => api('/settings', { method: 'PUT', json: { palette } }), 'Palette saved');
        if (res) route();
      });
      $('#logof', r) && ($('#logof', r).onsubmit = async e => {
        e.preventDefault();
        const fileInput = $('#logofile', r);
        if (!fileInput.files[0]) return;
        const fd = new FormData();
        fd.append('file', fileInput.files[0]);
        const res = await act(() => api('/kb/logos', { form: fd }), 'Logo uploaded');
        if (res) route();
      });
      $$('[data-del-logo]', r).forEach(b => b.onclick = async () => {
        if (confirm(`Delete logo ${b.dataset.delLogo}?`)) {
          const res = await act(() => api('/kb/logos/' + encodeURIComponent(b.dataset.delLogo), { method: 'DELETE' }), 'Logo deleted');
          if (res) route();
        }
      });
    }
  };
}

/* ---------- rules ---------- */
async function rules() {
  const rs = await api('/rules'), mgr = S.user.role === 'manager';
  return {
    html: `<div class="head"><div><h1>Brand rules</h1><p>Machine-readable rules behind every flag. Each links back to its guideline source.</p></div>${mgr ? '<button class="btn" id="add">Add rule</button>' : ''}</div>
    <div class="card"><div class="table-wrap"><table><tr><th>Rule</th><th>Category</th><th>Kind</th><th>Severity</th><th>Pattern → preferred</th><th>Active</th></tr>${rs.map(r => `<tr><td><b>${esc(r.name)}</b><div class="small muted">${esc(r.source)}</div></td>
      <td><span class="chip">${r.category}</span></td><td>${r.kind}</td><td>${sev(r.severity)}</td><td class="small"><code>${esc(r.pattern.slice(0, 60))}</code>${r.preferred ? ' → <b>' + esc(r.preferred) + '</b>' : ''}</td>
      <td><input type="checkbox" data-tg="${r.id}" ${r.active ? 'checked' : ''} ${mgr ? '' : 'disabled'} aria-label="Toggle rule"></td></tr>`).join('')}</table></div></div>`,
    bind: r => {
      $$('[data-tg]', r).forEach(c => c.onchange = () => act(() => api('/rules/' + c.dataset.tg, { method: 'PUT', json: { active: c.checked ? 1 : 0 } }), 'Rule updated'));
      $('#add', r) && ($('#add', r).onclick = () => modal(`<h2>Add rule</h2><form id="rf"><div class="grid g2"><div><label>Key</label><input type="text" id="k" required placeholder="term-synergy"></div><div><label>Name</label><input type="text" id="n" required></div>
        <div><label>Kind</label><select id="kd"><option>term</option><option>claim</option><option>disclaimer</option><option>exclaim</option><option>caps</option></select></div><div><label>Category</label><input type="text" id="c" value="terminology"></div>
        <div><label>Pattern (regex)</label><input type="text" id="p" required></div><div><label>Preferred replacement</label><input type="text" id="pf"></div>
        <div><label>Severity</label><select id="sv"><option>minor</option><option selected>medium</option><option>high</option><option>critical</option></select></div><div><label>Guideline source</label><input type="text" id="so"></div></div>
        <label>Description (used for retrieval/citation)</label><input type="text" id="ds"><div class="row mt"><button class="btn">Save</button><button type="button" class="btn ghost" id="x">Cancel</button></div></form>`, m => {
        $('#x', m).onclick = closeModal;
        $('#rf', m).onsubmit = async e => { e.preventDefault(); const ok = await act(() => api('/rules', { json: { key: $('#k').value, name: $('#n').value, kind: $('#kd').value, category: $('#c').value, pattern: $('#p').value, preferred: $('#pf').value, severity: $('#sv').value, source: $('#so').value, description: $('#ds').value } }), 'Rule added'); if (ok) { closeModal(); route(); } };
      }));
    }
  };
}

/* ---------- audit & verify ---------- */
async function auditLog() {
  const a = await api('/audit');
  return { html: `<div class="head"><div><h1>Audit log</h1><p>Immutable record of every analysis, edit, decision and rule change.</p></div></div><div class="card"><div class="table-wrap"><table><tr><th>When</th><th>Actor</th><th>Action</th><th>Detail</th></tr>
    ${a.map(x => `<tr><td class="small muted">${fmt(x.ts)}</td><td>${esc(x.actor_name)}</td><td><b>${esc(x.action)}</b></td><td class="small">${esc(x.detail || '')}</td></tr>`).join('')}</table></div></div>` };
}
function verify() {
  const tok = new URLSearchParams((location.hash.split('?')[1] || '')).get('token') || '';
  return {
    html: `<div class="head"><div><h1>Verify compliance badge</h1><p>Paste a badge token to confirm it was issued by this platform and that the content has not changed since approval.</p></div></div>
    <div class="card"><textarea id="tk" rows="3" placeholder="BG1.…">${esc(tok)}</textarea><div class="row mt"><button class="btn" id="vg">Verify</button></div><div id="vr" class="mt"></div></div>`,
    bind: r => {
      const go = async () => {
        const x = await fetch('/api/verify?token=' + encodeURIComponent($('#tk').value)).then(r => r.json());
        $('#vr').innerHTML = x.valid ? `<div class="issue badge-valid"><b class="text-green">✔ Valid badge</b><div class="small">${x.title ? 'Asset: <b>' + esc(x.title) + '</b><br>' : ''}Score at approval: ${x.payload.sc} · Approved ${esc(x.payload.at)} UTC by ${esc((x.payload.by || []).join(', '))}<br>Content unchanged since approval: ${x.content_unchanged === false ? 'NO' : 'yes'}</div></div>`
          : `<div class="issue critical"><b>✖ Not valid</b><div class="small">${esc(x.reason || '')}</div></div>`;
      };
      $('#vg', r).onclick = go; if (tok) go();
    }
  };
}

/* ---------- router ---------- */
async function route() {
  const [path] = (location.hash || '#/dashboard').slice(2).split('?'), [name, arg] = path.split('/');
  if (!S.token) { if (name !== 'login') { location.hash = '#/login'; return; } return loginView(); }
  if (!S.user) { try { S.user = await api('/auth/me'); } catch { return logout(); } }
  if (name === 'login') { location.hash = '#/dashboard'; return; }
  if (!window._notifTimer && S.token) {
    fetchNotifications();
    window._notifTimer = setInterval(fetchNotifications, 30000);
  }
  if (isReviewer()) api('/submissions?queue=1').then(q => { if (q.length !== S.queue) { S.queue = q.length; const c = $('.side a[href="#/queue"]'); if (c) c.innerHTML = `Review queue${q.length ? `<span class="count">${q.length}</span>` : ''}`; } }).catch(() => { });
  switch (name) {
    case 'dashboard': return render('dashboard', dashboard);
    case 'submissions': return render('submissions', () => submissions(false));
    case 'queue': return render('queue', () => submissions(true));
    case 'new': return render('new', async () => newCheck());
    case 's': return render('submissions', () => detail(arg));
    case 'kb': return render('kb', kb);
    case 'rules': return render('rules', rules);
    case 'audit': return render('audit', auditLog);
    case 'verify': return render('verify', async () => verify());
    default: location.hash = '#/dashboard';
  }
}
window.addEventListener('hashchange', () => { if (!location.hash.startsWith('#/s/')) { TAB = 'analysis'; SEL = null; } route(); });
route();
