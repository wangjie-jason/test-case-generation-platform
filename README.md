# Test Case Generation Platform

基于知识库驱动的 AI 测试用例生成工具，将生成可用率从 <30% 提升至 85%+。支持多人使用：账号登录、个人大模型凭据（花自己的额度）或系统统一兜底、知识库分团队/个人、批次与统计按人隔离。

## 技术栈

| 层       | 技术                                                    |
| -------- | ------------------------------------------------------- |
| 前端     | Vue 3 + Element Plus + Pinia + TypeScript               |
| 后端     | Python 3.10+ + FastAPI (async)                          |
| 数据库   | SQLite（WAL 模式，Alembic 迁移）                         |
| 向量库   | ChromaDB                                                |
| LLM      | 任意 OpenAI 兼容 API（DeepSeek / 智谱 GLM / OpenAI 等） |
| 认证     | JWT（PyJWT, HS256）+ bcrypt；个人 API Key 经 Fernet 加密 |
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

### 3. 配置环境变量

```bash
# 在项目根目录执行；复制模板后按注释填入
cp backend/.env.example backend/.env
```

多用户版本有几个**必填项，不填后端无法启动**：

```bash
# 生成 JWT 签名密钥和个人 API Key 的加密密钥（Fernet），各执行一次，填进 backend/.env
python3 -c "import secrets;print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

```ini
# backend/.env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=please-change-me   # 首个管理员，仅库中不存在时创建，启动后请改掉
JWT_SECRET_KEY=<上面第一条命令的输出>
LLM_CREDENTIAL_KEY=<上面第二条命令的输出>
```

大模型凭据有两种配法：

- **系统兜底模型**（本地开发推荐）：直接在 `.env` 填 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL`，所有人默认走它；
- **个人凭据**：留空兜底，启动后登录在「设置」页填自己的 key（花自己的额度）。个人与兜底都未配置时不能生成。

`.env` 默认示例为 OpenAI，按需改成你用的服务，例如智谱 GLM：

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

打开 http://localhost:3000，用 `.env` 里的首个管理员账号登录（模板默认 `admin` / `please-change-me`，登录后可在「设置」改密）。

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

### 账号与凭据
- 登录后使用（JWT 有效期 12 小时，过期自动跳登录页）；管理员可建号、设管理员、停用/启用、重置密码（账号只停用不删除）
- 「设置」页配置**个人大模型凭据**（OpenAI 兼容 base_url / key / model，加密存储、只显示掩码，可先测连通性）；未配置时使用系统兜底模型，两者都没有则不能生成
- 可随时清除个人配置回到系统兜底；个人 key 出错不会自动降级花公司额度

### 首页看板（统计）
- 用例总数、可用率、幻觉分布、token 消耗（今日/本周/累计、思考占比、按阶段拆分）
- 「我的 / 团队」两视图：团队视图汇总全员数据，另有按模型、按成员消耗，不暴露他人批次明细

### 用例生成
- 粘贴文本 / 上传 PRD（PDF/Word/MD/TXT，支持飞书链接导入）
- 选择知识库限定检索范围（只列出团队库 + 我的个人库）
- **需求补全**（可选）：需求描述简略时，先用知识库把缺失逻辑（字段约束/业务规则/状态流转/异常边界/回归风险）补成结构化完整需求，可编辑确认后再生成，减少用例遗漏
- 六大测试技术：等价类、边界值、决策表、状态迁移、错误推测、组合测试
- 生成后由 AI 以测试专家身份**评审**：删掉有问题的用例、针对缺口补充新用例（保留合格用例不改写）
- **并行生成**：可同时发起多个生成任务、互不阻塞；切换页面/刷新后自动重连续看进度；任务与批次按人隔离
- 下载 Excel（用例标题 / 等级 / 前置条件 / 步骤 / 预期结果，支持全部/仅通过）

### 审核标注
按批次分组（只含自己的批次），Tab 筛选，五种幻觉归因，可微调文案、手工补充用例

### 知识库
卡片式管理，支持 PRD文档、缺陷记录、字段字典、业务规则、状态机、术语映射：
- **团队库**：全员可见、可被生成引用，仅创建者和管理员能改/删（其他人进入为只读）
- **个人库**：仅本人可见，管理员也不可见

## 项目结构

```
├── backend/
│   ├── .env.example     # 运行时配置模板（复制为 .env，compose 经 env_file 注入）
│   ├── alembic/         # 数据库迁移（启动时自动执行）
│   ├── scripts/         # 运维脚本（删批次/重建向量/重排等）
│   └── app/
│       ├── main.py          # FastAPI 入口（迁移 + 首管理员 + 路由鉴权）
│       ├── config.py        # 配置
│       ├── models/          # 数据模型（含用户与个人凭据）
│       ├── routers/         # API 路由（auth/admin_users/llm_config/generation/knowledge）
│       ├── services/        # 业务逻辑（认证/加密/访问控制/生成流水线…）
│       └── vectorstore/     # ChromaDB
├── frontend/src/
│   ├── views/           # 页面（登录/看板/生成/审核/知识库/设置/用户管理）
│   ├── components/      # 组件
│   ├── stores/          # Pinia 状态（auth/generation/knowledge）
│   └── api/             # API 模块
├── deploy/              # 网关 TLS 反代示例（含 SSE 参数）
├── DESIGN.md            # 设计方案
├── PLAN.md              # 实施计划
└── docker-compose.yml
```
