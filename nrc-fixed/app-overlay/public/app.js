// ════════════════════════════════════════════════════════════
//  NRC 服装预览工具  —  app.js
// ════════════════════════════════════════════════════════════

// ── 状态 ─────────────────────────────────────────────────────
const state = {
  gender: 1,             // 1=男(PC1)  2=女(PC2)
  mainTab: null,
  subTab: null,
  search: '',
  selected: {},          // slot(type_name / salon_N) → { item, source }
  selectedSuitId: null,  // 当前高亮的套装 id
  activeColorGroup: null,
  data: null,
};

// 上一次渲染时的 tab 状态，用于跳过不必要的 sidebar/subtabs 重建
let _renderedMainTab = null;
let _renderedSubTab  = null;
let _lastPreviewSignature = null;

const CONFIG_FIELDS = ['dataRoot', 'iconRoot', 'suitsRoot', 'framesRoot', 'modelRoot', 'port',
  'mmdBlender', 'mmdOutDir', 'mmdMorphRoot', 'mmdNaming', 'mmdPhysics'];
const UI_PREF_KEYS = {
  cardSize: 'nrc.ui.cardSize',
  panelWidth: 'nrc.ui.panelWidth',
  selectedPanelHeight: 'nrc.ui.selectedPanelHeight',
};
const WATERMARK_ID_KEY = 'nrc.watermark.id';
const DISCLAIMER_ACCEPTED_KEY = 'nrc.disclaimer.accepted.v1';

// 游戏内只有材质贴图、没有网格模型的服饰（与 preview.js 共用同一份核对结果）。
// 这些物品缺的是游戏资源本身，不是本地导出漏了，卡片上要标出来。
const unreleasedItems = new Map();
const unreleasedReady = fetch('/unreleased-items.json')
  .then(r => (r.ok ? r.json() : null))
  .then(data => { for (const item of data?.items || []) unreleasedItems.set(String(item.id), item); })
  .catch(() => {});
function unreleasedInfo(item) { return item ? unreleasedItems.get(String(item.id)) || null : null; }

