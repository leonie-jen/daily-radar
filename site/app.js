/* 每日雷達 — 前端只做三件事：讀 JSON、排序、畫出來。
   所有判斷（相關性、是否降價）都在爬蟲階段算好了。 */

const REPO = 'https://github.com/leonie-jen/daily-radar';   // 換成你的 repo 網址
const FILES = ['status', 'omscs', 'cpt', 'jobs', 'finance', 'prices', 'leetcode'];
const DB = {};

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// ---------------------------------------------------------------- 工具

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function ago(iso) {
  if (!iso) return '';
  const mins = (Date.now() - new Date(iso)) / 6e4;
  if (mins < 60) return `${Math.max(1, Math.round(mins))} 分鐘前`;
  if (mins < 1440) return `${Math.round(mins / 60)} 小時前`;
  const d = Math.round(mins / 1440);
  return d <= 30 ? `${d} 天前` : new Date(iso).toLocaleDateString('zh-TW');
}

const isNew = it => it.first_seen && (Date.now() - new Date(it.first_seen)) < 30 * 3600e3;
const num = n => (n ?? null) === null ? '—' : Number(n).toLocaleString('zh-TW');

// 相關性未評分（沒開 AI）時一律顯示；有評分才拿來排序與過濾
const scoreOf = it => it.relevance ?? 55;

function sortItems(items) {
  return [...items].sort((a, b) => {
    const flag = x => (x.admission_signal || x.policy_signal) ? 1 : 0;
    return (isNew(b) - isNew(a))
        || (flag(b) - flag(a))
        || (scoreOf(b) - scoreOf(a))
        || String(b.first_seen || '').localeCompare(String(a.first_seen || ''));
  });
}

// ---------------------------------------------------------------- 條目

function itemCard(it) {
  const badges = [];
  if (isNew(it)) badges.push('<span class="badge new">NEW</span>');
  if (it.admission_signal) badges.push('<span class="badge hot">錄取情報</span>');
  if (it.policy_signal) badges.push('<span class="badge hot">政策異動</span>');
  if (it.paywalled) badges.push('<span class="badge lock">🔒 會員限定</span>');
  if (it.kind === 'job') badges.push('<span class="badge tag">職缺</span>');
  (it.tags || []).slice(0, 3).forEach(t => badges.push(`<span class="badge tag">${esc(t)}</span>`));

  const jobLine = it.company
    ? `<div class="meta">${esc(it.company)}${it.location ? ' · ' + esc(it.location) : ''}${it.salary ? ' · ' + esc(it.salary) : ''}</div>`
    : '';

  const body = it.summary
    ? `<p>${esc(it.summary)}</p>`
    : (it.excerpt ? `<p>${esc(it.excerpt.slice(0, 150))}…</p>` : '');

  return `<a class="item" href="${esc(it.url)}" target="_blank" rel="noopener">
    <h3>${esc(it.title)}</h3>
    ${jobLine}${body}
    <div class="meta" style="margin-top:8px">
      <span class="badge">${esc(it.source || '')}</span>${badges.join('')}
      <span>${ago(it.first_seen)}</span>
    </div>
  </a>`;
}

function renderList(el, items, empty = '今天沒有新內容') {
  el.innerHTML = items.length
    ? sortItems(items).map(itemCard).join('')
    : `<div class="empty">${empty}</div>`;
}

// ---------------------------------------------------------------- 迷你走勢圖

