# 资产清单

## 视觉资产（已生成真实 PNG）

### 1. 玩家角色
- **文件名**：player.png
- **路径**：`docs/experiments/roguelike_long_task/assets/player.png`
- **描述**：俯视角冒险者，32x32 像素，像素艺术风格。
- **来源**：Python 脚本生成（原始二进制 PNG 编码）。
- **状态**：✅ 已生成。

### 2. 敌人角色

#### 骷髅战士
- **文件名**：skeleton_warrior.png
- **路径**：`docs/experiments/roguelike_long_task/assets/skeleton_warrior.png`
- **描述**：近战骷髅兵，32x32 像素。
- **来源**：Python 脚本生成。
- **状态**：✅ 已生成。

#### 骷髅弓箭手
- **文件名**：skeleton_archer.png
- **路径**：`docs/experiments/roguelike_long_task/assets/skeleton_archer.png`
- **描述**：远程骷髅弓箭手，32x32 像素。
- **来源**：Python 脚本生成。
- **状态**：✅ 已生成。

#### 暗影刺客
- **文件名**：shadow_assassin.png
- **路径**：`docs/experiments/roguelike_long_task/assets/shadow_assassin.png`
- **描述**：暗黑刺客，32x32 像素。
- **来源**：Python 脚本生成。
- **状态**：✅ 已生成。

### 3. Boss 角色
- **文件名**：boss.png
- **路径**：`docs/experiments/roguelike_long_task/assets/boss.png`
- **描述**：大型恶魔 Boss，64x64 像素。
- **来源**：Python 脚本生成。
- **状态**：✅ 已生成。

### 4. 环境瓦片
- **文件名**：tile_floor.png
- **路径**：`docs/experiments/roguelike_long_task/assets/tile_floor.png`
- **描述**：地板瓦片，32x32 像素，棋盘格样式。
- **来源**：Python 脚本生成。
- **状态**：✅ 已生成。

## 生成方式
所有 PNG 资产均由 Python 脚本 `generate_assets.py` 使用原始 PNG 编码（IHDR/IDAT/IEND 块、zlib 压缩）生成，不依赖任何第三方图像库。脚本位于 `docs/experiments/roguelike_long_task/generate_assets.py`。

## 接入方式
游戏 `index.html` 通过 `Image` 对象加载这些 PNG 文件，并使用 `ctx.drawImage()` 渲染到 Canvas 上。不存在任何 Canvas 临时绘制冒充真实资产的逻辑。

## 验证状态
- 文件存在性：✅ 所有 PNG 文件均存在于 assets/ 目录。
- 加载验证：✅ index.html 中使用 `Promise.all` 加载所有资产，失败时有明确错误提示。
