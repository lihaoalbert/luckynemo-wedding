// 选装页：霓裳阁套装 + 微剧情场景
const app = getApp();

Page({
  data: {
    sets: [],
    scenes: [],
    setId: '',
    sceneIds: {},
    tab: 'sets',
    mode: 'couple',   // solo=个人写真：只看单人服装，只出单人照
    gender: 'female', // solo 时的服装性别（来自定妆选择）
    expandedId: '',   // 展开服装细节的卡片
    anchors: [],      // 我的定妆照集合（多张可选）
    anchorsA: [],     // 她的定妆照
    anchorsB: [],     // 他的定妆照
    activeAnchor: (getApp().globalData.selection || {}).anchor_key || '',
  },

  onLoad() {
    const order = app.globalData.order || {};
    this.setData({ mode: order.mode || 'couple' });
    // 我的定妆照集合（可多张：不同衣服配不同妆）
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const anchors = (res.jobs || [])
        .filter(j => j.kind === 'makeup_photo' && j.status === 'done' && j.result && j.result.url)
        .map(j => ({
          url: j.result.url, key: j.result.oss_key || '',
          name: j.makeup_name || '定妆照', role: j.role || 'A',
        }));
      // 服装性别：优先会话选择；否则按当前定妆照妆名推断（"男士"开头即男妆）
      let gender = (app.globalData.selection || {}).gender;
      if (!gender) {
        const active = anchors.find(a => a.key === this.data.activeAnchor) || anchors[0];
        gender = active && active.name.startsWith('男士') ? 'male' : 'female';
      }
      this.setData({
        anchors,
        anchorsA: anchors.filter(a => a.role !== 'B'),
        anchorsB: anchors.filter(a => a.role === 'B'),
        gender,
      });
    }).catch(() => {
      this.setData({ gender: (app.globalData.selection || {}).gender || 'female' });
    });
    wx.showLoading({ title: '打开霓裳阁…' });
    app.req('/api/mp/catalog').then(res => {
      wx.hideLoading();
      const sets = this.parseSets(res.sets_js, res.img_base.wardrobe);
      const scenes = this.parseScenes(res.scenes_js, res.img_base.scenes);
      this.setData({ sets, scenes });
    }).catch(e => {
      wx.hideLoading();
      wx.showToast({ title: e.message, icon: 'none' });
    });
  },

  // data.js 里是 JS 常量，用正则提取 JSON；img_base 是相对路径，需拼上完整域名
  fullBase(imgBase) {
    return app.globalData.apiBase + imgBase;
  },

  parseSets(js, imgBase) {
    const base = this.fullBase(imgBase);
    const m = js.match(/const SETS = (\[[\s\S]*\]);/);
    const arr = m ? JSON.parse(m[1]) : [];
    return arr.map(s => ({
      ...s,
      dressImg: base + encodeURI(s.dress.img.replace(/^img\//, '')),
      suitImg: base + encodeURI(s.suit.img.replace(/^img\//, '')),
    }));
  },

  parseScenes(js, imgBase) {
    const base = this.fullBase(imgBase);
    const m = js.match(/const SCENES = (\[[\s\S]*\]);/);
    const arr = m ? JSON.parse(m[1]) : [];
    return arr.map(s => ({ ...s, img: base + encodeURI(s.img.replace(/^img\//, '')) }));
  },

  switchTab(e) {
    this.setData({ tab: e.currentTarget.dataset.tab });
  },

  pickSet(e) {
    this.setData({ setId: e.currentTarget.dataset.id });
  },

  pickScene(e) {
    const id = e.currentTarget.dataset.id;
    const sceneIds = { ...this.data.sceneIds };
    if (sceneIds[id]) delete sceneIds[id];
    else sceneIds[id] = true;
    this.setData({ sceneIds });
  },

  // 选择本次出图使用的定妆照（按角色写入对应锚点：她的→anchor_key，他的→anchor_key_b）
  pickAnchor(e) {
    const { key, name, role } = e.currentTarget.dataset;
    const selection = app.globalData.selection || {};
    if (role === 'B') {
      selection.anchor_key_b = key;
      selection.makeup_name_b = name;
    } else {
      selection.anchor_key = key;
      selection.makeup_name = name;
      selection.gender = name.startsWith('男士') ? 'male' : 'female';
    }
    app.globalData.selection = selection;
    // 换定妆照时联动服装性别
    this.setData({ activeAnchor: key, gender: selection.gender || this.data.gender });
    wx.showToast({ title: `已选用「${name}」`, icon: 'none' });
  },

  confirm() {
    // 两段式：先选服装 → 再选场景（显式步骤，场景可多选也可不选）
    if (this.data.tab === 'sets') {
      if (!this.data.setId) {
        wx.showToast({ title: '先选一套服装哦', icon: 'none' });
        return;
      }
      this.setData({ tab: 'scenes' });
      wx.showToast({ title: '再挑个场景氛围吧（可不选）', icon: 'none' });
      return;
    }
    const set = this.data.sets.find(s => s.id === this.data.setId);
    const scenes = Object.keys(this.data.sceneIds);
    // 保留定妆环节的妆造和锚点，叠加服饰场景后进入动作神态
    const selection = app.globalData.selection || {};
    // 个人写真按性别带单件（女装/男装）；婚纱照带套装（女装+男装）
    if (this.data.mode === 'solo') {
      selection.set = this.data.gender === 'male' ? { suit: set.suit } : { dress: set.dress };
    } else {
      selection.set = set;
    }
    selection.scenes = scenes;
    selection.mode = this.data.mode;
    app.globalData.selection = selection;
    wx.navigateTo({ url: '/pages/pose/pose' });
  },

  previewImg(e) {
    wx.previewImage({ urls: [e.currentTarget.dataset.url] });
  },

  toggleDetail(e) {
    const id = e.currentTarget.dataset.id;
    this.setData({ expandedId: this.data.expandedId === id ? '' : id });
  },
});
