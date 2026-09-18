# Test Case Generation Platform — 实施计划

> 版本 v2.8 | 更新 2026-09-18 | 多用户化首轮代码评审安全修复（设计见 DESIGN.md v0.33，分支 fix/auth-review-p0-p1，**已改未提交**）：① 零可见知识库检索 fail-open 越权——空 kb_ids 被当成不过滤致全库检索，改为空集合零结果（SQL 空 IN + Chroma 入口短路）、任务入口去掉 `or None`；② 密钥启动 fail-fast——JWT 密钥 ≥32 字符、ADMIN 账号非空/≥6 位、Fernet 密钥启动试构造校验（空串实测可签发 JWT）；③ CryptoError 五处转 400、损坏的 docx/pdf/xlsx 转 400；④ 登出改整页跳转（销毁 Pinia store、中止 SSE，防同标签换号残留）；⑤ 修最后管理员判定误拦普通用户 no-op；⑥ 用户名/知识库名纯空白 422。验证：16 项一次性脚本断言 + vue-tsc 通过。
>
> 版本 v2.7 | 更新 2026-09-18 | 多用户化与服务器部署收口：登录/JWT(12h)/用户管理（建号·角色·停用·重置密码，只停用不删除）、个人大模型凭据（Fernet 加密、连通测试、清除）+ 系统兜底模型两级解析（个人 key 失败不自动降级）、ContextVar+任务快照把凭据透传到后台流水线、知识库个人/团队可见性与 can_manage、批次/用例/SSE/few-shot 按 owner 私有、统计「我的/团队」两视图（by_model/by_user，无批次明细）、Alembic 0003 迁移（users 两表+归属列+partial unique index+老数据归 admin）、compose 端口收敛与 healthcheck、网关 TLS/SSE 反代示例、SQLite WAL、env_file 密钥注入与在线备份。对应 PR #70–#73/#76/#77，设计见 DESIGN.md v0.32
>
> 版本 v2.6 | 更新 2026-08-18 | 死代码清理（删 `POST /retrieve`、`GET /cases` 无 `batch_id` 分支、前端 4 个无引用文件与未用的 echarts 依赖、`complete` 事件里没人消费的 `validation_warnings`、`excel_service` 三个未接路由的导入函数、孤儿 schema `KnowledgeBaseUpdate`）+ `generate_stream` 拆分（238 行 → 64 行编排器，模块并行改用通用 `_parallel_agents`，事件契约零变化）+ 修生成失败的**原因到不了用户**（`_generate_one_batch` 提前滤掉了 error 占位，使 `generate_stream` 里取原因那段成了死代码；现在「只吐思考」「模型判定无可测功能点」都会把可行动原因透传到前端）+ 回归测试 61 → 108 项（新增 LLM 输出解析 36 + 生成流水线事件序列 11）

## 当前状态
- **架构变更**: Project/Module → KnowledgeBase（知识库为核心，卡片式管理）
- **导航**: 统计看板(首页) / 用例生成 / 审核标注 / 知识库 / 设置 / 用户管理(仅管理员)；独立登录页
- **多用户**: 登录后使用（JWT 12h）；知识库分团队/个人，批次与统计按人隔离；个人大模型凭据 + 系统兜底两级
- **Prompt**: 融合六大测试技术（等价类/边界值/决策表/状态迁移/错误推测/组合测试）+ 覆盖率总结
- **用例格式**: 对齐用户模板（标题【模块-功能】、等级P0-P2、步骤字符串）
- **PRD 导入**: 支持本地文件上传（PDF/Word/MD/TXT） + 飞书链接一键导入（Wiki/docx/旧 doc，含表格结构化）
- **部署**: Docker Compose（后端不直暴端口、前端绑回环）+ 公司网关 TLS 反代，SQLite WAL，详见 README

