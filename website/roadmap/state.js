const ROADMAP_STATE = {
  "_note": "徐大恩 LuckyNemo 战略路线图状态文件 v2（唯一事实源，本地使用）。route: main(主线·胜负手) / tech(技术突破) / market(市场验证) / side(支线)。critical: 关键任务（胜负手或卡点）。status: done / doing / todo。更新方式：用户勾选或告知 Kimi，由 Kimi 修改本文件。",
  "updated_at": "2026-07-25",
  "vision": {
    "title": "AI 原生驱动的影像服务公司",
    "goal": "2029 年成为中国婚庆短片市场第一名，或年收入 10 亿+",
    "thesis": "胜负手不是技术，是婚礼现场的病毒系数 K：每支成片在婚礼现场被 100-300 名精准人群（同龄、备婚）观看——产品即广告。片尾放「扫码，给你们的故事也做一支」，把交付物变成渠道，增长就是自费的。第二胜负手：用 Nemo Studio 把工作室从同行收编成渠道。"
  },
  "crux": [
    {
      "id": "d1",
      "level": "致命",
      "title": "一次性消费、没有复购",
      "detail": "LTV=首单，CAC 必须被首单毛利覆盖。破法：K 系数裂变 + 钩子产品（尝鲜/快道）拉低获客成本"
    },
    {
      "id": "d2",
      "level": "致命",
      "title": "合规摩擦（真人形象录入）",
      "detail": "每个真实客户单都要人脸核验+授权，是产能悬崖。破法：录入自助化 + 反转为信任卖点「官方认证，保护你的脸」"
    },
    {
      "id": "d3",
      "level": "重",
      "title": "人效瓶颈",
      "detail": "脚本/品控/沟通全靠人。破法：模板库+共创自动化+品控半自动，目标 0.3 人日/单"
    },
    {
      "id": "d4",
      "level": "重",
      "title": "质量信任状",
      "detail": "「AI 会不会不像我」是下单第一阻力。破法：先出定妆照满意再付款（风险逆转）+ 样片墙"
    },
    {
      "id": "d5",
      "level": "中",
      "title": "渠道单一",
      "detail": "过度依赖小红书。破法：婚礼现场裂变 + 婚礼纪/到喜啦 + B 端渠道"
    }
  ],
  "cognitive": [
    "从「卖片子」到「卖传播」：产品是社交货币，定价和交付要收传播红利",
    "从「合规是成本」到「合规是信任资产」：真人录入做成卖点",
    "从「同行是对手」到「同行是渠道」：影楼有客无技，我们有技无客",
    "从「憋大招」到「假设速度」：50 单验证优先于继续打磨",
    "从「留存思维」到「K 系数思维」：一次性生意看裂变不看复购"
  ],
  "routes": {
    "main": {
      "name": "主线 · 胜负手（病毒飞轮）",
      "items": [
        {
          "id": "m1",
          "title": "片尾裂变卡设计：「扫码，给你们的故事也做一支」",
          "status": "done",
          "critical": true
        },
        {
          "id": "m2",
          "title": "婚礼现场传播设计：交付包内含投屏版+分享版+裂变卡",
          "status": "done",
          "critical": true
        },
        {
          "id": "m3",
          "title": "私域承接链路（企微+扫码直达下单页）",
          "status": "todo",
          "critical": true
        },
        {
          "id": "m4",
          "title": "K 系数验证：50 单现场转化追踪（目标每单 ≥1 咨询）",
          "status": "todo",
          "critical": true
        },
        {
          "id": "m7",
          "title": "品质三板斧：情感节拍表 + AI 剧本体检门 + 双盲试映",
          "status": "todo",
          "critical": true
        },
        {
          "id": "m8",
          "title": "裂变定价上线：现场扫码减 ¥200 + 转介绍双向抵扣",
          "status": "todo",
          "critical": true
        },
        {
          "id": "m5",
          "title": "B 端收编：Nemo Studio 10 家工作室内测",
          "status": "todo",
          "critical": false
        },
        {
          "id": "m6",
          "title": "B 端 ¥499/月 付费验证（转化 ≥30%）",
          "status": "todo",
          "critical": false
        },
        {
          "id": "m9",
          "title": "小程序照相馆 MVP（人脸核身+选装+免费1张+49套餐）",
          "status": "todo",
          "critical": true
        },
        {
          "id": "m10",
          "title": "AI 订单线程：每单一条持续对话（照相馆+短片共创）",
          "status": "todo",
          "critical": true
        }
      ]
    },
    "tech": {
      "name": "技术突破线",
      "items": [
        {
          "id": "t1",
          "title": "真人形象录入自助化流程（产能悬崖 D2）",
          "status": "todo",
          "critical": true
        },
        {
          "id": "t2",
          "title": "reference_image 模式全线切换（已验证零漂移）",
          "status": "done",
          "critical": false
        },
        {
          "id": "t3",
          "title": "口型路径验证：reference_audio 音画同出（已通，音色仿声待定）",
          "status": "done",
          "critical": false
        },
        {
          "id": "t4",
          "title": "品控半自动：ArcFace 阈值用真实单校准",
          "status": "todo",
          "critical": false
        },
        {
          "id": "t5",
          "title": "LoveStory 剧本工具 skill 化（访谈→长线故事→节拍表→体检门）",
          "status": "doing",
          "critical": true
        },
        {
          "id": "t6",
          "title": "单均人工压到 0.3 人日（模板+共创+半自动品控）",
          "status": "todo",
          "critical": true
        },
        {
          "id": "t7",
          "title": "快道产品：领证 2h 交付（quick_pipeline）",
          "status": "done",
          "critical": false
        },
        {
          "id": "t8",
          "title": "AI 剧本体检门：情感曲线+真实细节密度自动评分",
          "status": "todo",
          "critical": false
        }
      ]
    },
    "market": {
      "name": "市场验证线",
      "items": [
        {
          "id": "v1",
          "title": "奔奔首单：真人核验未过，先用虚拟形象讲好她的故事（剧本打磨中）",
          "status": "doing",
          "critical": true
        },
        {
          "id": "v2",
          "title": "小红书冷启动（账号+样片投放）",
          "status": "todo",
          "critical": false
        },
        {
          "id": "v3",
          "title": "首批 50 付费单（H1 付费意愿/H2 像本人/H3 成本）",
          "status": "todo",
          "critical": true
        },
        {
          "id": "v4",
          "title": "CAC 验证：小红书聚光 < ¥150",
          "status": "todo",
          "critical": false
        },
        {
          "id": "v5",
          "title": "定妆照满意再付款（风险逆转，破 D4）",
          "status": "todo",
          "critical": false
        },
        {
          "id": "v6",
          "title": "婚礼纪/到喜啦渠道入驻评估",
          "status": "todo",
          "critical": false
        },
        {
          "id": "v7",
          "title": "50 单复盘：转化/退款/NPS/单均成本",
          "status": "todo",
          "critical": false
        },
        {
          "id": "v8",
          "title": "定价体系 v1：阶梯 + 风险逆转定金 + 裂变价",
          "status": "done",
          "critical": false
        },
        {
          "id": "v9",
          "title": "49 元/50 张获客武器：转化与亏损护栏验证",
          "status": "todo",
          "critical": true
        }
      ]
    },
    "side": {
      "name": "支线任务",
      "items": [
        {
          "id": "s1",
          "title": "商标 41/45 类注册",
          "status": "todo",
          "critical": false
        },
        {
          "id": "s2",
          "title": "OSS 30 天生命周期（交付即删兑现）",
          "status": "todo",
          "critical": false
        },
        {
          "id": "s3",
          "title": "luckynemo.com 备案推进",
          "status": "todo",
          "critical": false
        },
        {
          "id": "s4",
          "title": "霓裳阁扩充：配饰/鞋履第二批→每类 100+",
          "status": "done",
          "critical": false
        },
        {
          "id": "s5",
          "title": "剧本模板库扩到 12 套",
          "status": "todo",
          "critical": false
        },
        {
          "id": "s6",
          "title": "MiniMax 音乐商用授权确认",
          "status": "todo",
          "critical": false
        },
        {
          "id": "s7",
          "title": "声音授权模板补「AI 口型合成」条款",
          "status": "todo",
          "critical": false
        },
        {
          "id": "s8",
          "title": "制片手册与新人培训认证体系",
          "status": "todo",
          "critical": false
        },
        {
          "id": "s9",
          "title": "LoveStory skill 部署进 LuckyNemo 网关",
          "status": "todo",
          "critical": false
        },
        {
          "id": "s10",
          "title": "小程序主体：企业注册+微信认证+算法备案+人脸核身申请",
          "status": "todo",
          "critical": true
        }
      ]
    }
  },
  "hypotheses": [
    {
      "id": "h1",
      "text": "消费者愿为 AI 叙事短片付 ¥999",
      "method": "首批 50 单付费率与退款率",
      "target": "退款率 < 5%",
      "status": "todo"
    },
    {
      "id": "h2",
      "text": "成片「像本人」达到满意阈值",
      "method": "一次通过率与修改次数",
      "target": "一次通过 ≥80%，修改 ≤2 次",
      "status": "todo"
    },
    {
      "id": "h3",
      "text": "单均成本（算力+人工）≤ ¥300",
      "method": "50 单成本台账",
      "target": "毛利 ≥70%",
      "status": "todo"
    },
    {
      "id": "h4",
      "text": "小红书私域获客 CAC ≤ ¥150",
      "method": "聚光投放 A/B",
      "target": "CAC < 首单毛利 1/3",
      "status": "todo"
    },
    {
      "id": "h5",
      "text": "婚礼现场 K 系数 ≥ 1",
      "method": "50 单现场转化追踪",
      "target": "每单 ≥1 个现场咨询",
      "status": "todo"
    },
    {
      "id": "h6",
      "text": "工作室愿为 Nemo Studio 付 ¥499/月",
      "method": "10 家内测转化",
      "target": "付费转化 ≥30%",
      "status": "todo"
    },
    {
      "id": "h7",
      "text": "剧本共创带来「独一无二」感知",
      "method": "交付满意度问卷",
      "target": "≥4.5/5 分",
      "status": "todo"
    },
    {
      "id": "h8",
      "text": "产能可线性复制",
      "method": "新制片 1 周上岗作品方差",
      "target": "品控通过率与熟手相当",
      "status": "todo"
    },
    {
      "id": "h9",
      "text": "「笑了又湿」是飞轮燃料",
      "method": "双盲试映通过率 + 交付 NPS",
      "target": "试映通过率 ≥90%，NPS ≥60",
      "status": "todo"
    },
    {
      "id": "h10",
      "text": "49 元照相馆是高效获客前端",
      "method": "切片广告 A/B + 套餐转化漏斗",
      "target": "获客成本 < 短片首单毛利，升级率 ≥10%",
      "status": "todo"
    }
  ]
};
