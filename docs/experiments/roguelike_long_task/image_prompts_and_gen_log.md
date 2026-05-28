# 生图提示词与资源生成说明

## 生成工具
- **工具**：AI 图像生成（内部 image_generate 工具）
- **输出格式**：PNG
- **尺寸**：32x32 像素（玩家角色），其他资产按需调整

## 资产生成记录

### 1. 玩家角色 (player.png)
- **提示词**：
  ```
  A top-down 2D pixel art character of a fantasy adventurer with a sword, 32x32 pixels, simple colors, suitable for a roguelike game, transparent background.
  ```
- **修订后提示词**（由生成工具自动优化）：
  ```
  Top-down 2D pixel art character sprite, fantasy adventurer holding a sword, 32x32 pixels, simple limited color palette, clean readable silhouette, roguelike game asset, transparent background, centered composition, no text, no border
  ```
- **生成结果**：✅ 成功
- **生成文件路径**：`frontend/public/souls/generated/chat-docs-experiments-roguelike_long_task-assets-player.png.png`
- **目标路径**：`docs/experiments/roguelike_long_task/assets/player.png`
- **大小**：786,053 字节（注意：32x32 pixel art 不应这么大，可能生成器未严格按尺寸生成，游戏中使用时需缩放）
- **集成方式**：在游戏代码中通过 Canvas 绘制时加载该图像并缩放至 32x32
- **备注**：文件扩展名出现双重 .png，需在引用时注意实际文件名。由于沙盒限制无法直接复制文件，游戏代码将尝试通过相对路径或运行时生成的 URL 引用。

### 2. 骷髅兵 (skeleton_warrior.png)
- **提示词**：
  ```
  A top-down 2D pixel art skeleton warrior with a rusty sword, 32x32 pixels, dark gray and bone white colors, simple limited palette, roguelike enemy sprite, transparent background.
  ```
- **生成结果**：⏳ 待生成（MVP 中使用 Canvas 绘制的彩色矩形替代）
- **状态**：待后续迭代生成

### 3. 骷髅弓箭手 (skeleton_archer.png)
- **提示词**：
  ```
  A top-down 2D pixel art skeleton archer with a bow, 32x32 pixels, dark green hood, simple limited palette, roguelike enemy sprite, transparent background.
  ```
- **生成结果**：⏳ 待生成（MVP 中使用 Canvas 绘制替代）

### 4. 暗影刺客 (shadow_assassin.png)
- **提示词**：
  ```
  A top-down 2D pixel art shadow assassin with dual daggers, 32x32 pixels, dark purple and black colors, semi-transparent cloak, roguelike enemy sprite, transparent background.
  ```
- **生成结果**：⏳ 待生成（MVP 中使用 Canvas 绘制替代）

### 5. Boss 角色
- **亡灵骑士 (knight_boss.png)**：
  ```
  A top-down 2D pixel art undead knight boss, 48x48 pixels, dark armor with glowing red eyes, heavy sword, roguelike boss sprite, transparent background.
  ```
- **大法师 (mage_boss.png)**：
  ```
  A top-down 2D pixel art dark mage boss, 48x48 pixels, purple robes with floating orbs, casting magic, roguelike boss sprite, transparent background.
  ```
- **石像鬼 (gargoyle_boss.png)**：
  ```
  A top-down 2D pixel art gargoyle boss, 48x48 pixels, stone gray wings spread, flying pose top-down view, roguelike boss sprite, transparent background.
  ```
- **火焰领主 (firelord_boss.png)**：
  ```
  A top-down 2D pixel art fire lord boss, 48x48 pixels, made of lava and flames, top-down view, roguelike boss sprite, transparent background.
  ```
- **黑暗君主 (darklord_boss.png)**：
  ```
  A top-down 2D pixel art dark lord final boss, 64x64 pixels, black armor with crown, two-handed sword, glowing aura, top-down view, roguelike boss sprite, transparent background.
  ```
- **生成结果**：⏳ 全部待生成（MVP 中使用 Canvas 绘制大型彩色矩形替代）

## 环境/瓦片资产
- 所有瓦片（地板、墙壁、门、宝箱、楼梯）在 MVP 中使用 Canvas 程序化绘制，后续可替换为生成位图。
- **地板提示词参考**：
  ```
  A top-down 2D pixel art stone dungeon floor tile, 32x32 pixels, gray and brown, seamless tiling, roguelike environment, simple palette.
  ```
- **墙壁提示词参考**：
  ```
  A top-down 2D pixel art dungeon wall tile, 32x32 pixels, dark gray stone bricks, roguelike environment, simple palette.
  ```

## 失败处理
- 若 AI 图像生成失败，回退方案为使用 Canvas 绘制几何形状（彩色矩形、圆形等），确保游戏可运行。
- 生成的图像文件若尺寸不符合预期，在代码中使用 drawImage 时指定目标宽高进行缩放。

## 备注
- MVP 阶段至少需要一个真实位图（玩家角色）用于验证图像加载功能。
- 当前已生成玩家角色位图，位于 `frontend/public/souls/generated/` 下。
- 由于沙盒环境限制，无法使用 shell 命令复制文件，游戏代码将通过路径引用或 data URI 方式加载图像。
