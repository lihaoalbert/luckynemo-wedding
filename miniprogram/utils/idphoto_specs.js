// 证件照规格库：w/h 为像素，head_min/head_max 为头部高度占画面比例（0-1）
// bg：支持的底色；hot：热门规格（首页大卡区）；group：分组（常用/考试报名/签证出行/职业）
// 注：像素与占比按常见报名要求整理，官方要求以各报名系统公告为准
const SPECS = [
  // ---- 常用 ----
  { id: 'yicun', name: '一寸', sub: '最万能的尺寸，简历/报名表通吃', w: 295, h: 413, head_min: 0.55, head_max: 0.72, bg: ['white', 'blue', 'red'], hot: true, group: 'changyong' },
  { id: 'ercun', name: '二寸', sub: '毕业证、资格证书常用', w: 413, h: 579, head_min: 0.55, head_max: 0.72, bg: ['white', 'blue', 'red'], hot: true, group: 'changyong' },
  { id: 'xiaoyicun', name: '小一寸', sub: '部分登记表指定的小号一寸', w: 260, h: 378, head_min: 0.55, head_max: 0.72, bg: ['white', 'blue', 'red'], hot: false, group: 'changyong' },
  { id: 'dayicun', name: '大一寸', sub: '签证与部分考试报名用', w: 390, h: 567, head_min: 0.55, head_max: 0.72, bg: ['white', 'blue', 'red'], hot: false, group: 'changyong' },
  { id: 'jianli', name: '简历照', sub: '求职简历头像，精神一点', w: 295, h: 413, head_min: 0.5, head_max: 0.68, bg: ['white', 'blue'], hot: true, group: 'changyong' },

  // ---- 考试报名 ----
  { id: 'kaoyan', name: '考研报名', sub: '研招网报名照，白底', w: 480, h: 640, head_min: 0.55, head_max: 0.7, bg: ['white'], hot: true, group: 'exam' },
  { id: 'cet', name: '四六级', sub: '四六级报名照，白底或蓝底', w: 240, h: 320, head_min: 0.55, head_max: 0.72, bg: ['white', 'blue'], hot: false, group: 'exam' },
  { id: 'ncre', name: '计算机二级', sub: 'NCRE 报名照，白底或蓝底', w: 295, h: 413, head_min: 0.55, head_max: 0.72, bg: ['white', 'blue'], hot: false, group: 'exam' },
  { id: 'jiaozi', name: '教师资格证', sub: '教资笔试/认定报名照，白底', w: 295, h: 413, head_min: 0.55, head_max: 0.72, bg: ['white'], hot: false, group: 'exam' },
  { id: 'putonghua', name: '普通话', sub: '普通话水平测试报名照，白底', w: 390, h: 567, head_min: 0.55, head_max: 0.72, bg: ['white'], hot: false, group: 'exam' },

  // ---- 签证出行 ----
  { id: 'meiqian', name: '美签', sub: '美国签证 DS-160，正方形白底', w: 600, h: 600, head_min: 0.5, head_max: 0.69, bg: ['white'], hot: true, group: 'visa' },
  { id: 'riqian', name: '日签', sub: '日本签证，正方形白底', w: 531, h: 531, head_min: 0.55, head_max: 0.72, bg: ['white'], hot: false, group: 'visa' },
  { id: 'shengen', name: '申根签', sub: '欧洲申根签证，35×45mm 白底', w: 413, h: 531, head_min: 0.6, head_max: 0.75, bg: ['white'], hot: false, group: 'visa' },
  { id: 'gangaao', name: '港澳通行证', sub: '往来港澳通行证申请照', w: 390, h: 567, head_min: 0.55, head_max: 0.72, bg: ['white', 'blue'], hot: false, group: 'visa' },
  { id: 'huzhao', name: '护照', sub: '出入境审核严格，本结果仅供参考', w: 390, h: 567, head_min: 0.55, head_max: 0.72, bg: ['white'], hot: false, group: 'visa' },
  { id: 'jiazhao', name: '驾照', sub: '驾驶证申领/换证照，白底', w: 260, h: 378, head_min: 0.55, head_max: 0.72, bg: ['white'], hot: false, group: 'visa' },
  { id: 'shebaoka', name: '社保卡', sub: '社保卡申领照，白底', w: 358, h: 441, head_min: 0.55, head_max: 0.72, bg: ['white'], hot: false, group: 'visa' },

  // ---- 职业 ----
  { id: 'biye', name: '毕业证', sub: '毕业证/学位证照，一般蓝底', w: 480, h: 640, head_min: 0.55, head_max: 0.72, bg: ['blue', 'white'], hot: false, group: 'career' },
  { id: 'gongpai', name: '工牌照', sub: '工牌、胸卡、门禁照', w: 295, h: 413, head_min: 0.5, head_max: 0.68, bg: ['white', 'blue', 'red'], hot: false, group: 'career' },
  { id: 'xingxiang', name: '形象照', sub: '职场形象照，半身更松弛', w: 640, h: 853, head_min: 0.35, head_max: 0.5, bg: ['white', 'blue'], hot: false, group: 'career' },
];

const GROUPS = [
  { key: 'changyong', name: '常用尺寸' },
  { key: 'exam', name: '考试报名' },
  { key: 'visa', name: '签证出行' },
  { key: 'career', name: '职业证件' },
];

const BG_NAMES = { white: '白底', blue: '蓝底', red: '红底' };
const BG_COLORS = { white: '#ffffff', blue: '#438edb', red: '#d03a34' };

function byId(id) {
  return SPECS.find(s => s.id === id) || SPECS[0];
}

function hotList() {
  return SPECS.filter(s => s.hot);
}

function grouped() {
  return GROUPS.map(g => ({ name: g.name, items: SPECS.filter(s => s.group === g.key) }))
    .filter(g => g.items.length);
}

module.exports = { SPECS, GROUPS, BG_NAMES, BG_COLORS, byId, hotList, grouped };
