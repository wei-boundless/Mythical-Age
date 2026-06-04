// ============================================================
// 冒险岛传奇 2.0 — 15关游戏数据
// ============================================================

import type { MapData, Monster, NPC, Platform, Portal, MonsterKind, MonsterSize } from "./types";
import { MONSTER_SIZE_MULT } from "./config";

// ---- 怪物模板工厂 ----
let _monsterId = 0;
function nextId(): number {
  return ++_monsterId;
}

function makeMonster(
  kind: MonsterKind,
  size: MonsterSize,
  name: string,
  x: number,
  y: number,
  patrolRange: number,
  baseHp: number,
  baseDmg: number,
  baseDef: number,
  baseXp: number,
  isBoss: boolean = false
): Monster {
  const mult = MONSTER_SIZE_MULT[size];
  const w = Math.round(32 * mult.scale);
  const h = Math.round(32 * mult.scale);
  return {
    id: nextId(),
    kind,
    size,
    name,
    x,
    y,
    vx: 0,
    vy: 0,
    width: w,
    height: h,
    hp: Math.round(baseHp * mult.hpMult),
    maxHp: Math.round(baseHp * mult.hpMult),
    damage: Math.round(baseDmg * mult.dmgMult),
    def: Math.round(baseDef * mult.defMult),
    xpReward: Math.round(baseXp * mult.xpMult),
    patrolLeft: x - patrolRange,
    patrolRight: x + patrolRange,
    direction: "left",
    animFrame: 0,
    animTimer: 0,
    hitTimer: 0,
    alive: true,
    isBoss,
  };
}

// ---- 平台工具 ----
function plat(x: number, y: number, w: number, h: number = 16): Platform {
  return { x, y, w, h };
}

// ---- 传送门工具 ----
function portal(x: number, y: number, targetMap: number, targetX: number, targetY: number, label: string): Portal {
  return { x, y, width: 40, height: 56, targetMap, targetX, targetY, label };
}

