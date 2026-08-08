// 动作神态页：每组单选（四步流程第 3 步）
const app = getApp();

Page({
  data: {
    groups: [],   // [{name, options:[...], picked:''}]
  },

  onLoad() {
    const order = app.globalData.order || {};
    const solo = order.mode === 'solo';
    const build = (poses) => Object.keys(poses).map(name => ({
      name, options: poses[name], picked: '',
    }));
    const cached = tt.getStorageSync('mp_poses');
    if (cached && cached.couple && cached.solo) {
      this.setData({ groups: build(solo ? cached.solo : cached.couple) });
      return;
    }
    app.req('/api/mp/catalog').then(res => {
      const all = { couple: res.poses || {}, solo: res.poses_solo || {} };
      tt.setStorageSync('mp_poses', all);
      this.setData({ groups: build(solo ? all.solo : all.couple) });
    }).catch(e => tt.showToast({ title: e.message, icon: 'none' }));
  },

  pick(e) {
    const { group, option } = e.currentTarget.dataset;
    const groups = this.data.groups.map(g =>
      g.name === group ? { ...g, picked: g.picked === option ? '' : option } : g);
    this.setData({ groups });
  },

  confirm() {
    const picked = this.data.groups.filter(g => g.picked);
    if (!picked.length) {
      tt.showToast({ title: '至少选一个动作或神态哦', icon: 'none' });
      return;
    }
    const selection = app.globalData.selection || {};
    selection.poses = picked.map(g => g.picked);
    app.globalData.selection = selection;
    tt.navigateTo({ url: '/pages/generating/generating' });
  },
});
