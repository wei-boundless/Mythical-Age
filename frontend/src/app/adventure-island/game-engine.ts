// ============================================================
// 冒险岛传奇 2.0 — 核心游戏引擎
// ============================================================

import type {
  GameState,
  Player,
  Monster,
  NPC,
  Particle,
  FloatingText,
  MapData,
  Equipment,
  SkillId,
} from "./types";
import {
  GAME_W,
  GAME_H,
  GRAVITY,
  PLAYER_SPEED,
  PLAYER_JUMP_VY,
  PLAYER_WIDTH,
  PLAYER_HEIGHT,
  PLAYER_INIT_HP,
  PLAYER_INIT_ATK,
  PLAYER_INIT_DEF,
  PLAYER_INIT_MP,
  ATTACK_COOLDOWN,
  ATTACK_DURATION,
  INVINCIBLE_DURATION,
  ATTACK_RANGE_X,
  ATTACK_RANGE_Y,
  xpForLevel,
  calcDamage,
  MP_REGEN_RATE,
  SKILLS,
  EQUIPMENT_DB,
} from "./config";
import { getBossDialogue, getMapMeta, getTrappedElfDialogue } from "./game-data";

// ============================================================
// 创建初始状态
// ============================================================
export function createInitialState(maps: MapData[]): GameState {
  const initialSkills = SKILLS.filter((s) => s.unlockLevel <= 1).map((s) => ({ ...s, cooldownMax: s.cooldownMax, duration: s.duration }));
  return {
    phase: "title",
    currentMap: 0,
    player: createPlayer(),
    maps,
    cameraX: 0,
    keys: new Set<string>(),
    dialogueNPC: null,
    dialogueLine: 0,
    transitionTimer: 0,
    transitionTargetMap: 0,
    particles: [],
    floatingTexts: [],
    shakeTimer: 0,
    shakeIntensity: 0,
    titleBlink: 0,
    skillKeyJustPressed: null,
    clearedMaps: new Set<number>(),
    showInventory: false,
    selectedInventoryIndex: 0,
  } as GameState;
}

function createSkillCooldowns(): Record<SkillId, number> {
  return Object.fromEntries(SKILLS.map((skill) => [skill.id, 0])) as Record<SkillId, number>;
}

function createPlayer(): Player {
  return {
    x: 100,
    y: 400,
    vx: 0,
    vy: 0,
    width: PLAYER_WIDTH,
    height: PLAYER_HEIGHT,
    hp: PLAYER_INIT_HP,
    maxHp: PLAYER_INIT_HP,
    level: 1,
    xp: 0,
    mp: PLAYER_INIT_MP,
    maxMp: PLAYER_INIT_MP,
    baseAtk: PLAYER_INIT_ATK,
    baseDef: PLAYER_INIT_DEF,
    attackCooldown: 0,
    attackTimer: 0,
    invincibleTimer: 0,
    direction: "right",
    animFrame: 0,
    animTimer: 0,
    attacking: false,
    onGround: false,
    weapon: null,
    armor: null,
    accessory: null,
    inventory: [],
    skills: [],
    skillCooldowns: createSkillCooldowns(),
    activeSkill: null,
    activeSkillTimer: 0,
    shieldTimer: 0,
  };
}

// ============================================================
// 碰撞检测工具
// ============================================================
function rectsOverlap(
  x1: number, y1: number, w1: number, h1: number,
  x2: number, y2: number, w2: number, h2: number,
): boolean {
  return x1 < x2 + w2 && x1 + w1 > x2 && y1 < y2 + h2 && y1 + h1 > y2;
}

// ============================================================
// 粒子系统
// ============================================================
function spawnParticles(
  particles: Particle[],
  x: number,
  y: number,
  count: number,
  color: string,
  force: number = 3,
): void {
  for (let i = 0; i < count; i++) {
    particles.push({
      x,
      y,
      vx: (Math.random() - 0.5) * force * 2,
      vy: (Math.random() - 0.5) * force * 2 - 2,
      life: 20 + Math.random() * 20,
      maxLife: 40,
      color,
      size: 2 + Math.random() * 4,
    });
  }
}

