// ============================================================
// 冒险岛传奇 2.0 — 常量 & 数值平衡表
// ============================================================

import type { MonsterSize, SkillId, Equipment } from "./types";

// ---- 画布尺寸 ----
export const GAME_W = 960;
export const GAME_H = 540;

// ---- 物理常量 ----
export const GRAVITY = 0.6;
export const PLAYER_SPEED = 4;
export const PLAYER_JUMP_VY = -11;
export const PLAYER_WIDTH = 32;
export const PLAYER_HEIGHT = 48;

// ---- 玩家初始属性 ----
export const PLAYER_INIT_HP = 100;
export const PLAYER_INIT_ATK = 10;
export const PLAYER_INIT_DEF = 2;
export const PLAYER_INIT_MP = 50;

// ---- 攻击参数 ----
export const ATTACK_COOLDOWN = 18; // frames
export const ATTACK_DURATION = 10; // frames
export const INVINCIBLE_DURATION = 40;
export const ATTACK_RANGE_X = 38;
export const ATTACK_RANGE_Y = 44;

// ---- 经验公式 ----
/** 升到下一级所需总经验 */
export function xpForLevel(level: number): number {
  return level * level * 25 + 50;
}

/** 升级时回复量 */
export function healOnLevelUp(level: number): { hp: number; mp: number } {
  return { hp: level * 20, mp: level * 15 };
}

// ---- 伤害公式 ----
export function calcDamage(
  baseAtk: number,
  weaponAtk: number,
  skillDmg: number,
  monsterDef: number,
  armorDef: number
): number {
  const raw = (baseAtk + weaponAtk + skillDmg) - Math.max(0, monsterDef - armorDef);
  return Math.max(1, Math.round(raw));
}

// ---- 怪物体型系数 ----
export const MONSTER_SIZE_MULT: Record<MonsterSize, { scale: number; hpMult: number; dmgMult: number; defMult: number; xpMult: number }> = {
  small: { scale: 0.7, hpMult: 0.5, dmgMult: 0.6, defMult: 0.5, xpMult: 0.6 },
  medium: { scale: 1.0, hpMult: 1.0, dmgMult: 1.0, defMult: 1.0, xpMult: 1.0 },
  large: { scale: 1.4, hpMult: 2.0, dmgMult: 1.6, defMult: 1.5, xpMult: 1.8 },
};

// ---- 技能数据表 ----
export interface SkillDef {
  id: SkillId;
  name: string;
  unlockLevel: number;
  cooldownMax: number;
  duration: number;
  damage: number;
  mpCost: number;
  description: string;
  icon: string;
}

export const SKILLS: SkillDef[] = [
  {
    id: "whirlwind",
    name: "旋风斩",
    unlockLevel: 3,
    cooldownMax: 40,
    duration: 8,
    damage: 35,
    mpCost: 12,
    description: "旋转攻击周围敌人",
    icon: "🌀",
  },
  {
    id: "dash_slash",
    name: "冲刺斩",
    unlockLevel: 7,
    cooldownMax: 45,
    duration: 6,
    damage: 22,
    mpCost: 20,
    description: "向前冲刺并斩击",
    icon: "⚡",
  },
  {
    id: "holy_shield",
    name: "神圣护盾",
    unlockLevel: 10,
    cooldownMax: 180,
    duration: 120,
    damage: 0,
    mpCost: 30,
    description: "短时间内无敌",
    icon: "🛡️",
  },
  {
    id: "light_judgment",
    name: "光之审判",
    unlockLevel: 15,
    cooldownMax: 300,
    duration: 12,
    damage: 60,
    mpCost: 50,
    description: "全屏神圣打击",
    icon: "✨",
  },
];

// ---- 装备数据表 ----
export const EQUIPMENT_DB: Record<string, Equipment> = {
  iron_sword: {
    id: "iron_sword",
    name: "铁剑",
    slot: "weapon",
    atk: 5,
    def: 0,
    hpBonus: 0,
    hpRegen: 0,
    description: "普通的铁剑，每位勇者的起点",
  },
  steel_sword: {
    id: "steel_sword",
    name: "钢剑",
    slot: "weapon",
    atk: 10,
    def: 0,
    hpBonus: 0,
    hpRegen: 0,
    description: "精钢锻造，锋利无比",
  },
  mithril_sword: {
    id: "mithril_sword",
    name: "秘银剑",
    slot: "weapon",
    atk: 18,
    def: 0,
    hpBonus: 0,
    hpRegen: 0,
    description: "秘银打造，对魔王有克制效果",
  },
  holy_sword: {
    id: "holy_sword",
    name: "圣剑",
    slot: "weapon",
    atk: 30,
    def: 0,
    hpBonus: 0,
    hpRegen: 0,
    description: "传说中的神圣之剑，只有真正的勇者才能驾驭",
  },
  leather_armor: {
    id: "leather_armor",
    name: "皮甲",
    slot: "armor",
    atk: 0,
    def: 3,
    hpBonus: 0,
    hpRegen: 0,
    description: "轻便的皮甲",
  },
  chainmail: {
    id: "chainmail",
    name: "锁子甲",
    slot: "armor",
    atk: 0,
    def: 8,
    hpBonus: 0,
    hpRegen: 0,
    description: "坚固的锁子甲",
  },
  knight_armor: {
    id: "knight_armor",
    name: "骑士铠甲",
    slot: "armor",
    atk: 0,
    def: 15,
    hpBonus: 0,
    hpRegen: 0,
    description: "骑士的荣耀铠甲",
  },
  hero_amulet: {
    id: "hero_amulet",
    name: "勇者护符",
    slot: "accessory",
    atk: 0,
    def: 0,
    hpBonus: 20,
    hpRegen: 0,
    description: "增加生命上限的护符",
  },
  sage_stone: {
    id: "sage_stone",
    name: "贤者之石",
    slot: "accessory",
    atk: 0,
    def: 0,
    hpBonus: 50,
    hpRegen: 1,
    description: "每秒回复生命，蕴含神秘力量",
  },
};

// ---- MP 回复 ----
export const MP_REGEN_RATE = 0.08; // 每帧回复
