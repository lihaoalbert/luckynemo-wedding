// 结果页：免费成片 + 付费升级（3.9/张 或 49 套餐）+ 下载分享
const app = getApp();

Page({
  data: {
    order: null,
    photo: '',
  },

  onLoad() {
    const order = app.globalData.order;
    this.setData({ order });
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const job = (res.jobs || []).find(j =>
        (j.kind === 'free_photo' || j.kind === 'solo_photo' || j.kind === 'template_photo') && j.result && j.result.url);
      if (job) this.setData({ photo: job.result.url });
    }).catch(() => {});
  },

  preview() {
    if (!this.data.photo) return;
    wx.previewImage({ urls: [this.data.photo] });
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

  buyPer() {
    wx.showModal({ title: '继续生成', content: '3.9 元/张，按张付费，满意再生成下一张', confirmText: '好', success: () => this.pay('per_photo', 3.9) });
  },

  buyPack() {
    wx.showModal({ title: '49 元套餐', content: '50 张高清婚纱照，多风格多场景，最划算', confirmText: '买它', success: () => this.pay('pack49', 49) });
  },

  pay(kind, amount) {
    // v1：AppID/商户号下来前，引导客服核销（线上支付开通后替换为 wx.requestPayment）
    wx.showModal({
      title: '支付通道即将开通',
      content: `你选择了「${kind === 'pack49' ? '49 元套餐' : '3.9 元/张'}」（¥${amount}）。小程序支付正在开通中，可先扫码联系客服完成下单。`,
      confirmText: '复制客服微信',
      success: (r) => {
        if (r.confirm) wx.setClipboardData({ data: 'LuckyNemo2026' });
      },
    });
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
