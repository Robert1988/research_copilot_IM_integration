# Research Copilot + Slack (AI Agent 实验代码生成器)

一个与 Slack 集成的 FastAPI 后端项目，旨在作为一个 AI 代理（AI Agent），帮助研究人员和开发者自动分析论文、生成实验代码、修复代码并部署到 AWS 环境。项目深度集成了 Slack DM（直接消息）和交互式组件，支持 GitHub 仓库分析和 PayPal 支付订阅系统。

## 功能特性

- 🤖 **AI 代码生成与修复**: 核心功能 `AgentWorkFlow`，支持从学术论文和聊天记录自动生成实验代码 (`CodeGenerateHandler`)，并进行代码修复 (`CodeFixHandler`)。
- 📚 **PDF 论文分析**: 自动分析 PDF 格式的学术论文 (`PaperAnalyzer`)，提取核心贡献和未来研究方向。
- 🔗 **GitHub 深度集成**: 自动解析 GitHub 仓库 (`GitHubService`)，提取项目结构和代码内容作为 AI 生成上下文；支持更新 GitHub Secrets。
- ☁️ **AWS 自动化**: 集成了基于 boto3 的 AWS 操作，可能用于自动化部署实验环境（如 ECR、SageMaker 等）。
- 💬 **Slack 全面集成**: 
  - 支持 Slack OAuth 认证 (`/auth/login`)。
  - DM (直接消息) 处理，响应用户的指令和消息 (`/slack/events`)。
  - 交互式组件 (Interactive Components) 支持 (`/slack/interactive`)。
- 💳 **PayPal 订阅系统**: 集成 PayPal 支付 (`/slack/paypal-payment`) 和 Webhook (`/slack/paypal-webhook`)，实现多层级订阅和自动续费。
- 👥 **用户与工作区管理**: 用户资料维护、使用统计、订阅状态查询；支持多 Slack 工作区初始化和管理。
- 🛡️ **安全与异常处理**: 全局异常捕获 (`SlackBotException`)、请求安全头、JWT 认证以及 GitHub 凭证加密处理。

## 技术栈

- **Web 框架**: FastAPI, Uvicorn, Starlette
- **异步处理**: aiohttp, asyncio, anyio
- **AI/LLM**: openai, tiktoken
- **数据处理与科学计算**: numpy, pandas, scipy, sympy
- **数据库**: MongoDB (Motor异步驱动, pymongo)
- **Slack 集成**: slack-sdk
- **云服务集成**: boto3, aioboto3 (AWS)
- **文档处理**: PyMuPDF, pdfplumber, pdfminer.six, pdf2image (PDF 解析)
- **认证与安全**: PyJWT, bcrypt, cryptography, PyNaCl
- **支付集成**: PayPal API
- **代码格式化**: black

## 项目结构

```
slack-integration/
├── main.py                 # FastAPI 应用主入口，注册中间件和路由
├── run.py                  # 应用启动脚本
├── config.py               # 环境变量与配置管理
├── database.py             # 数据库连接初始化
├── models.py               # 数据库模型定义
├── exceptions.py           # 自定义异常类
├── middleware.py           # 中间件（日志、异常处理、安全头）
├── utils.py                # 通用工具函数
├── requirements.txt        # Python 依赖清单
├── .env.example            # 环境变量配置示例
├── k8s/                    # Kubernetes 部署文件 (deployment.yaml, service.yaml)
├── .github/workflows/      # GitHub Actions CI/CD 配置
├── routers/                # 基础 REST API 路由
│   ├── auth.py             # 认证
│   ├── events.py           # Slack 基础事件
│   ├── subscription.py     # 订阅查询
│   ├── user.py             # 用户管理
│   └── workspace.py        # 工作区管理
├── routes/                 # 核心业务路由
│   ├── paypal_payment.py   # PayPal 支付发起
│   ├── paypal_webhook.py   # PayPal 回调处理
│   └── slack_interactive.py# Slack 交互组件回调
└── services/               # 核心业务逻辑层 (Agent 核心)
    ├── agent_work_flow.py  # 核心 Agent 工作流（代码生成 -> 部署流程管理）
    ├── analyzer.py         # PDF/文本内容分析器
    ├── code_fix_handler.py # AI 代码自动修复
    ├── code_generate_handler.py # AI 实验代码生成
    ├── database_service.py # 数据库操作封装
    ├── github_service.py   # GitHub API 交互与仓库解析
    ├── paypal_handler.py   # PayPal 业务逻辑
    ├── pdfLinkHandler.py   # PDF 链接下载与处理
    ├── slack_service.py    # Slack 消息发送与 API 封装
    └── user_reply_handler.py # 用户交互回复处理
```

## 安装和配置

### 1. 克隆项目

