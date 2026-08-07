// 首次进入落地页：效果展示 → 三步流程 → 隐私承诺，只看一次
Page({
  data: {
    current: 0,
  },

  onSwiper(e) {
    this.setData({ current: e.detail.current });
  },

  start() {
    wx.setStorageSync('landing_seen', 1);
    wx.navigateBack({ fail: () => wx.switchTab({ url: '/pages/chat/chat' }) });
  },
});
