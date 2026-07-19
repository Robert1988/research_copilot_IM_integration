from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

class SubscriptionStatus(str, Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class SubscriptionPlan(str, Enum):
    FREE = "free"
    BASE = "base"
    PRO = "pro"

class MessageType(str, Enum):
    RECEIVED = "received"
    SENT = "sent"

class SlackWorkspace(BaseModel):
    """Slack工作区配置模型"""
    id: Optional[str] = Field(None, alias="_id")
    team_id: str  # Slack团队ID
    team_name: str  # 工作区名称
    bot_token: str  # 该工作区的Bot Token
    bot_user_id: str  # Bot在该工作区的用户ID
    signing_secret: Optional[str] = None  # 可选的签名密钥
    installed_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class User(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    slack_user_id: str
    slack_team_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class Subscription(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    external_subscription_id: Optional[str] = None  # 改为可选字段
    slack_user_id: str
    plan: SubscriptionPlan = SubscriptionPlan.FREE
    status: SubscriptionStatus = SubscriptionStatus.TRIAL
    started_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    usage_limit: int = 100  # Messages per month
    current_usage: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class MessageLog(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    slack_user_id: str
    slack_channel_id: str
    slack_message_ts: str
    message_type: MessageType
    original_message: str
    processed_message: Optional[str] = None
    response_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    processing_time_ms: Optional[int] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class UsageStats(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    slack_user_id: str  # 改名以保持一致性
    date: datetime
    messages_received: int = 0
    messages_sent: int = 0
    total_processing_time_ms: int = 0
    errors_count: int = 0
    
    # 新增字段用于保存更详细的信息
    message_type: Optional[str] = None  # 消息类型，如 "agent_workflow"
    subscription_id: Optional[str] = None  # 订阅ID
    external_subscription_id: Optional[str] = None  # 外部订阅ID
    message_ts: Optional[str] = None  # Slack消息时间戳
    deduction_time: Optional[datetime] = None  # 扣减时间
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class GitHubRepository(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    slack_user_id: Optional[str] = Field(None)
    slack_message_ts: str  # Associated Slack message timestamp
    slack_channel_id: str  # Slack channel where the message was sent
    
    # Repository information
    github_url: str
    owner: str
    repo_name: str
    branch: str = "main"
    url_type: str  # 'repository', 'gist', 'raw'
    
    # Processing information
    total_files: int = 0
    processed_files: int = 0
    total_size_bytes: int = 0
    markdown_content: str  # The generated markdown content
    
    # Metadata
    file_extensions: List[str] = []  # List of file extensions found
    processing_status: str = "pending"  # pending, processing, completed, failed
    error_message: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# Request/Response models
class SlackEventRequest(BaseModel):
    token: str
    team_id: str
    api_app_id: str
    event: Dict[str, Any]
    type: str
    event_id: str
    event_time: int

class SlackMessageEvent(BaseModel):
    type: str
    channel: str
    user: str
    text: str
    ts: str
    event_ts: str
    channel_type: str

class UserResponse(BaseModel):
    id: str
    slack_user_id: str
    name: Optional[str]
    email: Optional[str]
    subscription_status: SubscriptionStatus
    subscription_plan: SubscriptionPlan
    usage_count: int
    usage_limit: int
    created_at: datetime

# PayPal Models
class OrderType(str, Enum):
    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"

class DataAddonType(str, Enum):
    CREDITS_100 = "credits_100"
    CREDITS_300 = "credits_300"
    EXTRA_STORAGE = "extra_storage"
    PREMIUM_FEATURES = "premium_features"

class SubscriptionPlanType(str, Enum):
    BASE = "base"
    PRO = "pro"
    BUSINESS = "business"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"

class SubscriptionPlanDetails(BaseModel):
    plan_type: str
    price: float
    currency: str = "USD"
    daily_credits: Optional[int] = None
    monthly_credits: int
    description: str

class DataAddonDetails(BaseModel):
    addon_type: str
    price: float
    currency: str = "USD"
    credits: int
    description: str

class PayPalAmount(BaseModel):
    currency_code: str = "USD"
    value: str

class PayPalLink(BaseModel):
    href: str
    rel: str
    method: str

class PayPalPurchaseUnit(BaseModel):
    reference_id: str
    amount: PayPalAmount
    description: Optional[str] = None

class PayPalOrderRequest(BaseModel):
    # PayPal 处理器使用的字段
    is_subscription: bool = False
    subscription_plan_type: Optional[str] = None
    data_addon_type: Optional[str] = None
    description: str
    return_url: str
    cancel_url: str
    metadata: Optional[Dict[str, Any]] = None
    
    # 标准 PayPal API 字段（可选）
    intent: str = "CAPTURE"
    purchase_units: Optional[List[PayPalPurchaseUnit]] = None
    application_context: Optional[Dict[str, Any]] = None

class PayPalCapture(BaseModel):
    id: str
    status: str
    amount: PayPalAmount

class PayPalPayments(BaseModel):
    captures: List[PayPalCapture]

class PayPalOrderResponse(BaseModel):
    id: str
    status: str
    links: List[PayPalLink]
    success: bool = True
    error_message: Optional[str] = None
    order_details: Optional[Dict[str, Any]] = None
    subscription_id: Optional[str] = None
    approval_url: Optional[str] = None

class PayPalCaptureResponse(BaseModel):
    id: str
    status: str
    success: bool = True
    error_message: Optional[str] = None
    order_details: Optional[Dict[str, Any]] = None
    subscription_id: Optional[str] = None

class PayPalErrorResponse(BaseModel):
    success: bool = False
    error_message: str
    error_code: Optional[str] = None

class PDFProcessingStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class PDFProcessingTask(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    message_id: str
    user_id: str
    original_pdf_url: str
    status: PDFProcessingStatus
    txt_content: Optional[str] = None
    file_size: Optional[int] = None
    page_count: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class SubscriptionResponse(BaseModel):
    id: str
    plan: SubscriptionPlan
    status: SubscriptionStatus
    usage_count: int
    usage_limit: int
    expires_at: Optional[datetime]
    created_at: datetime