// ---- NPC 对话集 ----
const NPC_DIALOGUES: Record<string, string[]> = {
  elder_start: [
    "老者：年轻的勇者啊，你终于来了……",
    "老者：黑暗魔王正在侵蚀这片大陆。",
    "老者：森林里到处都是他的爪牙。",
    "老者：带上这把铁剑和这枚护符，出发吧！",
    "勇者：我明白了。我一定会守护这片土地。",
    "【获得 铁剑 + 勇者护符】",
  ],
  forest_guide: [
    "精灵斥候：小心！前方有大量史莱姆出没。",
    "精灵斥候：它们虽然小，但成群结队很危险。",
    "精灵斥候：用你的剑斩出一条路吧！",
  ],
  forest_elder: [
    "树精长老：我能感受到森林正在哭泣……",
    "树精长老：魔王的污染越来越严重了。",
    "树精长老：请收下这件皮甲，它或许能帮到你。",
    "【获得 皮甲】",
  ],
  boss1_pre: [
    "？？？：愚蠢的人类，你以为你能阻止我吗？",
    "魔王（第一形态）：我是黑暗的化身！",
    "魔王（第一形态）：让我看看你有多少本事！",
  ],
  boss1_post: [
    "魔王：这……这不可能……",
    "魔王：你确实有些实力。但这才刚刚开始。",
    "魔王：我在城堡深处等你……哈哈哈哈哈……",
    "精灵长老：勇者大人！魔王逃往地下了！",
    "精灵长老：请务必追上去，不能让他恢复力量！",
  ],
  cave_entrance: [
    "矿工：前面就是幽暗洞穴了。",
    "矿工：进去的人很少有出来的……",
    "矿工：据说里面有骷髅兵和石像鬼在游荡。",
    "矿工：祝你好运，勇者。",
  ],
  trapped_elf: [
    "被困的精灵：谢天谢地！有人来了！",
    "被困的精灵：魔王把我关在这里为他抽取魔力。",
    "被困的精灵：我知道他的弱点——光明！",
    "被困的精灵：魔王惧怕神圣之力。",
    "被困的精灵：收下这把钢剑，它曾属于上一位勇者。",
    "【获得 钢剑】",
  ],
  cave_sage: [
    "洞穴贤者：我在这里等了很久了……",
    "洞穴贤者：这件锁子甲是我年轻时穿的。",
    "洞穴贤者：拿去吧，它还能派上用场。",
    "【获得 锁子甲】",
  ],
  boss2_pre: [
    "魔王（第二形态）：又见面了，小虫子。",
    "魔王（第二形态）：我吸收了无数灵魂的力量！",
    "魔王（第二形态）：这次你逃不掉了！",
  ],
  boss2_post: [
    "魔王：不可能……我明明……",
    "魔王：你身上有某种力量在保护你……",
    "魔王：但我的真身在城堡里！你永远到不了那里！",
    "精灵：勇者！你成功了！",
    "精灵：请用我的力量，加上这把秘银剑……",
    "精灵：去城堡终结这一切！",
    "【获得 秘银剑】",
  ],
  castle_gate: [
    "守卫亡魂：停……止……",
    "守卫亡魂：啊，是你……预言中的勇者……",
    "守卫亡魂：城门已为你开启。请拯救我们的灵魂。",
  ],
  knight_ghost: [
    "骑士亡魂：我曾是这里的骑士团长。",
    "骑士亡魂：魔王背叛了我们所有人。",
    "骑士亡魂：这铠甲……已经不需要了。",
    "骑士亡魂：穿上去战斗吧！",
    "【获得 骑士铠甲】",
  ],
  sage_ghost: [
    "贤者之魂：瞧我这把老骨头……",
    "贤者之魂：这块石头陪了我一辈子。",
    "贤者之魂：它能缓慢恢复持有者的生命。",
    "贤者之魂：拿去吧，勇者。",
    "【获得 贤者之石】",
  ],
  boss3_pre: [
    "魔王（最终形态）：你终于来了。",
    "魔王（最终形态）：我等你很久了，勇者。",
    "魔王（最终形态）：你以为那些小胜利能改变什么？",
    "魔王（最终形态）：在这城堡里，我就是法则！",
    "魔王（最终形态）：来吧！为这片大陆的命运而战！",
  ],
  boss3_post: [
    "魔王：不……不可能……",
    "魔王：区区人类……怎么可能有这种力量……",
    "魔王：我诅咒你……我诅咒……",
    "勇者：结束了。",
    "勇者：这片大陆终于恢复了和平。",
    "【圣光从天而降，照亮了整个城堡】",
    "旁白：勇者拾起了魔王留下的圣剑……",
    "【获得 圣剑】",
    "旁白：他成为了新的传说。冒险岛迎来了光明。",
    "🎉 恭喜通关！你已成为冒险岛传奇！ 🎉",
  ],
};

// ---- 装备掉落/赠送标记 ----
interface MapMeta {
  giftOnClear?: string; // 装备 ID
  healOnEnter?: boolean;
}

const mapMeta: MapMeta[] = [];

