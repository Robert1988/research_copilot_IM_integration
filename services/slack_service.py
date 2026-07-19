import httpx
from typing import Optional, Dict, Any, List
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from services.database_service import db_service

from config import settings

class SlackService:
    def __init__(self):
        self.client_id = settings.SLACK_CLIENT_ID
        self.client_secret = settings.SLACK_CLIENT_SECRET
        self.redirect_uri = settings.OAUTH_REDIRECT_URI
        self.scopes = settings.SLACK_SCOPES

        # 多工作区支持：存储不同工作区的Bot Token
        self.workspace_tokens = {}
        self.workspace_clients = {}
        
    
    def add_workspace_token(self, team_id: str, bot_token: str):
        """添加工作区的Bot Token"""
        self.workspace_tokens[team_id] = bot_token
        self.workspace_clients[team_id] = WebClient(token=bot_token)
        print(f"✅ 已添加工作区 {team_id} 的Bot Token")
    
    async def initialize_workspaces(self):
        """初始化所有工作区配置"""
        try:
            from services.workspace_service import workspace_service
            workspaces = await workspace_service.get_active_workspaces()
            
            for workspace in workspaces:
                self.add_workspace_token(workspace.team_id, workspace.bot_token)
            
            print(f"✅ 已初始化 {len(workspaces)} 个工作区配置")
        except Exception as e:
            print(f"❌ 初始化工作区配置失败: {e}")
    
    def get_client_for_team(self, team_id: str) -> Optional[WebClient]:
        """根据team_id获取对应的WebClient"""
        if team_id in self.workspace_clients:
            return self.workspace_clients[team_id]
        # 如果没有找到对应的工作区客户端，返回默认客户端
        return None
    
    def _validate_bot_token(self, team_id: str) -> bool:
        """Validate bot token by testing auth for specific team"""
        try:
            client = self.get_client_for_team(team_id)
            if client:
                response = client.auth_test()
                if response["ok"]:
                    print(f"✅ Bot token valid for team {team_id} - Bot ID: {response.get('bot_id')}, Team: {response.get('team')}")
                    return True
                else:
                    print(f"❌ Bot token invalid for team {team_id}: {response.get('error')}")
                    return False
            else:
                print(f"❌ No client found for team {team_id}")
                return False
        except Exception as e:
            print(f"❌ Bot token validation failed for team {team_id}: {e}")
            return False
    
    def get_oauth_url(self, state: Optional[str] = None) -> str:
        """Generate Slack OAuth authorization URL"""
        scopes_str = ",".join(self.scopes)
        url = f"https://slack.com/oauth/v2/authorize"
        params = {
            "client_id": self.client_id,
            "scope": scopes_str,
            # "user_scope": "identity.basic",  # 明确指定 user scope
            "redirect_uri": self.redirect_uri
        }
        
        if state:
            params["state"] = state
        
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{url}?{query_string}"
    
    async def exchange_code_for_token(self, code: str) -> Optional[Dict[str, Any]]:
        """Exchange authorization code for access token"""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://slack.com/api/oauth.v2.access",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": self.redirect_uri
                    }
                )
                
                data = response.json()
                if data.get("ok"):
                    return data
                else:
                    print(f"Slack OAuth error: {data.get('error')}")
                    return None
                    
            except Exception as e:
                print(f"Error exchanging code for token: {e}")
                return None
    
    async def get_user_info(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Get user information using access token"""
        client = WebClient(token=access_token)
        
        try:
            # Get user identity
            response = client.users_identity()
            if response["ok"]:
                return response
            else:
                print(f"Error getting user info: {response.get('error')}")
                return None
                
        except SlackApiError as e:
            print(f"Slack API error getting user info: {e}")
            return None
    
    async def get_user_info_by_id(self, user_id: str, team_id: str ) -> Optional[Dict[str, Any]]:
        """Get user information using bot token and user ID"""
        # 根据team_id选择合适的客户端
        client = self.get_client_for_team(team_id)
        
        if not client and team_id:
            try:
                from services.database_service import db_service
                workspace = await db_service.get_workspace_by_team_id(team_id)
                if workspace and workspace.bot_token:
                    # 创建新的客户端并添加到workspace_clients中
                    client = WebClient(token=workspace.bot_token)
                    self.workspace_clients[team_id] = client
                    print(f"✅ 从数据库获取并创建了team_id {team_id} 的客户端")
                else:
                    print(f"❌ 数据库中没有找到team_id {team_id} 对应的工作区或bot_token")
            except Exception as e:
                print(f"❌ 从数据库获取工作区信息失败: {e}")

        if not client:
            print(f"❌ 没有找到team_id {team_id} 对应的客户端")
            return None
        
        try:
            # Get user info using bot token
            response = client.users_info(user=user_id)
            if response["ok"]:
                return response
            else:
                print(f"Error getting user info by ID: {response.get('error')}")
                return None
                
        except SlackApiError as e:
            print(f"Slack API error getting user info by ID: {e}")
            return None
    
    async def send_message(self, channel: str, text: str = None, blocks: List[Dict[str, Any]] = None, access_token: Optional[str] = None, team_id: str = None) -> bool:
        """Send message to Slack channel"""
        # 优先使用access_token，然后根据team_id获取对应的客户端
        if access_token:
            client = WebClient(token=access_token)
        elif team_id:
            client = self.get_client_for_team(team_id)
            if not client:
                try:
                    workspace = await db_service.get_workspace_by_team_id(team_id)
                    if workspace and workspace.bot_token:
                        # 创建新的客户端并添加到workspace_clients中
                        client = WebClient(token=workspace.bot_token)
                        self.workspace_clients[team_id] = client
                        print(f"✅ 从数据库获取并创建了team_id {team_id} 的客户端")
                    else:
                        print(f"❌ 数据库中没有找到team_id {team_id} 对应的工作区或bot_token")
                except Exception as e:
                    print(f"❌ 从数据库获取工作区信息失败: {e}")
        else:
            return False
            
        try:
            kwargs = {"channel": channel}
            if text:
                kwargs["text"] = text
            if blocks:
                kwargs["blocks"] = blocks
                
            response = client.chat_postMessage(**kwargs)
            return response["ok"]
            
        except SlackApiError as e:
            print(f"Error sending message: {e}")
            return False
    
    async def get_conversation_history(self, channel: str, access_token: Optional[str] = None, team_id: Optional[str] = None, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        """Get conversation history from a channel"""
        token = access_token
        
        # 如果没有提供access_token，尝试根据team_id获取bot_token
        if not token and team_id:
            try:
                workspace = await db_service.get_workspace_by_team_id(team_id)
                if workspace and workspace.bot_token:
                    token = workspace.bot_token
            except Exception as e:
                print(f"Error getting workspace token: {e}")
        
        if not token:
            print("No access token or bot token available")
            return None
            
        client = WebClient(token=token)
        
        try:
            response = client.conversations_history(
                channel=channel,
                limit=limit
            )
            
            if response["ok"]:
                return response["messages"]
            else:
                print(f"Error getting conversation history: {response.get('error')}")
                return None
                
        except SlackApiError as e:
            print(f"Slack API error getting conversation history: {e}")
            return None
    
    async def get_full_conversation_history(self, channel: str, access_token: Optional[str] = None, team_id: Optional[str] = None, limit: int = None) -> Optional[List[Dict[str, Any]]]:
        """Get conversation history from a channel with optional limit"""
        token = access_token
        
        # 如果没有提供access_token，尝试根据team_id获取bot_token
        if not token and team_id:
            try:
                workspace = await db_service.get_workspace_by_team_id(team_id)
                if workspace and workspace.bot_token:
                    token = workspace.bot_token
            except Exception as e:
                print(f"Error getting workspace token: {e}")
        
        if not token:
            print("No access token or bot token available")
            return None
            
        client = WebClient(token=token)
        all_messages = []
        cursor = None
        
        try:
            while True:
                # Get messages with pagination
                kwargs = {
                    "channel": channel,
                    "limit": min(200, limit) if limit else 200  # Maximum allowed by Slack API or user limit
                }
                if cursor:
                    kwargs["cursor"] = cursor
                
                response = client.conversations_history(**kwargs)
                
                if not response["ok"]:
                    error_msg = response.get('error')
                    print(f"Error getting conversation history: {error_msg}")
                    
                    # Handle specific permission errors gracefully
                    if error_msg == 'missing_scope':
                        needed_scopes = response.get('needed', 'channels:history,groups:history,mpim:history,im:history')
                        provided_scopes = response.get('provided', 'unknown')
                        print(f"Missing required scopes. Needed: {needed_scopes}, Provided: {provided_scopes}")
                        return None
                    break
                
                messages = response.get("messages", [])
                all_messages.extend(messages)
                
                # If we have a limit and reached it, break
                if limit and len(all_messages) >= limit:
                    all_messages = all_messages[:limit]
                    break
                
                # Check if there are more messages
                if not response.get("has_more", False):
                    break
                    
                cursor = response.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            
            # Sort messages by timestamp (newest first for recent messages)
            all_messages.sort(key=lambda x: float(x.get("ts", 0)), reverse=True)
            return all_messages
                
        except SlackApiError as e:
            print(f"Slack API error getting full conversation history: {e}")
            return None
    
    def format_conversation_history(self, messages: List[Dict[str, Any]], user_id: str, max_message_length: int = None) -> str:
        """Format conversation history into readable text"""
        if not messages:
            return "No conversation history found."
        
        formatted_messages = []
        for msg in messages:
            # Skip bot messages and system messages
            if msg.get("subtype") in ["bot_message", "channel_join", "channel_leave"]:
                continue
                
            sender = msg.get("user", "Unknown")
            text = msg.get("text", "")
            timestamp = msg.get("ts", "")
            
            # Convert timestamp to readable format
            try:
                import datetime
                dt = datetime.datetime.fromtimestamp(float(timestamp))
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                time_str = timestamp
            
            # Determine if it's the user or the bot
            if sender == user_id:
                sender_label = "You"
            else:
                sender_label = "Bot"
            
            # Truncate message if max_message_length is specified
            if max_message_length and len(text) > max_message_length:
                text = text[:max_message_length] + "..."
            
            if text.strip():
                formatted_messages.append(f"[{time_str}] {sender_label}: {text}")
        
        if not formatted_messages:
            return "No conversation messages found."
        
        return "\n".join(formatted_messages)
    
    async def open_im_channel(self, user_id: str, access_token: Optional[str] = None, team_id: Optional[str] = None) -> Optional[str]:
        """Open IM channel with user"""
        token = access_token
        
        # 如果没有提供access_token，尝试根据team_id获取bot_token
        if not token and team_id:
            try:
                workspace = await db_service.get_workspace_by_team_id(team_id)
                if workspace and workspace.bot_token:
                    token = workspace.bot_token
            except Exception as e:
                print(f"Error getting workspace token: {e}")
        
        if not token:
            print("No access token or bot token available")
            return None
            
        client = WebClient(token=token)
        
        try:
            response = client.conversations_open(users=user_id)
            
            if response["ok"]:
                return response["channel"]["id"]
            else:
                print(f"Error opening IM channel: {response.get('error')}")
                return None
                
        except SlackApiError as e:
            print(f"Slack API error opening IM channel: {e}")
            return None
    
    async def send_direct_message(self, user_id: str, text: str = None, blocks: List[Dict[str, Any]] = None, team_id: str = None) -> bool:
        """Send direct message to user"""
        try:
            print(f"发送直接消息给用户 {user_id} team {team_id}")
            # 根据team_id选择合适的客户端和token
            client = self.get_client_for_team(team_id)

            # 如果没有找到对应的客户端，尝试从数据库获取bot_token
            if not client and team_id:
                try:
                    from services.database_service import db_service
                    workspace = await db_service.get_workspace_by_team_id(team_id)
                    if workspace and workspace.bot_token:
                        # 创建新的客户端并添加到workspace_clients中
                        client = WebClient(token=workspace.bot_token)
                        self.workspace_clients[team_id] = client
                        print(f"✅ 从数据库获取并创建了team_id {team_id} 的客户端")
                    else:
                        print(f"❌ 数据库中没有找到team_id {team_id} 对应的工作区或bot_token")
                except Exception as e:
                    print(f"❌ 从数据库获取工作区信息失败: {e}")

            if not client:
                print(f"❌ 没有找到team_id {team_id} 对应的客户端")
                return False
            
            # 获取对应的token - 优先从数据库获取
            token = None
            print(f"team_id debug: {team_id}")
            if team_id:
                # 从数据库获取workspace的bot_token
                from services.database_service import db_service
                print(f"team_id debug: {team_id}")
                workspace = await db_service.get_workspace_by_team_id(team_id)
                if workspace:
                    token = workspace.bot_token
                    print(f"🔍 从数据库获取Bot Token: {token[:20]}..." if token else "❌ 数据库中没有Bot Token")
                else:
                    print(f"❌ 数据库中没有找到team_id {team_id} 对应的工作区")
                    # 回退到内存中的token
                    token = self.workspace_tokens.get(team_id)
            else:
                # 如果没有team_id，尝试获取第一个可用的token
                if self.workspace_tokens:
                    token = next(iter(self.workspace_tokens.values()))
                else:
                    print("❌ 没有可用的Bot Token")
                    return False
            
            # 诊断：检查token和工作区信息
            print(f"🔍 最终使用的Bot Token: {token[:20]}..." if token else "❌ 没有Bot Token")
            print(f"🔍 目标工作区ID: {team_id}")
            
            # 诊断：先检查用户是否存在
            print(f"🔍 尝试获取用户 {user_id} 的信息...")
            # 如果team_id为None，尝试从token中获取工作区信息
            effective_team_id = team_id
            if not effective_team_id and token:
                try:
                    test_client = WebClient(token=token)
                    auth_response = test_client.auth_test()
                    if auth_response["ok"]:
                        effective_team_id = auth_response.get('team_id')
                        print(f"🔍 从Bot Token获取工作区ID: {effective_team_id}")
                except Exception as e:
                    print(f"❌ 从Bot Token获取工作区ID失败: {e}")
            
            user_info = await self.get_user_info_by_id(user_id, effective_team_id)
            if user_info:
                user_data = user_info.get('user', {})
                print(f"✅ 用户 {user_id} 存在: {user_data.get('name', 'unknown')}")
                print(f"   用户状态: deleted={user_data.get('deleted', False)}, is_bot={user_data.get('is_bot', False)}")
            else:
                print(f"❌ 无法获取用户 {user_id} 的信息")
                print("🔍 可能的原因:")
                print("   1. 用户ID不正确或用户不在当前工作区")
                print("   2. Bot Token对应的工作区与用户不匹配")
                print("   3. 用户已被删除或停用")
                print("   4. Bot缺少users:read权限")
                
                # 尝试验证bot token
                print("🔍 验证Bot Token...")
                try:
                    test_client = WebClient(token=token)
                    auth_response = test_client.auth_test()
                    if auth_response["ok"]:
                        print(f"✅ Bot Token有效 - 工作区: {auth_response.get('team', 'unknown')}")
                        print(f"   Bot用户ID: {auth_response.get('user_id', 'unknown')}")
                        print(f"   工作区ID: {auth_response.get('team_id', 'unknown')}")
                    else:
                        print(f"❌ Bot Token验证失败: {auth_response.get('error')}")
                except Exception as auth_error:
                    print(f"❌ Bot Token验证出错: {auth_error}")
            
            # First, open IM channel with the user
            channel_id = await self.open_im_channel(user_id, token)
            if not channel_id:
                print(f"Failed to open IM channel with user {user_id}")
                return False
            
            # Send message to the IM channel
            return await self.send_message(channel_id, text, blocks, token)
            
        except Exception as e:
            print(f"Error sending direct message to user {user_id}: {e}")
            return False
    
    def verify_request_signature(self, timestamp: str, body: str, signature: str) -> bool:
        """Verify Slack request signature"""
        import hmac
        import hashlib
        
        if not settings.SLACK_SIGNING_SECRET:
            return False
        
        # Create signature
        sig_basestring = f"v0:{timestamp}:{body}"
        my_signature = 'v0=' + hmac.new(
            settings.SLACK_SIGNING_SECRET.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(my_signature, signature)
    
    async def get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file information from Slack API"""
        try:
            if not self.bot_client:
                print("Bot client not initialized")
                return None
                
            response = self.bot_client.files_info(file=file_id)
            if response["ok"]:
                return response["file"]
            else:
                print(f"Failed to get file info: {response.get('error')}")
                return None
                
        except SlackApiError as e:
            print(f"Slack API error getting file info: {e}")
            return None
        except Exception as e:
            print(f"Error getting file info: {e}")
            return None
    
    async def download_file(self, file_url: str, team_id: Optional[str] = None) -> Optional[bytes]:
        """Download file content from Slack"""
        try:
            # 根据team_id获取对应的bot_token
            token = None
            if team_id:
                try:
                    workspace = await db_service.get_workspace_by_team_id(team_id)
                    if workspace and workspace.bot_token:
                        token = workspace.bot_token
                except Exception as e:
                    print(f"Error getting workspace token: {e}")
            
            # 如果没有找到token，尝试使用第一个可用的token
            if not token and self.workspace_tokens:
                token = next(iter(self.workspace_tokens.values()))
            
            if not token:
                print("Bot token not available")
                return None
                
            headers = {
                "Authorization": f"Bearer {token}"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(file_url, headers=headers)
                if response.status_code == 200:
                    return response.content
                else:
                    print(f"Failed to download file: {response.status_code}")
                    return None
                    
        except Exception as e:
            print(f"Error downloading file: {e}")
            return None

# Global Slack service instance
slack_service = SlackService()