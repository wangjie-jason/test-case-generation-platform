# Test Case Generation Platform

基于知识库驱动的 AI 测试用例生成工具，将生成可用率从 <30% 提升至 85%+。

## 技术栈

| 层       | 技术                                                    |
| -------- | ------------------------------------------------------- |
| 前端     | Vue 3 + Element Plus + Pinia + TypeScript               |
| 后端     | Python 3.10+ + FastAPI (async)                          |
| 数据库   | SQLite (dev)                                            |
| 向量库   | ChromaDB                                                |
| LLM      | 任意 OpenAI 兼容 API（DeepSeek / 智谱 GLM / OpenAI 等） |
| 文档解析 | pdfplumber + python-docx                                |

## 快速开始

### 1. 克隆仓库

```bash
git clone git@github.com:wangjie-jason/test-case-generation-platform.git
cd test-case-generation-platform
```

> 需要 Python 3.10+、Node.js 18+。

### 2. 安装后端依赖

```bash
# 在项目根目录创建虚拟环境（PyCharm 打开项目时也会复用这个 venv）
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### 3. 配置 API Key

```bash
# 在项目根目录执行；复制模板后填入自己的密钥（任意 OpenAI 兼容服务均可）
cp backend/.env.example backend/.env
```

`backend/.env` 默认示例为 OpenAI，按需改成你用的服务，例如智谱 GLM：

```ini
LLM_API_KEY=your-key-here
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL=glm-4.7-flash
```

### 4. 安装前端依赖

```bash
cd frontend
npm install
```

### 5. 启动

```bash
# 终端 1 - 后端（在项目根目录激活 venv，再进 backend 启动）
source venv/bin/activate && cd backend && uvicorn app.main:app --port 8000

# 终端 2 - 前端
cd frontend && npm run dev
```

数据库结构由 Alembic 管理，启动时自动迁移（新库建表、老库自动识别并补列），无需手工执行任何命令。

打开 http://localhost:3000

### 让局域网内的同事访问

`vite.config.ts` 里已设 `host: true`（前端监听 `0.0.0.0`），同事在同一局域网直接打开 `http://<你的内网IP>:3000` 即可，**不需要改任何代码**——前端请求走相对路径 `/api/v1`，由 Vite 代理转发到本机的 8000 端口。

```bash
# 查本机内网 IP（macOS：Wi-Fi 一般是 en0，有线一般是 en1）
ipconfig getifaddr en0
```

几点注意：

- **后端保持默认的 127.0.0.1**（`uvicorn app.main:app --port 8000`，别加 `--host 0.0.0.0`）。8000 端口没有暴露的必要，同事的请求经 Vite 代理就能到达。
- macOS 防火墙首次会弹窗询问是否允许 `node` 接受传入连接，必须点「允许」，否则同事连不上。
- 服务跑在你的机器上，**合盖休眠就断**。需要长时间可用时用 `caffeinate -i` 挂着，或改用 Docker 部署到服务器。
- 内网 IP 由 DHCP 分配，换网络或重连后可能变化，变了要重新告知同事。
- **需要登录**：除健康检查和登录接口外，所有接口都要求登录，未登录会自动跳到登录页。账号由管理员创建，首个管理员通过 `.env` 的 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 在启动时初始化。

### Docker 部署到服务器

```bash
# 1) 准备运行时配置（含必填密钥，见下）
cp backend/.env.example backend/.env
vi backend/.env

# 2) 构建并后台启动
docker compose up -d --build
```

- 前端容器只绑定 `127.0.0.1:3000`，后端不直接暴露端口；对外统一由公司网关终止 TLS 后反代到 3000。配置示例见 [`deploy/nginx-gateway.example.conf`](deploy/nginx-gateway.example.conf)（含 SSE 长连接参数）。
- 首次启动自动建表迁移并创建首个管理员。

**`backend/.env` 必填项**（`.env.example` 有注释与生成命令）：

| 变量 | 说明 |
| --- | --- |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 首个管理员，仅在库中不存在时创建（之后改密走界面） |
| `JWT_SECRET_KEY` | 登录 token 签名密钥 |
| `LLM_CREDENTIAL_KEY` | 用户个人 API Key 的加密密钥（Fernet） |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | **系统兜底模型**：未配置个人凭据的用户走这里；留空则所有人必须自配 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书导入（不用可留空） |

> 多用户模型：知识库分**团队**（全员可见引用，改删限创建者/管理员）和**个人**（仅本人）；批次与统计按人隔离，统计页可切「团队」看全员汇总。

**数据备份**：只需备份 SQLite 库与 chroma 目录（都在挂载卷 `./data`）。SQLite 已开 WAL，用在线备份而非直接 cp：

```bash
# 每日 cron，保留 14 天
sqlite3 ./data/testcase_platform.db ".backup '/backup/tcg-$(date +%F).db'"
tar czf /backup/chroma-$(date +%F).tgz -C ./data chromadb
```

备份文件含用户 API Key 的密文，按敏感件保管；`JWT_SECRET_KEY` 与 `LLM_CREDENTIAL_KEY` 要与备份分开存放（丢了 Fernet 密钥，用户需重录 key）。

## 功能模块

### 首页看板
用例总数、可用率、幻觉分布、生成批次统计 + 平台功能介绍

### 用例生成
- 粘贴文本 / 上传 PRD（PDF/Word/MD/TXT）
- 选择知识库限定检索范围
- **需求补全**（可选）：需求描述简略时，先用知识库把缺失逻辑（字段约束/业务规则/状态流转/异常边界/回归风险）补成结构化完整需求，可编辑确认后再生成，减少用例遗漏
- 六大测试技术：等价类、边界值、决策表、状态迁移、错误推测、组合测试
- 生成后由 AI 以测试专家身份**评审**：删掉有问题的用例、针对缺口补充新用例（保留合格用例不改写）
- **并行生成**：可同时发起多个生成任务、互不阻塞；切换页面/刷新后自动重连续看进度；多人各自浏览器任务隔离
- 下载 Excel（用例标题 / 等级 / 前置条件 / 步骤 / 预期结果）

### 审核标注
按批次分组，Tab 筛选，五种幻觉归因，批量操作

### 知识库
卡片式管理，支持 PRD文档、缺陷记录、字段字典、业务规则、状态机、术语映射

## 项目结构

```
├── backend/app/
│   ├── main.py          # FastAPI 入口
│   ├── config.py        # 配置
│   ├── models/          # 数据模型
│   ├── routers/         # API 路由
│   ├── services/        # 业务逻辑
│   └── vectorstore/     # ChromaDB
├── frontend/src/
│   ├── views/           # 页面视图
│   ├── components/      # 组件
│   ├── stores/          # Pinia 状态
│   └── api/             # API 模块
├── DESIGN.md            # 设计方案
├── PLAN.md              # 实施计划
└── docker-compose.yml
```
