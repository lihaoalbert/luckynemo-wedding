// 上传页：拍摄指引 + 拍照/相册上传（复用 /api/uploads/sign 直传 OSS）
// 双人婚纱照分「她的」「他的」两个区（B 区 contact = order_no:B）；个人写真只有她的区
const app = getApp();

Page({
  data: {
    order: null,
    mode: 'solo',     // couple=婚纱照 / solo=个人写真
    myRole: 'A',      // 协同创作：B 端只传自己的照片
    files: [],        // [{path, status, progress, role}]
    guideShow: true,
    hasDone: false,   // 有任意一张传完就显示「去定妆」
    prompted: false,  // 引导弹窗只弹一次
  },

  onLoad() {
    const order = app.globalData.order || {};
    this.setData({ order, mode: order.mode || 'solo', myRole: app.globalData.myRole || 'A' });
    // 已传过的用户（含分批传）直接显示「去定妆」入口；B 端看他自己的照片数
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const mine = this.data.myRole === 'B' ? (res.photo_count_b || 0) : (res.photo_count || 0);
      if (mine > 0) this.setData({ hasDone: true });
    }).catch(() => {});
  },

  toggleGuide() {
    this.setData({ guideShow: !this.data.guideShow });
  },

  chooseA() { this.choose('A'); },
  chooseB() { this.choose('B'); },

  choose(role) {
    wx.chooseMedia({
      count: 9,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        res.tempFiles.forEach(f => this.upload(f.tempFilePath, role));
      },
    });
  },

  upload(path, role) {
    const files = this.data.files.concat([{ path, status: '签名中', progress: 0, role }]);
    this.setData({ files });
    const idx = files.length - 1;
    const name = path.split('/').pop();
    app.req('/api/uploads/sign', 'POST', {
      contact: role === 'B' ? this.data.order.order_no + '-B' : this.data.order.order_no,
      filename: name,
      content_type: 'image/jpeg',
      size: 1,
    }).then(signed => {
      this.setStatus(idx, '上传中', 40);
      wx.uploadFile({
        url: signed.url,
        filePath: path,
        name: 'file',
        formData: signed.fields,
        success: (r) => {
          if (r.statusCode >= 200 && r.statusCode < 300) {
            this.setStatus(idx, '完成', 100);
            this.maybeDone();
          } else {
            this.setStatus(idx, '失败', 0);
          }
        },
        fail: () => this.setStatus(idx, '失败', 0),
      });
    }).catch(e => this.setStatus(idx, '失败：' + e.message, 0));
  },

  setStatus(idx, status, progress) {
    const files = this.data.files.slice();
    if (files[idx]) { files[idx].status = status; files[idx].progress = progress; }
    this.setData({ files });
  },

  maybeDone() {
    const doneA = this.data.files.filter(f => f.status === '完成' && f.role === 'A').length;
    if (doneA > 0) this.setData({ hasDone: true });
    if (doneA >= 3 && !this.data.prompted) {
      this.setData({ prompted: true });
      wx.showModal({
        title: '照片已收到',
        content: '收到她的 ' + doneA + ' 张照片，接下来先为她定个妆吧～',
        confirmText: '去定妆',
        success: (r) => { if (r.confirm) this.goMakeup(); },
      });
    }
  },

  goMakeup() {
    if (!this.data.hasDone) {
      wx.showToast({ title: '先传至少 1 张照片哦', icon: 'none' });
      return;
    }
    const url = this.data.myRole === 'B' ? '/pages/makeup/makeup?role=B' : '/pages/makeup/makeup';
    wx.navigateTo({ url });
  },
});
