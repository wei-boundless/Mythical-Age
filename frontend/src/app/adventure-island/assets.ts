// ============================================================
// 冒险岛传奇 2.0 — 图片资源预加载器
// ============================================================

import type { MonsterKind, SceneKind } from "./types";

const ASSET_BASE = "/api/image-assets/files";

// 资源文件名映射
const ASSET_FILES: Record<string, string> = {
  player: `${ASSET_BASE}/game-player-hero.png`,
  slime: `${ASSET_BASE}/game-monster-slime.png`,
  mushroom: `${ASSET_BASE}/game-monster-mushroom.png`,
  skeleton: `${ASSET_BASE}/game-monster-skeleton.png`,
  gargoyle: `${ASSET_BASE}/game-monster-gargoyle.png`,
  dark_knight: `${ASSET_BASE}/game-monster-dark-knight.png`,
  boss: `${ASSET_BASE}/game-boss-demon-king.png`,
  npc: `${ASSET_BASE}/game-npc-elder.png`,
  forest: `${ASSET_BASE}/game-map-forest.png`,
  cave: `${ASSET_BASE}/game-map-cave.png`,
  castle: `${ASSET_BASE}/game-map-castle.png`,
};

// 全局图片缓存
const imageCache = new Map<string, HTMLImageElement>();

// 是否全部加载完毕
let allLoaded = false;
let loadPromise: Promise<boolean> | null = null;

/** 获取怪物对应的资源 key */
export function monsterAssetKey(kind: MonsterKind): string {
  if (kind === "boss") return "boss";
  return kind; // slime, mushroom, skeleton, gargoyle, dark_knight
}

/** 获取场景对应的资源 key */
export function sceneAssetKey(scene: SceneKind): string {
  return scene; // forest, cave, castle
}

/** 获取已缓存的图片（调用前确保已预加载） */
export function getImage(key: string): HTMLImageElement | undefined {
  return imageCache.get(key);
}

/** 预加载全部图片资源 */
export function preloadAllAssets(): Promise<boolean> {
  if (allLoaded) return Promise.resolve(true);
  if (loadPromise) return loadPromise;

  const entries = Object.entries(ASSET_FILES);
  const promises = entries.map(([key, url]) => {
    return new Promise<boolean>((resolve) => {
      const img = new Image();
      img.onload = () => {
        imageCache.set(key, img);
        resolve(true);
      };
      img.onerror = () => {
        console.warn(`[AdventureIsland] 图片加载失败: ${key} (${url})`);
        resolve(false); // 不阻断游戏，降级到手绘
      };
      img.src = url;
    });
  });

  loadPromise = Promise.all(promises).then((results) => {
    const loadedCount = results.filter(Boolean).length;
    allLoaded = loadedCount === entries.length;
    console.log(
      `[AdventureIsland] 图片预加载完成: ${loadedCount}/${entries.length} 张`
    );
    return allLoaded;
  });

  return loadPromise;
}

/** 是否所有图片已加载 */
export function isAssetsReady(): boolean {
  return allLoaded;
}

/** 重置（用于测试或重新开始） */
export function resetAssetCache(): void {
  imageCache.clear();
  allLoaded = false;
  loadPromise = null;
}
