// 生成的照片（二级页）：网格展示 + 全屏左右滑动 + 保存/删除
const app = getApp();

Page({
  data: {
    photos: [],
    loading: true,
  },

  onShow() {
    const order = app.globalData.order;
    if (!order || !order.order_no) {
      this.setData({ loading: false });
      return;
    }
    app.req('/api/mp/me', 'GET', { order_no: order.order_no }).then(res => {
      this.setData({ photos: res.photos, loading: false });
    }).catch(() => this.setData({ loading: false }));
  },

  // 全屏预览：整组 urls + current，系统自带左右滑动
  previewImg(e) {
    wx.previewImage({
      urls: this.data.photos.map(p => p.url),
      current: e.currentTarget.dataset.url,
    });
  },

  showOps(e) {
    const idx = e.currentTarget.dataset.idx;
    const item = this.data.photos[idx];
    wx.showActionSheet({
      itemList: ['保存到相册', '生成分享海报', '删除这张图'],
      success: (r) => {
        if (r.tapIndex === 0) this.saveImg(item.url);
        else if (r.tapIndex === 1) this.makePoster(item.url);
        else if (r.tapIndex === 2) this.delPhoto(item.key);
      },
    });
  },

  // 分享海报：成品图 + 品牌条（朋友圈素材，P1 裂变）
  makePoster(url) {
    wx.showLoading({ title: '海报生成中' });
    wx.downloadFile({
      url,
      success: (dl) => {
        wx.getImageInfo({
          src: dl.tempFilePath,
          success: (info) => {
            const W = 600, H = 900, STRIP = 110;
            const ctx = wx.createCanvasContext('poster', this);
            // cover 裁切铺满上部
            const scale = Math.max(W / info.width, (H - STRIP) / info.height);
            const w = info.width * scale, h = info.height * scale;
            ctx.drawImage(dl.tempFilePath, (W - w) / 2, (H - STRIP - h) / 2, w, h);
            // 品牌条
            ctx.setFillStyle('#1c1714');
            ctx.fillRect(0, H - STRIP, W, STRIP);
            ctx.setFillStyle('#fdf8f4');
            ctx.setFontSize(30);
            ctx.setTextAlign('center');
            ctx.fillText('徐大恩 AI 照相馆', W / 2, H - STRIP + 46);
            ctx.setFontSize(22);
            ctx.setFillStyle('#c9b8ac');
            ctx.fillText('不出门，拍好婚纱照 · 小程序搜「徐大恩」', W / 2, H - STRIP + 84);
            ctx.draw(false, () => {
              wx.canvasToTempFilePath({
                canvasId: 'poster',
                success: (r) => {
                  wx.saveImageToPhotosAlbum({
                    filePath: r.tempFilePath,
                    success: () => wx.showToast({ title: '海报已存相册，去朋友圈晒吧' }),
                    fail: () => wx.showToast({ title: '保存失败，检查相册权限', icon: 'none' }),
                  });
                },
                complete: () => wx.hideLoading(),
              }, this);
            });
          },
          fail: () => { wx.hideLoading(); wx.showToast({ title: '海报生成失败', icon: 'none' }); },
        });
      },
      fail: () => { wx.hideLoading(); wx.showToast({ title: '下载原图失败', icon: 'none' }); },
    });
  },

  saveImg(url) {
    wx.showLoading({ title: '保存中' });
    wx.downloadFile({
      url,
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

  delPhoto(key) {
    wx.showModal({
      title: '删除这张生成图？',
      content: '会从云端彻底删除，不可恢复。',
      confirmText: '删除',
      confirmColor: '#c0736a',
      success: (r) => {
        if (!r.confirm) return;
        app.req('/api/mp/delete', 'POST', {
          order_no: app.globalData.order.order_no, target: 'photo', oss_key: key,
        }).then(() => {
          wx.showToast({ title: '已删除' });
          this.onShow();
        }).catch(err => wx.showToast({ title: err.message, icon: 'none' }));
      },
    });
  },

  onShareAppMessage() {
    // 分享卡片带最新成品图（5:4 裁切由微信处理；P1 裂变）
    const img = this.data.photos.length ? this.data.photos[0].url
      : 'https://luckynemo.ibi.ren/moka/templates/mk005.png';
    return {
      title: '看看我们的婚纱照，不出门 AI 拍的 ✨',
      path: '/pages/chat/chat',
      imageUrl: img,
    };
  },
});
