// 生成中：提交免费任务 + 轮询状态
const app = getApp();

Page({
  data: {
    order: null,
    phase: 'submitting',  // submitting → queued → done
    tips: ['正在为你们挑选最美的光线…', '霓裳阁的衣服正在上身…', '精修每一根发丝…', '摄影师说：再靠近一点点～', '风把裙摆吹起来了，抓拍！', '把这一刻的喜欢藏进照片里…', '最后一遍检查你们的笑容…'],
    tipIdx: 0,
  },

  onLoad() {
    const order = app.globalData.order;
    // 一键同款/高级定制统一入口：pendingJob 优先（模卡页来），否则按模式走
    const pending = app.globalData.pendingJob;
    const kind = pending ? pending.kind : (order.mode === 'solo' ? 'solo_photo' : 'free_photo');
    const payload = pending ? pending.payload
      : Object.assign(app.globalData.selection || {}, { mode: order.mode || '' });
    app.globalData.pendingJob = null;
    this.setData({ order, kind });
    app.req('/api/mp/job', 'POST', {
      order_no: order.order_no,
      kind,
      payload,
    }).then(() => {
      this.setData({ phase: 'queued' });
      this.startTips();
      this.poll();
    }).catch(e => this.failOut(e.message));
  },

  // 生成失败/被拒：给出明确出口，绝不留在等待页空转
  failOut(message) {
    clearInterval(this.poller);
    clearInterval(this.timer);
    const isQuota = (message || '').includes('额度') || (message || '').includes('充值');
    wx.showModal({
      title: isQuota ? '额度已用完' : '生成失败',
      content: message || '生成失败了，请稍后再试',
      confirmText: isQuota ? '去充值' : '返回',
      cancelText: '返回',
      success: (r) => {
        if (r.confirm && isQuota) {
          wx.switchTab({ url: '/pages/me/me' });
        } else {
          wx.navigateBack();
        }
      },
    });
  },

  startTips() {
    this.timer = setInterval(() => {
      this.setData({ tipIdx: (this.data.tipIdx + 1) % this.data.tips.length });
    }, 2600);
  },

  poll() {
    this.poller = setInterval(() => {
      app.req('/api/mp/order/' + this.data.order.order_no).then(res => {
        const job = (res.jobs || []).find(j => j.kind === this.data.kind);
        if (job && job.status === 'done') {
          clearInterval(this.poller);
          clearInterval(this.timer);
          wx.redirectTo({ url: '/pages/result/result' });
        } else if (job && job.status === 'failed') {
          const msg = (job.result && job.result.error) || '生成失败了，请重新尝试';
          this.failOut(msg);
        }
      }).catch(() => {});
    }, 4000);
  },

  onUnload() {
    clearInterval(this.poller);
    clearInterval(this.timer);
  },
});