// ── UE 路径解析 ───────────────────────────────────────────────
// "Texture2D'/Game/.../Icon/10700101.10700101'"  →  "10700101"
// 注意：部分路径末尾缺闭合的 '（如 img_wazi_png），用字符串操作更稳健
function parseUEId(uePath) {
  if (!uePath) return null;
  const lastSlash = uePath.lastIndexOf('/');
  if (lastSlash === -1) return null;
  const filename = uePath.slice(lastSlash + 1);   // "10700101.10700101'" 或 "img_wazi_png.img_wazi_png"
  const dotIndex = filename.indexOf('.');
  return dotIndex !== -1 ? filename.slice(0, dotIndex) : filename.replace(/['"]+$/, '');
}

function iconUrl(uePath)  { const id = parseUEId(uePath); return id ? `/assets/icon/${id}` : null; }
function suitImgUrl(path) { const id = parseUEId(path);   return id ? `/assets/suit/${id}` : null; }

// 套装卡片的灰模 / 上身图偏好，与角色性别及穿戴状态独立。
const SUIT_PREVIEW_MODE_KEY = 'nrc.ui.suitPreviewMode';
function loadSuitPreviewMode() {
  try { return localStorage.getItem(SUIT_PREVIEW_MODE_KEY) === 'pose' ? 'pose' : 'gray'; }
  catch { return 'gray'; }
}
let suitPreviewMode = loadSuitPreviewMode();
const suitThumbOverrides = new Map();
const suitThumbOverrideReady = fetch('/suit-thumbs.json')
  .then(r => (r.ok ? r.json() : null))
  .then(data => { for (const [id, name] of Object.entries(data || {})) suitThumbOverrides.set(String(id), name); })
  .catch(() => {});
const suitPoseOverrides = new Map();
const suitPoseOverrideReady = fetch('/suit-poses.json')
  .then(r => (r.ok ? r.json() : null))
  .then(data => { for (const [id, name] of Object.entries(data || {})) suitPoseOverrides.set(String(id), name); })
  .catch(() => {});
function suitThumbOverride(suit) { return suitThumbOverrides.get(String(suit.id)) || null; }
function suitThumbUrls(suit) {
  const override = suitThumbOverride(suit);
  const gray = override ? `/assets/suit/${override}` : suitImgUrl(suit.suits_icon);
  const poseName = suitPoseOverrides.get(String(suit.id));
  const configuredPose = parseUEId(suit.suits_icon_big);
  const pose = poseName ? `/assets/suit/${poseName}`
    : configuredPose?.endsWith('_pose') ? `/assets/suit/${configuredPose}` : null;
  if (suitPreviewMode === 'pose' && pose) return { primary: pose, fallback: gray && gray !== pose ? gray : null };
  return { primary: gray || pose, fallback: null };
}
function updateSuitPreviewToggle() {
  const toggle = document.getElementById('suit-preview-toggle');
  if (toggle) toggle.classList.toggle('hidden', state.mainTab !== 1);
  document.querySelectorAll('.suit-preview-btn').forEach(btn => {
    const active = btn.dataset.previewMode === suitPreviewMode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', String(active));
  });
}
function setSuitPreviewMode(mode) {
  if (mode !== 'gray' && mode !== 'pose') return;
  suitPreviewMode = mode;
  try { localStorage.setItem(SUIT_PREVIEW_MODE_KEY, mode); } catch {}
  updateSuitPreviewToggle();
  renderGrid();
  renderSelectedPanel();
}
function frameUrl(uePath) { const id = parseUEId(uePath); return id ? `/assets/frame/${id}` : null; }

// ── 一级 Tab 定义（按游戏侧边栏顺序）────────────────────────
const MAIN_TABS = [
  { id: 1,  label: '套装' },
  { id: 3,  label: '衣服' },
  { id: 9,  label: '装饰' },
  { id: 2,  label: '法杖' },
  { id: 15, label: '发型' },
  { id: 16, label: '妆容' },
];

// 对没有 use_FashionLabelType 的叶子 tab，按 type_name 过滤
// tab id → type_name（展示该 type_name 的所有物品）
const TAB_TYPENAME_FALLBACK = {
  5: '上衣',   // 上装 tab
};

// 固定装备槽位定义（实线=必选，虚线=可选）
const SLOTS = [
  // ── 服装 ──────────────────────────────────────────────────
  { key: '上衣',   label: '上衣',   required: true,  group: 'fashion' },
  { key: '下装',   label: '下装',   required: true,  group: 'fashion' },
  { key: '袜子',   label: '袜子',   required: true,  group: 'fashion' },
  { key: '鞋子',   label: '鞋子',   required: false, group: 'fashion' },
  { key: '帽子',   label: '帽子',   required: false, group: 'fashion' },
  { key: '头饰',   label: '头饰',   required: false, group: 'fashion' },
  { key: '面饰',   label: '面饰',   required: false, group: 'fashion' },
  { key: '手饰',   label: '手饰',   required: true,  group: 'fashion' },
  { key: '背包',   label: '背包',   required: false, group: 'fashion' },
  { key: '包挂饰', label: '包挂饰', required: false, group: 'fashion' },
  { key: '法杖',   label: '法杖',   required: false, group: 'fashion' },
  // ── 妆容 ──────────────────────────────────────────────────
  { key: 'salon_1',         label: '发型', required: true,  group: 'salon' },
  { key: 'salon_undefined', label: '肤色', required: true,  group: 'salon' },
  { key: 'salon_2',         label: '眉毛', required: true,  group: 'salon' },
  { key: 'salon_3',         label: '睫毛', required: true,  group: 'salon' },
  { key: 'salon_4',         label: '瞳孔', required: true,  group: 'salon' },
  { key: 'salon_5',         label: '贴花', required: false, group: 'salon' },
];

// ── 数据加载 ──────────────────────────────────────────────────
async function loadData() {
  const [tabs, items, suits, salon, config] = await Promise.all([
    fetch('/api/tabs').then(r => r.json()),
    fetch('/api/items').then(r => r.json()),
    fetch('/api/suits').then(r => r.json()),
    fetch('/api/salon').then(r => r.json()),
    fetch('/api/config').then(r => r.json()),
  ]);

  const salonArr = Object.values(salon);

  // 按 avatar_id 合并发型/妆容颜色变体
  const salonGroupMap = {};
  salonArr.forEach(item => {
    const key = item.avatar_id;
    if (!salonGroupMap[key]) {
      salonGroupMap[key] = {
        avatar_id:    key,
        name:         item.name,
        icon:         item.icon,
        type:         item.type,
        gender:       item.gender,
        item_quality: item.item_quality,
        variants:     [],
      };
    }
    salonGroupMap[key].variants.push(item);
  });
  // 按 texture_id 排序变体
  Object.values(salonGroupMap).forEach(g =>
    g.variants.sort((a, b) => (a.texture_id || 0) - (b.texture_id || 0))
  );

  const itemArr = Object.values(items);

  // id → item 快速查找（套装展开用）
  const itemById = {};
  itemArr.forEach(i => { itemById[i.id] = i; });

  state.data = {
    tabs,
    tabArr:        Object.values(tabs),
    itemArr,
    itemById,
    suitArr:       Object.values(suits),
    salonArr,
    salonGroupMap,
    salonGroupArr: Object.values(salonGroupMap),
    config,
  };
}

// ── 子标签获取 ────────────────────────────────────────────────
function getSubTabs(mainTabId) {
  if (!state.data) return [];
  return state.data.tabArr
    .filter(t => t.fathertab === String(mainTabId))
    .sort((a, b) => (a.subrank_value ?? 99) - (b.subrank_value ?? 99));
}

// gender=3 表示双性通用（包挂饰、法杖等），对 PC1 和 PC2 都显示
function matchGender(itemGender, gender) {
  return itemGender === gender || itemGender === 3;
}

// ── 物品过滤 ──────────────────────────────────────────────────
function getItems() {
  const { itemArr, suitArr, salonGroupArr, tabs } = state.data;
  const gender = state.gender;
  const search = state.search.trim().toLowerCase();

  let results = [];
  let source  = 'items';

  const leafId = state.subTab ?? state.mainTab;
  const tab    = leafId ? tabs[String(leafId)] : null;

  if (state.mainTab === 1) {
    // ── 套装 ──
    source  = 'suits';
    results = suitArr.filter(s => s.gender === gender);

  } else if (tab) {
    const flType = tab.use_FashionLabelType;
    const slType = tab.use_SalonLabelType;

    if (slType !== undefined && slType >= 0) {
      // ── 发型 / 妆容子类（有明确 use_SalonLabelType）──
      source  = 'salon';
      results = salonGroupArr.filter(g => matchGender(g.gender, gender) && g.type === slType);

    } else if (leafId === 17) {
      // ── 肤色 tab：type=undefined、gender=3 的特殊 salon 项 ──
      source  = 'salon';
      results = salonGroupArr.filter(g => !g.type);

    } else if (flType !== undefined && flType >= 0) {
      // ── 服装单品（type 字段匹配）──
      source  = 'items';
      results = itemArr.filter(i => matchGender(i.gender, gender) && i.type === flType);

    } else if (state.mainTab === 15) {
      // ── 发型一级 tab ──
      source  = 'salon';
      results = salonGroupArr.filter(g => matchGender(g.gender, gender) && g.type === 1);

    } else if (state.mainTab === 16) {
      // ── 妆容一级 tab（无子 tab 选中时）──
      source  = 'salon';
      results = salonGroupArr.filter(g => matchGender(g.gender, gender) && g.type >= 2);

    } else if (TAB_TYPENAME_FALLBACK[leafId]) {
      // ── type_name 回退（如 上装 tab）──
      // 排除有数字 type 的物品（它们归属于其他 flType tab，如连体服 type=2）
      const typeName = TAB_TYPENAME_FALLBACK[leafId];
      source  = 'items';
      results = itemArr.filter(i => matchGender(i.gender, gender) && i.type_name === typeName && i.type === undefined);

    } else {
      // ── 父级 tab（衣服/装饰）—— 聚合所有子类 ──
      const childFLTypes = state.data.tabArr
        .filter(t => t.fathertab === String(leafId) && t.use_FashionLabelType >= 0)
        .map(t => t.use_FashionLabelType);
      source  = 'items';
      results = itemArr.filter(i => matchGender(i.gender, gender) && childFLTypes.includes(i.type));
    }
  }

  // 文本搜索（salon 组使用 avatar_id，其余使用 id）
  if (search) {
    results = results.filter(r => {
      const name = (r.name || r.editor_name || '').toLowerCase();
      const id   = String(r.avatar_id ?? r.id);
      return name.includes(search) || id.includes(search);
    });
  }

  return { results, source };
}

// ── 渲染：一级侧边栏 ──────────────────────────────────────────
function renderSidebar() {
  const sidebar = document.getElementById('sidebar');
  const tabChanged = _renderedMainTab !== state.mainTab;

  if (sidebar.childElementCount === MAIN_TABS.length && !tabChanged) return;

  // 首次构建，或 tab 数量不对时重建；否则只更新 active 类
  if (sidebar.childElementCount !== MAIN_TABS.length) {
    sidebar.innerHTML = '';
    for (const def of MAIN_TABS) {
      const tabConf = state.data?.tabs[String(def.id)];
      const iconSrc = tabConf?.icon ? frameUrl(tabConf.icon) : null;

      const btn = document.createElement('div');
      btn.className = 'main-tab';
      btn.dataset.id = def.id;

      if (iconSrc) {
        const img = document.createElement('img');
        img.src   = iconSrc;
        img.alt   = def.label;
        img.onerror = () => img.replaceWith(makeTabEmoji(def.label));
        btn.appendChild(img);
      } else {
        btn.appendChild(makeTabEmoji(def.label));
      }

      const label = document.createElement('span');
      label.className   = 'main-tab-label';
      label.textContent = def.label;
      btn.appendChild(label);

      btn.addEventListener('click', () => onMainTabClick(def.id));
      sidebar.appendChild(btn);
    }
  }

  // 只更新 active 类，不重建 DOM
  sidebar.querySelectorAll('.main-tab').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.id) === state.mainTab);
  });
}

function makeTabEmoji(label) {
  const MAP = {
    '套装': '👗',
    '衣服': '👕',
    '装饰': '💍',
    '法杖': '☸️',
    '发型': '💇',
    '妆容': '💄',
    '上衣': '👕',
    '上装': '👕',
    '下装': '👖',
    '裤子': '👖',
    '袜子': '🧦',
    '鞋子': '👟',
    '帽子': '🎩',
    '头饰': '🎀',
    '面饰': '😷',
    '手饰': '🧤',
    '背包': '🎒',
    '包挂饰': '🔖',
    '眉毛': '〰️',
    '睫毛': '👁️',
    '瞳孔': '👁️',
    '贴花': '✦',
    '肤色': '🎨',
  };
  const span = document.createElement('span');
  span.style.fontSize = '22px';
  span.textContent = MAP[label] || '📦';
  return span;
}

// ── 渲染：二级 Tab 横排 ───────────────────────────────────────
function renderSubTabs() {
  const bar = document.getElementById('subtabs');
  const tabChanged = _renderedMainTab !== state.mainTab;

  // mainTab 没变时只更新 active 类
  if (!tabChanged && bar.childElementCount > 0) {
    bar.querySelectorAll('.sub-tab').forEach(el => {
      el.classList.toggle('active', Number(el.dataset.id) === state.subTab);
    });
    return;
  }

  bar.innerHTML = '';
  const children = getSubTabs(state.mainTab);
  if (children.length === 0) return;

  for (const t of children) {
    const iconSrc = t.icon ? frameUrl(t.icon) : null;
    const label = subTabLabel(t);

    const btn = document.createElement('div');
    btn.className = 'sub-tab' + (state.subTab === t.id ? ' active' : '');
    btn.dataset.id = t.id;

    if (iconSrc) {
      const img = document.createElement('img');
      img.src     = iconSrc;
      img.alt     = label;
      img.onerror = () => img.replaceWith(makeTabEmoji(label));
      btn.appendChild(img);
    }

    btn.appendChild(document.createTextNode(label));
    btn.addEventListener('click', () => onSubTabClick(t.id));
    bar.appendChild(btn);
  }
}

