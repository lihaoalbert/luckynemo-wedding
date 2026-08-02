// 对话流主页：AI 引导完成 认证→上传→选装→免费生成
const app = getApp();

const WELCOME = [
  '你好呀，我是徐大恩的 AI 小助手 💌',
  '从今天开始，你们的婚纱照可以不出门就拍好——先免费送你们 1 张试试手艺。',
  '第一步很简单，先完成一次「真人认证」。这是为了保护你们的脸：认证过的照片，只用来给你们自己生成作品，交付即删。',
];

Page({
  data: {
    messages: [],      // [{role:'ai'|'me', text, action?}]
    step: 'welcome',   // welcome → mode → auth → wardrobe
    order: null,
    authUrl: '',
    busy: false,
    dockText: '上传我们的照片 →',
    dockPage: '/pages/upload/upload',
    inputMode: '',      // '' | 'text' | 'voice'
    inputValue: '',
    recording: false,
    pendingImages: [],  // 聊天里待发送的图片 [{path, key, status}]
  },

  onLoad() {
    // 老用户跳过欢迎语（首次用户才看引导三句话）
    const saved = wx.getStorageSync('mp_order');
    if (!(saved && saved.order_no)) {
      this.setData({ messages: WELCOME.map(t => ({ role: 'ai', text: t })) });
    }
    this.ensureOrder();
  },

  ensureOrder() {
    // 协同创作：带 share 参数进入 → 加入对方订单
    const share = app.globalData.pendingShare;
    if (share) {
      app.globalData.pendingShare = '';
      app.globalData.tokenPromise.then(() => {
        app.req('/api/mp/join', 'POST', { share_token: share, open_token: app.globalData.openToken })
          .then(res => {
            app.globalData.myRole = res.role || 'A';
            wx.setStorageSync('mp_role', app.globalData.myRole);
            this.setData({ order: res.order });
            app.globalData.order = res.order;
            wx.setStorageSync('mp_order', res.order);
            if (res.role === 'B') {
              this.push('ai', '欢迎加入 💌 你们的订单已经连在一起啦，完成你的认证后就可以继续创作～');
            }
            this._resumeKey = null;
            this.resume(res.order);
          })
          .catch(e => this.push('ai', '邀请链接好像失效了：' + e.message));
      });
      return;
    }
    const saved = wx.getStorageSync('mp_order');
    if (saved && saved.order_no) {
      app.globalData.myRole = wx.getStorageSync('mp_role') || 'A';
      this.setData({ order: saved });
      app.globalData.order = saved;
      this.resume(saved);
      return;
    }
    // 等 wx.login 拿到 openid 后再建订单，否则 open_token 为空会 422
    app.globalData.tokenPromise.then(() => {
      app.req('/api/mp/order', 'POST', {
        open_token: app.globalData.openToken, ref: app.globalData.ref || undefined,
      })
        .then(res => {
          this.setData({ order: res.order });
          app.globalData.order = res.order;
          wx.setStorageSync('mp_order', res.order);
          this.resume(res.order);
        })
        .catch(e => this.push('ai', '服务器开小差了，' + e.message));
    });
  },

  resume(order) {
    // 防重复推送：模式+认证+进度状态没变就不重复发消息
    const needRoles = order.mode === 'couple' ? ['A', 'B'] : ['A'];
    const members = order.members || {};
    const pending = order.mode ? needRoles.filter(r => !(members[r] && members[r].auth_ok)) : [];

    // 第 0 步：选模式（婚纱照双人 / 个人写真单人）
    if (!order.mode) {
      const key = 'mode';
      if (this._resumeKey === key) return;
      this._resumeKey = key;
      this.setData({ step: 'mode' });
      this.push('ai', '先告诉我，今天想拍什么？');
      this.push('ai', '👰 婚纱照：你们两个人一起，需要先各自完成真人认证', { text: '拍婚纱照 →', kind: 'mode', mode: 'couple' });
      this.push('ai', '📷 个人写真：就你一个人，妆造服装场景随心挑', { text: '拍个人写真 →', kind: 'mode', mode: 'solo' });
      return;
    }

    // 第 1 步：成员认证（婚纱照需要新娘+新郎各自认证）
    if (pending.length) {
      const key = 'auth:' + pending.join(',');
      if (this._resumeKey === key) return;
      this._resumeKey = key;
      this.setData({ step: 'auth' });
      const doneWho = needRoles.filter(r => members[r] && members[r].auth_ok)
        .map(r => (r === 'A' ? (order.mode === 'couple' ? '新娘' : '你') : '新郎'));
      if (doneWho.length) this.push('ai', `已完成认证：${doneWho.join('、')} ✅`);
      pending.forEach(r => {
        const who = r === 'A' ? (order.mode === 'couple' ? '新娘' : '你') : '新郎';
        this.push('ai', `请${who}完成真人认证（刷个脸，30 秒）。认证是为了保护你们的脸：照片只用来给你们自己生成作品，交付即删。`,
          { text: `${who}去认证 →`, kind: 'auth', role: r });
      });
      this.push('ai', '认证完成后点这里，我马上刷新状态', { text: '我已完成认证 ✓', kind: 'checkauth' });
      return;
    }

    // 认证齐全 → 按服务端真实进度续走：没照片→上传；没定妆→定妆；已定妆→选衣服
    this.setData({ step: 'wardrobe' });
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const hasPhotos = (res.photo_count || 0) > 0;
      const makeupDone = (res.jobs || []).some(j => j.kind === 'makeup_photo' && j.status === 'done');
      const key = `go:${hasPhotos}:${makeupDone}`;
      if (this._resumeKey === key) return;
      this._resumeKey = key;
      if (!hasPhotos) {
        this.setData({ dockText: '上传我们的照片 →', dockPage: '/pages/upload/upload' });
        this.push('ai', '认证都通过啦 👏 接下来上传照片，然后定妆、选衣服、选动作，一张美美的照片就出来啦～', { text: '去上传照片', page: '/pages/upload/upload' });
      } else if (!makeupDone) {
        this.setData({ dockText: '去定妆 →', dockPage: '/pages/makeup/makeup' });
        this.push('ai', '你的照片已经在我这里啦，直接去定妆吧～', { text: '去定妆 →', page: '/pages/makeup/makeup' });
      } else {
        this.setData({ dockText: '去挑模卡 →', dockPage: '/pages/moka/moka' });
        this.push('ai', '照片和定妆照都在，挑一张模卡一键同款吧～', { text: '去挑模卡 →', page: '/pages/moka/moka' });
        this.push('ai', '想要独一无二的一张？把喜欢的样片发给我，再说一句想法，我帮你定制专属模卡 ✨');
        this.push('ai', '想换个妆容再拍一版？点这里', { text: '换个妆容 →', page: '/pages/makeup/makeup' });
        this.push('ai', '想自己搭配服装场景？进高级定制', { text: '高级定制 →', page: '/pages/wardrobe/wardrobe' });
      }
    }).catch(() => {});
  },

  setMode(mode) {
    wx.showLoading({ title: '好的…' });
    app.req('/api/mp/order', 'POST', {
      open_token: app.globalData.openToken, order_no: this.data.order.order_no, mode,
    }).then(res => {
      wx.hideLoading();
      this.setData({ order: res.order });
      app.globalData.order = res.order;
      wx.setStorageSync('mp_order', res.order);
      this.push('me', mode === 'couple' ? '拍婚纱照' : '拍个人写真');
      this.resume(res.order);
    }).catch(e => {
      wx.hideLoading();
      wx.showToast({ title: e.message, icon: 'none' });
    });
  },

  openAuth(role) {
    // 每次点击都新建会话（H5 链接一次性且限时，永不复用）
    wx.showLoading({ title: '创建认证链接…' });
    app.req('/api/mp/auth-session', 'GET', { order_no: this.data.order.order_no, role })
      .then(res => {
        wx.hideLoading();
        // 注：反代 web-view 方案已被火山 H5 的域名校验拦截（初始化 API 拒绝跨域调用），
        // 只能复制链接到浏览器/微信聊天里打开
        wx.setClipboardData({
          data: res.url,
          success: () => wx.showModal({
            title: '去认证',
            content: '链接已复制。粘贴到微信任意聊天（比如文件传输助手）点开，或用手机浏览器打开。完成刷脸后回到这里点「我已完成认证」',
            confirmText: '我已完成',
            cancelText: '稍后',
            success: (r) => { if (r.confirm) this.checkAuth(); },
          }),
        });
      })
      .catch(e => {
        wx.hideLoading();
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  push(role, text, action, images) {
    const messages = this.data.messages.concat([{ role, text, action, images }]);
    this.setData({ messages });
    setTimeout(() => {
      const q = wx.createSelectorQuery();
      q.select('#scroll').scrollOffset();
      wx.pageScrollTo({ scrollTop: 99999, duration: 200 });
    }, 50);
  },

  onAction(e) {
    const action = e.currentTarget.dataset.action;
    if (!action) return;
    if (action.kind === 'mode') {
      this.setMode(action.mode);
      return;
    }
    if (action.kind === 'auth') {
      this.openAuth(action.role || 'A');
      return;
    }
    if (action.kind === 'checkauth') {
      this.checkAuth();
      return;
    }
    if (action.kind === 'diy_use') {
      this.useDiyMoka(action);
      return;
    }
    if (action.page) wx.navigateTo({ url: action.page });
  },

  checkAuth() {
    this.setData({ busy: true });
    // 先走 auth-status：回调没到时服务端会主动用 BytedToken 查认证结果
    app.req('/api/mp/auth-status', 'GET', { order_no: this.data.order.order_no })
      .then(res => {
        this.setData({ busy: false, order: res.order });
        wx.setStorageSync('mp_order', res.order);
        if (res.order.auth_ok) {
          this.push('me', '我已完成认证');
          this.resume(res.order);
        } else {
          wx.showToast({ title: '还没查到认证结果，完成后再点我哦', icon: 'none' });
        }
      })
      .catch(e => {
        this.setData({ busy: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  goUpload() {
    wx.navigateTo({ url: this.data.dockPage });
  },

  // ---- 自然语言输入 ----
  openInput() { this.setData({ inputMode: 'text' }); },
  closeInput() { this.setData({ inputMode: '', inputValue: '', recording: false }); },
  onInput(e) { this.setData({ inputValue: e.detail.value }); },

  // ---- 语音输入（微信同声传译插件：录音 → 文字 → 填入输入框确认）----
  openVoice() {
    this.setData({ inputMode: 'voice' });
    if (!this._si) {
      try {
        const plugin = requirePlugin('WechatSI');
        this._si = plugin.getRecordRecognitionManager();
        this._si.onStop = (res) => {
          this.setData({ recording: false });
          if (res.result) {
            // 识别结果填入打字框，用户确认/修改后再发送
            this.setData({ inputMode: '', inputValue: res.result });
          } else {
            this.setData({ inputMode: '' });
            wx.showToast({ title: '没听清，再说一次？', icon: 'none' });
          }
        };
        this._si.onError = () => {
          this.setData({ recording: false, inputMode: '' });
          wx.showToast({ title: '语音识别失败，请重试', icon: 'none' });
        };
      } catch (e) {
        this.setData({ inputMode: '' });
        wx.showToast({ title: '语音插件未就绪', icon: 'none' });
      }
    }
  },

  closeVoice() {
    if (this.data.recording && this._si) this._si.stop();
    this.setData({ inputMode: '', recording: false });
  },

  startVoice() {
    if (!this._si) return;
    wx.authorize({
      scope: 'scope.record',
      success: () => {
        this.setData({ recording: true });
        this._si.start({ duration: 30000, lang: 'zh_CN' });
      },
      fail: () => wx.showToast({ title: '需要录音权限哦', icon: 'none' }),
    });
  },

  stopVoice() {
    if (!this.data.recording) return;
    this._si.stop();
  },

  // ---- 聊天里发图片（反馈截图 / 新底图两用）----
  chooseImage() {
    if (!this.data.order) return;
    wx.chooseMedia({
      count: 3 - this.data.pendingImages.length,
      mediaType: ['image'],
      success: (res) => {
        res.tempFiles.forEach(f => this.uploadChatImage(f.tempFilePath));
        this.setData({ inputMode: 'text' });
      },
    });
  },

  uploadChatImage(path) {
    const pendingImages = this.data.pendingImages.concat([{ path, key: '', status: '上传中' }]);
    this.setData({ pendingImages });
    const idx = pendingImages.length - 1;
    app.req('/api/uploads/sign', 'POST', {
      contact: this.data.order.order_no + '-chat',
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
          const imgs = this.data.pendingImages.slice();
          imgs[idx].status = r.statusCode < 300 ? '完成' : '失败';
          imgs[idx].key = signed.fields.key;
          this.setData({ pendingImages: imgs });
        },
        fail: () => {
          const imgs = this.data.pendingImages.slice();
          imgs[idx].status = '失败';
          this.setData({ pendingImages: imgs });
        },
      });
    }).catch(() => {});
  },

  removePending(e) {
    const imgs = this.data.pendingImages.slice();
    imgs.splice(e.currentTarget.dataset.idx, 1);
    this.setData({ pendingImages: imgs });
  },

  sendChat() {
    const message = this.data.inputValue.trim();
    const images = this.data.pendingImages.filter(i => i.key).map(i => i.key);
    if (!message && !images.length) return;
    if (this.data.pendingImages.some(i => i.status === '上传中')) {
      wx.showToast({ title: '图片还在上传中', icon: 'none' });
      return;
    }
    if (!this.data.order) {
      wx.showToast({ title: '订单还没准备好，稍等一下', icon: 'none' });
      return;
    }
    const localPaths = this.data.pendingImages.map(i => i.path);
    this.setData({ inputValue: '', pendingImages: [] });
    if (message) this.push('me', message);
    if (localPaths.length) this.push('me', '', null, localPaths);
    this.push('ai', '…');
    // 带最近对话上下文，M3 才能听懂"嗯/提交吧"这类确认；带图的消息标注图数
    const history = this.data.messages.slice(-6).map(m =>
      `${m.role === 'me' ? '用户' : '助手'}：${m.text || ''}${m.images ? `[${m.images.length}张图]` : ''}`);
    app.req('/api/mp/chat', 'POST', { order_no: this.data.order.order_no, message, images, history })
      .then(res => {
        this.replaceLast(res.reply || '我在呢～');
        this.runChatAction(res.action || {});
      })
      .catch(() => this.replaceLast('网络有点卡，你再说一次好吗？'));
  },

  replaceLast(text) {
    const messages = this.data.messages.slice();
    if (messages.length && messages[messages.length - 1].text === '…') {
      messages[messages.length - 1] = { role: 'ai', text };
    } else {
      messages.push({ role: 'ai', text });
    }
    this.setData({ messages });
    setTimeout(() => wx.pageScrollTo({ scrollTop: 99999, duration: 200 }), 50);
  },

  runChatAction(action) {
    if (action.type === 'navigate' && action.page) {
      setTimeout(() => wx.navigateTo({ url: action.page }), 800);
    } else if (action.type === 'update_selection' && action.selection) {
      const selection = Object.assign(app.globalData.selection || {}, action.selection);
      app.globalData.selection = selection;
    } else if (action.type === 'regenerate_makeup' && action.page) {
      setTimeout(() => wx.navigateTo({ url: action.page }), 800);
    } else if ((action.type === 'show_result' || action.type === 'show_uploads') && action.photos && action.photos.length) {
      this.push('ai', '', null, action.photos);
    } else if (action.type === 'set_mode' && action.mode) {
      const order = Object.assign({}, this.data.order, { mode: action.mode });
      this.setData({ order });
      app.globalData.order = order;
      wx.setStorageSync('mp_order', order);
      this._resumeKey = null;  // 模式变了，重新路由
      this.resume(order);
    } else if (action.type === 'custom_moka') {
      this.pollDiyMoka();
    } else if (action.type === 'generate_photo' && action.template_key) {
      // 直接出片：刚发的图/最近聊天图当模板 + 最新定妆照锚点，走 generating 页统一创建任务
      app.globalData.pendingJob = {
        kind: 'template_photo',
        payload: {
          custom_template_key: action.template_key,
          mode: action.mode || 'couple',
          anchor_key: action.anchor_key || '',
          anchor_key_b: action.anchor_key_b || '',
          swap_imgs: [],
          swap_note: action.note || '',
        },
      };
      setTimeout(() => wx.navigateTo({ url: '/pages/generating/generating' }), 800);
    } else if (action.type === 'delete_assets') {
      // 资产已删，清空本地进度并重新走流程
      app.globalData.selection = {};
      if (action.target === 'reset') {
        const order = Object.assign({}, this.data.order, { mode: '', members: {} });
        this.setData({ order });
        app.globalData.order = order;
        wx.setStorageSync('mp_order', order);
        this._resumeKey = null;
        setTimeout(() => this.resume(order), 800);
      }
    }
  },

  // ---- 定制模卡：chat 动作触发后轮询任务，出图后给"用这张出片"按钮 ----
  pollDiyMoka() {
    this.push('ai', '定制模卡绘制中，大概 1 分钟，好了我马上给你看 🎨');
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      app.req('/api/mp/order/' + this.data.order.order_no).then(res => {
        const job = (res.jobs || []).find(j => j.kind === 'custom_moka');
        if (!job) return;
        if (job.status === 'done' && job.result && job.result.url) {
          clearInterval(timer);
          this.push('ai', '你的专属模卡画好啦 ✨ 满意就点下面按钮出片，想调整直接打字告诉我（比如"背景再亮一点"）', null, [job.result.url]);
          this.push('ai', '', { text: '用这张出片 →', kind: 'diy_use', key: job.result.oss_key, mode: job.result.mode || 'couple' });
        } else if (job.status === 'failed') {
          clearInterval(timer);
          this.push('ai', '这次定制没成功：' + ((job.result && job.result.error) || '请换个描述再试试'));
        } else if (tries >= 40) {
          clearInterval(timer);
          this.push('ai', '画得有点久，稍后跟我说"看我的定制模卡"，我再帮你看看～');
        }
      }).catch(() => {});
    }, 5000);
  },

  useDiyMoka(action) {
    const selection = app.globalData.selection || {};
    const couple = action.mode === 'couple';
    app.globalData.pendingJob = {
      kind: 'template_photo',
      payload: {
        custom_template_key: action.key,
        mode: couple ? 'couple' : 'solo',
        anchor_key: selection.anchor_key || '',
        anchor_key_b: couple ? (selection.anchor_key_b || '') : '',
        swap_imgs: [],
        swap_note: '',
      },
    };
    this.push('me', '用这张出片');
    wx.navigateTo({ url: '/pages/generating/generating' });
  },

  previewImg(e) {
    wx.previewImage({ urls: [e.currentTarget.dataset.url] });
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
