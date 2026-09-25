// AI 小导演 · 证件照拍摄页（本功能核心）
// 状态机：shooting（实时指引）→ countdown（达标倒计时 3-2-1）→ preview（预览确认）
//        → bgcolor（选底色）→ paywall（2 元导出，额度够则跳过）→ processing（冲印中）→ done（成片）
// 镜头对被拍者、屏幕对持机的摄影师：大字 hint 给摄影师看，cue 台词卡可以照着喊
const app = getApp();
const { track } = require('../../utils/track');
const specs = require('../../utils/idphoto_specs');
const rules = require('../../utils/idphoto_rules');
const faceDetect = require('../../utils/face_detect');

const OK_STREAK_NEED = 5;    // 连续 5 帧 ok（约 1 秒）才算达标
const FRAME_INTERVAL = 150;  // 帧处理节流（约 6-7fps），处理中时直接丢帧
const SPEAK_GAP = 5000;      // 同一句台词 5 秒内不重复播报

Page({
  data: {
    state: 'shooting',   // shooting/countdown/preview/bgcolor/paywall/processing/done/nocamera
    spec: null,
    devicePosition: 'back',
    hint: '把脸放进圆圈里',
    cue: '镜头里还没看到人哦～',
    okNow: false,        // 当前帧是否达标（hint 变绿）
    modelText: 'AI 小导演上场中…',  // 模型加载提示；空串=就绪
    manualMode: false,   // 模型加载失败降级：手动拍摄
    count: 3,            // 倒计时数字
    photoPath: '',       // 抓拍原片本地路径
    uploading: false,
    bgOptions: [],       // [{key,name,color}]
    bgSelected: '',
    paying: false,       // 已发起支付、等待额度到账
    resultUrl: '',       // 成片
    printUrl: '',        // 打印排版版（后端可能不出第二张）
  },

  onLoad(options) {
    const spec = specs.byId(options && options.spec_id);
    this.setData({
      spec,
      bgOptions: spec.bg.map(b => ({ key: b, name: specs.BG_NAMES[b], color: specs.BG_COLORS[b] })),
      bgSelected: spec.bg[0],
    });
    wx.setNavigationBarTitle({ title: spec.name + ' · AI 证件照' });
    this._ttsCache = {};   // text → mp3 url
    this._spokenAt = {};   // text → 上次播报时间戳
    this._okStreak = 0;
    this._passed = false;  // 本次拍摄是否已 track 过首次达标
    this._lastFace = null;
    this.ensureOrder();
    this.checkCameraAuth();
    // 模型惰性加载：完成后更新提示；失败自动降级手动模式
    faceDetect.init().then(st => {
      this.setData(st === 'ready'
        ? { modelText: '', manualMode: false }
        : { modelText: '手动模式：对准框线，自己按快门', manualMode: true, hint: '手动对准框线拍摄' });
    });
  },

  onReady() {
    this._cameraCtx = wx.createCameraContext();
    // 实时帧：onCameraFrame 回调里做节流 + 推理
    this._frameListener = this._cameraCtx.onCameraFrame(frame => this.onFrame(frame));
    this._frameListener.start();
  },

  onUnload() {
    this._teardown();
  },

  _teardown() {
    if (this._frameListener) this._frameListener.stop();
    clearInterval(this._countTimer);
    clearInterval(this._poller);
    clearInterval(this._payPoller);
    if (this._audio) { this._audio.destroy(); this._audio = null; }
  },

  // ---- 相机权限 ----
  checkCameraAuth() {
    wx.authorize({
      scope: 'scope.camera',
      fail: () => this.setData({ state: 'nocamera' }),
    });
  },

  onCameraError() {
    this.setData({ state: 'nocamera' });
  },

  openSetting() {
    wx.openSetting({
      success: (r) => {
        if (r.authSetting && r.authSetting['scope.camera']) {
          this.setData({ state: 'shooting' });
        }
      },
    });
  },

  // ---- 订单确保（证件照可独立入口进入，不一定走过 chat 流程）----
  ensureOrder() {
    const saved = app.globalData.order || wx.getStorageSync('mp_order');
    if (saved && saved.order_no) {
      app.globalData.order = saved;
      this.orderNo = saved.order_no;
      return Promise.resolve();
    }
    return app.globalData.tokenPromise.then(() =>
      app.req('/api/mp/order', 'POST', {
        open_token: app.globalData.openToken, ref: app.globalData.ref || undefined,
      })
    ).then(res => {
      app.globalData.order = res.order;
      wx.setStorageSync('mp_order', res.order);
      this.orderNo = res.order.order_no;
    }).catch(() => {});
  },

  // ---- 实时帧处理：推理 → 规则 → 大字指引 + 播报 ----
  onFrame(frame) {
    if (this.data.state !== 'shooting' || this.data.manualMode) return;
    if (this._busy) return;
    const now = Date.now();
    if (now - (this._lastFrameAt || 0) < FRAME_INTERVAL) return;
    this._lastFrameAt = now;
    this._busy = true;
    const w = frame.width, h = frame.height;
    const light = this._sampleLight(frame.data, w, h);
    faceDetect.detect(frame.data, w, h).then(face => {
      this._busy = false;
      if (this.data.state !== 'shooting') return;
      if (face.has_face && face.w) {
        this._lastFace = { x: face.x, y: face.y, w: face.w, h: face.h };
      }
      const r = rules.evaluate({
        has_face: face.has_face && !!face.w,
        face: face.w ? { x: face.x, y: face.y, w: face.w, h: face.h } : null,
        yaw: face.yaw, roll: face.roll,
        brightness: light.brightness, light_diff: light.diff,
      });
      this._applyRule(r);
      this._drawGuides(r.code === 'ok');
    }).catch(() => { this._busy = false; });
  },

  // 亮度估算：RGBA 帧抽样（每 16 像素取 1），同时算左右半幅亮度差（阴阳脸）
  _sampleLight(buf, w, h) {
    const px = new Uint8Array(buf);
    let sum = 0, n = 0, left = 0, ln = 0, right = 0, rn = 0;
    const step = 16;
    for (let y = 0; y < h; y += step) {
      for (let x = 0; x < w; x += step) {
        const i = (y * w + x) * 4;
        const luma = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
        sum += luma; n += 1;
        if (x < w / 2) { left += luma; ln += 1; } else { right += luma; rn += 1; }
      }
    }
    return {
      brightness: n ? sum / n : 128,
      diff: (ln && rn) ? Math.abs(left / ln - right / rn) : 0,
    };
  },

  _applyRule(r) {
    this.setData({ hint: r.hint, cue: r.cue, okNow: r.code === 'ok' });
    // 播报：每帧都尝试，speak 内部按文案 5 秒去重 + url 缓存
    this.speak(r.cue);
    if (r.code === 'ok') {
      this._okStreak += 1;
      if (this._okStreak >= OK_STREAK_NEED && this.data.state === 'shooting') {
        this.startCountdown();
      }
    } else {
      this._okStreak = 0;
    }
  },

  // ---- 达标 → 倒计时 → 抓拍 ----
  startCountdown() {
    if (!this._passed) {
      this._passed = true;
      track('idphoto_pass', { spec_id: this.data.spec.id });
    }
    this.setData({ state: 'countdown', count: 3, hint: '很好，保持不动！' });
    this.speak('很好！保持不动，3、2、1～');
    this._countTimer = setInterval(() => {
      const c = this.data.count - 1;
      if (c <= 0) {
        clearInterval(this._countTimer);
        this.snap();
      } else {
        this.setData({ count: c });
      }
    }, 1000);
  },

  snap() {
    this._cameraCtx.takePhoto({
      quality: 'high',
      success: (res) => {
        track('idphoto_shot', { spec_id: this.data.spec.id, auto: !this.data.manualMode });
        this._okStreak = 0;
        this.setData({ state: 'preview', photoPath: res.tempImagePath });
        this.uploadPhoto(res.tempImagePath);
      },
      fail: () => {
        // 抓拍失败回到拍摄态重试，不卡流程
        this.setData({ state: 'shooting', count: 3 });
      },
    });
  },

  manualShot() {
    this.snap();
  },

  switchCamera() {
    this.setData({ devicePosition: this.data.devicePosition === 'back' ? 'front' : 'back' });
  },

  // ---- 原片上传 OSS（预览时后台进行，"用这张"前必须传完）----
  uploadPhoto(path) {
    if (!this.orderNo) {
      // 订单还没建好（独立入口直接进入的场景）：先补订单再重传
      this.ensureOrder().then(() => {
        if (this.orderNo) this.uploadPhoto(path);
      });
      return;
    }
    this.photoOssKey = '';
    this.setData({ uploading: true });
    app.req('/api/uploads/sign', 'POST', {
      order_no: this.orderNo,
      filename: 'idphoto-' + Date.now() + '.jpg',
      content_type: 'image/jpeg',
      size: 1,
    }).then(signed => {
      wx.uploadFile({
        url: signed.url,
        filePath: path,
        name: 'file',
        formData: signed.fields,
        success: (r) => {
          if (r.statusCode >= 200 && r.statusCode < 300) {
            this.photoOssKey = signed.key;
            this.setData({ uploading: false });
          } else {
            this.uploadFail();
          }
        },
        fail: () => this.uploadFail(),
      });
    }).catch(() => this.uploadFail());
  },

  uploadFail() {
    this.setData({ uploading: false });
    wx.showToast({ title: '原片上传失败，点「用这张」重试', icon: 'none' });
  },

  // ---- 预览确认 ----
  usePhoto() {
    if (this.data.uploading) {
      wx.showToast({ title: '原片还在上传中…', icon: 'none' });
      return;
    }
    if (!this.photoOssKey) {
      // 上传失败过：重传一次再继续
      if (!this.data.photoPath) return;
      this.uploadPhoto(this.data.photoPath);
      return;
    }
    this.setData({ state: 'bgcolor' });
  },

  retake() {
    this._passed = false;
    this._okStreak = 0;
    this.setData({ state: 'shooting', photoPath: '', hint: '把脸放进圆圈里', cue: '再来一次，这次一定行～' });
  },

  // ---- 选底色 ----
  pickBg(e) {
    this.setData({ bgSelected: e.currentTarget.dataset.key });
  },

  confirmBg() {
    this.checkExport();
  },

  // ---- 导出：额度够直接建任务，不够先付 2 元 ----
  checkExport() {
    wx.showLoading({ title: '查额度…' });
    app.req('/api/mp/me', 'GET', { order_no: this.orderNo }).then(res => {
      wx.hideLoading();
      const count = (res.quota && res.quota.idphoto_count) || 0;
      if (count > 0) {
        this.createJob();
      } else {
        this.setData({ state: 'paywall', paying: false });
      }
    }).catch(e => {
      wx.hideLoading();
      wx.showToast({ title: e.message, icon: 'none' });
    });
  },

  pay() {
    track('idphoto_export_pay', { spec_id: this.data.spec.id, stage: 'invoke' });
    // vpay 内部完成 prepare → requestVirtualPayment → confirm 补偿到账（app.js 通用流程），
    // 这里发起后轮询额度，到账即自动建任务
    app.vpay('idphoto2', '证件照导出');
    this.setData({ paying: true });
    clearInterval(this._payPoller);
    let tries = 0;
    this._payPoller = setInterval(() => {
      tries += 1;
      app.req('/api/mp/me', 'GET', { order_no: this.orderNo }).then(res => {
        const count = (res.quota && res.quota.idphoto_count) || 0;
        if (count > 0) {
          clearInterval(this._payPoller);
          track('idphoto_export_pay', { spec_id: this.data.spec.id, stage: 'paid' });
          wx.showToast({ title: '到账啦，开始冲印' });
          this.createJob();
        } else if (tries >= 15) {
          clearInterval(this._payPoller);
          this.setData({ paying: false });
        }
      }).catch(() => {});
    }, 4000);
  },

  repaid() {
    // 「我已完成支付」手动刷新
    this.checkExport();
  },

  // ---- 建任务 + 轮询 ----
  createJob() {
    this.setData({ state: 'processing' });
    app.req('/api/mp/job', 'POST', {
      order_no: this.orderNo,
      open_token: app.globalData.openToken,
      kind: 'idphoto',
      payload: {
        spec_id: this.data.spec.id,
        bg_color: this.data.bgSelected,
        photo_oss_key: this.photoOssKey,
        face_box: this._lastFace || { x: 0.3, y: 0.2, w: 0.4, h: 0.5 },
      },
    }).then(() => this.pollJob()).catch(e => {
      wx.showModal({
        title: '提交失败', content: e.message || '请稍后再试', showCancel: false,
        success: () => this.setData({ state: 'bgcolor' }),
      });
    });
  },

  pollJob() {
    clearInterval(this._poller);
    let tries = 0;
    this._poller = setInterval(() => {
      tries += 1;
      app.req('/api/mp/order/' + this.orderNo).then(res => {
        // 取最新一条 idphoto 任务（jobs 顺序不假设，按 id 取最大）
        const job = (res.jobs || []).filter(j => j.kind === 'idphoto')
          .reduce((m, j) => (!m || (j.id || 0) > (m.id || 0) ? j : m), null);
        if (!job) return;
        if (job.status === 'done' && job.result && job.result.url) {
          clearInterval(this._poller);
          this.setData({
            state: 'done',
            resultUrl: job.result.url,
            printUrl: job.result.print_url || '',
          });
        } else if (job.status === 'failed') {
          clearInterval(this._poller);
          wx.showModal({
            title: '冲印失败',
            content: (job.result && job.result.error) || '这张照片没冲出来，换一张试试',
            showCancel: false,
            success: () => this.setData({ state: 'preview' }),
          });
        } else if (tries >= 60) {
          clearInterval(this._poller);
          wx.showModal({
            title: '冲印有点慢',
            content: '照片还在路上，稍后可到「我的 → 相册」查看',
            showCancel: false,
            success: () => this.setData({ state: 'preview' }),
          });
        }
      }).catch(() => {});
    }, 4000);
  },

  // ---- 成片 ----
  savePhoto(e) {
    const url = (e && e.currentTarget.dataset.url) || this.data.resultUrl;
    if (!url) return;
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
      fail: () => wx.showToast({ title: '下载失败，稍后再试', icon: 'none' }),
      complete: () => wx.hideLoading(),
    });
  },

  previewResult(e) {
    const url = e.currentTarget.dataset.url;
    if (url) wx.previewImage({ urls: [url] });
  },

  again() {
    this._passed = false;
    this._okStreak = 0;
    this._lastFace = null;
    this.photoOssKey = '';
    this.setData({
      state: 'shooting', photoPath: '', resultUrl: '', printUrl: '',
      count: 3, hint: '把脸放进圆圈里', cue: '换张更美的，走起～',
    });
  },

  goMoka() {
    track('idphoto_to_moka', { spec_id: this.data.spec.id });
    wx.navigateTo({ url: '/pages/moka/moka' });
  },

  // ---- TTS 播报（本地 Map 缓存 text→url，同一句 5 秒内不重复）----
  speak(text) {
    if (!text) return;
    const now = Date.now();
    if (this._spokenAt[text] && now - this._spokenAt[text] < SPEAK_GAP) return;
    this._spokenAt[text] = now;
    const cached = this._ttsCache[text];
    if (cached) return this._playAudio(cached);
    app.req('/api/mp/tts', 'POST', { open_token: app.globalData.openToken, text })
      .then(res => {
        if (res && res.url) {
          this._ttsCache[text] = res.url;
          this._playAudio(res.url);
        }
      })
      .catch(() => {});  // 播报失败不影响拍摄
  },

  _playAudio(url) {
    if (!this._audio) this._audio = wx.createInnerAudioContext();
    this._audio.src = url;
    this._audio.play();
  },

  // ---- 构图引导 overlay（canvas 2d 同层渲染）----
  _drawGuides(ok) {
    const spec = this.data.spec;
    if (!spec) return;
    const draw = (canvas, ctx, W, H) => {
      ctx.clearRect(0, 0, W, H);
      const stroke = ok ? '#58a06b' : 'rgba(201, 145, 63, 0.95)';
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 3;
      ctx.setLineDash([12, 10]);
      // 头部椭圆：按规格的头部占比区间中值画目标圈
      const eh = (spec.head_min + spec.head_max) / 2 * H;
      const ew = eh * 0.72;
      const cx = W / 2, cy = H * 0.42;
      ctx.beginPath();
      if (ctx.ellipse) {
        ctx.ellipse(cx, cy, ew / 2, eh / 2, 0, 0, Math.PI * 2);
      } else {
        // 老基础库无 ellipse：缩放 arc 兜底
        ctx.save();
        ctx.translate(cx, cy);
        ctx.scale(ew / 2, eh / 2);
        ctx.arc(0, 0, 1, 0, Math.PI * 2);
        ctx.restore();
      }
      ctx.stroke();
      // 双肩水平线
      ctx.beginPath();
      ctx.moveTo(W * 0.12, H * 0.78);
      ctx.lineTo(W * 0.88, H * 0.78);
      ctx.stroke();
      // 头顶留白线
      const topY = cy - eh / 2 - H * 0.05;
      ctx.beginPath();
      ctx.moveTo(W * 0.3, topY);
      ctx.lineTo(W * 0.7, topY);
      ctx.stroke();
      ctx.setLineDash([]);
    };
    if (this._canvasNode) {
      draw(this._canvasNode, this._canvasCtx, this._canvasW, this._canvasH);
      return;
    }
    wx.createSelectorQuery().in(this).select('#guides')
      .fields({ node: true, size: true }).exec((res) => {
        if (!res || !res[0] || !res[0].node) return;
        const canvas = res[0].node;
        const dpr = wx.getWindowInfo ? wx.getWindowInfo().pixelRatio : 2;
        canvas.width = res[0].width * dpr;
        canvas.height = res[0].height * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        this._canvasNode = canvas;
        this._canvasCtx = ctx;
        this._canvasW = res[0].width;
        this._canvasH = res[0].height;
        draw(canvas, ctx, this._canvasW, this._canvasH);
      });
  },
});
