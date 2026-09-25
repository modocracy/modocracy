'use strict';

const TOKEN = document.querySelector('meta[name="hd2mm-token"]').content;
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------ 언어 (서버가 <html lang>에 넣어 준다)
const LANG = document.documentElement.lang === 'en' ? 'en' : 'ko';
function t(key, params = {}) {
  const text = I18N[LANG][key] ?? I18N.ko[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

function applyStaticText() {
  document.title = t('app.title');
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-title]').forEach((el) => { el.title = t(el.dataset.i18nTitle); });
  document.querySelectorAll('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
}

// ------------------------------------------------------------ 아이콘
const svg = (inner, fill = 'none') =>
  `<svg viewBox="0 0 24 24" fill="${fill}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
const ICONS = {
  settings: svg('<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>'),
  trash: svg('<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/>'),
  folder: svg('<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>'),
  play: svg('<path d="M6 3l14 9-14 9z"/>'),
  up: svg('<path d="m18 15-6-6-6 6"/>'),
  down: svg('<path d="m6 9 6 6 6-6"/>'),
  bottom: svg('<path d="M12 3v12M6 9l6 6 6-6M5 21h14"/>'),
  grip: svg('<circle cx="9" cy="6" r="1.4"/><circle cx="15" cy="6" r="1.4"/><circle cx="9" cy="12" r="1.4"/><circle cx="15" cy="12" r="1.4"/><circle cx="9" cy="18" r="1.4"/><circle cx="15" cy="18" r="1.4"/>', 'currentColor'),
  warn: svg('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4M12 17h.01"/>'),
  error: svg('<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>'),
  info: svg('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>'),
  ok: svg('<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'),
  package: svg('<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/>'),
  upload: svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5M12 3v12"/>'),
  x: svg('<path d="M18 6 6 18M6 6l12 12"/>'),
};

// ------------------------------------------------------------ 도우미
function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'html') el.innerHTML = value; // 고정된 아이콘 SVG에만 사용
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key in el && typeof value !== 'string') el[key] = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}
const icon = (name, cls = '') => h('span', { class: `ico ${cls}`, html: ICONS[name], 'aria-hidden': 'true' });
const enc = encodeURIComponent;

function fmtSize(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (v) => String(v).padStart(2, '0');
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return t('time.today', { time });
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())} ${time}`;
}

class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data; }
}

async function api(path, { body, file } = {}) {
  const post = body !== undefined || file !== undefined;
  const init = { method: post ? 'POST' : 'GET', headers: {} };
  if (post) init.headers['X-HD2MM-Token'] = TOKEN;
  if (file !== undefined) {
    init.body = file;
    init.headers['Content-Type'] = 'application/octet-stream';
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers['Content-Type'] = 'application/json';
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(t('err.disconnected'), 0, null);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || t('err.request_failed', { status: res.status }), res.status, data);
  return data;
}

// ------------------------------------------------------------ 상태
let state = null;
let selectedId = null;
let busy = null; // 'deploy' | 'purge' | 'import'
let lastStateText = '';
const openFolds = new Set(); // 펼쳐 둔 README·파일 목록 (다시 그려도 유지)

// quiet: 자동 새로고침일 때는 바뀐 게 없으면 화면을 다시 그리지 않는다.
async function refresh({ quiet = false } = {}) {
  let next;
  try {
    next = await api('/api/state');
  } catch (e) {
    if (!quiet) toast('err', e.message);
    return;
  }
  const text = JSON.stringify(next);
  if (quiet && text === lastStateText) return;
  lastStateText = text;
  state = next;
  if (!state.mods.some((m) => m.id === selectedId)) selectedId = state.mods[0]?.id ?? null;
  render();
}

function render() {
  if (!state) return;
  renderTop();
  renderStatus();
  renderList();
  renderDetail();
}

const modById = (id) => state?.mods.find((m) => m.id === id);
const needsDeploy = () => ['pending', 'dirty', 'broken'].includes(state?.status.state);

// ------------------------------------------------------------ 상단 / 상태 표시줄
function renderTop() {
  const g = state.game;
  const chip = $('gameChip');
  if (g.problem) {
    chip.replaceChildren(h('span', { class: 'dot err' }), h('span', { class: 'chip-text' }, t('chip.set_game')));
  } else {
    chip.replaceChildren(
      h('span', { class: `dot ${g.running ? 'warn' : 'ok'}` }),
      h('span', { class: 'chip-text' },
        h('b', null, 'Helldivers 2'),
        g.version ? ` · v${g.version}` : '',
        g.running ? t('chip.running') : ''),
    );
  }
  chip.title = g.path ? t('chip.title_path', { path: g.path }) : t('chip.title');
}