function updateParticles(particles: Particle[]): void {
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.vy += 0.1;
    p.life--;
    if (p.life <= 0) particles.splice(i, 1);
  }
}

// ============================================================
// 浮动文字
// ============================================================
function spawnFloatingText(
  texts: FloatingText[],
  x: number,
  y: number,
  text: string,
  color: string,
): void {
  texts.push({ x, y, vy: -3, life: 40, text, color });
}

function updateFloatingTexts(texts: FloatingText[]): void {
  for (let i = texts.length - 1; i >= 0; i--) {
    const t = texts[i];
    t.y += t.vy;
    t.life--;
    if (t.life <= 0) texts.splice(i, 1);
  }
}

// ============================================================
// 获取装备总属性
// ============================================================
function totalAtk(player: Player): number {
  return player.baseAtk + (player.weapon?.atk ?? 0) + (player.accessory?.atk ?? 0);
}

function totalDef(player: Player): number {
  return player.baseDef + (player.armor?.def ?? 0) + (player.accessory?.def ?? 0);
}

function totalHpBonus(player: Player): number {
  return (player.weapon?.hpBonus ?? 0) + (player.armor?.hpBonus ?? 0) + (player.accessory?.hpBonus ?? 0);
}

function hpRegen(player: Player): number {
  return (player.weapon?.hpRegen ?? 0) + (player.armor?.hpRegen ?? 0) + (player.accessory?.hpRegen ?? 0);
}

function recomputeMaxHp(player: Player): void {
  player.maxHp = PLAYER_INIT_HP + player.level * 10 + totalHpBonus(player);
}

function recomputeMaxMp(player: Player): void {
  player.maxMp = PLAYER_INIT_MP + player.level * 8;
}

// ============================================================
// 装备授予
// ============================================================
function giveEquipment(player: Player, equip: Equipment): void {
  // 放入背包
  player.inventory.push(equip);
  // 如果该槽位为空则自动装备
  if (equip.slot === "weapon" && !player.weapon) player.weapon = equip;
  else if (equip.slot === "armor" && !player.armor) player.armor = equip;
  else if (equip.slot === "accessory" && !player.accessory) player.accessory = equip;
  recomputeMaxHp(player);
  recomputeMaxMp(player);
}

// ============================================================
// 技能解锁
// ============================================================
function unlockSkills(player: Player): void {
  for (const sDef of SKILLS) {
    if (sDef.unlockLevel <= player.level && !player.skills.find((s) => s.id === sDef.id)) {
      player.skills.push({
        ...sDef,
        cooldownMax: sDef.cooldownMax,
        duration: sDef.duration,
      } as any);
      // 初始化冷却
      if (!(sDef.id in player.skillCooldowns)) {
        player.skillCooldowns[sDef.id] = 0;
      }
    }
  }
}

// ============================================================
// 经验与升级
// ============================================================
function addXp(state: GameState, xp: number): void {
  state.player.xp += xp;
  while (state.player.xp >= xpForLevel(state.player.level)) {
    state.player.xp -= xpForLevel(state.player.level);
    state.player.level++;
    state.player.baseAtk += 2;
    state.player.baseDef += 1;
    state.player.hp = Math.min(state.player.hp + 20, state.player.maxHp);
    state.player.mp = Math.min(state.player.mp + 15, state.player.maxMp);
    recomputeMaxHp(state.player);
    recomputeMaxMp(state.player);
    unlockSkills(state.player);
    state.floatingTexts.push({
      x: state.player.x + 16,
      y: state.player.y - 20,
      vy: -3,
      life: 60,
      text: `LEVEL UP! Lv${state.player.level}`,
      color: "#ffd700",
    });
  }
}

