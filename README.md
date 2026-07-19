# Slack 集成后端 API

一个与 Slack 集成的 FastAPI 后端项目，支持 DM 消息处理、用户认证、订阅管理等功能。

## 功能特性

- 🔐 **Slack OAuth 认证**: 支持用户通过 Slack 账号登录
- 💬 **DM 消息处理**: 接收和回复 Slack 直接消息
- 👥 **用户管理**: 用户注册、资料管理、行为记录
- 💳 **订阅系统**: 多层级订阅计划和支付处理
- 📊 **使用统计**: 用户行为分析和使用次数统计
- 🛡️ **安全保护**: JWT 认证、请求签名验证、安全头
- 📚 **API 文档**: 自动生成的 OpenAPI 文档

## 技术栈

- **FastAPI**: 现代、快速的 Web 框架
- **MongoDB**: NoSQL 数据库
- **Slack SDK**: Slack API 集成
- **JWT**: 用户认证
- **Pydantic**: 数据验证
- **Motor**: 异步 MongoDB 驱动

## 项目结构

```
slack-integration/
├── main.py                 # FastAPI 应用入口
├── run.py                  # 应用启动文件
├── config.py               # 配置管理
├── database.py             # 数据库连接
├── models.py               # 数据模型
├── exceptions.py           # 自定义异常
├── middleware.py           # 中间件
├── utils.py                # 工具函数
├── requirements.txt        # 依赖包
├── .env.example           # 环境变量示例
├── routers/               # 路由模块
│   ├── __init__.py
│   ├── auth.py            # 认证路由
│   ├── events.py          # Slack 事件路由
│   ├── subscription.py    # 订阅管理路由
│   └── user.py            # 用户管理路由
└── services/              # 服务层
    ├── __init__.py
    ├── auth_service.py     # 认证服务
    ├── database_service.py # 数据库服务
    ├── message_service.py  # 消息处理服务
    ├── slack_service.py    # Slack API 服务
    └── subscription_service.py # 订阅服务
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

编辑 `.env` 文件：

```env
# Slack 应用配置
SLACK_CLIENT_ID=your_slack_client_id
SLACK_CLIENT_SECRET=your_slack_client_secret
SLACK_SIGNING_SECRET=your_slack_signing_secret
SLACK_BOT_TOKEN=xoxb-your-bot-token

# MongoDB 配置
MONGODB_URL=mongodb://localhost:27017
MONGODB_DATABASE=slack-integration

# 应用配置
SECRET_KEY=your-secret-key-here
ENVIRONMENT=development
HOST=0.0.0.0
PORT=8000

# OAuth 配置
OAUTH_REDIRECT_URI=http://localhost:8000/auth/callback
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