function renderStatus() {
  const s = state.status;
  const g = state.game;
  const enabled = state.mods.filter((m) => m.enabled && !m.error).length;
  let tone = 'idle';
  let title = '';
  const lines = [];
  switch (s.state) {
    case 'nogame':
      tone = 'err';
      title = t('status.nogame.title');
      lines.push(t('status.nogame.line', { problem: g.problem }));
      break;
    case 'empty':
      title = state.mods.length ? t('status.empty.title_some') : t('status.empty.title_none');
      lines.push(state.mods.length ? t('status.empty.line_some') : t('status.empty.line_none'));
      break;
    case 'pending':
      tone = 'warn';
      title = t('status.pending.title');
      lines.push(t('status.pending.line', { count: enabled }));
      break;
    case 'dirty':
      tone = 'warn';
      title = t('status.dirty.title');
      lines.push(t('status.dirty.line'));
      break;
    case 'broken':
      tone = 'err';
      title = t('status.broken.title');
      lines.push(t('status.broken.line'));
      break;
    case 'ok':
      tone = 'ok';
      title = t('status.ok.title');
      lines.push(t('status.ok.line', { mods: s.deployedMods, files: s.deployedFiles, time: fmtTime(s.deployedAt) }));
      break;
    default:
      title = '';
  }
  if (s.unmanaged?.length) {
    lines.push({ cls: 'warn', text: t('status.unmanaged', { count: s.unmanaged.length }) });
  }
  for (const other of s.otherDeployments || []) {
    lines.push({ cls: 'warn', text: t('status.other_deployment', { path: other.gamePath, count: other.files }) });
  }
  if (g.running) lines.push({ cls: 'err', text: t('status.game_running') });

  $('statusBar').className = `statusbar tone-${tone}`;
  $('statusTitle').textContent = title;
  $('statusSub').replaceChildren(...lines.map((l) =>
    typeof l === 'string' ? h('div', { class: 'line' }, l) : h('div', { class: `line ${l.cls}` }, l.text)));

  const deployBtn = $('deployBtn');
  deployBtn.disabled = !!busy || s.state === 'nogame';
  deployBtn.classList.toggle('attention', !busy && needsDeploy());
  deployBtn.replaceChildren(...(busy === 'deploy' ? [h('span', { class: 'spinner' }), t('btn.applying')] : [t('btn.apply')]));
  const purgeBtn = $('purgeBtn');
  purgeBtn.disabled = !!busy || s.state === 'nogame' || (!s.deployedFiles && !s.unmanaged?.length);
  purgeBtn.replaceChildren(...(busy === 'purge' ? [h('span', { class: 'spinner' }), t('btn.removing')] : [t('btn.remove_all')]));
  $('launchBtn').replaceChildren(icon('play'), t('btn.launch'));
}

// ------------------------------------------------------------ 모드 목록
function worstIssue(m) {
  if (m.error || m.issues.some((i) => i.level === 'error')) return 'error';
  if (m.issues.some((i) => i.level === 'warn')) return 'warn';
  return null;
}

function thumb(url, cls) {
  if (url) return h('img', { class: cls, src: url, alt: '', loading: 'lazy', draggable: 'false' });
  return h('div', { class: `${cls} placeholder` }, icon('package'));
}

function modSwitch(checked, label, onChange) {
  return h('label', { class: 'switch', title: checked ? t('switch.on_title') : t('switch.off_title'), onclick: (e) => e.stopPropagation() },
    h('input', { type: 'checkbox', checked, 'aria-label': label, onchange: (e) => onChange(e.target.checked) }),
    h('span', { class: 'track' }));
}

function renderList() {
  const list = $('modList');
  const mods = state.mods;
  $('modCount').textContent = mods.length ? `${mods.filter((m) => m.enabled).length}/${mods.length}` : '';
  $('emptyList').hidden = mods.length > 0;
  if (!mods.length) {
    list.replaceChildren();
    return;
  }
  const items = mods.map((m) => {
    const worst = worstIssue(m);
    const meta = [];
    if (m.version) meta.push(h('span', { class: 'badge accent' }, m.version));
    if (m.error) meta.push(h('span', { class: 'badge err' }, t('mod.load_error')));
    else if (m.mode === 'multi' || m.mode === 'single') meta.push(h('span', { class: 'badge' }, t('mod.options')));
    meta.push(h('span', null, m.enabled ? t('mod.on') : t('mod.off')));
    return h('li', {
      class: `mod-item${m.id === selectedId ? ' selected' : ''}${m.enabled ? '' : ' off'}`,
      draggable: 'true',
      tabindex: '0',
      'aria-current': m.id === selectedId ? 'true' : null,
      dataset: { id: m.id },
      onclick: () => select(m.id),
      onkeydown: (e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(m.id); }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          const sibling = e.key === 'ArrowDown' ? e.currentTarget.nextElementSibling : e.currentTarget.previousElementSibling;
          if (sibling?.classList.contains('mod-item')) sibling.focus();
        }
      },
    },
    h('span', { class: 'grip', title: t('mod.drag'), html: ICONS.grip }),
    modSwitch(m.enabled, t('switch.aria', { name: m.name }), (v) => toggleMod(m.id, v)),
    thumb(m.icon, 'thumb'),
    h('div', { class: 'mod-main' },
      h('div', { class: 'mod-name', title: m.name }, m.name),
      h('div', { class: 'mod-meta' }, meta)),
    worst
      ? h('span', { class: `issue-flag ${worst}`, title: t('mod.has_issues') }, icon(worst === 'error' ? 'error' : 'warn'))
      : h('span'));
  });
  list.replaceChildren(
    h('li', { class: 'list-edge', 'aria-hidden': 'true' }, t('list.first')),
    ...items,
    h('li', { class: 'list-edge bottom', 'aria-hidden': 'true' }, t('list.last')),
  );
}

function select(id) {
  if (selectedId === id) return;
  selectedId = id;
  renderList();
  renderDetail();
  $('detail').scrollTop = 0;
}

