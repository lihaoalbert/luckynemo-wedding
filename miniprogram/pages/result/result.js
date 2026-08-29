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
    eyebrow: '',     // 顶部眉标（反馈 #46：不再写死"免费第一张"）
    headline: '',    // 顶部主标（单人/双人文案不同）
    quotaLeft: 0,    // 剩余可生成张数（免费余+付费余）：>0 时不显示充值卡（反馈 #46）
  },

  onLoad() {
    const order = app.globalData.order || {};
    const solo = order.mode === 'solo';
    const headline = solo ? '看看，是不是你？' : '看看，是不是你们？';
    this.setData({ order });
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const o = res.order || {};
      const quotaLeft = Math.max(0, (o.free_quota || 0) - (o.free_used || 0)) + (o.paid_count || 0);
      // 取最新一条可展示任务（jobs 按时间倒序）：修图重生成(edit_photo)完成后必须展示新图，
      // 不能被更早的系列组图压下去（反馈 #48/#51 跳转发现在结果页还是旧图）
      const latest = (res.jobs || []).find(j =>
        (j.kind === 'template_series' && j.result && j.result.urls && j.result.urls.length) ||
        ((j.kind === 'free_photo' || j.kind === 'solo_photo' || j.kind === 'template_photo'
          || j.kind === 'edit_photo') && j.result && j.result.url));
      const seriesJob = latest && latest.kind === 'template_series' ? latest : null;
      // 整组（≥2 张）走九宫格；只有 1 张的系列结果按单张渲染（反馈 #46：单张九宫格布局错乱）
      if (seriesJob && seriesJob.result.urls.length > 1) {
        const urls = seriesJob.result.urls;
        this.setData({
          quotaLeft,
          eyebrow: '系列组图 · 礼成',
          headline,
          photos: urls.map(u => u.url),
          photoKeys: urls.map(u => u.oss_key || ''),
          mmPhotos: urls.map(u => u.url).slice(0, 9),
        });
        wx.setNavigationBarTitleText({ title: '系列组图出炉' });
        this.loadSeriesInfo(seriesJob.result.series_id || '');
        return;
      }
      const single = seriesJob ? { result: seriesJob.result.urls[0] } : latest;
      this.setData({ quotaLeft, eyebrow: '成片 · 礼成', headline });
      if (single) this.setData({ photo: single.result.url, photoKey: single.result.oss_key || '' });
      wx.setNavigationBarTitleText({ title: solo ? '你的成片' : '你们的成片' });
    }).catch(() => {});
  },

  // 模板 vs 成片：按任务结果里的 series_id 从 catalog 取正确的系列标题与封面
  // （反馈 #46：之前用生成时暂存的 lastSeries，换生成路径后对不上模板）
  loadSeriesInfo(seriesId) {
    if (!seriesId) return;
    app.req('/api/mp/catalog').then(res => {
      const s = (res.moka_series || []).find(x => x.id === seriesId);
      const tpl = (res.moka || []).find(t => t.series === seriesId);
      const base = app.globalData.apiBase;
      this.setData({
        seriesTitle: (s && s.title) || '',
        templateCover: tpl ? base + tpl.img : '',
      });
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
          // 反馈 #48/#51：改跳生成中页（进度动画+轮询，完成后自动进结果页），不再只弹静态提示
          app.globalData.pendingJob = {
            kind: 'edit_photo', submitted: true,
            payload: { base_key: baseKey, instruction },
          };
          wx.navigateTo({ url: '/pages/generating/generating' });
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
