// 结果页：免费成片 + 付费升级（4 元/张 或 52 套餐 · 20 张）+ 下载分享
const app = getApp();

Page({
  data: {
    order: null,
    photo: '',
    photoKey: '',    // 单张成片的 oss_key（不满意重生成用）
    photos: [],      // template_series 整组结果（九宫格）
    photoKeys: [],   // 九宫格对应的 oss_key（长按提意见重生成用）
    mmPhotos: [],    // 朋友圈 mock 缩略（前 9 张）
    seriesTitle: '', // 来源系列（模板 vs 成片对比）
    templateCover: '',
  },

  onLoad() {
    const order = app.globalData.order;
    this.setData({ order });
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const seriesJob = (res.jobs || []).find(j =>
        j.kind === 'template_series' && j.result && j.result.urls && j.result.urls.length);
      if (seriesJob) {
        const photos = seriesJob.result.urls.map(u => u.url);
        const photoKeys = seriesJob.result.urls.map(u => u.oss_key || '');
        // 详情页生成时留下的系列信息（job 接口不回传 series_id），没有就不渲染对比块
        const last = app.globalData.lastSeries || {};
        this.setData({
          photos,
          photoKeys,
          mmPhotos: photos.slice(0, 9),
          seriesTitle: last.title || '',
          templateCover: last.cover || '',
        });
        return;
      }
      const job = (res.jobs || []).find(j =>
        (j.kind === 'free_photo' || j.kind === 'solo_photo' || j.kind === 'template_photo') && j.result && j.result.url);
      if (job) this.setData({ photo: job.result.url, photoKey: job.result.oss_key || '' });
    }).catch(() => {});
  },

  // 不满意 → 提修改意见重生成（反馈 #41/#45：每单免费 3 次，后端 /api/mp/revise 控制）
  revise(e) {
    const baseKey = (e && e.currentTarget && e.currentTarget.dataset.key) || this.data.photoKey;
    if (!baseKey) {
      wx.showToast({ title: '这张照片暂不支持修改', icon: 'none' });
      return;
    }
    wx.showModal({
      title: '哪里不满意？',
      placeholderText: '比如：去掉眼镜、背景亮一点',
      editable: true,
      confirmText: '重新生成',
      success: (r) => {
        if (!r.confirm) return;
        const instruction = (r.content || '').trim();
        if (!instruction) {
          wx.showToast({ title: '写一句修改意见哦', icon: 'none' });
          return;
        }
        app.req('/api/mp/revise', 'POST', {
          order_no: this.data.order.order_no, target: 'photo',
          base_key: baseKey, instruction,
        }).then(() => {
          app.askSubscribe();
          wx.showModal({
            title: '已开始重新生成',
            content: '大约 1 分钟，完成后到「相册」查看；接受订阅的话会收到服务通知。',
            confirmText: '去相册',
            cancelText: '留在这',
            success: (m) => {
              if (m.confirm) wx.navigateTo({ url: '/pages/photos/photos' });
            },
          });
        }).catch(err => {
          wx.showModal({ title: '提示', content: err.message, showCancel: false });
        });
      },
    });
  },

  // 九宫格：长按某张提意见重生成
  reviseOne(e) {
    const key = e.currentTarget.dataset.key;
    if (!key) return;
    wx.showActionSheet({
      itemList: ['这张不满意，提意见重生成'],
      success: (r) => {
        if (r.tapIndex === 0) this.revise({ currentTarget: { dataset: { key } } });
      },
    });
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
      title: '不出门，拍好婚纱照 📷 新用户免费送 1 张',
      path: '/pages/chat/chat' + (order.share_token ? '?ref=' + order.share_token : ''),
      imageUrl: this.data.photo || '',
    };
  },
});
