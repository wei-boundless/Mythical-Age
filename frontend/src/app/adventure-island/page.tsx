"use client";

// ============================================================
// 冒险岛传奇 2.0 — React 主组件（薄外壳）
// ============================================================

import { useEffect, useRef, useCallback, useState } from "react";
import { createInitialState, updateGame } from "./game-engine";
import { renderGame } from "./renderer";
import { buildMaps } from "./game-data";
import { preloadAllAssets, isAssetsReady } from "./assets";
import type { GameState } from "./types";
import type { SkillId } from "./types";
import { GAME_W, GAME_H, SKILLS } from "./config";

// ---- 技能热键映射 ----
const SKILL_KEY_MAP: Record<string, number> = {
  "1": 0,
  "2": 1,
  "3": 2,
  "4": 3,
  Digit1: 0,
  Digit2: 1,
  Digit3: 2,
  Digit4: 3,
};

export default function AdventureIslandPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<GameState | null>(null);
  const rafRef = useRef<number>(0);
  const [loading, setLoading] = useState(true);

  // ---- 开始/重启游戏 ----
  const startGame = useCallback(() => {
    const maps = buildMaps();
    stateRef.current = createInitialState(maps);
    // 从标题/胜利/失败画面进入实际游戏
    stateRef.current.phase = "playing";
    setLoading(false);
  }, []);

  // ---- 游戏主循环 ----
  const gameLoop = useCallback(() => {
    const state = stateRef.current;
    if (!state) return;

    updateGame(state);

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    renderGame(ctx, state);
    rafRef.current = requestAnimationFrame(gameLoop);
  }, []);

  // ---- 键盘输入 ----
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      const state = stateRef.current;
      if (!state) return;

      const key = e.key;

      // 标题 / 胜利 / 失败 → Enter 进入游戏；游戏中 → 触发 NPC 对话
      if (key === "Enter") {
        e.preventDefault();
        if (state.phase === "title" || state.phase === "victory" || state.phase === "game_over") {
          startGame();
          return;
        }
        // 游戏中和对话中：Enter 交给引擎（NPC 交互 / 对话推进）
        state.keys.add("Enter");
        return;
      }

      // 空格：跳跃 + 对话推进（引擎 L269 检查 "Space"，L706 检查 "Space"）
      if (key === " " || key === "Spacebar") {
        e.preventDefault();
        state.keys.add("Space");
        return;
      }

      // 技能热键 1-4
      const skillIdx = SKILL_KEY_MAP[e.code] ?? SKILL_KEY_MAP[key];
      if (skillIdx !== undefined) {
        e.preventDefault();
        const unlocked = SKILLS.filter((s) => state.player.level >= s.unlockLevel);
        const skill = unlocked[skillIdx];
        if (skill) {
          state.skillKeyJustPressed = skill.id as SkillId;
          setTimeout(() => {
            if (state && state.skillKeyJustPressed === skill.id) {
              state.skillKeyJustPressed = null;
            }
          }, 50);
        }
        return;
      }

      // 移动键 + 攻击键
      state.keys.add(key);
    },
    [startGame],
  );

  const handleKeyUp = useCallback((e: KeyboardEvent) => {
    const state = stateRef.current;
    if (!state) return;
    // 空格键 keydown 写入的是 "Space"，keyup 也要删 "Space"
    if (e.key === " " || e.key === "Spacebar") {
      state.keys.delete("Space");
    } else {
      state.keys.delete(e.key);
    }
  }, []);

  // ---- 初始化 ----
  useEffect(() => {
    let cancelled = false;

    (async () => {
      if (!isAssetsReady()) {
        const ok = await preloadAllAssets();
        if (!ok) {
          console.warn("[AdventureIsland] 部分图片加载失败，使用降级渲染");
        }
      }
      if (cancelled) return;

      const maps = buildMaps();
      stateRef.current = createInitialState(maps);
      setLoading(false);
    })();

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // ---- 启动/停止游戏循环 ----
  useEffect(() => {
    if (loading) return;

    rafRef.current = requestAnimationFrame(gameLoop);

    return () => {
      cancelAnimationFrame(rafRef.current);
    };
  }, [loading, gameLoop]);

  // ---- 全局键盘监听 ----
  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [handleKeyDown, handleKeyUp]);

  // ---- 防止页面滚动 ----
  useEffect(() => {
    const preventScroll = (e: KeyboardEvent) => {
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(e.key)) {
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", preventScroll);
    return () => window.removeEventListener("keydown", preventScroll);
  }, []);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        backgroundColor: "#000",
        color: "#fff",
        fontFamily: "sans-serif",
      }}
    >
      {loading ? (
        <div style={{ textAlign: "center" }}>
          <p style={{ fontSize: 18, marginBottom: 8 }}>🎮 正在加载素材...</p>
          <div
            style={{
              width: 200,
              height: 6,
              backgroundColor: "#333",
              borderRadius: 3,
              margin: "0 auto",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: "60%",
                height: "100%",
                backgroundColor: "#ffd700",
                animation: "loadingBar 1.5s infinite",
              }}
            />
          </div>
          <style>{`@keyframes loadingBar { 0% { width: 20%; } 50% { width: 80%; } 100% { width: 20%; } }`}</style>
        </div>
      ) : (
        <>
          <canvas
            ref={canvasRef}
            width={GAME_W}
            height={GAME_H}
            style={{
              border: "2px solid #333",
              borderRadius: 4,
              imageRendering: "pixelated",
              maxWidth: "100%",
              maxHeight: "90vh",
            }}
          />
          <div
            style={{
              marginTop: 8,
              fontSize: 12,
              color: "#666",
              textAlign: "center",
              maxWidth: 480,
            }}
          >
            操作：← → 移动 | ↑ / 空格 跳跃 | Z / J 攻击 | 1-4 技能 | 空格 对话
          </div>
        </>
      )}
    </div>
  );
}