// ---- 15关地图 ----
export function buildMaps(): MapData[] {
  _monsterId = 0;
  const maps: MapData[] = [];

  // ==========================================================
  // 阶段一：翠绿森林 (关0-4)
  // ==========================================================

  // 关0：新手村
  maps.push({
    name: "新手村·启程",
    scene: "forest",
    width: 960,
    height: 540,
    bgColor: "#1a3a1a",
    platforms: [
      plat(0, 520, 960, 20), // 地面
      plat(150, 440, 100),
      plat(400, 380, 120),
      plat(700, 440, 100),
    ],
    monsters: [],
    npcs: [
      {
        x: 300,
        y: 472,
        width: 40,
        height: 48,
        name: "村长",
        dialogues: NPC_DIALOGUES.elder_start,
        triggered: false,
        giftItem: undefined,
        healsPlayer: true,
      },
    ],
    portals: [
      portal(860, 464, 1, 80, 460, "→ 翠绿森林"),
    ],
  });
  mapMeta.push({});

  // 关1：翠绿森林
  maps.push({
    name: "翠绿森林·入口",
    scene: "forest",
    width: 1440,
    height: 540,
    bgColor: "#1a3a1a",
    platforms: [
      plat(0, 520, 1440, 20),
      plat(200, 430, 100),
      plat(500, 400, 100),
      plat(800, 440, 120),
      plat(1100, 380, 100),
    ],
    monsters: [
      makeMonster("slime", "small", "小史莱姆", 300, 496, 80, 20, 4, 1, 10),
      makeMonster("slime", "small", "小史莱姆", 550, 496, 80, 20, 4, 1, 10),
      makeMonster("slime", "medium", "史莱姆", 900, 496, 100, 30, 6, 2, 15),
      makeMonster("mushroom", "small", "小毒蘑菇", 1200, 496, 60, 25, 5, 2, 12),
    ],
    npcs: [],
    portals: [
      portal(0, 464, 0, 860, 464, "← 新手村"),
      portal(1380, 464, 2, 80, 460, "→ 密林深处"),
    ],
  });
  mapMeta.push({});

  // 关2：密林深处
  maps.push({
    name: "翠绿森林·密林深处",
    scene: "forest",
    width: 1600,
    height: 540,
    bgColor: "#152d15",
    platforms: [
      plat(0, 520, 1600, 20),
      plat(180, 440, 100),
      plat(420, 370, 120),
      plat(700, 450, 100),
      plat(1000, 390, 100),
      plat(1300, 430, 120),
    ],
    monsters: [
      makeMonster("slime", "medium", "史莱姆", 250, 496, 90, 30, 6, 2, 15),
      makeMonster("mushroom", "small", "小毒蘑菇", 480, 496, 70, 25, 5, 2, 12),
      makeMonster("slime", "small", "小史莱姆", 750, 496, 80, 20, 4, 1, 10),
      makeMonster("mushroom", "medium", "毒蘑菇", 1080, 496, 80, 40, 8, 3, 20),
      makeMonster("slime", "medium", "史莱姆", 1350, 496, 90, 30, 6, 2, 15),
    ],
    npcs: [],
    portals: [
      portal(0, 464, 1, 1380, 464, "← 入口"),
      portal(1540, 464, 3, 80, 460, "→ 林中空地"),
    ],
  });
  mapMeta.push({});

  // 关3：林中空地（NPC给皮甲）
  maps.push({
    name: "翠绿森林·林中空地",
    scene: "forest",
    width: 1600,
    height: 540,
    bgColor: "#1d3d1d",
    platforms: [
      plat(0, 520, 1600, 20),
      plat(250, 430, 120),
      plat(550, 380, 100),
      plat(850, 440, 120),
      plat(1200, 370, 100),
    ],
    monsters: [
      makeMonster("mushroom", "medium", "毒蘑菇", 320, 496, 80, 40, 8, 3, 20),
      makeMonster("mushroom", "small", "小毒蘑菇", 620, 496, 70, 25, 5, 2, 12),
      makeMonster("slime", "large", "大史莱姆", 1000, 496, 100, 60, 10, 4, 30),
      makeMonster("mushroom", "medium", "毒蘑菇", 1400, 496, 80, 40, 8, 3, 20),
    ],
    npcs: [
      {
        x: 700,
        y: 472,
        width: 40,
        height: 48,
        name: "树精长老",
        dialogues: NPC_DIALOGUES.forest_elder,
        triggered: false,
        giftItem: {
          id: "leather_armor",
          name: "皮甲",
          slot: "armor",
          atk: 0, def: 3, hpBonus: 0, hpRegen: 0,
          description: "轻便的皮甲",
        },
      },
    ],
    portals: [
      portal(0, 464, 2, 1540, 464, "← 密林"),
      portal(1540, 464, 4, 80, 460, "→ Boss洞穴"),
    ],
  });
  mapMeta.push({ giftOnClear: "leather_armor" });

  // 关4：Boss前哨
  maps.push({
    name: "翠绿森林·Boss前哨",
    scene: "forest",
    width: 2000,
    height: 540,
    bgColor: "#0f1f0f",
    platforms: [
      plat(0, 520, 2000, 20),
      plat(200, 420, 120),
      plat(500, 370, 100),
      plat(900, 440, 120),
      plat(1300, 380, 100),
      plat(1700, 420, 120),
    ],
    monsters: [
      makeMonster("slime", "large", "大史莱姆", 300, 496, 100, 60, 10, 4, 30),
      makeMonster("mushroom", "large", "大毒蘑菇", 700, 496, 80, 70, 12, 5, 40),
      makeMonster("slime", "medium", "史莱姆", 1100, 496, 90, 30, 6, 2, 15),
      makeMonster("mushroom", "medium", "毒蘑菇", 1500, 496, 80, 40, 8, 3, 20),
    ],
    npcs: [],
    portals: [
      portal(0, 464, 3, 1540, 464, "← 空地"),
      portal(1920, 464, 5, 200, 400, "→ ⚠️ BOSS战"),
    ],
  });
  mapMeta.push({});

  // ==========================================================
  // Boss 1：关5 — 森林Boss
  // ==========================================================
  maps.push({
    name: "⚔️ Boss战：魔王第一形态",
    scene: "forest",
    width: 1200,
    height: 540,
    bgColor: "#0a0a1a",
    platforms: [
      plat(0, 520, 1200, 20),
      plat(300, 400, 200),
      plat(700, 420, 180),
    ],
    monsters: [
      makeMonster("boss", "large", "魔王·第一形态", 800, 472, 400, 300, 15, 8, 200, true),
    ],
    npcs: [],
    portals: [],
  });
  mapMeta.push({ giftOnClear: "steel_sword" });

  // ==========================================================
  // 阶段二：幽暗洞穴 (关6-9)
  // ==========================================================

  // 关6：洞穴入口
  maps.push({
    name: "幽暗洞穴·入口",
    scene: "cave",
    width: 1600,
    height: 540,
    bgColor: "#1a1a2e",
    platforms: [
      plat(0, 520, 1600, 20),
      plat(250, 430, 120),
      plat(550, 380, 100),
      plat(850, 440, 120),
      plat(1200, 370, 100),
    ],
    monsters: [
      makeMonster("skeleton", "small", "小骷髅兵", 300, 496, 80, 40, 8, 3, 20),
      makeMonster("skeleton", "small", "小骷髅兵", 600, 496, 80, 40, 8, 3, 20),
      makeMonster("skeleton", "medium", "骷髅兵", 1000, 496, 90, 60, 12, 5, 30),
    ],
    npcs: [
      {
        x: 1300,
        y: 472,
        width: 40,
        height: 48,
        name: "矿工",
        dialogues: NPC_DIALOGUES.cave_entrance,
        triggered: false,
      },
    ],
    portals: [
      portal(0, 464, 5, 1150, 400, "← 森林"),
      portal(1540, 464, 7, 80, 460, "→ 洞穴深处"),
    ],
  });
  mapMeta.push({});

  // 关7：洞穴深处
  maps.push({
    name: "幽暗洞穴·深处",
    scene: "cave",
    width: 1800,
    height: 540,
    bgColor: "#12122a",
    platforms: [
      plat(0, 520, 1800, 20),
      plat(200, 430, 100),
      plat(480, 380, 120),
      plat(750, 440, 100),
      plat(1050, 360, 120),
      plat(1400, 420, 100),
    ],
    monsters: [
      makeMonster("skeleton", "medium", "骷髅兵", 280, 496, 90, 60, 12, 5, 30),
      makeMonster("gargoyle", "small", "小石像鬼", 550, 496, 70, 45, 10, 4, 25),
      makeMonster("skeleton", "small", "小骷髅兵", 850, 496, 80, 40, 8, 3, 20),
      makeMonster("gargoyle", "medium", "石像鬼", 1200, 496, 80, 65, 14, 6, 35),
    ],
    npcs: [],
    portals: [
      portal(0, 464, 6, 1540, 464, "← 入口"),
      portal(1740, 464, 8, 80, 460, "→ 地下暗河"),
    ],
  });
  mapMeta.push({});

  // 关8：地下暗河（NPC给锁子甲）
  maps.push({
    name: "幽暗洞穴·地下暗河",
    scene: "cave",
    width: 1800,
    height: 540,
    bgColor: "#0f0f24",
    platforms: [
      plat(0, 520, 1800, 20),
      plat(300, 420, 120),
      plat(600, 380, 100),
      plat(900, 430, 120),
      plat(1200, 360, 100),
      plat(1500, 410, 120),
    ],
    monsters: [
      makeMonster("gargoyle", "medium", "石像鬼", 400, 496, 80, 65, 14, 6, 35),
      makeMonster("skeleton", "medium", "骷髅兵", 800, 496, 90, 60, 12, 5, 30),
      makeMonster("gargoyle", "small", "小石像鬼", 1100, 496, 70, 45, 10, 4, 25),
      makeMonster("skeleton", "large", "大骷髅兵", 1500, 496, 100, 100, 18, 8, 55),
    ],
    npcs: [
      {
        x: 1400,
        y: 472,
        width: 40,
        height: 48,
        name: "洞穴贤者",
        dialogues: NPC_DIALOGUES.cave_sage,
        triggered: false,
        giftItem: {
          id: "chainmail",
          name: "锁子甲",
          slot: "armor",
          atk: 0, def: 8, hpBonus: 0, hpRegen: 0,
          description: "坚固的锁子甲",
        },
      },
    ],
    portals: [
      portal(0, 464, 7, 1740, 464, "← 深处"),
      portal(1740, 464, 9, 80, 460, "→ Boss巢穴"),
    ],
  });
  mapMeta.push({ giftOnClear: "chainmail" });

  // 关9：Boss前哨
  maps.push({
    name: "幽暗洞穴·Boss前哨",
    scene: "cave",
    width: 2000,
    height: 540,
    bgColor: "#0a0a1e",
    platforms: [
      plat(0, 520, 2000, 20),
      plat(200, 430, 100),
      plat(500, 370, 120),
      plat(900, 440, 100),
      plat(1300, 370, 120),
      plat(1700, 430, 100),
    ],
    monsters: [
      makeMonster("gargoyle", "large", "大石像鬼", 350, 496, 80, 100, 18, 8, 55),
      makeMonster("skeleton", "large", "大骷髅兵", 750, 496, 100, 100, 18, 8, 55),
      makeMonster("gargoyle", "medium", "石像鬼", 1150, 496, 80, 65, 14, 6, 35),
      makeMonster("skeleton", "medium", "骷髅兵", 1550, 496, 90, 60, 12, 5, 30),
    ],
    npcs: [],
    portals: [
      portal(0, 464, 8, 1740, 464, "← 暗河"),
      portal(1920, 464, 10, 200, 400, "→ ⚠️ BOSS战"),
    ],
  });
  mapMeta.push({});

  // ==========================================================
  // Boss 2：关10 — 洞穴Boss
  // ==========================================================
  maps.push({
    name: "⚔️ Boss战：魔王第二形态",
    scene: "cave",
    width: 1200,
    height: 540,
    bgColor: "#080818",
    platforms: [
      plat(0, 520, 1200, 20),
      plat(250, 410, 180),
      plat(700, 420, 180),
    ],
    monsters: [
      makeMonster("boss", "large", "魔王·第二形态", 800, 472, 400, 600, 22, 12, 500, true),
    ],
    npcs: [],
    portals: [],
  });
  mapMeta.push({ giftOnClear: "mithril_sword" });

  // ==========================================================
  // 阶段三：魔王城堡 (关11-14)
  // ==========================================================

  // 关11：城堡外围
  maps.push({
    name: "魔王城堡·外围",
    scene: "castle",
    width: 1800,
    height: 540,
    bgColor: "#1a121a",
    platforms: [
      plat(0, 520, 1800, 20),
      plat(250, 430, 120),
      plat(550, 370, 100),
      plat(850, 440, 120),
      plat(1200, 360, 100),
      plat(1550, 420, 100),
    ],
    monsters: [
      makeMonster("dark_knight", "medium", "暗影骑士", 350, 496, 90, 80, 16, 7, 45),
      makeMonster("gargoyle", "medium", "石像鬼", 700, 496, 80, 65, 14, 6, 35),
      makeMonster("dark_knight", "small", "小暗影骑士", 1050, 496, 80, 60, 12, 5, 35),
    ],
    npcs: [
      {
        x: 200,
        y: 472,
        width: 40,
        height: 48,
        name: "守卫亡魂",
        dialogues: NPC_DIALOGUES.castle_gate,
        triggered: false,
      },
    ],
    portals: [
      portal(0, 464, 10, 1150, 400, "← 洞穴"),
      portal(1740, 464, 12, 80, 460, "→ 城堡大厅"),
    ],
  });
  mapMeta.push({});

  // 关12：城堡大厅（NPC给骑士铠甲）
  maps.push({
    name: "魔王城堡·大厅",
    scene: "castle",
    width: 1800,
    height: 540,
    bgColor: "#1a0a1a",
    platforms: [
      plat(0, 520, 1800, 20),
      plat(300, 420, 120),
      plat(600, 380, 100),
      plat(900, 430, 120),
      plat(1300, 370, 100),
      plat(1600, 420, 120),
    ],
    monsters: [
      makeMonster("dark_knight", "medium", "暗影骑士", 400, 496, 90, 80, 16, 7, 45),
      makeMonster("dark_knight", "medium", "暗影骑士", 800, 496, 90, 80, 16, 7, 45),
      makeMonster("gargoyle", "large", "大石像鬼", 1200, 496, 80, 100, 18, 8, 55),
    ],
    npcs: [
      {
        x: 700,
        y: 472,
        width: 40,
        height: 48,
        name: "骑士亡魂",
        dialogues: NPC_DIALOGUES.knight_ghost,
        triggered: false,
        giftItem: {
          id: "knight_armor",
          name: "骑士铠甲",
          slot: "armor",
          atk: 0, def: 15, hpBonus: 0, hpRegen: 0,
          description: "骑士的荣耀铠甲",
        },
      },
    ],
    portals: [
      portal(0, 464, 11, 1740, 464, "← 外围"),
      portal(1740, 464, 13, 80, 460, "→ 城堡上层"),
    ],
  });
  mapMeta.push({ giftOnClear: "knight_armor" });

  // 关13：城堡上层（NPC给贤者之石）
  maps.push({
    name: "魔王城堡·上层",
    scene: "castle",
    width: 2000,
    height: 540,
    bgColor: "#150a15",
    platforms: [
      plat(0, 520, 2000, 20),
      plat(250, 430, 100),
      plat(500, 380, 120),
      plat(850, 440, 100),
      plat(1200, 360, 120),
      plat(1550, 420, 100),
      plat(1800, 370, 100),
    ],
    monsters: [
      makeMonster("dark_knight", "large", "大暗影骑士", 350, 496, 100, 130, 22, 10, 70),
      makeMonster("dark_knight", "medium", "暗影骑士", 800, 496, 90, 80, 16, 7, 45),
      makeMonster("gargoyle", "large", "大石像鬼", 1200, 496, 80, 100, 18, 8, 55),
      makeMonster("dark_knight", "medium", "暗影骑士", 1650, 496, 90, 80, 16, 7, 45),
    ],
    npcs: [
      {
        x: 1000,
        y: 472,
        width: 40,
        height: 48,
        name: "贤者之魂",
        dialogues: NPC_DIALOGUES.sage_ghost,
        triggered: false,
        giftItem: {
          id: "sage_stone",
          name: "贤者之石",
          slot: "accessory",
          atk: 0, def: 0, hpBonus: 50, hpRegen: 1,
          description: "每秒回复生命，蕴含神秘力量",
        },
      },
    ],
    portals: [
      portal(0, 464, 12, 1740, 464, "← 大厅"),
      portal(1940, 464, 14, 80, 460, "→ Boss王座"),
    ],
  });
  mapMeta.push({ giftOnClear: "sage_stone" });

  // 关14：Boss前哨
  maps.push({
    name: "魔王城堡·王座前",
    scene: "castle",
    width: 2000,
    height: 540,
    bgColor: "#0f0a0f",
    platforms: [
      plat(0, 520, 2000, 20),
      plat(200, 420, 120),
      plat(500, 370, 100),
      plat(900, 430, 120),
      plat(1300, 360, 100),
      plat(1700, 420, 120),
    ],
    monsters: [
      makeMonster("dark_knight", "large", "大暗影骑士", 350, 496, 100, 130, 22, 10, 70),
      makeMonster("gargoyle", "large", "大石像鬼", 750, 496, 80, 100, 18, 8, 55),
      makeMonster("dark_knight", "large", "大暗影骑士", 1150, 496, 100, 130, 22, 10, 70),
      makeMonster("dark_knight", "medium", "暗影骑士", 1550, 496, 90, 80, 16, 7, 45),
    ],
    npcs: [],
    portals: [
      portal(0, 464, 13, 1940, 464, "← 上层"),
      portal(1920, 464, 15, 200, 380, "→ ⚠️ 最终BOSS"),
    ],
  });
  mapMeta.push({});

  // ==========================================================
  // Boss 3：关15 — 最终Boss
  // ==========================================================
  maps.push({
    name: "⚔️ 最终决战：魔王真身",
    scene: "castle",
    width: 1400,
    height: 540,
    bgColor: "#100010",
    platforms: [
      plat(0, 520, 1400, 20),
      plat(200, 400, 200),
      plat(600, 420, 200),
      plat(1000, 400, 200),
    ],
    monsters: [
      makeMonster("boss", "large", "魔王·真身", 900, 442, 500, 1000, 30, 18, 1000, true),
    ],
    npcs: [],
    portals: [],
  });
  mapMeta.push({ giftOnClear: "holy_sword" });

  return maps;
}

/** 获取地图元信息（装备掉落等） */
export function getMapMeta(index: number): MapMeta {
  return mapMeta[index] || {};
}

/** 获取Boss战前/后对话 */
export function getBossDialogue(mapIndex: number, postFight: boolean): string[] | null {
  if (mapIndex === 5 && !postFight) return NPC_DIALOGUES.boss1_pre;
  if (mapIndex === 5 && postFight) return NPC_DIALOGUES.boss1_post;
  if (mapIndex === 10 && !postFight) return NPC_DIALOGUES.boss2_pre;
  if (mapIndex === 10 && postFight) return NPC_DIALOGUES.boss2_post;
  if (mapIndex === 15 && !postFight) return NPC_DIALOGUES.boss3_pre;
  if (mapIndex === 15 && postFight) return NPC_DIALOGUES.boss3_post;
  return null;
}

/** 获取被困精灵对话（关10之前触发） */
export function getTrappedElfDialogue(): string[] {
  return NPC_DIALOGUES.trapped_elf;
}