// ============================================================
// 玩家物理 & 移动
// ============================================================
function updatePlayerPhysics(player: Player, keys: Set<string>, map: MapData): void {
  // 水平移动
  if (keys.has("ArrowLeft") || keys.has("KeyA")) {
    player.vx = -PLAYER_SPEED;
    player.direction = "left";
  } else if (keys.has("ArrowRight") || keys.has("KeyD")) {
    player.vx = PLAYER_SPEED;
    player.direction = "right";
  } else {
    player.vx *= 0.6;
    if (Math.abs(player.vx) < 0.2) player.vx = 0;
  }

  // 跳跃
  if ((keys.has("ArrowUp") || keys.has("KeyW") || keys.has("Space")) && player.onGround) {
    player.vy = PLAYER_JUMP_VY;
    player.onGround = false;
  }

  // 重力
  player.vy += GRAVITY;
  if (player.vy > 15) player.vy = 15;

  // 水平碰撞
  player.x += player.vx;
  if (player.x < 0) player.x = 0;
  if (player.x > map.width - player.width) player.x = map.width - player.width;

  for (const plat of map.platforms) {
    if (
      rectsOverlap(player.x, player.y, player.width, player.height, plat.x, plat.y, plat.w, plat.h)
    ) {
      // 从上方或侧方挤压
      const overlapX =
        Math.min(player.x + player.width, plat.x + plat.w) -
        Math.max(player.x, plat.x);
      const overlapY =
        Math.min(player.y + player.height, plat.y + plat.h) -
        Math.max(player.y, plat.y);
      if (overlapX < overlapY) {
        if (player.x < plat.x + plat.w / 2) {
          player.x = plat.x - player.width;
        } else {
          player.x = plat.x + plat.w;
        }
        player.vx = 0;
      }
    }
  }

  // 垂直碰撞
  player.y += player.vy;
  player.onGround = false;

  if (player.y + player.height > map.height) {
    player.y = map.height - player.height;
    player.vy = 0;
    player.onGround = true;
  }

  for (const plat of map.platforms) {
    if (
      rectsOverlap(player.x, player.y, player.width, player.height, plat.x, plat.y, plat.w, plat.h)
    ) {
      // 下落时站在平台上
      if (player.vy >= 0) {
        player.y = plat.y - player.height;
        player.vy = 0;
        player.onGround = true;
      } else {
        // 上跳撞头
        player.y = plat.y + plat.h;
        player.vy = 0;
      }
    }
  }

  // 掉出地图
  if (player.y > map.height + 60) {
    player.y = 100;
    player.x = 80;
    player.vy = 0;
    player.hp -= 10;
    if (player.hp < 0) player.hp = 0;
  }
}

// ============================================================
// 怪物 AI
// ============================================================
function updateMonsterAI(monster: Monster, player: Player): void {
  if (!monster.alive) return;
  monster.hitTimer = Math.max(0, monster.hitTimer - 1);

  // Boss 专用
  if (monster.isBoss) {
    updateBossAI(monster, player);
    return;
  }

  const distToPlayer = Math.abs(monster.x + monster.width / 2 - (player.x + player.width / 2));
  const chaseRange = 200;

  if (distToPlayer < chaseRange) {
    // 追踪玩家
    if (player.x + player.width / 2 < monster.x + monster.width / 2) {
      monster.direction = "left";
      monster.vx = -1.5;
    } else {
      monster.direction = "right";
      monster.vx = 1.5;
    }
  } else {
    // 巡逻
    if (monster.x <= monster.patrolLeft) {
      monster.direction = "right";
      monster.vx = 1;
    } else if (monster.x >= monster.patrolRight) {
      monster.direction = "left";
      monster.vx = -1;
    }
  }

  // 重力
  monster.vy += GRAVITY;
  if (monster.vy > 10) monster.vy = 10;

  monster.x += monster.vx;
  monster.y += monster.vy;

  // 地面碰撞（简化）
  if (monster.y + monster.height > 520) {
    monster.y = 520 - monster.height;
    monster.vy = 0;
  }
}

