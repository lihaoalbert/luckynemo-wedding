// 证件照合规规则引擎（纯函数，无小程序 API 依赖，可单测）
// 输入：{face:{x,y,w,h}（相对坐标 0-1）, yaw（左右转头角度）, roll（歪头角度）,
//        brightness（0-255）, light_diff（左右半脸亮度差，可选）, has_face}
// 输出：{code, hint, cue}
//   code ∈ ok | move_left | move_right | move_up | move_down | come_closer | step_back
//        | tilt_head | level_shoulder | too_dark | uneven_light | no_face | hold
//   hint=屏幕大字指引（10 字内）；cue=台词卡（摄影师可以直接喊出口）
// 注意：code 为 ok 时由调用方连续计数 N 帧后才算"达标"（防抖），hold 预留给调用方倒计时阶段

const THRESH = {
  FACE_W_MIN: 0.28,   // 脸宽占画面比例下限（太小=离太远）
  FACE_W_MAX: 0.45,   // 上限（太大=离太近）
  CX_TOL: 0.08,       // 水平中心偏移容忍
  CY_TARGET: 0.42,    // 脸中心理想纵向位置（头顶留白）
  CY_TOL: 0.08,       // 纵向偏移容忍
  ROLL_MAX: 10,       // 歪头角度上限（度）
  YAW_MAX: 15,        // 转头角度上限（度）
  BR_MIN: 90,         // 亮度下限（太暗）
  BR_MAX: 190,        // 亮度上限（过曝）
  LIGHT_DIFF_MAX: 45, // 左右半脸亮度差上限（阴阳脸）
};

const TEXTS = {
  ok:             { hint: '很好，保持不动！', cue: '完美！别动别动，要数一二三啦～' },
  move_left:      { hint: '手机往左一点', cue: '往你的左边挪一丢丢～对，就是酱紫！' },
  move_right:     { hint: '手机往右一点', cue: '往你的右边挪一丢丢～欸，回来了回来了！' },
  move_up:        { hint: '手机抬高一点', cue: '手机举高一点点，对，保持住～' },
  move_down:      { hint: '手机放低一点', cue: '手机放低一点点，别让我踮脚啦～' },
  come_closer:    { hint: '再靠近一点', cue: '走近一点点，让脸脸把圆圈装满～' },
  step_back:      { hint: '退后一点点', cue: '太近啦！退后半步，给美貌一点空间～' },
  tilt_head:      { hint: '头摆正哦', cue: '头不要歪～像小树苗一样直直的！' },
  level_shoulder: { hint: '脸转向正面', cue: '脸脸转回来，正面对着镜头，让我看看你！' },
  too_dark:       { hint: '光线太暗了', cue: '这里黑黢黢的，我们去亮一点的地方～' },
  too_bright:     { hint: '光线太刺眼', cue: '光太猛啦，躲到柔一点的亮处去～' },
  uneven_light:   { hint: '避开阴阳脸', cue: '脸上一边亮一边暗，转个方向让光均匀一点～' },
  no_face:        { hint: '人脸进圈圈', cue: '我还没看到你哦，把脸放进圆圈里～' },
  hold:           { hint: '很好，保持不动！', cue: '保持这个姿势，马上就好！' },
};

function evaluate(m) {
  const out = (code) => ({ code, hint: TEXTS[code].hint, cue: TEXTS[code].cue });
  if (!m || !m.has_face || !m.face) return out('no_face');
  // 光线优先：太黑/过曝/阴阳脸时位置再对也没用
  if (typeof m.brightness === 'number') {
    if (m.brightness < THRESH.BR_MIN) return out('too_dark');
    // 过曝没有独立 code，复用 too_dark（都是"光线不对"类问题），文案区分
    if (m.brightness > THRESH.BR_MAX) {
      return { code: 'too_dark', hint: TEXTS.too_bright.hint, cue: TEXTS.too_bright.cue };
    }
  }
  if (typeof m.light_diff === 'number' && m.light_diff > THRESH.LIGHT_DIFF_MAX) {
    return out('uneven_light');
  }
  // 距离：脸宽占比
  if (m.face.w < THRESH.FACE_W_MIN) return out('come_closer');
  if (m.face.w > THRESH.FACE_W_MAX) return out('step_back');
  // 水平位置（屏幕对摄影师：脸偏右=手机要往左移）
  const cx = m.face.x + m.face.w / 2;
  if (cx - 0.5 > THRESH.CX_TOL) return out('move_left');
  if (0.5 - cx > THRESH.CX_TOL) return out('move_right');
  // 纵向位置（脸中心偏高=手机要放低）
  const cy = m.face.y + m.face.h / 2;
  if (cy - THRESH.CY_TARGET > THRESH.CY_TOL) return out('move_down');
  if (THRESH.CY_TARGET - cy > THRESH.CY_TOL) return out('move_up');
  // 姿态
  if (typeof m.roll === 'number' && Math.abs(m.roll) > THRESH.ROLL_MAX) return out('tilt_head');
  if (typeof m.yaw === 'number' && Math.abs(m.yaw) > THRESH.YAW_MAX) return out('level_shoulder');
  return out('ok');
}

module.exports = { evaluate, THRESH };
