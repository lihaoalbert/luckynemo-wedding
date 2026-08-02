// 徐大恩 LuckyNemo 小程序
// v1：设备 token 做订单归属（AppID 下来后换 wx.login openid）
const API_BASE = 'https://luckynemo.ibi.ren';

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
    // 分享进入：share=协同创作加入订单；ref=裂变来源
    const query = (options && options.query) || {};
    if (query.share) this.globalData.pendingShare = query.share;
    if (query.ref) this.globalData.ref = query.ref;
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
});
