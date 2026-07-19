"""\nSlack 集成后端 FastAPI 应用\n"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import init_database, close_database
from routers import auth, events, subscription, user, workspace, oauth
from routes import slack_interactive, paypal_payment, paypal_webhook
from middleware import ExceptionHandlerMiddleware, LoggingMiddleware, SecurityHeadersMiddleware
from exceptions import SlackBotException
from utils import format_error_response, format_success_response

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

# 设置特定模块的日志级别
logging.getLogger("routers.events").setLevel(logging.INFO)
logging.getLogger("services").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    try:
        # 启动时初始化数据库
        await init_database()
        
        # 初始化工作区配置
        from services.slack_service import slack_service
        await slack_service.initialize_workspaces()
        
        yield
    finally:
        # 关闭时清理资源
        print("Shutting down application, closing database connections...")
        await close_database()
        print("Application shutdown complete")

# 创建 FastAPI 应用
app = FastAPI(
    title="Slack Integration Backend",
    description="与 Slack 集成的后端 API 服务，支持 DM 消息处理、用户认证、订阅管理等功能",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "API Support",
        "email": "support@example.com",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
)

# 添加中间件（顺序很重要）
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(ExceptionHandlerMiddleware)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境中应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
# 全局异常处理器
@app.exception_handler(SlackBotException)
async def slack_bot_exception_handler(request: Request, exc: SlackBotException):
    """处理自定义异常"""
    return JSONResponse(
        status_code=exc.status_code,
        content=format_error_response(exc.message, exc.details, exc.status_code)
    )

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """处理 404 错误"""
    return JSONResponse(
        status_code=404,
        content=format_error_response("Endpoint not found", {"path": request.url.path})
    )


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc):
    """处理 405 错误"""
    return JSONResponse(
        status_code=405,
        content=format_error_response("Method not allowed", {"method": request.method, "path": request.url.path})
    )

# 注册路由
app.include_router(auth.router, prefix="/slack", tags=["auth"])
app.include_router(events.router, prefix="/slack", tags=["slack-events"])
app.include_router(subscription.router, prefix="/slack", tags=["subscription"])
app.include_router(user.router, prefix="/slack", tags=["user"])
app.include_router(workspace.router, prefix="/slack/workspaces", tags=["workspaces"])

# Include Slack and PayPal routes
app.include_router(slack_interactive.router, prefix="/slack", tags=["slack-interactive"])
app.include_router(paypal_payment.router, prefix="/slack", tags=["paypal-payment"])
app.include_router(paypal_webhook.router, prefix="/slack", tags=["paypal-webhook"])

@app.get("/", summary="根路径", description="返回 API 基本信息")
async def root():
    """根路径"""
    return format_success_response({
        "name": "Slack Integration Backend API",
        "version": "1.0.0",
        "description": "与 Slack 集成的后端 API 服务",
        "docs_url": "/docs",
        "redoc_url": "/redoc"
    })

@app.get("/slack/health", summary="Slack 健康检查", description="检查 Slack 相关服务运行状态")
async def slack_health_check():
    """Slack 健康检查"""
    return format_success_response({
        "status": "healthy",
        "service": "slack-integration-backend",
        "version": "1.0.0",
        "endpoint": "/slack/health"
    })


@app.get("/health", summary="应用健康检查", description="检查整体应用运行状态")
async def health_check():
    """应用健康检查"""
    return format_success_response({
        "status": "healthy",
        "service": "slack-integration-backend",
        "version": "1.0.0",
        "endpoint": "/health"
    })