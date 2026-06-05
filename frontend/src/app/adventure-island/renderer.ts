// ============================================================
// 冒险岛传奇 2.0 — 图片精灵渲染器
// ============================================================

import type {
  GameState,
  MapData,
  Player,
  Monster,
  NPC,
  Portal,
  Particle,
  FloatingText,
  Skill,
  Equipment,
} from "./types";
import { getImage, monsterAssetKey, sceneAssetKey } from "./assets";
import { GAME_W, GAME_H, SKILLS, ATTACK_COOLDOWN } from "./config";

// ============================================================
// 绘制辅助
// ============================================================

function drawBar(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  ratio: number,
  color: string,
  bgColor: string,
  borderColor = "#333",
): void {
  ctx.fillStyle = bgColor;
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w * Math.max(0, Math.min(1, ratio)), h);
  ctx.strokeStyle = borderColor;
  ctx.lineWidth = 1;
  ctx.strokeRect(x, y, w, h);
}

function drawCenteredText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  color: string,
  font: string,
): void {
  ctx.fillStyle = color;
  ctx.font = font;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y);
}

function displayAtk(player: Player): number {
  return player.baseAtk + (player.weapon?.atk ?? 0) + (player.accessory?.atk ?? 0);
}

function displayDef(player: Player): number {
  return player.baseDef + (player.armor?.def ?? 0) + (player.accessory?.def ?? 0);
}

// ============================================================
// 背景渲染（parallax）
// ============================================================

function renderBackground(
  ctx: CanvasRenderingContext2D,
  map: MapData,
  cameraX: number,
): void {
  const img = getImage(sceneAssetKey(map.scene));
  if (img) {
    // parallax: 背景移动速度 = 相机 30%
    const parallaxX = -(cameraX * 0.3);
    const scaleH = GAME_H / img.height;
    const scaledW = img.width * scaleH;
    // 平铺背景
    let x = parallaxX % scaledW;
    if (x > 0) x -= scaledW;
    while (x < GAME_W) {
      ctx.drawImage(img, x, 0, scaledW, GAME_H);
      x += scaledW;
    }
  } else {
    // 降级：纯色背景
    ctx.fillStyle = map.bgColor;
    ctx.fillRect(0, 0, GAME_W, GAME_H);
  }

  // 半透明暗色叠加增加景深感
  ctx.fillStyle = "rgba(0,0,0,0.15)";
  ctx.fillRect(0, 0, GAME_W, GAME_H);
}

// ============================================================
// 平台渲染
// ============================================================

function renderPlatforms(
  ctx: CanvasRenderingContext2D,
  map: MapData,
  cameraX: number,
): void {
  for (const pl of map.platforms) {
    const sx = pl.x - cameraX;
    const sy = pl.y;
    // 草地 / 土块效果
    const topGrad = ctx.createLinearGradient(sx, sy, sx, sy + 6);
    topGrad.addColorStop(0, "#5a9e4b");
    topGrad.addColorStop(1, "#3d6b33");
    ctx.fillStyle = topGrad;
    ctx.fillRect(sx, sy, pl.w, 6);

    ctx.fillStyle = "#8b6914";
    ctx.fillRect(sx, sy + 6, pl.w, pl.h - 6);

    // 纹理线
    ctx.strokeStyle = "#6b4f10";
    ctx.lineWidth = 1;
    ctx.strokeRect(sx, sy + 6, pl.w, pl.h - 6);

    // 左右边缘
    ctx.fillStyle = "#6b4f10";
    ctx.fillRect(sx, sy, 2, pl.h);
    ctx.fillRect(sx + pl.w - 2, sy, 2, pl.h);
  }
}

// ============================================================
// 传送门渲染
// ============================================================

