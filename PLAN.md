# Test Case Generation Platform — 实施计划

> 版本 v1.1 | 更新 2026-06-30 | 全功能交付 + 生成任务可重连

## 当前状态
- **架构变更**: Project/Module → KnowledgeBase（知识库为核心，卡片式管理）
- **导航**: 统计看板 / 用例生成 / 审核标注 / 知识库
- **Prompt**: 融合六大测试技术（等价类/边界值/决策表/状态迁移/错误推测/组合测试）+ 覆盖率总结
- **用例格式**: 对齐用户模板（标题【模块-功能】、等级P0-P2、步骤字符串）

## 已完成功能清单
| 模块 | 功能 | 状态 |
|------|------|------|
| 知识库 | 创建/删除知识库，7种知识类型管理，Excel批量导入 | ✓ |
| 用例生成 | PRD上传解析 + 文本输入，知识库选择，AI生成+自我修正 | ✓ |
| 审核标注 | 按批次分组，逐条通过/拒绝，幻觉归因(5种)，Tab筛选 | ✓ |
| 统计分析 | 用例数/可用率/幻觉分布/批次统计，看板 | ✓ |
| 检索 | 中文n-gram关键词 + ChromaDB向量混合检索 | ✓ |
| 导出 | Excel下载(5列对齐用户模板)，按批次/按结果导出 | ✓ |
| 生成任务 | 后台任务(asyncio)+独立DB会话，SSE事件缓存重放，刷新/切页后断点续看，全局页头「生成中」入口 | ✓ |

## Context

基于 PRD（`.claude/prds/test-case-generation-platform.prd.md`）和设计方案（`DESIGN.md`），搭建一个面向中小QA团队的Web端平台，通过「知识库驱动 + LLM」将AI生成测试用例的可用率从 <30% 提升到 ≥85%。

**用户明确选择**: 前端用 Vue 3（非 React），LLM 用 OpenAI 兼容 API（当前接入智谱 GLM）。

---

## 技术栈定案

| 层 | 选型 | 
|---|---|
| 前端 | Vue 3 Composition API + `<script setup>` + Element Plus + Pinia + Vue Router + TypeScript |
| 构建 | Vite |
| 后端 | Python 3.10+ + FastAPI (async) |
| 数据库 | SQLite (dev) → PostgreSQL (prod) |
| 向量库 | ChromaDB 1.5.x（持久化 PersistentClient） |
| LLM | LLM API (OpenAI 兼容 /v1/chat/completions) |
| Embedding | Embedding API (OpenAI 兼容) (可切换 sentence-transformers 本地模式) |
| PRD解析 | pdfplumber + python-docx |
| Excel处理 | openpyxl |
| 部署 | Docker + docker-compose |

---

## 项目结构

```
/Users/wangjie/Desktop/test-case-generation-platform/
├── docker-compose.yml
├── .env.example
├── DESIGN.md              # (已有)
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── models/          # 10 SQLAlchemy models (UUID pk)
│       ├── schemas/         # Pydantic request/response
│       ├── routers/         # FastAPI route handlers
│       ├── services/        # 10 service modules
│       ├── vectorstore/     # ChromaDB client
│       └── utils/
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── vite.config.ts
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/          # Vue Router 4
│       ├── stores/          # 4 Pinia stores
│       ├── api/             # 7 Axios API modules
│       ├── types/           # TypeScript interfaces
│       ├── views/           # 7 page views
│       ├── components/      # layout/ knowledge/ generation/ review/ stats/ common/
│       └── utils/
```

---

## API 设计概要

所有接口前缀 `/api/v1`。前端通过 Axios client 统一处理响应和错误；FastAPI 当前直接返回业务对象。

### 当前已实现 API

#### 知识库
- `GET/POST /knowledge-bases`, `DELETE /knowledge-bases/{kb_id}`
- `GET/POST /knowledge-bases/{kb_id}/field-dicts`, `PUT/DELETE /knowledge-bases/{kb_id}/field-dicts/{item_id}`
- `GET/POST /knowledge-bases/{kb_id}/business-rules`, `PUT/DELETE /knowledge-bases/{kb_id}/business-rules/{item_id}`
- `GET/POST /knowledge-bases/{kb_id}/state-machines`, `PUT/DELETE /knowledge-bases/{kb_id}/state-machines/{item_id}`
- `GET/POST /knowledge-bases/{kb_id}/term-mappings`, `PUT/DELETE /knowledge-bases/{kb_id}/term-mappings/{item_id}`
- `GET /knowledge-bases/{kb_id}/prd-documents`, `POST /knowledge-bases/{kb_id}/prd-documents/upload`, `DELETE /knowledge-bases/{kb_id}/prd-documents/{id}`
- `GET/POST /knowledge-bases/{kb_id}/defect-records`, `PUT/DELETE /knowledge-bases/{kb_id}/defect-records/{id}`
- `POST /knowledge-bases/{kb_id}/import-defects`
- `POST /retrieve` — 请求体为 `{ query: string, kb_ids: string[] }`

