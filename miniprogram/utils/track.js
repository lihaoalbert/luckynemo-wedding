// 埋点上报（P0 观测层）：POST /api/mp/event，静默失败不阻塞业务
// 自动带上 globalData 里的 orderNo/openid（拿不到就留空）

function track(event, props) {
  const app = getApp();
  const gd = (app && app.globalData) || {};
  const order = gd.order || {};
  const token = gd.openToken || '';
  wx.request({
    url: (gd.apiBase || 'https://luckynemo.ibi.ren') + '/api/mp/event',
    method: 'POST',
    data: {
      event,
      order_no: order.order_no || '',
      openid: /^(wx|dy)-/.test(token) ? token.slice(3) : '',
      props: props || {},
    },
    fail: () => {},
  });
}

module.exports = { track };