// ------------------------------------------------------------ 상세 정보
function renderDetail() {
  const panel = $('detail');
  const m = modById(selectedId);
  if (!m) {
    panel.replaceChildren(h('div', { class: 'detail-empty' },
      h('div', null, h('strong', null, t('detail.empty_title')), t('detail.empty_text'))));
    return;
  }
  const keepScroll = panel.dataset.mod === m.id ? panel.scrollTop : 0;
  panel.dataset.mod = m.id;
  panel.replaceChildren(hero(m), h('div', { class: 'detail-body' },
    toolbar(m), callouts(m), description(m), options(m), files(m), readme(m), metaInfo(m)));
  panel.scrollTop = keepScroll;
}

function hero(m) {
  const box = h('div', { class: 'hero' });
  if (m.icon) {
    const bg = h('div', { class: 'hero-bg' });
    bg.style.backgroundImage = `url("${m.icon}")`;
    box.append(bg, h('img', { class: 'hero-img', src: m.icon, alt: '', draggable: 'false' }));
  } else {
    box.append(h('div', { class: 'hero-img placeholder' }, icon('package')));
  }
  const badges = [];
  if (m.version) badges.push(h('span', { class: 'badge accent' }, m.version));
  badges.push(h('span', { class: `badge ${m.enabled ? 'ok' : ''}` }, m.enabled ? t('mod.on') : t('mod.off')));
  if (m.gameVersion) badges.push(h('span', { class: 'badge' }, t('detail.game_version', { version: m.gameVersion })));
  box.append(h('div', { class: 'hero-text' }, h('h1', null, m.name), h('div', { class: 'hero-badges' }, badges)));
  return box;
}

function toolbar(m) {
  const index = state.mods.indexOf(m);
  const last = state.mods.length - 1;
  return h('div', { class: 'toolbar' },
    h('div', { class: 'toggle-label' },
      modSwitch(m.enabled, t('switch.aria', { name: m.name }), (v) => toggleMod(m.id, v)),
      h('span', null, m.enabled ? t('detail.in_use') : t('detail.not_in_use'))),
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn small', type: 'button', title: t('detail.up_title'), disabled: index <= 0, onclick: () => moveMod(m.id, (from) => from - 1) }, icon('up'), t('detail.up')),
    h('button', { class: 'btn small', type: 'button', title: t('detail.down_title'), disabled: index >= last, onclick: () => moveMod(m.id, (from) => from + 1) }, icon('down'), t('detail.down')),
    h('button', { class: 'btn small', type: 'button', title: t('detail.bottom_title'), disabled: index >= last, onclick: () => moveMod(m.id, (_, length) => length - 1) }, icon('bottom'), t('detail.bottom')),
    h('button', { class: 'btn small', type: 'button', title: t('detail.folder_title'), onclick: () => openFolder('mod', m.id) }, icon('folder'), t('detail.folder')),
    h('button', { class: 'btn small danger', type: 'button', onclick: () => deleteMod(m) }, icon('trash'), t('btn.delete')));
}

function callouts(m) {
  const items = [];
  if (m.error) items.push({ level: 'error', text: t('detail.read_error', { error: m.error }) });
  items.push(...m.issues);
  if (!items.length) return null;
  const iconFor = { error: 'error', warn: 'warn', info: 'info' };
  return h('div', { class: 'callouts' }, items.map((issue) => h('div', { class: `callout ${issue.level}` },
    icon(iconFor[issue.level] || 'info'),
    h('div', { class: 'callout-text' }, issue.text),
    issue.fix === 'bottom'
      ? h('button', { class: 'btn small', type: 'button', onclick: () => moveMod(m.id, (_, length) => length - 1) }, t('detail.move_bottom'))
      : null)));
}

function description(m) {
  if (!m.description) return null;
  return h('div', { class: 'section' }, h('h3', null, t('detail.description')), h('div', { class: 'desc' }, m.description));
}

function options(m) {
  if (!m.options?.length || m.error) return null;
  const replaceAt = (list, i, value) => list.map((v, j) => (j === i ? value : v));
  let rows;
  if (m.mode === 'multi') {
    const only = m.options.length === 1;
    rows = m.options.map((o, i) => {
      const on = m.state.enabledOptions[i];
      const sub = o.subs[m.state.selectedSubs[i]];
      return h('label', { class: `option${on ? ' active' : ''}` },
        only ? h('span') : h('input', {
          type: 'checkbox', checked: on, 'aria-label': o.name,
          onchange: (e) => {
            const checked = e.target.checked;
            setModState(m.id, (s) => ({ enabledOptions: replaceAt(s.enabledOptions, i, checked) }));
          },
        }),
        h('div', null,
          h('div', { class: 'option-name' }, o.name),
          o.description ? h('div', { class: 'option-desc' }, o.description) : null,
          o.subs.length ? h('select', {
            'aria-label': t('detail.suboption_aria', { name: o.name }), disabled: !on,
            onchange: (e) => {
              const value = Number(e.target.value);
              setModState(m.id, (s) => ({ selectedSubs: replaceAt(s.selectedSubs, i, value) }));
            },
          }, o.subs.map((s, j) => h('option', { value: String(j), selected: j === m.state.selectedSubs[i] }, s.name))) : null,
          sub?.description ? h('div', { class: 'option-desc' }, sub.description) : null),
        (sub?.image || o.image) ? h('img', { class: 'option-img', src: sub?.image || o.image, alt: '', draggable: 'false' }) : h('span'));
    });
  } else {
    rows = m.options.map((o, i) => h('label', { class: `option${m.state.choice === i ? ' active' : ''}` },
      h('input', { type: 'radio', name: `choice-${m.id}`, checked: m.state.choice === i, onchange: () => setModState(m.id, () => ({ choice: i })) }),
      h('div', null, h('div', { class: 'option-name' }, o.name), o.description ? h('div', { class: 'option-desc' }, o.description) : null),
      o.image ? h('img', { class: 'option-img', src: o.image, alt: '', draggable: 'false' }) : h('span')));
  }
  const title = m.mode === 'single' ? t('detail.choose_one') : t('detail.options');
  return h('div', { class: 'section' }, h('h3', null, title), h('div', { class: 'options' }, rows));
}