function updateBossAI(boss: Monster, player: Player): void {
  // Boss 阶段系统
  const hpRatio = boss.hp / boss.maxHp;
  if (hpRatio > 0.66) boss.bossPhase = 1;
  else if (hpRatio > 0.33) boss.bossPhase = 2;
  else boss.bossPhase = 3;

  boss.bossSpecialTimer = (boss.bossSpecialTimer ?? 0) + 1;

  const centerBoss = boss.x + boss.width / 2;
  const centerPlayer = player.x + player.width / 2;

  // 追踪玩家
  if (centerBoss < centerPlayer) {
    boss.direction = "right";
    boss.vx = 0.8 + boss.bossPhase! * 0.4;
  } else {
    boss.direction = "left";
    boss.vx = -(0.8 + boss.bossPhase! * 0.4);
  }

  // 阶段3额外移动速度
  if (boss.bossPhase === 3) {
    boss.vx *= 1.3;
  }

  // 特殊攻击计时
  if ((boss.bossSpecialTimer ?? 0) > 120) {
    boss.bossSpecialTimer = 0;
  }

  boss.vy += GRAVITY;
  if (boss.vy > 10) boss.vy = 10;
  boss.x += boss.vx;
  boss.y += boss.vy;
  if (boss.y + boss.height > 520) {
    boss.y = 520 - boss.height;
    boss.vy = 0;
  }
}

// ============================================================
// 玩家攻击检测
// ============================================================
function playerAttack(state: GameState, map: MapData): void {
  const p = state.player;
  if (p.attackTimer <= 0) return;

  const attackX = p.direction === "right" ? p.x + p.width : p.x - ATTACK_RANGE_X;
  const attackY = p.y - 4;

  for (const m of map.monsters) {
    if (!m.alive) continue;
    if (
      rectsOverlap(
        attackX, attackY, ATTACK_RANGE_X, ATTACK_RANGE_Y,
        m.x, m.y, m.width, m.height,
      )
    ) {
      if (m.hitTimer > 0) continue;
      const dmg = calcDamage(totalAtk(p), 0, 0, m.def, totalDef(p));
      m.hp -= dmg;
      m.hitTimer = 15;
      spawnParticles(state.particles, m.x + m.width / 2, m.y + m.height / 2, 5, "#ff4444");
      state.floatingTexts.push({
        x: m.x + m.width / 2,
        y: m.y - 10,
        vy: -3,
        life: 25,
        text: `-${dmg}`,
        color: "#ff6666",
      });
      // 击退
      const knockback = p.direction === "right" ? 4 : -4;
      m.x += knockback;

      if (m.hp <= 0) {
        m.alive = false;
        spawnParticles(state.particles, m.x + m.width / 2, m.y + m.height / 2, 15, "#ffaa00");
        addXp(state, m.xpReward);
        state.floatingTexts.push({
          x: m.x + m.width / 2,
          y: m.y - 20,
          vy: -3,
          life: 40,
          text: `+${m.xpReward} XP`,
          color: "#ffd700",
        });
      }
    }
  }
}

// ============================================================
// 怪物攻击玩家
// ============================================================
function monsterAttackPlayer(player: Player, monster: Monster, state: GameState): void {
  if (!monster.alive || player.invincibleTimer > 0 || player.shieldTimer > 0) return;
  const hitX = player.x + player.width / 2;
  const hitY = player.y + player.height / 2;
  const mX = monster.x + monster.width / 2;
  const mY = monster.y + monster.height / 2;
  const dist = Math.sqrt((hitX - mX) ** 2 + (hitY - mY) ** 2);
  if (dist > 50) return;

  const dmg = Math.max(1, monster.damage - totalDef(player));
  player.hp -= dmg;
  player.invincibleTimer = INVINCIBLE_DURATION;
  spawnParticles(state.particles, hitX, hitY, 3, "#ffffff", 2);
  state.floatingTexts.push({
    x: hitX,
    y: player.y - 10,
    vy: -3,
    life: 30,
    text: `-${dmg}`,
    color: "#ff4444",
  });
}