## 已完成功能清单
| 模块           | 功能                                                                                       | 状态 |
| -------------- | ------------------------------------------------------------------------------------------ | ---- |
| 知识库         | 创建/编辑（名称+描述）/删除知识库，7种知识类型管理，Excel批量导入                           | ✓    |
| 用例生成       | PRD上传解析 + 文本输入，知识库选择，AI生成+评审补充                                        | ✓    |
| 审核标注       | 按批次分组，逐条通过/拒绝，幻觉归因(5种)，Tab筛选                                          | ✓    |
| 统计分析       | 用例数/可用率/幻觉分布/批次统计，看板                                                      | ✓    |
| 检索           | 中文n-gram关键词 + ChromaDB向量混合检索                                                    | ✓    |
| 导出           | Excel下载(5列对齐用户模板)，按批次/按结果导出                                              | ✓    |
| 生成任务       | 后台任务(asyncio)+独立DB会话，SSE事件缓存重放，刷新/切页后断点续看，全局页头「生成中」入口 | ✓    |
| 评审-删除-补充 | 生成后 LLM 以测试专家身份判定哪些该删（只列待删，未列出即保留），定向补充缺口，不再整批改写。评审按标题【】模块路径分组并行：顶层一律先分，之后**由条数驱动**——只有超 `LLM_REVIEW_BATCH_SIZE` 的组才逐级下钻，装得下的整组保留（不写死深度：路径有几级取决于 PRD 是否含平台层）；响应撞满 max_tokens 时检测截断并抢救已判完的部分，前端小结标注「仅部分判定生效」 | ✓    |
| 并行生成       | store 改为多任务 Map，可同时发起多个生成互不阻塞；前端任务列表可切换查看                   | ✓    |
| 模块并行+分区流式 | 大需求按模块并发生成（并发上限+错峰防限流），模块内真流式，前端按 agent 卡片分区展示各自的流（可多开，完成后换用例列表）；评审/补充也按模块并发 + agent 卡片流式（实时看到保留/删除判断与补充过程） | ✓    |
| 登录与账号     | 用户名/密码登录，bcrypt 哈希 + HS256 JWT（12h）；除登录与 /api/health 外全接口鉴权；401 自动跳登录；管理员建号/角色/停用/重置密码（只停用不删除，不能操作自己、至少留一个活跃管理员） | ✓    |
| 个人LLM凭据    | 「设置」页配置 OpenAI 兼容三件套，api_key Fernet 加密存储、只回掩码；支持连通测试与清除。**两级解析**：个人凭据优先，否则系统兜底模型，皆无则引导配置；个人 key 失败不自动降级 | ✓    |
| 数据归属       | 知识库分团队（全员可见可引用、创建者/管理员可改删）与个人（仅本人，管理员也不可见）；批次/用例/评审/活动任务/SSE 全部按 owner 私有（越权 task_id 返 404）；历史 few-shot 向量按 owner 过滤；删库显式级联（6 张子表 + 2 个 Chroma 集合 + 用例置 kb_id=NULL） | ✓    |
| 统计两视图     | 「我的/团队」切换：我的按 owner 全量指标并拆系统兜底消耗；团队给全员汇总 + 按模型/按成员消耗，不含他人批次明细 | ✓    |
| 部署收口       | compose 后端仅 expose、前端绑 127.0.0.1:3000，env_file 注入密钥，.dockerignore 防 .env/data 入镜像，restart+双向 healthcheck；网关 TLS 反代 SSE 示例（deploy/）；SQLite WAL；在线备份与密钥分离 | ✓    |
| 需求补全       | POST /generate/clarify，LLM 结合知识库补全简略需求为结构化 Markdown，可编辑确认            | ✓    |
| 429 处理       | 限额/限流不重试直接报错，5xx 服务端抖动保留指数退避重试                                    | ✓    |
| 死代码清理     | 删除无人调用的 POST /generate、/generate/stream、GenerateResponse 及相关非流式函数         | ✓    |
| 用例编辑       | 审核阶段可微调 title/precondition/steps/expected_result，只改内容不碰 review 状态（保留原 reject_reason 信号），加 `edited` 标记 | ✓    |
| 用例顺序       | 规则集中在 `app/utils/case_ordering.py`（生成流程与运维脚本共用）：顶层模块按需求切割顺序成块 → 块内按标题层级路径聚合到子功能级 → 同路径段内按正文共同前缀（≥3 字）单向前移聚合到功能点级。生成时自动排好，无需手工干预；**只挪补充用例、原有用例位置一律不动**——路径层（`place_by_path`）与功能点层（`forward_place`）都受 `is_movable` 约束，锁定用例只作被吸附的锚点；路径层的吸附力 `_affinity` 会压低待插用例的后代路径，避免总纲级补充被自己的细则隔开；`scripts/resort_batch.py` 补排历史批次时不传该约束，走全量排序 | ✓    |
| 标题粒度约束   | 生成 prompt 硬要求前缀最后一级是功能点、不能停在页面/区块名（给正反例 + 判断标准），补充 prompt 要求复用已有功能点完整前缀；路径自带功能点后字面前缀启发式退化为兜底 | ✓    |
| 补充用例标识   | 评审后定向补充的用例落库带 `origin='supplement'`，前端在生成结果/历史批次/审核页显示「补充」标签；加列前的历史用例为 NULL、不显示标签（阶段信息已丢失，不反推） | ✓    |
| 导出范围       | 历史批次「下载 Excel」为 split-button，可选「全部用例 / 仅通过用例」（后者筛 `review.status === 'approved'`，与是否编辑过无关）；生成页用例未入库故不提供该选项 | ✓    |
| Token 用量统计 | `llm_usage` 流水表（一行 = 一次 chat/completions 请求）。统计分析页显示今日/本周（周一起）/累计消耗、思考 token 占比、按阶段（需求补全/模块拆分/用例生成/评审/补充）拆分条形图；审核页批次卡显示该批消耗。采集靠 `stream_options.include_usage`，`LLM_COLLECT_TOKEN_USAGE=False` 可一键关。归属用 contextvars（`task_service._run` 顶层装一次 collector 覆盖全部并发 worker，各 worker 的 stage 互不串台），失败路径也记账，统计写库失败不连坐生成结果。上线前的历史批次无流水，`tokens` 返回 `null` 而非 0（前端不显示，避免被读成「没花钱」） | ✓    |

