from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_database
from models import User, Subscription, MessageLog, UsageStats, SubscriptionStatus, SubscriptionPlan, MessageType, GitHubRepository, SlackWorkspace

class DatabaseService:
    def __init__(self):
        self.db: Optional[AsyncIOMotorDatabase] = None
    
    async def get_db(self):
        if self.db is None:
            self.db = await get_database()
            # 初始化工作区集合
            self.workspaces_collection = self.db.workspaces
        return self.db

    # User operations
    async def create_user(self, user_data: Dict[str, Any]) -> User:
        db = await self.get_db()
        user_data["created_at"] = datetime.utcnow()
        user_data["updated_at"] = datetime.utcnow()
        
        result = await db.users.insert_one(user_data)
        user_data["_id"] = str(result.inserted_id)
        return User(**user_data)
    
    async def get_user_by_slack_id(self, slack_user_id: str, slack_team_id: str = None) -> Optional[User]:
        db = await self.get_db()
        
        # 如果提供了team_id，使用复合查询；否则只用user_id查询（向后兼容）
        if slack_team_id:
            query = {"slack_user_id": slack_user_id, "slack_team_id": slack_team_id}
        else:
            query = {"slack_user_id": slack_user_id}
            
        user_data = await db.users.find_one(query)
        if user_data:
            user_data["_id"] = str(user_data["_id"])
            
            # Map display_name to name field for User model compatibility
            if "display_name" in user_data and "name" not in user_data:
                user_data["name"] = user_data["display_name"]
            
            # Map user_token to access_token field for User model compatibility
            if "user_token" in user_data and "access_token" not in user_data:
                user_data["access_token"] = user_data["user_token"]
            
            return User(**user_data)
        return None
    
    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        db = await self.get_db()
        user_data = await db.users.find_one({"_id": ObjectId(user_id)})
        if user_data:
            user_data["_id"] = str(user_data["_id"])
            
            # Map display_name to name field for User model compatibility
            if "display_name" in user_data and "name" not in user_data:
                user_data["name"] = user_data["display_name"]
            
            # Map user_token to access_token field for User model compatibility
            if "user_token" in user_data and "access_token" not in user_data:
                user_data["access_token"] = user_data["user_token"]
            
            # Provide default slack_team_id if missing
            if "slack_team_id" not in user_data:
                user_data["slack_team_id"] = ""  # Should be empty or handled by the caller
            
            return User(**user_data)
        return None
    
    async def update_user(self, user_id: str, update_data: Dict[str, Any]) -> Optional[User]:
        db = await self.get_db()
        update_data["updated_at"] = datetime.utcnow()
        
        result = await db.users.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": update_data},
            return_document=True
        )
        
        if result:
            result["_id"] = str(result["_id"])
            
            # Map display_name to name field for User model compatibility
            if "display_name" in result and "name" not in result:
                result["name"] = result["display_name"]
            
            # Map user_token to access_token field for User model compatibility
            if "user_token" in result and "access_token" not in result:
                result["access_token"] = result["user_token"]
            
            # Provide default slack_team_id if missing
            if "slack_team_id" not in result:
                result["slack_team_id"] = ""  # Should be empty or handled by the caller
            
            return User(**result)
        return None

    # Subscription operations
    async def create_subscription(self, subscription_data: Dict[str, Any]) -> Subscription:
        db = await self.get_db()
        subscription_data["created_at"] = datetime.utcnow()
        subscription_data["updated_at"] = datetime.utcnow()
        
        result = await db.subscriptions.insert_one(subscription_data)
        subscription_data["_id"] = str(result.inserted_id)
        return Subscription(**subscription_data)
    
    async def get_user_subscription(self, slack_user_id: str, subscription_id: str = None) -> Optional[Subscription]:
        db = await self.get_db()
        if subscription_id:
            subscription_data = await db.subscriptions.find_one(
                {"slack_user_id": slack_user_id, "external_subscription_id":subscription_id},
                sort=[("created_at", -1)]
            )
        else:
            subscription_data = await db.subscriptions.find_one(
                {"slack_user_id": slack_user_id, "status": "active"},
                sort=[("created_at", -1)]
            )
        if subscription_data:
            subscription_data["_id"] = str(subscription_data["_id"])
            return Subscription(**subscription_data)
        return None
    
    async def get_user_subscriptions(self, slack_user_id: str) -> List[Subscription]:
        """获取用户的所有订阅记录"""
        db = await self.get_db()
        subscriptions_data = await db.subscriptions.find(
            {"slack_user_id": slack_user_id},
            sort=[("created_at", -1)]
        ).to_list(None)
        
        subscriptions = []
        for sub_data in subscriptions_data:
            sub_data["_id"] = str(sub_data["_id"])
            subscriptions.append(Subscription(**sub_data))
        return subscriptions
    
    async def get_user_active_subscriptions(self, user_id: str) -> List[Subscription]:
        """获取用户的所有活跃订阅"""
        db = await self.get_db()
        subscriptions_data = await db.subscriptions.find(
            {"slack_user_id": user_id, "status": "active"},
            sort=[("created_at", -1)]
        ).to_list(None)
        
        subscriptions = []
        for sub_data in subscriptions_data:
            sub_data["_id"] = str(sub_data["_id"])
            subscriptions.append(Subscription(**sub_data))
        return subscriptions
    
    async def update_subscription(self, subscription_id: str, update_data: Dict[str, Any]) -> Optional[Subscription]:
        db = await self.get_db()
        update_data["updated_at"] = datetime.utcnow()
        
        result = await db.subscriptions.find_one_and_update(
            {"_id": ObjectId(subscription_id)},
            {"$set": update_data},
            return_document=True
        )
        
        if result:
            result["_id"] = str(result["_id"])
            return Subscription(**result)
        return None

    # Message log operations
    async def create_message_log(self, message_data: Dict[str, Any]) -> MessageLog:
        db = await self.get_db()
        message_data["timestamp"] = datetime.utcnow()
        
        result = await db.message_logs.insert_one(message_data)
        message_data["_id"] = str(result.inserted_id)
        return MessageLog(**message_data)
    
    async def get_user_message_history(self, user_id: str, limit: int = 50) -> List[MessageLog]:
        db = await self.get_db()
        cursor = db.message_logs.find(
            {"slack_user_id": user_id}
        ).sort("timestamp", -1).limit(limit)
        
        messages = []
        async for message_data in cursor:
            message_data["_id"] = str(message_data["_id"])
            messages.append(MessageLog(**message_data))
        
        return messages

    # Usage stats operations
    async def update_usage_stats(self, slack_user_id: str, message_type: str, processing_time_ms: int = 0, error: bool = False, 
                                subscription_id: Optional[str] = None, external_subscription_id: Optional[str] = None, 
                                message_ts: Optional[str] = None, deduction_time: Optional[datetime] = None):
        db = await self.get_db()
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 准备更新操作
        set_data = {
            "updated_at": datetime.utcnow()
        }
        
        # 如果提供了额外信息，也保存到set_data中
        if subscription_id:
            set_data["subscription_id"] = subscription_id
        if external_subscription_id:
            set_data["external_subscription_id"] = external_subscription_id
        if message_ts:
            set_data["message_ts"] = message_ts
        if deduction_time:
            set_data["deduction_time"] = deduction_time
        if message_type:
            set_data["message_type"] = message_type
        
        inc_data = {}
        
        # 根据消息类型更新计数
        if message_type == MessageType.RECEIVED or message_type == "received":
            inc_data["messages_received"] = 1
        elif message_type == MessageType.SENT or message_type == "sent":
            inc_data["messages_sent"] = 1
        elif message_type == "agent_workflow":
            # agent_workflow 可以算作发送的消息
            inc_data["messages_sent"] = 1
        
        if processing_time_ms > 0:
            inc_data["total_processing_time_ms"] = processing_time_ms
        
        if error:
            inc_data["errors_count"] = 1
        
        # 构建更新文档 - 注意：slack_user_id 只在 $setOnInsert 中设置，避免冲突
        set_on_insert = {
            "slack_user_id": slack_user_id,  # 只在插入时设置
            "date": today,
            "created_at": datetime.utcnow()
        }
        
        # 为未被增量更新的字段添加默认值
        if "messages_received" not in inc_data:
            set_on_insert["messages_received"] = 0
        if "messages_sent" not in inc_data:
            set_on_insert["messages_sent"] = 0
        if "total_processing_time_ms" not in inc_data:
            set_on_insert["total_processing_time_ms"] = 0
        if "errors_count" not in inc_data:
            set_on_insert["errors_count"] = 0
        
        update_doc = {
            "$set": set_data,
            "$setOnInsert": set_on_insert
        }
        
        # 只有在有字段需要增量更新时才添加$inc
        if inc_data:
            update_doc["$inc"] = inc_data
        
        await db.usage_stats.update_one(
            {"slack_user_id": slack_user_id, "date": today},
            update_doc,
            upsert=True
        )
    
    async def get_user_usage_stats(self, user_id: str, days: int = 30) -> List[UsageStats]:
        db = await self.get_db()
        start_date = datetime.utcnow() - timedelta(days=days)
        
        cursor = db.usage_stats.find(
            {"slack_user_id": user_id, "date": {"$gte": start_date}}
        ).sort("date", -1)
        
        stats = []
        async for stat_data in cursor:
            stat_data["_id"] = str(stat_data["_id"])
            stats.append(UsageStats(**stat_data))
        
        return stats
    
    async def get_user_monthly_usage(self, slack_user_id: str) -> int:
        """Get user's current month usage count"""
        db = await self.get_db()
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        pipeline = [
            {
                "$match": {
                    "slack_user_id": slack_user_id,
                    "date": {"$gte": start_of_month}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_messages": {"$sum": {"$add": ["$messages_received", "$messages_sent"]}}
                }
            }
        ]
        
        result = await db.usage_stats.aggregate(pipeline).to_list(1)
        return result[0]["total_messages"] if result else 0

    # GitHub Repository operations
    async def create_github_repository(self, repo_data: Dict[str, Any]) -> GitHubRepository:
        """Create a new GitHub repository record"""
        db = await self.get_db()
        repo_data["created_at"] = datetime.utcnow()
        repo_data["updated_at"] = datetime.utcnow()
        
        result = await db.github_repositories.insert_one(repo_data)
        repo_data["_id"] = str(result.inserted_id)
        return GitHubRepository(**repo_data)
    
    async def get_github_repository_by_message(self, user_id: str, slack_message_ts: str) -> Optional[GitHubRepository]:
        """Get GitHub repository by user ID and Slack message timestamp"""
        db = await self.get_db()
        repo_data = await db.github_repositories.find_one({
            "slack_user_id": user_id,
            "slack_message_ts": slack_message_ts
        })
        if repo_data:
            repo_data["_id"] = str(repo_data["_id"])
            return GitHubRepository(**repo_data)
        return None
    
    async def get_github_repositories_by_user(self, user_id: str, limit: int = 50) -> List[GitHubRepository]:
        """Get GitHub repositories by user ID"""
        db = await self.get_db()
        cursor = db.github_repositories.find({"slack_user_id": user_id}).sort("created_at", -1).limit(limit)
        repositories = []
        
        async for repo_data in cursor:
            repo_data["_id"] = str(repo_data["_id"])
            repositories.append(GitHubRepository(**repo_data))
        
        return repositories
    
    async def update_github_repository(self, repo_id: str, update_data: Dict[str, Any]) -> Optional[GitHubRepository]:
        """Update GitHub repository record"""
        db = await self.get_db()
        update_data["updated_at"] = datetime.utcnow()
        
        result = await db.github_repositories.find_one_and_update(
            {"_id": ObjectId(repo_id)},
            {"$set": update_data},
            return_document=True
        )
        
        if result:
            result["_id"] = str(result["_id"])
            return GitHubRepository(**result)
        return None
    
    async def get_slack_user_id(self, user_id: str) -> Optional[str]:
        """Get Slack user ID by user ID"""
        db = await self.get_db()
        user_data = await db.users.find_one({"_id": ObjectId(user_id)})
        if user_data:
            return user_data.get("slack_user_id")
        return None

    async def get_github_repository_by_url(self, user_id: str, github_url: str) -> Optional[GitHubRepository]:
        """Get GitHub repository by user ID and GitHub URL"""
        db = await self.get_db()
        repo_data = await db.github_repositories.find_one({
            "slack_user_id": user_id,
            "github_url": github_url,
            "markdown_content": {"$exists": True, "$ne": ""}
        })
        if repo_data:
            repo_data["_id"] = str(repo_data["_id"])
            return GitHubRepository(**repo_data)
        return None

    # Workspace operations
    async def create_workspace(self, workspace_data: Dict[str, Any]) -> SlackWorkspace:
        """创建新的工作区配置"""
        db = await self.get_db()
        workspace_data["installed_at"] = datetime.utcnow()
        workspace_data["is_active"] = workspace_data.get("is_active", True)
        
        result = await db.workspaces.insert_one(workspace_data)
        workspace_data["_id"] = str(result.inserted_id)
        return SlackWorkspace(**workspace_data)
    
    async def get_workspace_by_team_id(self, team_id: str) -> Optional[SlackWorkspace]:
        """根据team_id获取工作区配置"""
        db = await self.get_db()
        workspace_data = await db.workspaces.find_one({"team_id": team_id})
        if workspace_data:
            workspace_data["_id"] = str(workspace_data["_id"])
            return SlackWorkspace(**workspace_data)
        return None
    
    async def get_all_workspaces(self) -> List[SlackWorkspace]:
        """获取所有工作区配置"""
        db = await self.get_db()
        workspaces = []
        async for workspace_data in db.workspaces.find({}):
            workspace_data["_id"] = str(workspace_data["_id"])
            workspaces.append(SlackWorkspace(**workspace_data))
        return workspaces
    
    async def update_workspace(self, team_id: str, update_data: Dict[str, Any]) -> Optional[SlackWorkspace]:
        """更新工作区配置"""
        db = await self.get_db()
        
        # 移除None值
        update_data = {k: v for k, v in update_data.items() if v is not None}
        
        if update_data:
            result = await db.workspaces.update_one(
                {"team_id": team_id},
                {"$set": update_data}
            )
            if result.modified_count > 0:
                return await self.get_workspace_by_team_id(team_id)
        return None
    
    async def deactivate_workspace(self, team_id: str) -> bool:
        """停用工作区"""
        db = await self.get_db()
        result = await db.workspaces.update_one(
            {"team_id": team_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0

# Global database service instance
db_service = DatabaseService()