function files(m) {
  if (m.error) return null;
  const note = m.enabled
    ? t('files.note_on')
    : t('files.note_off');
  const body = m.files.length
    ? h('table', { class: 'files' },
      h('thead', null, h('tr', null, h('th', null, t('files.source')), h('th'), h('th', null, t('files.target')), h('th', null, t('files.size')))),
      h('tbody', null, m.files.map((f) => h('tr', null,
        h('td', null, f.source), h('td', { class: 'arrow' }, '→'),
        h('td', null, f.target || '—'), h('td', { class: 'muted' }, fmtSize(f.size))))))
    : h('p', { class: 'muted' }, t('files.none'));
  return fold(`${m.id}:files`,
    h('summary', null, t('files.title'), h('span', { class: 'muted' }, t('files.sets', { count: m.files.length }))),
    h('div', { class: 'fold-body' }, body, h('p', { class: 'muted', style: 'margin:8px 0 0;font-size:12.5px' }, note)));
}

function fold(key, ...children) {
  return h('details', {
    class: 'fold', open: openFolds.has(key),
    ontoggle: (e) => (e.currentTarget.open ? openFolds.add(key) : openFolds.delete(key)),
  }, children);
}

// README 본문은 목록 새로고침마다 보내지 않고, 펼칠 때 한 번 가져와 기억해 둔다.
const readmeCache = new Map(); // `${id}|${README 파일 수정 시각}` → Promise<string>

function loadReadme(m) {
  const key = `${m.id}|${m.readmeRev}`;
  if (!readmeCache.has(key)) {
    readmeCache.set(key, api(`/api/mods/${enc(m.id)}/readme`).then(
      (r) => r.readme || '',
      (e) => { readmeCache.delete(key); throw e; },
    ));
  }
  return readmeCache.get(key);
}

function readme(m) {
  if (!m.hasReadme) return null;
  const pre = h('pre', { class: 'readme' }, t('common.loading'));
  const show = () => loadReadme(m).then((text) => { pre.textContent = text; }, (e) => { pre.textContent = e.message; });
  const details = fold(`${m.id}:readme`,
    h('summary', null, t('readme.title')),
    h('div', { class: 'fold-body' }, pre));
  details.addEventListener('toggle', () => { if (details.open) show(); });
  if (details.open) show();
  return details;
}

function metaInfo(m) {
  const rows = [];
  const add = (k, v) => v && rows.push(h('dt', null, k), h('dd', null, v));
  add(t('meta.source'), m.sourceName);
  add(t('meta.added'), fmtTime(m.addedAt));
  add(t('meta.updated'), fmtTime(m.updatedAt));
  add(t('meta.game_version'), m.gameVersion);
  add(t('meta.requires'), (m.requires || []).map((r) => {
    const label = r.revision ? t('meta.at_least', { name: r.name, revision: r.revision }) : r.name;
    return r.optional ? t('meta.optional', { label }) : label;
  }).join(', '));
  add(t('meta.guid'), m.guid ? h('span', { class: 'mono' }, m.guid) : null);
  if (!rows.length) return null;
  return h('div', { class: 'section' }, h('h3', null, t('meta.title')), h('dl', { class: 'meta-grid' }, rows));
}

// ------------------------------------------------------------ 동작
let mutationQueue = Promise.resolve();
function queueMutation(fn) {
  const job = mutationQueue.then(async () => {
    try {
      return await fn();
    } finally {
      await refresh();
    }
  });
  mutationQueue = job.catch(() => {});
  return job;
}

const queuedApi = (path, options) => queueMutation(() => api(path, options));
const mutate = (fn) => queueMutation(fn).catch((e) => toast('err', e.message));
const toggleMod = (id, enabled) => mutate(() => {
  if (modById(id)) return api(`/api/mods/${enc(id)}`, { body: { enabled } });
});
const setModState = (id, changes) => mutate(() => {
  const m = modById(id);
  if (m) return api(`/api/mods/${enc(id)}`, { body: changes(m.state) });
});

function moveMod(id, toIndex) {
  return mutate(() => {
    const ids = state.mods.map((m) => m.id);
    const from = ids.indexOf(id);
    const target = toIndex(from, ids.length);
    if (from < 0 || target < 0 || target >= ids.length || from === target) return;
    ids.splice(from, 1);
    ids.splice(target, 0, id);
    return api('/api/order', { body: { ids } });
  });
}

async function deleteMod(m) {
  const ok = await openModal({
    title: t('delete.title'),
    body: [
      h('p', null, t('delete.text', { name: m.name })),
      h('p', { class: 'muted' }, t('delete.note')),
    ],
    actions: [{ label: t('btn.cancel'), value: false }, { label: t('btn.delete'), kind: 'danger-solid', value: true }],
  });
  if (!ok) return;
  await mutate(async () => {
    await api(`/api/mods/${enc(m.id)}/delete`, { body: {} });
    toast('ok', t('delete.done', { name: m.name }));
  });
}