## Context

基于 PRD（`.claude/prds/test-case-generation-platform.prd.md`）和设计方案（`DESIGN.md`），搭建一个面向中小QA团队的Web端平台，通过「知识库驱动 + LLM」将AI生成测试用例的可用率从 <30% 提升到 ≥85%。

**用户明确选择**: 前端用 Vue 3（非 React），LLM 用 OpenAI 兼容 API（当前接入智谱 GLM）。

---

## 技术栈定案

| 层        | 选型                                                                                      |
| --------- | ----------------------------------------------------------------------------------------- |
| 前端      | Vue 3 Composition API + `<script setup>` + Element Plus + Pinia + Vue Router + TypeScript |
| 构建      | Vite                                                                                      |
| 后端      | Python 3.10+ + FastAPI (async)                                                            |
| 数据库    | SQLite (dev) → PostgreSQL (prod)                                                          |
| 向量库    | ChromaDB 1.5.x（持久化 PersistentClient）                                                 |
| LLM       | LLM API (OpenAI 兼容 /v1/chat/completions)                                                |
| Embedding | Embedding API (OpenAI 兼容) (可切换 sentence-transformers 本地模式)                       |
| PRD解析   | pdfplumber + python-docx                                                                  |
| Excel处理 | openpyxl                                                                                  |
| 认证/加密 | PyJWT（HS256, 12h）+ bcrypt（cost 12）+ cryptography（Fernet 加密个人 API Key）           |
| 部署      | Docker Compose + 公司网关 TLS 反代（后端不直暴端口、SQLite WAL、在线备份）                 |

---

## 项目结构

