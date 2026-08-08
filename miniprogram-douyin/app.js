// 徐大恩 LuckyNemo 抖音小程序（由微信版移植，tt.* 体系）
// 登录：tt.login → /api/dy/login（openid 前缀 dy-）；支付：担保支付 tt.pay（iOS 无虚拟支付通道，整端隐藏付费入口）
const API_BASE = 'https://luckynemo.ibi.ren';

App({
  globalData: {
    apiBase: API_BASE,
    openToken: '',
    order: null,
    myRole: 'A',       // 协同创作：A=订单创建者，B=被邀请加入者
    pendingShare: '',
    ref: '',
    canPay: true,      // iOS 端 false：抖音不支持虚拟支付，付费入口全部隐藏（审核红线：禁止任何引导文案）
  },
  onLaunch(options) {
    // 分享进入：share=协同创作加入订单；ref=裂变来源（分享卡片/海报小程序码 scene=r_xxx）
    const query = (options && options.query) || {};
    if (query.share) this.globalData.pendingShare = query.share;
    if (query.ref) this.globalData.ref = query.ref;
    if (query.scene) {
      // 小程序码进入：scene=r_<share_token>（URL 编码过）
      const scene = decodeURIComponent(query.scene);
      if (scene.startsWith('r_')) this.globalData.ref = scene.slice(2);
    }
    // iOS 无虚拟支付通道：标记 canPay=false，各页据此隐藏充值/购买入口
    try {
      const info = tt.getSystemInfoSync();
      if (info && info.platform === 'ios') this.globalData.canPay = false;
    } catch (e) {}
    // 优先用 tt.login 换 openid；失败回退设备 token（开发期兜底）
    // tokenPromise：页面在拿到 token 之前不得创建订单（否则 422）
    this.globalData.tokenPromise = new Promise((resolve) => {
      this._resolveToken = resolve;
      tt.login({
        success: (res) => {
          if (!res.code) return this.fallbackToken();
          this.req('/api/dy/login', 'GET', { code: res.code })
            .then(r => {
              this.globalData.openToken = 'dy-' + r.openid;
              tt.setStorageSync('open_token', this.globalData.openToken);
              this._resolveToken(this.globalData.openToken);
            })
            .catch(() => this.fallbackToken());
        },
        fail: () => this.fallbackToken(),
      });
    });
    const order = tt.getStorageSync('mp_order');
    if (order) this.globalData.order = order;
  },
  fallbackToken() {
    let token = tt.getStorageSync('open_token');
    if (!token) {
      token = 'dev-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      tt.setStorageSync('open_token', token);
    }
    this.globalData.openToken = token;
    if (this._resolveToken) this._resolveToken(token);
  },
  // 统一请求封装
  req(path, method, data) {
    return new Promise((resolve, reject) => {
      tt.request({
        url: API_BASE + path,
        method: method || 'GET',
        data,
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300 && res.data && res.data.ok !== false) {
            resolve(res.data);
          } else {
            // FastAPI 422 的 detail 是对象数组，需转成可读文本
            let detail = res.data && res.data.detail;
            if (detail && typeof detail !== 'string') {
              try { detail = detail.map(d => d.msg || '').filter(Boolean).join('；') || JSON.stringify(detail); }
              catch (e) { detail = '参数校验失败'; }
            }
            reject(new Error(detail || ('HTTP ' + res.statusCode)));
          }
        },
        fail: (e) => reject(new Error('网络异常，请稍后再试')),
      });
    });
  },
  // 担保支付（按单支付，无代币模式）：后端预下单 → tt.pay 收银台 → confirm 补偿到账
  // iOS 无虚拟支付通道（canPay=false 时入口已隐藏，此处兜底直接返回）
  // 未开通/未配置时回退意见反馈流程（抖音禁止站外引流，不放微信号）
  vpay(product, title) {
    if (!this.globalData.canPay || !tt.pay) return;
    const order = this.globalData.order || {};
    this.req('/api/dy/pay/prepare', 'POST', {
      order_no: order.order_no || '',
      product,
      open_token: this.globalData.openToken,
    }).then(res => {
      tt.pay({
        orderInfo: res.orderInfo,
        service: 5, // 拉起小程序收银台（抖音支付/微信/支付宝）
        success: () => {
          // 异步回调可能延迟，客户端主动 confirm 补偿到账（服务端幂等）
          this.req('/api/dy/pay/confirm', 'POST', {
            out_trade_no: res.outTradeNo,
            open_token: this.globalData.openToken,
          }).then(() => {
            tt.showModal({ title: '支付成功', content: '额度已到账，去生成吧', showCancel: false });
          }).catch(() => {
            tt.showToast({ title: '支付成功，额度稍后到账', icon: 'none' });
          });
        },
        fail: (e) => {
          if (!/cancel/i.test((e && e.errMsg) || '')) {
            const detail = e ? `${e.errCode !== undefined ? e.errCode + ' ' : ''}${e.errMsg || ''}` : '';
            tt.showModal({ title: '支付未完成', content: detail || '请稍后再试', showCancel: false });
          }
        },
      });
    }).catch(e => this.vpayFallback(title, e.message));
  },
  vpayFallback(title, msg) {
    tt.showModal({
      title: title || '充值 / 续购',
      content: (msg === '担保支付未配置（DOUYIN_PAY_SALT）' ? '线上支付即将开通。' : (msg ? msg + '。' : ''))
        + '可在「我的 → 意见反馈」留言联系我们。',
      confirmText: '去反馈',
      success: (r) => {
        if (r.confirm) tt.navigateTo({ url: '/pages/feedback/feedback' });
      },
    });
  },
});