async function openFolder(target, id) {
  try {
    await queuedApi('/api/open', { body: { target, id } });
  } catch (e) {
    toast('err', e.message);
  }
}

async function importFiles(fileList) {
  const files = [...fileList];
  const accepted = files.filter((f) => /\.(zip|7z|rar)$/i.test(f.name));
  const rejected = files.filter((f) => !accepted.includes(f));
  if (rejected.length) toast('warn', t('import.only_archives', { names: rejected.map((f) => f.name).join(', ') }));
  if (!accepted.length) return;
  if (busy) {
    toast('warn', t('import.busy'));
    return;
  }
  busy = 'import';
  render();
  const progress = toast('loading', '', { sticky: true });
  try {
    for (const [i, file] of accepted.entries()) {
      progress.update('loading', t('import.progress', { name: file.name, counter: accepted.length > 1 ? ` (${i + 1}/${accepted.length})` : '' }));
      try {
        const r = await queuedApi(`/api/import?name=${enc(file.name)}`, { file });
        selectedId = r.id;
        if (!r.updated) toast('ok', t('import.added', { name: r.name }));
        else if (r.previousName && r.previousName !== r.name) toast('ok', t('import.renamed', { old: r.previousName, name: r.name }));
        else toast('ok', t('import.replaced', { name: r.name }));
      } catch (e) {
        toast('err', `${file.name}: ${e.message}`);
      }
    }
  } finally {
    progress.close();
    busy = null;
    await refresh();
  }
}

// 앞서 누른 변경(켜기·옵션·순서)이 서버에 반영되고 화면이 새로고침될 때까지 기다린다.
// 기다리는 동안 새 변경이 들어오면 그것까지 끝날 때까지 기다린다.
async function settlePendingChanges() {
  busy = 'wait';
  renderStatus();
  try {
    let pending;
    do {
      pending = mutationQueue;
      await pending;
    } while (pending !== mutationQueue);
  } finally {
    busy = null;
    renderStatus();
  }
}

async function runGameAction(kind) {
  if (busy || !state) return false;
  await settlePendingChanges();
  if (kind === 'deploy') {
    const broken = state.mods.filter((m) => m.enabled && (m.error || m.issues.some((i) => i.level === 'error')));
    if (broken.length) {
      const ok = await openModal({
        title: t('confirm_broken.title'),
        body: [
          h('p', null, t('confirm_broken.text')),
          h('ul', { class: 'file-groups' }, broken.map((m) => h('li', null, h('span', null, m.name), h('span', { class: 'badge err' }, t('confirm_broken.badge'))))),
          h('p', { class: 'muted' }, t('confirm_broken.note')),
        ],
        actions: [{ label: t('btn.cancel'), value: false }, { label: t('confirm_broken.apply'), kind: 'primary', value: true }],
      });
      if (!ok) return false;
    }
  } else {
    const ok = await openModal({
      title: t('purge.title'),
      body: [
        h('p', null, t('purge.text')),
        h('p', { class: 'muted' }, t('purge.note')),
      ],
      actions: [{ label: t('btn.cancel'), value: false }, { label: t('btn.remove_all'), kind: 'danger-solid', value: true }],
    });
    if (!ok) return false;
  }

  let mode = 'ask';
  let success = false;
  busy = kind;
  renderStatus();
  try {
    for (;;) {
      try {
        const r = await queuedApi(`/api/${kind}`, { body: { unmanaged: mode } });
        const moved = r.backup ? t('result.moved') : '';
        if (kind === 'purge') toast('ok', t('result.purged', { count: r.removed, moved }));
        else if (r.modCount) toast('ok', t('result.deployed', { mods: r.modCount, files: r.fileCount, moved }));
        else toast('ok', t('result.cleared', { moved }));
        success = true;
        break;
      } catch (e) {
        if (e.status === 409 && e.data?.needsConfirm === 'unmanaged' && mode === 'ask') {
          busy = null;
          renderStatus();
          const choice = await confirmUnmanaged(e.data.unmanaged, kind);
          if (!choice) break;
          mode = choice;
          busy = kind;
          renderStatus();
          continue;
        }
        throw e;
      }
    }
  } catch (e) {
    toast('err', e.message);
  } finally {
    busy = null;
    await refresh();
  }
  return success;
}

function confirmUnmanaged(groups, kind) {
  const unknown = groups.filter((g) => !g.match).length;
  const body = [
    h('p', null, t('unmanaged.text')),
    h('ul', { class: 'file-groups' }, groups.map((g) => h('li', null,
      h('span', null, h('span', { class: 'mono' }, g.name), g.files.length > 1 ? h('span', { class: 'muted' }, t('unmanaged.more', { count: g.files.length - 1 })) : null),
      g.match
        ? h('span', { class: 'badge ok', title: t('unmanaged.same_title') }, t('unmanaged.same', { name: g.match }))
        : h('span', { class: 'badge warn' }, g.size ? t('unmanaged.unknown_size', { size: fmtSize(g.size) }) : t('unmanaged.unknown'))))),
    h('p', null, kind === 'deploy'
      ? t('unmanaged.deploy_text')
      : t('unmanaged.purge_text')),
  ];
  if (unknown) body.push(h('p', { class: 'muted' }, t('unmanaged.unknown_note')));
  body.push(h('p', { class: 'muted' }, t('unmanaged.one_manager')));
  const actions = kind === 'deploy'
    ? [{ label: t('btn.cancel'), value: null }, { label: t('unmanaged.move_apply'), kind: 'primary', value: 'move' }]
    : [{ label: t('btn.cancel'), value: null }, { label: t('unmanaged.keep'), value: 'keep' }, { label: t('unmanaged.move'), kind: 'primary', value: 'move' }];
  return openModal({ title: t('unmanaged.title'), body, actions, wide: true });
}