// 数据表的 tabname 字段存在缺失/错位，按标签内容类型给出正确显示名
const SUBTAB_LABEL_BY_ID = { '5': '上衣', '17': '肤色' };
const SUBTAB_LABEL_BY_FL = {
  '1': '下装', '2': '连衣/玩偶服', '3': '袜子', '4': '鞋子',
  '5': '帽子/头饰', '6': '面饰', '9': '手饰', '10': '背包', '14': '包挂饰',
};
const SUBTAB_LABEL_BY_SL = { '1': '发型', '2': '眉毛', '3': '睫毛', '4': '瞳孔', '5': '贴花' };
function subTabLabel(t) {
  if (SUBTAB_LABEL_BY_ID[String(t.id)] !== undefined) return SUBTAB_LABEL_BY_ID[String(t.id)];
  const sl = Number(t.use_SalonLabelType);
  if (Number.isFinite(sl) && sl >= 0 && SUBTAB_LABEL_BY_SL[String(sl)] !== undefined) return SUBTAB_LABEL_BY_SL[String(sl)];
  const fl = Number(t.use_FashionLabelType);
  if (Number.isFinite(fl) && fl >= 0 && SUBTAB_LABEL_BY_FL[String(fl)] !== undefined) return SUBTAB_LABEL_BY_FL[String(fl)];
  return t.tabname || '';
}

// ── 渲染：物品网格 ────────────────────────────────────────────
function renderGrid() {
  const grid  = document.getElementById('grid');
  const empty = document.getElementById('grid-empty');
  grid.innerHTML = '';

  const { results, source } = getItems();

  if (results.length === 0) {
    grid.classList.add('hidden');
    empty.classList.remove('hidden');
    return;
  }
  grid.classList.remove('hidden');
  empty.classList.add('hidden');

  const fragment = document.createDocumentFragment();
  for (const item of results) {
    let card;
    if (source === 'suits')      card = makeSuitCard(item);
    else if (source === 'salon') card = makeSalonCard(item);
    else                         card = makeItemCard(item, source);
    fragment.appendChild(card);
  }
  grid.appendChild(fragment);
}

// 只更新网格中卡片的选中状态（不重建 DOM）
function updateGridSelection() {
  document.querySelectorAll('#grid .item-card').forEach(card => {
    const slot = card.dataset.slot;
    const id   = Number(card.dataset.itemId);
    card.classList.toggle('selected', state.selected[slot]?.item.id === id);
  });
  document.querySelectorAll('#grid .suit-card').forEach(card => {
    const id = Number(card.dataset.itemId);
    card.classList.toggle('selected', state.selectedSuitId === id);
  });
  document.querySelectorAll('#grid .salon-card').forEach(card => {
    const avatarId = Number(card.dataset.avatarId);
    const slot     = card.dataset.slot;
    // 高亮：颜色条打开 或 该组有变体被选中
    const isActive   = state.activeColorGroup === avatarId;
    const isSelected = state.selected[slot]?.item.avatar_id === avatarId;
    card.classList.toggle('active',   isActive);
    card.classList.toggle('selected', isSelected && !isActive);
  });
}

// ── 卡片：服装单品 ────────────────────────────────────────────
function getEquipmentSlot(item) {
  const slots = { '连衣': '上衣', '玩偶服': '上衣', '头套': '帽子', '口罩': '面饰' };
  return slots[item.type_name] || item.type_name || 'unknown';
}

function isFullBodyItem(item) {
  return !!item && (item.type === 2 || item.type_name === '连衣' || item.type_name === '玩偶服');
}

function makeItemCard(item, source) {
  const slot = source === 'salon' ? `salon_${item.type}` : getEquipmentSlot(item);
  const isSelected = state.selected[slot]?.item.id === item.id;

  const card = document.createElement('div');
  card.className      = 'item-card' + (isSelected ? ' selected' : '');
  card.dataset.slot   = slot;
  card.dataset.itemId = item.id;

  if (item.item_quality) {
    const dot = document.createElement('span');
    dot.className = `item-quality quality-${item.item_quality}`;
    card.appendChild(dot);
  }

  const thumbUrl = iconUrl(item.icon);
  if (thumbUrl) {
    const img = document.createElement('img');
    img.className = 'item-thumb';
    img.src       = thumbUrl;
    img.alt       = item.name;
    img.onerror   = () => img.replaceWith(makePlaceholder(slot));
    card.appendChild(img);
  } else {
    card.appendChild(makePlaceholder(slot));
  }

  const name = document.createElement('div');
  name.className   = 'item-name';
  name.textContent = item.name || item.editor_name || '—';
  card.appendChild(name);

  const idBadge = document.createElement('div');
  idBadge.className   = 'item-id';
  idBadge.textContent = item.id;
  card.appendChild(idBadge);

  const unreleased = unreleasedInfo(item);
  if (unreleased) {
    const badge = document.createElement('span');
    badge.className   = 'item-unreleased';
    badge.textContent = '游戏未实装';
    badge.title       = '游戏内只有材质贴图，没有网格模型，因此无法预览外观';
    card.appendChild(badge);
  }

  card.addEventListener('click', () => onItemClick(item, slot, source));
  return card;
}

// ── 卡片：套装 ────────────────────────────────────────────────
function makeSuitCard(suit) {
  const isSelected = state.selectedSuitId === suit.id;

  const card = document.createElement('div');
  card.className      = 'suit-card' + (isSelected ? ' selected' : '');
  card.dataset.itemId = suit.id;

  const thumb = suitThumbUrls(suit);
  if (thumb.primary) {
    const img = document.createElement('img');
    img.className = 'suit-thumb';
    img.src       = thumb.primary;
    img.alt       = suit.name;
    img.onerror   = () => {
      if (thumb.fallback && !img.dataset.fallbackApplied) {
        img.dataset.fallbackApplied = '1';
        img.src = thumb.fallback;
        return;
      }
      img.replaceWith(makeSuitPlaceholder());
    };
    card.appendChild(img);
  } else {
    card.appendChild(makeSuitPlaceholder());
  }

  const info = document.createElement('div');
  info.className = 'suit-info';

  const nameEl = document.createElement('div');
  nameEl.className   = 'suit-name';
  nameEl.textContent = suit.name || '—';
  info.appendChild(nameEl);

  const meta = document.createElement('div');
  meta.className   = 'suit-meta';
  meta.textContent = `${(suit.item_id || []).length} 件  ·  ID ${suit.id}`;
  info.appendChild(meta);

  card.appendChild(info);
  card.addEventListener('click', () => onSuitClick(suit));
  return card;
}

// ── 卡片：发型 / 妆容组 ──────────────────────────────────────
function makeSalonCard(group) {
  const slot      = `salon_${group.type}`;
  const avatarId  = group.avatar_id;
  const isActive  = state.activeColorGroup === avatarId;
  const isSelected = state.selected[slot]?.item.avatar_id === avatarId;

  const card = document.createElement('div');
  card.className       = 'item-card salon-card'
                       + (isActive ? ' active' : '')
                       + (isSelected && !isActive ? ' selected' : '');
  card.dataset.avatarId = avatarId;
  card.dataset.slot     = slot;

  if (group.item_quality) {
    const dot = document.createElement('span');
    dot.className = `item-quality quality-${group.item_quality}`;
    card.appendChild(dot);
  }

  const thumbUrl = iconUrl(group.icon);
  if (thumbUrl) {
    const img = document.createElement('img');
    img.className = 'item-thumb';
    img.src       = thumbUrl;
    img.alt       = group.name;
    img.onerror   = () => img.replaceWith(makePlaceholder(slot));
    card.appendChild(img);
  } else {
    card.appendChild(makePlaceholder(slot));
  }

  // 颜色点徽章（最多显示 6 个，超出用 +N）
  if (group.variants.length > 1) {
    const badge = document.createElement('div');
    badge.className = 'salon-color-badge';
    const shown = Math.min(group.variants.length, 6);
    for (let i = 0; i < shown; i++) {
      const v   = group.variants[i];
      const dot = document.createElement('span');
      dot.className        = 'salon-color-dot';
      dot.style.background = v.colour_id?.[0] || '#888';
      badge.appendChild(dot);
    }
    if (group.variants.length > 6) {
      const more = document.createElement('span');
      more.style.cssText  = 'font-size:9px;color:var(--text-mute);line-height:7px;';
      more.textContent    = `+${group.variants.length - 6}`;
      badge.appendChild(more);
    }
    card.appendChild(badge);
  }

  const name = document.createElement('div');
  name.className   = 'item-name';
  name.textContent = group.name || '—';
  card.appendChild(name);

  const idBadge = document.createElement('div');
  idBadge.className   = 'item-id';
  idBadge.textContent = avatarId;
  card.appendChild(idBadge);

  card.addEventListener('click', () => onSalonCardClick(group));
  return card;
}