```
<repo-root>/
├── docker-compose.yml
├── deploy/                  # 网关反代示例：nginx-gateway.example.conf（TLS + SSE 长连接参数）
├── DESIGN.md
├── PLAN.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example         # 运行时配置模板（复制为 .env；compose 经 env_file 注入，不进镜像）
│   ├── alembic/             # 迁移：0001 初始 / 0002 老库补列 / 0003 多用户（users 两表+归属+回填）
│   ├── scripts/             # 运维脚本（手工执行）：delete_batch / backfill_case_priority / reindex_vectors / resort_batch / clean_expected_step_no
│   └── app/
│       ├── main.py          # lifespan：run_migrations + ensure_admin；router 挂载与登录依赖
│       ├── config.py        # Settings（ADMIN/JWT/Fernet 四项必填，缺失启动失败）
│       ├── database.py      # 异步 engine；SQLite WAL/synchronous=NORMAL/busy_timeout；run_migrations
│       ├── models/          # 11 个模型文件 / 12 张表（含 user.py: User, UserLlmConfig）
│       ├── schemas/         # Pydantic request/response（含 user.py / llm_config.py）
│       ├── routers/         # auth / admin_users / llm_config / generation / knowledge（+ deps.py 鉴权依赖）
│       ├── services/        # 21 个：auth/crypto/access/llm_credential + 知识库/生成流水线/检索/解析…
│       ├── vectorstore/     # ChromaDB client（search 支持 where_extra；delete_by_kb/source）
│       └── utils/           # 纯逻辑：case_grouping / case_ordering / llm_parsing /
│                            #   token_usage / llm_credentials（ContextVar）/ text_utils / docx_blocks
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf           # /api 反代 backend；SSE 参数（HTTP/1.1、清 Connection、3600s、关缓冲）
│   ├── vite.config.ts
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/          # 路由守卫：无 token 跳 /login、requiresAdmin、/stats→/ 重定向
│       ├── stores/          # 3 Pinia stores (auth / generation / knowledge)
│       ├── api/             # 6 个：client(401拦截) / auth / admin / llmConfig / generation / knowledge
│       ├── types/           # auth / llmConfig / project / knowledge / testCase
│       ├── views/           # 8 个：Login / Stats(首页) / Generation / Review / Knowledge /
│       │                    #       Settings(凭据+改密) / Users(管理员) / NotFound
│       ├── components/      # layout/ knowledge/(含共享只读) generation/ review/
│       ├── composables/     # useBatchList / useBatchReview / useDurationTimer 等 6 个
│       └── utils/           # authToken(tcg_token) / formatTokens / priority / renderSteps / saveBlob
```

---

## API 设计概要

所有接口前缀 `/api/v1`。前端通过 Axios client 统一处理响应和错误；FastAPI 当前直接返回业务对象。

**鉴权（v0.32）**：除 `POST /auth/login` 以及 `/api/v1` 前缀之外的 `GET /api/health`，全部接口要求 `Authorization: Bearer <JWT>`（登录后 12h 有效）；未登录/过期/停用返 401，前端拦截后整页跳 `/login?redirect=...`。SSE 用原生 fetch，需手动补同一个头。无 CORS（前后端同源）。

### 当前已实现 API

#### 认证与账号
- `POST /auth/login` — 用户名/密码换 token；成功返 `{access_token, token_type:"bearer", user}`；用户不存在与密码错统一 401，已停用账号返 403
- `GET /auth/me` — 当前用户 `{id, username, display_name, is_admin, is_active, created_at}`
- `POST /auth/change-password` — 旧密码校验 + 新密码（≥6 位）
- `GET /admin/users` / `POST /admin/users` — 管理员列用户 / 建号（用户名、显示名、初始密码、is_admin）；重名 400
- `PATCH /admin/users/{id}` — 改显示名/角色/停用（仅这三字段可选）；不能停用或降级自己、至少保留一个活跃 admin，违反返 400
- `POST /admin/users/{id}/reset-password` — 管理员重置密码
- （无删除用户接口；账号生命周期只有启用/停用）

#### 个人大模型凭据
- `GET /llm-config` — `{configured, base_url, model, api_key_masked, updated_at, fallback_available, fallback_model}`，不回传明文/密文
- `PUT /llm-config` — upsert 三件套；api_key 传空=不改（首次必填），base_url 末尾 `/` 归一
- `DELETE /llm-config` — 清除个人配置，之后回落到系统兜底模型
- `POST /llm-config/test` — 连通测试：body 带表单值则按表单（缺项回落已存值），空 body 测当前生效配置；max_tokens=8、20s 超时，返 `{ok, latency_ms, message}`
- 解析规则：个人凭据 → 系统兜底（`LLM_API_KEY/BASE_URL/MODEL`）→ 皆无时 clarify/async 入口 400 不建任务；个人 key 调用失败不自动降级