async function launchGame() {
  if (busy || !state) return;
  await settlePendingChanges();
  if (needsDeploy() && !state.game.running) {
    const choice = await openModal({
      title: t('launch.title'),
      body: h('p', null, t('launch.text')),
      actions: [{ label: t('btn.cancel'), value: null }, { label: t('launch.anyway'), value: 'launch' }, { label: t('launch.apply'), kind: 'primary', value: 'deploy' }],
    });
    if (!choice) return;
    if (choice === 'deploy' && !(await runGameAction('deploy'))) return;
  }
  try {
    await queuedApi('/api/launch-game', { body: {} });
    toast('ok', t('launch.started'));
  } catch (e) {
    toast('err', e.message);
  }
}

// ------------------------------------------------------------ 앱 업데이트
let updateInfo = null;
let restarting = false;
let restartOverlay = null;

async function checkForUpdate({ manual = false } = {}) {
  try {
    // 직접 누른 확인은 기억해 둔 결과 없이 새로 묻는다 (토큰이 필요한 POST)
    updateInfo = manual ? await api('/api/update/check', { body: {} }) : await api('/api/update');
  } catch (e) {
    if (manual) toast('err', e.message);  // 켤 때 자동 확인이 실패하면 조용히 넘어간다
    return;
  }
  renderUpdateBar();
  if (manual && !updateInfo.newer) toast('ok', t('update.latest', { version: updateInfo.current }));
}

function renderUpdateBar() {
  const bar = $('updateBar');
  const u = updateInfo;
  bar.hidden = !u?.newer;
  if (bar.hidden) return;
  bar.replaceChildren(
    h('div', { class: 'update-text' },
      icon('upload'),
      h('span', null, h('strong', null, t('update.available', { version: u.latest })), h('span', { class: 'muted' }, t('update.current', { version: u.current })))),
    h('div', { class: 'status-actions' },
      h('button', { class: 'btn ghost small', type: 'button', onclick: () => openFolder('release') }, t('update.changes')),
      u.canInstall
        ? h('button', { class: 'btn primary small', type: 'button', onclick: installUpdate }, t('update.install'))
        : h('button', { class: 'btn small', type: 'button', title: u.problem || '', onclick: () => openFolder('release') }, t('update.download'))));
}

async function installUpdate() {
  if (busy || !updateInfo?.canInstall) return;
  const ok = await openModal({
    title: t('update.confirm_title', { version: updateInfo.latest }),
    body: [
      h('p', null, t('update.confirm_text')),
      h('p', { class: 'muted' }, t('update.confirm_note')),
    ],
    actions: [{ label: t('btn.later'), value: false }, { label: t('update.install'), kind: 'primary', value: true }],
  });
  if (!ok || busy) return;
  await settlePendingChanges();
  busy = 'update';
  render();
  const progress = toast('loading', t('update.downloading'), { sticky: true });
  try {
    const r = await api('/api/update/install', { body: {} });
    restarting = true;
    progress.close();
    restartOverlay = h('div', { class: 'disconnected' }, h('div', null,
      h('strong', null, t('update.restarting', { version: r.version })),
      h('span', { class: 'muted' }, t('update.restarting_note'))));
    document.body.append(restartOverlay);
  } catch (e) {
    progress.close();
    busy = null;
    render();
    const open = await openModal({
      title: t('update.failed_title'),
      body: [h('p', null, e.message), h('p', { class: 'muted' }, t('update.failed_note'))],
      actions: [{ label: t('btn.close'), value: false }, { label: t('update.open_releases'), kind: 'primary', value: true }],
    });
    if (open) openFolder('release');
  }
}

