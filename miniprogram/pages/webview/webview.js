// 内嵌 H5 页：真人认证等（业务域名已验证的链接才能在 web-view 打开）
Page({
  data: { url: '' },
  onLoad(options) {
    if (options.url) this.setData({ url: decodeURIComponent(options.url) });
  },
});