// ── 渲染：颜色选择条（三级菜单）────────────────────────────
function renderColorPicker() {
  const bar      = document.getElementById('colorpicker');
  const label    = document.getElementById('colorpicker-label');
  const swatches = document.getElementById('colorpicker-swatches');

  if (!state.activeColorGroup) {
    bar.classList.add('hidden');
    return;
  }

  const group = state.data.salonGroupMap[state.activeColorGroup];
  if (!group) { bar.classList.add('hidden'); return; }

  const slot          = `salon_${group.type}`;
  const selectedId    = state.selected[slot]?.item.id;

  bar.classList.remove('hidden');
  label.textContent = `${group.name}  ·  ${group.variants.length} 色`;
  swatches.innerHTML = '';

  for (const v of group.variants) {
    const opt = document.createElement('div');
    opt.className = 'color-option' + (v.id === selectedId ? ' active' : '');

    // 颜色圆
    const circle = document.createElement('div');
    circle.className = 'swatch-circle' + (v.colour_id?.length >= 2 ? ' dual' : '');
    if (v.colour_id?.length >= 2) {
      circle.style.setProperty('--c1', v.colour_id[0]);
      circle.style.setProperty('--c2', v.colour_id[1]);
    } else {
      circle.style.background = v.colour_id?.[0] || '#888';
    }
    opt.appendChild(circle);

    // 编号
    const idx = document.createElement('div');
    idx.className   = 'swatch-idx';
    idx.textContent = v.texture_id ?? v.id;
    opt.appendChild(idx);

    opt.addEventListener('click', () => onColorSelect(group, v));
    swatches.appendChild(opt);
  }
}

function placeholderEmoji(slot) {
  const map = {
    '上衣': '👕',
    '下装': '👖',
    '袜子': '🧦',
    '鞋子': '👟',
    '帽子': '🎩',
    '头饰': '🎀',
    '面饰': '😷',
    '手饰': '🧤',
    '背包': '🎒',
    '包挂饰': '🔖',
    '法杖': '🪄',
    'salon_1': '💇',
    'salon_2': '〰️',
    'salon_3': '👁️',
    'salon_4': '👁️',
    'salon_5': '✦',
    'salon_undefined': '🎨',
  };
  return map[slot] || '□';
}

function makeSlotThumbPlaceholder(slot) {
  const div = document.createElement('div');
  div.className = 'slot-thumb';
  div.textContent = placeholderEmoji(slot);
  return div;
}

function makePlaceholder(slot) {
  const div = document.createElement('div');
  div.className   = 'item-thumb-placeholder';
  div.textContent = placeholderEmoji(slot);
  return div;
}
function makeSuitPlaceholder() {
  const div = document.createElement('div');
  div.className   = 'suit-thumb-placeholder';
  div.textContent = '👗';
  return div;
}

function updateSlotGridLayout() {
  document.querySelectorAll('.slot-grid').forEach(grid => {
    grid.style.setProperty('--slot-columns', 2);
  });
}

function applyCardSize(value) {
  const size = Math.max(80, Math.min(200, Number(value) || 100));
  const root = document.documentElement;
  root.style.setProperty('--card-min', `${size}px`);
  root.style.setProperty('--card-img', `${Math.round(size * 0.8)}px`);
  const slider = document.getElementById('card-size-slider');
  if (slider) slider.value = String(size);
  updateSlotGridLayout();
}

async function loadUiPreferences() {
  let prefs = {};
  try { prefs = await fetch('/api/prefs').then(r => r.json()); } catch { /* ignore */ }

  if (prefs.cardSize) applyCardSize(prefs.cardSize);
  if (prefs.panelWidth) document.documentElement.style.setProperty('--panel-w', prefs.panelWidth);
  if (prefs.selectedPanelHeight) document.documentElement.style.setProperty('--selected-panel-h', prefs.selectedPanelHeight);
}

function saveUiPref(key, value) {
  fetch('/api/prefs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [key]: value }),
  }).catch(() => {});
}

function initSlotGridAutoLayout() {
  const panel = document.getElementById('selected-panel');
  if (!panel) return;
  if (window.ResizeObserver) {
    new ResizeObserver(updateSlotGridLayout).observe(panel);
  } else {
    window.addEventListener('resize', updateSlotGridLayout);
  }
}

// ── 渲染：已选面板（固定槽位网格）────────────────────────────
function renderSelectedPanel() {
  const list = document.getElementById('selected-list');
  list.innerHTML = '';

  let lastGroup = null;
  let grid = null;

  for (const slotDef of SLOTS) {
    const hasJumpsuit = isFullBodyItem(state.selected['上衣']?.item);
    if (slotDef.key === '下装' && hasJumpsuit) continue;

    // 分组标题
    if (slotDef.group !== lastGroup) {
      const sec = document.createElement('div');
      sec.className   = 'slot-section-label';
      sec.textContent = slotDef.group === 'fashion' ? '服装' : '妆容';
      list.appendChild(sec);

      grid = document.createElement('div');
      grid.className = 'slot-grid';
      list.appendChild(grid);

      lastGroup = slotDef.group;
    }

    const sel    = state.selected[slotDef.key];
    const filled = !!sel;
    const isJumpsuitCard = slotDef.key === '上衣' && isFullBodyItem(sel?.item);

    const card = document.createElement('div');
    card.className    = `slot-card ${slotDef.required ? 'required' : 'optional'} ${filled ? 'filled' : 'empty'}${isJumpsuitCard ? ' jumpsuit' : ''}`;
    card.dataset.slot = slotDef.key;

    if (filled) {
      const { item, source } = sel;
      const thumbUrl = source === 'suits' ? suitThumbUrls(item).primary : iconUrl(item.icon);

      if (thumbUrl) {
        const img     = document.createElement('img');
        img.className = 'slot-thumb';
        img.src       = thumbUrl;
        img.alt       = item.name || '';
        const suitFallback = source === 'suits' ? suitThumbUrls(item).fallback : null;
        img.onerror   = () => {
          if (suitFallback && !img.dataset.fallbackApplied) {
            img.dataset.fallbackApplied = '1';
            img.src = suitFallback;
            return;
          }
          img.replaceWith(makeSlotThumbPlaceholder(slotDef.key));
        };
        card.appendChild(img);
      } else {
        card.appendChild(makeSlotThumbPlaceholder(slotDef.key));
      }

      const info = document.createElement('div');
      info.className = 'slot-info';

      const labelEl = document.createElement('div');
      labelEl.className   = 'slot-label';
      labelEl.textContent = isJumpsuitCard ? '连体服' : slotDef.label;
      info.appendChild(labelEl);

      const nameEl = document.createElement('div');
      nameEl.className   = 'slot-name';
      nameEl.textContent = item.name || item.editor_name || '—';
      info.appendChild(nameEl);

      const idEl = document.createElement('div');
      idEl.className   = 'slot-id';
      idEl.textContent = item.id;
      idEl.title       = '点击复制 ID';
      idEl.addEventListener('click', e => {
        e.stopPropagation();
        navigator.clipboard.writeText(String(item.id));
        idEl.classList.add('copied');
        idEl.textContent = '已复制!';
        setTimeout(() => { idEl.classList.remove('copied'); idEl.textContent = item.id; }, 1200);
      });
      info.appendChild(idEl);

      card.appendChild(info);

      const rmBtn = document.createElement('button');
      rmBtn.className   = 'slot-remove';
      rmBtn.textContent = '×';
      rmBtn.title       = '取消选中';
      rmBtn.addEventListener('click', e => {
        e.stopPropagation();
        delete state.selected[slotDef.key];
        applyDefaults();
        updateGridSelection();
        renderSelectedPanel();
        syncPreview();
      });
      card.appendChild(rmBtn);

    } else {
      const labelEl = document.createElement('span');
      labelEl.className   = 'slot-label';
      labelEl.textContent = slotDef.label;
      card.appendChild(labelEl);
    }

    grid.appendChild(card);
  }

  updateSlotGridLayout();
}

