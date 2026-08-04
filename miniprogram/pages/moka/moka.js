// 模卡页：系列化一键同款（选系列 → 整组九宫格 / 单张同款），微调可换服装/换妆容
const app = getApp();

Page({
  data: {
    tab: 'couple',     // 老版平铺回退用：couple / solo_f / solo_m
    tabs: [
      { key: 'couple', label: '情侣婚纱' },
      { key: 'solo_f', label: '女生写真' },
      { key: 'solo_m', label: '男生写真' },
    ],
    groups: [],        // v3 一级分组（含系列卡片）；为空时回退老版平铺
    activeGroup: '',
    templates: [],
    picked: null,      // 选中的单张模板（弹层确认）
    pickedSeries: null, // 选中的系列（九宫格弹层）
    anchors: [],       // 我的定妆照（微调-换妆容用）
    anchorsF: [],      // 女生定妆照
    anchorsM: [],      // 男生定妆照
    swapAnchorF: '',
    swapAnchorM: '',
    swapSetId: '',
    sets: [],
    generating: false,
  },

  onLoad() {
    const order = app.globalData.order || {};
    const mode = order.mode || 'couple';
    this.setData({ tab: mode === 'solo' ? 'solo_f' : 'couple' });
    wx.showLoading({ title: '打开模卡库…' });
    app.req('/api/mp/catalog').then(res => {
      wx.hideLoading();
      const base = app.globalData.apiBase;
      const templates = (res.moka || []).map(t => ({ ...t, img: base + t.img }));
      const sets = this.parseSets(res.sets_js, base + res.img_base.wardrobe);
      const groups = this.buildGroups(res, templates);
      this.setData({
        templates, sets, groups,
        activeGroup: groups.length ? groups[0].id : '',
      });
    }).catch(e => {
      wx.hideLoading();
      wx.showToast({ title: e.message, icon: 'none' });
    });
    // 我的定妆照（微调-换妆容；按性别分组，A 不一定是女生）
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

  // 一级分组 → 系列卡片（封面=首发变体，variants 带完整模板对象）
  buildGroups(res, templates) {
    const tmap = {};
    templates.forEach(t => { tmap[t.id] = t; });
    const seriesAll = res.moka_series || [];
    const modeLabel = { couple: '情侣', solo_f: '女单', solo_m: '男单' };
    return (res.moka_groups || []).map(g => ({
      ...g,
      seriesList: (g.series || [])
        .map(sid => seriesAll.find(s => s.id === sid))
        .filter(Boolean)
        .map(s => {
          const variants = (s.variants || []).map(v => tmap[v]).filter(Boolean);
          return {
            ...s, variants, count: variants.length,
            cover: variants.length ? variants[0].img : '',
            modeText: modeLabel[s.mode] || '',
          };
        })
        .filter(s => s.count),
    })).filter(g => g.seriesList.length);
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

  switchTab(e) { this.setData({ tab: e.currentTarget.dataset.key, picked: null }); },

  switchGroup(e) { this.setData({ activeGroup: e.currentTarget.dataset.id, pickedSeries: null }); },

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
    this.setData({ picked: t, swapSetId: '', pickedSeries: null, ...this._anchorDefaults() });
  },

  closePick() { this.setData({ picked: null }); },

  // 系列九宫格弹层
  pickSeries(e) {
    const gid = this.data.activeGroup;
    const g = this.data.groups.find(x => x.id === gid);
    const s = g && g.seriesList.find(x => x.id === e.currentTarget.dataset.id);
    if (!s) return;
    this.setData({ pickedSeries: s, picked: null, swapSetId: '', ...this._anchorDefaults() });
  },

  closeSeries() { this.setData({ pickedSeries: null }); },

  // 系列弹层里点单张 → 走单张同款确认弹层
  pickVariant(e) {
    const t = this.data.templates.find(x => x.id === e.currentTarget.dataset.id);
    if (!t) return;
    t.componentsList = Object.keys(t.components || {}).map(k => ({ k, v: t.components[k] }));
    this.setData({ picked: t, pickedSeries: null, swapSetId: '' });
  },

  noop() {},

  // 微调：换妆容（女生位/男生位各选一张定妆照）
  swapAnchor(e) {
    const { g, key } = e.currentTarget.dataset;
    if (g === 'm') this.setData({ swapAnchorM: key });
    else this.setData({ swapAnchorF: key });
  },

  // 微调：换服装（选套装，附加服装参考图）
  swapSet(e) { this.setData({ swapSetId: e.currentTarget.dataset.id }); },

  previewImg(e) { wx.previewImage({ urls: [e.currentTarget.dataset.url] }); },

  previewVariant(e) {
    const s = this.data.pickedSeries;
    if (!s) return;
    wx.previewImage({
      urls: s.variants.map(v => v.img),
      current: e.currentTarget.dataset.url,
    });
  },

  // 锚点按模板/系列性别走：女单→女生定妆照，男单→男生定妆照，情侣→两个都要
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
      wx.showModal({
        title: `${who}还没有定妆照`,
        content: '可以继续生成（用 TA 上传的原始照片），或先去定妆（效果更好）',
        confirmText: '继续生成',
        cancelText: '去定妆',
        success: (r) => {
          if (r.confirm) go();
          else wx.navigateTo({ url: '/pages/makeup/makeup' });
        },
      });
      return;
    }
    go();
  },

  // 整组生成：一个系列的全部变体一次出齐（九宫格）
  confirmSeries() {
    const s = this.data.pickedSeries;
    if (!s) return;
    const a = this._anchorsFor(s.mode);
    const payload = {
      series_id: s.id,
      mode: a.couple ? 'couple' : 'solo',
      anchor_key: a.anchor_key,
      anchor_key_b: a.anchor_key_b,
    };
    this._checkAnchors(s.mode, payload, () => {
      app.globalData.pendingJob = { kind: 'template_series', payload };
      this.setData({ pickedSeries: null });
      wx.navigateTo({ url: '/pages/generating/generating' });
    });
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
    wx.navigateTo({ url: '/pages/generating/generating' });
  },
});