#### 生成
- `POST /parse-prd` — 上传解析 PRD 文件
- `POST /generate` — 非流式生成并落库
- `POST /generate/stream` — SSE 流式生成（请求内直连，随请求结束而中断）
- `POST /generate/async` — 启动后台生成任务，立即返回 `{task_id, title, status, created_at}`；任务脱离请求运行，刷新/切走后仍继续
- `GET /generate/active` — 列出仍在运行的生成任务，供刷新后「继续查看」
- `GET /generate/stream/{task_id}` — 订阅指定任务的 SSE：先重放已缓存事件，再推送实时事件（支持断线重连续看）

#### 审核
- `GET /cases` — 最近 200 条用例，带审核状态
- `POST /cases/{id}/review` — 单条审核

#### 导出 & 统计
- `POST /cases/export` — 请求体为 `{ cases: [...] }`
- `GET /stats/overview`

### 计划 API
- 批量审核：`POST /cases/batch-review`
- 导出模板：`GET /export-templates`
- 按知识库或时间过滤用例：`GET /cases?kb_id=...&status=...`
- 生成前约束校验：`POST /generate/validate`
- 向量化状态查询：`GET /knowledge-bases/{kb_id}/vectorization-status`

---

## SSE 流式生成协议

```
event: progress  → {stage: "retrieving"|"constructing"|"generating"|"validating"|"correcting", message: "..."}
event: chunk     → {text: "(LLM 增量输出)"}
event: complete  → {cases: [...], knowledge_used: {...}, knowledge_matches: {...}, validation_warnings: [...]}
event: error     → {message: "..."}
```

**后台任务模式（`/generate/async` + `/generate/stream/{task_id}`）**：事件由后台任务产生并缓存在内存中。客户端订阅时，先按序重放已缓存事件实现「断点续看」，再续接实时事件；任务结束后服务端关闭流。前端在应用加载时通过 `/generate/active` 发现运行中的任务并自动重连。

---

## 分阶段实施 (预估 8-10 天)

### Phase 1: 骨架 + 知识库CRUD (已完成 ✓)

**已交付**（2026-06-13）：
- 后端 FastAPI + SQLite + 10个模型 + 完整 CRUD API
- 前端 Vue 3 + Element Plus + Pinia + 6种知识类型管理界面
- Docker部署方案（docker-compose + nginx反向代理）
- Python 3.10+ 虚拟环境 (.venv)
- PRD文档上传解析（PDF/Word/MD/TXT）
- 缺陷记录 Excel 导入（自动映射优先级）
- 模块级筛选（PRD/缺陷按模块过滤，为 Phase 3 模块级检索做准备）
- 文件上传进度显示
- 缺陷 Excel 模板下载

**技术要点**：
- 混合知识库：7种知识类型（字段字典/业务规则/状态机/术语映射/PRD文档/历史用例/缺陷记录）
- 文档解析：pdfplumber + python-docx
- 前端布局：纯 CSS flexbox（放弃 el-container 自动检测）
- 缺陷导入：自动列映射（标题/描述/优先级），忽略多余列

### Phase 2: 向量化 + 混合检索引擎 (已完成 ✓)

**目标**: PRD文档/缺陷记录向量化存储，关键词+语义混合检索可用。

**后端**:
- `vectorstore/chroma_client.py` — ChromaDB 封装（embedding + upsert + query）
- `services/retrieval_service.py` — 混合检索：关键词SQL匹配（结构化知识）+ ChromaDB语义检索（PRD/缺陷）
- `routers/knowledge.py` — 追加 `POST /retrieve` 混合检索接口
- `utils/text_utils.py` — 文本分块、实体提取
- Embedding: sentence-transformers 本地模型（`all-MiniLM-L6-v2`，免API调用）
- 上传时自动向量化：PRD文档/缺陷记录上传后异步分块 → embedding → 存入Chrom

