'use strict';

const TOKEN = document.querySelector('meta[name="hd2mm-token"]').content;
const $ = (id) => document.getElementById(id);

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
  if (d.toDateString() === today.toDateString()) return `오늘 ${time}`;
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
    throw new ApiError('모드 매니저 프로그램과 연결이 끊겼어요. 창을 닫고 다시 실행해 주세요.', 0, null);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || `요청이 실패했어요 (${res.status})`, res.status, data);
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
    chip.replaceChildren(h('span', { class: 'dot err' }), h('span', { class: 'chip-text' }, '게임 폴더를 설정해 주세요'));
  } else {
    chip.replaceChildren(
      h('span', { class: `dot ${g.running ? 'warn' : 'ok'}` }),
      h('span', { class: 'chip-text' },
        h('b', null, 'Helldivers 2'),
        g.version ? ` · v${g.version}` : '',
        g.running ? ' · 실행 중' : ''),
    );
  }
  chip.title = g.path ? `게임 폴더: ${g.path}` : '게임 폴더 설정';
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
      title = '게임 폴더를 찾지 못했어요';
      lines.push(`${g.problem} 오른쪽 위 ⚙ 설정에서 게임 폴더를 지정해 주세요.`);
      break;
    case 'empty':
      title = state.mods.length ? '켜진 모드가 없어요' : '아직 추가한 모드가 없어요';
      lines.push(state.mods.length
        ? '사용할 모드를 켜고 [적용하기]를 누르세요.'
        : '[+ 모드 추가]를 누르거나 모드 압축 파일을 창에 끌어다 놓으세요.');
      break;
    case 'pending':
      tone = 'warn';
      title = '아직 게임에 적용하지 않았어요';
      lines.push(`[적용하기]를 누르면 켜진 모드 ${enabled}개가 게임에 설치돼요.`);
      break;
    case 'dirty':
      tone = 'warn';
      title = '바뀐 내용이 아직 게임에 반영되지 않았어요';
      lines.push('[적용하기]를 눌러야 게임에 반영돼요.');
      break;
    case 'broken':
      tone = 'err';
      title = '설치했던 모드 파일 일부가 사라졌어요';
      lines.push('게임 업데이트나 파일 무결성 검사 때문일 수 있어요. [적용하기]를 다시 눌러 주세요.');
      break;
    case 'ok':
      tone = 'ok';
      title = '게임에 적용된 상태예요';
      lines.push(`모드 ${s.deployedMods}개 · 파일 ${s.deployedFiles}개 · ${fmtTime(s.deployedAt)} 적용`);
      break;
    default:
      title = '';
  }
  if (s.unmanaged?.length) {
    lines.push({ cls: 'warn', text: `이 매니저가 설치하지 않은 모드 파일 ${s.unmanaged.length}개가 게임 폴더에 있어요. 적용할 때 백업 폴더로 옮겨 드려요.` });
  }
  for (const other of s.otherDeployments || []) {
    lines.push({ cls: 'warn', text: `다른 게임 폴더(${other.gamePath})에 이 매니저가 설치한 모드 파일 ${other.files}개가 남아 있어요. 설정에서 그 폴더로 바꾼 뒤 [모두 제거]로 정리할 수 있어요.` });
  }
  if (g.running) lines.push({ cls: 'err', text: '게임이 실행 중이에요. 적용·제거하려면 게임을 먼저 꺼 주세요.' });

  $('statusBar').className = `statusbar tone-${tone}`;
  $('statusTitle').textContent = title;
  $('statusSub').replaceChildren(...lines.map((l) =>
    typeof l === 'string' ? h('div', { class: 'line' }, l) : h('div', { class: `line ${l.cls}` }, l.text)));

  const deployBtn = $('deployBtn');
  deployBtn.disabled = !!busy || s.state === 'nogame';
  deployBtn.classList.toggle('attention', !busy && needsDeploy());
  deployBtn.replaceChildren(...(busy === 'deploy' ? [h('span', { class: 'spinner' }), '적용 중…'] : ['적용하기']));
  const purgeBtn = $('purgeBtn');
  purgeBtn.disabled = !!busy || s.state === 'nogame' || (!s.deployedFiles && !s.unmanaged?.length);
  purgeBtn.replaceChildren(...(busy === 'purge' ? [h('span', { class: 'spinner' }), '제거 중…'] : ['모두 제거']));
  $('launchBtn').replaceChildren(icon('play'), '게임 실행');
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
  return h('label', { class: 'switch', title: checked ? '켜짐 — 누르면 꺼요' : '꺼짐 — 누르면 켜요', onclick: (e) => e.stopPropagation() },
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
    if (m.error) meta.push(h('span', { class: 'badge err' }, '불러오기 오류'));
    else if (m.mode === 'multi' || m.mode === 'single') meta.push(h('span', { class: 'badge' }, '옵션'));
    meta.push(h('span', null, m.enabled ? '켜짐' : '꺼짐'));
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
    h('span', { class: 'grip', title: '끌어서 순서 바꾸기', html: ICONS.grip }),
    modSwitch(m.enabled, `${m.name} 켜기`, (v) => toggleMod(m.id, v)),
    thumb(m.icon, 'thumb'),
    h('div', { class: 'mod-main' },
      h('div', { class: 'mod-name', title: m.name }, m.name),
      h('div', { class: 'mod-meta' }, meta)),
    worst
      ? h('span', { class: `issue-flag ${worst}`, title: '확인할 내용이 있어요' }, icon(worst === 'error' ? 'error' : 'warn'))
      : h('span'));
  });
  list.replaceChildren(
    h('li', { class: 'list-edge', 'aria-hidden': 'true' }, '먼저 적용'),
    ...items,
    h('li', { class: 'list-edge bottom', 'aria-hidden': 'true' }, '마지막 적용 · 가장 높은 우선순위'),
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
      h('div', null, h('strong', null, '모드를 추가해 보세요'),
        '왼쪽 목록에서 모드를 고르면 자세한 정보와 옵션이 여기에 보여요.')));
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
  badges.push(h('span', { class: `badge ${m.enabled ? 'ok' : ''}` }, m.enabled ? '켜짐' : '꺼짐'));
  if (m.gameVersion) badges.push(h('span', { class: 'badge' }, `게임 ${m.gameVersion} 기준`));
  box.append(h('div', { class: 'hero-text' }, h('h1', null, m.name), h('div', { class: 'hero-badges' }, badges)));
  return box;
}

