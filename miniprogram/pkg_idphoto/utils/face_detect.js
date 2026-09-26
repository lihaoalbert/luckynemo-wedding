// BlazeFace 人脸检测封装（小程序端侧推理）
// - 惰性初始化：第一次 detect 时才装依赖、配插件、加载模型（网络加载，不打进包）
// - 依赖官方 tfjs 插件 tfjsPlugin（app.json 已声明，需在小程序后台添加）+ npm 包
//   （@tensorflow/tfjs-core / tfjs-converter / tfjs-backend-webgl / @tensorflow-models/blazeface / fetch-wechat）
// - 模型自托管在 luckynemo.ibi.ren（tfhub 国内不可达且未进小程序域名白名单，曾致真机加载卡死）；
//   源文件在 website/models/blazeface/，ECS /var/www/luckynemo/models/blazeface/
// - 任何一步失败（含 20s 超时）都降级为 manual 模式：detect 恒返回 has_face:true（无框），
//   拍摄页据此关闭自动抓拍、显示「手动对准框线拍摄」
const MODEL_URL = 'https://luckynemo.ibi.ren/models/blazeface/model.json';
const LOAD_TIMEOUT_MS = 20000;

let _state = 'idle';   // idle → loading → ready | manual
let _model = null;
let _tf = null;
let _loadingPromise = null;  // 必须显式声明：真机 app-service.js 是严格模式，
                             // 未声明赋值会 ReferenceError（模拟器非严格模式不炸，曾因此漏网）
// 安卓竖屏 onCameraFrame 给横向传感器帧（人脸侧躺，BlazeFace 检不出），
// 需转正再推理；方向因机型/前后摄而异：开拍后自动探测（轮流试 0/90/270/180，
// 检出人脸即锁定），换镜头时 resetRotation()
let _rot = 0;
let _rotLocked = false;
let _probeIdx = 0;
const _PROBE_ROTATIONS = [0, 90, 270, 180];
let _lastRotated = null;  // {data,w,h} 供页面采样亮度（与推理同方向）

function status() { return _state; }
function resetRotation() { _rotLocked = false; _probeIdx = 0; _rot = 0; }
function lastRotated() { return _lastRotated; }

// RGBA 帧旋转（deg ∈ 0/90/180/270 顺时针），返回 {data,w,h}
function _rotateRGBA(src, w, h, deg) {
  if (!deg) return { data: src, w, h };
  const s = new Uint8Array(src);
  const nw = (deg === 180) ? w : h, nh = (deg === 180) ? h : w;
  const d = new Uint8Array(s.length);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let dx, dy;
      if (deg === 90) { dx = h - 1 - y; dy = x; }
      else if (deg === 270) { dx = y; dy = w - 1 - x; }
      else { dx = w - 1 - x; dy = h - 1 - y; }
      const si = (y * w + x) * 4, di = (dy * nw + dx) * 4;
      d[di] = s[si]; d[di + 1] = s[si + 1]; d[di + 2] = s[si + 2]; d[di + 3] = s[si + 3];
    }
  }
  return { data: d.buffer, w: nw, h: nh };
}

function _loadDeps() {
  // 构建 npm 之前 require 会抛错，这里统一兜住走降级
  try {
    const tf = require('@tensorflow/tfjs-core');
    const fetchWechat = require('fetch-wechat');
    const webgl = require('@tensorflow/tfjs-backend-webgl');
    const blazeface = require('@tensorflow-models/blazeface');
    return { tf, fetchWechat, webgl, blazeface };
  } catch (e) {
    return null;
  }
}

async function init() {
  if (_state === 'ready' || _state === 'manual') return _state;
  if (_state === 'loading') return _loadingPromise;
  _state = 'loading';
  _loadingPromise = _doInit();
  return _loadingPromise;
}