#### 知识库
- `GET/POST /knowledge-bases`, `PUT /knowledge-bases/{kb_id}`, `DELETE /knowledge-bases/{kb_id}`
  - 创建/更新可带 `visibility: team|personal`（默认 team）；列表只含团队库 + 本人个人库，响应带 `owner_id/visibility/owner_name/can_manage`
  - 团队库全员可读可引用，改/删限创建者与管理员（403）；不可见 id 读返 404、在 kb_ids 入参里越界返 400；重名按 partial unique 约束返 400
  - 删除做显式级联（SQLite 未开 FK）：6 张子表 + prd/defect 两向量集合按 kb 清，关联 test_cases 置 kb_id=NULL
- `GET/POST /knowledge-bases/{kb_id}/field-dicts`, `PUT/DELETE /knowledge-bases/{kb_id}/field-dicts/{item_id}`
- `GET/POST /knowledge-bases/{kb_id}/business-rules`, `PUT/DELETE /knowledge-bases/{kb_id}/business-rules/{item_id}`
- `GET/POST /knowledge-bases/{kb_id}/state-machines`, `PUT/DELETE /knowledge-bases/{kb_id}/state-machines/{item_id}`
- `GET/POST /knowledge-bases/{kb_id}/term-mappings`, `PUT/DELETE /knowledge-bases/{kb_id}/term-mappings/{item_id}`
- `GET /knowledge-bases/{kb_id}/prd-documents`, `POST /knowledge-bases/{kb_id}/prd-documents/upload`, `DELETE /knowledge-bases/{kb_id}/prd-documents/{id}`
- `GET/POST /knowledge-bases/{kb_id}/defect-records`, `PUT/DELETE /knowledge-bases/{kb_id}/defect-records/{id}`
- `POST /knowledge-bases/{kb_id}/import-defects`

> 检索不对外暴露 HTTP 端点：`RetrievalService.retrieve` 由生成流程内部直接调用。
> （曾有 `POST /retrieve`，前端从未调用，已移除。）

#### 生成
- `POST /parse-prd` — 上传解析 PRD 文件（图片 OCR 随当前用户凭据，无凭据时插入占位说明、不挡上传）
- `POST /generate/clarify` — 基于知识库补全需求，返回结构化完整需求（Markdown），供用户确认/编辑后再生成；个人和兜底凭据皆无返 400
- `POST /generate/async` — 启动后台生成任务，立即返回 `{task_id, title, status, owner_id, created_at}`；任务脱离请求运行，刷新/切走后仍继续。owner 取登录用户、凭据在请求期解析后快照进任务（旧 `client_id` 已移除）
- `GET /generate/active` — 无参，固定列出当前用户仍在运行的任务，供刷新后「继续查看」
- `GET /generate/stream/{task_id}` — 订阅指定任务的 SSE：先重放已缓存事件，再推送实时事件（支持断线重连续看）；task 不属于本人返 404

#### 审核
- `GET /cases/batches` — **当前用户**的批次汇总：`[{batch_id, total, reviewed, approved, req_text, created_at, tokens}]`。历史/审核页首屏用它渲染折叠卡片，避免一次拉全量被截断。`tokens` 为该批 LLM 消耗，无流水的批次为 `null`（前端不显示）。
- `GET /cases?batch_id=<uuid>` — 某个批次的全部用例（无上限）。`batch_id` 必填且必须属于本人（否则 404）：前端一律先调 `/cases/batches` 拿汇总，再对展开的那一批拉明细。
- `PATCH /cases/{id}` / `POST /cases/{id}/review` / 批次内手工新增与插入 — 全部先校用例/批次归属，非本人 404

#### 导出 & 统计
- `POST /cases/export` — 请求体为 `{ cases: [...] }`
- `GET /stats/overview?scope=me|team` — 看板数据，默认 me（非 team 值一律按 me）。两 scope 同键：用例数/可用率/幻觉分布/generation_count + `token_usage`。me 全部按 owner 过滤，token 含 `{today_tokens, week_tokens, total_tokens, reasoning_tokens, system_tokens, calls, by_stage:[{stage,label,tokens,calls}], since}`（`system_tokens` = 其中走系统兜底的消耗）；team 为全员聚合，并追加 `by_model:[{model,tokens,calls}]` 与 `by_user:[{username,total_tokens,system_tokens,case_count}]`（仅有流水的用户入表），**不提供他人批次明细**。时间口径为 naive Asia/Shanghai（本周 = 周一 00:00 起）；`since` 是首条流水时间，为 `null` 说明还没采到数据。

