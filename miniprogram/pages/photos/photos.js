// 相册（生成的照片二级页）：类型筛选 + 系列整组收叠 + 全屏滑动 + 保存/海报/删除
const app = getApp();

// 筛选维度：全部 / 定妆照 / 同款大片（单张）/ 系列组图
const CHIPS = [
  { id: 'all', label: '全部' },
  { id: 'makeup', label: '定妆照' },
  { id: 'moka', label: '同款大片' },
  { id: 'series', label: '系列组图' },
];

Page({
  data: {
    chips: CHIPS,
    chip: 'all',
    photos: [],   // 原始平铺列表
    cells: [],    // 当前筛选下的展示格（系列组图按 job 收叠成一格）
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
      this.rebuild();
    }).catch(() => this.setData({ loading: false }));
  },

  chipTap(e) {
    this.setData({ chip: e.currentTarget.dataset.id });
    this.rebuild();
  },

  // 按筛选条件把 photos 装配成格子：template_series 按 job 收叠成组封面
  rebuild() {
    const chip = this.data.chip;
    const cells = [];
    const groups = {};
    for (const p of this.data.photos) {
      const isSeries = p.kind === 'template_series';
      if (chip === 'makeup' && p.kind !== 'makeup_photo') continue;
      if (chip === 'series' && !isSeries) continue;
      if (chip === 'moka' && (isSeries || p.kind === 'makeup_photo')) continue;
      if (isSeries && p.job) {
        const g = groups[p.job] || (groups[p.job] = {
          isGroup: true, job: p.job, label: '系列组图',
          cover: p.url, urls: [], keys: [], time: p.time,
        });
        g.urls.push(p.url);
        g.keys.push(p.key);
        if (!cells.includes(g)) cells.push(g);
      } else {
        cells.push({ ...p, isGroup: false, urls: [p.url], keys: [p.key] });
      }
    }
    for (const k in groups) groups[k].count = groups[k].urls.length;
    // wx:key 只接受属性名，统一算好 cid
    for (const c of cells) c.cid = c.isGroup ? 'g' + c.job : (c.key || c.url);
    this.setData({ cells });
  },

  // 全屏预览：整组 urls + current，系统自带左右滑动
  previewImg(e) {
    const item = this.data.cells[e.currentTarget.dataset.idx];
    if (!item) return;
    wx.previewImage({
      urls: item.isGroup ? item.urls : this.data.cells.reduce((acc, c) => acc.concat(c.urls), []),
      current: item.isGroup ? item.urls[0] : e.currentTarget.dataset.url,
    });
  },

  showOps(e) {
    const item = this.data.cells[e.currentTarget.dataset.idx];
    if (!item) return;
    if (item.isGroup) {
      wx.showActionSheet({
        itemList: [`整组 ${item.urls.length} 张保存到相册`, '删除整组'],
        success: (r) => {
          if (r.tapIndex === 0) this.saveAll(item.urls);
          else if (r.tapIndex === 1) this.delGroup(item.keys);
        },
      });
      return;
    }
    wx.showActionSheet({
      itemList: ['保存到相册', '生成分享海报', '提意见重生成', '删除这张图'],
      success: (r) => {
        if (r.tapIndex === 0) this.saveImg(item.url);
        else if (r.tapIndex === 1) this.makePoster(item.url);
        else if (r.tapIndex === 2) this.revisePhoto(item.key);
        else if (r.tapIndex === 3) this.delPhoto(item.key);
      },
    });
  },

  // 提意见重生成（与结果页同一链路：/api/mp/revise，每单免费 3 次）
  revisePhoto(key) {
    if (!key) {
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
          order_no: app.globalData.order.order_no, target: 'photo',
          base_key: key, instruction,
        }).then(() => {
          // 反馈 #48/#51：改跳生成中页（进度动画+轮询），不再只弹静态提示
          app.globalData.pendingJob = {
            kind: 'edit_photo', submitted: true,
            payload: { base_key: key, instruction },
          };
          wx.navigateTo({ url: '/pages/generating/generating' });
        }).catch(err => {
          wx.showModal({ title: '提示', content: err.message, showCancel: false });
        });
      },
    });
  },

  // 分享海报：成品图 + 品牌条 + 小程序码（扫码进入带裂变归因，P1 裂变奖励）
  makePoster(url) {
    wx.showLoading({ title: '海报生成中' });
    const order = app.globalData.order || {};
    // 小程序码（可选，失败不挡海报）
    const qrPromise = new Promise((resolve) => {
      app.req('/api/mp/qrcode', 'GET', { order_no: order.order_no })
        .then(res => {
          wx.downloadFile({
            url: res.url,
            success: (r) => resolve(r.tempFilePath),
            fail: () => resolve(null),
          });
        })
        .catch(() => resolve(null));
    });
    wx.downloadFile({
      url,
      success: (dl) => {
        wx.getImageInfo({
          src: dl.tempFilePath,
          success: (info) => {
            qrPromise.then(qrPath => this._drawPoster(dl.tempFilePath, info, qrPath));
          },
          fail: () => { wx.hideLoading(); wx.showToast({ title: '海报生成失败', icon: 'none' }); },
        });
      },
      fail: () => { wx.hideLoading(); wx.showToast({ title: '下载原图失败', icon: 'none' }); },
    });
  },

  _drawPoster(imgPath, info, qrPath) {
    const W = 600, H = 900, STRIP = 130;
    const ctx = wx.createCanvasContext('poster', this);
    // cover 裁切铺满上部
    const scale = Math.max(W / info.width, (H - STRIP) / info.height);
    const w = info.width * scale, h = info.height * scale;
    ctx.drawImage(imgPath, (W - w) / 2, (H - STRIP - h) / 2, w, h);
    // 品牌条
    ctx.setFillStyle('#1c1714');
    ctx.fillRect(0, H - STRIP, W, STRIP);
    ctx.setFillStyle('#fdf8f4');
    ctx.setFontSize(30);
    ctx.setTextAlign(qrPath ? 'left' : 'center');
    ctx.fillText('徐大恩 AI 照相馆', qrPath ? 40 : W / 2, H - STRIP + 50);
    ctx.setFontSize(22);
    ctx.setFillStyle('#c9b8ac');
    ctx.fillText(qrPath ? '不出门，拍好婚纱照 · 扫码试试' : '不出门，拍好婚纱照 · 小程序搜「徐大恩」',
                 qrPath ? 40 : W / 2, H - STRIP + 92);
    // 小程序码（圆角白底衬底）
    if (qrPath) {
      ctx.setFillStyle('#ffffff');
      ctx.beginPath();
      ctx.arc(W - 65, H - STRIP / 2, 52, 0, 2 * Math.PI);
      ctx.fill();
      ctx.drawImage(qrPath, W - 113, H - STRIP / 2 - 48, 96, 96);
    }
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

  // 整组保存：逐张下载存相册
  saveAll(urls) {
    wx.showLoading({ title: `保存中 0/${urls.length}` });
    const step = (i) => {
      if (i >= urls.length) {
        wx.hideLoading();
        wx.showToast({ title: '整组已存到相册' });
        return;
      }
      wx.downloadFile({
        url: urls[i],
        success: (r) => new Promise(res => wx.saveImageToPhotosAlbum({
          filePath: r.tempFilePath, success: res, fail: res,
        })).then(() => {
          wx.showLoading({ title: `保存中 ${i + 1}/${urls.length}` });
          step(i + 1);
        }),
        fail: () => { wx.hideLoading(); wx.showToast({ title: '保存失败，检查相册权限', icon: 'none' }); },
      });
    };
    step(0);
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

  // 整组删除：逐张调删除接口
  delGroup(keys) {
    wx.showModal({
      title: `删除整组 ${keys.length} 张？`,
      content: '会从云端彻底删除，不可恢复。',
      confirmText: '删除整组',
      confirmColor: '#c0736a',
      success: (r) => {
        if (!r.confirm) return;
        const order_no = app.globalData.order.order_no;
        Promise.all(keys.map(key => app.req('/api/mp/delete', 'POST', {
          order_no, target: 'photo', oss_key: key,
        }))).then(() => {
          wx.showToast({ title: '已删除整组' });
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