async function _doInit() {
  const deps = _loadDeps();
  if (!deps) { _state = 'manual'; return _state; }
  const { tf, fetchWechat, webgl, blazeface } = deps;
  try {
    // 官方插件注入 webgl 后端 + fetch polyfill（必须在页面内调，onLaunch 里调会因
    // offscreen canvas 随页面跳转失效而出错，见 tfjs-wechat README；webgl 必须显式传入，
    // 否则 tf 注册表里没有任何后端，报 No backend found in registry）
    const plugin = requirePlugin('tfjsPlugin');
    plugin.configPlugin({
      fetchFunc: fetchWechat.fetchFunc(),
      tf,
      webgl,
      canvas: wx.createOffscreenCanvas(),
    });
    _tf = tf;
    // 直接加载自托管模型（blazeface.load 支持 modelUrl；不试 tfhub：真机域名白名单没有它，会无限挂起）；
    // 全程包超时，任何挂起都降级 manual，绝不让「上场中」卡死
    _model = await Promise.race([
      blazeface.load({ maxFaces: 1, modelUrl: MODEL_URL }),
      new Promise((_, rej) => setTimeout(() => rej(new Error('model load timeout')), LOAD_TIMEOUT_MS)),
    ]);
    _state = 'ready';
  } catch (e) {
    _state = 'manual';
  }
  return _state;
}

// frameData：onCameraFrame 的 frame.data（RGBA ArrayBuffer）；w/h 为帧尺寸
// 返回 {has_face, x,y,w,h（相对坐标 0-1）, yaw, roll}；manual 模式下恒 {has_face:true}
async function detect(frameData, w, h) {
  if (_state === 'idle') init();  // 不等结果，下一帧起生效
  if (_state !== 'ready' || !_model) return { has_face: true };
  let tensor = null;
  try {
    // 方向：锁定前按探测序列转正（安卓竖屏横向帧，人脸侧躺检不出）
    const deg = _rotLocked ? _rot : _PROBE_ROTATIONS[_probeIdx % _PROBE_ROTATIONS.length];
    const rot = _rotateRGBA(frameData, w, h, deg);
    _lastRotated = rot;
    // RGBA → RGB（blazeface 输入 3 通道）
    const src = new Uint8Array(rot.data);
    const rgb = new Uint8Array(rot.w * rot.h * 3);
    for (let i = 0, j = 0; i < rot.w * rot.h * 4; i += 4, j += 3) {
      rgb[j] = src[i]; rgb[j + 1] = src[i + 1]; rgb[j + 2] = src[i + 2];
    }
    tensor = _tf.tensor3d(rgb, [rot.h, rot.w, 3]);
    const faces = await _model.estimateFaces(tensor, false);
    if (!faces || !faces.length) {
      if (!_rotLocked) _probeIdx++;  // 本方向没检出，下一帧换方向试
      return { has_face: false };
    }
    if (!_rotLocked) { _rot = deg; _rotLocked = true; }  // 检出即锁定方向
    const f = faces[0];
    const x1 = f.topLeft[0] / rot.w, y1 = f.topLeft[1] / rot.h;
    const x2 = f.bottomRight[0] / rot.w, y2 = f.bottomRight[1] / rot.h;
    const lm = f.landmarks || [];
    // landmarks 顺序：右眼、左眼、鼻尖、嘴、右耳、左耳（被摄者视角）
    let yaw = 0, roll = 0;
    if (lm.length >= 6) {
      const eyeR = lm[0], eyeL = lm[1], nose = lm[2], earR = lm[4], earL = lm[5];
      // 歪头：双眼连线与水平线夹角
      roll = Math.atan2(eyeL[1] - eyeR[1], eyeL[0] - eyeR[0]) * 180 / Math.PI;
      // 转头：鼻尖相对双眼中点的偏移，用双耳距离归一化（几何近似，无深度信息）
      const midEyeX = (eyeR[0] + eyeL[0]) / 2;
      const earDist = Math.max(Math.abs(earL[0] - earR[0]), 1);
      yaw = Math.max(-90, Math.min(90, (nose[0] - midEyeX) / earDist * 90));
    }
    return { has_face: true, x: x1, y: y1, w: x2 - x1, h: y2 - y1, yaw, roll };
  } catch (e) {
    return { has_face: true };  // 单帧失败不抖动 UI，按"有脸"放行
  } finally {
    if (tensor) tensor.dispose();
  }
}

module.exports = { init, detect, status, resetRotation, lastRotated, MODEL_URL };