```bash
git clone <repository-url>
cd slack-integration
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件，补充核心配置（部分必须配置项如下）：

```env
# Slack 应用配置
SLACK_CLIENT_ID=your_slack_client_id
SLACK_CLIENT_SECRET=your_slack_client_secret
SLACK_SIGNING_SECRET=your_slack_signing_secret
SLACK_BOT_TOKEN=xoxb-your-bot-token

# GitHub 集成配置
GITHUB_USERNAME=your_github_username
GITHUB_TOKEN=your_github_personal_access_token

# AWS 部署配置
AWS_ACCESS_KEY=your_aws_access_key
AWS_SECRET_KEY=your_aws_secret_key
AWS_REGION=your_aws_region
AWS_ACCOUNT_ID=your_aws_account_id

# MongoDB 配置
MONGODB_URL=mongodb://localhost:27017
MONGODB_DATABASE=slack-integration

# 支付与其他配置
SECRET_KEY=your-secret-key-here
ENVIRONMENT=development
HOST=0.0.0.0
PORT=8000
```

### 4. 设置 Slack 应用

1. 访问 [Slack API](https://api.slack.com/apps) 创建新应用
2. 配置 OAuth & Permissions:
   - 添加 Redirect URLs: `http://localhost:8000/auth/callback`
   - 添加 Bot Token Scopes: `im:read`, `im:write`, `im:history`, `users:read`
3. 配置 Event Subscriptions:
   - Request URL: `http://your-domain.com/slack/events`
   - 订阅 Bot Events: `message.im`
4. 配置 Interactive Components:
   - Request URL: `http://your-domain.com/slack/interactive`

### 5. 启动应用

```bash
python run.py
```

应用将在 `http://localhost:8000` 启动。

## API 文档

启动应用后，访问以下地址查看 API 文档：

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## 主要 API 端点

### 认证相关
- `GET /auth/login` - 启动 Slack OAuth 流程
- `GET /auth/callback` - OAuth 回调处理
- `GET /auth/me` - 获取当前用户信息
- `POST /auth/logout` - 用户登出

### Slack 事件
- `POST /slack/events` - Slack 事件回调
- `POST /slack/interactive` - Slack 交互式组件

### 用户管理
- `GET /user/profile` - 获取用户资料
- `PUT /user/profile` - 更新用户资料
- `GET /user/messages` - 获取消息历史
- `GET /user/stats` - 获取使用统计

### 订阅管理
- `GET /subscription/plans` - 获取订阅计划
- `GET /subscription/status` - 获取订阅状态
- `POST /subscription/upgrade` - 升级订阅
- `POST /subscription/cancel` - 取消订阅

## 数据模型

### 用户模型
```python
{
    "slack_user_id": "U1234567890",
    "email": "user@example.com",
    "display_name": "John Doe",
    "avatar_url": "https://...",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
}
```

### 订阅模型
```python
{
    "user_id": "ObjectId",
    "plan": "premium",
    "status": "active",
    "start_date": "2024-01-01T00:00:00Z",
    "end_date": "2024-02-01T00:00:00Z",
    "auto_renew": true
}
```

## 开发指南

### 添加新的 API 端点

1. 在 `routers/` 目录下创建或编辑路由文件
2. 在 `services/` 目录下添加业务逻辑
3. 在 `models.py` 中定义数据模型
4. 在 `main.py` 中注册路由

### 错误处理

项目使用自定义异常类进行错误处理：

```python
from exceptions import AuthenticationError, ValidationError

# 抛出认证错误
raise AuthenticationError("Invalid token")

# 抛出验证错误
raise ValidationError("Invalid input data", details={"field": "email"})
```

### 日志记录

使用 Python 标准日志库：

```python
import logging

logger = logging.getLogger(__name__)
logger.info("User action performed")
logger.error("Error occurred", exc_info=True)
```

## 部署

### Docker 部署

创建 `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "run.py"]
```

### 环境变量

生产环境需要设置以下环境变量：

- `ENVIRONMENT=production`
- `SECRET_KEY=<strong-secret-key>`
- `MONGODB_URL=<production-mongodb-url>`
- 所有 Slack 相关配置

## 安全注意事项

1. **环境变量**: 不要将敏感信息提交到版本控制
2. **HTTPS**: 生产环境必须使用 HTTPS
3. **CORS**: 限制允许的源域名
4. **签名验证**: 验证所有 Slack 请求的签名
5. **JWT 密钥**: 使用强密钥并定期轮换

## 监控和日志

- 应用日志记录在标准输出
- 使用中间件记录请求/响应信息
- 监控用户行为和系统性能
- 设置错误告警

## 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 创建 Pull Request

## 许可证

MIT License

## 支持

如有问题，请创建 Issue 或联系开发团队。