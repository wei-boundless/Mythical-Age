# 改造计划快速参考指南

## 📋 6阶段改造概览

### 第1阶段: 状态管理（1-2周）
**目标**: 建立三层状态架构
- bootstrap/state.py (Session级全局状态)
- AppState Store (React桥梁)
- ToolUseContext (工具执行上下文)

**关键代码**:
```python
# bootstrap/state.py - 35行极简Store实现
class Store:
    def get_state(self): return self._state
    def set_state(self, updater): 
        old = self._state
        new = updater(old)
        if new is old: return
        self._state = new
        for listener in self._listeners: listener()
    def subscribe(self, listener): 
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)
```

**验收标准**:
- [ ] 无循环依赖
- [ ] 状态订阅机制完整
- [ ] 单元测试覆盖>90%

---

### 第2阶段: 工具系统统一化（3-4周）
**目标**: 统一Tool协议，支持完整生命周期

**核心接口**:
```python
class Tool(ABC):
    name: str
    input_schema: ToolInputSchema
    
    async def call(args, context) -> ToolResult
    async def validate_input(args) -> ValidationResult
    async def check_permissions(args, context) -> PermissionResult
    async def render_tool_use_message(args) -> str
```

**注册机制**:
- 编译期: feature flag (模拟)
- 加载期: 环境变量
- 运行时: is_enabled() 回调

**验收标准**:
- [ ] 所有工具实现统一Tool接口
- [ ] ToolRegistry支持三层过滤
- [ ] 工具UI渲染完整

---

### 第3阶段: Agent系统多源加载（5-6周）
**目标**: 支持内置/自定义/插件Agent的多源加载

**加载优先级**:
1. 内置Agent (代码)
2. 插件Agent (plugin/)
3. 自定义Agent (.claude/agents/)

**context隔离**:
```python
class AgentContext:
    available_tools: Dict[str, Tool]  # 隔离工具集
    app_state_snapshot: AppState      # 状态快照
    parent_context: Optional['AgentContext']  # 支持子Agent
```

**验收标准**:
- [ ] 三源加载完整
- [ ] 子Agent context隔离
- [ ] 去重策略清晰

---

### 第4阶段: 上下文管理优化（7-8周）
**目标**: Token预算 + 主动压缩

**Token预算分配**:
```python
TokenBudget:
  - system_prompt: 20%
  - tools: 15%
  - history: 50%
  - context: 10%
  - buffer: 5%
```

**压缩策略**:
1. 删除最早的非关键消息
2. 摘要关键消息段
3. 去重重复内容

**验收标准**:
- [ ] Token估算准确
- [ ] 压缩率达到目标
- [ ] 质量不下降

---

### 第5阶段: 权限系统多防线（9周）
**目标**: 四层权限检查

**检查顺序**:
1. 输入验证 (validate_input)
2. 权限规则 (check_permissions)
3. 资源限制 (rate_limit, quota)
4. 审计日志 (log)

**权限模式**:
- ALLOW: 所有操作允许
- ASK: 询问用户
- DENY: 拒绝危险操作
- STRICT: 严格模式

**验收标准**:
- [ ] 四层检查无遗漏
- [ ] 审计日志完整
- [ ] 权限拒绝有明确原因

---

### 第6阶段: 配置系统统一化（10周）
**目标**: 6层配置合并策略

**配置层级（优先级从低到高）**:
1. 代码默认值
2. /etc/claude/config.json
3. ~/.claude/config.json
4. .claude/config.json
5. 环境变量
6. 运行时传入

**示例**:
```python
ConfigManager:
  default_config      (1)
  ↓ merge
  system_config       (2)
  ↓ merge
  user_config         (3)
  ↓ merge
  project_config      (4)
  ↓ merge
  env_config          (5)
  ↓ merge
  runtime_config      (6)
  =
  final_config
```

**验收标准**:
- [ ] 6层都支持
- [ ] 合并逻辑清晰
- [ ] 优先级无歧义

---

## 🎯 改造重点项目

### 必做项（High Priority）
1. **bootstrap/state.py** - 极简Store实现
   - 代码量: ~200行
   - 影响: 全局
   - 优先级: 🔴 Critical

2. **工具系统统一化** - Tool接口+Registry
   - 代码量: ~400行
   - 影响: 所有工具
   - 优先级: 🔴 Critical

3. **Agent多源加载** - AgentDefinition+Registry
   - 代码量: ~300行
   - 影响: Agent系统
   - 优先级: 🔴 Critical

### 应做项（Medium Priority）
4. **上下文压缩** - TokenBudget+Compactor
   - 代码量: ~400行
   - 影响: 性能
   - 优先级: 🟠 High

5. **权限系统** - 多层防线
   - 代码量: ~250行
   - 影响: 安全
   - 优先级: 🟠 High

### 可做项（Low Priority）
6. **配置系统** - 6层合并
   - 代码量: ~150行
   - 影响: 可用性
   - 优先级: 🟡 Medium

---

## 📊 度量指标

