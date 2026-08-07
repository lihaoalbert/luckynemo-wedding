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
      itemList: ['保存到相册', '删除这张图'],
      success: (r) => {
        if (r.tapIndex === 0) this.saveImg(item.url);
        else if (r.tapIndex === 1) this.delPhoto(item.key);
      },
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
});