**验证**: 输入查询文本 → 返回匹配的字段字典/业务规则/PRD片段/缺陷记录（带相关度排序）。

### Phase 3: LLM用例生成引擎 (已完成 ✓)

**目标**: 核心价值闭环——输入需求 → 知识库检索 → Prompt注入 → LLM流式生成 → 知识追溯。

**后端**:
- `services/parser_service.py` (pdfplumber/docx/md/txt 文本提取)
- `services/llm_service.py` (LLM 同步+SSE流式，httpx.AsyncClient)
- `services/prompt_service.py` (三层Prompt构造: 系统规则+知识上下文+用户需求)
- `services/validation_service.py` (字段存在性+状态可达性校验)
- `services/generator_service.py` (编排器: validate→retrieve→prompt→generate→postprocess)
- `schemas/generation.py` + `routers/generation.py`
- 后处理: 校验LLM输出的knowledge_refs ID是否真实存在

**前端**:
- `GenerationView.vue` (双栏: 输入+输出)
- `RequirementInput.vue` (文本输入) + `PrdUploader.vue` (拖拽上传PRD)
- `GenerationProgress.vue` (SSE状态展示) + `CaseResultTable.vue`
- `CaseDetailPanel.vue` + `KnowledgeRefTags.vue` (知识追溯标签)
- `stores/generation.ts` + `api/generation.ts`

**验证**: 上传PRD PDF → 知识库有关联数据 → 生成 → 流式进度 → 用例结果含知识引用标签。

### Phase 4: 审核闭环 + 导出 + 统计 (2-3天)

**目标**: 完整反馈闭环 —— 审核标注 → 幻觉归因 → 知识缺口建议 → Excel导出 → 统计看板。

**后端**:
- `schemas/review.py` + `routers/review.py` (逐条+批量审核)
- `routers/export.py` (Excel导出，兼容模板)
- `routers/stats.py` + `services/stats_service.py` (可用率/幻觉分布/趋势)

**前端**:
- `ReviewView.vue` + `ReviewCard.vue` + `RejectReasonForm.vue` + `BatchReviewBar.vue`
- `StatsView.vue` + 4个ECharts图表组件
- `KnowledgeCoverage.vue` (知识缺口建议面板)
- `stores/review.ts` + `api/review.ts` + `api/export.ts` + `api/stats.ts`

**验证**: 生成30条 → 审核全部 → 统计可用率83% → 幻觉分布正确 → 导出Excel → 缺口建议出现。

---

## 关键设计决策

1. **不用LangChain**: 检索链足够简单(关键词SQL + ChromaDB)，框架增加调试成本
2. **SSE非WebSocket**: 单向推送够用，nginx `proxy_buffering off` 即可
3. **UUID主键**: 安全、前端可生成乐观ID、未来多实例部署友好
4. **Knowledge ref校验**: LLM输出的引用ID后处理验证，不存在则标记警告
5. **Embedding先用云端 API**: 免本地模型下载，config支持切 sentence-transformers 本地模式
6. **Element Plus按需导入**: `unplugin-vue-components` + `unplugin-auto-import` 控制打包体积
7. **生成解耦后台任务**: 生成用 `asyncio.create_task` + 独立 DB 会话脱离请求，事件缓存在内存任务注册表中支持重连重放；前端状态提升到 Pinia store。代价是任务态为进程内内存，后端重启会丢失活动任务列表（已落库用例不受影响）

## 风险应对

| 风险 | 应对 |
|---|---|
| 知识库冷启动 | 允许仅含字段字典即可生成，展示警告提示质量预期 |
| LLM返回非JSON | regex fallback从markdown代码块提取; 失败则重试 |
| 大PRD超上下文 | 按Markdown标题分章节生成，聚合结果 |
| ChromaDB持久化问题 | Docker volume挂载; 提供备份/恢复接口 |

---

## 验证计划

1. **Phase 1**: docker-compose up → 创建项目/模块 → CRUD 4种知识类型
2. **Phase 2**: Excel导入 → `/retrieve` API 返回匹配结果
3. **Phase 3**: 上传PRD PDF → 生成用例 → 用例含知识引用标签 → 可用率人工验证
4. **Phase 4**: 审核30条 → 统计看板 → Excel导出 → 缺口建议
5. **端到端**: 导入真实团队Excel知识库 → 上传真实PRD → 审核 → 是否≥85%可用率