### 计划 API
- 批量审核：`POST /cases/batch-review`
- 导出模板：`GET /export-templates`
- 按知识库或时间过滤用例：`GET /cases?kb_id=...&status=...`
- 生成前约束校验：`POST /generate/validate`
- 向量化状态查询：`GET /knowledge-bases/{kb_id}/vectorization-status`

---

## SSE 流式生成协议

```
event: progress  → {stage: "retrieving"|"constructing"|"splitting"|"generating"|"validating"|"reviewing"|"supplementing", message: "..."}
event: chunk     → {text: "(LLM 增量输出)"}                                # 单批路径 / 补充阶段的流式文本
event: modules       → {modules: ["模块A", "模块B", ...]}                  # 模块拆分完成后推送清单
event: module_start  → {index, module}                                    # 某模块(agent)开始生成
event: module_chunk  → {index, text}                                      # 该模块的实时流，前端按 index 分区归档
event: module_done   → {index, module, cases: [...], elapsed}             # 该模块完成，带解析好的用例 + 生成耗时(秒)
event: module_failed → {index, module, elapsed}                           # 该模块失败（跳过，不中断整批），带失败前耗时(秒)
event: review_start    → {index, module}                                  # 某评审 agent(按模块分组)开始
event: review_thinking → {index, text}                                    # 该评审 agent 的思考流
event: review_chunk    → {index, text}                                    # 该评审 agent 的实时评审输出(只列待删条目)
event: review_done     → {index, module, kept, deleted, truncated?, elapsed} # 该评审 agent 完成，带保留/删除条数 + 耗时(秒)；truncated=输出被截断，仅截断前判定生效
event: review_failed   → {index, module, elapsed}                         # 该评审 agent 失败（该组默认全部保留）
event: supplement_start    → {index, module}                              # 某补充 agent(被删模块/遗漏场景)开始
event: supplement_thinking → {index, text}                                # 该补充 agent 的思考流
event: supplement_chunk    → {index, text}                                # 该补充 agent 的实时补充用例输出
event: supplement_done     → {index, module, count, elapsed}              # 该补充 agent 完成，带新增条数(去重前) + 耗时(秒)
event: supplement_failed   → {index, module, elapsed}                     # 该补充 agent 失败（该组跳过）
event: knowledge → {knowledge_used: {...}, knowledge_matches: {...}}    # 检索结束后立即推送，让前端不等生成完成也能显示命中知识
event: complete  → {cases: [...], knowledge_used: {...}, knowledge_matches: {...}, elapsed}  # elapsed 为总耗时(秒)
event: error     → {message: "..."}
```

**需求补全（`POST /generate/clarify`）**：非流式，返回 `{clarified_text}`（Markdown）。检索 + 补全一步完成，不经过后台任务。

**后台任务模式（`POST /generate/async` + `GET /generate/stream/{task_id}`）**：事件由后台任务产生并缓存在内存中。客户端订阅时，先按序重放已缓存事件实现「断点续看」，再续接实时事件；任务结束后服务端关闭流。

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
- `services/pipeline_service.py` (`GeneratorService.generate_stream` 编排器；五阶段拆到 `pipeline_generate_service.py`/`pipeline_review_service.py`/`pipeline_supplement_service.py`，跨阶段共享工具在 `pipeline_context_service.py`，外部依赖接缝在 `pipeline_deps.py`；每阶段一个 async generator，产物走 `_results` 事件回传)
- `schemas/generation.py` + `routers/generation.py`
- 后处理: 校验LLM输出的knowledge_refs ID是否真实存在

**前端**:
- `GenerationView.vue` (双栏: 输入+输出)
- `stores/generation.ts` + `api/generation.ts`
- 注：原计划把输入/进度/结果表/详情/追溯标签拆成 `RequirementInput.vue`、`PrdUploader.vue`、
  `GenerationProgress.vue`、`CaseResultTable.vue`、`CaseDetailPanel.vue`、`KnowledgeRefTags.vue`
  六个子组件，实际全部内联在 `GenerationView.vue` 里（该文件已 650+ 行，拆分仍是待办）。