### 代码质量
| 指标 | 当前 | 目标 | 工具 |
|------|------|------|------|
| 类型覆盖率 | 60% | >95% | mypy |
| 测试覆盖率 | 45% | >80% | coverage.py |
| 循环依赖 | 3个 | 0个 | import-linter |
| 代码重复率 | 25% | <10% | SonarQube |

### 性能指标
| 指标 | 当前 | 目标 | 改进 |
|------|------|------|------|
| API响应延迟 | 800ms | <650ms | -20% |
| Token消耗 | 基准 | 基准*0.7 | -30% |
| 启动时间 | 500ms | <325ms | -35% |

### 架构指标
| 指标 | 当前 | 目标 |
|------|------|------|
| DAG叶子节点 | 不清晰 | bootstrap + config + perm |
| 工具接口统一度 | 40% | 100% |
| 跨模块耦合度 | 高 | 低 |

---

## 🔧 通用工具与最佳实践

### 依赖检查
```bash
# 检查循环依赖
pip install import-linter
lint-imports --config=.importlinterrc

# 可视化依赖图
pipdeptree --graph-output svg
```

### 类型检查
```bash
pip install mypy
mypy backend/ --strict
```

### 测试框架
```bash
pip install pytest pytest-asyncio coverage
pytest --cov=backend tests/
coverage report --precision=2
```

### 代码风格
```bash
pip install black flake8
black backend/
flake8 backend/
```

---

## 🎓 学习资源

### 参考文档
1. **Claude Code源码** - 完整的参考实现
   - 状态管理: state/store.ts (35行)
   - 工具系统: Tool.ts (30+方法)
   - Agent系统: tools/AgentTool/
   - 上下文: context_management/

2. **本项目docs**
   - 第3篇: 状态管理
   - 第9篇: 工具系统
   - 第12篇: Agent系统
   - 第25篇: 架构模式总结

### 建议阅读顺序
1. 开发前: 通读改造计划和架构对比
2. 阶段1前: 阅读docs第3篇（状态管理）
3. 阶段2前: 阅读docs第9篇（工具系统）
4. 阶段3前: 阅读docs第12篇（Agent系统）
5. 阶段4前: 阅读docs第6篇（上下文管理）

---

## ✅ 验收清单

### 第1阶段验收
- [ ] bootstrap/state.py完成
- [ ] AppState Store完成
- [ ] 单元测试>90%覆盖
- [ ] 文档完成
- [ ] Code Review通过

### 第2阶段验收
- [ ] Tool接口定义完成
- [ ] ToolBuilder + Registry完成
- [ ] 所有现有工具迁移完成
- [ ] 三层过滤功能完整
- [ ] 集成测试通过

### 第3阶段验收
- [ ] AgentDefinition + AgentLoader完成
- [ ] AgentRegistry完成
- [ ] AgentContext隔离完成
- [ ] 多源加载测试通过
- [ ] 性能基准测试完成

### 第4阶段验收
- [ ] TokenBudget实现完成
- [ ] ContextCompactor实现完成
- [ ] 集成到context_controller
- [ ] 压缩效果验证
- [ ] Token估算准确度>95%

### 第5阶段验收
- [ ] 四层权限检查完成
- [ ] 审计日志完整
- [ ] 权限测试覆盖>90%
- [ ] 文档完成

### 第6阶段验收
- [ ] 6层配置加载完成
- [ ] 合并逻辑验证
- [ ] 配置优先级测试
- [ ] 迁移指南完成

---

## 🚀 快速开始

### Day 1: 环境准备
```bash
# 创建改造分支
git checkout -b refactor/framework-improvement

# 安装开发依赖
pip install mypy pytest pytest-asyncio coverage black flake8

# 创建改造目录结构
mkdir -p backend/state
mkdir -p backend/tools/
mkdir -p backend/graph/
mkdir -p tests/state tests/tools tests/graph
```

### Day 2-3: 第1阶段启动
```bash
# 1. 实现bootstrap/state.py
# 2. 实现AppState Store
# 3. 编写单元测试
pytest tests/state/ -v --cov=backend/state

# 4. Type checking
mypy backend/state/

# 5. Code review
```

---

## 📞 常见问题 Q&A

**Q: 改造期间能否同时发布功能？**
A: 可以。使用特性开关（feature flag）在改造分支中隔离新功能。

**Q: 如何处理向后兼容性？**
A: 1) 创建适配层包装旧接口 2) 逐步迁移模块 3) 写入迁移指南

**Q: 性能会不会下降？**
A: 不会。改造特意优化了上下文管理、Token预算和缓存，性能应该提升。

**Q: 学习成本大吗？**
A: 中等。7个设计模式都是可理解的，docs中有详细解释。

**Q: 何时能看到效果？**
A: 
- 第1阶段后: 代码质量提升
- 第2阶段后: 工具扩展更容易
- 第4阶段后: API响应变快
- 全部完成: 整体系统质量大幅提升

---

**开始日期**: [填入日期]
**预计完成**: [开始日期 + 10周]
**负责人**: [团队成员]
**审核人**: [技术lead]

祝改造顺利！🎉
