// ============================================================
// 冒险岛传奇 2.0 — 类型定义
// ============================================================

export type Direction = "left" | "right";
export type GamePhase =
  | "title"
  | "playing"
  | "dialogue"
  | "map_transition"
  | "victory"
  | "game_over";

export type MonsterKind =
  | "slime"
  | "mushroom"
  | "skeleton"
  | "gargoyle"
  | "dark_knight"
  | "boss";

export type MonsterSize = "small" | "medium" | "large";

export type SkillId = "whirlwind" | "dash_slash" | "holy_shield" | "light_judgment";

export type EquipmentSlot = "weapon" | "armor" | "accessory";

export type SceneKind = "forest" | "cave" | "castle";

// ---- 装备 ----
export interface Equipment {
  id: string;
  name: string;
  slot: EquipmentSlot;
  atk: number;
  def: number;
  hpBonus: number;
  hpRegen: number;
  description: string;
}

// ---- 技能 ----
export interface Skill {
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

// ---- 玩家 ----
export interface Player {
  x: number;
  y: number;
  vx: number;
  vy: number;
  width: number;
  height: number;
  hp: number;
  maxHp: number;
  level: number;
  xp: number;
  mp: number;
  maxMp: number;
  baseAtk: number;
  baseDef: number;
  attackCooldown: number;
  attackTimer: number;
  invincibleTimer: number;
  direction: Direction;
  animFrame: number;
  animTimer: number;
  attacking: boolean;
  onGround: boolean;
  // 装备
  weapon: Equipment | null;
  armor: Equipment | null;
  accessory: Equipment | null;
  // 背包
  inventory: Equipment[];
  // 技能
  skills: Skill[];
  skillCooldowns: Record<SkillId, number>;
  activeSkill: SkillId | null;
  activeSkillTimer: number;
  shieldTimer: number;
}

// ---- 怪物 ----
export interface Monster {
  id: number;
  kind: MonsterKind;
  size: MonsterSize;
  name: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  width: number;
  height: number;
  hp: number;
  maxHp: number;
  damage: number;
  def: number;
  xpReward: number;
  patrolLeft: number;
  patrolRight: number;
  direction: Direction;
  animFrame: number;
  animTimer: number;
  hitTimer: number;
  alive: boolean;
  bossPhase?: number;
  bossSpecialTimer?: number;
  isBoss: boolean;
}

// ---- NPC ----
export interface NPC {
  x: number;
  y: number;
  width: number;
  height: number;
  name: string;
  dialogues: string[];
  triggered: boolean;
  giftItem?: Equipment;
  healsPlayer?: boolean;
}

// ---- 传送门 ----
export interface Portal {
  x: number;
  y: number;
  width: number;
  height: number;
  targetMap: number;
  targetX: number;
  targetY: number;
  label: string;
}

// ---- 平台 ----
export interface Platform {
  x: number;
  y: number;
  w: number;
  h: number;
}

// ---- 地图 ----
export interface MapData {
  name: string;
  scene: SceneKind;
  width: number;
  height: number;
  bgColor: string;
  platforms: Platform[];
  monsters: Monster[];
  npcs: NPC[];
  portals: Portal[];
}

// ---- 粒子 ----
export interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  color: string;
  size: number;
}

// ---- 浮动文字 ----
export interface FloatingText {
  x: number;
  y: number;
  vy: number;
  life: number;
  text: string;
  color: string;
}

// ---- 全局游戏状态 ----
export interface GameState {
  phase: GamePhase;
  currentMap: number;
  player: Player;
  maps: MapData[];
  cameraX: number;
  keys: Set<string>;
  dialogueNPC: NPC | null;
  dialogueLine: number;
  transitionTimer: number;
  transitionTargetMap: number;
  particles: Particle[];
  floatingTexts: FloatingText[];
  shakeTimer: number;
  shakeIntensity: number;
  titleBlink: number;
  // 技能输入
  skillKeyJustPressed: SkillId | null;
  // 关卡通关记录
  clearedMaps: Set<number>;
  // 背包界面
  showInventory: boolean;
}
