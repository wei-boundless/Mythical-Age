"use client";

import { useEffect, useRef, useCallback, useState } from "react";

// ============================================================
// 冒险岛 Canvas 小游戏 — 类型定义
// ============================================================

interface Vec2 {
  x: number;
  y: number;
}

type Direction = "left" | "right";
type GamePhase = "title" | "playing" | "dialogue" | "map_transition" | "victory" | "game_over";

interface Player {
  x: number;
  y: number;
  vx: number;
  vy: number;
  width: number;
  height: number;
  hp: number;
  maxHp: number;
  attackCooldown: number;
  invincibleTimer: number;
  direction: Direction;
  animFrame: number;
  animTimer: number;
  attacking: boolean;
  attackTimer: number;
  onGround: boolean;
}

interface Monster {
  id: number;
  type: "slime" | "mushroom" | "skeleton" | "gargoyle" | "dark_knight" | "boss";
  x: number;
  y: number;
  vx: number;
  vy: number;
  width: number;
  height: number;
  hp: number;
  maxHp: number;
  damage: number;
  patrolLeft: number;
  patrolRight: number;
  direction: Direction;
  animFrame: number;
  animTimer: number;
  hitTimer: number;
  alive: boolean;
  bossPhase?: number;
  bossSpecialTimer?: number;
}

interface NPC {
  x: number;
  y: number;
  width: number;
  height: number;
  name: string;
  dialogues: string[];
  dialogueIndex: number;
  triggered: boolean;
}

interface Portal {
  x: number;
  y: number;
  width: number;
  height: number;
  targetMap: number;
  targetX: number;
  targetY: number;
  label: string;
}

interface MapData {
  name: string;
  width: number;
  height: number;
  bgColor: string;
  platforms: { x: number; y: number; w: number; h: number }[];
  monsters: Monster[];
  npcs: NPC[];
  portals: Portal[];
  drawBackground: (ctx: CanvasRenderingContext2D, camX: number) => void;
}

interface GameState {
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
  shakeTimer: number;
  shakeIntensity: number;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  color: string;
  size: number;
}

// ============================================================
// 常量
// ============================================================

const GAME_W = 960;
const GAME_H = 540;
const GRAVITY = 0.6;
const PLAYER_SPEED = 4;
const PLAYER_JUMP = -11;
const ATTACK_COOLDOWN = 25;
const ATTACK_DURATION = 12;
const INVINCIBLE_DURATION = 60;
const CAMERA_SMOOTH = 0.08;

// ============================================================
// 精灵绘制函数 — 主角（帅气小伙子）
// ============================================================

function drawPlayer(ctx: CanvasRenderingContext2D, p: Player) {
  ctx.save();
  const cx = p.x + p.width / 2;
  const cy = p.y + p.height / 2;
  ctx.translate(cx, cy);
  if (p.direction === "left") ctx.scale(-1, 1);

  const bob = p.attacking ? 0 : Math.sin(p.animTimer * 0.15) * 1.5;
  const hurtFlash = p.invincibleTimer > 0 && Math.floor(p.invincibleTimer / 4) % 2 === 0;

  // 腿
  const legSwing = p.attacking ? 0 : Math.sin(p.animTimer * 0.2) * 8;
  ctx.fillStyle = hurtFlash ? "#ff8888" : "#5a3825";
  ctx.fillRect(-6, 10 + bob, 5, 12 + legSwing * 0.5);
  ctx.fillRect(1, 10 + bob, 5, 12 - legSwing * 0.5);

  // 身体
  ctx.fillStyle = hurtFlash ? "#ffaaaa" : "#4a90d9";
  ctx.fillRect(-8, -2 + bob, 16, 14);

  // 腰带
  ctx.fillStyle = "#8b6914";
  ctx.fillRect(-8, 10 + bob, 16, 3);

  // 头
  ctx.fillStyle = hurtFlash ? "#ffccaa" : "#fdbcb4";
  ctx.beginPath();
  ctx.arc(0, -10 + bob, 8, 0, Math.PI * 2);
  ctx.fill();

  // 头发（刺猬头）
  ctx.fillStyle = "#5c3317";
  ctx.fillRect(-7, -20 + bob, 3, 8);
  ctx.fillRect(-3, -21 + bob, 3, 7);
  ctx.fillRect(1, -19 + bob, 4, 9);
  ctx.fillRect(4, -20 + bob, 3, 6);
  ctx.fillRect(-9, -18 + bob, 3, 4);

  // 眼睛
  ctx.fillStyle = "#fff";
  ctx.fillRect(2, -12 + bob, 4, 4);
  ctx.fillStyle = "#333";
  ctx.fillRect(4, -11 + bob, 2, 2);

  // 剑
  if (p.attacking) {
    ctx.save();
    ctx.rotate(-0.4 + p.attackTimer * 0.08);
    ctx.fillStyle = "#ddd";
    ctx.fillRect(8, -5 + bob, 20, 3);
    ctx.fillStyle = "#ffd700";
    ctx.fillRect(6, -6 + bob, 3, 5);
    ctx.fillStyle = "#888";
    ctx.fillRect(6, -5 + bob, 4, 3);
    ctx.restore();
  } else {
    // 背上的剑鞘
    ctx.fillStyle = "#8b4513";
    ctx.fillRect(-9, -6 + bob, 2, 16);
    ctx.fillStyle = "#ffd700";
    ctx.fillRect(-10, -6 + bob, 4, 3);
  }

  ctx.restore();
}

// ============================================================
// 怪物绘制函数
// ============================================================