// ------------------------------------------------------------ 설정
function openSettings() {
  const updateToggle = h('input', { type: 'checkbox', checked: state?.checkUpdates !== false });
  const languageSelect = h('select', { id: 'languageSelect' },
    [['auto', t('settings.language_auto')], ['ko', '한국어'], ['en', 'English']].map(([value, label]) =>
      h('option', { value, selected: (state?.language || 'auto') === value }, label)));
  const input = h('input', {
    type: 'text', id: 'gamePathInput', value: state?.game.path || '', spellcheck: 'false',
    placeholder: 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Helldivers 2',
  });
  const help = h('div', { class: 'help' }, t('settings.game_help'));
  const setHelp = (cls, text) => { help.className = `help ${cls}`; help.textContent = text; };
  const browse = h('button', {
    class: 'btn', type: 'button',
    onclick: async () => {
      try {
        const r = await queuedApi('/api/pick-folder', { body: {} });
        if (r.path) { input.value = r.path; setHelp('', t('settings.picked')); }
      } catch (e) { setHelp('err', e.message); }
    },
  }, icon('folder'), t('settings.browse'));
  const detect = h('button', {
    class: 'btn', type: 'button',
    onclick: async () => {
      try {
        const r = await queuedApi('/api/detect-game', { body: {} });
        if (r.path) { input.value = r.path; setHelp('ok', t('settings.found')); }
        else setHelp('err', t('settings.not_found'));
      } catch (e) { setHelp('err', e.message); }
    },
  }, t('settings.detect'));
  const body = [
    h('div', { class: 'field' },
      h('label', { for: 'gamePathInput' }, t('settings.game_folder')),
      h('div', { class: 'row' }, input),
      h('div', { class: 'row' }, browse, detect),
      help),
    h('div', { class: 'field' },
      h('label', null, t('settings.library')),
      h('div', { class: 'path-box' }, state?.paths.library || ''),
      h('div', { class: 'help' }, t('settings.library_help')),
      h('div', { class: 'row' },
        h('button', { class: 'btn small', type: 'button', onclick: () => openFolder('library') }, icon('folder'), t('settings.open_library')),
        h('button', { class: 'btn small', type: 'button', onclick: () => openFolder('backups') }, icon('folder'), t('settings.open_backups')),
        h('button', { class: 'btn small', type: 'button', onclick: () => openFolder('log') }, t('settings.view_log')))),
    h('div', { class: 'field' },
      h('label', { for: 'languageSelect' }, t('settings.language')),
      h('div', { class: 'row' }, languageSelect)),
    h('div', { class: 'field' },
      h('label', null, t('settings.updates')),
      h('label', { class: 'check-row' }, updateToggle, t('settings.check_on_start')),
      h('div', { class: 'row' },
        h('button', { class: 'btn small', type: 'button', onclick: () => checkForUpdate({ manual: true }) }, t('settings.check_now')),
        h('span', { class: 'help' }, t('settings.version', { version: state?.appVersion || '' })))),
    state && !state.sevenZip ? h('p', { class: 'muted', style: 'font-size:12.5px' }, t('settings.no_7zip')) : null,
  ];
  return openModal({
    title: t('settings.title'),
    body,
    actions: [
      { label: t('btn.close'), value: null },
      {
        label: t('btn.save'), kind: 'primary', value: true,
        onClick: async () => {
          try {
            await queuedApi('/api/settings', {
              body: { gamePath: input.value, checkUpdates: updateToggle.checked, language: languageSelect.value },
            });
            await refresh();
            // 언어가 바뀌면 화면 전체를 새 언어로 다시 불러온다
            if (state?.lang && state.lang !== LANG) {
              location.reload();
              return true;
            }
            toast('ok', t('settings.saved'));
            return true;
          } catch (e) {
            setHelp('err', e.message);
            return false;
          }
        },
      },
    ],
  });
}

