// 模卡页：一键同款（挑模板 → 换人出图），微调可换服装/换妆容
const app = getApp();

Page({
  data: {
    tab: 'couple',     // couple / solo_f / solo_m
    tabs: [
      { key: 'couple', label: '情侣婚纱' },
      { key: 'solo_f', label: '女生写真' },
      { key: 'solo_m', label: '男生写真' },
    ],
    templates: [],
    picked: null,      // 选中的模板（弹层确认）
    anchors: [],       // 我的定妆照（微调-换妆容用）
    swapAnchorKey: '',
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
      this.setData({ templates, sets });
    }).catch(e => {
      wx.hideLoading();
      wx.showToast({ title: e.message, icon: 'none' });
    });
    // 我的定妆照（微调-换妆容）
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const anchors = (res.jobs || [])
        .filter(j => j.kind === 'makeup_photo' && j.status === 'done' && j.result && j.result.url)
        .map(j => ({ url: j.result.url, key: j.result.oss_key || '', name: j.makeup_name || '定妆照', role: j.role || 'A' }));
      this.setData({ anchors });
    }).catch(() => {});
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

  pick(e) {
    const t = this.data.templates.find(x => x.id === e.currentTarget.dataset.id);
    const selection = app.globalData.selection || {};
    // components 对象转列表供模板渲染
    t.componentsList = Object.keys(t.components || {}).map(k => ({ k, v: t.components[k] }));
    this.setData({ picked: t, swapAnchorKey: selection.anchor_key || '', swapSetId: '' });
  },

  closePick() { this.setData({ picked: null }); },

  noop() {},

  // 微调：换妆容（选另一张定妆照）
  swapAnchor(e) { this.setData({ swapAnchorKey: e.currentTarget.dataset.key }); },

  // 微调：换服装（选套装，附加服装参考图）
  swapSet(e) { this.setData({ swapSetId: e.currentTarget.dataset.id }); },

  previewImg(e) { wx.previewImage({ urls: [e.currentTarget.dataset.url] }); },

  confirm() {
    const t = this.data.picked;
    if (!t) return;
    const selection = app.globalData.selection || {};
    const payload = {
      template_id: t.id,
      mode: t.mode === 'couple' ? 'couple' : 'solo',
      anchor_key: this.data.swapAnchorKey || selection.anchor_key || '',
      anchor_key_b: t.mode === 'couple' ? (selection.anchor_key_b || '') : '',
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
    if (t.mode === 'couple' && (!payload.anchor_key || !payload.anchor_key_b)) {
      wx.showModal({ title: '还缺定妆照', content: '情侣模板需要新娘和新郎都有定妆照，先去定妆好吗？', confirmText: '去定妆', success: (r) => { if (r.confirm) wx.navigateTo({ url: '/pages/makeup/makeup' }); } });
      return;
    }
    if (t.mode !== 'couple' && !payload.anchor_key) {
      wx.showModal({ title: '还缺定妆照', content: '需要一张你的定妆照才能一键同款，先去定妆好吗？', confirmText: '去定妆', success: (r) => { if (r.confirm) wx.navigateTo({ url: '/pages/makeup/makeup' }); } });
      return;
    }
    app.globalData.selection = selection;
    app.globalData.pendingJob = { kind: 'template_photo', payload };
    this.setData({ picked: null });
    wx.navigateTo({ url: '/pages/generating/generating' });
  },
});