function toolbar(m) {
  const index = state.mods.indexOf(m);
  const last = state.mods.length - 1;
  return h('div', { class: 'toolbar' },
    h('div', { class: 'toggle-label' },
      modSwitch(m.enabled, `${m.name} 켜기`, (v) => toggleMod(m.id, v)),
      h('span', null, m.enabled ? '사용 중' : '사용 안 함')),
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn small', type: 'button', title: '위로 (우선순위 낮추기)', disabled: index <= 0, onclick: () => moveMod(m.id, (from) => from - 1) }, icon('up'), '위로'),
    h('button', { class: 'btn small', type: 'button', title: '아래로 (우선순위 높이기)', disabled: index >= last, onclick: () => moveMod(m.id, (from) => from + 1) }, icon('down'), '아래로'),
    h('button', { class: 'btn small', type: 'button', title: '맨 아래로 (가장 높은 우선순위)', disabled: index >= last, onclick: () => moveMod(m.id, (_, length) => length - 1) }, icon('bottom'), '맨 아래로'),
    h('button', { class: 'btn small', type: 'button', title: '모드 파일이 있는 폴더 열기', onclick: () => openFolder('mod', m.id) }, icon('folder'), '폴더'),
    h('button', { class: 'btn small danger', type: 'button', onclick: () => deleteMod(m) }, icon('trash'), '삭제'));
}

function callouts(m) {
  const items = [];
  if (m.error) items.push({ level: 'error', text: `이 모드를 읽지 못했어요: ${m.error}` });
  items.push(...m.issues);
  if (!items.length) return null;
  const iconFor = { error: 'error', warn: 'warn', info: 'info' };
  return h('div', { class: 'callouts' }, items.map((issue) => h('div', { class: `callout ${issue.level}` },
    icon(iconFor[issue.level] || 'info'),
    h('div', { class: 'callout-text' }, issue.text),
    issue.fix === 'bottom'
      ? h('button', { class: 'btn small', type: 'button', onclick: () => moveMod(m.id, (_, length) => length - 1) }, '맨 아래로 옮기기')
      : null)));
}

