// 同款大片 · 发现首页：搜索 / 主推轮播 / 人生节点 / 本周热门 / 全部分组
// 点系列卡 → 详情独立页（pages/moka_series）；老版平铺为无分组数据时的回退
const app = getApp();
const { buildTemplates, buildSeriesList } = require('../../utils/moka.js');

Page({
  data: {
    tab: 'couple',     // 老版平铺回退用：couple / solo_f / solo_m
    tabs: [
      { key: 'couple', label: '情侣婚纱' },
      { key: 'solo_f', label: '女生写真' },
      { key: 'solo_m', label: '男生写真' },
    ],
    groups: [],        // 一级分组（含系列卡片）；为空时回退老版平铺
    activeGroup: '',
    seriesAll: [],     // 系列全集（轮播/热门/搜索/节点过滤共用）
    heroList: [],      // 主推轮播（status!=normal 优先，不足 3 个按热度补齐）
    heroIdx: 0,
    moments: [],       // 人生节点入口（catalog.moments）
    activeMoment: '',
    activeMomentTitle: '',
    hotList: [],       // 本周热门（hot 降序前 6）
    gridList: [],      // 当前网格（分组或节点过滤结果）
    searchText: '',
    searchResults: [],
    templates: [],
    picked: null,      // 老版回退：选中的单张模板（弹层确认）
    anchors: [],       // 我的定妆照（老版回退弹层用）
    anchorsF: [],
    anchorsM: [],
    swapAnchorF: '',
    swapAnchorM: '',
    swapSetId: '',
    sets: [],
  },

  onLoad() {
    const order = app.globalData.order || {};
    const mode = order.mode || 'couple';
    this.setData({ tab: mode === 'solo' ? 'solo_f' : 'couple' });
    tt.showLoading({ title: '打开大片库…' });
    app.req('/api/mp/catalog').then(res => {
      tt.hideLoading();
      const base = app.globalData.apiBase;
      const templates = buildTemplates(res, base);
      const seriesAll = buildSeriesList(res, templates);
      const groups = this.buildGroups(res, seriesAll);
      const heroList = this.buildHero(seriesAll);
      const hotList = seriesAll
        .filter(s => s.hasHot)
        .sort((a, b) => b.hotVal - a.hotVal)
        .slice(0, 6);
      this.setData({
        templates, seriesAll, groups, heroList, hotList,
        moments: Array.isArray(res.moments) ? res.moments : [],
        sets: this.parseSets(res.sets_js, base + res.img_base.wardrobe),
        activeGroup: groups.length ? groups[0].id : '',
      });
      this.refreshGrid();
    }).catch(e => {
      tt.hideLoading();
      tt.showToast({ title: e.message, icon: 'none' });
    });
    // 我的定妆照（老版回退弹层的换妆容用；按性别分组，A 不一定是女生）
    if (!order.order_no) return;
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const anchors = (res.jobs || [])
        .filter(j => j.kind === 'makeup_photo' && j.status === 'done' && j.result && j.result.url)
        .map(j => ({
          url: j.result.url, key: j.result.oss_key || '', name: j.makeup_name || '定妆照',
          role: j.role || 'A',
          gender: j.gender || ((j.makeup_name || '').includes('男士') ? 'male' : 'female'),
        }));
      this.setData({ anchors });
    }).catch(() => {});
  },

  // 分组 → 系列卡片（系列对象与 seriesAll 共享引用）
  buildGroups(res, seriesAll) {
    return (res.moka_groups || []).map(g => ({
      ...g,
      seriesList: (g.series || [])
        .map(sid => seriesAll.find(s => s.id === sid))
        .filter(Boolean),
    })).filter(g => g.seriesList.length);
  },

  // 主推轮播：status!=normal 的系列优先，不足 3 个按热度补齐
  buildHero(seriesAll) {
    const featured = seriesAll.filter(s => s.status && s.status !== 'normal');
    const list = featured.slice();
    if (list.length < 3) {
      const rest = seriesAll
        .filter(s => list.indexOf(s) < 0)
        .sort((a, b) => b.hotVal - a.hotVal);
      list.push(...rest.slice(0, 3 - list.length));
    }
    return list.slice(0, 5);
  },

  // 当前网格：节点过滤优先，否则当前分组
  refreshGrid() {
    const { activeMoment, activeGroup, seriesAll, groups } = this.data;
    let gridList;
    if (activeMoment) {
      gridList = seriesAll.filter(s => s.moments.includes(activeMoment));
    } else {
      const g = groups.find(x => x.id === activeGroup);
      gridList = g ? g.seriesList : [];
    }
    this.setData({ gridList });
  },

  parseSets(js, imgBase) {
    const m = js.match(/const SETS = (\[[\s\S]*\]);/);
    const arr = m ? JSON.parse(m[1]) : [];
    return arr.map(s => ({
      ...s,
      dressImg: imgBase + encodeURI(s.dress.img.replace(/^img\//, '')),
      suitImg: imgBase + encodeURI(s.suit.img.replace(/^img\//, '')),
    }));
  },

  // ---- 搜索：系列名 / tags / 分组名 包含匹配，清空恢复原视图 ----
  onSearch(e) {
    const text = (e.detail.value || '').trim();
    const searchResults = text ? this.data.seriesAll.filter(s =>
      s.title.includes(text) ||
      s.groupTitle.includes(text) ||
      s.tags.some(t => t.includes(text))
    ) : [];
    this.setData({ searchText: text, searchResults });
  },

  clearSearch() { this.setData({ searchText: '', searchResults: [] }); },

  // ---- 主推轮播指示点 ----
  onHeroScroll(e) {
    const n = this.data.heroList.length;
    if (n < 2) return;
    const win = tt.getWindowInfo ? tt.getWindowInfo() : tt.getSystemInfoSync();
    const max = e.detail.scrollWidth - win.windowWidth + 20; // 右侧留白补偿
    let idx = max > 0 ? Math.round(e.detail.scrollLeft / max * (n - 1)) : 0;
    idx = Math.max(0, Math.min(n - 1, idx));
    if (idx !== this.data.heroIdx) this.setData({ heroIdx: idx });
  },

  // ---- 分组 / 人生节点 ----
  pickGroup(e) {
    this.setData({ activeGroup: e.currentTarget.dataset.id, activeMoment: '', activeMomentTitle: '' });
    this.refreshGrid();
  },

  pickMoment(e) {
    const id = e.currentTarget.dataset.id;
    const title = e.currentTarget.dataset.title;
    const off = this.data.activeMoment === id;
    this.setData({ activeMoment: off ? '' : id, activeMomentTitle: off ? '' : title });
    this.refreshGrid();
    if (!off) tt.showToast({ title: `已按「${title}」筛选`, icon: 'none' });
  },

  // 任何系列卡 → 详情独立页
  openSeries(e) {
    tt.navigateTo({ url: '/pages/moka_series/moka_series?id=' + e.currentTarget.dataset.id });
  },

  // ================= 老版平铺回退（无分组数据时）=================
  switchTab(e) { this.setData({ tab: e.currentTarget.dataset.key, picked: null }); },

  // 定妆照按性别分组并给默认选中（不依赖 role，A 不一定是女生）
  _anchorDefaults() {
    const selection = app.globalData.selection || {};
    const anchorsF = this.data.anchors.filter(a => a.gender !== 'male');
    const anchorsM = this.data.anchors.filter(a => a.gender === 'male');
    return {
      anchorsF, anchorsM,
      swapAnchorF: selection.anchor_key || (anchorsF[0] && anchorsF[0].key) || '',
      swapAnchorM: selection.anchor_key_b || (anchorsM[0] && anchorsM[0].key) || '',
    };
  },

  pick(e) {
    const t = this.data.templates.find(x => x.id === e.currentTarget.dataset.id);
    // components 对象转列表供模板渲染
    t.componentsList = Object.keys(t.components || {}).map(k => ({ k, v: t.components[k] }));
    this.setData({ picked: t, swapSetId: '', ...this._anchorDefaults() });
  },

  closePick() { this.setData({ picked: null }); },

  noop() {},

  // 微调：换妆容（女生位/男生位各选一张定妆照）
  swapAnchor(e) {
    const { g, key } = e.currentTarget.dataset;
    if (g === 'm') this.setData({ swapAnchorM: key });
    else this.setData({ swapAnchorF: key });
  },

  // 微调：换服装（选套装，附加服装参考图）
  swapSet(e) { this.setData({ swapSetId: e.currentTarget.dataset.id }); },

  previewImg(e) { tt.previewImage({ urls: [e.currentTarget.dataset.url] }); },

  // 锚点按模板性别走：女单→女生定妆照，男单→男生定妆照，情侣→两个都要
  _anchorsFor(mode) {
    const couple = mode === 'couple';
    const soloM = mode === 'solo_m';
    return {
      couple, soloM,
      anchor_key: couple ? (this.data.swapAnchorF || '')
               : (soloM ? (this.data.swapAnchorM || '') : (this.data.swapAnchorF || '')),
      anchor_key_b: couple ? (this.data.swapAnchorM || '') : '',
    };
  },

  // 缺定妆照不硬拦：知情继续（worker 会用原始照片回退），或先去定妆
  _checkAnchors(mode, payload, go) {
    const couple = mode === 'couple';
    const soloM = mode === 'solo_m';
    const missF = couple ? !payload.anchor_key : (!soloM && !payload.anchor_key);
    const missB = couple ? !payload.anchor_key_b : (soloM && !payload.anchor_key);
    if (missF || missB) {
      const who = missF ? '女生' : '男生';
      tt.showModal({
        title: `${who}还没有定妆照`,
        content: '可以继续生成（用 TA 上传的原始照片），或先去定妆（效果更好）',
        confirmText: '继续生成',
        cancelText: '去定妆',
        success: (r) => {
          if (r.confirm) go();
          else tt.navigateTo({ url: '/pages/makeup/makeup' + (missB ? '?role=B' : '') });
        },
      });
      return;
    }
    go();
  },

  confirm() {
    const t = this.data.picked;
    if (!t) return;
    const a = this._anchorsFor(t.mode);
    const payload = {
      template_id: t.id,
      mode: a.couple ? 'couple' : 'solo',
      anchor_key: a.anchor_key,
      anchor_key_b: a.anchor_key_b,
      swap_imgs: [],
      swap_note: '',
    };
    if (this.data.swapSetId) {
      const set = this.data.sets.find(s => s.id === this.data.swapSetId);
      if (set) {
        payload.swap_imgs = [set.dress.img, set.suit.img].filter(Boolean);
        payload.swap_note = `服装以附加参考图为准（${set.name}），替换掉模板中的服装`;
      }
    }
    this._checkAnchors(t.mode, payload, () => this._go(payload));
  },

  _go(payload) {
    const selection = app.globalData.selection || {};
    app.globalData.selection = selection;
    app.globalData.pendingJob = { kind: 'template_photo', payload };
    this.setData({ picked: null });
    tt.navigateTo({ url: '/pages/generating/generating' });
  },
});