function renderPortals(
  ctx: CanvasRenderingContext2D,
  portals: Portal[],
  cameraX: number,
): void {
  const t = Date.now() / 500;
  for (const p of portals) {
    const sx = p.x - cameraX + p.width / 2;
    const sy = p.y + p.height / 2;
    const r = 16 + Math.sin(t) * 3;

    // 外发光
    const grad = ctx.createRadialGradient(sx, sy, r * 0.3, sx, sy, r * 1.6);
    grad.addColorStop(0, "rgba(100,180,255,0.8)");
    grad.addColorStop(0.5, "rgba(50,120,220,0.4)");
    grad.addColorStop(1, "rgba(20,60,160,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(sx - r * 2, sy - r * 2, r * 4, r * 4);

    // 内圈
    ctx.fillStyle = "rgba(180,220,255,0.9)";
    ctx.beginPath();
    ctx.arc(sx, sy, r * 0.4, 0, Math.PI * 2);
    ctx.fill();

    // 标签
    ctx.fillStyle = "#fff";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText(p.label, sx, sy - r - 4);
  }
}

// ============================================================
// NPC 渲染
// ============================================================

function renderNPCs(
  ctx: CanvasRenderingContext2D,
  npcs: NPC[],
  cameraX: number,
): void {
  const img = getImage("npc");
  for (const npc of npcs) {
    const sx = npc.x - cameraX;
    const sy = npc.y;

    if (img) {
      ctx.drawImage(img, sx, sy, npc.width, npc.height);
    } else {
      // 降级绘制
      ctx.fillStyle = "#8b7355";
      ctx.fillRect(sx, sy, npc.width, npc.height);
      ctx.fillStyle = "#ffd39b";
      ctx.fillRect(sx + 4, sy + 4, npc.width - 8, npc.height / 2 - 4);
    }

    // NPC 名字
    ctx.fillStyle = "#ffd700";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText(npc.name, sx + npc.width / 2, sy - 4);

    // 未触发标记
    if (!npc.triggered) {
      const t = Date.now() / 300;
      const alpha = 0.5 + Math.sin(t) * 0.3;
      ctx.fillStyle = `rgba(255,255,100,${alpha})`;
      ctx.font = "14px sans-serif";
      ctx.fillText("!", sx + npc.width / 2, sy - 18);
    }
  }
}

// ============================================================
// 怪物渲染
// ============================================================

function renderMonsters(
  ctx: CanvasRenderingContext2D,
  monsters: Monster[],
  cameraX: number,
): void {
  for (const m of monsters) {
    if (!m.alive) continue;
    const sx = Math.round(m.x - cameraX);
    const sy = Math.round(m.y);

    // 受伤闪烁
    if (m.hitTimer > 0 && m.hitTimer % 4 < 2) {
      ctx.globalAlpha = 0.5;
    }

    const assetKey = monsterAssetKey(m.kind);
    const img = getImage(assetKey);

    if (img) {
      // 方向翻转（面向玩家方向）
      if (m.direction === "left") {
        ctx.save();
        ctx.translate(sx + m.width, sy);
        ctx.scale(-1, 1);
        ctx.drawImage(img, 0, 0, m.width, m.height);
        ctx.restore();
      } else {
        ctx.drawImage(img, sx, sy, m.width, m.height);
      }
    } else {
      // 降级手绘
      const colors: Record<string, string> = {
        slime: "#4caf50",
        mushroom: "#e53935",
        skeleton: "#bdbdbd",
        gargoyle: "#78909c",
        dark_knight: "#37474f",
        boss: "#6a1b9a",
      };
      ctx.fillStyle = colors[m.kind] || "#888";
      ctx.fillRect(sx, sy, m.width, m.height);
      // 眼睛
      ctx.fillStyle = "#fff";
      const eyeX = m.direction === "left" ? sx + 4 : sx + m.width - 8;
      ctx.fillRect(eyeX, sy + m.height * 0.25, 4, 4);
    }

    ctx.globalAlpha = 1;

    // Boss 标记
    if (m.isBoss) {
      const t = Date.now() / 200;
      const bs = 18 + Math.sin(t) * 4;
      ctx.fillStyle = "#ff1a1a";
      ctx.font = `${bs}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText("👑", sx + m.width / 2, sy - 2);
    }

    // 血条（Boss 或受伤时显示）
    const hpRatio = m.hp / m.maxHp;
    if (m.isBoss || hpRatio < 1) {
      const barW = m.isBoss ? 60 : m.width;
      const barH = m.isBoss ? 6 : 3;
      const barX = sx + m.width / 2 - barW / 2;
      const barY = sy - barH - 6;
      drawBar(ctx, barX, barY, barW, barH, hpRatio, "#e53935", "#333", "transparent");
    }

    // Boss 名字
    if (m.isBoss) {
      ctx.fillStyle = "#ff4444";
      ctx.font = "bold 12px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(m.name, sx + m.width / 2, sy - 14);
    }
  }
}

// ============================================================
// 玩家渲染
// ============================================================

function renderPlayer(
  ctx: CanvasRenderingContext2D,
  p: Player,
  cameraX: number,
): void {
  const sx = Math.round(p.x - cameraX);
  const sy = Math.round(p.y);

  // 无敌闪烁
  if (p.invincibleTimer > 0 && p.invincibleTimer % 6 < 3) {
    ctx.globalAlpha = 0.4;
  }

  // 护盾光环
  if (p.shieldTimer > 0) {
    const t = Date.now() / 150;
    ctx.strokeStyle = `rgba(255,255,150,${0.5 + Math.sin(t) * 0.3})`;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(sx + p.width / 2, sy + p.height / 2, p.width * 0.9 + Math.sin(t) * 3, 0, Math.PI * 2);
    ctx.stroke();
  }

  const img = getImage("player");
  if (img) {
    if (p.direction === "left") {
      ctx.save();
      ctx.translate(sx + p.width, sy);
      ctx.scale(-1, 1);
      ctx.drawImage(img, 0, 0, p.width, p.height);
      ctx.restore();
    } else {
      ctx.drawImage(img, sx, sy, p.width, p.height);
    }
  } else {
    // 降级手绘
    ctx.fillStyle = "#448aff";
    ctx.fillRect(sx, sy, p.width, p.height);
    ctx.fillStyle = "#ffcc80";
    ctx.fillRect(sx + 6, sy + 4, p.width - 12, p.height / 2 - 4);
  }

  ctx.globalAlpha = 1;

  // 攻击特效
  if (p.attackTimer > ATTACK_COOLDOWN - 4) {
    const atkX = p.direction === "right" ? sx + p.width - 2 : sx - 10;
    const atkY = sy + p.height * 0.3;
    ctx.strokeStyle = "#ffd700";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(atkX, atkY, 12, -0.5, 0.5);
    ctx.stroke();
  }

  // 主动技能特效
  if (p.activeSkill === "dash_slash" && p.activeSkillTimer > 0) {
    ctx.strokeStyle = "rgba(255,136,0,0.8)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx + p.width, sy + p.height);
    ctx.stroke();
  }
}

// ============================================================
// 粒子渲染
// ============================================================

function renderParticles(
  ctx: CanvasRenderingContext2D,
  particles: Particle[],
  cameraX: number,
): void {
  for (const pt of particles) {
    const alpha = pt.life / pt.maxLife;
    ctx.fillStyle = pt.color;
    ctx.globalAlpha = alpha;
    ctx.fillRect(pt.x - cameraX - pt.size / 2, pt.y - pt.size / 2, pt.size, pt.size);
  }
  ctx.globalAlpha = 1;
}

// ============================================================
// 浮动文字（伤害数字等）
// ============================================================

function renderFloatingTexts(
  ctx: CanvasRenderingContext2D,
  texts: FloatingText[],
  cameraX: number,
): void {
  for (const t of texts) {
    const alpha = t.life / 40;
    ctx.fillStyle = t.color;
    ctx.globalAlpha = alpha;
    ctx.font = "bold 14px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(t.text, t.x - cameraX, t.y);
  }
  ctx.globalAlpha = 1;
}

// ============================================================
// HUD — 状态栏
// ============================================================

function renderHUD(ctx: CanvasRenderingContext2D, p: Player): void {
  // ---- 左上：HP / MP / 等级 ----
  const hudX = 12;
  const hudY = 10;

  // HP 条
  drawBar(ctx, hudX, hudY, 200, 16, p.hp / p.maxHp, "#e53935", "#400");
  ctx.fillStyle = "#fff";
  ctx.font = "bold 11px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(`HP ${Math.ceil(p.hp)}/${p.maxHp}`, hudX + 6, hudY + 8);

  // MP 条
  drawBar(ctx, hudX, hudY + 20, 200, 10, p.mp / p.maxMp, "#2979ff", "#001a40");
  ctx.fillStyle = "#fff";
  ctx.font = "9px sans-serif";
  ctx.fillText(`MP ${Math.ceil(p.mp)}/${p.maxMp}`, hudX + 6, hudY + 25);

  // 等级徽章
  ctx.fillStyle = "#ffd700";
  ctx.font = "bold 18px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillText(`Lv.${p.level}`, hudX + 212, hudY);

  // ---- 底部：XP 条 ----
  const xpBarW = GAME_W - 60;
  const xpBarX = 30;
  const xpBarY = GAME_H - 22;
  const xpNeeded = xpForLevelImported(p.level);
  drawBar(ctx, xpBarX, xpBarY, xpBarW, 10, p.xp / xpNeeded, "#ffd700", "#332200", "#553300");
  ctx.fillStyle = "#fff";
  ctx.font = "8px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(`EXP ${p.xp}/${xpNeeded}`, GAME_W / 2, xpBarY + 5);

  // ---- 底部：技能热键栏 ----
  renderSkillBar(ctx, p);

  // ---- 右上：装备栏 ----
  renderEquipment(ctx, p);
}

/** 从 config 获取升级经验（避免循环依赖） */
function xpForLevelImported(level: number): number {
  // 使用简单公式，与 config.ts 的 xpForLevel 一致
  return level * level * 25 + 50;
}

function renderSkillBar(ctx: CanvasRenderingContext2D, p: Player): void {
  const unlockedSkills = SKILLS.filter((s) => p.level >= s.unlockLevel);
  if (unlockedSkills.length === 0) return;

  const slotW = 38;
  const slotH = 32;
  const gap = 5;
  const totalW = unlockedSkills.length * slotW + (unlockedSkills.length - 1) * gap;
  const startX = (GAME_W - totalW) / 2;
  const barY = GAME_H - 44;

  for (let i = 0; i < unlockedSkills.length; i++) {
    const sk = unlockedSkills[i];
    const sx = startX + i * (slotW + gap);
    const cd = p.skillCooldowns[sk.id] ?? 0;
    const cdRatio = sk.cooldownMax > 0 ? cd / sk.cooldownMax : 0;
    const isActive = p.activeSkill === sk.id && p.activeSkillTimer > 0;

    // 槽背景
    ctx.fillStyle = isActive ? "#553300" : "#1a1a2e";
    ctx.strokeStyle = "#ffd700";
    ctx.lineWidth = 1.5;
    ctx.fillRect(sx, barY, slotW, slotH);
    ctx.strokeRect(sx, barY, slotW, slotH);

    // 技能图标（文字 + 颜色）
    const iconColors: Record<string, string> = {
      whirlwind: "#4fc3f7",
      dash_slash: "#ff8a65",
      holy_shield: "#fff176",
      light_judgment: "#ce93d8",
    };
    ctx.fillStyle = iconColors[sk.id] || "#888";
    ctx.font = "16px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(sk.icon, sx + slotW / 2, barY + slotH / 2 - 3);

    // 技能名缩写
    ctx.fillStyle = "#ccc";
    ctx.font = "7px sans-serif";
    ctx.fillText(sk.name.slice(0, 4), sx + slotW / 2, barY + slotH - 6);

    // CD 覆盖
    if (cd > 0) {
      ctx.fillStyle = "rgba(0,0,0,0.6)";
      ctx.fillRect(sx, barY, slotW, slotH * cdRatio);
      ctx.fillStyle = "#fff";
      ctx.font = "bold 10px sans-serif";
      ctx.fillText(`${Math.ceil(cd / 60)}s`, sx + slotW / 2, barY + slotH / 2 + 8);
    }

    // 热键编号
    ctx.fillStyle = "#ffd700";
    ctx.font = "bold 9px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(`${i + 1}`, sx + 3, barY + 2);

    // MP 不足提示
    if (p.mp < sk.mpCost) {
      ctx.fillStyle = "rgba(255,0,0,0.3)";
      ctx.fillRect(sx, barY, slotW, slotH);
    }
  }
}

function renderEquipment(ctx: CanvasRenderingContext2D, p: Player): void {
  const slots: { slot: "weapon" | "armor" | "accessory"; equip: Equipment | null; label: string }[] = [
    { slot: "weapon", equip: p.weapon, label: "武器" },
    { slot: "armor", equip: p.armor, label: "护甲" },
    { slot: "accessory", equip: p.accessory, label: "饰品" },
  ];

  const startX = GAME_W - 120;
  const startY = 10;

  for (let i = 0; i < slots.length; i++) {
    const { equip, label } = slots[i];
    const ey = startY + i * 36;

    // 槽背景
    ctx.fillStyle = "#1a1a2e";
    ctx.strokeStyle = "#555";
    ctx.lineWidth = 1;
    ctx.fillRect(startX, ey, 108, 32);
    ctx.strokeRect(startX, ey, 108, 32);

    // 图标
    const icons: Record<string, string> = { weapon: "⚔️", armor: "🛡️", accessory: "💎" };
    ctx.font = "16px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(icons[slots[i].slot], startX + 6, ey + 16);

    // 装备名
    if (equip) {
      ctx.fillStyle = "#ffd700";
      ctx.font = "10px sans-serif";
      ctx.fillText(equip.name, startX + 28, ey + 10);
      // 属性
      const stats: string[] = [];
      if (equip.atk) stats.push(`攻+${equip.atk}`);
      if (equip.def) stats.push(`防+${equip.def}`);
      if (equip.hpBonus) stats.push(`HP+${equip.hpBonus}`);
      ctx.fillStyle = "#8f8";
      ctx.font = "8px sans-serif";
      ctx.fillText(stats.join(" "), startX + 28, ey + 24);
    } else {
      ctx.fillStyle = "#666";
      ctx.font = "10px sans-serif";
      ctx.fillText(`空${label}`, startX + 28, ey + 16);
    }
  }
}

// ============================================================
// 标题画面
// ============================================================

function renderTitle(ctx: CanvasRenderingContext2D, state: GameState): void {
  // 深色背景
  ctx.fillStyle = "#0a0a1a";
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  // 装饰星光
  const t = Date.now() / 1000;
  for (let i = 0; i < 40; i++) {
    const sx = ((i * 137 + 50) % GAME_W);
    const sy = ((i * 97 + 30) % GAME_H);
    const alpha = 0.3 + Math.sin(t + i) * 0.3;
    ctx.fillStyle = `rgba(255,255,200,${alpha})`;
    ctx.fillRect(sx, sy, 2, 2);
  }

  // 标题
  ctx.fillStyle = "#ffd700";
  ctx.font = "bold 48px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("冒险岛传奇", GAME_W / 2, GAME_H / 2 - 60);

  // 副标题
  ctx.fillStyle = "#ccc";
  ctx.font = "20px sans-serif";
  ctx.fillText("Adventure Island Saga", GAME_W / 2, GAME_H / 2 - 10);

  // 闪烁提示
  if (state.titleBlink < 50) {
    ctx.fillStyle = "#fff";
    ctx.font = "bold 18px sans-serif";
    ctx.fillText("按 Enter 开始冒险", GAME_W / 2, GAME_H / 2 + 50);
  }

  // 底部版本
  ctx.fillStyle = "#555";
  ctx.font = "12px sans-serif";
  ctx.fillText("v2.0 — 15关 · 技能 · 装备 · 等级", GAME_W / 2, GAME_H - 20);
}

// ============================================================
// 对话界面
// ============================================================

function renderDialogue(ctx: CanvasRenderingContext2D, state: GameState): void {
  const npc = state.dialogueNPC;
  if (!npc) return;

  const boxH = 120;
  const boxY = GAME_H - boxH - 10;

  // 半透明黑底
  ctx.fillStyle = "rgba(0,0,0,0.75)";
  ctx.fillRect(20, boxY, GAME_W - 40, boxH);

  // 边框
  ctx.strokeStyle = "#ffd700";
  ctx.lineWidth = 2;
  ctx.strokeRect(20, boxY, GAME_W - 40, boxH);

  // 名字
  ctx.fillStyle = "#ffd700";
  ctx.font = "bold 14px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillText(npc.name, 32, boxY + 8);

  // 对话内容
  const line = npc.dialogues[state.dialogueLine] || "";
  ctx.fillStyle = "#fff";
  ctx.font = "15px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  // 简单换行
  const words = line;
  const maxW = GAME_W - 80;
  ctx.fillText(words, 32, boxY + 32, maxW);

  // 继续提示
  const t = Date.now() / 400;
  if (Math.floor(t) % 2 === 0) {
    ctx.fillStyle = "#aaa";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "bottom";
    ctx.fillText("按 Space 继续 ▶", GAME_W - 32, boxY + boxH - 8);
  }
}

// ============================================================
// 通关/失败画面
// ============================================================

function renderVictory(ctx: CanvasRenderingContext2D, _state: GameState): void {
  ctx.fillStyle = "rgba(0,0,0,0.7)";
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  // 光芒
  const t = Date.now() / 800;
  for (let i = 0; i < 20; i++) {
    const angle = (i / 20) * Math.PI * 2 + t;
    const r = 120 + Math.sin(t * 2 + i) * 30;
    const lx = GAME_W / 2 + Math.cos(angle) * r;
    const ly = GAME_H / 2 - 30 + Math.sin(angle) * r;
    ctx.fillStyle = "rgba(255,215,0,0.4)";
    ctx.beginPath();
    ctx.arc(lx, ly, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  drawCenteredText(ctx, "🎉 魔王已被击败！🎉", GAME_W / 2, GAME_H / 2 - 30, "#ffd700", "bold 36px sans-serif");
  drawCenteredText(ctx, "世界恢复了和平，勇者成为传说。", GAME_W / 2, GAME_H / 2 + 15, "#fff", "18px sans-serif");
  drawCenteredText(ctx, "按 Enter 回到标题", GAME_W / 2, GAME_H / 2 + 55, "#aaa", "16px sans-serif");
}

function renderGameOver(ctx: CanvasRenderingContext2D, _state: GameState): void {
  ctx.fillStyle = "rgba(0,0,0,0.7)";
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  drawCenteredText(ctx, "💀 你倒下了...", GAME_W / 2, GAME_H / 2 - 20, "#e53935", "bold 36px sans-serif");
  drawCenteredText(ctx, "按 Enter 从失败中站起", GAME_W / 2, GAME_H / 2 + 25, "#aaa", "16px sans-serif");
}

// ============================================================
// 地图转换过渡
// ============================================================

function renderTransition(ctx: CanvasRenderingContext2D, state: GameState): void {
  const progress = 1 - state.transitionTimer / 40;
  ctx.fillStyle = `rgba(0,0,0,${progress})`;
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  // 地图名
  const nextMap = state.maps[state.transitionTargetMap];
  if (nextMap) {
    ctx.fillStyle = "#fff";
    ctx.font = "bold 22px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(nextMap.name, GAME_W / 2, GAME_H / 2);
  }
}

// ============================================================
// 主渲染入口
// ============================================================

export function renderGame(ctx: CanvasRenderingContext2D, state: GameState): void {
  ctx.clearRect(0, 0, GAME_W, GAME_H);

  // 特殊画面直接渲染
  if (state.phase === "title") {
    renderTitle(ctx, state);
    return;
  }
  if (state.phase === "victory") {
    renderVictory(ctx, state);
    return;
  }
  if (state.phase === "game_over") {
    renderGameOver(ctx, state);
    return;
  }

  // 游戏画面（含震屏）
  const map = state.maps[state.currentMap];
  if (!map) return;

  const shakeX = state.shakeTimer > 0 ? (Math.random() - 0.5) * state.shakeIntensity : 0;
  const shakeY = state.shakeTimer > 0 ? (Math.random() - 0.5) * state.shakeIntensity : 0;

  ctx.save();
  ctx.translate(shakeX, shakeY);

  renderBackground(ctx, map, state.cameraX);
  renderPlatforms(ctx, map, state.cameraX);
  renderPortals(ctx, map.portals, state.cameraX);
  renderNPCs(ctx, map.npcs, state.cameraX);
  renderMonsters(ctx, map.monsters, state.cameraX);
  renderPlayer(ctx, state.player, state.cameraX);
  renderParticles(ctx, state.particles, state.cameraX);
  renderFloatingTexts(ctx, state.floatingTexts, state.cameraX);

  ctx.restore();

  // HUD（不受相机和震屏影响）
  renderHUD(ctx, state.player);

  // 过渡层
  if (state.phase === "map_transition") {
    renderTransition(ctx, state);
  }

  // 对话层
  if (state.phase === "dialogue" && state.dialogueNPC) {
    renderDialogue(ctx, state);
  }

  // 按键提示（playing / dialogue 阶段始终显示）
  if (state.phase === "playing" || state.phase === "dialogue") {
    renderKeyHints(ctx);
  }

  // 背包 / 装备界面
  if (state.showInventory) {
    renderInventoryPanel(ctx, state);
  }
}

// ============================================================
// 按键提示栏
// ============================================================

function renderKeyHints(ctx: CanvasRenderingContext2D): void {
  const hints = [
    { key: "WASD/↑↓←→", desc: "移动" },
    { key: "J", desc: "攻击" },
    { key: "Space", desc: "跳跃" },
    { key: "Enter", desc: "对话" },
    { key: "1-4", desc: "技能" },
    { key: "Tab", desc: "背包" },
  ];

  const panelH = 28;
  const panelY = GAME_H - panelH;

  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(0, panelY, GAME_W, panelH);

  ctx.strokeStyle = "#333";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, panelY);
  ctx.lineTo(GAME_W, panelY);
  ctx.stroke();

  const spacing = GAME_W / hints.length;
  for (let i = 0; i < hints.length; i++) {
    const cx = spacing * i + spacing / 2;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    ctx.fillStyle = "#ffd700";
    ctx.font = "bold 9px monospace";
    ctx.fillText(hints[i].key, cx, panelY + 8);

    ctx.fillStyle = "#aaa";
    ctx.font = "8px sans-serif";
    ctx.fillText(hints[i].desc, cx, panelY + 20);
  }
}

// ============================================================
// 背包 / 装备面板
// ============================================================

function renderInventoryPanel(ctx: CanvasRenderingContext2D, state: GameState): void {
  const p = state.player;

  // 半透明遮罩
  ctx.fillStyle = "rgba(0,0,0,0.65)";
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  // 面板主框
  const panelW = 500;
  const panelH = 400;
  const panelX = (GAME_W - panelW) / 2;
  const panelY = (GAME_H - panelH) / 2;

  ctx.fillStyle = "#1a1a2e";
  ctx.strokeStyle = "#ffd700";
  ctx.lineWidth = 2;
  ctx.fillRect(panelX, panelY, panelW, panelH);
  ctx.strokeRect(panelX, panelY, panelW, panelH);

  // 标题
  ctx.fillStyle = "#ffd700";
  ctx.font = "bold 18px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("⚔️ 背包 / 装备", panelX + panelW / 2, panelY + 12);

  // 关闭提示
  ctx.fillStyle = "#888";
  ctx.font = "11px sans-serif";
  ctx.fillText("↑↓选择  Enter装备  Tab关闭", panelX + panelW / 2, panelY + panelH - 20);

  // ---- 左侧：背包列表 ----
  const leftX = panelX + 16;
  const leftY = panelY + 44;
  const leftW = 220;
  const listH = 280;

  ctx.fillStyle = "#22223a";
  ctx.fillRect(leftX, leftY, leftW, listH);
  ctx.strokeStyle = "#555";
  ctx.lineWidth = 1;
  ctx.strokeRect(leftX, leftY, leftW, listH);

  ctx.fillStyle = "#ccc";
  ctx.font = "bold 12px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillText("📦 背包", leftX, leftY - 4);

  if (p.inventory.length === 0) {
    ctx.fillStyle = "#555";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("（空）", leftX + leftW / 2, leftY + listH / 2);
  } else {
    const icons: Record<string, string> = { weapon: "⚔️", armor: "🛡️", accessory: "💎" };
    for (let i = 0; i < p.inventory.length && i < 7; i++) {
      const item = p.inventory[i];
      const iy = leftY + 8 + i * 40;

      ctx.fillStyle = i % 2 === 0 ? "#1e1e36" : "#282850";
      ctx.fillRect(leftX + 4, iy, leftW - 8, 36);

      // 选中高亮
      if (i === state.selectedInventoryIndex) {
        ctx.strokeStyle = "#ffd700";
        ctx.lineWidth = 2;
        ctx.strokeRect(leftX + 4, iy, leftW - 8, 36);
      }

      ctx.font = "14px sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(icons[item.slot] || "📦", leftX + 10, iy + 18);

      ctx.fillStyle = "#ffd700";
      ctx.font = "11px sans-serif";
      ctx.fillText(item.name, leftX + 30, iy + 12);

      const stats: string[] = [];
      if (item.atk) stats.push(`攻+${item.atk}`);
      if (item.def) stats.push(`防+${item.def}`);
      if (item.hpBonus) stats.push(`HP+${item.hpBonus}`);
      ctx.fillStyle = "#8f8";
      ctx.font = "9px sans-serif";
      ctx.fillText(stats.join(" "), leftX + 30, iy + 27);
    }
  }

  // ---- 右侧：装备槽 + 属性 ----
  const rightX = panelX + 260;
  const rightY = panelY + 44;

  // 装备槽
  const slots: { slot: "weapon" | "armor" | "accessory"; equip: Equipment | null; label: string }[] = [
    { slot: "weapon", equip: p.weapon, label: "武器" },
    { slot: "armor", equip: p.armor, label: "护甲" },
    { slot: "accessory", equip: p.accessory, label: "饰品" },
  ];

  ctx.fillStyle = "#ccc";
  ctx.font = "bold 12px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillText("🛡️ 装备栏", rightX, rightY - 4);

  const eqIcons: Record<string, string> = { weapon: "⚔️", armor: "🛡️", accessory: "💎" };
  for (let i = 0; i < slots.length; i++) {
    const { equip, label, slot } = slots[i];
    const ey = rightY + 8 + i * 48;

    ctx.fillStyle = equip ? "#1e2e1e" : "#222240";
    ctx.strokeStyle = equip ? "#ffd700" : "#555";
    ctx.lineWidth = 1;
    ctx.fillRect(rightX, ey, 220, 42);
    ctx.strokeRect(rightX, ey, 220, 42);

    ctx.fillStyle = "#888";
    ctx.font = "9px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(label, rightX + 6, ey + 4);

    if (equip) {
      ctx.font = "14px sans-serif";
      ctx.textBaseline = "middle";
      ctx.fillText(eqIcons[slot] || "", rightX + 6, ey + 28);

      ctx.fillStyle = "#ffd700";
      ctx.font = "bold 11px sans-serif";
      ctx.textBaseline = "middle";
      ctx.fillText(equip.name, rightX + 30, ey + 18);

      const stats: string[] = [];
      if (equip.atk) stats.push(`攻+${equip.atk}`);
      if (equip.def) stats.push(`防+${equip.def}`);
      if (equip.hpBonus) stats.push(`HP+${equip.hpBonus}`);
      ctx.fillStyle = "#8f8";
      ctx.font = "9px sans-serif";
      ctx.fillText(stats.join(" "), rightX + 30, ey + 34);
    } else {
      ctx.fillStyle = "#555";
      ctx.font = "10px sans-serif";
      ctx.textBaseline = "middle";
      ctx.fillText("空", rightX + 30, ey + 21);
    }
  }

  // 属性总览
  const statsY = rightY + 170;
  ctx.fillStyle = "#ccc";
  ctx.font = "bold 12px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillText("📊 属性总览", rightX, statsY - 4);

  ctx.fillStyle = "#ddd";
  ctx.font = "11px sans-serif";
  ctx.textBaseline = "top";
  const statLines = [
    `等级: ${p.level}    经验: ${p.xp}/${xpForLevelImported(p.level)}`,
    `攻击: ${displayAtk(p)}    防御: ${displayDef(p)}`,
    `HP: ${p.hp}/${p.maxHp}    MP: ${p.mp}/${p.maxMp}`,
  ];
  for (let i = 0; i < statLines.length; i++) {
    ctx.fillText(statLines[i], rightX, statsY + 8 + i * 18);
  }
}