// ------------------------------------------------------------ 대화상자 / 알림
function openModal({ title, body, actions, wide = false }) {
  return new Promise((resolve) => {
    const root = $('modalRoot');
    const previous = document.activeElement;
    let done = false;
    const close = (value) => {
      if (done) return;
      done = true;
      backdrop.remove();
      document.removeEventListener('keydown', onKey, true);
      previous?.focus?.();
      resolve(value);
    };
    const buttons = actions.map((a) => h('button', {
      class: `btn ${a.kind || ''}`, type: 'button',
      onclick: async (e) => {
        if (a.onClick) {
          const button = e.currentTarget;
          button.disabled = true;
          try {
            if ((await a.onClick()) === false) return;
          } catch (err) {
            toast('err', err.message);
            return;
          } finally {
            button.disabled = false;
          }
        }
        close(a.value);
      },
    }, a.label));
    const dialog = h('div', { class: `modal${wide ? ' wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      h('div', { class: 'modal-head' }, h('h2', null, title)),
      h('div', { class: 'modal-body' }, body),
      h('div', { class: 'modal-actions' }, buttons));
    const backdrop = h('div', { class: 'modal-backdrop', onmousedown: (e) => { if (e.target === backdrop) close(actions[0]?.value ?? null); } }, dialog);
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); close(actions[0]?.value ?? null); }
    };
    document.addEventListener('keydown', onKey, true);
    root.append(backdrop);
    // 기본 초점은 주 버튼, 위험한 동작(삭제 등)만 있는 창은 첫 번째(취소) 버튼
    const primary = actions.findLastIndex((a) => a.kind === 'primary');
    (buttons[primary >= 0 ? primary : 0] || dialog).focus();
  });
}

function toast(kind, text, { sticky = false } = {}) {
  const box = $('toasts');
  const textEl = h('div', { class: 'toast-text' });
  const lead = h('span');
  const el = h('div', { class: 'toast', role: kind === 'err' ? 'alert' : 'status' }, lead, textEl,
    h('button', { class: 'toast-close', type: 'button', 'aria-label': t('btn.close'), onclick: () => close() }, icon('x')));
  let timer = null;
  const close = () => { clearTimeout(timer); el.remove(); };
  const update = (k, message) => {
    el.className = `toast ${k}`;
    lead.replaceChildren(k === 'loading' ? h('span', { class: 'spinner' }) : icon({ ok: 'ok', err: 'error', warn: 'warn' }[k] || 'info'));
    textEl.textContent = message;
    clearTimeout(timer);
    if (!sticky) timer = setTimeout(close, k === 'err' ? 9000 : 5000);
  };
  update(kind, text);
  box.append(el);
  while (box.children.length > 5) box.firstElementChild.remove();
  return { close, update };
}

// ------------------------------------------------------------ 끌어놓기
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
let fileDragDepth = 0;
window.addEventListener('dragenter', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  fileDragDepth++;
  $('dropOverlay').hidden = false;
});
window.addEventListener('dragover', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'copy';
});
window.addEventListener('dragleave', (e) => {
  if (!hasFiles(e)) return;
  fileDragDepth = Math.max(0, fileDragDepth - 1);
  if (!fileDragDepth) $('dropOverlay').hidden = true;
});
window.addEventListener('drop', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  fileDragDepth = 0;
  $('dropOverlay').hidden = true;
  importFiles(e.dataTransfer.files);
});

let dragId = null;
let dropTarget = null;
const clearDropMarks = () => document.querySelectorAll('.drop-before, .drop-after').forEach((el) => el.classList.remove('drop-before', 'drop-after'));
const list = $('modList');
list.addEventListener('dragstart', (e) => {
  const li = e.target.closest?.('.mod-item');
  if (!li) return;
  dragId = li.dataset.id;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('application/x-hd2mm-mod', dragId);
  li.classList.add('dragging');
});
list.addEventListener('dragend', () => {
  dragId = null;
  dropTarget = null;
  clearDropMarks();
  document.querySelectorAll('.mod-item.dragging').forEach((el) => el.classList.remove('dragging'));
});
list.addEventListener('dragover', (e) => {
  if (!dragId) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const target = e.target.closest?.('.mod-item');
  clearDropMarks();
  if (!target || target.dataset.id === dragId) { dropTarget = null; return; }
  const rect = target.getBoundingClientRect();
  const after = e.clientY > rect.top + rect.height / 2;
  target.classList.add(after ? 'drop-after' : 'drop-before');
  dropTarget = { id: target.dataset.id, after };
});
list.addEventListener('drop', (e) => {
  if (!dragId) return;
  e.preventDefault();
  const moving = dragId;
  const target = dropTarget;
  clearDropMarks();
  if (!target) return;
  mutate(() => {
    if (!modById(moving) || !modById(target.id) || moving === target.id) return;
    const ids = state.mods.map((m) => m.id).filter((id) => id !== moving);
    const index = ids.indexOf(target.id) + (target.after ? 1 : 0);
    ids.splice(index, 0, moving);
    return api('/api/order', { body: { ids } });
  });
});

// ------------------------------------------------------------ 시작
function watchConnection() {
  let lostTimer = null;
  let overlay = null;
  const es = new EventSource('/api/events');
  es.addEventListener('open', () => {
    clearTimeout(lostTimer);
    lostTimer = null;
    if (overlay) { overlay.remove(); overlay = null; refresh(); }
  });
  es.addEventListener('error', () => {
    if (lostTimer || overlay) return;
    lostTimer = setTimeout(() => {
      lostTimer = null;
      if (restarting) {
        // Edge 창으로 열었을 때는 이 창이 저절로 닫히지 않는다: 새 창이 따로 열린다고 알려 준다
        restartOverlay?.replaceChildren(h('div', null,
          h('strong', null, t('update.new_window')),
          h('span', { class: 'muted' }, t('update.close_this'))));
        return;
      }
      overlay = h('div', { class: 'disconnected' }, h('div', null,
        h('strong', null, t('disconnected.title')),
        h('span', { class: 'muted' }, t('disconnected.text'))));
      document.body.append(overlay);
    }, 4000);
  });
}

function sizeAppWindow() {
  if (!new URLSearchParams(location.search).has('app')) return;
  try {
    if (sessionStorage.getItem('hd2mm-sized')) return;
    sessionStorage.setItem('hd2mm-sized', '1');
  } catch { return; }
  if (window.outerWidth >= 1180) return;
  const w = Math.min(1320, screen.availWidth - 40);
  const hgt = Math.min(880, screen.availHeight - 40);
  window.resizeTo(w, hgt);
  window.moveTo((screen.availLeft || 0) + (screen.availWidth - w) / 2, (screen.availTop || 0) + (screen.availHeight - hgt) / 2);
}

function init() {
  applyStaticText();
  $('settingsBtn').replaceChildren(icon('settings'));
  document.querySelectorAll('.empty-icon').forEach((el) => { el.innerHTML = ICONS.upload; });
  $('addBtn').addEventListener('click', () => $('fileInput').click());
  $('emptyList').addEventListener('click', () => $('fileInput').click());
  $('fileInput').addEventListener('change', (e) => {
    const files = [...e.target.files];
    e.target.value = '';
    importFiles(files);
  });
  $('deployBtn').addEventListener('click', () => runGameAction('deploy'));
  $('purgeBtn').addEventListener('click', () => runGameAction('purge'));
  $('launchBtn').addEventListener('click', launchGame);
  $('settingsBtn').addEventListener('click', openSettings);
  $('gameChip').addEventListener('click', openSettings);

  let lastFocusRefresh = 0;
  window.addEventListener('focus', () => {
    if (busy || Date.now() - lastFocusRefresh < 1500) return;
    lastFocusRefresh = Date.now();
    refresh({ quiet: true });
  });
  setInterval(() => {
    if (!busy && document.visibilityState === 'visible' && !$('modalRoot').children.length) refresh({ quiet: true });
  }, 15000);

  sizeAppWindow();
  watchConnection();
  refresh().then(() => {
    if (state?.game.problem) openSettings();
    if (state?.checkUpdates) checkForUpdate();
  });
}

init();
