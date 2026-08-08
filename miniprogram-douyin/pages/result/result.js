// 结果页：免费成片 + 付费升级（4 元/张 或 52 套餐 · 20 张）+ 下载分享
const app = getApp();

Page({
  data: {
    order: null,
    photo: '',
    photos: [],      // template_series 整组结果（九宫格）
    mmPhotos: [],    // 朋友圈 mock 缩略（前 9 张）
    seriesTitle: '', // 来源系列（模板 vs 成片对比）
    templateCover: '',
    canPay: true,    // iOS 端 false：隐藏付费升级区（抖音无 iOS 虚拟支付）
  },

  onLoad() {
    const order = app.globalData.order;
    this.setData({ order, canPay: app.globalData.canPay });
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const seriesJob = (res.jobs || []).find(j =>
        j.kind === 'template_series' && j.result && j.result.urls && j.result.urls.length);
      if (seriesJob) {
        const photos = seriesJob.result.urls.map(u => u.url);
        // 详情页生成时留下的系列信息（job 接口不回传 series_id），没有就不渲染对比块
        const last = app.globalData.lastSeries || {};
        this.setData({
          photos,
          mmPhotos: photos.slice(0, 9),
          seriesTitle: last.title || '',
          templateCover: last.cover || '',
        });
        return;
      }
      const job = (res.jobs || []).find(j =>
        (j.kind === 'free_photo' || j.kind === 'solo_photo' || j.kind === 'template_photo') && j.result && j.result.url);
      if (job) this.setData({ photo: job.result.url });
    }).catch(() => {});
  },

  preview() {
    if (!this.data.photo) return;
    tt.previewImage({ urls: [this.data.photo] });
  },

  previewOne(e) {
    tt.previewImage({ urls: this.data.photos, current: e.currentTarget.dataset.url });
  },

  save() {
    if (!this.data.photo) return;
    tt.showLoading({ title: '保存中' });
    tt.downloadFile({
      url: this.data.photo,
      success: (r) => {
        tt.saveImageToPhotosAlbum({
          filePath: r.tempFilePath,
          success: () => tt.showToast({ title: '已存到相册' }),
          fail: () => tt.showToast({ title: '保存失败，检查相册权限', icon: 'none' }),
        });
      },
      complete: () => tt.hideLoading(),
    });
  },

  // 整组保存：逐张下载存入相册
  saveAll() {
    const urls = this.data.photos;
    if (!urls.length) return;
    tt.showLoading({ title: '保存中 0/' + urls.length });
    let done = 0;
    const next = (i) => {
      if (i >= urls.length) {
        tt.hideLoading();
        tt.showToast({ title: '已全部存到相册' });
        return;
      }
      tt.downloadFile({
        url: urls[i],
        success: (r) => tt.saveImageToPhotosAlbum({
          filePath: r.tempFilePath,
          complete: () => { done += 1; tt.showLoading({ title: `保存中 ${done}/${urls.length}` }); next(i + 1); },
        }),
        fail: () => { done += 1; next(i + 1); },
      });
    };
    next(0);
  },

  buyPer() {
    tt.showModal({ title: '继续生成', content: '4 元/张，按张付费，满意再生成下一张', confirmText: '好', success: () => this.pay('per_photo', 4) });
  },

  buyPack() {
    tt.showModal({ title: '52 元套餐', content: '20 张高清婚纱照，多风格多场景，最划算', confirmText: '买它', success: () => this.pay('pack52', 52) });
  },

  pay(kind, amount) {
    // 担保支付（按单支付）：4 元/张、52 元套餐 · 20 张；iOS 入口已隐藏此处兜底；未配置时 app.vpay 回退意见反馈
    if (!app.globalData.canPay) return;
    app.vpay(kind, kind === 'pack52' ? '52 元套餐 · 20 张' : '4 元/张');
  },

  upgrade() {
    tt.showModal({
      title: '想要一支爱情短片？',
      content: '把你们的爱情故事做成 60-90 秒的叙事短片：专属脚本、配音配乐，婚礼开场放一次，往后每个纪念日再看一次。',
      confirmText: '去留言咨询',
      success: (r) => { if (r.confirm) tt.navigateTo({ url: '/pages/feedback/feedback' }); },
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
