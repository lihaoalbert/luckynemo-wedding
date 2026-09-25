// BlazeFace 人脸检测封装（小程序端侧推理）
// - 惰性初始化：第一次 detect 时才装依赖、配插件、加载模型（网络加载，不打进包）
// - 依赖官方 tfjs 插件 tfjsPlugin（app.json 已声明，需在小程序后台添加）+ npm 包
//   （@tensorflow/tfjs-core / tfjs-converter / tfjs-backend-webgl / @tensorflow-models/blazeface / fetch-wechat）
// - 模型默认走谷歌中国镜像，可切自有 CDN：把 MODEL_URL 改到 OSS 即可（权重 ~300KB）
// - 任何一步失败都降级为 manual 模式：detect 恒返回 has_face:true（无框），
//   拍摄页据此关闭自动抓拍、显示「手动对准框线拍摄」
const MODEL_URL = 'https://www.gstaticcnapps.cn/tfjs-models/savedmodel/blazeface/model.json';
const INPUT_SIZE = [128, 128];  // blazeface 默认输入

let _state = 'idle';   // idle → loading → ready | manual
let _model = null;
let _tf = null;

function status() { return _state; }

function _loadDeps() {
  // 构建 npm 之前 require 会抛错，这里统一兜住走降级
  try {
    const tf = require('@tensorflow/tfjs-core');
    const fetchWechat = require('fetch-wechat');
    require('@tensorflow/tfjs-backend-webgl');
    const blazeface = require('@tensorflow-models/blazeface');
    return { tf, fetchWechat, blazeface };
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
  const { tf, fetchWechat, blazeface } = deps;
  try {
    // 官方插件注入 webgl 后端 + fetch polyfill（必须在页面内调，onLaunch 里调会因
    // offscreen canvas 随页面跳转失效而出错，见 tfjs-wechat README）
    const plugin = requirePlugin('tfjsPlugin');
    plugin.configPlugin({
      fetchFunc: fetchWechat.fetchFunc(),
      tf,
      canvas: wx.createOffscreenCanvas(),
      backendName: 'wechat-webgl-idphoto',
    });
    _tf = tf;
    try {
      // 首选 blazeface.load()（tfhub 在线加载）
      _model = await blazeface.load({ maxFaces: 1 });
    } catch (e1) {
      // tfhub 不通时退到镜像/自有 CDN：手动 loadGraphModel + 组装 BlazeFaceModel
      const tfconv = require('@tensorflow/tfjs-converter');
      const graph = await tfconv.loadGraphModel(MODEL_URL);
      _model = new blazeface.BlazeFaceModel(graph, INPUT_SIZE, 1, 0.3, 0.75);
    }
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
    // RGBA → RGB（blazeface 输入 3 通道）
    const src = new Uint8Array(frameData);
    const rgb = new Uint8Array(w * h * 3);
    for (let i = 0, j = 0; i < w * h * 4; i += 4, j += 3) {
      rgb[j] = src[i]; rgb[j + 1] = src[i + 1]; rgb[j + 2] = src[i + 2];
    }
    tensor = _tf.tensor3d(rgb, [h, w, 3]);
    const faces = await _model.estimateFaces(tensor, false);
    if (!faces || !faces.length) return { has_face: false };
    const f = faces[0];
    const x1 = f.topLeft[0] / w, y1 = f.topLeft[1] / h;
    const x2 = f.bottomRight[0] / w, y2 = f.bottomRight[1] / h;
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

module.exports = { init, detect, status, MODEL_URL };
