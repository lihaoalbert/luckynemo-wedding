// 结果页：免费成片 + 付费升级（4 元/张 或 52 套餐 · 20 张）+ 下载分享
const app = getApp();

Page({
  data: {
    order: null,
    photo: '',
    photos: [],      // template_series 整组结果（九宫格）
  },

  onLoad() {
    const order = app.globalData.order;
    this.setData({ order });
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const seriesJob = (res.jobs || []).find(j =>
        j.kind === 'template_series' && j.result && j.result.urls && j.result.urls.length);
      if (seriesJob) {
        this.setData({ photos: seriesJob.result.urls.map(u => u.url) });
        return;
      }
      const job = (res.jobs || []).find(j =>
        (j.kind === 'free_photo' || j.kind === 'solo_photo' || j.kind === 'template_photo') && j.result && j.result.url);
      if (job) this.setData({ photo: job.result.url });
    }).catch(() => {});
  },

  preview() {
    if (!this.data.photo) return;
    wx.previewImage({ urls: [this.data.photo] });
  },

  previewOne(e) {
    wx.previewImage({ urls: this.data.photos, current: e.currentTarget.dataset.url });
  },

  save() {
    if (!this.data.photo) return;
    wx.showLoading({ title: '保存中' });
    wx.downloadFile({
      url: this.data.photo,
      success: (r) => {
        wx.saveImageToPhotosAlbum({
          filePath: r.tempFilePath,
          success: () => wx.showToast({ title: '已存到相册' }),
          fail: () => wx.showToast({ title: '保存失败，检查相册权限', icon: 'none' }),
        });
      },
      complete: () => wx.hideLoading(),
    });
  },

  // 整组保存：逐张下载存入相册
  saveAll() {
    const urls = this.data.photos;
    if (!urls.length) return;
    wx.showLoading({ title: '保存中 0/' + urls.length });
    let done = 0;
    const next = (i) => {
      if (i >= urls.length) {
        wx.hideLoading();
        wx.showToast({ title: '已全部存到相册' });
        return;
      }
      wx.downloadFile({
        url: urls[i],
        success: (r) => wx.saveImageToPhotosAlbum({
          filePath: r.tempFilePath,
          complete: () => { done += 1; wx.showLoading({ title: `保存中 ${done}/${urls.length}` }); next(i + 1); },
        }),
        fail: () => { done += 1; next(i + 1); },
      });
    };
    next(0);
  },

  buyPer() {
    wx.showModal({ title: '继续生成', content: '4 元/张，按张付费，满意再生成下一张', confirmText: '好', success: () => this.pay('per_photo', 4) });
  },

  buyPack() {
    wx.showModal({ title: '52 元套餐', content: '20 张高清婚纱照，多风格多场景，最划算', confirmText: '买它', success: () => this.pay('pack52', 52) });
  },

  pay(kind, amount) {
    // 虚拟支付（代币模式，1 元=1 金币）：4 元/张 = 4 币，52 元套餐 = 52 币；未开通时 app.vpay 自动回退客服
    app.vpay(kind, kind === 'pack52' ? '52 元套餐 · 20 张' : '4 元/张');
  },

  upgrade() {
    wx.showModal({
      title: '想要一支爱情短片？',
      content: '把你们的爱情故事做成 60-90 秒的叙事短片：专属脚本、配音配乐，婚礼开场放一次，往后每个纪念日再看一次。',
      confirmText: '了解一下',
      success: (r) => { if (r.confirm) wx.setClipboardData({ data: 'LuckyNemo2026', success: () => wx.showToast({ title: '客服微信已复制' }) }); },
    });
  },

  onShareAppMessage() {
    const order = this.data.order || {};
    return {
      title: '不出门，拍好婚纱照 📷 内测送你 20 张免费额度',
      path: '/pages/chat/chat' + (order.share_token ? '?ref=' + order.share_token : ''),
      imageUrl: this.data.photo || '',
    };
  },
});
