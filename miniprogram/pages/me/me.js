// 我的：个人信息 / 额度 / 上传的照片 / 生成的照片 / 充值入口
const app = getApp();

Page({
  data: {
    order: {},
    quota: {},
    uploads: { A: [], B: [] },
    photos: [],
    loading: true,
    fsMode: '',   // 人脸三视图选片模式：'' | 'A' | 'B'
    fsBase: '',   // 正脸底照 key
    fsSides: [],  // 侧脸照 keys（最多 2 张）
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

  onImgTap(e) {
    if (this.data.fsMode) {
      this.fsPick(e);
      return;
    }
    this.previewImg(e);
  },

  previewImg(e) {
    // 全屏预览支持左右滑动：传当前相册整组 urls + 当前图
    const role = e.currentTarget.dataset.role;
    const album = role && this.data.uploads[role] ? this.data.uploads[role] : this.data.photos;
    wx.previewImage({
      urls: album.map(p => p.url),
      current: e.currentTarget.dataset.url,
    });
  },

  goPhotos() {
    wx.navigateTo({ url: '/pages/photos/photos' });
  },

  // ---- 人脸三视图选片（反馈 #26：侧脸不像） ----
  fsStart(e) {
    const role = e.currentTarget.dataset.role;
    this.setData({ fsMode: role, fsBase: '', fsSides: [] });
    this._fsMark();
    wx.showToast({ title: '先点 1 张正脸底照', icon: 'none' });
  },

  fsPick(e) {
    const role = e.currentTarget.dataset.role;
    const key = e.currentTarget.dataset.key;
    if (role !== this.data.fsMode) {
      wx.showToast({ title: '生成谁的就选谁的照片', icon: 'none' });
      return;
    }
    let { fsBase, fsSides } = this.data;
    if (fsBase === key) {
      fsBase = '';
    } else if (fsSides.includes(key)) {
      fsSides = fsSides.filter(k => k !== key);
    } else if (!fsBase) {
      fsBase = key;
    } else if (fsSides.length < 2) {
      fsSides = fsSides.concat(key);
    } else {
      wx.showToast({ title: '侧脸最多选 2 张', icon: 'none' });
      return;
    }
    this.setData({ fsBase, fsSides });
    this._fsMark();
  },

  _fsMark() {
    // 给已选照片打角标（底照/侧1/侧2），其余清空
    const mark = (list) => list.map(it => {
      let m = '';
      if (it.key === this.data.fsBase) m = '底照';
      else {
        const i = this.data.fsSides.indexOf(it.key);
        if (i >= 0) m = `侧${i + 1}`;
      }
      return { ...it, fsMark: m };
    });
    this.setData({
      'uploads.A': mark(this.data.uploads.A),
      'uploads.B': mark(this.data.uploads.B),
    });
  },

  fsCancel() {
    this.setData({ fsMode: '', fsBase: '', fsSides: [] });
    this._fsMark();
  },

  fsConfirm() {
    const { fsMode, fsBase, fsSides } = this.data;
    if (!fsBase || !fsSides.length) return;
    app.req('/api/mp/job', 'POST', {
      order_no: this.data.order.order_no, kind: 'face_sheet',
      payload: { role: fsMode, base_key: fsBase, side_keys: fsSides },
    }).then(() => {
      wx.showModal({
        title: '已开始生成',
        content: '人脸三视图约 1 分钟出图，好了会出现在下方「生成的照片」里（下拉刷新或稍后再进来看）。之后生成的照片侧脸会更像本人。',
        showCancel: false,
      });
      this.fsCancel();
    }).catch(err => wx.showToast({ title: err.message || '提交失败', icon: 'none' }));
  },

  recharge() {
    wx.showActionSheet({
      itemList: ['4 元 / 张（按张付费）', '52 元套餐 · 20 张（最划算）'],
      success: (r) => {
        const pack = r.tapIndex === 1;
        app.vpay(pack ? 'pack52' : 'per_photo', pack ? '52 元套餐 · 20 张' : '4 元/张');
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
      imageUrl: 'https://luckynemo.ibi.ren/moka/templates/mk005.png',
    };
  },
});
