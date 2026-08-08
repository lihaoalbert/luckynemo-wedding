// 意见反馈：类型 + 文字 + 图片（持续改进用）
const app = getApp();

Page({
  data: {
    types: [
      { key: 'bug', label: '🐞 问题反馈' },
      { key: 'feature', label: '💡 功能期望' },
      { key: 'other', label: '💬 其他想说' },
    ],
    type: 'bug',
    text: '',
    images: [],      // [{path, key, status}] 
    history: [],
    submitting: false,
  },

  onLoad() {
    const order = app.globalData.order || {};
    if (order.order_no) {
      app.req('/api/mp/feedback', 'GET', { order_no: order.order_no })
        .then(res => this.setData({ history: res.items || [] }))
        .catch(() => {});
    }
  },

  pickType(e) { this.setData({ type: e.currentTarget.dataset.key }); },
  onText(e) { this.setData({ text: e.detail.value }); },

  chooseImage() {
    wx.chooseMedia({
      count: 3 - this.data.images.length,
      mediaType: ['image'],
      success: (res) => {
        res.tempFiles.forEach(f => this.uploadImage(f.tempFilePath));
      },
    });
  },

  uploadImage(path) {
    const order = app.globalData.order || {};
    const images = this.data.images.concat([{ path, key: '', status: '上传中' }]);
    this.setData({ images });
    const idx = images.length - 1;
    app.req('/api/uploads/sign', 'POST', {
      contact: (order.order_no || 'anonymous') + '-feedback',
      filename: path.split('/').pop(),
      content_type: 'image/jpeg',
      size: 1,
    }).then(signed => {
      wx.uploadFile({
        url: signed.url,
        filePath: path,
        name: 'file',
        formData: signed.fields,
        success: (r) => {
          const imgs = this.data.images.slice();
          imgs[idx].status = r.statusCode < 300 ? '完成' : '失败';
          imgs[idx].key = signed.fields.key;
          this.setData({ images: imgs });
        },
        fail: () => this.setStatus(idx, '失败'),
      });
    }).catch(() => this.setStatus(idx, '失败'));
  },

  setStatus(idx, status) {
    const imgs = this.data.images.slice();
    imgs[idx].status = status;
    this.setData({ images: imgs });
  },

  removeImage(e) {
    const imgs = this.data.images.slice();
    imgs.splice(e.currentTarget.dataset.idx, 1);
    this.setData({ images: imgs });
  },

  submit() {
    if (!this.data.text.trim()) {
      wx.showToast({ title: '说点什么吧～', icon: 'none' });
      return;
    }
    if (this.data.images.some(i => i.status === '上传中')) {
      wx.showToast({ title: '图片还在上传中', icon: 'none' });
      return;
    }
    this.setData({ submitting: true });
    const order = app.globalData.order || {};
    app.req('/api/mp/feedback', 'POST', {
      order_no: order.order_no || 'anonymous',
      type: this.data.type,
      text: this.data.text.trim(),
      images: this.data.images.filter(i => i.key).map(i => i.key),
    }).then(() => {
      this.setData({ submitting: false, text: '', images: [] });
      wx.showToast({ title: '收到啦，谢谢你的反馈 💌' });
      app.req('/api/mp/feedback', 'GET', { order_no: order.order_no })
        .then(res => this.setData({ history: res.items || [] }))
        .catch(() => {});
    }).catch(e => {
      this.setData({ submitting: false });
      wx.showToast({ title: e.message, icon: 'none' });
    });
  },

  previewImg(e) {
    wx.previewImage({ urls: [e.currentTarget.dataset.url] });
  },
});
