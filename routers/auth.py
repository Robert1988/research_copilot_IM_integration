from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from typing import Optional
import urllib.parse
import secrets
import hmac, hashlib, base64, json, time
from config import settings
from models import UserResponse, SubscriptionPlan, SubscriptionStatus
from services.auth_service import AuthService
from services.slack_service import SlackService
from services.database_service import DatabaseService
from services.subscription_service import SubscriptionService
from exceptions import AuthenticationError, SlackAPIError, DatabaseError
from utils import get_current_user, log_user_action, format_success_response, format_error_response

router = APIRouter()


# 初始化服务
auth_service = AuthService()
slack_service = SlackService()
db_service = DatabaseService()
subscription_service = SubscriptionService()


# Signed state helpers (HMAC-SHA256 with SECRET_KEY)
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def _b64url_decode(data_str: str) -> bytes:
    padding = '=' * (-len(data_str) % 4)
    return base64.urlsafe_b64decode(data_str + padding)

def create_signed_state(ttl_seconds: int = 600) -> str:
    issued_at = int(time.time())
    payload = {
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
        "nonce": secrets.token_urlsafe(16)
    }
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    secret = settings.SECRET_KEY.encode('utf-8')
    sig = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
    return _b64url_encode(payload_bytes) + '.' + _b64url_encode(sig)

