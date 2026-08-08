// 同款大片公共：catalog → 模板/系列列表（含封面、热度、缺省回退）
// 后端新字段（moments/tags/hot/cover/status）可能缺失，全部在这里兜底。

const MODE_LABEL = { couple: '情侣', solo_f: '女单', solo_m: '男单' };

// 热度展示：1234 → 1.2k；无 hot 字段时返回空串（页面不渲染人数）
function formatHot(hot) {
  if (typeof hot !== 'number' || !hot) return '';
  return hot >= 1000 ? (hot / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(hot);
}

// 模板数组：img 相对路径拼 apiBase
function buildTemplates(res, apiBase) {
  return (res.moka || []).map(t => ({ ...t, img: apiBase + t.img }));
}

// 系列数组：变体解析成完整模板对象，封面取 series.cover 指定变体（缺省首个）
function buildSeriesList(res, templates) {
  const tmap = {};
  templates.forEach(t => { tmap[t.id] = t; });
  const groupTitle = {};
  (res.moka_groups || []).forEach(g => { groupTitle[g.id] = g.title; });
  return (res.moka_series || []).map(s => {
    const variants = (s.variants || []).map(v => tmap[v]).filter(Boolean);
    const coverTpl = (s.cover && tmap[s.cover]) || variants[0];
    const status = s.status || 'normal';
    return {
      ...s,
      variants,
      count: variants.length,
      coverId: coverTpl ? coverTpl.id : '',
      coverImg: coverTpl ? coverTpl.img : '',
      desc: s.desc || (variants[0] && variants[0].desc) || '',
      modeText: MODE_LABEL[s.mode] || '',
      tags: Array.isArray(s.tags) ? s.tags : [],
      moments: Array.isArray(s.moments) ? s.moments : [],
      hotVal: typeof s.hot === 'number' ? s.hot : 0,
      hasHot: typeof s.hot === 'number' && s.hot > 0,
      hotText: formatHot(s.hot),
      status,
      badgeText: status === 'new' ? '新上' : (status === 'limited' ? '限定' : ''),
      groupTitle: groupTitle[s.group] || '',
    };
  }).filter(s => s.count);
}

module.exports = { MODE_LABEL, formatHot, buildTemplates, buildSeriesList };