function salonTypeName(type) {
  return { 1: '发型', 2: '眉毛', 3: '睫毛', 4: '瞳孔', 5: '贴花' }[type] || '妆容';
}

function getPreviewSelectionSignature() {
  const selected = Object.entries(state.selected || {})
    .map(([slot, value]) => {
      const item = value?.item || {};
      return [
        slot,
        value?.source || '',
        item.id ?? null,
        item.avatar_id ?? null,
        item.texture_id ?? null,
        item.type ?? null,
        item.type_name ?? null,
      ];
    })
    .sort((a, b) => a[0].localeCompare(b[0]));
  return JSON.stringify({ gender: state.gender, selected });
}

// 通知 3D 预览模块刷新（preview.js 加载后挂载到 window.updatePreview）
function syncPreview() {
  const signature = getPreviewSelectionSignature();
  if (signature === _lastPreviewSignature) return;
  _lastPreviewSignature = signature;
  window.updatePreview?.(state.selected, state.gender);
}

// ── 事件处理 ──────────────────────────────────────────────────
function onMainTabClick(id) {
  if (state.mainTab === id) return;
  state.mainTab = id;
  state.activeColorGroup = null;
  const children = getSubTabs(id);
  state.subTab = children.length ? children[0].id : null;
  render();
}

function onSubTabClick(id) {
  if (state.subTab === id) return;
  state.subTab = id;
  state.activeColorGroup = null;
  renderSubTabs();
  renderGrid();
  renderColorPicker();
  renderSelectedPanel();
  _renderedSubTab = id;
}

// ── 冲突规则 ──────────────────────────────────────────────────
// 连体服（上衣 type=2）与上装/下装互斥：
//   选连体服 → 清下装；选下装 → 如果已选的是连体服则清掉
function applyConflictRules(slot, item) {
  if (slot === '上衣' && isFullBodyItem(item)) {
    // 选了连体服，清掉下装
    delete state.selected['下装'];
  }
  if (slot === '下装' && isFullBodyItem(state.selected['上衣']?.item)) {
    // 选了下装，已有连体服 → 清掉连体服
    delete state.selected['上衣'];
  }
  if (slot === '帽子') {
    // 帽子和头饰互斥
    delete state.selected['头饰'];
  }
  if (slot === '头饰') {
    // 头饰和帽子互斥
    delete state.selected['帽子'];
  }
}

function onItemClick(item, slot, source) {
  if (state.selected[slot]?.item.id === item.id) {
    delete state.selected[slot];
    applyDefaults();
  } else {
    const exitsJumpsuit = isFullBodyItem(state.selected['上衣']?.item)
      && ((slot === '上衣' && !isFullBodyItem(item)) || slot === '下装');
    applyConflictRules(slot, item);
    state.selected[slot] = { item, source };
    if (exitsJumpsuit) applyDefaults();
  }
  // 手动改了单品，清除套装高亮
  state.selectedSuitId = null;
  updateGridSelection();
  renderSelectedPanel();
  syncPreview();
}

// ── 套装选择 ──────────────────────────────────────────────────
function getSuitItems(suit) {
  return (suit.item_id || [])
    .map(id => state.data.itemById[id])
    .filter(Boolean);
}

// 少数套装记录里同时写着男/女两套部件（如 274 异色玳塔印象、194 捕尘长绒印象）。
// 之前按顺序写入同一个槽位，后写的女款会盖掉男款，男角色就整件消失。
// 这里按当前性别挑出可用部件；若没有一件与当前性别相符，才退回原列表。
// 数据里同一套装按性别拆成两条同名记录，个别部件被登记在另一条记录上
// （男款「异色玳塔印象」的帽子 11308702、「捕尘长绒印象」的头饰 12106901
//  都记在同名的女款记录里），因此空缺槽位再用同名记录中同性别部件补齐。
function suitSiblingItems(suit, gender) {
  const suits = state.data?.suitArr || [];
  const items = state.data?.itemArr || [];
  const siblingIds = new Set(suits
    .filter(other => other.name === suit.name && String(other.id) !== String(suit.id))
    .map(other => String(other.id)));
  if (!siblingIds.size) return [];
  return items.filter(item => siblingIds.has(String(item.suits_id)) && item.gender === gender);
}

function getSuitItemsForGender(suit, gender) {
  const items = getSuitItems(suit);
  const matching = items.filter(item => !item.gender || matchGender(item.gender, gender));
  const usable = matching.length ? matching : items;
  const bySlot = new Map();
  for (const item of usable) bySlot.set(getEquipmentSlot(item), item);
  for (const item of suitSiblingItems(suit, gender)) {
    const slot = getEquipmentSlot(item);
    if (!bySlot.has(slot)) bySlot.set(slot, item);
  }
  return [...bySlot.values()];
}

function onSuitClick(suit) {
  if (state.selectedSuitId === suit.id) {
    // 再次点击同一套装 → 取消全部组件，必选槽恢复默认
    getSuitItemsForGender(suit, state.gender).forEach(item => {
      const slot = getEquipmentSlot(item);
      if (state.selected[slot]?.item.id === item.id)
        delete state.selected[slot];
    });
    state.selectedSuitId = null;
    applyDefaults();
  } else {
    // 选中新套装 → 清空后展开组件，必选槽补默认值
    state.selected = {};
    getSuitItemsForGender(suit, state.gender).forEach(item => {
      const slot = getEquipmentSlot(item);
      applyConflictRules(slot, item);
      state.selected[slot] = { item, source: 'items' };
    });
    state.selectedSuitId = suit.id;
    applyDefaults();
  }
  updateGridSelection();
  renderSelectedPanel();
  syncPreview();
}

// 点击 salon 组卡片
function onSalonCardClick(group) {
  const avatarId = group.avatar_id;

  if (group.variants.length === 1) {
    // 单色：直接选中 / 取消
    const slot    = `salon_${group.type}`;
    const variant = group.variants[0];
    if (state.selected[slot]?.item.id === variant.id) {
      delete state.selected[slot];
      state.activeColorGroup = null;
      applyDefaults();
    } else {
      state.selected[slot] = { item: variant, source: 'salon' };
      state.activeColorGroup = null;
    }
    updateGridSelection();
    renderSelectedPanel();
    renderColorPicker();
    syncPreview();
    return;
  }

  // 多色：先选中该组的第一个颜色，再打开颜色条继续细选。
  let selectionChanged = false;
  const slot = `salon_${group.type}`;
  if (state.activeColorGroup === avatarId) {
    // 再次点击同一组 → 关闭颜色条并取消选中
    state.activeColorGroup = null;
    delete state.selected[slot];
    applyDefaults();
    selectionChanged = true;
  } else {
    const selectedItem = state.selected[slot]?.item;
    if (selectedItem?.avatar_id !== avatarId) {
      state.selected[slot] = { item: group.variants[0], source: 'salon' };
      selectionChanged = true;
    }
    state.activeColorGroup = avatarId;
  }
  updateGridSelection();
  renderSelectedPanel();
  renderColorPicker();
  if (selectionChanged) syncPreview();
}

