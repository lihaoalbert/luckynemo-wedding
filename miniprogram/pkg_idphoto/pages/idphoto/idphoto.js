// AI 证件照：规格选择页（首次进入弹授权确认层）
const app = getApp();
const { track } = require('../../utils/track');
const specs = require('../../utils/idphoto_specs');

const CONSENT_KEY = 'idphoto_consent_v1';

Page({
  data: {
    consentVisible: false,  // 首次进入的拍摄授权层
    consentChecked: false,
    hot: [],                // 热门大卡区
    groups: [],             // 分组列表
    bgNames: specs.BG_NAMES,
  },

  onLoad() {
    track('idphoto_enter');
    const hot = specs.hotList().map(this._decorate);
    const groups = specs.grouped().map(g => ({ name: g.name, items: g.items.map(this._decorate) }));
    this.setData({
      hot,
      groups,
      consentVisible: !wx.getStorageSync(CONSENT_KEY),
    });
  },

  // 卡片展示用补充字段：尺寸文本 + 底色文本
  _decorate(s) {
    return Object.assign({}, s, {
      sizeText: s.w + '×' + s.h + 'px',
      bgText: s.bg.map(b => ({ white: '白', blue: '蓝', red: '红' })[b]).join('/'),
    });
  },

  toggleConsent() {
    this.setData({ consentChecked: !this.data.consentChecked });
  },

  confirmConsent() {
    if (!this.data.consentChecked) {
      wx.showToast({ title: '先勾选确认哦', icon: 'none' });
      return;
    }
    wx.setStorageSync(CONSENT_KEY, true);
    track('idphoto_consent');
    this.setData({ consentVisible: false });
  },

  pickSpec(e) {
    const id = e.currentTarget.dataset.id;
    track('idphoto_spec_pick', { spec_id: id });
    wx.navigateTo({ url: '/pkg_idphoto/pages/idphoto_shoot/idphoto_shoot?spec_id=' + id });
  },
});
