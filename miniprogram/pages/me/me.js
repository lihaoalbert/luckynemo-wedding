// 我的：个人信息 / 额度 / 上传的照片 / 生成的照片 / 充值入口
const app = getApp();

Page({
  data: {
    order: {},
    quota: {},
    uploads: { A: [], B: [] },
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
      this.setData({
        order: res.order, quota: res.quota,
        uploads: res.uploads, photos: res.photos, loading: false,
      });
    }).catch(() => this.setData({ loading: false }));
  },

  previewImg(e) {
    wx.previewImage({ urls: [e.currentTarget.dataset.url] });
  },

  saveImg(e) {
    const url = e.currentTarget.dataset.url;
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

  recharge() {
    wx.showActionSheet({
      itemList: ['3.9 元 / 张（按张付费）', '49 元套餐 · 50 张（最划算）'],
      success: (r) => {
        const pack = r.tapIndex === 1;
        app.vpay(pack ? 'pack49' : 'per_photo', pack ? '49 元套餐 · 50 张' : '3.9 元/张');
      },
      fail: () => {},
    });
  },

  privacy() {
    wx.showModal({
      title: '隐私承诺',
      content: '你上传的照片只用于为你自己生成作品，真人认证保护你的脸不被他人使用，交付即删。',
      showCancel: false,
    });
  },

  copyOrderNo() {
    wx.setClipboardData({
      data: this.data.order.order_no,
      success: () => wx.showToast({ title: '订单号已复制' }),
    });
  },

  goFeedback() {
    wx.navigateTo({ url: '/pages/feedback/feedback' });
  },

  // 长按删除上传的照片（OSS + 记录都删）
  delUpload(e) {
    const key = e.currentTarget.dataset.key;
    wx.showModal({
      title: '删除这张照片？',
      content: '会从云端彻底删除，不可恢复。',
      confirmText: '删除',
      confirmColor: '#c0736a',
      success: (r) => {
        if (!r.confirm) return;
        app.req('/api/mp/delete', 'POST', {
          order_no: this.data.order.order_no, target: 'upload', oss_key: key,
        }).then(() => {
          wx.showToast({ title: '已删除' });
          this.onShow();
        }).catch(err => wx.showToast({ title: err.message, icon: 'none' }));
      },
    });
  },

  // 删除生成的照片
  delPhoto(e) {
    const key = e.currentTarget.dataset.key;
    wx.showModal({
      title: '删除这张生成图？',
      content: '会从云端彻底删除，不可恢复。',
      confirmText: '删除',
      confirmColor: '#c0736a',
      success: (r) => {
        if (!r.confirm) return;
        app.req('/api/mp/delete', 'POST', {
          order_no: this.data.order.order_no, target: 'photo', oss_key: key,
        }).then(() => {
          wx.showToast({ title: '已删除' });
          this.onShow();
        }).catch(err => wx.showToast({ title: err.message, icon: 'none' }));
      },
    });
  },

  restart() {
    wx.showModal({
      title: '重新开始？',
      content: '会清空当前进度并开启新订单（历史订单保留在服务器）。',
      confirmText: '重新开始',
      confirmColor: '#c0736a',
      success: (r) => {
        if (!r.confirm) return;
        wx.removeStorageSync('mp_order');
        wx.removeStorageSync('mp_role');
        app.globalData.order = null;
        app.globalData.selection = {};
        app.globalData.myRole = 'A';
        wx.reLaunch({ url: '/pages/chat/chat' });
      },
    });
  },

  onShareAppMessage() {
    const order = this.data.order || {};
    if (order.mode === 'couple' && order.share_token) {
      return {
        title: '💌 邀请你一起拍婚纱照：点这里完成你的认证和照片',
        path: '/pages/chat/chat?share=' + order.share_token,
      };
    }
    return {
      title: '不出门拍好婚纱照，内测送你 20 张免费额度',
      path: '/pages/chat/chat' + (order.share_token ? '?ref=' + order.share_token : ''),
    };
  },
});