// 在颜色条中选择一个变体
function onColorSelect(group, variant) {
  const slot = `salon_${group.type}`;
  if (state.selected[slot]?.item.id === variant.id) {
    // 再次点击同一色 → 取消并关闭
    delete state.selected[slot];
    state.activeColorGroup = null;
    applyDefaults();
  } else {
    state.selected[slot] = { item: variant, source: 'salon' };
  }
  updateGridSelection();
  renderSelectedPanel();
  renderColorPicker();
  syncPreview();
}

// ── 默认填充（启动时预选必要槽位）──────────────────────────
function applyDefaults() {
  const { salonGroupArr } = state.data;
  const gender = state.gender;

  // 服装必选槽（fallback 模型 ID，不在目录中，作为导出占位符）
  const hasJumpsuit = isFullBodyItem(state.selected['上衣']?.item);
  const fashionDefaults = gender === 1
    ? [
        { slot: '上衣', id: 10700001, name: '默认上衣', type_name: '上衣' },
        { slot: '下装', id: 10900001, name: '默认下装', type_name: '下装' },
        { slot: '袜子', id: 11000001, name: '默认袜子', type_name: '袜子' },
        { slot: '手饰', id: 10800001, name: '默认手饰', type_name: '手饰' },
      ]
    : [
        { slot: '上衣', id: 20700001, name: '默认上衣', type_name: '上衣' },
        { slot: '下装', id: 20900001, name: '默认下装', type_name: '下装' },
        { slot: '袜子', id: 21000001, name: '默认袜子', type_name: '袜子' },
        { slot: '手饰', id: 20800001, name: '默认手饰', type_name: '手饰' },
      ];
  for (const { slot, id, name, type_name } of fashionDefaults) {
    // 已选连体服时跳过下装默认值
    if (slot === '下装' && hasJumpsuit) continue;
    if (!state.selected[slot])
      state.selected[slot] = { item: { id, name, type_name }, source: 'items' };
  }

  // salon 必选槽：取各类型首个符合性别的变体
  const salonTypes = [1, 2, 3, 4, 5, undefined];
  for (const type of salonTypes) {
    const slot = `salon_${type}`;
    if (state.selected[slot]) continue;
    const groups = type !== undefined
      ? salonGroupArr.filter(g => matchGender(g.gender, gender) && g.type === type)
      : salonGroupArr.filter(g => !g.type);
    if (groups.length && groups[0].variants.length)
      state.selected[slot] = { item: groups[0].variants[0], source: 'salon' };
  }
}

// ── 导出 JSON ──────────────────────────────────────────────────
function getSlotDef(slot) {
  return SLOTS.find(def => def.key === slot) || null;
}

function getSelectedEntries() {
  const orderedSlots = [
    ...SLOTS.map(def => def.key),
    ...Object.keys(state.selected).filter(slot => !SLOTS.some(def => def.key === slot)),
  ];
  return [...new Set(orderedSlots)]
    .map(slot => {
      const sel = state.selected[slot];
      if (!sel) return null;
      const item = sel.item || {};
      const slotDef = getSlotDef(slot);
      return {
        slot,
        label: slotDef?.label || (sel.source === 'salon' ? salonTypeName(item.type) : (item.type_name || slot)),
        group: slotDef?.group || null,
        required: !!slotDef?.required,
        source: sel.source,
        resourceKey: `slot:${slot}`,
        item: {
          id: item.id ?? null,
          avatar_id: item.avatar_id ?? null,
          texture_id: item.texture_id ?? null,
          colour_id: item.colour_id || [],
          type: item.type ?? null,
          type_name: item.type_name ?? null,
          name: item.name || item.editor_name || null,
        },
      };
    })
    .filter(Boolean);
}

const PC_ASSET_REL_ROOT = 'NRC/Content/ArtRes/AnimSequence/Human/PC';

function toSlashPath(path) {
  return String(path || '').replace(/\\/g, '/');
}

function stripTrailingSlash(path) {
  return String(path || '').replace(/[\\/]+$/, '');
}

function getExtractedRoot(kind) {
  const modelRoot = toSlashPath(state.data?.config?.modelRoot || '');
  const marker = `/${PC_ASSET_REL_ROOT}`;
  const index = modelRoot.indexOf(marker);
  const ueRoot = index >= 0 ? modelRoot.slice(0, index) : stripTrailingSlash(modelRoot);
  return kind === 'metadata'
    ? ueRoot.replace(/UEViewer Outputs$/i, 'FModel Outputs')
    : ueRoot;
}

function modelUrlToAssetRelativePath(url) {
  if (typeof url !== 'string' || !url.startsWith('/models/')) return null;
  const relativeToPc = decodeURIComponent(url.split('?')[0].replace(/^\/models\/?/, ''));
  return `${PC_ASSET_REL_ROOT}/${relativeToPc}`;
}

function metadataPathForAsset(assetPath) {
  return assetPath ? assetPath.replace(/\.[^.\/]+$/, '.json') : null;
}

function folderFromAssetPath(assetPath) {
  const parts = String(assetPath || '').split('/');
  const avatarIndex = parts.indexOf('Avatar');
  if (avatarIndex >= 0 && parts[avatarIndex + 1]) return parts[avatarIndex + 1];
  const pcIndex = parts.findIndex(part => /^PC\d$/.test(part));
  if (pcIndex >= 0 && parts[pcIndex + 1] && parts[pcIndex + 1] !== 'Avatar') return parts[pcIndex + 1];
  return null;
}

function modelDirFromAssetPath(assetPath) {
  return assetPath ? assetPath.slice(0, assetPath.lastIndexOf('/')) : null;
}

function textureSetFromUrl(url, usage) {
  const assetPath = modelUrlToAssetRelativePath(url);
  if (!assetPath) return [];
  const rows = [];
  const add = (type, path) => rows.push({
    type,
    usage,
    file: path,
    metadata: metadataPathForAsset(path),
  });

  if (/_D\.png$/i.test(assetPath)) {
    add('D', assetPath);
    add('M', assetPath.replace(/_D\.png$/i, '_M.png'));
    add('ID', assetPath.replace(/_D\.png$/i, '_ID.png'));
  } else {
    add(usage || 'texture', assetPath);
  }
  return rows;
}

function collectAssetTextures(part) {
  const textures = [];
  const seen = new Set();
  const addSet = (url, usage) => {
    for (const texture of textureSetFromUrl(url, usage)) {
      const key = `${texture.type}|${texture.usage}|${texture.file}`;
      if (seen.has(key)) continue;
      seen.add(key);
      textures.push(texture);
    }
  };

  for (const row of part.loadedMaterials || []) {
    addSet(row.baseTexture?.url, 'baseColor');
    addSet(row.overlayTexture?.url, 'overlay');
  }

  if (!textures.length) {
    for (const entry of part.manualTextures || []) {
      for (const candidate of entry.candidates || []) {
        addSet(candidate.url, 'baseColor');
        addSet(candidate.overlay?.url, 'overlay');
      }
    }
  }

  return textures;
}

function collectMaterialConfigs(part, modelPath) {
  const modelDir = modelDirFromAssetPath(modelPath);
  if (!modelDir) return [];
  const rows = [];
  const seen = new Set();
  const add = materialName => {
    if (!materialName || seen.has(materialName)) return;
    seen.add(materialName);
    rows.push({
      name: materialName,
      metadata: `${modelDir}/Mat/${materialName}.json`,
    });
  };

  for (const row of part.loadedMaterials || []) add(row.material);
  return rows;
}

function buildAssetBundleEntry(part) {
  const modelPath = modelUrlToAssetRelativePath(part.model?.loadedUrl || part.model?.primaryUrl);
  if (!modelPath) return null;
  const folder = part.model?.folder || folderFromAssetPath(modelPath);
  const category = folder || 'misc';
  return {
    category,
    model: modelPath,
    textures: collectAssetTextures(part),
    materials: collectMaterialConfigs(part, modelPath),
  };
}