**验证**: 上传PRD PDF → 知识库有关联数据 → 生成 → 流式进度 → 用例结果含知识引用标签。

### Phase 4: 审核闭环 + 导出 + 统计 (已完成 ✓)

**目标**: 完整反馈闭环 —— 审核标注 → 幻觉归因 → 知识缺口建议 → Excel导出 → 统计看板。

**后端**（实际未拆分独立 router，全部并入 `routers/generation.py`）:
- `POST /cases/{case_id}/review` (逐条审核，写 `review_record` 表)
- `POST /cases/export` + `services/excel_service.py` 的 `ExcelExportService` (Excel导出)
- `GET /stats/overview` (可用率/幻觉分布/token用量)
- 注：原计划的 `schemas/review.py`、`routers/review.py`、`routers/export.py`、`routers/stats.py`、
  `services/stats_service.py` 均未创建；`generation.py` 因此成为杂物路由（拆分仍是待办）。

**前端**（实际未拆分子组件）:
- `ReviewView.vue` (单页承载批次列表+审核+手动插入用例)
- `StatsView.vue` (手写 CSS 条形图，**未引入 ECharts**——曾装过 echarts/vue-echarts 但从未使用，已移除)
- 注：原计划的 `ReviewCard.vue`、`RejectReasonForm.vue`、`BatchReviewBar.vue`、
  `KnowledgeCoverage.vue`（知识缺口建议面板）均未创建；知识缺口建议目前只体现在
  生成阶段的评审 gaps → 定向补充用例，没有独立面板。
- 审核/导出/统计三块都复用 `api/generation.ts`，未建 `stores/review.ts`、`api/review.ts`、
  `api/export.ts`、`api/stats.ts`。

**验证**: 生成30条 → 审核全部 → 统计可用率83% → 幻觉分布正确 → 导出Excel。

---

## 关键设计决策

1. **不用LangChain**: 检索链足够简单(关键词SQL + ChromaDB)，框架增加调试成本
2. **SSE非WebSocket**: 单向推送够用，nginx `proxy_buffering off` 即可
3. **UUID主键**: 安全、前端可生成乐观ID、未来多实例部署友好
4. **Knowledge ref校验**: LLM输出的引用ID后处理验证，不存在则标记警告
5. **Embedding先用云端 API**: 免本地模型下载，config支持切 sentence-transformers 本地模式
6. **Element Plus按需导入**: `unplugin-vue-components` + `unplugin-auto-import` 控制打包体积
7. **生成解耦后台任务**: 生成用 `asyncio.create_task` + 独立 DB 会话脱离请求，事件缓存在内存任务注册表中支持重连重放；前端状态提升到 Pinia store。代价是任务态为进程内内存，后端重启会丢失活动任务列表（已落库用例不受影响）
8. **多用户 fail-closed（v0.32）**: owner 用无 FK 裸列、查询一律 `WHERE owner_id=:me`，NULL 天然不可见；越权读统一 404 不泄露存在性；权限服务端判定，前端只读化只是体验。个人 key 调用失败**不自动降级**系统兜底（避免悄悄花公司额度）；个人 api_key 用 Fernet 加密、接口只回掩码，JWT/Fernet 密钥与备份分开存放

## 风险应对

| 风险               | 应对                                           |
| ------------------ | ---------------------------------------------- |
| 知识库冷启动       | 允许仅含字段字典即可生成，展示警告提示质量预期 |
| LLM返回非JSON      | regex fallback从markdown代码块提取; 失败则重试 |
| 大PRD超上下文      | 按Markdown标题分章节生成，聚合结果             |
| ChromaDB持久化问题 | Docker volume挂载; 提供备份/恢复接口           |

---

## 验证计划

1. **Phase 1**: docker-compose up → 创建项目/模块 → CRUD 4种知识类型
2. **Phase 2**: Excel导入 → `/retrieve` API 返回匹配结果
3. **Phase 3**: 上传PRD PDF → 生成用例 → 用例含知识引用标签 → 可用率人工验证
4. **Phase 4**: 审核30条 → 统计看板 → Excel导出 → 缺口建议
5. **端到端**: 导入真实团队Excel知识库 → 上传真实PRD → 审核 → 是否≥85%可用率
