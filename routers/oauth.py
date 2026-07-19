from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional, Dict
import urllib.parse
import secrets
import time
import hmac, hashlib, base64, json
from config import settings
from services.workspace_service import workspace_service
from services.slack_service import slack_service
from slack_sdk import WebClient

router = APIRouter()

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
    <html>
    <head>
        <title>Install Slack App</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 600px;
                margin: 50px auto;
                padding: 20px;
                text-align: center;
            }}
            .install-button {{
                display: inline-block;
                background-color: #4A154B;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 4px;
                font-weight: bold;
                margin: 20px 0;
            }}
            .install-button:hover {{
                background-color: #611f69;
            }}
        </style>
    </head>
    <body>
        <h1>Install the Slack App to Your Workspace</h1>
        <p>Click the button below to install the app to your Slack workspace:</p>
        <a href="{oauth_url}" class="install-button">
            <img src="https://platform.slack-edge.com/img/add_to_slack.png" 
                 alt="Add to Slack" height="40" width="139">
        </a>
        <p><small>After installation, you can use @Agent to interact with the bot in Slack.</small></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@router.get("/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    error: Optional[str] = Query(None)
):
    """处理OAuth回调"""
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth错误: {error}")
    
    # 校验签名 state（格式/签名/过期）
    verify_signed_state(state)

    try:
        # 使用授权码获取访问令牌
        client = WebClient()
        oauth_response = client.oauth_v2_access(
            client_id=settings.SLACK_CLIENT_ID,
            client_secret=settings.SLACK_CLIENT_SECRET,
            code=code,
            redirect_uri=settings.OAUTH_REDIRECT_URI
        )
        
        if not oauth_response["ok"]:
            raise HTTPException(status_code=400, detail="OAuth授权失败")
        
        # 提取工作区信息
        team_info = oauth_response["team"]
        bot_info = oauth_response["access_token"]
        app_info = oauth_response.get("app_id")
        
        workspace_data = {
            "team_id": team_info["id"],
            "team_name": team_info["name"],
            "bot_token": bot_info,
            "bot_user_id": oauth_response.get("bot_user_id", ""),
            "scope": oauth_response.get("scope", ""),
            "app_id": app_info or "",
            "is_active": True
        }
        
        # 检查工作区是否已存在
        existing_workspace = await workspace_service.get_workspace(team_info["id"])
        if existing_workspace:
            await workspace_service.update_workspace(team_info["id"], workspace_data)
            message = "工作区配置已更新"
        else:
            await workspace_service.add_workspace(workspace_data)
            message = "工作区安装成功"
        
        slack_service.add_workspace_token(team_info["id"], bot_info)
        
        # 返回成功页面
        success_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>安装成功</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 600px;
                    margin: 50px auto;
                    padding: 20px;
                    text-align: center;
                }}
                .success {{
                    color: #28a745;
                    font-size: 24px;
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            <div class="success">✅ {message}</div>
            <h2>工作区: {team_info["name"]}</h2>
            <p>您现在可以在Slack中使用机器人了！</p>
            <p><small>您可以关闭此页面并返回Slack</small></p>
        </body>
        </html>
        """
        return HTMLResponse(content=success_html)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OAuth处理失败: {str(e)}")

@router.get("/status/{team_id}")
async def installation_status(team_id: str):
    """检查安装状态"""
    try:
        workspace = await workspace_service.get_workspace(team_id)
        if workspace and workspace.is_active:
            return {
                "installed": True,
                "team_name": workspace.team_name,
                "installed_at": workspace.installed_at.isoformat() if workspace.installed_at else None
            }
        else:
            return {"installed": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check installation status: {str(e)}")

# State 签名/校验工具（使用 SECRET_KEY 进行 HMAC-SHA256）
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

def verify_signed_state(state: str) -> None:
    try:
        parts = state.split('.')
        if len(parts) != 2:
            raise ValueError("Invalid state format")
        payload_b64, sig_b64 = parts
        payload_bytes = _b64url_decode(payload_b64)
        expected_sig = hmac.new(settings.SECRET_KEY.encode('utf-8'), payload_bytes, hashlib.sha256).digest()
        provided_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            raise ValueError("Signature mismatch")
        payload = json.loads(payload_bytes)
        now = int(time.time())
        exp = int(payload.get('exp', 0))
        if now > exp:
            raise ValueError("State expired")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invaid state: {str(e)}")