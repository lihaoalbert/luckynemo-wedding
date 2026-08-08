// 我收藏的大片：收藏的系列卡网格，点击进详情页
const app = getApp();
const { buildTemplates, buildSeriesList } = require('../../utils/moka.js');

Page({
  data: {
    loading: true,
    list: [],
  },

  onShow() {
    this.setData({ loading: true });
    Promise.all([
      // 收藏接口未上线/登录态无效时回退空列表，不阻塞页面
      app.req('/api/mp/favs', 'GET', { open_token: app.globalData.openToken || '' })
        .catch(() => ({ favs: [] })),
      app.req('/api/mp/catalog'),
    ]).then(([favRes, catalog]) => {
      const base = app.globalData.apiBase;
      const templates = buildTemplates(catalog, base);
      const seriesAll = buildSeriesList(catalog, templates);
      const list = (favRes.favs || [])
        .map(id => seriesAll.find(s => s.id === id))
        .filter(Boolean);
      this.setData({ list, loading: false });
    }).catch(e => {
      this.setData({ loading: false });
      wx.showToast({ title: e.message, icon: 'none' });
    });
  },

  openSeries(e) {
    wx.navigateTo({ url: '/pages/moka_series/moka_series?id=' + e.currentTarget.dataset.id });
  },

  goMoka() {
    wx.navigateTo({ url: '/pages/moka/moka' });
  },
});