// ============================================================
// NPC 交互
// ============================================================
function checkNPCInteraction(state: GameState, map: MapData): void {
  const p = state.player;
  if (!state.keys.has("KeyE") && !state.keys.has("Enter")) return;

  for (const npc of map.npcs) {
    if (npc.triggered) continue;
    const dist = Math.sqrt(
      (p.x + p.width / 2 - (npc.x + npc.width / 2)) ** 2 +
      (p.y + p.height / 2 - (npc.y + npc.height / 2)) ** 2,
    );
    if (dist < 60) {
      state.phase = "dialogue";
      state.dialogueNPC = npc;
      state.dialogueLine = 0;
      npc.triggered = true;
      if (npc.healsPlayer) {
        p.hp = p.maxHp;
        p.mp = p.maxMp;
      }
      return;
    }
  }
}

// ============================================================
// 传送门检测
// ============================================================
function checkPortal(state: GameState, map: MapData): void {
  const p = state.player;
  for (const portal of map.portals) {
    if (
      rectsOverlap(p.x, p.y, p.width, p.height, portal.x, portal.y, portal.width, portal.height)
    ) {
      state.transitionTimer = 40;
      state.transitionTargetMap = portal.targetMap;
      state.phase = "map_transition";
      // 预设位置
      p.x = portal.targetX;
      p.y = portal.targetY;
      return;
    }
  }
}

// ============================================================
// 通关检测（所有怪物死亡）
// ============================================================
function checkLevelClear(state: GameState, map: MapData): boolean {
  if (map.monsters.length === 0) return false; // 新手村不算
  return map.monsters.every((m) => !m.alive);
}

// ============================================================
// 技能释放
// ============================================================
function castSkill(state: GameState, skillId: SkillId, map: MapData): void {
  const p = state.player;
  if (p.skillCooldowns[skillId] > 0) return;
  const skillDef = SKILLS.find((s) => s.id === skillId);
  if (!skillDef) return;
  if (p.mp < skillDef.mpCost) return;

  p.mp -= skillDef.mpCost;
  p.skillCooldowns[skillId] = skillDef.cooldownMax;
  p.activeSkill = skillId;
  p.activeSkillTimer = skillDef.duration;

  if (skillId === "whirlwind") {
    // AOE 范围伤害
    const cx = p.x + p.width / 2;
    const cy = p.y + p.height / 2;
    for (const m of map.monsters) {
      if (!m.alive) continue;
      const dist = Math.sqrt((cx - (m.x + m.width / 2)) ** 2 + (cy - (m.y + m.height / 2)) ** 2);
      if (dist < 80) {
        const dmg = calcDamage(totalAtk(p), 0, skillDef.damage, m.def, totalDef(p));
        m.hp -= dmg;
        m.hitTimer = 10;
        spawnParticles(state.particles, m.x + m.width / 2, m.y + m.height / 2, 5, "#00ccff");
        state.floatingTexts.push({ x: m.x + m.width / 2, y: m.y - 10, vy: -3, life: 25, text: `-${dmg}`, color: "#00ccff" });
        if (m.hp <= 0) {
          m.alive = false;
          spawnParticles(state.particles, m.x + m.width / 2, m.y + m.height / 2, 15, "#ffaa00");
          addXp(state, m.xpReward);
        }
      }
    }
  } else if (skillId === "dash_slash") {
    p.vx = p.direction === "right" ? 10 : -10;
    p.vy = -4;
    // 伤害在 update 中检测接触
  } else if (skillId === "holy_shield") {
    p.shieldTimer = skillDef.duration;
    spawnParticles(state.particles, p.x + p.width / 2, p.y + p.height / 2, 20, "#ffff88", 1.5);
  } else if (skillId === "light_judgment") {
    // 全屏打击
    for (const m of map.monsters) {
      if (!m.alive) continue;
      const dmg = calcDamage(totalAtk(p), 0, skillDef.damage, m.def, totalDef(p));
      m.hp -= dmg;
      m.hitTimer = 10;
      spawnParticles(state.particles, m.x + m.width / 2, m.y + m.height / 2, 8, "#ffffff");
      state.floatingTexts.push({ x: m.x + m.width / 2, y: m.y - 10, vy: -3, life: 30, text: `-${dmg}`, color: "#ffd700" });
      if (m.hp <= 0) {
        m.alive = false;
        spawnParticles(state.particles, m.x + m.width / 2, m.y + m.height / 2, 15, "#ffaa00");
        addXp(state, m.xpReward);
      }
    }
    state.shakeTimer = 20;
    state.shakeIntensity = 8;
    spawnParticles(state.particles, p.x + p.width / 2, p.y + p.height / 2, 30, "#ffffff", 4);
  }
}

