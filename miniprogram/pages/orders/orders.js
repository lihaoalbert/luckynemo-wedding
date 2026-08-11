// 订单中心：充值/购买记录（微信提审要求提供订单中心页 path）
const app = getApp();

Page({
  data: {
    items: [],
    loading: true,
    failed: false,
  },

  onShow() {
    this.setData({ loading: true, failed: false });
    (app.globalData.tokenPromise || Promise.resolve()).then(() =>
      app.req('/api/mp/pay_orders', 'GET', { open_token: app.globalData.openToken || '' })
    ).then(res => {
      this.setData({ items: res.pay_orders || [], loading: false });
    }).catch(() => this.setData({ loading: false, failed: true }));
  },

  copyTradeNo(e) {
    wx.setClipboardData({
      data: e.currentTarget.dataset.no,
      success: () => wx.showToast({ title: '交易单号已复制' }),
    });
  },
});