function drawSlime(ctx: CanvasRenderingContext2D, m: Monster) {
  ctx.save();
  const cx = m.x + m.width / 2;
  const cy = m.y + m.height / 2;
  const squish = 1 + Math.sin(m.animTimer * 0.08) * 0.15;
  const hitColor = m.hitTimer > 0 ? "#fff" : "";

  ctx.fillStyle = hitColor || "#4caf50";
  ctx.beginPath();
  ctx.ellipse(cx, cy + 4, 14 * squish, 12, 0, 0, Math.PI * 2);
  ctx.fill();

  // 高光
  ctx.fillStyle = hitColor ? "#fff" : "#81c784";
  ctx.beginPath();
  ctx.ellipse(cx - 4, cy - 3, 5, 3, -0.3, 0, Math.PI * 2);
  ctx.fill();

  // 眼睛
  ctx.fillStyle = "#fff";
  ctx.beginPath();
  ctx.arc(cx + 4, cy - 2, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.arc(cx - 5, cy - 2, 5, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = "#333";
  ctx.beginPath();
  ctx.arc(cx + 5, cy - 1, 2.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.arc(cx - 4, cy - 1, 2.5, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

function drawMushroom(ctx: CanvasRenderingContext2D, m: Monster) {
  ctx.save();
  const cx = m.x + m.width / 2;
  const cy = m.y + m.height / 2;
  const hitColor = m.hitTimer > 0;

  // 菌柄
  ctx.fillStyle = hitColor ? "#ffe0e0" : "#e8d5b7";
  ctx.fillRect(cx - 5, cy + 2, 10, 14);

  // 菌盖
  ctx.fillStyle = hitColor ? "#ff6666" : "#d32f2f";
  ctx.beginPath();
  ctx.arc(cx, cy - 2, 16, Math.PI, 0);
  ctx.fill();
  ctx.fillRect(cx - 16, cy - 2, 32, 4);

  // 白色斑点
  ctx.fillStyle = "#fff";
  ctx.beginPath();
  ctx.arc(cx - 7, cy - 6, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(cx + 6, cy - 5, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(cx + 2, cy - 10, 3.5, 0, Math.PI * 2);
  ctx.fill();

  // 眼睛（凶恶）
  ctx.fillStyle = "#fff";
  ctx.fillRect(cx - 8, cy - 4, 5, 5);
  ctx.fillRect(cx + 3, cy - 4, 5, 5);
  ctx.fillStyle = "#d32f2f";
  ctx.fillRect(cx - 6, cy - 3, 2, 2);
  ctx.fillRect(cx + 5, cy - 3, 2, 2);

  ctx.restore();
}

function drawSkeleton(ctx: CanvasRenderingContext2D, m: Monster) {
  ctx.save();
  const cx = m.x + m.width / 2;
  const cy = m.y + m.height / 2;
  const hitColor = m.hitTimer > 0;
  const bob = Math.sin(m.animTimer * 0.1) * 2;

  // 身体骨架
  ctx.fillStyle = hitColor ? "#fff" : "#e0d8c8";
  // 肋骨
  ctx.fillRect(cx - 7, cy - 8 + bob, 14, 12);
  ctx.strokeStyle = hitColor ? "#ccc" : "#b8a88a";
  ctx.lineWidth = 1;
  for (let i = 0; i < 3; i++) {
    ctx.strokeRect(cx - 5, cy - 6 + bob + i * 4, 10, 1);
  }

  // 头骨
  ctx.fillStyle = hitColor ? "#fff" : "#f0e8d8";
  ctx.beginPath();
  ctx.arc(cx, cy - 14 + bob, 9, 0, Math.PI * 2);
  ctx.fill();

  // 眼睛（红光）
  ctx.fillStyle = "#ff2222";
  ctx.beginPath();
  ctx.arc(cx - 3, cy - 15 + bob, 2.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.arc(cx + 3, cy - 15 + bob, 2.5, 0, Math.PI * 2);
  ctx.fill();

  // 手臂
  const armSwing = Math.sin(m.animTimer * 0.12) * 6;
  ctx.fillStyle = hitColor ? "#fff" : "#e0d8c8";
  ctx.fillRect(cx - 8, cy - 4 + bob, 3, 14 + armSwing);
  ctx.fillRect(cx + 5, cy - 4 + bob, 3, 14 - armSwing);

  // 腿
  ctx.fillRect(cx - 5, cy + 6 + bob, 4, 12);
  ctx.fillRect(cx + 1, cy + 6 + bob, 4, 12);

  // 生锈的盾牌
  ctx.fillStyle = hitColor ? "#ccc" : "#8b7355";
  ctx.fillRect(cx - 10, cy - 3 + bob, 5, 10);
  ctx.fillStyle = hitColor ? "#ddd" : "#a08060";
  ctx.beginPath();
  ctx.arc(cx - 7, cy + 2 + bob, 3, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

function drawGargoyle(ctx: CanvasRenderingContext2D, m: Monster) {
  ctx.save();
  const cx = m.x + m.width / 2;
  const cy = m.y + m.height / 2;
  const hitColor = m.hitTimer > 0;
  const flap = Math.sin(m.animTimer * 0.18) * 5;

  // 翅膀
  ctx.fillStyle = hitColor ? "#aaa" : "#5d6d7e";
  ctx.beginPath();
  ctx.moveTo(cx - 4, cy - 5);
  ctx.lineTo(cx - 20, cy - 12 + flap);
  ctx.lineTo(cx - 8, cy + 2);
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(cx + 4, cy - 5);
  ctx.lineTo(cx + 20, cy - 12 - flap);
  ctx.lineTo(cx + 8, cy + 2);
  ctx.closePath();
  ctx.fill();

  // 身体
  ctx.fillStyle = hitColor ? "#999" : "#6c7a89";
  ctx.fillRect(cx - 6, cy - 4, 12, 16);

  // 头
  ctx.fillStyle = hitColor ? "#aaa" : "#7d8a96";
  ctx.beginPath();
  ctx.arc(cx, cy - 9, 8, 0, Math.PI * 2);
  ctx.fill();

  // 角
  ctx.fillStyle = hitColor ? "#888" : "#444";
  ctx.beginPath();
  ctx.moveTo(cx - 4, cy - 15);
  ctx.lineTo(cx - 8, cy - 24);
  ctx.lineTo(cx - 1, cy - 14);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(cx + 4, cy - 15);
  ctx.lineTo(cx + 8, cy - 24);
  ctx.lineTo(cx + 1, cy - 14);
  ctx.fill();

  // 眼睛
  ctx.fillStyle = "#ff0";
  ctx.fillRect(cx - 5, cy - 12, 3, 3);
  ctx.fillRect(cx + 2, cy - 12, 3, 3);

  // 爪子
  ctx.fillStyle = hitColor ? "#999" : "#555";
  ctx.fillRect(cx - 7, cy + 8, 4, 4);
  ctx.fillRect(cx + 3, cy + 8, 4, 4);

  ctx.restore();
}

function drawDarkKnight(ctx: CanvasRenderingContext2D, m: Monster) {
  ctx.save();
  const cx = m.x + m.width / 2;
  const cy = m.y + m.height / 2;
  const hitColor = m.hitTimer > 0;

  // 披风
  ctx.fillStyle = hitColor ? "#555" : "#2c003e";
  ctx.beginPath();
  ctx.moveTo(cx - 10, cy - 4);
  ctx.lineTo(cx - 14, cy + 16);
  ctx.lineTo(cx - 4, cy + 10);
  ctx.closePath();
  ctx.fill();

  // 身体（黑甲）
  ctx.fillStyle = hitColor ? "#666" : "#1a1a2e";
  ctx.fillRect(cx - 9, cy - 8, 18, 20);

  // 胸甲纹饰
  ctx.fillStyle = hitColor ? "#999" : "#6a0dad";
  ctx.fillRect(cx - 3, cy - 4, 6, 8);

  // 头盔
  ctx.fillStyle = hitColor ? "#777" : "#222";
  ctx.beginPath();
  ctx.arc(cx, cy - 14, 10, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillRect(cx - 10, cy - 14, 20, 6);

  // 头盔角
  ctx.fillStyle = hitColor ? "#888" : "#444";
  ctx.fillRect(cx - 4, cy - 26, 3, 10);
  ctx.fillRect(cx + 1, cy - 26, 3, 10);

  // 暗光眼
  ctx.fillStyle = "#ff4444";
  ctx.beginPath();
  ctx.arc(cx - 3, cy - 14, 2.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.arc(cx + 3, cy - 14, 2.5, 0, Math.PI * 2);
  ctx.fill();

  // 剑
  ctx.fillStyle = hitColor ? "#aaa" : "#6a0dad";
  ctx.fillRect(cx + 8, cy - 6, 3, 20);
  ctx.fillStyle = hitColor ? "#ccc" : "#999";
  ctx.fillRect(cx + 9, cy - 8, 1, 4);

  // 腿
  ctx.fillStyle = hitColor ? "#555" : "#1a1a2e";
  ctx.fillRect(cx - 7, cy + 10, 5, 10);
  ctx.fillRect(cx + 2, cy + 10, 5, 10);

  ctx.restore();
}

function drawBoss(ctx: CanvasRenderingContext2D, m: Monster) {
  ctx.save();
  const cx = m.x + m.width / 2;
  const cy = m.y + m.height / 2;
  const hitColor = m.hitTimer > 0;
  const aura = Math.sin(m.animTimer * 0.05) * 3;

  // 暗黑光环
  ctx.strokeStyle = hitColor ? "#fff" : `rgba(180, 0, 30, ${0.3 + Math.sin(m.animTimer * 0.06) * 0.15})`;
  ctx.lineWidth = 3 + aura * 0.5;
  ctx.beginPath();
  ctx.arc(cx, cy, 32 + aura, 0, Math.PI * 2);
  ctx.stroke();

  // 披风
  ctx.fillStyle = hitColor ? "#800" : "#4a0000";
  ctx.beginPath();
  ctx.moveTo(cx - 16, cy - 8);
  ctx.lineTo(cx - 22, cy + 24);
  ctx.lineTo(cx + 22, cy + 24);
  ctx.lineTo(cx + 16, cy - 8);
  ctx.closePath();
  ctx.fill();

  // 身体（魔王铠甲）
  const grad = ctx.createLinearGradient(cx, cy - 16, cx, cy + 16);
  grad.addColorStop(0, hitColor ? "#f88" : "#8b0000");
  grad.addColorStop(0.5, hitColor ? "#f66" : "#5c0000");
  grad.addColorStop(1, hitColor ? "#f88" : "#8b0000");
  ctx.fillStyle = grad;
  ctx.fillRect(cx - 14, cy - 12, 28, 28);

  // 胸甲符文
  ctx.fillStyle = hitColor ? "#fff" : "#ffd700";
  ctx.font = "bold 12px monospace";
  ctx.textAlign = "center";
  ctx.fillText("✧", cx, cy + 2);

  // 头
  ctx.fillStyle = hitColor ? "#faa" : "#5c0000";
  ctx.beginPath();
  ctx.arc(cx, cy - 22, 14, 0, Math.PI * 2);
  ctx.fill();

  // 巨大魔角
  ctx.fillStyle = hitColor ? "#ccc" : "#222";
  ctx.beginPath();
  ctx.moveTo(cx - 8, cy - 32);
  ctx.lineTo(cx - 20, cy - 55);
  ctx.lineTo(cx - 1, cy - 28);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(cx + 8, cy - 32);
  ctx.lineTo(cx + 20, cy - 55);
  ctx.lineTo(cx + 1, cy - 28);
  ctx.fill();

  // 燃烧的眼睛
  ctx.fillStyle = hitColor ? "#fff" : "#ff6600";
  ctx.shadowColor = hitColor ? "#fff" : "#ff6600";
  ctx.shadowBlur = 6;
  ctx.beginPath();
  ctx.arc(cx - 5, cy - 22, 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.arc(cx + 5, cy - 22, 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;

  // 火焰巨剑
  ctx.fillStyle = hitColor ? "#ddd" : "#333";
  ctx.fillRect(cx + 12, cy - 22, 4, 38);
  ctx.fillStyle = hitColor ? "#ff0" : "#ff4500";
  ctx.fillRect(cx + 12, cy - 22, 4, 8);
  ctx.fillStyle = hitColor ? "#fff" : "#ffd700";
  ctx.fillRect(cx + 13, cy - 24, 2, 4);

  // 火焰粒子效果
  for (let i = 0; i < 4; i++) {
    const fy = cy - 18 - i * 6 + Math.sin(m.animTimer * 0.2 + i) * 3;
    ctx.fillStyle = `rgba(255, ${100 + i * 30}, 0, ${0.6 + Math.sin(m.animTimer * 0.15 + i) * 0.3})`;
    ctx.beginPath();
    ctx.arc(cx + 14 + Math.sin(m.animTimer * 0.3 + i) * 4, fy, 2 + Math.random(), 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}

function drawMonster(ctx: CanvasRenderingContext2D, m: Monster) {
  switch (m.type) {
    case "slime":
      drawSlime(ctx, m);
      break;
    case "mushroom":
      drawMushroom(ctx, m);
      break;
    case "skeleton":
      drawSkeleton(ctx, m);
      break;
    case "gargoyle":
      drawGargoyle(ctx, m);
      break;
    case "dark_knight":
      drawDarkKnight(ctx, m);
      break;
    case "boss":
      drawBoss(ctx, m);
      break;
  }
}

// ============================================================
// 地图背景绘制
// ============================================================

function drawForestBG(ctx: CanvasRenderingContext2D, camX: number) {
  // 天空
  const skyGrad = ctx.createLinearGradient(0, 0, 0, GAME_H);
  skyGrad.addColorStop(0, "#87ceeb");
  skyGrad.addColorStop(0.6, "#b8e6b8");
  skyGrad.addColorStop(1, "#5a8f3c");
  ctx.fillStyle = skyGrad;
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  // 远山
  ctx.fillStyle = "#6b9e4a";
  for (let i = 0; i < 8; i++) {
    const mx = i * 180 - (camX * 0.1) % 180;
    ctx.beginPath();
    ctx.moveTo(mx - 40, GAME_H - 100);
    ctx.quadraticCurveTo(mx + 20, GAME_H - 220, mx + 70, GAME_H - 100);
    ctx.fill();
  }

  // 云朵
  ctx.fillStyle = "rgba(255,255,255,0.7)";
  for (let i = 0; i < 6; i++) {
    const cx = i * 250 - (camX * 0.05) % 250;
    ctx.beginPath();
    ctx.arc(cx, 60, 25, 0, Math.PI * 2);
    ctx.arc(cx + 20, 50, 20, 0, Math.PI * 2);
    ctx.arc(cx + 15, 70, 18, 0, Math.PI * 2);
    ctx.fill();
  }

  // 树（前景）
  for (let i = 0; i < 10; i++) {
    const tx = i * 180 - (camX * 0.3) % 180;
    const treeH = 80 + (i * 37) % 40;
    // 树干
    ctx.fillStyle = "#6b3a2a";
    ctx.fillRect(tx - 6, GAME_H - 90 - treeH, 12, treeH + 20);
    // 树冠
    ctx.fillStyle = "#3d7a28";
    ctx.beginPath();
    ctx.arc(tx, GAME_H - 110 - treeH, 28, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#4a9430";
    ctx.beginPath();
    ctx.arc(tx - 12, GAME_H - 95 - treeH, 20, 0, Math.PI * 2);
    ctx.fill();
    ctx.arc(tx + 10, GAME_H - 98 - treeH, 18, 0, Math.PI * 2);
    ctx.fill();
  }

  // 地面花草
  for (let i = 0; i < 30; i++) {
    const gx = i * 50 - (camX * 0.5) % 50;
    ctx.fillStyle = ["#ff69b4", "#ffd700", "#fff", "#ff8c00"][i % 4];
    ctx.beginPath();
    ctx.arc(gx, GAME_H - 18, 3, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawCaveBG(ctx: CanvasRenderingContext2D, camX: number) {
  // 洞穴暗色背景
  const caveGrad = ctx.createLinearGradient(0, 0, 0, GAME_H);
  caveGrad.addColorStop(0, "#1a1025");
  caveGrad.addColorStop(0.5, "#1c1528");
  caveGrad.addColorStop(1, "#261a30");
  ctx.fillStyle = caveGrad;
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  // 钟乳石
  ctx.fillStyle = "#3a3045";
  for (let i = 0; i < 12; i++) {
    const sx = i * 110 - (camX * 0.15) % 110;
    const sh = 30 + (i * 23) % 50;
    ctx.beginPath();
    ctx.moveTo(sx - 8, 0);
    ctx.lineTo(sx, sh);
    ctx.lineTo(sx + 8, 0);
    ctx.fill();
  }

  // 石笋
  for (let i = 0; i < 14; i++) {
    const sx = i * 100 - (camX * 0.2) % 100;
    const sh = 20 + (i * 31) % 40;
    ctx.fillStyle = "#3a3045";
    ctx.beginPath();
    ctx.moveTo(sx - 6, GAME_H);
    ctx.lineTo(sx, GAME_H - sh);
    ctx.lineTo(sx + 6, GAME_H);
    ctx.fill();
  }

  // 发光水晶
  for (let i = 0; i < 8; i++) {
    const cx = i * 200 - (camX * 0.2) % 200;
    const alpha = 0.3 + Math.sin(Date.now() * 0.002 + i) * 0.15;
    ctx.fillStyle = `rgba(100, 200, 255, ${alpha})`;
    ctx.shadowColor = "rgba(100,200,255,0.5)";
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.arc(cx, 120 + (i % 3) * 80, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  // 地面
  ctx.fillStyle = "#2a2035";
  ctx.fillRect(0, GAME_H - 20, GAME_W, 20);
  ctx.fillStyle = "#352a42";
  for (let i = 0; i < 20; i++) {
    ctx.fillRect(i * 60 - (camX * 0.3) % 60, GAME_H - 22, 40, 4);
  }
}

function drawCastleBG(ctx: CanvasRenderingContext2D, camX: number) {
  // 暗红天空
  const skyGrad = ctx.createLinearGradient(0, 0, 0, GAME_H);
  skyGrad.addColorStop(0, "#1a0000");
  skyGrad.addColorStop(0.4, "#3d0000");
  skyGrad.addColorStop(1, "#2a0a0a");
  ctx.fillStyle = skyGrad;
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  // 远城堡塔楼
  for (let i = 0; i < 5; i++) {
    const tx = i * 280 - (camX * 0.08) % 280;
    ctx.fillStyle = "#1a0a0a";
    ctx.fillRect(tx - 15, GAME_H - 200, 30, 180);
    ctx.fillStyle = "#2a0a0a";
    ctx.fillRect(tx - 18, GAME_H - 210, 36, 20);
    // 尖顶
    ctx.fillStyle = "#3d0000";
    ctx.beginPath();
    ctx.moveTo(tx - 20, GAME_H - 210);
    ctx.lineTo(tx, GAME_H - 270);
    ctx.lineTo(tx + 20, GAME_H - 210);
    ctx.fill();
  }

  // 石砖纹理
  ctx.fillStyle = "#2a1520";
  ctx.fillRect(0, GAME_H - 30, GAME_W, 30);
  for (let i = 0; i < 30; i++) {
    const bx = i * 50 - (camX * 0.3) % 50;
    ctx.strokeStyle = "#3d2030";
    ctx.lineWidth = 1;
    ctx.strokeRect(bx, GAME_H - 28, 45, 12);
  }

  // 火炬
  for (let i = 0; i < 6; i++) {
    const fx = i * 250 - (camX * 0.2) % 250;
    ctx.fillStyle = "#444";
    ctx.fillRect(fx - 2, GAME_H - 70, 4, 40);
    const flicker = Math.sin(Date.now() * 0.008 + i) * 3;
    ctx.fillStyle = "rgba(255,150,20,0.6)";
    ctx.shadowColor = "#ff6600";
    ctx.shadowBlur = 15;
    ctx.beginPath();
    ctx.arc(fx, GAME_H - 75 + flicker, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }
}

// ============================================================
// 粒子系统
// ============================================================

function spawnParticles(
  particles: Particle[],
  x: number,
  y: number,
  color: string,
  count: number
) {
  for (let i = 0; i < count; i++) {
    particles.push({
      x,
      y,
      vx: (Math.random() - 0.5) * 6,
      vy: (Math.random() - 0.5) * 6 - 3,
      life: 20 + Math.random() * 20,
      maxLife: 40,
      color,
      size: 2 + Math.random() * 3,
    });
  }
}

function updateParticles(particles: Particle[]) {
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.vy += 0.1;
    p.life--;
    if (p.life <= 0) particles.splice(i, 1);
  }
}

function drawParticles(ctx: CanvasRenderingContext2D, particles: Particle[]) {
  for (const p of particles) {
    const alpha = p.life / p.maxLife;
    ctx.fillStyle = p.color.replace(")", `,${alpha})`).replace("rgb", "rgba");
    if (p.color.startsWith("#")) {
      ctx.globalAlpha = alpha;
      ctx.fillStyle = p.color;
    }
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.size * alpha, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}

// ============================================================
// 地图数据构建
// ============================================================

function buildMaps(): MapData[] {
  const groundY = GAME_H - 40;

  // 地图1：翠绿森林
  const forestMap: MapData = {
    name: "翠绿森林",
    width: GAME_W * 3,
    height: GAME_H,
    bgColor: "#87ceeb",
    platforms: [
      { x: 0, y: groundY, w: GAME_W * 3, h: 40 }, // 主地面
      { x: 300, y: groundY - 80, w: 150, h: 12 }, // 浮台1
      { x: 600, y: groundY - 130, w: 120, h: 12 }, // 浮台2
      { x: 900, y: groundY - 90, w: 140, h: 12 }, // 浮台3
      { x: 1200, y: groundY - 110, w: 160, h: 12 }, // 浮台4
      { x: 1600, y: groundY - 80, w: 130, h: 12 }, // 浮台5
      { x: 2000, y: groundY - 130, w: 150, h: 12 }, // 浮台6
      { x: 2400, y: groundY - 90, w: 140, h: 12 }, // 浮台7
    ],
    monsters: [
      createMonster("slime", 350, groundY - 28, 200, 500),
      createMonster("slime", 650, groundY - 28, 580, 750),
      createMonster("mushroom", 550, groundY - 32, 500, 680),
      createMonster("mushroom", 1100, groundY - 32, 1020, 1250),
      createMonster("slime", 1700, groundY - 28, 1580, 1820),
      createMonster("mushroom", 2100, groundY - 32, 2020, 2180),
      createMonster("slime", 2450, groundY - 28, 2350, 2580),
    ],
    npcs: [
      {
        x: 100,
        y: groundY - 44,
        width: 20,
        height: 36,
        name: "村长",
        dialogues: [
          "勇者啊，你终于来了！",
          "森林里的怪物越来越猖狂……",
          "史莱姆还算温和，但毒蘑菇怪很危险！",
          "打败它们，穿过森林前往洞穴吧！",
          "前方入口通往幽暗洞穴，那里有更强的敌人。",
          "愿光明与你同在！",
        ],
        dialogueIndex: 0,
        triggered: false,
      },
      {
        x: 2600,
        y: groundY - 44,
        width: 20,
        height: 36,
        name: "森林守卫",
        dialogues: [
          "前方的洞穴充满危险……",
          "骷髅兵和石像鬼盘踞其中。",
          "你准备好了吗？进入洞穴吧，勇者！",
        ],
        dialogueIndex: 0,
        triggered: false,
      },
    ],
    portals: [
      {
        x: GAME_W * 3 - 80,
        y: groundY - 60,
        width: 50,
        height: 60,
        targetMap: 1,
        targetX: 120,
        targetY: groundY - 100,
        label: "→ 幽暗洞穴",
      },
    ],
    drawBackground: drawForestBG,
  };

  // 地图2：幽暗洞穴
  const caveMap: MapData = {
    name: "幽暗洞穴",
    width: GAME_W * 3,
    height: GAME_H,
    bgColor: "#1a1025",
    platforms: [
      { x: 0, y: groundY, w: GAME_W * 3, h: 40 },
      { x: 250, y: groundY - 70, w: 130, h: 12 },
      { x: 500, y: groundY - 100, w: 140, h: 12 },
      { x: 800, y: groundY - 75, w: 120, h: 12 },
      { x: 1100, y: groundY - 110, w: 150, h: 12 },
      { x: 1500, y: groundY - 80, w: 160, h: 12 },
      { x: 1900, y: groundY - 95, w: 140, h: 12 },
      { x: 2300, y: groundY - 70, w: 130, h: 12 },
    ],
    monsters: [
      createMonster("skeleton", 400, groundY - 32, 300, 550),
      createMonster("skeleton", 700, groundY - 32, 620, 850),
      createMonster("gargoyle", 600, groundY - 110, 500, 780),
      createMonster("skeleton", 1300, groundY - 32, 1180, 1450),
      createMonster("gargoyle", 1700, groundY - 110, 1580, 1850),
      createMonster("skeleton", 2100, groundY - 32, 2020, 2220),
      createMonster("gargoyle", 2500, groundY - 100, 2380, 2600),
    ],
    npcs: [
      {
        x: 80,
        y: groundY - 44,
        width: 20,
        height: 36,
        name: "探险家",
        dialogues: [
          "小心！这洞穴里的骷髅兵不知疲倦……",
          "石像鬼会从空中俯冲攻击！",
          "我上次差点没逃出去……",
          "穿过洞穴就是魔王的城堡，祝你顺利！",
        ],
        dialogueIndex: 0,
        triggered: false,
      },
    ],
    portals: [
      {
        x: 50,
        y: groundY - 60,
        width: 50,
        height: 60,
        targetMap: 0,
        targetX: GAME_W * 3 - 150,
        targetY: groundY - 60,
        label: "← 翠绿森林",
      },
      {
        x: GAME_W * 3 - 80,
        y: groundY - 60,
        width: 50,
        height: 60,
        targetMap: 2,
        targetX: 120,
        targetY: groundY - 100,
        label: "→ 魔王城堡",
      },
    ],
    drawBackground: drawCaveBG,
  };

  // 地图3：魔王城堡 + Boss
  const castleMap: MapData = {
    name: "魔王城堡",
    width: GAME_W * 3,
    height: GAME_H,
    bgColor: "#1a0000",
    platforms: [
      { x: 0, y: groundY, w: GAME_W * 2, h: 40 },
      { x: GAME_W * 2, y: groundY, w: GAME_W, h: 40 }, // Boss区域地面
      { x: 300, y: groundY - 80, w: 140, h: 12 },
      { x: 700, y: groundY - 100, w: 130, h: 12 },
      { x: 1200, y: groundY - 85, w: 150, h: 12 },
      { x: 1600, y: groundY - 75, w: 120, h: 12 },
    ],
    monsters: [
      createMonster("dark_knight", 450, groundY - 36, 350, 600),
      createMonster("dark_knight", 900, groundY - 36, 800, 1050),
      createMonster("dark_knight", 1400, groundY - 36, 1280, 1520),
      createMonster("dark_knight", 1750, groundY - 36, 1650, 1850),
      // Boss
      {
        id: 999,
        type: "boss",
        x: GAME_W * 2 + 300,
        y: groundY - 60,
        vx: 0,
        vy: 0,
        width: 56,
        height: 60,
        hp: 300,
        maxHp: 300,
        damage: 20,
        patrolLeft: GAME_W * 2 + 100,
        patrolRight: GAME_W * 3 - 100,
        direction: "left",
        animFrame: 0,
        animTimer: 0,
        hitTimer: 0,
        alive: true,
        bossPhase: 1,
        bossSpecialTimer: 0,
      },
    ],
    npcs: [
      {
        x: 100,
        y: groundY - 44,
        width: 20,
        height: 36,
        name: "王国骑士",
        dialogues: [
          "勇者！你终于来到了这里……",
          "魔王就在前方，他已经屠杀了无数勇士。",
          "暗影骑士是魔王的贴身侍卫，极度危险！",
          "打败魔王，拯救这片大陆吧！",
          "全王国的希望都在你身上了！",
        ],
        dialogueIndex: 0,
        triggered: false,
      },
    ],
    portals: [
      {
        x: 50,
        y: groundY - 60,
        width: 50,
        height: 60,
        targetMap: 1,
        targetX: GAME_W * 3 - 150,
        targetY: groundY - 60,
        label: "← 幽暗洞穴",
      },
    ],
    drawBackground: drawCastleBG,
  };

  return [forestMap, caveMap, castleMap];
}

function createMonster(
  type: Monster["type"],
  x: number,
  y: number,
  patrolLeft: number,
  patrolRight: number
): Monster {
  const stats: Record<string, { w: number; h: number; hp: number; dmg: number }> = {
    slime: { w: 28, h: 24, hp: 30, dmg: 8 },
    mushroom: { w: 32, h: 30, hp: 45, dmg: 12 },
    skeleton: { w: 30, h: 32, hp: 55, dmg: 15 },
    gargoyle: { w: 34, h: 32, hp: 50, dmg: 14 },
    dark_knight: { w: 34, h: 36, hp: 80, dmg: 20 },
    boss: { w: 56, h: 60, hp: 300, dmg: 25 },
  };
  const s = stats[type];
  return {
    id: Date.now() + Math.random() * 10000,
    type,
    x,
    y,
    vx: 0,
    vy: 0,
    width: s.w,
    height: s.h,
    hp: s.hp,
    maxHp: s.hp,
    damage: s.dmg,
    patrolLeft,
    patrolRight,
    direction: "left",
    animFrame: 0,
    animTimer: Math.random() * 100,
    hitTimer: 0,
    alive: true,
  };
}

// ============================================================
// 碰撞检测
// ============================================================

function rectsOverlap(
  ax: number, ay: number, aw: number, ah: number,
  bx: number, by: number, bw: number, bh: number
): boolean {
  return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
}

// ============================================================
// 主游戏组件
// ============================================================

export default function AdventureIslandPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const gameRef = useRef<GameState | null>(null);
  const rafRef = useRef<number>(0);
  const [gameStarted, setGameStarted] = useState(false);

  const initGame = useCallback((): GameState => {
    const maps = buildMaps();
    const groundY = GAME_H - 40;
    return {
      phase: "title",
      currentMap: 0,
      player: {
        x: 150,
        y: groundY - 44,
        vx: 0,
        vy: 0,
        width: 20,
        height: 36,
        hp: 100,
        maxHp: 100,
        attackCooldown: 0,
        invincibleTimer: 0,
        direction: "right",
        animFrame: 0,
        animTimer: 0,
        attacking: false,
        attackTimer: 0,
        onGround: false,
      },
      maps,
      cameraX: 0,
      keys: new Set(),
      dialogueNPC: null,
      dialogueLine: 0,
      transitionTimer: 0,
      transitionTargetMap: 0,
      particles: [],
      shakeTimer: 0,
      shakeIntensity: 0,
    };
  }, []);

  // 游戏循环
  const gameLoop = useCallback(() => {
    const gs = gameRef.current;
    if (!gs) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    update(gs);
    render(gs, ctx);

    rafRef.current = requestAnimationFrame(gameLoop);
  }, []);

  useEffect(() => {
    if (!gameStarted) return;
    if (!gameRef.current) {
      gameRef.current = initGame();
    }

    // 键盘事件
    const handleKeyDown = (e: KeyboardEvent) => {
      const gs = gameRef.current;
      if (!gs) return;
      e.preventDefault();

      if (gs.phase === "title") {
        if (e.code === "Enter" || e.code === "Space") {
          gs.phase = "playing";
        }
        return;
      }

      if (gs.phase === "dialogue") {
        if (e.code === "Enter" || e.code === "Space" || e.code === "KeyZ") {
          advanceDialogue(gs);
        }
        return;
      }

      if (gs.phase === "victory" || gs.phase === "game_over") {
        if (e.code === "Enter" || e.code === "Space") {
          // 重新开始
          gameRef.current = initGame();
          gameRef.current!.phase = "playing";
        }
        return;
      }

      gs.keys.add(e.code);

      if (e.code === "KeyZ" || e.code === "Space") {
        playerAttack(gs);
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      const gs = gameRef.current;
      if (!gs) return;
      gs.keys.delete(e.code);
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);

    rafRef.current = requestAnimationFrame(gameLoop);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      cancelAnimationFrame(rafRef.current);
    };
  }, [gameStarted, gameLoop, initGame]);

  const startGame = () => {
    setGameStarted(true);
  };

  return (
    <div style={{
      width: "100vw",
      height: "100vh",
      background: "#000",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      overflow: "hidden",
      fontFamily: "'Press Start 2P', 'Courier New', monospace",
    }}>
      {!gameStarted ? (
        <div style={{ textAlign: "center", color: "#fff" }}>
          <h1 style={{ fontSize: "2rem", marginBottom: "2rem", color: "#ffd700" }}>
            冒险岛传奇
          </h1>
          <p style={{ fontSize: "0.9rem", color: "#aaa", marginBottom: "2rem" }}>
            横版动作RPG小游戏
          </p>
          <button
            onClick={startGame}
            style={{
              padding: "1rem 3rem",
              fontSize: "1.2rem",
              background: "#ffd700",
              color: "#1a1a2e",
              border: "none",
              borderRadius: "8px",
              cursor: "pointer",
              fontWeight: "bold",
            }}
          >
            开始游戏
          </button>
          <div style={{ marginTop: "2rem", fontSize: "0.7rem", color: "#888" }}>
            <p>方向键 ← → 移动 | ↑ 跳跃 | Z / 空格 攻击</p>
            <p>靠近NPC按 Z 触发对话</p>
          </div>
        </div>
      ) : (
        <canvas
          ref={canvasRef}
          width={GAME_W}
          height={GAME_H}
          style={{
            width: "100%",
            maxWidth: "960px",
            height: "auto",
            aspectRatio: "16/9",
            imageRendering: "pixelated",
          }}
        />
      )}
    </div>
  );
}

// ============================================================
// 游戏逻辑 — 更新
// ============================================================

function update(gs: GameState) {
  if (gs.phase === "map_transition") {
    gs.transitionTimer--;
    if (gs.transitionTimer <= 0) {
      gs.currentMap = gs.transitionTargetMap;
      gs.phase = "playing";
    }
    return;
  }

  if (gs.phase !== "playing") return;

  const p = gs.player;
  const map = gs.maps[gs.currentMap];
  const keys = gs.keys;

  // --- 玩家输入 ---
  let moveX = 0;
  if (keys.has("ArrowLeft") || keys.has("KeyA")) moveX = -PLAYER_SPEED;
  if (keys.has("ArrowRight") || keys.has("KeyD")) moveX = PLAYER_SPEED;

  p.vx = moveX;
  if (moveX !== 0) p.direction = moveX > 0 ? "right" : "left";

  // 跳跃
  if ((keys.has("ArrowUp") || keys.has("KeyW")) && p.onGround) {
    p.vy = PLAYER_JUMP;
    p.onGround = false;
  }

  // 重力
  p.vy += GRAVITY;

  // 最大下落速度
  if (p.vy > 15) p.vy = 15;

  // 移动
  p.x += p.vx;
  p.y += p.vy;

  // 平台碰撞
  p.onGround = false;
  for (const plat of map.platforms) {
    if (rectsOverlap(p.x, p.y, p.width, p.height, plat.x, plat.y, plat.w, plat.h)) {
      // 从上方落下
      if (p.vy > 0 && p.y + p.height - p.vy <= plat.y + 6) {
        p.y = plat.y - p.height;
        p.vy = 0;
        p.onGround = true;
      }
      // 从下方撞头
      else if (p.vy < 0 && p.y - p.vy >= plat.y + plat.h - 6) {
        p.y = plat.y + plat.h;
        p.vy = 1;
      }
    }
  }

  // 地图边界
  if (p.x < 0) p.x = 0;
  if (p.x + p.width > map.width) p.x = map.width - p.width;
  if (p.y > GAME_H) {
    // 掉落死亡
    p.hp = 0;
    gs.phase = "game_over";
  }

  // 冷却计时
  if (p.attackCooldown > 0) p.attackCooldown--;
  if (p.invincibleTimer > 0) p.invincibleTimer--;
  if (p.attackTimer > 0) {
    p.attackTimer--;
    if (p.attackTimer <= 0) p.attacking = false;
  }
  p.animTimer++;

  // --- 摄像机 ---
  const targetCamX = p.x - GAME_W / 2 + p.width / 2;
  const maxCamX = map.width - GAME_W;
  gs.cameraX += (Math.max(0, Math.min(targetCamX, maxCamX)) - gs.cameraX) * CAMERA_SMOOTH;

  // --- 怪物更新 ---
  updateMonsters(gs, map);

  // --- 攻击检测 ---
  if (p.attacking) {
    const attackBox = {
      x: p.direction === "right" ? p.x + p.width : p.x - 20,
      y: p.y - 4,
      w: 20,
      h: p.height + 8,
    };
    for (const m of map.monsters) {
      if (!m.alive) continue;
      if (rectsOverlap(attackBox.x, attackBox.y, attackBox.w, attackBox.h, m.x, m.y, m.width, m.height)) {
        if (m.hitTimer <= 0) {
          const dmg = m.type === "boss" ? 8 : 25;
          m.hp -= dmg;
          m.hitTimer = 15;
          spawnParticles(gs.particles, m.x + m.width / 2, m.y + m.height / 2, "#ff0", 5);
          gs.shakeTimer = 6;
          gs.shakeIntensity = 3;

          if (m.hp <= 0) {
            m.alive = false;
            spawnParticles(gs.particles, m.x + m.width / 2, m.y + m.height / 2, "#ff6600", 15);

            // Boss被击败
            if (m.type === "boss") {
              gs.phase = "victory";
              gs.shakeTimer = 20;
              gs.shakeIntensity = 8;
            }
          }

          // Boss阶段切换
          if (m.type === "boss" && m.alive) {
            const hpRatio = m.hp / m.maxHp;
            if (hpRatio < 0.3 && m.bossPhase !== 3) {
              m.bossPhase = 3;
            } else if (hpRatio < 0.6 && m.bossPhase !== 2) {
              m.bossPhase = 2;
            }
          }
        }
      }
    }
  }

  // --- 玩家受伤检测 ---
  if (p.invincibleTimer <= 0) {
    for (const m of map.monsters) {
      if (!m.alive) continue;
      if (rectsOverlap(p.x, p.y, p.width, p.height, m.x, m.y, m.width, m.height)) {
        p.hp -= m.damage;
        p.invincibleTimer = INVINCIBLE_DURATION;
        spawnParticles(gs.particles, p.x + p.width / 2, p.y + p.height / 2, "#ff0000", 8);
        gs.shakeTimer = 8;
        gs.shakeIntensity = 4;
        // 击退
        const knockDir = p.x < m.x ? -1 : 1;
        p.vx = knockDir * 7;
        p.vy = -5;
        p.onGround = false;

        if (p.hp <= 0) {
          gs.phase = "game_over";
        }
        break;
      }
    }
  }

  // --- NPC 检测 ---
  if (keys.has("KeyZ") && gs.phase === "playing") {
    for (const npc of map.npcs) {
      const distX = Math.abs(p.x + p.width / 2 - (npc.x + npc.width / 2));
      const distY = Math.abs(p.y + p.height / 2 - (npc.y + npc.height / 2));
      if (distX < 50 && distY < 50) {
        gs.phase = "dialogue";
        gs.dialogueNPC = npc;
        gs.dialogueLine = 0;
        break;
      }
    }
  }

  // --- 传送门检测 ---
  for (const portal of map.portals) {
    if (rectsOverlap(p.x, p.y, p.width, p.height, portal.x, portal.y, portal.width, portal.height)) {
      gs.phase = "map_transition";
      gs.transitionTimer = 40;
      gs.transitionTargetMap = portal.targetMap;
      p.x = portal.targetX;
      p.y = portal.targetY;
      break;
    }
  }

  // --- 粒子 ---
  updateParticles(gs.particles);

  // --- 屏幕震动 ---
  if (gs.shakeTimer > 0) gs.shakeTimer--;
}

function updateMonsters(gs: GameState, map: MapData) {
  const p = gs.player;
  for (const m of map.monsters) {
    if (!m.alive) continue;
    m.animTimer++;
    if (m.hitTimer > 0) m.hitTimer--;

    // Boss特殊AI
    if (m.type === "boss") {
      updateBoss(m, p, gs);
      continue;
    }

    // 普通怪物巡逻AI
    m.vx = m.direction === "left" ? -1.5 : 1.5;
    m.x += m.vx;

    if (m.x <= m.patrolLeft) {
      m.x = m.patrolLeft;
      m.direction = "right";
    } else if (m.x + m.width >= m.patrolRight) {
      m.x = m.patrolRight - m.width;
      m.direction = "left";
    }

    // 玩家接近时加速追击
    const distToPlayer = Math.abs(m.x - p.x);
    if (distToPlayer < 200 && Math.abs(m.y - p.y) < 60) {
      const chaseDir = p.x < m.x ? "left" : "right";
      m.direction = chaseDir;
      m.vx = chaseDir === "left" ? -2.5 : 2.5;
      m.x += (chaseDir === "left" ? -1 : 1);
    }

    // 石像鬼上下浮动
    if (m.type === "gargoyle") {
      m.y += Math.sin(m.animTimer * 0.06) * 1;
    }
  }
}

function updateBoss(m: Monster, p: Player, gs: GameState) {
  m.bossSpecialTimer = (m.bossSpecialTimer || 0) + 1;

  const speed = m.bossPhase === 3 ? 3.5 : m.bossPhase === 2 ? 2.5 : 1.8;
  const chaseDist = Math.abs(m.x - p.x);

  if (chaseDist > 30) {
    m.direction = p.x < m.x ? "left" : "right";
    m.vx = m.direction === "left" ? -speed : speed;
  } else {
    m.vx = 0;
  }

  m.x += m.vx;

  // Boss冲刺攻击
  if (m.bossPhase! >= 2 && m.bossSpecialTimer! > 120) {
    m.bossSpecialTimer = 0;
    // 向玩家冲刺
    m.vx = m.direction === "left" ? -8 : 8;
    m.x += m.vx;
  }

  // Boss阶段3：召唤火焰波
  if (m.bossPhase === 3 && m.bossSpecialTimer! % 60 === 0) {
    spawnParticles(gs.particles, m.x + m.width / 2, m.y + m.height / 2, "#ff4500", 3);
  }

  // 边界
  if (m.x < m.patrolLeft) m.x = m.patrolLeft;
  if (m.x + m.width > m.patrolRight) m.x = m.patrolRight - m.width;
}

function playerAttack(gs: GameState) {
  const p = gs.player;
  if (p.attackCooldown > 0 || p.attacking) return;
  p.attacking = true;
  p.attackTimer = ATTACK_DURATION;
  p.attackCooldown = ATTACK_COOLDOWN;
}

function advanceDialogue(gs: GameState) {
  if (!gs.dialogueNPC) return;
  gs.dialogueLine++;
  if (gs.dialogueLine >= gs.dialogueNPC.dialogues.length) {
    gs.dialogueNPC.triggered = true;
    gs.dialogueNPC = null;
    gs.dialogueLine = 0;
    gs.phase = "playing";
  }
}

// ============================================================
// 游戏逻辑 — 渲染
// ============================================================

function render(gs: GameState, ctx: CanvasRenderingContext2D) {
  ctx.clearRect(0, 0, GAME_W, GAME_H);

  // 屏幕震动偏移
  let shakeX = 0, shakeY = 0;
  if (gs.shakeTimer > 0) {
    const intensity = gs.shakeIntensity * (gs.shakeTimer / 20);
    shakeX = (Math.random() - 0.5) * intensity * 2;
    shakeY = (Math.random() - 0.5) * intensity * 2;
  }

  ctx.save();
  ctx.translate(shakeX, shakeY);

  if (gs.phase === "title") {
    renderTitle(ctx);
    ctx.restore();
    return;
  }

  const map = gs.maps[gs.currentMap];
  const camX = gs.cameraX;
  const p = gs.player;

  // 绘制地图背景
  map.drawBackground(ctx, camX);

  // 绘制平台
  ctx.save();
  ctx.translate(-camX, 0);
  for (const plat of map.platforms) {
    if (gs.currentMap === 0) {
      // 森林平台 — 草地质感
      ctx.fillStyle = "#5a8f3c";
      ctx.fillRect(plat.x, plat.y, plat.w, plat.h);
      ctx.fillStyle = "#4a7f2c";
      ctx.fillRect(plat.x, plat.y, plat.w, 5);
    } else if (gs.currentMap === 1) {
      // 洞穴平台
      ctx.fillStyle = "#3a3045";
      ctx.fillRect(plat.x, plat.y, plat.w, plat.h);
      ctx.fillStyle = "#4a4055";
      ctx.fillRect(plat.x, plat.y, plat.w, 4);
    } else {
      // 城堡平台 — 石砖
      ctx.fillStyle = "#2a1520";
      ctx.fillRect(plat.x, plat.y, plat.w, plat.h);
      ctx.fillStyle = "#3d2030";
      for (let bx = plat.x; bx < plat.x + plat.w; bx += 20) {
        ctx.fillRect(bx, plat.y, 19, 6);
      }
    }
  }

  // 绘制传送门
  for (const portal of map.portals) {
    const glow = Math.sin(Date.now() * 0.005) * 0.3 + 0.7;
    ctx.fillStyle = `rgba(100, 200, 255, ${glow * 0.5})`;
    ctx.shadowColor = "rgba(100,200,255,0.6)";
    ctx.shadowBlur = 12;
    ctx.fillRect(portal.x, portal.y, portal.width, portal.height);
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#fff";
    ctx.font = "9px monospace";
    ctx.textAlign = "center";
    ctx.fillText(portal.label, portal.x + portal.width / 2, portal.y - 10);
  }

  // 绘制NPC
  for (const npc of map.npcs) {
    // NPC身体
    ctx.fillStyle = "#e8b88a";
    ctx.fillRect(npc.x + 4, npc.y + 8, 12, 20);
    // NPC头
    ctx.fillStyle = "#f0c8a0";
    ctx.beginPath();
    ctx.arc(npc.x + 10, npc.y, 8, 0, Math.PI * 2);
    ctx.fill();
    // NPC帽子
    ctx.fillStyle = "#6b3a2a";
    ctx.fillRect(npc.x + 2, npc.y - 14, 16, 5);
    ctx.fillRect(npc.x + 6, npc.y - 20, 8, 6);
    // NPC名字
    ctx.fillStyle = "#ffd700";
    ctx.font = "8px monospace";
    ctx.textAlign = "center";
    ctx.fillText(npc.name, npc.x + 10, npc.y - 26);
    // 未触发标记
    if (!npc.triggered) {
      ctx.fillStyle = "#ff0";
      ctx.beginPath();
      ctx.arc(npc.x + 10, npc.y - 30, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#000";
      ctx.font = "bold 7px monospace";
      ctx.fillText("!", npc.x + 10, npc.y - 27);
    }
  }

  // 绘制怪物
  for (const m of map.monsters) {
    if (!m.alive) continue;
    drawMonster(ctx, m);
  }

  ctx.restore();

  // 绘制玩家（屏幕坐标）
  const playerScreenX = p.x - camX;
  const playerScreenY = p.y;
  const screenPlayer = { ...p, x: playerScreenX, y: playerScreenY };
  drawPlayer(ctx, screenPlayer);

  // 攻击判定框可视（调试用，可注释掉）
  // if (p.attacking) {
  //   const atkX = p.direction === "right" ? playerScreenX + p.width : playerScreenX - 20;
  //   ctx.strokeStyle = "rgba(255,255,0,0.6)";
  //   ctx.lineWidth = 2;
  //   ctx.strokeRect(atkX, playerScreenY - 4, 20, p.height + 8);
  // }

  // 粒子
  drawParticles(ctx, gs.particles);

  // --- HUD ---
  drawHUD(ctx, gs);

  // --- 转场效果 ---
  if (gs.phase === "map_transition") {
    const alpha = gs.transitionTimer / 40;
    ctx.fillStyle = `rgba(0,0,0,${alpha})`;
    ctx.fillRect(0, 0, GAME_W, GAME_H);
    ctx.fillStyle = "#fff";
    ctx.font = "18px monospace";
    ctx.textAlign = "center";
    ctx.fillText("加载中...", GAME_W / 2, GAME_H / 2);
  }

  // --- 对话 ---
  if (gs.phase === "dialogue" && gs.dialogueNPC) {
    drawDialogueBox(ctx, gs.dialogueNPC, gs.dialogueLine);
  }

  // --- 胜利 ---
  if (gs.phase === "victory") {
    drawVictory(ctx);
  }

  // --- 失败 ---
  if (gs.phase === "game_over") {
    drawGameOver(ctx);
  }

  ctx.restore();
}

function renderTitle(ctx: CanvasRenderingContext2D) {
  // 背景
  const grad = ctx.createLinearGradient(0, 0, 0, GAME_H);
  grad.addColorStop(0, "#1a1a2e");
  grad.addColorStop(0.5, "#16213e");
  grad.addColorStop(1, "#0f3460");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  // 星星
  for (let i = 0; i < 50; i++) {
    const sx = (i * 137 + 50) % GAME_W;
    const sy = (i * 89 + 30) % (GAME_H * 0.7);
    const twinkle = Math.sin(Date.now() * 0.003 + i) * 0.4 + 0.6;
    ctx.fillStyle = `rgba(255,255,255,${twinkle})`;
    ctx.beginPath();
    ctx.arc(sx, sy, 1.5, 0, Math.PI * 2);
    ctx.fill();
  }

  // 标题
  ctx.fillStyle = "#ffd700";
  ctx.font = "bold 42px monospace";
  ctx.textAlign = "center";
  ctx.shadowColor = "#ff6600";
  ctx.shadowBlur = 20;
  ctx.fillText("冒险岛传奇", GAME_W / 2, 200);
  ctx.shadowBlur = 0;

  ctx.fillStyle = "#fff";
  ctx.font = "14px monospace";
  ctx.fillText("Adventure Island Legends", GAME_W / 2, 235);

  // 装饰线
  ctx.strokeStyle = "#ffd700";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(GAME_W / 2 - 180, 260);
  ctx.lineTo(GAME_W / 2 + 180, 260);
  ctx.stroke();

  // 操作说明
  const instructions = [
    "方向键 ← →  移动",
    "方向键 ↑  跳跃",
    "Z 或 空格  攻击 / 对话",
  ];
  ctx.fillStyle = "#ccc";
  ctx.font = "11px monospace";
  instructions.forEach((txt, i) => {
    ctx.fillText(txt, GAME_W / 2, 300 + i * 25);
  });

  // 故事简介
  ctx.fillStyle = "#aaa";
  ctx.font = "10px monospace";
  ctx.fillText("魔王的黑暗笼罩了大陆……", GAME_W / 2, 390);
  ctx.fillText("一位年轻的勇者踏上了冒险之旅。", GAME_W / 2, 410);
  ctx.fillText("穿过翠绿森林、幽暗洞穴，", GAME_W / 2, 430);
  ctx.fillText("击败魔王，拯救这片土地！", GAME_W / 2, 450);

  // 闪烁提示
  const blink = Math.sin(Date.now() * 0.005) > 0;
  if (blink) {
    ctx.fillStyle = "#ffd700";
    ctx.font = "bold 16px monospace";
    ctx.fillText("按 Enter 开始游戏", GAME_W / 2, 500);
  }

  // 底部角色预览
  const previewPlayer: Player = {
    x: GAME_W / 2 - 10,
    y: 80,
    vx: 0,
    vy: 0,
    width: 20,
    height: 36,
    hp: 100,
    maxHp: 100,
    attackCooldown: 0,
    invincibleTimer: 0,
    direction: "right",
    animFrame: 0,
    animTimer: Date.now() * 0.02,
    attacking: false,
    attackTimer: 0,
    onGround: false,
  };
  // 画小预览
  ctx.save();
  ctx.translate(GAME_W / 2 - 10, 90);
  ctx.scale(1.5, 1.5);
  // 简化的预览
  ctx.fillStyle = "#fdbcb4";
  ctx.beginPath();
  ctx.arc(10, 5, 8, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#4a90d9";
  ctx.fillRect(2, 13, 16, 14);
  ctx.fillStyle = "#5c3317";
  ctx.fillRect(3, -5, 3, 8);
  ctx.fillRect(7, -6, 3, 7);
  ctx.fillRect(11, -4, 4, 9);
  ctx.restore();
}

function drawHUD(ctx: CanvasRenderingContext2D, gs: GameState) {
  const p = gs.player;
  const map = gs.maps[gs.currentMap];

  // 半透明HUD背景
  ctx.fillStyle = "rgba(0,0,0,0.6)";
  ctx.fillRect(0, 0, GAME_W, 40);

  // 血条
  ctx.fillStyle = "#333";
  ctx.fillRect(10, 8, 200, 14);
  const hpRatio = Math.max(0, p.hp / p.maxHp);
  const hpColor =
    hpRatio > 0.5 ? "#4caf50" : hpRatio > 0.25 ? "#ff9800" : "#f44336";
  ctx.fillStyle = hpColor;
  ctx.fillRect(10, 8, 200 * hpRatio, 14);
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 1;
  ctx.strokeRect(10, 8, 200, 14);

  // HP文字
  ctx.fillStyle = "#fff";
  ctx.font = "bold 10px monospace";
  ctx.textAlign = "left";
  ctx.fillText(`HP: ${Math.max(0, p.hp)} / ${p.maxHp}`, 14, 19);

  // 地图名称
  ctx.textAlign = "center";
  ctx.fillStyle = "#ffd700";
  ctx.font = "bold 13px monospace";
  ctx.fillText(map.name, GAME_W / 2, 18);

  // 地图进度
  ctx.textAlign = "right";
  ctx.fillStyle = "#aaa";
  ctx.font = "9px monospace";
  const progress = Math.round((p.x / map.width) * 100);
  ctx.fillText(`探索: ${progress}%`, GAME_W - 15, 18);

  // 操作提示
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.textAlign = "right";
  ctx.font = "8px monospace";
  ctx.fillText("←→移动 ↑跳跃 Z攻击", GAME_W - 15, 34);
}

function drawDialogueBox(ctx: CanvasRenderingContext2D, npc: NPC, lineIndex: number) {
  // 半透明背景
  ctx.fillStyle = "rgba(0,0,0,0.85)";
  ctx.fillRect(20, GAME_H - 140, GAME_W - 40, 120);
  ctx.strokeStyle = "#ffd700";
  ctx.lineWidth = 2;
  ctx.strokeRect(20, GAME_H - 140, GAME_W - 40, 120);

  // NPC名字
  ctx.fillStyle = "#ffd700";
  ctx.font = "bold 13px monospace";
  ctx.textAlign = "left";
  ctx.fillText(npc.name, 40, GAME_H - 108);

  // 对话内容
  ctx.fillStyle = "#fff";
  ctx.font = "11px monospace";
  const dialogue = npc.dialogues[lineIndex] || "";
  ctx.fillText(dialogue, 40, GAME_H - 80);

  // 继续提示
  if (lineIndex < npc.dialogues.length - 1) {
    const blink = Math.sin(Date.now() * 0.005) > 0;
    if (blink) {
      ctx.fillStyle = "#ffd700";
      ctx.textAlign = "right";
      ctx.font = "9px monospace";
      ctx.fillText("▼ 按Z继续", GAME_W - 50, GAME_H - 32);
    }
  } else {
    ctx.fillStyle = "#ffd700";
    ctx.textAlign = "right";
    ctx.font = "9px monospace";
    ctx.fillText("▼ 按Z关闭", GAME_W - 50, GAME_H - 32);
  }
}

function drawVictory(ctx: CanvasRenderingContext2D) {
  ctx.fillStyle = "rgba(0,0,0,0.7)";
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  ctx.fillStyle = "#ffd700";
  ctx.font = "bold 36px monospace";
  ctx.textAlign = "center";
  ctx.shadowColor = "#ff6600";
  ctx.shadowBlur = 20;
  ctx.fillText("🎉 通关！ 🎉", GAME_W / 2, 200);
  ctx.shadowBlur = 0;

  ctx.fillStyle = "#fff";
  ctx.font = "16px monospace";
  ctx.fillText("魔王已被击败！", GAME_W / 2, 250);
  ctx.fillText("光明重新照耀这片大陆。", GAME_W / 2, 275);

  ctx.fillStyle = "#4caf50";
  ctx.font = "14px monospace";
  ctx.fillText("你是一位真正的勇者！", GAME_W / 2, 310);

  const blink = Math.sin(Date.now() * 0.005) > 0;
  if (blink) {
    ctx.fillStyle = "#ffd700";
    ctx.font = "bold 14px monospace";
    ctx.fillText("按 Enter 重新开始", GAME_W / 2, 400);
  }
}

function drawGameOver(ctx: CanvasRenderingContext2D) {
  ctx.fillStyle = "rgba(0,0,0,0.8)";
  ctx.fillRect(0, 0, GAME_W, GAME_H);

  ctx.fillStyle = "#f44336";
  ctx.font = "bold 36px monospace";
  ctx.textAlign = "center";
  ctx.fillText("你倒下了……", GAME_W / 2, 220);

  ctx.fillStyle = "#ccc";
  ctx.font = "14px monospace";
  ctx.fillText("勇敢的冒险者，不要气馁！", GAME_W / 2, 270);
  ctx.fillText("从失败中汲取力量，再次出发吧。", GAME_W / 2, 295);

  const blink = Math.sin(Date.now() * 0.005) > 0;
  if (blink) {
    ctx.fillStyle = "#ffd700";
    ctx.font = "bold 14px monospace";
    ctx.fillText("按 Enter 重新开始", GAME_W / 2, 380);
  }
}
