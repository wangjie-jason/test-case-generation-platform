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
- **当前没有任何鉴权**：拿到地址的人都能用你的 LLM Key 发起生成（真实花钱），也能看到并删除知识库与所有用例批次。知识库、批次、用例是**全局共享的一个工作区**——`client_id`（`app/routers/generation.py`）只隔离「进行中的任务」，不隔离数据。仅限可信内网使用。

### 跑测试

```bash
# 首次需装测试依赖
source venv/bin/activate && pip install -r backend/requirements-dev.txt

cd backend && pytest
```

排序规则（`app/utils/case_ordering.py`）有回归测试守着——「只挪补充用例、原有用例位置一律不动」这个承诺曾连漏两次（PR #52 漏了路径层、#53 漏了同级/后代之分），改动排序逻辑后请务必跑一遍。

测试只装 `pytest` 就能跑，不需要 `requirements.txt` 里的 chromadb / sentence-transformers：排序与归位是纯字符串逻辑，为此把 `case_grouping` 从 `generator_service` 抽了出来（后者顶部 import ChromaStore，一 import 就会拉起约 433 MB 的向量库依赖）。若新增测试确实需要 fastapi/sqlalchemy，改 `.github/workflows/ci.yml` 里的安装步骤。

### CI

`.github/workflows/ci.yml`：push 到 main 与向 main 提 PR 时自动跑两个 job——后端 `pytest`（Python 3.10）、前端 `npm ci && npm run build`（Node 18，`build` 脚本含 `vue-tsc` 类型检查）。

### Docker 部署

```bash
docker-compose up
```

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