function description(m) {
  if (!m.description) return null;
  return h('div', { class: 'section' }, h('h3', null, '설명'), h('div', { class: 'desc' }, m.description));
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
            'aria-label': `${o.name} 세부 선택`, disabled: !on,
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
  const title = m.mode === 'single' ? '버전 고르기 (하나만)' : '옵션';
  return h('div', { class: 'section' }, h('h3', null, title), h('div', { class: 'options' }, rows));
}

function files(m) {
  if (m.error) return null;
  const note = m.enabled
    ? '각 파일은 짝 파일(.gpu_resources, .stream)과 함께 설치돼요. 번호는 목록 순서에 따라 자동으로 매겨져요.'
    : '모드를 켜면 설치될 이름이 정해져요.';
  const body = m.files.length
    ? h('table', { class: 'files' },
      h('thead', null, h('tr', null, h('th', null, '모드 안의 파일'), h('th'), h('th', null, '게임에 설치될 이름'), h('th', null, '크기'))),
      h('tbody', null, m.files.map((f) => h('tr', null,
        h('td', null, f.source), h('td', { class: 'arrow' }, '→'),
        h('td', null, f.target || '—'), h('td', { class: 'muted' }, fmtSize(f.size))))))
    : h('p', { class: 'muted' }, '지금 설정으로는 설치할 파일이 없어요.');
  return fold(`${m.id}:files`,
    h('summary', null, '설치될 파일', h('span', { class: 'muted' }, `${m.files.length}세트`)),
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
  const pre = h('pre', { class: 'readme' }, '불러오는 중…');
  const show = () => loadReadme(m).then((text) => { pre.textContent = text; }, (e) => { pre.textContent = e.message; });
  const details = fold(`${m.id}:readme`,
    h('summary', null, '제작자 설명서 (README)'),
    h('div', { class: 'fold-body' }, pre));
  details.addEventListener('toggle', () => { if (details.open) show(); });
  if (details.open) show();
  return details;
}

function metaInfo(m) {
  const rows = [];
  const add = (k, v) => v && rows.push(h('dt', null, k), h('dd', null, v));
  add('원본 파일', m.sourceName);
  add('추가한 날', fmtTime(m.addedAt));
  add('업데이트한 날', fmtTime(m.updatedAt));
  add('기준 게임 버전', m.gameVersion);
  add('필요한 모드', (m.requires || []).map((r) => (r.revision ? `${r.name} (${r.revision} 이상)` : r.name)).join(', '));
  add('모드 ID', m.guid ? h('span', { class: 'mono' }, m.guid) : null);
  if (!rows.length) return null;
  return h('div', { class: 'section' }, h('h3', null, '정보'), h('dl', { class: 'meta-grid' }, rows));
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
    title: '모드를 삭제할까요?',
    body: [
      h('p', null, `‘${m.name}’을(를) 모드 목록과 보관함에서 지워요.`),
      h('p', { class: 'muted' }, '게임에 이미 설치된 파일은 다음에 [적용하기]를 누를 때 함께 빠져요.'),
    ],
    actions: [{ label: '취소', value: false }, { label: '삭제', kind: 'danger-solid', value: true }],
  });
  if (!ok) return;
  await mutate(async () => {
    await api(`/api/mods/${enc(m.id)}/delete`, { body: {} });
    toast('ok', `‘${m.name}’을(를) 삭제했어요.`);
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
  if (rejected.length) toast('warn', `압축 파일(.zip, .7z, .rar)만 추가할 수 있어요: ${rejected.map((f) => f.name).join(', ')}`);
  if (!accepted.length) return;
  if (busy) {
    toast('warn', '지금은 다른 작업을 하고 있어요. 끝난 뒤 다시 추가해 주세요.');
    return;
  }
  busy = 'import';
  render();
  const progress = toast('loading', '', { sticky: true });
  try {
    for (const [i, file] of accepted.entries()) {
      progress.update('loading', `‘${file.name}’ 추가하는 중…${accepted.length > 1 ? ` (${i + 1}/${accepted.length})` : ''}`);
      try {
        const r = await queuedApi(`/api/import?name=${enc(file.name)}`, { file });
        selectedId = r.id;
        if (!r.updated) toast('ok', `‘${r.name}’ 모드를 추가했어요.`);
        else if (r.previousName && r.previousName !== r.name) toast('ok', `‘${r.previousName}’을(를) ‘${r.name}’(으)로 업데이트했어요. (같은 모드 ID)`);
        else toast('ok', `‘${r.name}’ 모드를 새 파일로 바꿨어요.`);
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
        title: '확인이 필요한 모드가 있어요',
        body: [
          h('p', null, '아래 모드는 필요한 모드가 빠졌거나 문제가 있어 게임에서 제대로 작동하지 않을 수 있어요.'),
          h('ul', { class: 'file-groups' }, broken.map((m) => h('li', null, h('span', null, m.name), h('span', { class: 'badge err' }, '확인 필요')))),
          h('p', { class: 'muted' }, '모드를 눌러 오른쪽의 안내를 확인해 보세요.'),
        ],
        actions: [{ label: '취소', value: false }, { label: '그래도 적용', kind: 'primary', value: true }],
      });
      if (!ok) return false;
    }
  } else {
    const ok = await openModal({
      title: '게임에서 모드를 모두 제거할까요?',
      body: [
        h('p', null, '이 매니저가 게임 폴더에 설치한 모드 파일을 지워서 게임을 원래 상태로 되돌려요.'),
        h('p', { class: 'muted' }, '모드 목록(보관함)은 그대로 남아서 언제든 다시 [적용하기]로 설치할 수 있어요.'),
      ],
      actions: [{ label: '취소', value: false }, { label: '모두 제거', kind: 'danger-solid', value: true }],
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
        const moved = r.backup ? ' 원래 있던 모드 파일은 백업 폴더로 옮겼어요.' : '';
        if (kind === 'purge') toast('ok', `게임에서 모드 파일 ${r.removed}개를 제거했어요.${moved}`);
        else if (r.modCount) toast('ok', `적용 완료! 모드 ${r.modCount}개(파일 ${r.fileCount}개)를 게임에 설치했어요.${moved}`);
        else toast('ok', `켜진 모드가 없어서 게임에서 모드 파일을 모두 뺐어요.${moved}`);
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
    h('p', null, '이 매니저가 설치하지 않은 모드 파일이 게임 폴더에 있어요. 다른 모드 매니저(Arsenal, HD2MM 등)로 설치했거나 직접 넣은 파일일 수 있어요.'),
    h('ul', { class: 'file-groups' }, groups.map((g) => h('li', null,
      h('span', null, h('span', { class: 'mono' }, g.name), g.files.length > 1 ? h('span', { class: 'muted' }, ` 외 ${g.files.length - 1}개`) : null),
      g.match
        ? h('span', { class: 'badge ok', title: '보관함에 있는 모드와 내용이 같아요' }, `‘${g.match}’와 같음`)
        : h('span', { class: 'badge warn' }, g.size ? `알 수 없음 · ${fmtSize(g.size)}` : '알 수 없음')))),
    h('p', null, kind === 'deploy'
      ? '번호가 겹치지 않도록 이 파일들을 백업 폴더로 옮긴 뒤 적용할게요. 지우는 게 아니라서 필요하면 백업 폴더에서 되찾을 수 있어요.'
      : '이 파일들도 백업 폴더로 옮길까요? 지우는 게 아니라서 필요하면 되찾을 수 있어요.'),
  ];
  if (unknown) body.push(h('p', { class: 'muted' }, '‘알 수 없음’ 모드를 계속 쓰려면, 그 모드의 원본 압축 파일을 이 매니저에 추가해 주세요.'));
  body.push(h('p', { class: 'muted' }, '다른 모드 매니저와 함께 쓰면 서로의 파일을 지울 수 있어서, 한 가지만 쓰는 걸 권장해요.'));
  const actions = kind === 'deploy'
    ? [{ label: '취소', value: null }, { label: '백업 폴더로 옮기고 적용', kind: 'primary', value: 'move' }]
    : [{ label: '취소', value: null }, { label: '매니저 파일만 제거', value: 'keep' }, { label: '백업 폴더로 옮기기', kind: 'primary', value: 'move' }];
  return openModal({ title: '게임 폴더에 다른 모드 파일이 있어요', body, actions, wide: true });
}

async function launchGame() {
  if (busy || !state) return;
  await settlePendingChanges();
  if (needsDeploy() && !state.game.running) {
    const choice = await openModal({
      title: '아직 적용하지 않은 변경이 있어요',
      body: h('p', null, '지금 실행하면 바뀐 모드 설정이 게임에 반영되지 않아요. 적용하고 실행할까요?'),
      actions: [{ label: '취소', value: null }, { label: '그냥 실행', value: 'launch' }, { label: '적용하고 실행', kind: 'primary', value: 'deploy' }],
    });
    if (!choice) return;
    if (choice === 'deploy' && !(await runGameAction('deploy'))) return;
  }
  try {
    await queuedApi('/api/launch-game', { body: {} });
    toast('ok', 'Steam으로 게임을 실행하고 있어요.');
  } catch (e) {
    toast('err', e.message);
  }
}

// ------------------------------------------------------------ 설정
function openSettings() {
  const input = h('input', {
    type: 'text', id: 'gamePathInput', value: state?.game.path || '', spellcheck: 'false',
    placeholder: 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Helldivers 2',
  });
  const help = h('div', { class: 'help' }, 'bin 폴더와 data 폴더가 들어 있는 Helldivers 2 설치 폴더예요.');
  const setHelp = (cls, text) => { help.className = `help ${cls}`; help.textContent = text; };
  const browse = h('button', {
    class: 'btn', type: 'button',
    onclick: async () => {
      try {
        const r = await queuedApi('/api/pick-folder', { body: {} });
        if (r.path) { input.value = r.path; setHelp('', '폴더를 골랐어요. [저장]을 눌러 주세요.'); }
      } catch (e) { setHelp('err', e.message); }
    },
  }, icon('folder'), '찾아보기');
  const detect = h('button', {
    class: 'btn', type: 'button',
    onclick: async () => {
      try {
        const r = await queuedApi('/api/detect-game', { body: {} });
        if (r.path) { input.value = r.path; setHelp('ok', '게임 폴더를 찾았어요. [저장]을 눌러 주세요.'); }
        else setHelp('err', '자동으로 찾지 못했어요. [찾아보기]로 직접 골라 주세요.');
      } catch (e) { setHelp('err', e.message); }
    },
  }, '자동으로 찾기');
  const body = [
    h('div', { class: 'field' },
      h('label', { for: 'gamePathInput' }, '게임 설치 폴더'),
      h('div', { class: 'row' }, input),
      h('div', { class: 'row' }, browse, detect),
      help),
    h('div', { class: 'field' },
      h('label', null, '모드 보관 폴더'),
      h('div', { class: 'path-box' }, state?.paths.library || ''),
      h('div', { class: 'help' }, '추가한 모드, 설정, 백업이 여기에 저장돼요.'),
      h('div', { class: 'row' },
        h('button', { class: 'btn small', type: 'button', onclick: () => openFolder('library') }, icon('folder'), '보관 폴더 열기'),
        h('button', { class: 'btn small', type: 'button', onclick: () => openFolder('backups') }, icon('folder'), '백업 폴더 열기'),
        h('button', { class: 'btn small', type: 'button', onclick: () => openFolder('log') }, '로그 보기'))),
    h('p', { class: 'muted', style: 'font-size:12.5px' }, `Modocracy v${state?.appVersion || ''}${state && !state.sevenZip ? ' · 7-Zip이 없어 .7z/.rar 파일은 추가할 수 없어요' : ''}`),
  ];
  return openModal({
    title: '설정',
    body,
    actions: [
      { label: '닫기', value: null },
      {
        label: '저장', kind: 'primary', value: true,
        onClick: async () => {
          try {
            await queuedApi('/api/settings', { body: { gamePath: input.value } });
            toast('ok', '게임 폴더를 저장했어요.');
            await refresh();
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
    h('button', { class: 'toast-close', type: 'button', 'aria-label': '닫기', onclick: () => close() }, icon('x')));
  let timer = null;
  const close = () => { clearTimeout(timer); el.remove(); };
  const update = (k, t) => {
    el.className = `toast ${k}`;
    lead.replaceChildren(k === 'loading' ? h('span', { class: 'spinner' }) : icon({ ok: 'ok', err: 'error', warn: 'warn' }[k] || 'info'));
    textEl.textContent = t;
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
      overlay = h('div', { class: 'disconnected' }, h('div', null,
        h('strong', null, '모드 매니저가 종료되었어요'),
        h('span', { class: 'muted' }, '이 창을 닫고 모드 매니저를 다시 실행해 주세요.')));
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
  });
}

init();
