import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Slack Configuration
    SLACK_CLIENT_ID: str = os.getenv("SLACK_CLIENT_ID", "")
    SLACK_CLIENT_SECRET: str = os.getenv("SLACK_CLIENT_SECRET", "")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    
    # MongoDB Configuration
    MONGODB_URL: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "slack")
    
    # Application Configuration
    SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-secret-key")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # OAuth Configuration
    OAUTH_REDIRECT_URI: str = (
        os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/slack/callback") 
        if os.getenv("ENVIRONMENT", "development").upper() == "DEVELOPMENT"
        else os.getenv("OAUTH_REDIRECT_URI_PROD", "https://www.alignspires.com/slack/callback")
    )

    # GitHub Configuration
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_USERNAME: str = os.getenv("GITHUB_USERNAME", "")
    
    # Slack OAuth Scopes - DM 功能所需的权限（仅 Bot Token scopes）
    SLACK_SCOPES = [
        "im:read", 
        "im:write", 
        "im:history", 
        "users:read", 
        "chat:write",
        "files:read",  # 读取文件信息
        "files:write"  # 下载文件内容
    ]

settings = Settings()