function sparkline(points, { up = 'var(--up)', down = 'var(--down)' } = {}) {
  if (!points || points.length < 2) return '';
  const vs = points.map(p => p.v);
  const lo = Math.min(...vs), hi = Math.max(...vs), span = (hi - lo) || 1;
  const W = 260, H = 42;
  const d = points.map((p, i) =>
    `${(i / (points.length - 1)) * W},${H - ((p.v - lo) / span) * (H - 6) - 3}`).join(' ');
  const rising = vs.at(-1) >= vs[0];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <polyline points="${d}" fill="none" stroke="${rising ? up : down}" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

const dirClass = n => n == null ? 'flat' : (n > 0 ? 'up' : n < 0 ? 'down' : 'flat');
const signed = n => n == null ? '—' : (n > 0 ? '+' : '') + Number(n).toLocaleString('zh-TW');

// ---------------------------------------------------------------- 各版面

function renderHome() {
  const cards = [];
  const fx = DB.finance?.fx;

  if (fx?.usd_twd) {
    const d7 = fx.change_7d;
    cards.push(`<div class="card">
      <div class="k">美金 / 台幣 ${fx.good_time_to_buy ? '· 💰 到你設的價位了' : ''}</div>
      <div class="v">${fx.usd_twd.toFixed(3)}</div>
      <div class="sub ${dirClass(d7 == null ? null : -d7)}">
        ${d7 == null ? '走勢累積中（每天記一筆）' : `7 天 ${signed(d7)}`} · ${esc(fx.note || '')}</div>
      ${sparkline(fx.history)}
    </div>`);
  }

  const twii = (DB.finance?.quotes || []).find(q => q.symbol === '^TWII');
  if (twii) cards.push(`<div class="card">
    <div class="k">台股加權指數 · ${esc(twii.as_of || '')}</div>
    <div class="v ${dirClass(twii.change)}">${num(twii.price)}</div>
    <div class="sub ${dirClass(twii.change)}">${signed(twii.change)} (${signed(twii.change_pct)}%)</div>
  </div>`);

  const deals = (DB.prices?.items || []).filter(p => p.hit_target || p.is_lowest_ever);
  cards.push(`<div class="card">
    <div class="k">商品降價</div>
    <div class="v ${deals.length ? 'deal' : ''}">${deals.length}</div>
    <div class="sub">${deals.length ? deals.map(d => esc(d.title)).join('、') + ' 到價了' : '追蹤中，目前都沒到你設的價'}</div>
  </div>`);

  const goal = DB.status?.leetcode_goal || 10;
  const week = weekCount();
  cards.push(`<div class="card">
    <div class="k">本週刷題 · 目標 ${goal} 題</div>
    <div class="v">${week}</div>
    <div class="bar"><i style="width:${Math.min(100, week / goal * 100)}%"></i></div>
    <div class="sub">${week >= goal ? '達標了 🎉' : `還差 ${goal - week} 題`}</div>
  </div>`);

  $('#home-cards').innerHTML = cards.join('');

  const fresh = ['omscs', 'cpt', 'jobs', 'finance']
    .flatMap(k => (DB[k]?.items || []).filter(isNew))
    .filter(it => scoreOf(it) >= 45);
  renderList($('#home-new'), fresh.slice(0, 25), '今天各處都沒有新東西，休息一下 ☕');
}

function renderFinance() {
  const fx = DB.finance?.fx;
  $('#fx-card').innerHTML = fx?.usd_twd ? `<div class="card">
    <div class="k">美金 / 台幣（${esc(fx.source || '')}）</div>
    <div class="v">${fx.usd_twd.toFixed(3)}</div>
    <div class="sub">7 天 ${signed(fx.change_7d)} · 30 天 ${signed(fx.change_30d)}
      ${fx.alert_below ? ` · 你的提醒價 ${fx.alert_below}` : ''}</div>
    <div class="sub">${esc(fx.note || '')}</div>
    ${sparkline(fx.history)}
  </div>` : '<div class="empty">匯率抓取失敗</div>';

  $('#quotes').innerHTML = (DB.finance?.quotes || []).map(q => `<div class="quote">
    <div class="n">${esc(q.name || q.symbol)}</div>
    <div class="p ${dirClass(q.change)}">${num(q.price)}</div>
    <div class="c ${dirClass(q.change)}">${signed(q.change_pct)}%</div>
    <div class="n" style="margin-top:4px">${esc(q.as_of || '')}</div>
  </div>`).join('') || '<div class="empty">報價抓取失敗</div>';

  renderList($('#finance-list'), DB.finance?.items || []);
}

function renderPrices() {
  const items = DB.prices?.items || [];
  $('#prices-list').innerHTML = items.length ? items.map(p => {
    const cur = p.currency === 'TWD' ? 'NT$' : (p.currency === 'JPY' ? '¥' : '$');
    const tags = [];
    if (p.hit_target) tags.push('<span class="badge hot">到你的目標價</span>');
    if (p.is_lowest_ever && p.history?.length > 2) tags.push('<span class="badge hot">歷史新低</span>');
    if (!p.ok) tags.push('<span class="badge">抓取失敗</span>');
    return `<a class="item ${p.ok ? '' : 'stale'}" href="${esc(p.url)}" target="_blank" rel="noopener">
      <h3>${esc(p.title)}</h3>
      <div class="price-row">
        <span class="price-now ${p.hit_target ? 'deal' : ''}">${p.ok ? cur + num(p.price) : '—'}</span>
        <span class="meta ${dirClass(p.change)}">${p.change ? signed(p.change) : ''}</span>
      </div>
      <div class="meta" style="margin-top:6px">
        ${p.target_price ? `目標 ${cur}${num(p.target_price)}` : '未設目標價'}
        ${p.lowest ? ` · 追蹤期最低 ${cur}${num(p.lowest)}` : ''}
        <span class="badge">${esc(p.source)}</span>${tags.join('')}
      </div>
      ${sparkline(p.history, { up: 'var(--up)', down: 'var(--down)' })}
    </a>`;
  }).join('') : '<div class="empty">還沒設定要追蹤的商品，改 config.yml 的 prices.watch</div>';
}

function weekCount() {
  const start = new Date(); start.setDate(start.getDate() - start.getDay());
  start.setHours(0, 0, 0, 0);
  return (DB.leetcode?.entries || [])
    .filter(e => new Date(e.date) >= start)
    .reduce((n, e) => n + (e.problems?.length || 1), 0);
}

function renderLeetcode() {
  const entries = DB.leetcode?.entries || [];
  const goal = DB.status?.leetcode_goal || 10;
  const week = weekCount();
  const total = entries.reduce((n, e) => n + (e.problems?.length || 1), 0);

  $('#leetcode-panel').innerHTML = `
    <div class="grid">
      <div class="card"><div class="k">本週 · 目標 ${goal}</div><div class="v">${week}</div>
        <div class="bar"><i style="width:${Math.min(100, week / goal * 100)}%"></i></div></div>
      <div class="card"><div class="k">累計題數</div><div class="v">${total}</div>
        <div class="sub">共 ${entries.length} 天有紀錄</div></div>
    </div>
    <a class="btn" href="${REPO}/issues/new?template=leetcode.yml" target="_blank" rel="noopener">＋ 記錄今天刷的題</a>
    <h2 class="sec-h">紀錄</h2>
    ${entries.length ? entries.slice(0, 60).map(e => `
      <div class="item">
        <div class="log-row"><b>${esc(e.date)}</b><span class="meta">${(e.problems || []).length} 題</span></div>
        ${(e.problems || []).map(p => `<div class="log-row"><span>${esc(p)}</span></div>`).join('')}
        ${e.note ? `<p>${esc(e.note)}</p>` : ''}
      </div>`).join('')
      : '<div class="empty">還沒有紀錄。點上面的按鈕開一張 issue 就會自動存進來。</div>'}`;
}

function renderStatus() {
  const secs = DB.status?.sections || [];
  const rows = secs.flatMap(s => (s.sources || []).map(src => `
    <div class="status-line"><span>${esc(s.label)} · ${esc(src.name)}</span>
      <span>${src.ok ? `${src.count} 筆` : esc(src.note || '失敗')}
        <i class="dot ${src.ok ? 'ok' : 'bad'}"></i></span></div>`));

  const ai = DB.status?.ai || {};
  rows.push(`<div class="status-line"><span>AI 摘要</span><span>${
    ai.enabled ? `${esc(ai.model)} · 本次約 NT$${ai.twd}` : '未啟用（沒有 API key）'}</span></div>`);

  $('#status-body').innerHTML = rows.join('');
  const bad = secs.flatMap(s => s.sources || []).filter(s => !s.ok).length;
  $('#status-dot').innerHTML = bad
    ? `<i class="dot bad"></i> ${bad} 個來源異常`
    : '<i class="dot ok"></i> 全部正常';
}

// ---------------------------------------------------------------- 過濾器

const FILTERS = {
  all: () => true,
  new: isNew,
  admission: it => it.admission_signal,
  policy: it => it.policy_signal,
  job: it => it.kind === 'job',
  article: it => it.kind !== 'job',
};

function wireFilters(tabId, listId, key) {
  const tab = $(tabId);
  $$('.chip', tab).forEach(chip => chip.onclick = () => {
    $$('.chip', tab).forEach(c => c.classList.toggle('on', c === chip));
    const f = FILTERS[chip.dataset.filter] || FILTERS.all;
    renderList($(listId), (DB[key]?.items || []).filter(f), '這個條件下沒有內容');
  });
}

// ---------------------------------------------------------------- 啟動

async function load() {
  $('#updated').textContent = '載入中…';
  // 發布時 data/ 跟 index.html 同層；本機直接開 repo 根目錄時在上一層。兩種都試。
  await Promise.all(FILES.map(async name => {
    for (const base of ['data', '../data']) {
      try {
        const r = await fetch(`${base}/${name}.json?t=${Date.now()}`);
        if (r.ok) { DB[name] = await r.json(); return; }
      } catch { /* 換下一個路徑 */ }
    }
  }));

  const t = DB.status?.updated_at;
  $('#updated').textContent = t
    ? `資料更新於 ${new Date(t).toLocaleString('zh-TW', { hour12: false })}（${ago(t)}）`
    : '還沒有資料 — 先在 GitHub Actions 跑一次 daily 工作流程';

  renderHome();
  renderList($('#omscs-list'), DB.omscs?.items || []);
  renderList($('#cpt-list'), DB.cpt?.items || []);
  renderList($('#jobs-list'), DB.jobs?.items || []);
  renderFinance();
  renderPrices();
  renderLeetcode();
  renderStatus();
}

$$('#tabs button').forEach(b => b.onclick = () => {
  $$('#tabs button').forEach(x => x.classList.toggle('on', x === b));
  $$('.tab').forEach(s => s.classList.toggle('on', s.id === 'tab-' + b.dataset.tab));
  location.hash = b.dataset.tab;
  scrollTo(0, 0);
});

wireFilters('#tab-omscs', '#omscs-list', 'omscs');
wireFilters('#tab-cpt', '#cpt-list', 'cpt');
wireFilters('#tab-jobs', '#jobs-list', 'jobs');
$('#refresh').onclick = load;

const wanted = location.hash.slice(1);
if (wanted) $(`#tabs button[data-tab="${wanted}"]`)?.click();
load();
