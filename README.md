# Test Case Generation Platform

基于知识库驱动的 AI 测试用例生成工具，将生成可用率从 <30% 提升至 85%+。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Element Plus + Pinia + TypeScript |
| 后端 | Python 3.10+ + FastAPI (async) |
| 数据库 | SQLite (dev) |
| 向量库 | ChromaDB |
| LLM | 任意 OpenAI 兼容 API（DeepSeek / 智谱 GLM / OpenAI 等） |
| 文档解析 | pdfplumber + python-docx |

## 快速开始

### 1. 安装后端依赖

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# 任意 OpenAI 兼容服务均可，以下以智谱 GLM 为例
echo 'LLM_API_KEY=your-key-here
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL=glm-4-flash' > backend/.env
```

### 3. 安装前端依赖

```bash
cd frontend
npm install
```

### 4. 启动

```bash
# 终端 1 - 后端
cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8000

# 终端 2 - 前端
cd frontend && npm run dev
```

打开 http://localhost:3000

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
- 六大测试技术：等价类、边界值、决策表、状态迁移、错误推测、组合测试
- 生成后自我修正（校验字段/规则合法性）
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
