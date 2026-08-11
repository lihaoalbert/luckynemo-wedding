// 我的：额度 / 邀请有礼 / 资产区（相册·收藏·上传照片）/ 人脸三视图 / 个人信息（折叠）/ 帮助
const app = getApp();

Page({
  data: {
    order: {},
    quota: {},
    quotaTotal: 0,
    uploads: { A: [], B: [] },
    uploadsCount: 0,
    photos: [],
    loading: true,
    infoOpen: false,  // 个人信息卡默认折叠
    canPay: true,     // iOS 端 false：隐藏充值入口（抖音无 iOS 虚拟支付）
  },

  onShow() {
    const order = app.globalData.order;
    if (!order || !order.order_no) {
      this.setData({ loading: false, canPay: app.globalData.canPay });
      return;
    }
    app.req('/api/mp/me', 'GET', { order_no: order.order_no }).then(res => {
      const quota = res.quota || {};
      const uploads = res.uploads || { A: [], B: [] };
      this.setData({
        order: res.order, quota,
        quotaTotal: (quota.free_left || 0) + (quota.paid_left || 0),
        uploads,
        uploadsCount: uploads.A.length + uploads.B.length,
        photos: res.photos, loading: false,
        canPay: app.globalData.canPay,
      });
    }).catch(() => this.setData({ loading: false, canPay: app.globalData.canPay }));
  },

  toggleInfo() {
    this.setData({ infoOpen: !this.data.infoOpen });
  },

  goPhotos() {
    tt.navigateTo({ url: '/pages/photos/photos' });
  },

  goUploads() {
    tt.navigateTo({ url: '/pages/myuploads/myuploads' });
  },

  goFav() {
    tt.navigateTo({ url: '/pages/moka_fav/moka_fav' });
  },

  // 人脸三视图：跳到上传照片页进入点选模式（反馈 #26：侧脸不像）
  fsStart(e) {
    const role = e.currentTarget.dataset.role;
    tt.navigateTo({ url: '/pages/myuploads/myuploads?fs=' + role });
  },

  recharge() {
    tt.showActionSheet({
      itemList: ['4 元 / 张（按张付费）', '52 元套餐 · 20 张（最划算）'],
      success: (r) => {
        const pack = r.tapIndex === 1;
        app.vpay(pack ? 'pack52' : 'per_photo', pack ? '52 元套餐 · 20 张' : '4 元/张');
      },
      fail: () => {},
    });
  },

  privacy() {
    tt.showModal({
      title: '隐私承诺',
      content: '你上传的照片只用于为你自己生成作品，真人认证保护你的脸不被他人使用，交付即删。',
      showCancel: false,
    });
  },

  copyOrderNo() {
    tt.setClipboardData({
      data: this.data.order.order_no,
      success: () => tt.showToast({ title: '订单号已复制' }),
    });
  },

  goFeedback() {
    tt.navigateTo({ url: '/pages/feedback/feedback' });
  },

  restart() {
    tt.showModal({
      title: '开启新订单？',
      content: '会清空当前进度并开启新订单。当前订单的成片和照片仍保留在服务器，但新订单里看不到。',
      confirmText: '开启新订单',
      confirmColor: '#c0736a',
      success: (r) => {
        if (!r.confirm) return;
        tt.removeStorageSync('mp_order');
        tt.removeStorageSync('mp_role');
        app.globalData.order = null;
        app.globalData.selection = {};
        app.globalData.myRole = 'A';
        tt.reLaunch({ url: '/pages/chat/chat' });
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
      title: '不出门拍好婚纱照，新用户免费送 1 张',
      path: '/pages/chat/chat' + (order.share_token ? '?ref=' + order.share_token : ''),
      imageUrl: 'https://luckynemo.ibi.ren/moka/templates/mk005.png',
    };
  },
});