// ============================================================
// 主动技能持续伤害（dash_slash 等）
// ============================================================
function activeSkillDamage(state: GameState, map: MapData): void {
  const p = state.player;
  if (!p.activeSkill || p.activeSkillTimer <= 0) return;
  const skillDef = SKILLS.find((s) => s.id === p.activeSkill);
  if (!skillDef || skillDef.damage <= 0) return;

  for (const m of map.monsters) {
    if (!m.alive || m.hitTimer > 0) continue;
    if (
      rectsOverlap(p.x, p.y, p.width, p.height, m.x, m.y, m.width, m.height)
    ) {
      const dmg = calcDamage(totalAtk(p), 0, skillDef.damage, m.def, totalDef(p));
      m.hp -= dmg;
      m.hitTimer = 10;
      spawnParticles(state.particles, m.x + m.width / 2, m.y + m.height / 2, 5, "#ff8800");
      state.floatingTexts.push({ x: m.x + m.width / 2, y: m.y - 10, vy: -3, life: 25, text: `-${dmg}`, color: "#ff8800" });
      if (m.hp <= 0) {
        m.alive = false;
        spawnParticles(state.particles, m.x + m.width / 2, m.y + m.height / 2, 15, "#ffaa00");
        addXp(state, m.xpReward);
      }
    }
  }
}

