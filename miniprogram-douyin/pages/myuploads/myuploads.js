// 我上传的照片（二级页）：网格 + 全屏滑动 + 长按删除 + 人脸三视图点选（?fs=A|B 进入选片模式）
const app = getApp();

Page({
  data: {
    order: {},
    uploads: { A: [], B: [] },
    loading: true,
    fsMode: '',   // 人脸三视图选片模式：'' | 'A' | 'B'
    fsBase: '',   // 正脸底照 key
    fsSides: [],  // 侧脸照 keys（最多 2 张）
  },

  onLoad(options) {
    // 从「我的」页三视图入口带参进入选片模式
    if (options && (options.fs === 'A' || options.fs === 'B')) {
      this._pendingFs = options.fs;
    }
  },

  onShow() {
    const order = app.globalData.order;
    if (!order || !order.order_no) {
      this.setData({ loading: false });
      return;
    }
    app.req('/api/mp/me', 'GET', { order_no: order.order_no }).then(res => {
      this.setData({ order: res.order, uploads: res.uploads, loading: false });
      if (this._pendingFs) {
        const role = this._pendingFs;
        this._pendingFs = null;
        this.fsStart({ currentTarget: { dataset: { role } } });
      }
    }).catch(() => this.setData({ loading: false }));
  },

  onImgTap(e) {
    if (this.data.fsMode) {
      this.fsPick(e);
      return;
    }
    // 全屏预览支持左右滑动：传当前相册整组 urls + 当前图
    const role = e.currentTarget.dataset.role;
    const album = this.data.uploads[role] || [];
    tt.previewImage({
      urls: album.map(p => p.url),
      current: e.currentTarget.dataset.url,
    });
  },

  // ---- 人脸三视图选片（反馈 #26：侧脸不像） ----
  fsStart(e) {
    const role = e.currentTarget.dataset.role;
    this.setData({ fsMode: role, fsBase: '', fsSides: [] });
    this._fsMark();
    tt.showToast({ title: '先点 1 张正脸底照', icon: 'none' });
  },

  fsPick(e) {
    const role = e.currentTarget.dataset.role;
    const key = e.currentTarget.dataset.key;
    if (role !== this.data.fsMode) {
      tt.showToast({ title: '生成谁的就选谁的照片', icon: 'none' });
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
      tt.showToast({ title: '侧脸最多选 2 张', icon: 'none' });
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
      tt.showModal({
        title: '已开始生成',
        content: '人脸三视图约 1 分钟出图，好了会出现在「相册」里。之后生成的照片侧脸会更像本人。',
        showCancel: false,
      });
      this.fsCancel();
    }).catch(err => tt.showToast({ title: err.message || '提交失败', icon: 'none' }));
  },

  // 长按删除上传的照片（OSS + 记录都删）
  delUpload(e) {
    const key = e.currentTarget.dataset.key;
    tt.showModal({
      title: '删除这张照片？',
      content: '会从云端彻底删除，不可恢复。',
      confirmText: '删除',
      confirmColor: '#c0736a',
      success: (r) => {
        if (!r.confirm) return;
        app.req('/api/mp/delete', 'POST', {
          order_no: this.data.order.order_no, target: 'upload', oss_key: key,
        }).then(() => {
          tt.showToast({ title: '已删除' });
          this.onShow();
        }).catch(err => tt.showToast({ title: err.message, icon: 'none' }));
      },
    });
  },
});
