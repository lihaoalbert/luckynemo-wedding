// 徐大恩 LuckyNemo 小程序
// v1：设备 token 做订单归属（AppID 下来后换 wx.login openid）
const API_BASE = 'https://luckynemo.ibi.ren';
//: 订阅消息模板（MP 后台模板 73339「内容生成成功通知」）：生成完成时微信服务通知推送
const SUB_TMPL_ID = 'IlIzXgigktofL--1YSNksEv_3snoOCS8Vhc-_Co67xs';

App({
  globalData: {
    apiBase: API_BASE,
    openToken: '',
    order: null,
    myRole: 'A',       // 协同创作：A=订单创建者，B=被邀请加入者
    pendingShare: '',
    ref: '',
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
    // 优先用 wx.login 换 openid；失败回退设备 token（开发期兜底）
    // tokenPromise：页面在拿到 token 之前不得创建订单（否则 422）
    this.globalData.tokenPromise = new Promise((resolve) => {
      this._resolveToken = resolve;
      wx.login({
        success: (res) => {
          if (!res.code) return this.fallbackToken();
          this.req('/api/mp/login', 'GET', { code: res.code })
            .then(r => {
              this.globalData.openToken = 'wx-' + r.openid;
              wx.setStorageSync('open_token', this.globalData.openToken);
              this._resolveToken(this.globalData.openToken);
            })
            .catch(() => this.fallbackToken());
        },
        fail: () => this.fallbackToken(),
      });
    });
    const order = wx.getStorageSync('mp_order');
    if (order) this.globalData.order = order;
  },
  fallbackToken() {
    let token = wx.getStorageSync('open_token');
    if (!token) {
      token = 'dev-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      wx.setStorageSync('open_token', token);
    }
    this.globalData.openToken = token;
    if (this._resolveToken) this._resolveToken(token);
  },
  // 统一请求封装
  req(path, method, data) {
    return new Promise((resolve, reject) => {
      wx.request({
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
  // 订阅「生成完成通知」：接受一次=生成完成时微信服务通知推一次（凭证落后端 mp_subs）
  // 在发起生成的入口调用（generating 页/定妆确认）；用户拒绝或取消不打扰
  askSubscribe() {
    const order = this.globalData.order || {};
    if (!order.order_no || !wx.requestSubscribeMessage) return;
    wx.requestSubscribeMessage({
      tmplIds: [SUB_TMPL_ID],
      success: (res) => {
        if (res && res[SUB_TMPL_ID] === 'accept') {
          this.req('/api/mp/subscribe', 'POST', {
            order_no: order.order_no, open_token: this.globalData.openToken,
          }).catch(() => {});
        }
      },
      fail: () => {},
    });
  },
  // 虚拟支付（代币模式）：后端签名三要素 → wx.requestVirtualPayment → confirm 补偿到账
  // 未开通/不支持/未配置时回退客服流程
  vpay(product, title) {
    if (!wx.requestVirtualPayment) return this.vpayFallback(title);
    const order = this.globalData.order || {};
    const platform = (wx.getDeviceInfo ? wx.getDeviceInfo().platform : '') || 'android';
    this.req('/api/mp/vpay/prepare', 'POST', {
      order_no: order.order_no || '',
      product,
      open_token: this.globalData.openToken,
      platform,
    }).then(res => {
      wx.requestVirtualPayment({
        signData: res.signData,
        paySig: res.paySig,
        signature: res.signature,
        mode: res.mode,
        success: () => {
          // Midas 发货推送可能延迟/缺失，客户端主动 confirm 补偿到账（服务端幂等）
          this.req('/api/mp/vpay/confirm', 'POST', {
            out_trade_no: res.outTradeNo,
            open_token: this.globalData.openToken,
          }).then(() => {
            wx.showModal({ title: '支付成功', content: '额度已到账，去生成吧', showCancel: false });
          }).catch(() => {
            wx.showToast({ title: '支付成功，额度稍后到账', icon: 'none' });
          });
        },
        fail: (e) => {
          if (!/cancel/i.test((e && e.errMsg) || '')) {
            // 展示 errCode/errMsg 便于真机排查（-15006=paySig 错 / -15009=代币未发布 / -15011=现网版不能用沙箱 env=1）
            const detail = e ? `${e.errCode !== undefined ? e.errCode + ' ' : ''}${e.errMsg || ''}` : '';
            wx.showModal({ title: '支付未完成', content: detail || '请稍后再试', showCancel: false });
          }
        },
      });
    }).catch(e => this.vpayFallback(title, e.message));
  },
  vpayFallback(title, msg) {
    wx.showModal({
      title: title || '充值 / 续购',
      content: (msg === '虚拟支付未配置（VP_OFFER_ID/VP_APP_KEY）' ? '线上支付即将开通。' : (msg ? msg + '。' : ''))
        + '可先扫码联系客服完成下单。',
      confirmText: '复制客服微信',
      success: (r) => {
        if (r.confirm) wx.setClipboardData({ data: 'LuckyNemo2026' });
      },
    });
  },
});