// ============================================================
// 主更新循环
// ============================================================
export function updateGame(state: GameState): void {
  // 标题画面
  if (state.phase === "title") {
    state.titleBlink = (state.titleBlink + 1) % 80;
    if (state.keys.has("Enter") || state.keys.has("Space") || state.keys.has("KeyE")) {
      state.keys.delete("Enter");
      state.keys.delete("Space");
      state.keys.delete("KeyE");
      // 标题画面触发开局 → 去第0关（新手村）
      state.transitionTimer = 40;
      state.transitionTargetMap = 0;
      state.phase = "map_transition";
    }
    return;
  }

  // 地图过渡
  if (state.phase === "map_transition") {
    state.transitionTimer--;
    if (state.transitionTimer <= 0) {
      state.phase = "playing";
      state.currentMap = state.transitionTargetMap;
      state.player.x = 80;
      state.player.y = 300;
      state.player.vy = 0;
      state.particles = [];
      state.floatingTexts = [];

      // 关卡切换恢复：30% HP + 20% MP
      const p = state.player;
      const hpHeal = Math.floor(p.maxHp * 0.3);
      const mpHeal = Math.floor(p.maxMp * 0.2);
      p.hp = Math.min(p.maxHp, p.hp + hpHeal);
      p.mp = Math.min(p.maxMp, p.mp + mpHeal);
      if (hpHeal > 0) {
        state.floatingTexts.push({ x: p.x + p.width / 2, y: p.y - 20, vy: -2, life: 40, text: `+${hpHeal} HP`, color: "#00ff66" });
      }
      if (mpHeal > 0) {
        state.floatingTexts.push({ x: p.x + p.width / 2, y: p.y - 30, vy: -2, life: 40, text: `+${mpHeal} MP`, color: "#6699ff" });
      }

      // Boss 关检查：进入时触发开场对话
      const bossDialogue = getBossDialogue(state.transitionTargetMap, false);
      if (bossDialogue) {
        state.phase = "dialogue";
        state.dialogueNPC = {
          x: 0, y: 0, width: 0, height: 0,
          name: "剧情",
          dialogues: bossDialogue,
          triggered: false,
        };
        state.dialogueLine = 0;
      }
    }
    return;
  }

  // 对话
  if (state.phase === "dialogue") {
    if (state.keys.has("Enter") || state.keys.has("Space") || state.keys.has("KeyE")) {
      state.keys.delete("Enter");
      state.keys.delete("Space");
      state.keys.delete("KeyE");
      if (state.dialogueNPC) {
        state.dialogueLine++;
        if (state.dialogueLine >= state.dialogueNPC.dialogues.length) {
          // 对话结束
          if (state.dialogueNPC.giftItems) {
            for (const item of state.dialogueNPC.giftItems) {
              giveEquipment(state.player, item);
            }
          }
          state.dialogueNPC = null;
          state.dialogueLine = 0;
          state.phase = "playing";
        }
      } else {
        state.phase = "playing";
      }
    }
    return;
  }

  // 游戏结束/胜利
  if (state.phase === "game_over" || state.phase === "victory") {
    state.titleBlink = (state.titleBlink + 1) % 80;
    if (state.keys.has("Enter") || state.keys.has("Space")) {
      state.keys.delete("Enter");
      state.keys.delete("Space");
      // 重新开始
      const newState = createInitialState(state.maps);
      Object.assign(state, newState);
      state.phase = "title";
      state.currentMap = 0;
    }
    return;
  }

  // ========== playing 状态 ==========
  const map = state.maps[state.currentMap];
  if (!map) return;

  // MP 回复
  state.player.mp = Math.min(state.player.maxMp, state.player.mp + MP_REGEN_RATE);

  // HP 回复（贤者之石等）
  const regen = hpRegen(state.player);
  if (regen > 0 && state.player.hp > 0 && state.player.hp < state.player.maxHp) {
    state.player.hp = Math.min(state.player.maxHp, state.player.hp + regen / 60);
  }

  // 计时器衰减
  const p = state.player;
  p.attackCooldown = Math.max(0, p.attackCooldown - 1);
  p.attackTimer = Math.max(0, p.attackTimer - 1);
  p.invincibleTimer = Math.max(0, p.invincibleTimer - 1);
  p.activeSkillTimer = Math.max(0, p.activeSkillTimer - 1);
  if (p.activeSkillTimer <= 0) p.activeSkill = null;
  p.shieldTimer = Math.max(0, p.shieldTimer - 1);
  for (const key of Object.keys(p.skillCooldowns) as SkillId[]) {
    p.skillCooldowns[key] = Math.max(0, p.skillCooldowns[key] - 1);
  }
  state.shakeTimer = Math.max(0, state.shakeTimer - 1);

  // 背包界面切换与操作
  if (state.keys.has("Tab")) {
    state.keys.delete("Tab");
    state.showInventory = !state.showInventory;
    if (state.showInventory) state.selectedInventoryIndex = 0;
  }
  if (state.showInventory) {
    // 上下导航
    if (state.keys.has("ArrowUp") || state.keys.has("KeyW")) {
      state.keys.delete("ArrowUp");
      state.keys.delete("KeyW");
      state.selectedInventoryIndex = Math.max(0, state.selectedInventoryIndex - 1);
    }
    if (state.keys.has("ArrowDown") || state.keys.has("KeyS")) {
      state.keys.delete("ArrowDown");
      state.keys.delete("KeyS");
      state.selectedInventoryIndex = Math.min(state.player.inventory.length - 1, state.selectedInventoryIndex + 1);
    }
    // 装备选中物品
    if (state.keys.has("Enter")) {
      state.keys.delete("Enter");
      const inv = state.player.inventory;
      if (inv.length > 0 && state.selectedInventoryIndex < inv.length) {
        const item = inv[state.selectedInventoryIndex];
        const slot = item.slot as "weapon" | "armor" | "accessory";
        const old = state.player[slot];
        state.player[slot] = item;
        inv.splice(state.selectedInventoryIndex, 1);
        if (old) inv.push(old);
        state.selectedInventoryIndex = Math.min(state.selectedInventoryIndex, inv.length - 1);
      }
    }
    return;
  }

  // 攻击输入
  if (state.keys.has("KeyJ") && p.attackCooldown <= 0 && !p.attacking) {
    p.attacking = true;
    p.attackCooldown = ATTACK_COOLDOWN;
    p.attackTimer = ATTACK_DURATION;
  }
  if (!state.keys.has("KeyJ")) {
    p.attacking = false;
  }

  // 技能输入（通过 skillKeyJustPressed 一次性触发，page.tsx 会设置并自动清除）
  if (state.skillKeyJustPressed === "whirlwind")  { castSkill(state, "whirlwind", map);  state.skillKeyJustPressed = null; }
  if (state.skillKeyJustPressed === "dash_slash")  { castSkill(state, "dash_slash", map);  state.skillKeyJustPressed = null; }
  if (state.skillKeyJustPressed === "holy_shield") { castSkill(state, "holy_shield", map); state.skillKeyJustPressed = null; }
  if (state.skillKeyJustPressed === "light_judgment") { castSkill(state, "light_judgment", map); state.skillKeyJustPressed = null; }

  // 动画计时
  p.animTimer++;
  if (p.animTimer > 8) {
    p.animTimer = 0;
    p.animFrame = (p.animFrame + 1) % 4;
  }

  // 更新物理
  updatePlayerPhysics(p, state.keys, map);

  // 玩家攻击
  playerAttack(state, map);

  // 更新怪物
  for (const m of map.monsters) {
    if (!m.alive) continue;
    updateMonsterAI(m, p);
    m.animTimer++;
    if (m.animTimer > 10) {
      m.animTimer = 0;
      m.animFrame = (m.animFrame + 1) % 4;
    }
    monsterAttackPlayer(p, m, state);
  }

  // 主动技能伤害
  activeSkillDamage(state, map);

  // NPC 交互
  checkNPCInteraction(state, map);

  // 传送门
  checkPortal(state, map);

  // 玩家死亡
  if (p.hp <= 0) {
    state.phase = "game_over";
  }

  // 通关检测
  if (checkLevelClear(state, map)) {
    state.clearedMaps.add(state.currentMap);
    const meta = getMapMeta(state.currentMap);
    if (meta.giftOnClear) {
      const equip = EQUIPMENT_DB[meta.giftOnClear];
      if (equip) giveEquipment(p, equip);
    }
    // Boss 关：触发战后对话
    const bossPost = getBossDialogue(state.currentMap, true);
    if (bossPost) {
      state.phase = "dialogue";
      state.dialogueNPC = {
        x: 0, y: 0, width: 0, height: 0,
        name: "剧情",
        dialogues: bossPost,
        triggered: false,
      };
      state.dialogueLine = 0;
      // 检查是否是最终Boss关
      if (state.currentMap === 15) {
        // 最终对话结束后胜利
        const origLen = bossPost.length;
        const checkVictory = (): void => {
          if (state.dialogueLine >= origLen) {
            state.phase = "victory";
          } else {
            requestAnimationFrame(checkVictory);
          }
        };
        // 延迟检查
        setTimeout(checkVictory, 500);
      }
    }
  }

  // 镜头跟随
  state.cameraX = Math.max(
    0,
    Math.min(
      p.x - GAME_W / 2 + p.width / 2,
      Math.max(0, map.width - GAME_W),
    ),
  );

  // 粒子更新
  updateParticles(state.particles);
  updateFloatingTexts(state.floatingTexts);
}