@router.get("/install", response_class=HTMLResponse)
async def install_page():
    """Display installation page"""
    # 生成签名的 state（10 分钟有效）
    state = create_signed_state(ttl_seconds=600)
    # Build OAuth URL
    oauth_url = f"https://slack.com/oauth/v2/authorize?" + urllib.parse.urlencode({
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": "app_mentions:read,chat:write,files:read,im:history,im:read,im:write,users:read",
        "redirect_uri": settings.OAUTH_REDIRECT_URI,
        "state": state
    })
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            :root {{
                --accent: #1a73e8;
                --text: #1f1f1f;
                --muted: #5f6368;
                --bg: #f7f9fc;
                --card: #ffffff;
                --border: #e6e8eb;
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji";
                color: var(--text);
                background: linear-gradient(180deg, var(--bg) 0%, #ffffff 60%);
            }}
            .header {{
                padding: 20px 24px;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            .brand {{
                font-weight: 600;
                letter-spacing: .2px;
                color: var(--accent);
            }}
            .container {{
                max-width: 1000px;
                margin: 0 auto;
                padding: 24px;
            }}
            .hero {{
                text-align: center;
                padding: 32px 24px 12px;
            }}
            .hero h1 {{
                margin: 0 0 12px;
                font-size: 40px;
                line-height: 1.15;
            }}
            .hero p {{
                margin: 0 auto 24px;
                max-width: 720px;
                font-size: 18px;
                color: var(--muted);
            }}
            .cta {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                margin: 20px 0 8px;
            }}
            .cta img {{
                height: 44px;
                width: auto;
                filter: drop-shadow(0 2px 8px rgba(0,0,0,.15));
                transition: transform .15s ease, filter .15s ease;
            }}
            .cta:hover img {{
                transform: translateY(-1px);
                filter: drop-shadow(0 6px 18px rgba(0,0,0,.2));
            }}
            .note {{
                margin-top: 8px;
                color: var(--muted);
                font-size: 14px;
            }}
            .features {{
                display: grid;
                grid-template-columns: 1fr;
                gap: 16px;
                margin-top: 32px;
            }}
            @media (min-width: 768px) {{
                .features {{ grid-template-columns: repeat(2, 1fr); }}
            }}
            @media (min-width: 1024px) {{
                .features {{ grid-template-columns: repeat(4, 1fr); }}
            }}
            .card {{
                background: var(--card);
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 20px;
                text-align: left;
                box-shadow: 0 4px 12px rgba(0,0,0,.05);
            }}
            .card h3 {{
                margin: 0 0 8px;
                font-size: 16px;
                color: var(--accent);
            }}
            .card p {{
                margin: 0;
                color: var(--muted);
                font-size: 14px;
                line-height: 1.5;
            }}
            .footer {{
                padding: 24px 0 12px;
                text-align: center;
                color: var(--muted);
                font-size: 13px;
            }}
        </style>
    </head>
    <body>
        <main class="container">
            <section class="hero">
                <h1>Install the Slack App to Your Workspace</h1>
                <p>Connect your workspace and start collaborating with @Agent in Slack. Click the button below to install the app to your Slack workspace.</p>
                <a class="cta" href="{oauth_url}" aria-label="Add to Slack">
                    <img src="https://platform.slack-edge.com/img/add_to_slack.png" alt="Add to Slack">
                </a>
                <div class="note">After installation, you can use <code>@Agent</code> to interact with the bot in Slack.</div>
            </section>
            <section class="features">
                <div class="card">
                    <h3>Flexible</h3>
                    <p>Works across channels and DMs; invite your teammates anytime.</p>
                </div>
                <div class="card">
                    <h3>Helpful</h3>
                    <p>Get quick answers, automate tasks, and streamline your workflows.</p>
                </div>
                <div class="card">
                    <h3>Easy to Manage</h3>
                    <p>Simple setup with secure OAuth; manage access per workspace.</p>
                </div>
                <div class="card">
                    <h3>Trusted</h3>
                    <p>Secure by design with signed state and verified callbacks.</p>
                </div>
            </section>
            <div class="footer">
                Need help? Contact support after installation from within Slack.
            </div>
        </main>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
def verify_signed_state(state: str) -> None:
    try:
        parts = state.split('.')
        if len(parts) != 2:
            raise AuthenticationError("Invalid state format")
        payload_b64, sig_b64 = parts
        payload_bytes = _b64url_decode(payload_b64)
        expected_sig = hmac.new(settings.SECRET_KEY.encode('utf-8'), payload_bytes, hashlib.sha256).digest()
        provided_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            raise AuthenticationError("State signature mismatch")
        payload = json.loads(payload_bytes)
        now = int(time.time())
        exp = int(payload.get('exp', 0))
        if now > exp:
            raise AuthenticationError("State expired")
    except AuthenticationError:
        raise
    except Exception as e:
        raise AuthenticationError(f"Invalid state: {str(e)}")


@router.get("/login", summary="启动 OAuth 流程", description="重定向到 Slack OAuth 授权页面")
async def login():
    """启动 Slack OAuth 流程"""
    try:
        state = create_signed_state(ttl_seconds=600)
        auth_url = slack_service.get_oauth_url(state=state)
        return RedirectResponse(url=auth_url)
    except Exception as e:
        raise SlackAPIError(f"Failed to generate OAuth URL: {str(e)}")


@router.get("/callback", summary="OAuth 回调", description="处理 Slack OAuth 回调并完成用户认证")
async def oauth_callback(
    code: str,
    request: Request,
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """处理 Slack OAuth 回调"""
    import logging
    logger = logging.getLogger(__name__)
    
    # Require state; if missing, log and exit
    if error:
        raise AuthenticationError(f"OAuth error: {error}")
    if not state:
        logger.error("State is missing; rejecting callback")
        raise AuthenticationError("State is required")
    verify_signed_state(state)

    try:
        logger.info(f"🔄 开始处理OAuth回调，授权码: {code[:20]}...")
        logger.info(f"🔄 请求来源IP: {request.client.host if request.client else 'Unknown'}")
        
        # 检查必要的参数
        if not code:
            logger.error("❌ 未收到授权码")
            raise AuthenticationError("Authorization code is required")
        
        # 交换授权码获取访问令牌
        logger.info("🔄 正在交换授权码获取访问令牌...")
        token_response = await slack_service.exchange_code_for_token(code)
        
        if not token_response:
            logger.error("❌ 未能获取token响应")
            raise AuthenticationError("Failed to exchange code for token")
        
        logger.info(f"✅ 成功获取token响应，包含字段: {list(token_response.keys())}")
        
        # 从响应中提取令牌
        user_token = token_response.get("authed_user", {}).get("access_token")
        bot_token = token_response.get("access_token")
        
        logger.info(f"🔍 User Token存在: {bool(user_token)}")
        logger.info(f"🔍 Bot Token存在: {bool(bot_token)}")
        
        # 如果没有用户令牌，使用Bot令牌
        if not user_token:
            logger.warning("⚠️  未找到用户令牌，使用Bot令牌")
            user_token = bot_token
        
        if not user_token:
            logger.error("❌ 未能获取任何访问令牌")
            logger.error(f"❌ Token响应结构: {token_response}")
            raise AuthenticationError("Failed to obtain access token")
        
        logger.info("✅ 成功获取访问令牌")
        
        # 直接从Token响应中获取用户ID和团队ID
        slack_user_id = token_response.get("authed_user", {}).get("id")
        slack_team_id = token_response.get("team", {}).get("id")
        
        logger.info(f"🔍 从Token响应解析的用户ID: {slack_user_id}")
        
        # 验证应用是否已正确安装到workspace
        app_id = token_response.get("app_id")
        team_name = token_response.get("team", {}).get("name")
        logger.info(f"🔍 应用ID: {app_id}")
        logger.info(f"🔍 团队名称: {team_name}")
        logger.info(f"🔍 团队ID: {slack_team_id}")
        
        # 记录应用安装信息并保存工作区配置（oauth.py 的 workspace 更新逻辑已与此一致）
        if app_id and slack_team_id:
            logger.info(f"✅ 应用 {app_id} 已成功安装到团队 {team_name} ({slack_team_id})")
            
            from services.workspace_service import workspace_service
            workspace_data = {
                "team_id": slack_team_id,
                "team_name": team_name or "Unknown Team",
                "bot_token": bot_token,
                "bot_user_id": token_response.get("bot_user_id", ""),
                "scope": token_response.get("scope", ""),
                "app_id": app_id,
                "is_active": True
            }
            
            existing_workspace = await workspace_service.get_workspace(slack_team_id)
            if existing_workspace:
                await workspace_service.update_workspace(slack_team_id, workspace_data)
                logger.info(f"✅ 更新工作区配置: {team_name}")
            else:
                await workspace_service.add_workspace(workspace_data)
                logger.info(f"✅ 创建新工作区配置: {team_name}")
            
            slack_service.add_workspace_token(slack_team_id, bot_token)
            logger.info(f"✅ 工作区token已添加到Slack服务")
        else:
            logger.warning("⚠️  应用安装信息不完整")
        logger.info(f"🔍 从Token响应解析的团队ID: {slack_team_id}")
        
        if not slack_user_id:
            logger.error("❌ Token响应中缺少用户ID")
            logger.error(f"❌ Token响应结构: {token_response}")
            raise AuthenticationError("Failed to get user ID from token response")
        
        # 获取详细用户信息 (用于显示名称、头像等)
        logger.info("🔄 正在获取详细用户信息...")
        user_info = await slack_service.get_user_info(user_token)
        
        if not user_info:
            logger.warning("⚠️  未能获取详细用户信息，使用基本信息")
            user_info = {"user": {"id": slack_user_id}}
        else:
            logger.info(f"✅ 成功获取详细用户信息，包含字段: {list(user_info.keys())}")
        
        if not slack_team_id:
            logger.error("❌ token响应中缺少团队ID")
            logger.error(f"❌ Token响应结构: {token_response}")
            raise AuthenticationError("Failed to get team ID from token response")
        
        logger.info(f"✅ 成功解析用户信息: user_id={slack_user_id}, team_id={slack_team_id}")
        
        # 检查用户是否已存在
        logger.info("🔄 检查用户是否已存在...")
        existing_user = await db_service.get_user_by_slack_id(slack_user_id, slack_team_id)
        
        logger.info(f"🔍 用户已存在: {bool(existing_user)}")
        
        if existing_user:
            logger.info("🔄 更新现有用户信息...")
            # 更新现有用户信息
            user_data = {
                "user_token": user_token,
                "bot_token": bot_token,
                "access_token": user_token,  # 添加 access_token 字段
                "slack_team_id": slack_team_id,  # 添加 slack_team_id 字段
                "email": user_info.get("user", {}).get("profile", {}).get("email"),
                "display_name": user_info.get("user", {}).get("profile", {}).get("display_name"),
                "avatar_url": user_info.get("user", {}).get("profile", {}).get("image_192"),
                "updated_at": datetime.now(timezone.utc)
            }
            logger.info(f"🔍 准备更新的用户数据字段: {list(user_data.keys())}")
            
            user = await db_service.update_user(existing_user.id, user_data)
            logger.info(f"✅ 成功更新用户: {existing_user.id}")
            
            log_user_action(str(user.id), "user_login", {"method": "oauth_callback"}, request)
            logger.info("✅ 记录用户登录行为")
        else:
            logger.info("🔄 创建新用户...")
            # 创建新用户
            user_data = {
                "slack_user_id": slack_user_id,
                "slack_team_id": slack_team_id,  # 添加 slack_team_id 字段
                "user_token": user_token,
                "bot_token": bot_token,
                "access_token": user_token,  # 添加 access_token 字段
                "email": user_info.get("user", {}).get("profile", {}).get("email"),
                "display_name": user_info.get("user", {}).get("profile", {}).get("display_name"),
                "avatar_url": user_info.get("user", {}).get("profile", {}).get("image_192"),
                "is_active": True,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
            logger.info(f"🔍 准备创建的用户数据字段: {list(user_data.keys())}")
            
            user = await db_service.create_user(user_data)
            logger.info(f"✅ 成功创建新用户: {user.id}")
            
            # 为新用户创建默认订阅
            logger.info("🔄 为新用户创建默认订阅...")
            await subscription_service.create_subscription(str(user.id), "free", slack_user_id, None)
            logger.info("✅ 成功创建默认订阅")
            
            log_user_action(str(user.id), "user_register", {"method": "oauth_callback"}, request)
            logger.info("✅ 记录用户注册行为")

            log_user_action(str(user.id), "user_login", {"method": "oauth_callback"}, request)
            logger.info("✅ 记录用户登录行为")
        
        # 生成 JWT token
        logger.info("🔄 生成JWT访问令牌...")
        token = auth_service.create_access_token({"sub": str(user.id)})
        logger.info("✅ 成功生成JWT访问令牌")
        
        # 返回成功响应（实际应用中可能需要重定向到前端页面）
        logger.info("🔄 准备返回成功响应...")
        
        # 获取用户订阅信息用于UserResponse
        subscription = await subscription_service.get_user_subscription(slack_user_id)
        
        # 如果没有活跃订阅，为用户创建默认的免费订阅
        if not subscription or subscription.status == SubscriptionStatus.CANCELLED:
            logger.info("🔄 为用户创建默认免费订阅...")
            subscription = await subscription_service.create_subscription(
                str(user.id), SubscriptionPlan.FREE, slack_user_id, None
            )
            logger.info("✅ 成功创建默认免费订阅")
        
        response_data = {
            "access_token": token,
            "token_type": "bearer",
            "user": UserResponse(
                id=str(user.id),
                slack_user_id=user.slack_user_id,
                name=user.name,
                email=user.email,
                subscription_status=subscription.status if subscription else SubscriptionStatus.TRIAL,
                subscription_plan=subscription.plan if subscription else SubscriptionPlan.FREE,
                usage_count=subscription.current_usage if subscription else 0,
                usage_limit=subscription.usage_limit if subscription else 100,
                created_at=user.created_at
            )
        }
        logger.info("✅ OAuth回调处理完成，返回成功页面")
        
        # 返回成功的HTML页面而不是JSON
        success_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>AlignSpires Bot - 安装成功</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    max-width: 600px;
                    margin: 50px auto;
                    padding: 40px 20px;
                    text-align: center;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    color: white;
                    box-sizing: border-box;
                }}
                .container {{
                    background: rgba(255, 255, 255, 0.95);
                    border-radius: 20px;
                    padding: 40px;
                    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
                    color: #333;
                }}
                .success-icon {{
                    font-size: 64px;
                    margin-bottom: 20px;
                    animation: bounce 2s infinite;
                }}
                @keyframes bounce {{
                    0%, 20%, 50%, 80%, 100% {{
                        transform: translateY(0);
                    }}
                    40% {{
                        transform: translateY(-10px);
                    }}
                    60% {{
                        transform: translateY(-5px);
                    }}
                }}
                .success-title {{
                    color: #28a745;
                    font-size: 28px;
                    font-weight: bold;
                    margin: 20px 0;
                }}
                .bot-name {{
                    color: #4A154B;
                    font-size: 32px;
                    font-weight: bold;
                    margin: 10px 0;
                }}
                .description {{
                    font-size: 18px;
                    line-height: 1.6;
                    margin: 20px 0;
                    color: #666;
                }}
                .action-button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #4A154B, #611f69);
                    color: white;
                    padding: 15px 30px;
                    text-decoration: none;
                    border-radius: 50px;
                    font-weight: bold;
                    margin: 20px 10px;
                    transition: all 0.3s ease;
                    box-shadow: 0 4px 15px rgba(74, 21, 75, 0.3);
                }}
                .action-button:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(74, 21, 75, 0.4);
                }}
                .close-note {{
                    font-size: 14px;
                    color: #999;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                }}
                .features {{
                    text-align: left;
                    margin: 30px 0;
                    padding: 20px;
                    background: #f8f9fa;
                    border-radius: 10px;
                }}
                .features h3 {{
                    color: #4A154B;
                    margin-bottom: 15px;
                }}
                .features ul {{
                    list-style: none;
                    padding: 0;
                }}
                .features li {{
                    padding: 5px 0;
                    color: #666;
                }}
                .features li:before {{
                    content: "✨ ";
                    color: #28a745;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="success-icon">🎉</div>
                <div class="success-title">Installation Successful!</div>
                <div class="bot-name">AlignSpires Bot</div>
                <div class="description">
                    Congratulations! AlignSpires Bot has been successfully installed to your Slack workspace.
                    <br>You can now start using our intelligent assistant!
                </div>
                
                <div class="features">
                    <h3>🚀 You can now use the following features:</h3>
                    <ul>
                        <li>PDF document intelligent parsing and content extraction</li>
                        <li>GitHub repository automatic conversion to Markdown</li>
                        <li>AI intelligent conversation and code generation</li>
                        <li>File processing and content analysis</li>
                        <li>Free plan includes 20 AI message credits</li>
                    </ul>
                </div>
                
                <a href="slack://app" class="action-button">
                    🚀 Go to Slack to Start Using
                </a>
                
                <div class="close-note">
                    💡 You can safely close this page and start chatting with AlignSpires Bot directly in Slack.
                    <br>
                    If you have any questions, please send a message to our Bot in Slack.
                </div>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=success_html)
        
    except AuthenticationError as auth_error:
        logger.error(f"❌ 认证错误: {str(auth_error)}")
        raise auth_error
    except Exception as e:
        logger.error(f"❌ OAuth回调处理失败: {str(e)}")
        import traceback
        logger.error(f"❌ 完整错误堆栈: {traceback.format_exc()}")
        raise DatabaseError(f"Authentication failed: {str(e)}")


@router.post("/logout", summary="用户登出", description="撤销用户访问令牌")
async def logout(current_user: dict = Depends(get_current_user), request: Request = None):
    """用户登出"""
    try:
        user_id = current_user["user_id"]
        
        # 记录登出行为
        log_user_action(user_id, "user_logout", request=request)
        
        # 在实际应用中，这里可以将 token 加入黑名单
        # 或者撤销 Slack 访问令牌
        
        return format_success_response({}, "Logout successful")
        
    except Exception as e:
        raise AuthenticationError(f"Logout failed: {str(e)}")


@router.get("/me", summary="获取当前用户", description="获取当前认证用户的信息和订阅状态")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    try:
        user_id = current_user["user_id"]
        
        # 获取用户信息
        user = await db_service.get_user_by_id(user_id)
        if not user:
            raise AuthenticationError("User not found")
        
        # 获取用户订阅信息
        subscription = await subscription_service.get_user_subscription(user_id)
        
        return format_success_response({
            "user": UserResponse(
                id=str(user.id),
                slack_user_id=user.slack_user_id,
                name=user.name,
                email=user.email,
                subscription_status=subscription.status if subscription else SubscriptionStatus.TRIAL,
                subscription_plan=subscription.plan if subscription else SubscriptionPlan.FREE,
                usage_count=subscription.current_usage if subscription else 0,
                usage_limit=subscription.usage_limit if subscription else 100,
                created_at=user.created_at
            ),
            "subscription": subscription
        })
        
    except AuthenticationError:
        raise
    except Exception as e:
        raise DatabaseError(f"Failed to get user info: {str(e)}")