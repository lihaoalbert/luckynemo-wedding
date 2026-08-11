// 系列详情页：大图 / tags / 数据条 / 九宫格预览 / 成分表 / 收藏 / 整组或选张生成
const app = getApp();
const { buildTemplates, buildSeriesList } = require('../../utils/moka.js');

const PRICE_PER = 4; // 币/张

Page({
  data: {
    loading: true,
    notFound: false,
    series: null,
    cells: [],        // 九宫格格子（变体 + sel 选中态）
    comps: [],        // 成分表 k/v（取首个变体）
    selMode: false,
    selIds: [],       // 选中的变体 id（选片模式）
    selCount: 0,
    fav: false,
    favBusy: false,
    priceText: '',
    priceSub: '',
    goText: '',
    // 定妆照锚点（生成时按性别取，详情页「出镜人」区块可换）
    anchors: [],
    anchorsF: [],
    anchorsM: [],
    swapAnchorF: '',
    swapAnchorM: '',
  },

  onLoad(options) {
    this.seriesId = (options && options.id) || '';
    app.req('/api/mp/catalog').then(res => {
      const base = app.globalData.apiBase;
      const templates = buildTemplates(res, base);
      const seriesAll = buildSeriesList(res, templates);
      const series = seriesAll.find(s => s.id === this.seriesId);
      if (!series) {
        this.setData({ loading: false, notFound: true });
        return;
      }
      const first = series.variants[0] || {};
      const comps = Object.keys(first.components || {}).map(k => ({ k, v: first.components[k] }));
      this.setData({
        loading: false, series, comps,
        cells: series.variants.map(v => ({ ...v, sel: false })),
      });
      this.updateCta();
    }).catch(e => {
      this.setData({ loading: false });
      tt.showToast({ title: e.message, icon: 'none' });
    });
    // 收藏初始状态（登录态无效/接口未上线时静默回退未收藏）
    app.req('/api/mp/favs', 'GET', { open_token: app.globalData.openToken || '' })
      .then(res => {
        if ((res.favs || []).includes(this.seriesId)) this.setData({ fav: true });
      }).catch(() => {});
    // 我的定妆照（按性别分组，A 不一定是女生）
    const order = app.globalData.order || {};
    if (!order.order_no) return;
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const anchors = (res.jobs || [])
        .filter(j => j.kind === 'makeup_photo' && j.status === 'done' && j.result && j.result.url)
        .map(j => ({
          url: j.result.url, key: j.result.oss_key || '', name: j.makeup_name || '定妆照',
          gender: j.gender || ((j.makeup_name || '').includes('男士') ? 'male' : 'female'),
        }));
      const selection = app.globalData.selection || {};
      const anchorsF = anchors.filter(a => a.gender !== 'male');
      const anchorsM = anchors.filter(a => a.gender === 'male');
      this.setData({
        anchors, anchorsF, anchorsM,
        swapAnchorF: selection.anchor_key || (anchorsF[0] && anchorsF[0].key) || '',
        swapAnchorM: selection.anchor_key_b || (anchorsM[0] && anchorsM[0].key) || '',
      });
    }).catch(() => {});
  },

  goBack() { tt.navigateBack({ fail: () => tt.redirectTo({ url: '/pages/moka/moka' }) }); },

  // ---- 收藏 ----
  toggleFav() {
    if (this.data.favBusy || !this.data.series) return;
    const fav = !this.data.fav;
    this.setData({ fav, favBusy: true });
    app.req('/api/mp/fav', 'POST', {
      open_token: app.globalData.openToken || '',
      series_id: this.data.series.id,
      fav,
    }).then(() => {
      this.setData({ favBusy: false });
      if (fav) tt.showToast({ title: '已收藏，在「我的」里随时找到', icon: 'none' });
    }).catch(e => {
      this.setData({ fav: !fav, favBusy: false });
      tt.showToast({ title: e.message || '操作失败', icon: 'none' });
    });
  },

  // ---- 九宫格 ----
  cellTap(e) {
    const id = e.currentTarget.dataset.id;
    if (!this.data.selMode) {
      tt.previewImage({
        urls: this.data.series.variants.map(v => v.img),
        current: e.currentTarget.dataset.url,
      });
      return;
    }
    const selIds = this.data.selIds.slice();
    const i = selIds.indexOf(id);
    if (i >= 0) selIds.splice(i, 1);
    else selIds.push(id);
    this.setData({
      selIds,
      selCount: selIds.length,
      cells: this.data.cells.map(c => ({ ...c, sel: selIds.includes(c.id) })),
    });
    this.updateCta();
  },

  // ---- 选片模式 ----
  toggleSelMode() {
    const selMode = !this.data.selMode;
    this.setData({
      selMode,
      selIds: [],
      selCount: 0,
      cells: this.data.cells.map(c => ({ ...c, sel: false })),
    });
    this.updateCta();
    if (selMode) tt.showToast({ title: '点右上角圆圈选片，可多张', icon: 'none' });
  },

  updateCta() {
    const s = this.data.series;
    if (!s) return;
    if (this.data.selMode) {
      const n = this.data.selCount;
      this.setData({
        priceText: (n * PRICE_PER) + '币',
        priceSub: `已选 ${n} 张 · 每张${PRICE_PER}币`,
        goText: n ? `生成选中 ${n} 张 →` : '先选照片',
      });
    } else {
      this.setData({
        priceText: (s.count * PRICE_PER) + '币',
        priceSub: s.count === 9 ? `9张整组 · 单张${PRICE_PER}币` : `${s.count}张精选 · 单张${PRICE_PER}币`,
        goText: s.count === 9 ? '一键九宫格 →' : `整组 ${s.count} 张 →`,
      });
    }
  },

  // ---- 出镜人：换定妆照锚点（反馈 #32） ----
  swapAnchor(e) {
    const { g, key } = e.currentTarget.dataset;
    if (g === 'f') this.setData({ swapAnchorF: key });
    else this.setData({ swapAnchorM: key });
  },

  // ---- 生成 ----
  // 锚点按系列性别走：女单→女生定妆照，男单→男生定妆照，情侣→两个都要
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

  // 整组：不带 variant_ids；选片子集/单张：带 variant_ids
  generate() {
    const s = this.data.series;
    if (!s) return;
    if (this.data.selMode && !this.data.selCount) return;
    const a = this._anchorsFor(s.mode);
    const payload = {
      series_id: s.id,
      mode: a.couple ? 'couple' : 'solo',
      anchor_key: a.anchor_key,
      anchor_key_b: a.anchor_key_b,
    };
    if (this.data.selMode) {
      const order = s.variants.map(v => v.id);
      payload.variant_ids = this.data.selIds.slice()
        .sort((x, y) => order.indexOf(x) - order.indexOf(y));
    }
    // 扣费确认（反馈 #32：一键九宫格需二次确认）
    const n = this.data.selMode ? this.data.selCount : s.count;
    tt.showModal({
      title: '确认生成',
      content: `${n} 张成片，消耗 ${n * PRICE_PER} 币`,
      confirmText: '开始生成',
      success: (r) => {
        if (!r.confirm) return;
        this._checkAnchors(s.mode, payload, () => {
          app.globalData.pendingJob = { kind: 'template_series', payload };
          // 结果页「模板 vs 成片」对比用（job 接口不回传 series_id）
          app.globalData.lastSeries = { id: s.id, title: s.title, cover: s.coverImg };
          tt.navigateTo({ url: '/pages/generating/generating' });
        });
      },
    });
  },
});
