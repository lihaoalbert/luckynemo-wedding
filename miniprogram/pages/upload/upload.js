// 上传页：槽位引导（正脸必传 + 左侧/右侧/全身建议）+ 更多照片自由上传
// 凑齐 正脸+至少一张侧脸 自动后台生成人脸三视图（用户无感知，反馈 #26/#29 之后的三视图前台化取消）
const app = getApp();

const SLOT_NAMES = { front: '正脸照', left: '左侧脸', right: '右侧脸', body: '全身照' };

Page({
  data: {
    order: null,
    mode: 'solo',     // couple=婚纱照 / solo=个人写真
    myRole: 'A',      // 协同创作：B 端只传自己的照片
    files: [],        // [{path, status, progress, role, slot, slotName}]
    slots: {          // 槽位回填：{A: {front:{url,key}, ...}, B: {...}}
      A: { front: {}, left: {}, right: {}, body: {} },
      B: { front: {}, left: {}, right: {}, body: {} },
    },
    guideShow: true,
    hasDone: false,
    prompted: false,
  },

  onLoad() {
    const order = app.globalData.order || {};
    this.setData({ order, mode: order.mode || 'solo', myRole: app.globalData.myRole || 'A' });
    // 已传过的照片：回填槽位 + 显示「去定妆」入口
    app.req('/api/mp/me', 'GET', { order_no: order.order_no }).then(res => {
      const slots = this.data.slots;
      for (const role of ['A', 'B']) {
        for (const u of res.uploads[role] || []) {
          if (u.slot && SLOT_NAMES[u.slot] && !slots[role][u.slot].url) {
            slots[role][u.slot] = { url: u.url, key: u.key };
          }
        }
      }
      const mine = this.data.myRole === 'B' ? (res.uploads.B || []) : (res.uploads.A || []);
      this.setData({ slots, hasDone: mine.length > 0 });
    }).catch(() => {});
  },

  toggleGuide() {
    this.setData({ guideShow: !this.data.guideShow });
  },

  chooseA() { this.choose('A', ''); },
  chooseB() { this.choose('B', ''); },

  chooseSlot(e) {
    this.choose(e.currentTarget.dataset.role, e.currentTarget.dataset.slot);
  },

  choose(role, slot) {
    wx.chooseMedia({
      count: slot ? 1 : 9,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        res.tempFiles.forEach(f => this.upload(f.tempFilePath, role, slot));
      },
    });
  },

  // storylab 视频花絮：登记到 A 相册（contact=order_no，服务端自动触发素材理解；
  // 相册各处查询都带 image/% 过滤，视频行不影响照片流程）
  chooseVideo() {
    wx.chooseMedia({
      count: 3,
      mediaType: ['video'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        res.tempFiles.forEach(f => this.uploadVideo(f));
      },
    });
  },

  uploadVideo(f) {
    const thumb = f.thumbTempFilePath || f.tempFilePath;
    const files = this.data.files.concat([{
      path: thumb, status: '签名中', progress: 0, role: 'A', slot: '',
      slotName: '视频', isVideo: true,
    }]);
    this.setData({ files });
    const idx = files.length - 1;
    const name = (f.tempFilePath.split('/').pop() || 'video.mp4');
    const ext = (name.split('.').pop() || 'mp4').toLowerCase();
    const ctype = { mp4: 'video/mp4', mov: 'video/quicktime', m4v: 'video/mp4', '3gp': 'video/3gpp' }[ext] || 'video/mp4';
    app.req('/api/uploads/sign', 'POST', {
      contact: this.data.order.order_no,
      filename: name,
      content_type: ctype,
      size: f.size || 1,
      slot: '',
    }).then(signed => {
      this.setStatus(idx, '上传中', 40);
      wx.uploadFile({
        url: signed.url,
        filePath: f.tempFilePath,
        name: 'file',
        formData: signed.fields,
        success: (r) => {
          if (r.statusCode >= 200 && r.statusCode < 300) {
            this.setStatus(idx, '完成', 100);
          } else {
            this.setStatus(idx, '失败', 0);
          }
        },
        fail: () => this.setStatus(idx, '失败', 0),
      });
    }).catch(e => this.setStatus(idx, '失败：' + e.message, 0));
  },

  upload(path, role, slot) {
    const files = this.data.files.concat([{
      path, status: '签名中', progress: 0, role, slot,
      slotName: SLOT_NAMES[slot] || '',
    }]);
    this.setData({ files });
    const idx = files.length - 1;
    const name = path.split('/').pop();
    app.req('/api/uploads/sign', 'POST', {
      contact: role === 'B' ? this.data.order.order_no + '-B' : this.data.order.order_no,
      filename: name,
      content_type: 'image/jpeg',
      size: 1,
      slot: slot || '',
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
            this.onUploaded(idx);
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

  onUploaded(idx) {
    const f = this.data.files[idx];
    // 槽位回填缩略图
    if (f.slot && SLOT_NAMES[f.slot]) {
      this.setData({ [`slots.${f.role}.${f.slot}`]: { url: f.path, key: '' } });
      // 凑齐正脸+侧脸 → 后台自动出人脸三视图（静默，失败不打扰）
      if (f.slot !== 'body') {
        app.req('/api/mp/face_sheet/auto', 'POST', {
          order_no: this.data.order.order_no, role: f.role,
        }).catch(() => {});
      }
    }
    this.maybeDone();
  },

  maybeDone() {
    const doneA = this.data.files.filter(f => f.status === '完成' && f.role === 'A').length;
    if (doneA > 0) this.setData({ hasDone: true });
    if (doneA >= 3 && !this.data.prompted) {
      this.setData({ prompted: true });
      wx.showModal({
        title: '照片已收到',
        content: '收到我的 ' + doneA + ' 张照片，接下来先定个妆吧～',
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