function buildExportJson() {
  const previewManifest = window.buildPreviewManifest?.(state.selected, state.gender) || null;
  const grouped = {};
  for (const part of previewManifest?.parts || []) {
    const entry = buildAssetBundleEntry(part);
    if (!entry) continue;
    const { category, ...asset } = entry;
    if (!grouped[category]) grouped[category] = [];
    grouped[category].push(asset);
  }

  const skeleton = previewManifest?.masterSkeleton?.url
    ? modelUrlToAssetRelativePath(previewManifest.masterSkeleton.url)
    : null;

  return {
    roots: {
      assets: getExtractedRoot('assets'),
      metadata: getExtractedRoot('metadata'),
    },
    skeleton,
    parts: grouped,
  };
}
function downloadJson() {
  const json = JSON.stringify(buildExportJson(), null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `NRC_outfit_PC${state.gender}_${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── MMD 导出（POST /api/mmd/export，由本地 Blender 生成 PMX）─────
let mmdPollTimer = null;

function mmdSelectedItems() {
  const ids = [];
  for (const entry of Object.values(state.selected)) {
    const id = entry?.item?.id;
    if (id == null) continue;
    if (!ids.includes(String(id))) ids.push(String(id));
  }
  return ids;
}

function buildMmdName(items) {
  const names = [];
  for (const entry of Object.values(state.selected)) {
    const id = entry?.item?.id;
    if (id == null || !items.includes(String(id))) continue;
    const name = String(entry.item.name || '').trim();
    if (name && !names.includes(name)) names.push(name);
  }
  const base = names.length ? names.join('_') : items.join('_');
  return `PC${state.gender}-${base || Date.now()}`;
}

function setMmdStatus(message, type = '', path = null) {
  const box = document.getElementById('mmd-status');
  const text = document.getElementById('mmd-status-text');
  const reveal = document.getElementById('mmd-reveal-btn');
  if (!box || !text || !reveal) return;
  box.classList.toggle('hidden', !message);
  box.classList.remove('mmd-ok', 'mmd-error', 'mmd-running');
  if (type) box.classList.add(`mmd-${type}`);
  text.textContent = message || '';
  reveal.classList.toggle('hidden', !path);
  reveal.dataset.path = path || '';
}

async function pollMmdJob(jobId) {
  const res = await fetch(`/api/mmd/export/${jobId}`);
  if (!res.ok) throw new Error((await res.text()).trim() || `查询失败：${res.status}`);
  const job = await res.json();
  if (job.status === 'running') return false;
  if (job.status === 'error') {
    setMmdStatus(`导出失败：${job.message || '未知错误'}`, 'error');
    return true;
  }
  const report = job.result?.report;
  const boneSummary = job.result?.boneSummary || report?.clothing_bones_summary;
  const boneWeighted = boneSummary?.weighted || boneSummary?.clothingWeighted || [];
  const boneAdded = boneSummary?.added || boneSummary?.clothingAdded || [];
  const boneDetail = boneSummary
    ? ` / 骨骼 ${report?.bones_after_rename ?? boneSummary.total ?? 0} 根（服装骨 ${boneWeighted.length} 根，新增 ${boneAdded.length} 根）`
    : '';
  const detail = report
    ? `（${report.vertices} 顶点 / ${report.triangles} 三角面 / 贴图 ${report.textures_bound} 张${boneDetail}）`
    : '';
  const skipped = report?.items_skipped?.length || 0;
  const extra = skipped ? `，已跳过 ${skipped} 项非服装条目` : '';
  const pmx = job.result?.blend || job.result?.pmx || job.pmx;
  setMmdStatus(`已导出：${pmx}${detail}${extra}`, 'ok', pmx);
  return true;
}

let mmdChromaPreset = null;
window.addEventListener('nrc-chroma-change', e => { mmdChromaPreset = e.detail; });
async function exportMmd() {
  const chromaPreset = mmdChromaPreset;
  const dynamicChroma = !!chromaPreset;
  const button = document.getElementById('mmd-export-btn');
  const items = mmdSelectedItems();
  if (mmdPollTimer) return;
  button.disabled = true;
  setMmdStatus(dynamicChroma ? '正在导出 Blender 动态炫彩场景…' : '正在导出 MMD…', 'running');
  try {
    const res = await fetch('/api/mmd/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items, gender: state.gender, name: buildMmdName(items),
        dynamicChroma, chromaPresetId: dynamicChroma ? chromaPreset.id : undefined,
        chromaPatternTexture: dynamicChroma ? chromaPreset.ornament?.texture : undefined,
        hairColor: Number(state.selected.salon_1?.item?.texture_id) || 1,
        eyeAvatarId: Number(state.selected.salon_3?.item?.avatar_id) || undefined,
        browColor: Number(state.selected.salon_2?.item?.texture_id) || 1 }),
    });
    if (!res.ok) throw new Error((await res.text()).trim() || `导出请求失败：${res.status}`);
    const { jobId } = await res.json();
    mmdPollTimer = setInterval(async () => {
      try {
        if (await pollMmdJob(jobId)) {
          clearInterval(mmdPollTimer);
          mmdPollTimer = null;
          button.disabled = false;
        }
      } catch (err) {
        clearInterval(mmdPollTimer);
        mmdPollTimer = null;
        button.disabled = false;
        setMmdStatus(`导出查询失败：${err.message}`, 'error');
      }
    }, 900);
  } catch (err) {
    button.disabled = false;
    setMmdStatus(err.message, 'error');
  }
}

function initMmdExport() {
  document.getElementById('mmd-export-btn')?.addEventListener('click', () => { exportMmd(); });
  document.getElementById('mmd-reveal-btn')?.addEventListener('click', async event => {
    const target = event.currentTarget.dataset.path;
    if (!target) return;
    await fetch('/api/mmd/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: target }),
    }).catch(() => {});
  });
}

function initRightPanelResizer() {
  const handle = document.getElementById('right-resizer');
  if (!handle) return;

  const root = document.documentElement;
  const minWidth = 260;
  const maxWidth = 720;
  const setWidthFromClientX = clientX => {
    const available = window.innerWidth - parseInt(getComputedStyle(root).getPropertyValue('--sidebar-w'), 10) - 180;
    const max = Math.max(minWidth, Math.min(maxWidth, available));
    const width = Math.round(Math.min(max, Math.max(minWidth, window.innerWidth - clientX)));
    const value = `${width}px`;
    root.style.setProperty('--panel-w', value);
    saveUiPref('panelWidth', value);
  };

  handle.addEventListener('pointerdown', e => {
    e.preventDefault();
    handle.setPointerCapture?.(e.pointerId);
    document.body.classList.add('resizing-panel');
    setWidthFromClientX(e.clientX);
  });

  handle.addEventListener('pointermove', e => {
    if (!document.body.classList.contains('resizing-panel')) return;
    setWidthFromClientX(e.clientX);
  });

  const stopResize = e => {
    handle.releasePointerCapture?.(e.pointerId);
    document.body.classList.remove('resizing-panel');
  };
  handle.addEventListener('pointerup', stopResize);
  handle.addEventListener('pointercancel', stopResize);
}

function initPreviewHeightResizer() {
  const handle = document.getElementById('preview-resizer');
  const rightCol = document.getElementById('right-col');
  if (!handle || !rightCol) return;

  const root = document.documentElement;
  const minSelected = 120;
  const minPreview = 180;
  const setHeightFromClientY = clientY => {
    const rect = rightCol.getBoundingClientRect();
    const maxSelected = Math.max(minSelected, rect.height - minPreview - handle.offsetHeight);
    const height = Math.round(Math.min(maxSelected, Math.max(minSelected, clientY - rect.top)));
    const value = `${height}px`;
    root.style.setProperty('--selected-panel-h', value);
    saveUiPref('selectedPanelHeight', value);
  };

  handle.addEventListener('pointerdown', e => {
    e.preventDefault();
    handle.setPointerCapture?.(e.pointerId);
    document.body.classList.add('resizing-preview');
    setHeightFromClientY(e.clientY);
  });

  handle.addEventListener('pointermove', e => {
    if (!document.body.classList.contains('resizing-preview')) return;
    setHeightFromClientY(e.clientY);
  });

  const stopResize = e => {
    handle.releasePointerCapture?.(e.pointerId);
    document.body.classList.remove('resizing-preview');
  };
  handle.addEventListener('pointerup', stopResize);
  handle.addEventListener('pointercancel', stopResize);
}

// ── 设置页 ───────────────────────────────────────────────────
function getSettingInput(key) {
  return document.getElementById(`setting-${key}`);
}

function resizeSettingInput(input) {
  if (!input || input.tagName !== 'TEXTAREA') return;
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
}

function setSettingsStatus(message, type = '') {
  const el = document.getElementById('settings-status');
  if (!el) return;
  el.textContent = message || '';
  el.className = type || '';
  el.classList.toggle('hidden', !message);
}

function applyConfigStatus(status = {}) {
  for (const key of CONFIG_FIELDS) {
    const input = getSettingInput(key);
    if (!input) continue;
    input.classList.remove('path-ok', 'path-missing');
    // 只有路径类设置才有"存在/缺失"状态，枚举类（port/骨名/物理）不染红
    if (key === 'port' || !(key in (status || {}))) continue;
    input.classList.add(status[key] ? 'path-ok' : 'path-missing');
  }
}

function fillSettingsForm(config) {
  for (const key of CONFIG_FIELDS) {
    const input = getSettingInput(key);
    if (input) {
      input.value = config?.[key] ?? '';
      resizeSettingInput(input);
    }
  }
  applyConfigStatus(config?.status);
}

async function loadSettingsConfig() {
  const res = await fetch('/api/config');
  if (!res.ok) throw new Error(`读取配置失败：${res.status}`);
  const config = await res.json();
  fillSettingsForm(config);
  setSettingsStatus('');
  return config;
}

function getSettingsPayload() {
  const payload = {};
  for (const key of CONFIG_FIELDS) {
    const input = getSettingInput(key);
    if (!input) continue;
    payload[key] = key === 'port'
      ? Number(input.value)
      : input.value.trim();
  }
  return payload;
}

async function saveSettingsConfig() {
  setSettingsStatus('正在保存…');
  const res = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(getSettingsPayload()),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `保存配置失败：${res.status}`);
  }
  const config = await res.json();
  fillSettingsForm(config);
  const missing = Object.entries(config.status || {})
    .filter(([, ok]) => !ok)
    .map(([key]) => key);
  if (missing.length) {
    setSettingsStatus(`已保存，但这些路径不存在：${missing.join(', ')}`, 'error');
    return;
  }
  setSettingsStatus('已保存，正在刷新页面…', 'ok');
  setTimeout(() => location.reload(), 350);
}

function openSettingsDialog() {
  const modal = document.getElementById('settings-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  setSettingsStatus('');
  loadSettingsConfig().catch(err => setSettingsStatus(err.message, 'error'));
}

function closeSettingsDialog() {
  document.getElementById('settings-modal')?.classList.add('hidden');
}

function initSettingsDialog() {
  document.getElementById('settings-btn')?.addEventListener('click', openSettingsDialog);
  document.getElementById('settings-close')?.addEventListener('click', closeSettingsDialog);
  for (const key of CONFIG_FIELDS) {
    const input = getSettingInput(key);
    input?.addEventListener('input', () => resizeSettingInput(input));
  }
  document.getElementById('settings-reload')?.addEventListener('click', () => {
    loadSettingsConfig().catch(err => setSettingsStatus(err.message, 'error'));
  });
  document.getElementById('settings-save')?.addEventListener('click', () => {
    saveSettingsConfig().catch(err => setSettingsStatus(err.message, 'error'));
  });
}

function showStartupError(err) {
  const grid = document.getElementById('grid');
  const empty = document.getElementById('grid-empty');
  grid?.classList.add('hidden');
  if (empty) {
    empty.classList.remove('hidden');
    empty.textContent = '元数据缺失';
  }
  console.warn('[app] metadata missing:', err);
}

// ── 页面暗桩水印 ─────────────────────────────────────────────
function getWatermarkId() {
  let id = localStorage.getItem(WATERMARK_ID_KEY);
  if (id) return id;
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  id = [...bytes].map(v => v.toString(16).padStart(2, '0')).join('').toUpperCase();
  localStorage.setItem(WATERMARK_ID_KEY, id);
  return id;
}

function initPageWatermark() {
  if (document.getElementById('page-watermark')) return;
  const layer = document.createElement('div');
  layer.id = 'page-watermark';
  layer.setAttribute('aria-hidden', 'true');

  const text = `NRC-CLOSET-VIEWER · ${getWatermarkId()}`;
  const count = 90;
  for (let i = 0; i < count; i++) {
    const mark = document.createElement('span');
    mark.textContent = text;
    layer.appendChild(mark);
  }

  document.body.appendChild(layer);
}

// ── 首次打开免责声明 ─────────────────────────────────────────
async function initDisclaimerDialog() {
  const modal = document.getElementById('disclaimer-modal');
  const content = document.getElementById('disclaimer-content');
  const confirmBtn = document.getElementById('disclaimer-confirm');
  const hint = document.getElementById('disclaimer-hint');
  if (!modal || !content || !confirmBtn) return;

  let prefs = {};
  try { prefs = await fetch('/api/prefs').then(r => r.json()); } catch { /* ignore */ }

  if (prefs[DISCLAIMER_ACCEPTED_KEY] === '1') {
    modal.classList.add('hidden');
    return;
  }

  const updateConfirmState = () => {
    const atBottom = content.scrollTop + content.clientHeight >= content.scrollHeight - 2;
    confirmBtn.disabled = !atBottom;
    if (hint) hint.textContent = atBottom ? '' : '请完整阅读后确认';
  };

  modal.classList.remove('hidden');
  confirmBtn.disabled = true;
  content.scrollTop = 0;
  content.addEventListener('scroll', updateConfirmState);
  confirmBtn.addEventListener('click', () => {
    if (confirmBtn.disabled) return;
    saveUiPref(DISCLAIMER_ACCEPTED_KEY, '1');
    modal.classList.add('hidden');
  });
  requestAnimationFrame(updateConfirmState);
}

// ── 完整渲染（切主 tab / 切性别 / 初始化时使用）────────────
function render() {
  updateSuitPreviewToggle();
  renderSidebar();
  renderSubTabs();
  renderGrid();
  renderColorPicker();
  renderSelectedPanel();
  _renderedMainTab = state.mainTab;
  _renderedSubTab  = state.subTab;
}

// ── 初始化 ────────────────────────────────────────────────────
async function init() {
  initPageWatermark();
  initDisclaimerDialog();
  initSettingsDialog();
  initMmdExport();
  loadUiPreferences();

  try {
    await loadData();
    await Promise.all([unreleasedReady, suitThumbOverrideReady, suitPoseOverrideReady]);
  } catch (err) {
    showStartupError(err);
    return;
  }

  document.querySelectorAll('.gender-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.gender-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.gender           = parseInt(btn.dataset.gender, 10);
      state.selected         = {};
      state.selectedSuitId   = null;
      state.activeColorGroup = null;
      _renderedMainTab = null; // 强制重建侧边栏
      applyDefaults();
      render();
      syncPreview();
    });
  });

  document.querySelectorAll('.suit-preview-btn').forEach(btn => {
    btn.addEventListener('click', () => setSuitPreviewMode(btn.dataset.previewMode));
  });

  document.getElementById('search').addEventListener('input', e => {
    state.search = e.target.value;
    renderGrid();
  });

  document.getElementById('clear-btn').addEventListener('click', () => {
    // 清空全部，必选槽重置为默认值
    state.selected       = {};
    state.selectedSuitId = null;
    applyDefaults();
    updateGridSelection();
    renderSelectedPanel();
    syncPreview();
  });

  document.getElementById('export-btn').addEventListener('click', downloadJson);

  // 卡片大小滑块
  document.getElementById('card-size-slider').addEventListener('input', e => {
    const v = parseInt(e.target.value, 10);
    applyCardSize(v);
    saveUiPref('cardSize', String(v));
  });

  initRightPanelResizer();
  initPreviewHeightResizer();
  initSlotGridAutoLayout();


  state.mainTab = 1;
  state.subTab  = null;
  applyDefaults();

  // 供 preview.js 模块初始化后拉取当前状态
  window._getPreviewState = () => ({ selected: state.selected, gender: state.gender });
  render();
  syncPreview();
}

init();
