const SETS = [
  {
    "id": "set-01",
    "name": "晨曦缎光",
    "style": "西式经典",
    "pitch": "最不容易出错的一套，缎面的光泽就是高级感本身",
    "scenes": [
      "室内主纱",
      "仪式堂"
    ],
    "dress": {
      "id": "nz-001",
      "name": "晨曦缎光·A字缎面主纱",
      "img": "img/婚纱/nz-001.jpg"
    },
    "suit": {
      "id": "lf-001",
      "name": "晨曦缎光·黑色塔士多",
      "img": "img/礼服/lf-001.jpg"
    },
    "accessory": "珍珠耳钉+短款头纱",
    "shoes": "缎面婚鞋"
  },
  {
    "id": "set-02",
    "name": "云端蕾丝",
    "style": "西式浪漫",
    "pitch": "鱼尾勾勒线条，长头纱一铺，仪式感拉满",
    "scenes": [
      "教堂",
      "仪式堂"
    ],
    "dress": {
      "id": "nz-002",
      "name": "云端蕾丝·蕾丝鱼尾主纱",
      "img": "img/婚纱/nz-002.jpg"
    },
    "suit": {
      "id": "lf-002",
      "name": "云端蕾丝·深灰三件套",
      "img": "img/礼服/lf-002.jpg"
    },
    "accessory": "长款教堂头纱",
    "shoes": "水晶鞋"
  },
  {
    "id": "set-03",
    "name": "森系轻纱",
    "style": "户外自然",
    "pitch": "轻到可以跑起来的婚纱，适合光脚亲吻风的婚礼",
    "scenes": [
      "草坪",
      "森林"
    ],
    "dress": {
      "id": "nz-003",
      "name": "森系轻纱·波西米亚轻纱",
      "img": "img/婚纱/nz-003.jpg"
    },
    "suit": {
      "id": "lf-003",
      "name": "森系轻纱·亚麻浅色西装",
      "img": "img/礼服/lf-003.jpg"
    },
    "accessory": "鲜花花环",
    "shoes": "裸色平底鞋"
  },
  {
    "id": "set-04",
    "name": "海之誓言",
    "style": "旅拍",
    "pitch": "拖尾交给海风，落日负责打光",
    "scenes": [
      "海边",
      "落日"
    ],
    "dress": {
      "id": "nz-004",
      "name": "海之誓言·露背长拖尾白纱",
      "img": "img/婚纱/nz-004.jpg"
    },
    "suit": {
      "id": "lf-004",
      "name": "海之誓言·白衬衫挽袖+深色西裤",
      "img": "img/礼服/lf-004.jpg"
    },
    "accessory": "贝壳发饰",
    "shoes": "赤足/平底凉鞋"
  },
  {
    "id": "set-05",
    "name": "复古名伶",
    "style": "复古胶片",
    "pitch": "像从 1960 年的相片里走出来",
    "scenes": [
      "老街",
      "胶片感内景"
    ],
    "dress": {
      "id": "nz-005",
      "name": "复古名伶·复古方领缎面裙",
      "img": "img/婚纱/nz-005.jpg"
    },
    "suit": {
      "id": "lf-005",
      "name": "复古名伶·天鹅绒礼服",
      "img": "img/礼服/lf-005.jpg"
    },
    "accessory": "鸟笼网纱头饰",
    "shoes": "玛丽珍鞋"
  },
  {
    "id": "set-06",
    "name": "都市极简",
    "style": "韩式极简",
    "pitch": "越简单，越耐看",
    "scenes": [
      "纯色棚拍",
      "美术馆"
    ],
    "dress": {
      "id": "nz-006",
      "name": "都市极简·吊带极简长裙",
      "img": "img/婚纱/nz-006.jpg"
    },
    "suit": {
      "id": "lf-006",
      "name": "都市极简·浅灰西装",
      "img": "img/礼服/lf-006.jpg"
    },
    "accessory": "极简金属耳饰",
    "shoes": "裸色高跟"
  },
  {
    "id": "set-07",
    "name": "花园午后",
    "style": "法式田园",
    "pitch": "像一场永远散不了席的午后野餐",
    "scenes": [
      "花园",
      "野餐"
    ],
    "dress": {
      "id": "nz-007",
      "name": "花园午后·碎花茶歇裙",
      "img": "img/婚纱/nz-007.jpg"
    },
    "suit": {
      "id": "lf-007",
      "name": "花园午后·米色西装",
      "img": "img/礼服/lf-007.jpg"
    },
    "accessory": "草编帽",
    "shoes": "编织凉鞋"
  },
  {
    "id": "set-08",
    "name": "星空晚礼",
    "style": "晚宴",
    "pitch": "灯光一暗，她就是全场唯一的光源",
    "scenes": [
      "夜景",
      "宴会厅"
    ],
    "dress": {
      "id": "nz-008",
      "name": "星空晚礼·亮片晚礼服",
      "img": "img/婚纱/nz-008.jpg"
    },
    "suit": {
      "id": "lf-008",
      "name": "星空晚礼·午夜蓝西装",
      "img": "img/礼服/lf-008.jpg"
    },
    "accessory": "星芒头饰",
    "shoes": "银色高跟"
  },
  {
    "id": "set-09",
    "name": "红金囍嫁",
    "style": "中式传统",
    "pitch": "红金配色一上身，长辈的眼泪就到位了",
    "scenes": [
      "中式婚房",
      "灯笼布景"
    ],
    "dress": {
      "id": "nz-009",
      "name": "红金囍嫁·金丝刺绣秀禾服",
      "img": "img/中式/nz-009.jpg"
    },
    "suit": {
      "id": "lf-009",
      "name": "红金囍嫁·暗红长袍马褂",
      "img": "img/礼服/lf-009.jpg"
    },
    "accessory": "凤冠珠钗",
    "shoes": "红色绣鞋"
  },
  {
    "id": "set-10",
    "name": "龙凤呈祥",
    "style": "中式大典",
    "pitch": "褂皇褂后的气场，是西装给不了的",
    "scenes": [
      "传统仪式",
      "祠堂"
    ],
    "dress": {
      "id": "nz-010",
      "name": "龙凤呈祥·龙凤褂",
      "img": "img/中式/nz-010.jpg"
    },
    "suit": {
      "id": "lf-010",
      "name": "龙凤呈祥·黑色中山装",
      "img": "img/礼服/lf-010.jpg"
    },
    "accessory": "鎏金珠钗",
    "shoes": "黑缎鞋"
  },
  {
    "id": "set-11",
    "name": "旗袍往事",
    "style": "民国风",
    "pitch": "镁光灯一闪，回到 1932",
    "scenes": [
      "民国照相馆",
      "老街"
    ],
    "dress": {
      "id": "nz-011",
      "name": "旗袍往事·墨绿旗袍",
      "img": "img/中式/nz-011.jpg"
    },
    "suit": {
      "id": "lf-011",
      "name": "旗袍往事·深色中山装",
      "img": "img/礼服/lf-011.jpg"
    },
    "accessory": "白玉发簪",
    "shoes": "复古低跟鞋"
  },
  {
    "id": "set-12",
    "name": "新中式·竹",
    "style": "新中式",
    "pitch": "把江南的竹子穿在身上",
    "scenes": [
      "庭院",
      "茶室"
    ],
    "dress": {
      "id": "nz-012",
      "name": "新中式·竹·竹青改良旗袍",
      "img": "img/中式/nz-012.jpg"
    },
    "suit": {
      "id": "lf-012",
      "name": "新中式·竹·新中式立领装",
      "img": "img/礼服/lf-012.jpg"
    },
    "accessory": "竹节发簪",
    "shoes": "素色布鞋"
  },
  {
    "id": "set-13",
    "name": "初雪便利",
    "style": "轻婚纱日常",
    "pitch": "不穿婚纱的婚纱照，反而更像过日子",
    "scenes": [
      "冬日街景",
      "便利店"
    ],
    "dress": {
      "id": "nz-013",
      "name": "初雪便利·白色针织裙",
      "img": "img/婚纱/nz-013.jpg"
    },
    "suit": {
      "id": "lf-013",
      "name": "初雪便利·驼色大衣",
      "img": "img/礼服/lf-013.jpg"
    },
    "accessory": "毛线帽",
    "shoes": "短靴"
  },
  {
    "id": "set-14",
    "name": "图书馆之约",
    "style": "学院风",
    "pitch": "适合从校园走到婚纱的你们",
    "scenes": [
      "图书馆",
      "校园"
    ],
    "dress": {
      "id": "nz-014",
      "name": "图书馆之约·白衬衫+A字裙",
      "img": "img/婚纱/nz-014.jpg"
    },
    "suit": {
      "id": "lf-014",
      "name": "图书馆之约·毛衣背心+衬衫",
      "img": "img/礼服/lf-014.jpg"
    },
    "accessory": "发带",
    "shoes": "乐福鞋"
  },
  {
    "id": "set-15",
    "name": "机车与纱",
    "style": "个性街拍",
    "pitch": "婚纱配皮夹克，乖和野都要",
    "scenes": [
      "街拍",
      "天台"
    ],
    "dress": {
      "id": "nz-015",
      "name": "机车与纱·短款轻纱+皮夹克",
      "img": "img/婚纱/nz-015.jpg"
    },
    "suit": {
      "id": "lf-015",
      "name": "机车与纱·黑T+牛仔裤",
      "img": "img/礼服/lf-015.jpg"
    },
    "accessory": "短靴",
    "shoes": ""
  },
  {
    "id": "set-16",
    "name": "童话加冕",
    "style": "童话风",
    "pitch": "每个女孩都该有一次公主出场",
    "scenes": [
      "城堡",
      "旋转楼梯"
    ],
    "dress": {
      "id": "nz-016",
      "name": "童话加冕·蓬蓬公主裙",
      "img": "img/婚纱/nz-016.jpg"
    },
    "suit": {
      "id": "lf-016",
      "name": "童话加冕·王子风礼服",
      "img": "img/礼服/lf-016.jpg"
    },
    "accessory": "水晶冠",
    "shoes": "水晶鞋"
  },
  {
    "id": "set-17",
    "name": "唐风华服",
    "style": "唐制汉服",
    "pitch": "云想衣裳花想容",
    "scenes": [
      "唐风布景",
      "园林"
    ],
    "dress": {
      "id": "nz-017",
      "name": "唐风华服·齐胸襦裙",
      "img": "img/中式/nz-017.jpg"
    },
    "suit": {
      "id": "lf-017",
      "name": "唐风华服·唐制圆领袍",
      "img": "img/礼服/lf-017.jpg"
    },
    "accessory": "花钿+步摇",
    "shoes": "云头履"
  },
  {
    "id": "set-18",
    "name": "宋制雅集",
    "style": "宋制汉服",
    "pitch": "宋人的审美，放今天依然是顶流",
    "scenes": [
      "宋风园林",
      "书房"
    ],
    "dress": {
      "id": "nz-018",
      "name": "宋制雅集·宋制褙子套装",
      "img": "img/中式/nz-018.jpg"
    },
    "suit": {
      "id": "lf-018",
      "name": "宋制雅集·宋圆领袍",
      "img": "img/礼服/lf-018.jpg"
    },
    "accessory": "珍珠妆面",
    "shoes": "弓鞋"
  },
  {
    "id": "set-19",
    "name": "港风霓虹",
    "style": "港风复古",
    "pitch": "王家卫镜头里的那种暧昧",
    "scenes": [
      "霓虹夜景",
      "茶餐厅"
    ],
    "dress": {
      "id": "nz-019",
      "name": "港风霓虹·缎面吊带裙",
      "img": "img/婚纱/nz-019.jpg"
    },
    "suit": {
      "id": "lf-019",
      "name": "港风霓虹·花衬衫+西装外套",
      "img": "img/礼服/lf-019.jpg"
    },
    "accessory": "大波浪假发片",
    "shoes": "复古高跟"
  },
  {
    "id": "set-20",
    "name": "雪山之巅",
    "style": "旅拍大片",
    "pitch": "在离天最近的地方说愿意",
    "scenes": [
      "雪山",
      "高原"
    ],
    "dress": {
      "id": "nz-020",
      "name": "雪山之巅·长袖缎面主纱",
      "img": "img/婚纱/nz-020.jpg"
    },
    "suit": {
      "id": "lf-020",
      "name": "雪山之巅·白色西装",
      "img": "img/礼服/lf-020.jpg"
    },
    "accessory": "羊绒披肩",
    "shoes": "皮靴"
  }
];
