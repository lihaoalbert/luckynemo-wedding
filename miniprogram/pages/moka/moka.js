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
      this.setData({ templates, sets });
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
    // 定妆照按性别分组并给默认选中（不依赖 role，A 不一定是女生）
    const anchorsF = this.data.anchors.filter(a => a.gender !== 'male');
    const anchorsM = this.data.anchors.filter(a => a.gender === 'male');
    this.setData({
      picked: t, swapSetId: '', anchorsF, anchorsM,
      swapAnchorF: selection.anchor_key || (anchorsF[0] && anchorsF[0].key) || '',
      swapAnchorM: selection.anchor_key_b || (anchorsM[0] && anchorsM[0].key) || '',
    });
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

  previewImg(e) { wx.previewImage({ urls: [e.currentTarget.dataset.url] }); },

  confirm() {
    const t = this.data.picked;
    if (!t) return;
    const couple = t.mode === 'couple';
    const soloM = t.mode === 'solo_m';
    const payload = {
      template_id: t.id,
      mode: couple ? 'couple' : 'solo',
      // 锚点跟模板性别走：女单→女生定妆照，男单→男生定妆照，情侣→两个都要
      anchor_key: couple ? (this.data.swapAnchorF || '')
                 : (soloM ? (this.data.swapAnchorM || '') : (this.data.swapAnchorF || '')),
      anchor_key_b: couple ? (this.data.swapAnchorM || '') : '',
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
    // 缺定妆照不硬拦：知情继续（worker 会用原始照片回退），或先去定妆
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
          if (r.confirm) this._go(payload);
          else wx.navigateTo({ url: '/pages/makeup/makeup' });
        },
      });
      return;
    }
    this._go(payload);
  },

  _go(payload) {
    const selection = app.globalData.selection || {};
    app.globalData.selection = selection;
    app.globalData.pendingJob = { kind: 'template_photo', payload };
    this.setData({ picked: null });
    wx.navigateTo({ url: '/pages/generating/generating' });
  },
});
