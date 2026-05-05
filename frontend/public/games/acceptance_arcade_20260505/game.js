/* === 霓虹躲避 — 游戏逻辑 === */

(function () {
  /* ---- DOM 引用 ---- */
  const canvas = document.getElementById('gameCanvas');
  const ctx = canvas.getContext('2d');
  const scoreDisplay = document.getElementById('scoreDisplay');
  const btnStart = document.getElementById('btnStart');
  const btnRestart = document.getElementById('btnRestart');

  const W = canvas.width;   // 480
  const H = canvas.height;  // 640

  /* ---- 游戏状态 ---- */
  const STATE = { START: 'start', PLAYING: 'playing', OVER: 'over' };
  let gameState = STATE.START;

  /* ---- 玩家 ---- */
  const PLAYER_SIZE = 32;
  const PLAYER_SPEED = 320; // px/s

  let player = {
    x: W / 2 - PLAYER_SIZE / 2,
    y: H - 80,
    w: PLAYER_SIZE,
    h: PLAYER_SIZE,
  };

  /* ---- 障碍物 ---- */
  const BASE_OBSTACLE_SPEED = 220;   // px/s
  const SPEED_SCALE = 4;             // 每分加速量
  const BASE_SPAWN_MS = 750;         // 初始生成间隔
  const MIN_SPAWN_MS = 280;          // 最小生成间隔
  const SPAWN_SHRINK_PER_POINT = 4;  // 每分缩短量

  let obstacles = [];
  let spawnTimer = 0;

  /* ---- 得分 ---- */
  let score = 0;

  /* ---- 输入 ---- */
  const keys = { ArrowLeft: false, ArrowRight: false, ArrowUp: false, ArrowDown: false };

  /* ---- 时间 ---- */
  let lastTime = 0;

  /* ---- 辅助函数 ---- */
  function rand(min, max) {
    return Math.random() * (max - min) + min;
  }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function currentObstacleSpeed() {
    return BASE_OBSTACLE_SPEED + score * SPEED_SCALE;
  }

  function currentSpawnInterval() {
    return Math.max(MIN_SPAWN_MS, BASE_SPAWN_MS - score * SPAWN_SHRINK_PER_POINT);
  }

  /* ---- 重置 ---- */
  function resetGame() {
    player.x = W / 2 - PLAYER_SIZE / 2;
    player.y = H - 80;
    obstacles = [];
    spawnTimer = 0;
    score = 0;
    updateScoreDisplay();
  }

  function updateScoreDisplay() {
    scoreDisplay.textContent = score;
  }

  /* ---- 碰撞检测 (AABB) ---- */
  function rectsCollide(a, b) {
    return (
      a.x < b.x + b.w &&
      a.x + a.w > b.x &&
      a.y < b.y + b.h &&
      a.y + a.h > b.y
    );
  }

  /* ---- 生成障碍物 ---- */
  function spawnObstacle() {
    const w = rand(44, 120);
    const h = rand(14, 26);
    obstacles.push({
      x: rand(0, W - w),
      y: -h,
      w: w,
      h: h,
    });
  }

  /* ---- 更新逻辑 ---- */
  function update(dt) {
    if (gameState !== STATE.PLAYING) return;

    // 秒数，限制最大步进防止跳帧异常
    const sec = Math.min(dt, 0.1);

    // --- 玩家移动 ---
    let dx = 0, dy = 0;
    if (keys.ArrowLeft)  dx -= 1;
    if (keys.ArrowRight) dx += 1;
    if (keys.ArrowUp)    dy -= 1;
    if (keys.ArrowDown)  dy += 1;

    // 归一化斜向速度
    if (dx !== 0 && dy !== 0) {
      const inv = 1 / Math.SQRT2;
      dx *= inv;
      dy *= inv;
    }

    player.x += dx * PLAYER_SPEED * sec;
    player.y += dy * PLAYER_SPEED * sec;
    player.x = clamp(player.x, 0, W - player.w);
    player.y = clamp(player.y, 0, H - player.h);

    // --- 障碍物移动 ---
    const speed = currentObstacleSpeed();
    for (let i = obstacles.length - 1; i >= 0; i--) {
      obstacles[i].y += speed * sec;
    }

    // --- 碰撞检测 ---
    for (const obs of obstacles) {
      if (rectsCollide(player, obs)) {
        gameState = STATE.OVER;
        return;
      }
    }

    // --- 移除屏幕外的障碍物 & 加分 ---
    for (let i = obstacles.length - 1; i >= 0; i--) {
      if (obstacles[i].y > H) {
        obstacles.splice(i, 1);
        score += 1;
        updateScoreDisplay();
      }
    }

    // --- 生成新障碍物 ---
    spawnTimer += dt * 1000;
    const interval = currentSpawnInterval();
    while (spawnTimer >= interval) {
      spawnTimer -= interval;
      spawnObstacle();
    }
  }

  /* ---- 绘制 ---- */
  function drawGrid() {
    ctx.strokeStyle = '#1a1a2e';
    ctx.lineWidth = 1;
    const step = 40;
    for (let x = step; x < W; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
      ctx.stroke();
    }
    for (let y = step; y < H; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      ctx.stroke();
    }
  }

  function drawGlowRect(x, y, w, h, color, glowColor, glowRadius) {
    // 光晕层
    ctx.fillStyle = glowColor;
    ctx.shadowColor = glowColor;
    ctx.shadowBlur = glowRadius;
    ctx.fillRect(x, y, w, h);
    ctx.shadowBlur = 0;

    // 主体
    ctx.fillStyle = color;
    ctx.fillRect(x, y, w, h);
  }

  function drawPlayer() {
    const { x, y, w, h } = player;
    // 外光晕
    ctx.fillStyle = '#00f0ff33';
    ctx.shadowColor = '#00f0ff';
    ctx.shadowBlur = 18;
    ctx.fillRect(x, y, w, h);
    ctx.shadowBlur = 0;

    // 主体
    ctx.fillStyle = '#00e5f0';
    ctx.fillRect(x, y, w, h);

    // 内高光
    ctx.fillStyle = '#80f8ff';
    ctx.fillRect(x + 4, y + 4, w - 8, h - 8);
  }

  function drawObstacles() {
    for (const obs of obstacles) {
      const { x, y, w, h } = obs;
      // 外光晕
      ctx.fillStyle = '#ff6ec733';
      ctx.shadowColor = '#ff6ec7';
      ctx.shadowBlur = 14;
      ctx.fillRect(x, y, w, h);
      ctx.shadowBlur = 0;

      // 主体
      ctx.fillStyle = '#ff4da6';
      ctx.fillRect(x, y, w, h);

      // 高光边
      ctx.fillStyle = '#ff8fd3';
      ctx.fillRect(x, y, w, h > 4 ? 3 : 1);
    }
  }

  function drawOverlay(title, sub) {
    // 半透明遮罩
    ctx.fillStyle = 'rgba(6, 6, 18, 0.78)';
    ctx.fillRect(0, 0, W, H);

    // 标题
    ctx.fillStyle = '#00f0ff';
    ctx.font = 'bold 36px "Courier New", monospace';
    ctx.textAlign = 'center';
    ctx.shadowColor = '#00f0ff';
    ctx.shadowBlur = 20;
    ctx.fillText(title, W / 2, H / 2 - 20);
    ctx.shadowBlur = 0;

    // 副标题
    if (sub) {
      ctx.fillStyle = '#ccc';
      ctx.font = '16px "Courier New", monospace';
      ctx.fillText(sub, W / 2, H / 2 + 28);
    }

    ctx.textAlign = 'start';
  }

  function drawHUD() {
    // 右上角得分
    ctx.fillStyle = '#ffffff66';
    ctx.font = '14px "Courier New", monospace';
    ctx.textAlign = 'right';
    ctx.fillText('SCORE ' + score, W - 16, 28);
    ctx.textAlign = 'start';
  }

  function render() {
    // 清屏
    ctx.clearRect(0, 0, W, H);

    // 背景网格
    drawGrid();

    if (gameState === STATE.START) {
      // 绘制静态玩家
      drawPlayer();
      drawOverlay('霓虹躲避', '点击「开始游戏」');
    } else if (gameState === STATE.PLAYING) {
      drawObstacles();
      drawPlayer();
      drawHUD();
    } else if (gameState === STATE.OVER) {
      drawObstacles();
      drawPlayer();
      drawHUD();
      drawOverlay('游戏结束', '得分 ' + score + ' — 点击「重新开始」');
    }
  }

  /* ---- 游戏循环 ---- */
  function gameLoop(timestamp) {
    if (lastTime === 0) lastTime = timestamp;
    const dt = (timestamp - lastTime) / 1000;
    lastTime = timestamp;

    update(dt);
    render();

    requestAnimationFrame(gameLoop);
  }

  /* ---- 事件 ---- */
  window.addEventListener('keydown', function (e) {
    if (e.key in keys) {
      e.preventDefault();
      keys[e.key] = true;
    }
  });

  window.addEventListener('keyup', function (e) {
    if (e.key in keys) {
      e.preventDefault();
      keys[e.key] = false;
    }
  });

  btnStart.addEventListener('click', function () {
    if (gameState === STATE.PLAYING) return;
    resetGame();
    gameState = STATE.PLAYING;
    lastTime = 0; // 重置时间避免 dt 跳变
    btnStart.textContent = '游戏中…';
  });

  btnRestart.addEventListener('click', function () {
    resetGame();
    gameState = STATE.PLAYING;
    lastTime = 0;
    btnStart.textContent = '开始游戏';
  });

  /* ---- 启动 ---- */
  // 初始渲染一帧
  render();
  requestAnimationFrame(gameLoop);
})();
