// 选妆造页：红妆阁标准妆造库 → 生成定妆照（四步流程第 1 步：先定妆）
// 支持双角色：A=新娘/本人（默认女士妆），B=新郎（自动男士妆，可跳过）；
// 个人写真按用户照片自动识别性别预选 Tab，可手动切换。
const app = getApp();

Page({
  data: {
    role: 'A',         // A=新娘/本人，B=新郎
    mode: 'solo',
    makeup: [],        // 当前 Tab 的妆造列表
    allMakeup: [],
    allHairstyles: [],
    gender: 'female',  // 当前 Tab：female / male
    makeupId: '',
    expandedId: '',    // 展开妆容说明的卡片
    engine: 'seedream', // 生图引擎（内测可选）
    engines: [
      { key: 'seedream', label: '火山', hint: '最像本人' },
      { key: 'vidu', label: 'Vidu', hint: '妆效精致' },
    ],
    hairstyles: [],   // 发型库（按性别过滤）
    hairstyleId: '',  // 选中的发型（可空=保持原发型）
    uploads: [],      // 已上传照片（选底照用，本人+伴侣双相册，带 role/label）
    baseKey: '',      // 底照 oss_key（定妆以它为基础，其余照片做人脸参考）
    baseRole: 'A',    // 底照所在相册（A=本人/B=伴侣），定妆任务按它取对应相册照片
    lipColors: ['默认配方', '豆沙色', '番茄红', '奶茶色', '正红色'],
    lipColor: '默认配方',
    phase: 'pick',     // pick → waiting → done
    photo: '',
    anchorKey: '',
    tips: ['化妆师正在打底…', '扫上薄薄一层腮红…', '点亮卧蚕…', '睫毛一根一根刷…', '唇峰点一点高光…', '定妆喷雾最后一下…', '对着镜子最后检查一遍…'],
    tipIdx: 0,
  },

  onLoad(options) {
    const order = app.globalData.order || {};
    // 角色：URL 参数优先；协同创作 B 端设备默认新郎
    const role = (options && options.role === 'B') || app.globalData.myRole === 'B' ? 'B' : 'A';
    const mode = order.mode || 'solo';
    // 默认 Tab：新郎→男士；新娘（婚纱照）→女士；个人写真→先女士，识别后自动纠正
    const gender = role === 'B' ? 'male' : 'female';
    this.setData({ role, mode, gender });
    tt.showLoading({ title: '打开红妆阁…' });
    app.req('/api/mp/catalog').then(res => {
      tt.hideLoading();
      const base = app.globalData.apiBase;
      const all = (res.makeup || []).map(m => {
        const spec = m.spec || {};
        spec.partsList = Object.keys(spec.parts || {}).map(k => ({ k, v: spec.parts[k] }));
        return { ...m, img: base + m.img, spec };
      });
      const allHairstyles = (res.hairstyles || []).map(h => ({ ...h, img: base + h.img }));
      this.setData({ allMakeup: all, allHairstyles });
      this.applyGender(this.data.gender);
    }).catch(e => {
      tt.hideLoading();
      tt.showToast({ title: e.message, icon: 'none' });
    });
    // 个人写真：按最新照片自动识别性别预选 Tab
    if (mode === 'solo' && role === 'A') {
      app.req('/api/mp/detect-gender', 'GET', { order_no: order.order_no, role: 'A' })
        .then(res => {
          if (res.gender === 'male' || res.gender === 'female') this.applyGender(res.gender);
        }).catch(() => {});
    }
    // 拉已上传照片供选底照（本人+伴侣双相册都列出，默认最新一张）
    app.req('/api/mp/me', 'GET', { order_no: order.order_no }).then(res => {
      const mine = app.globalData.myRole || 'A';
      const ups = [];
      for (const r of ['A', 'B']) {
        const label = r === mine ? '我的' : '伴侣的';
        for (const u of ((res.uploads && res.uploads[r]) || [])) ups.push({ ...u, role: r, label });
      }
      if (ups.length) this.setData({ uploads: ups, baseKey: ups[0].key, baseRole: ups[0].role });
    }).catch(() => {});
    // 有正在进行的定妆任务（含对话里发起的重生成）→ 直接恢复等待页
    app.req('/api/mp/order/' + order.order_no).then(res => {
      const job = (res.jobs || []).find(j => j.kind === 'makeup_photo');
      if (job && (job.status === 'queued' || job.status === 'running')) {
        this.setData({ phase: 'waiting' });
        this.startTips();
        this.poll();
      }
    }).catch(() => {});
  },

  applyGender(gender) {
    const makeup = this.data.allMakeup.filter(m => (m.gender || 'female') === gender);
    const hairstyles = this.data.allHairstyles.filter(h => (h.gender || 'female') === gender);
    // MiniMax 男妆保真弱：显示但标不推荐（避免用户以为功能缺失）
    const engines = this.data.engines;
    this.setData({ gender, makeup, hairstyles, makeupId: '', hairstyleId: '', engines });
  },

  switchTab(e) {
    this.applyGender(e.currentTarget.dataset.gender);
  },

  pick(e) {
    this.setData({ makeupId: e.currentTarget.dataset.id });
  },

  pickEngine(e) {
    this.setData({ engine: e.currentTarget.dataset.key });
  },

  pickHairstyle(e) {
    const id = e.currentTarget.dataset.id;
    this.setData({ hairstyleId: this.data.hairstyleId === id ? '' : id });
  },

  pickBase(e) {
    this.setData({ baseKey: e.currentTarget.dataset.key, baseRole: e.currentTarget.dataset.role || 'A' });
  },

  pickLip(e) {
    this.setData({ lipColor: e.currentTarget.dataset.color });
  },

  previewImg(e) {
    tt.previewImage({ urls: [e.currentTarget.dataset.url] });
  },

  toggleDetail(e) {
    const id = e.currentTarget.dataset.id;
    this.setData({ expandedId: this.data.expandedId === id ? '' : id });
  },

  confirm() {
    const m = this.data.makeup.find(x => x.id === this.data.makeupId);
    if (!m) {
      tt.showToast({ title: '先选一款妆容哦', icon: 'none' });
      return;
    }
    const hair = this.data.hairstyles.find(x => x.id === this.data.hairstyleId);
    this.setData({ phase: 'waiting' });
    this.startTips();
    const order = app.globalData.order;
    // 唇色快选合并进化妆意见（与用户对话提的意见共存）
    const notes = this.data.lipColor !== '默认配方' ? `唇色使用${this.data.lipColor}` : '';
    app.req('/api/mp/job', 'POST', {
      order_no: order.order_no,
      kind: 'makeup_photo',
      payload: { role: this.data.baseRole, makeup_id: m.id, makeup_name: m.name,
                 makeup_prompt: m.prompt, gender: m.gender || 'female',
                 engine: this.data.engine,
                 base_key: this.data.baseKey,
                 makeup_notes: notes,
                 hairstyle: hair ? hair.prompt_key : '', hairstyle_name: hair ? hair.name : '' },
    }).then(() => this.poll()).catch(e => {
      this.setData({ phase: 'pick' });
      clearInterval(this.timer);
      tt.showModal({ title: '提示', content: e.message, showCancel: false });
    });
  },

  startTips() {
    this.timer = setInterval(() => {
      this.setData({ tipIdx: (this.data.tipIdx + 1) % this.data.tips.length });
    }, 2600);
  },

  poll() {
    this.poller = setInterval(() => {
      app.req('/api/mp/order/' + app.globalData.order.order_no).then(res => {
        const job = (res.jobs || []).find(j => j.kind === 'makeup_photo');
        if (job && job.status === 'done' && job.result && job.result.url) {
          clearInterval(this.poller);
          clearInterval(this.timer);
          this.setData({ phase: 'done', photo: job.result.url, anchorKey: job.result.oss_key || '' });
        } else if (job && job.status === 'failed') {
          clearInterval(this.poller);
          clearInterval(this.timer);
          this.setData({ phase: 'pick' });
          tt.showModal({ title: '生成失败', content: '这款妆容生成失败了，换一款试试？', showCancel: false });
        }
      }).catch(() => {});
    }, 4000);
  },

  preview() {
    if (this.data.photo) tt.previewImage({ urls: [this.data.photo] });
  },

  saveSelection() {
    const m = this.data.makeup.find(x => x.id === this.data.makeupId) || {};
    const selection = app.globalData.selection || {};
    if (this.data.role === 'B') {
      selection.makeup_name_b = m.name;
      selection.anchor_key_b = this.data.anchorKey;
    } else {
      selection.makeup_id = m.id;
      selection.makeup_name = m.name;
      selection.anchor_key = this.data.anchorKey;
      selection.gender = m.gender || 'female';  // 男士单人写真后续流程要用
    }
    app.globalData.selection = selection;
  },

  // 定妆满意 → B 端设备完成自己的部分回首页；A 端婚纱照流程带新郎定妆；否则去选衣服
  next() {
    this.saveSelection();
    if (this.data.role === 'B' && app.globalData.myRole === 'B') {
      tt.showToast({ title: '你的部分完成啦 🎉', icon: 'none' });
      setTimeout(() => tt.switchTab({ url: '/pages/chat/chat' }), 800);
      return;
    }
    if (this.data.mode === 'couple' && this.data.role === 'A') {
      tt.redirectTo({ url: '/pages/makeup/makeup?role=B' });
      return;
    }
    tt.navigateTo({ url: '/pages/wardrobe/wardrobe' });
  },

  // 不定妆：B 端设备回首页，A 端直接去选衣服
  skip() {
    if (this.data.role === 'B' && app.globalData.myRole === 'B') {
      tt.switchTab({ url: '/pages/chat/chat' });
      return;
    }
    tt.navigateTo({ url: '/pages/wardrobe/wardrobe' });
  },

  repick() {
    this.setData({ phase: 'pick', photo: '', anchorKey: '' });
  },

  onUnload() {
    clearInterval(this.poller);
    clearInterval(this.timer);
  },
});
