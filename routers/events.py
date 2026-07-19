from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
from starlette.requests import ClientDisconnect
import json
import logging
from datetime import datetime
from typing import Dict, Any

from services.slack_service import slack_service
from services.database_service import db_service
from services.message_service import message_service
from models import SlackEventRequest, SlackMessageEvent, User, MessageType
from database import get_database
from services.subscription_service import subscription_service
from models import SubscriptionPlan

logger = logging.getLogger(__name__)

router = APIRouter()

async def store_pdf_content_to_mongodb(slack_user_id: str, file_name: str, file_url: str, extracted_text: str, message_ts: str = None):
    """Store extracted PDF content to MongoDB"""
    try:
        db = await get_database()
        
        # Create document to store in MongoDB
        pdf_document = {
            "slack_user_id": slack_user_id,
            "file_name": file_name,
            "file_url": file_url,
            "extracted_text": extracted_text,
            "text_length": len(extracted_text),
            "word_count": len(extracted_text.split()),
            "processed_at": datetime.utcnow(),
            "source": "slack_upload"
        }
        
        # Add slack_message_ts if provided
        if message_ts:
            pdf_document["slack_message_ts"] = message_ts
            logger.info(f"Adding Slack message ID to PDF document: {message_ts}")
        
        # Insert into pdf_documents collection
        result = await db.pdf_documents.insert_one(pdf_document)
        
        logger.info(f"Successfully stored PDF content to MongoDB with ID: {result.inserted_id}")
        return result.inserted_id
        
    except Exception as e:
        logger.error(f"Error storing PDF content to MongoDB: {e}")
        raise

@router.post("/events")
async def handle_slack_events(request: Request, background_tasks: BackgroundTasks):
    """Handle Slack Events API callbacks"""
    
    logger.info("🔄 Received Slack event request")
    
    try:
        # Get request body and headers with error handling
        body = await request.body()
        body_str = body.decode('utf-8')
        logger.info(f"📥 Request body length: {len(body_str)} characters")
    except ClientDisconnect:
        # Client disconnected before we could read the body
        logger.warning("⚠️ Client disconnected before reading request body")
        return {"status": "client_disconnected"}
    except Exception as e:
        logger.error(f"❌ Error reading request body: {e}")
        raise HTTPException(status_code=400, detail="Failed to read request body")
    
    # Verify request signature
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    
    logger.info(f"🔐 Verifying request signature - timestamp: {timestamp[:10]}..., signature: {signature[:20]}...")
    
    if not slack_service.verify_request_signature(timestamp, body_str, signature):
        logger.error("❌ Request signature verification failed")
        raise HTTPException(status_code=401, detail="Invalid request signature")
    
    logger.info("✅ Request signature verification successful")
    
    try:
        data = json.loads(body_str)
        logger.info(f"📋 JSON parsing successful - event type: {data.get('type')}")
    except json.JSONDecodeError:
        logger.error("❌ JSON parsing failed")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Handle URL verification challenge
    if data.get("type") == "url_verification":
        logger.info("🔗 Handling URL verification challenge")
        return PlainTextResponse(data.get("challenge", ""))
    
    # Verify workspace
    # logger.info(f"🔍 Verifying event data  {data}")
    team_id = data.get("team_id")
    if team_id:
        from services.workspace_service import workspace_service
        workspace = await workspace_service.get_workspace(team_id)
        if not workspace or not workspace.is_active:
            logger.warning(f"❌ Received event from unconfigured or inactive workspace: {team_id}")
            return {"status": "ignored"}
    
    # Handle event callbacks
    if data.get("type") == "event_callback":
        event = data.get("event", {})
        event_type = event.get("type")
        logger.info(f"📨 Handling event callback - event type: {event_type}")
        
        # Handle message events in DM channels
        if event_type == "message" and event.get("channel_type") == "im":
            logger.info(f"💬 Detected DM message event - user: {event.get('user')}, channel: {event.get('channel')}")
            
            # Log detailed event information for debugging
            logger.info(f"🔍 Message details - subtype: {event.get('subtype')}, bot_id: {event.get('bot_id')}, files: {len(event.get('files', []))}")
            
            # Ignore bot messages and message changes, but allow file_share from users
            if event.get("bot_id") or (event.get("subtype") and event.get("subtype") not in ["file_share"]):
                logger.info(f"🤖 Ignoring bot message or message change - subtype: {event.get('subtype')}, bot_id: {event.get('bot_id')}")
                return {"status": "ignored"}
            
            # Process message in background
            logger.info("🔄 Adding DM message to background processing queue")
            background_tasks.add_task(process_dm_message, event, team_id)
        
        # Handle file shared events
        elif event_type == "file_shared":
            logger.info(f"📁 Detected file shared event - file ID: {event.get('file_id')}")
            # Process file upload in background
            background_tasks.add_task(process_file_shared, event, team_id)
        
        # Handle app home opened events
        elif event_type == "app_home_opened":
            logger.info(f"🏠 Detected App Home opened event - user: {event.get('user')}")
            # Process app home opened in background
            background_tasks.add_task(process_app_home_opened, event, team_id)
        
        else:
            logger.info(f"❓ Unhandled event type: {event_type}")
    
    logger.info("✅ Event processing completed")
    return {"status": "ok"}

async def get_welcome_message() -> str:
    """Get the standard welcome message used for hello responses and app home opened events"""
    return """👋 Hello! I'm your AI coding assistant that transforms ideas into *working code* and *beyond*!

🔬 *What I Do:*
• Idea Implementation - Transform ideas into working code
• Execution and Insights - Run code and generate actionable insights
• Auto-Generated Repositories - All code saved to GitHub with execution logs

🎁 *Your Free Trial Benefits:*
• 20 AI-generated messages (total)
• Message processing capabilities
• File analysis features
• Conversation history

💡 *Pro Tips:* Share relevant PDFs and existing code repositories to provide rich context - this helps me understand your methodology and generate more targeted implementations!

📊 *Usage Example:*
*You:* "@Agent Design a Bayesian A/B testing framework with sequential analysis for early stopping. Here's my current setup: https://github.com/yourname/ab-testing and relevant paper: [PDF doc]"

*Me:* I'll analyze your codebase and document, implement sequential Bayesian testing with proper stopping rules, generate synthetic data for validation, run comprehensive simulations, and deliver a complete experimental framework with final result analysis!

🚀 Ready to start? Just type *@Agent* followed by your new hypotheses or ideas!
💡 Use `status` to check your usage and account details, or `subscribe` to explore upgrade options."""


async def get_registration_message() -> str:
    """Get registration message for unregistered users (legacy function)"""
    return (
        "👋 *Welcome to our Slack Assistant!*\n\n"
        "🔄 *Account Setup Required*\n"
        "Your account wasn't created during app installation.\n\n"
        "*📱 Quick Fix:*\n"
        "1. Remove this app from your workspace\n"
        "2. Reinstall the app to automatically create your account\n"
        "3. Start using immediately with 20 free AI messages!\n\n"
        "💡 *Alternative:* Contact support if reinstalling doesn't work."
    )


async def handle_unregistered_user(slack_user_id: str, team_id: str, channel_id: str = None, is_dm: bool = True):
    """Handle interaction with unregistered users - automatically register them"""
    try:
        logger.info(f"🔄 自动注册未注册用户: {slack_user_id}, team_id: {team_id}")
        
        # 尝试获取用户信息 - 使用bot token和users.info API，传递team_id确保使用正确的工作区token
        user_info = await slack_service.get_user_info_by_id(slack_user_id, team_id)
        
        # 初始化用户数据，即使无法获取详细信息也能正常注册
        user_data = {
            "slack_user_id": slack_user_id,
            "slack_team_id": team_id,  # 使用传入的team_id
            "access_token": "",  # 在事件处理中没有用户访问令牌，使用空字符串
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # 如果成功获取用户信息，则填充详细数据
        if user_info:
            logger.info(f"✅ 成功获取用户 {slack_user_id} 的详细信息")
            user_profile = user_info.get("user", {}).get("profile", {})
            user_data.update({
                "email": user_profile.get("email"),
                "display_name": user_profile.get("display_name") or user_profile.get("real_name"),
                "avatar_url": user_profile.get("image_192")
            })
        else:
            logger.warning(f"⚠️ 无法获取用户 {slack_user_id} 的详细信息，使用基本信息注册")
            # 使用默认值
            user_data.update({
                "email": None,
                "display_name": f"User_{slack_user_id[-8:]}",  # 使用用户ID后8位作为默认显示名
                "avatar_url": None
            })
        
        user = await db_service.create_user(user_data)
        logger.info(f"✅ 自动创建用户: {slack_user_id}")
        
        # 为新用户创建免费试用订阅 - 使用与OAuth回调相同的逻辑
        subscription = await subscription_service.create_subscription(
            str(user.id), 
            SubscriptionPlan.FREE, 
            slack_user_id, 
            None
        )
        logger.info(f"✅ 为用户 {slack_user_id} 创建免费订阅")
        
        # 发送欢迎消息
        welcome_message = (
            "🎉 *Welcome to our Slack Assistant!*\n\n"
            "✅ *Account automatically created!*\n"
            "Your free trial account has been set up and is ready to use.\n\n"
            "*🎁 Your Free Trial Benefits:*\n"
            "• 20 AI-generated messages (total)\n"
            "• Message processing capabilities\n"
            "• File analysis features\n"
            "• Conversation history\n\n"
            "*🚀 What you can do now:*\n"
            "• Send me any message to start chatting\n"
            "• Upload files for analysis\n"
            "• Use `help` to see all available commands\n"
            "• Use `status` to check your usage and account details\n"
            "• Use `subscribe` to explore upgrade options\n\n"
            "💡 *Tip:* Just start typing to begin!"
        )
        
        if is_dm and channel_id:
            await slack_service.send_message(
                channel=channel_id,
                text=welcome_message,
                access_token=None  # Use bot token
            )
        else:
            await slack_service.send_direct_message(slack_user_id, welcome_message, team_id=team_id)
            
        logger.info(f"✅ 已向用户 {slack_user_id} 发送自动注册欢迎消息")
        
    except Exception as e:
        logger.error(f"❌ 自动注册用户时发生错误: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        
        # 发送错误消息
        error_message = (
            "❌ *Account Setup Failed*\n\n"
            "We encountered an error while setting up your account.\n"
            "Please try removing and reinstalling the app, or contact support."
        )
        
        try:
            if is_dm and channel_id:
                await slack_service.send_message(
                    channel=channel_id,
                    text=error_message,
                    access_token=None
                )
            else:
                await slack_service.send_direct_message(slack_user_id, error_message, team_id=team_id)
        except Exception as send_error:
            logger.error(f"❌ 发送错误消息失败: {send_error}")


async def ensure_user_subscription(user: User) -> bool:
    """Ensure user has a subscription, create one if missing"""
    try:
        subscription = await db_service.get_user_subscription(user.slack_user_id)
        if not subscription:
            subscription = await subscription_service.create_subscription(
                user.id, SubscriptionPlan.FREE, user.slack_user_id, None
            )
            logger.info(f"✅ 为用户 {user.slack_user_id} 创建了免费订阅")
        return True
    except Exception as e:
        logger.error(f"❌ 创建用户订阅失败: {e}")
        return False


async def check_user_active_status(user: User, slack_user_id: str, team_id: str, channel_id: str = None, is_dm: bool = True) -> bool:
    """Check if user is active and send appropriate message if not"""
    if not user.is_active:
        inactive_message = "❌ Your account is inactive. Please contact support."
        
        if is_dm and channel_id:
            await slack_service.send_message(
                channel=channel_id,
                text=inactive_message,
                access_token=None  # Use bot token
            )
        else:
            await slack_service.send_direct_message(slack_user_id, inactive_message, team_id=team_id)
        return False
    return True


async def process_app_home_opened(event: Dict[str, Any], team_id: str):
    """Process app home opened event - send welcome message to user"""
    try:
        slack_user_id = event.get("user")
        
        logger.info(f"🏠 处理App Home打开事件 - 用户: {slack_user_id}")
        
        if not slack_user_id:
            logger.error("❌ App Home事件缺少用户ID")
            return
        
        # Find user in database - 使用team_id进行查询
        user = await db_service.get_user_by_slack_id(slack_user_id, team_id)
        if not user:
            logger.info(f"👤 未注册用户打开App Home，开始自动注册: {slack_user_id}")
            # 自动注册用户 - 传递team_id参数
            await handle_unregistered_user(slack_user_id, team_id, is_dm=True)
            
            # 重新获取用户信息（注册后）
            user = await db_service.get_user_by_slack_id(slack_user_id, team_id)
            if not user:
                logger.error(f"❌ 自动注册失败，用户仍未找到: {slack_user_id}")
                return
            logger.info(f"✅ 自动注册成功，继续处理App Home: {slack_user_id}")

        # Ensure user has subscription
        if not await ensure_user_subscription(user):
            return
        
        # Check if user is active
        if not await check_user_active_status(user, slack_user_id, team_id, is_dm=False):
            return
        
        # Send welcome message
        welcome_message = await get_welcome_message()
        await slack_service.send_direct_message(slack_user_id, welcome_message, team_id=team_id)
        
        logger.info(f"✅ 已向用户 {slack_user_id} 发送App Home欢迎消息")
        
    except Exception as e:
        logger.error(f"❌ 处理App Home打开事件时发生错误: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")


async def process_dm_message(event: Dict[str, Any], team_id: str):
    """Process direct message event"""
    try:
        slack_user_id = event.get("user")
        channel_id = event.get("channel")
        message_text = event.get("text", "")
        message_ts = event.get("ts")
        files = event.get("files", [])
        
        logger.info(f"🔄 处理DM消息 - 用户: {slack_user_id}, team id:{team_id}, 频道: {channel_id}, 文本长度: {len(message_text)}, 文件数量: {len(files)}")
        
        if not all([slack_user_id, channel_id, message_ts]):
            logger.error("❌ 缺少必需的消息数据")
            return
        
        # Find user in database - 使用team_id进行查询
        user = await db_service.get_user_by_slack_id(slack_user_id, team_id)
        logger.info(f"查询用户 {slack_user_id} team id:{team_id} 结果: {user}")

        if not user:
            logger.info(f"👤 未注册用户发送消息，开始自动注册: {slack_user_id}")
            # 自动注册用户 - 传递team_id参数
            await handle_unregistered_user(slack_user_id, team_id, channel_id, is_dm=True)
            
            # 重新获取用户信息（注册后）
            user = await db_service.get_user_by_slack_id(slack_user_id, team_id)
            if not user:
                logger.error(f"❌ 自动注册失败，用户仍未找到: {slack_user_id}")
                return
            logger.info(f"✅ 自动注册成功，继续处理消息: {slack_user_id}")

        # Check if user has subscription, create one if missing
        subscription = await db_service.get_user_subscription(user.slack_user_id)
        if not subscription:
            subscription = await subscription_service.create_subscription(user.id, SubscriptionPlan.FREE, slack_user_id, None)
            print(f"Created subscription: {subscription}")
        
        # Check if user is active
        if not user.is_active:
            await slack_service.send_message(
                channel=channel_id,
                text="❌ Your account is inactive. Please contact support.",
                access_token=None  # Use bot token
            )
            return
        
        # Process files if present in the message
        if files:
            logger.info(f"📁 处理消息中的 {len(files)} 个文件")
            for file_info in files:
                await process_uploaded_file(user, file_info, channel_id, message_ts)
        
        # Check for GitHub URLs in the message - 修复检测逻辑
        has_github_urls = False
        github_urls = []
        if message_text.strip():
            from services.github_service import github_service
            github_urls = github_service.extract_github_urls(message_text)
            has_github_urls = len(github_urls) > 0
            logger.info(f"🔍 检测到 {len(github_urls)} 个GitHub URL: {[url['url'] for url in github_urls]}")
        
        # Process the message text if present
        if message_text.strip():
            response = await message_service.process_message(
                user=user,
                message_text=message_text,
                channel_id=channel_id,
                message_ts=message_ts
            )
            
            if response:
                # Send response back to user
                logger.info(f"📝 发送响应到用户 {slack_user_id} team id{team_id}: {response}")
                
                print(f'发送响应到用户 {slack_user_id} team id{team_id}: {response}')
                success = await message_service.send_response(
                    channel=channel_id,
                    text=response,
                    user_id=slack_user_id,  # Pass user_id for DM handling
                    team_id=team_id  # Pass team_id for correct workspace token
                )
                
                if not success:
                    logger.error(f"❌ 发送响应失败 - 用户: {user.slack_user_id}")
        else:
            # For file-only messages, create a message log entry
            if files:
                logger.info("📝 创建文件消息的message_log记录")
                file_names = [f.get('name', 'unknown') for f in files]
                file_message = f"[File upload: {', '.join(file_names)}]"
                
                # Create message log for file upload
                await db_service.create_message_log({
                    "slack_user_id": user.slack_user_id,
                    "slack_channel_id": channel_id,
                    "slack_message_ts": message_ts,
                    "message_type": MessageType.RECEIVED,
                    "original_message": file_message
                })
                
                # Update usage stats
                await db_service.update_usage_stats(user.slack_user_id, MessageType.RECEIVED)
            else:
                logger.info("📝 Message has no text content, only processing files")
        
    except Exception as e:
        logger.error(f"❌ 处理DM消息时发生错误: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")

@router.post("/interactive")
async def handle_slack_interactive(request: Request):
    """Handle Slack interactive components (buttons, modals, etc.)"""
    
    # Get request body and verify signature
    body = await request.body()
    body_str = body.decode('utf-8')
    
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    
    if not slack_service.verify_request_signature(timestamp, body_str, signature):
        raise HTTPException(status_code=401, detail="Invalid request signature")
    
    # Parse form data (Slack sends interactive payloads as form data)
    from urllib.parse import parse_qs
    parsed_data = parse_qs(body_str)
    
    if "payload" not in parsed_data:
        raise HTTPException(status_code=400, detail="No payload found")
    
    try:
        payload = json.loads(parsed_data["payload"][0])
    except (json.JSONDecodeError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid payload")
    
    # Handle different types of interactions
    interaction_type = payload.get("type")
    
    if interaction_type == "block_actions":
        # Handle button clicks, select menus, etc.
        return await handle_block_actions(payload)
    
    elif interaction_type == "view_submission":
        # Handle modal submissions
        return await handle_modal_submission(payload)
    
    return {"status": "ok"}

async def handle_block_actions(payload: Dict[str, Any]):
    """Handle block action interactions"""
    user = payload.get("user", {})
    user_id = user.get("id")
    actions = payload.get("actions", [])
    logger.info(f"🔍 处理块操作交互 - user: {user}, actions: {actions}")

    for action in actions:
        action_id = action.get("action_id")
        action_value = action.get("value")
        
        if action_id == "subscribe_button":
            # Handle subscription button click
            return {
                "response_type": "ephemeral",
                "text": "🚀 Redirecting you to subscription page..."
            }
        
        elif action_id in ["purchase_base_plan", "purchase_pro_plan", "cancel_base_plan", "cancel_pro_plan", "confirm_cancel_base_plan", "confirm_cancel_pro_plan", "keep_subscription"]:
            # Handle purchase button clicks - redirect to the proper interactive service
            from services.slack_interactive_service import slack_interactive_service
            
            try:
                logger.info(f"Processing purchase button: {action_id}")
                
                # Get team_id from payload
                team_id = payload.get("team", {}).get("id")
                
                # Get the actual User object from database
                db_user = await db_service.get_user_by_slack_id(user_id, team_id)
                if not db_user:
                    logger.error(f"User not found for Slack ID: {user_id}")
                    return {
                        "response_type": "ephemeral",
                        "text": "❌ User not found. Please make sure you are registered."
                    }
                
                # Return immediate response to avoid timeout
                immediate_response = {
                    "response_type": "ephemeral",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "⏳ Processing your subscription request, please wait..."
                            }
                        }
                    ]
                }
                
                # Process purchase in background (don't await)
                import asyncio
                response_url = payload.get("response_url")
                asyncio.create_task(process_purchase_async(payload, response_url, db_user))
                
                return immediate_response
                    
            except Exception as e:
                logger.error(f"Error handling purchase button for user {user_id}: {e}")
                return {
                    "response_type": "ephemeral",
                    "text": "❌ An error occurred while processing your purchase request. Please try again later."
                }
    
    return {"status": "ok"}

async def handle_modal_submission(payload: Dict[str, Any]):
    """Handle modal form submissions"""
    user_id = payload.get("user", {}).get("id")
    view = payload.get("view", {})
    
    # Process modal submission based on callback_id
    callback_id = view.get("callback_id")
    
    if callback_id == "subscription_modal":
        # Handle subscription modal
        pass
    
    return {"status": "ok"}

async def process_file_shared(event: Dict[str, Any], team_id: str):
    """Process file shared event"""
    try:
        file_id = event.get("file_id")
        user_id = event.get("user_id")
        channel_id = event.get("channel_id")
        
        logger.info(f"🔄 处理文件共享事件 - file_id: {file_id}, user_id: {user_id}, channel_id: {channel_id}")
        
        if not all([file_id, user_id, channel_id]):
            logger.error(f"❌ 缺少必需字段: file_id={file_id}, user_id={user_id}, channel_id={channel_id}")
            return
        
        # Find user in database
        user = await db_service.get_user_by_slack_id(user_id)
        if not user:
            logger.error(f"❌ 用户 {user_id} 在数据库中未找到")
            return
        
        logger.info(f"✅ 找到用户: {user.slack_user_id} ")
        
        # Check if user is active
        if not user.is_active:
            logger.warning(f"⚠️ 用户 {user_id} 未激活")
            return
        
        # Get file information from Slack API
        logger.info(f"📁 获取文件信息: {file_id}")
        file_info = await slack_service.get_file_info(file_id)
        if not file_info:
            logger.error(f"❌ 无法获取文件信息: {file_id}")
            return
        
        logger.info(f"📄 文件信息获取成功 - 名称: {file_info.get('name')}, 类型: {file_info.get('mimetype')}, 大小: {file_info.get('size')} bytes")
        
        # Process the file based on its type
        await process_uploaded_file(user, file_info, channel_id)
        
    except Exception as e:
        logger.error(f"❌ 处理文件共享事件时发生错误: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")

async def process_purchase_async(payload: Dict[str, Any], response_url: str, user: User):
    """Process purchase in background and send as new message"""
    try:
        from services.slack_interactive_service import slack_interactive_service
        from services.slack_service import slack_service
        
        # Extract channel and user info from payload
        channel_id = payload.get("channel", {}).get("id")
        user_id = payload.get("user", {}).get("id")
        
        if not channel_id or not user_id:
            logger.error("Missing channel_id or user_id in payload")
            return
        
        # Process the purchase
        response = await slack_interactive_service.handle_button_interaction(payload)
        
        # If response contains blocks, send as new message using chat.postMessage
        if response.get("blocks"):
            await slack_service.send_message(
                channel=channel_id,
                blocks=response["blocks"],
                team_id=user.slack_team_id
            )
        elif response.get("text"):
            await slack_service.send_message(
                channel=channel_id,
                text=response["text"],
                team_id=user.slack_team_id
            )
            
    except Exception as e:
        logger.error(f"Error in background purchase processing: {e}")
        # Send error message as new message
        try:
            channel_id = payload.get("channel", {}).get("id")
            if channel_id:
                await slack_service.send_message(
                    channel=channel_id,
                    text="❌ An error occurred while processing your purchase request. Please try again later."
                )
        except Exception as send_error:
            logger.error(f"Failed to send error message: {send_error}")

async def process_uploaded_file(user: User, file_info: Dict[str, Any], channel_id: str, message_ts: str = None):
    """Process uploaded file based on its type"""
    try:
        file_type = file_info.get("mimetype", "")
        file_name = file_info.get("name", "unknown")
        file_size = file_info.get("size", 0)
        
        logger.info(f"📁 Starting to process uploaded file - User: {user.slack_user_id}, File name: {file_name}, Type: {file_type}, Size: {file_size} bytes, Message ID: {message_ts}")
        
        # Check file size limit (e.g., 10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if file_size > max_size:
            logger.warning(f"⚠️ File rejected due to size limit - File: {file_name}, Size: {file_size} bytes, Limit: {max_size} bytes")
            await slack_service.send_message(
                channel=channel_id,
                text=f"❌ File `{file_name}` is too large! Maximum supported file size is 10MB.",
                team_id=user.slack_team_id
            )
            return
        
        # Handle different file types
        if file_type == "application/pdf":
            logger.info(f"📄 PDF file detected, starting processing: {file_name}")
            await handle_pdf_file(user, file_info, channel_id, message_ts)
        elif file_type.startswith("image/"):
            logger.info(f"🖼️ Image file detected, starting processing: {file_name}")
            await handle_image_file(user, file_info, channel_id, message_ts)
        elif file_type.startswith("text/"):
            logger.info(f"📝 Text file detected, starting processing: {file_name}")
            await handle_text_file(user, file_info, channel_id, message_ts)
        else:
            logger.warning(f"❓ Unsupported file type: {file_type} - File: {file_name}")
            # Unsupported file type
            await slack_service.send_message(
                channel=channel_id,
                text=f"📄 Received file `{file_name}`, but this file type ({file_type}) is not supported.\n\nSupported file types:\n• PDF documents\n• Image files (JPG, PNG, GIF)\n• Text files (TXT, CSV, JSON)",
                team_id=user.slack_team_id
            )
    
    except Exception as e:
        logger.error(f"❌ Error occurred while processing uploaded file: {e}")
        import traceback
        logger.error(f"Error details: {traceback.format_exc()}")
        await slack_service.send_message(
            channel=channel_id,
            text="❌ An error occurred while processing the file, please try again later.",
            team_id=user.slack_team_id
        )

async def handle_pdf_file(user: User, file_info: Dict[str, Any], channel_id: str, message_ts: str = None):
    """Handle PDF file upload"""
    file_name = file_info.get("name", "document.pdf")
    file_url = file_info.get("url_private")
    
    # Log confirmation that backend received valid URL
    logger.info(f"Received PDF file upload request - User: {user.slack_user_id}, File name: {file_name}, URL: {file_url}, Message ID: {message_ts}")
    
    if not file_url:
        logger.error(f"Unable to get PDF file download URL - User: {user.slack_user_id}, File name: {file_name}")
        return
    
    logger.info(f"PDF file URL verified successfully - User: {user.slack_user_id}, File name: {file_name}, URL length: {len(file_url)}")
    
    # Send initial processing message
    try:
        await slack_service.send_message(
            channel=channel_id,
            text="🚀 Processing your file, please wait... ✨",
            team_id=user.slack_team_id  # 添加team_id参数
        )
        logger.info(f"✅ 已发送文件处理开始消息到频道 {channel_id}")
    except Exception as e:
        logger.error(f"❌ 发送处理开始消息失败: {str(e)}")
        # 继续处理，不因为消息发送失败而中断文件处理
    
    try:
        # 获取用户对应的Bot Token用于文件下载认证
        bot_token = None
        try:
            from services.database_service import db_service
            workspace = await db_service.get_workspace_by_team_id(user.slack_team_id)
            if workspace:
                bot_token = workspace.bot_token
                logger.info(f"✅ 获取到Bot Token用于文件下载认证")
            else:
                logger.warning(f"⚠️  未找到工作区 {user.slack_team_id} 的Bot Token")
        except Exception as e:
            logger.error(f"❌ 获取Bot Token失败: {str(e)}")
        
        # Import PDFLinkHandler
        from services.pdfLinkHandler import PDFLinkHandler
        
        # Create PDF handler instance with the file URL and Slack token
        pdf_handler = PDFLinkHandler(file_url, False, slack_token=bot_token)
        
        # Process PDF and extract text content
        extracted_text = await pdf_handler.process_url_download_extract(enforce_license_check=False)
        
        if not extracted_text or not extracted_text.strip():
            await slack_service.send_message(
                channel=channel_id,
                text="❌ Failed to extract text from PDF file. The file might be corrupted or in an unsupported format.",
                team_id=user.slack_team_id
            )
            return
        
        # Store extracted content to MongoDB with message_ts
        await store_pdf_content_to_mongodb(user.slack_user_id, file_name, file_url, extracted_text, message_ts)
        
        # Send completion message
        await slack_service.send_message(
            channel=channel_id,
            text="🎉 File processing completed! Your content has been successfully extracted and saved 📄✅",
            team_id=user.slack_team_id
        )
        
    except Exception as e:
        logger.error(f"❌ 处理PDF文件时发生错误: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        
        # 根据错误类型提供更具体的错误信息
        error_message = "❌ PDF文件处理失败"
        if "需要认证" in str(e) or "权限不足" in str(e):
            error_message += "：文件需要认证访问，请确保Bot有足够的权限。"
        elif "HTML页面" in str(e):
            error_message += "：下载的不是PDF文件，可能是登录页面。"
        elif "文件格式错误" in str(e):
            error_message += "：文件格式不正确或已损坏。"
        else:
            error_message += f"：{str(e)}"
        
        await slack_service.send_message(
            channel=channel_id,
            text=error_message,
            team_id=user.slack_team_id
        )

async def handle_image_file(user: User, file_info: Dict[str, Any], channel_id: str, message_ts: str = None):
    """Handle image file upload"""
    file_name = file_info.get("name", "image")
    
    logger.info(f"Processing image file - User: {user.slack_user_id}, File name: {file_name}, Message ID: {message_ts}")
    
    response = f"""🖼️ *Image File Received*

📋 *File Information:*
• File Name: `{file_name}`
• Type: {file_info.get('mimetype', 'unknown')}
• Size: {file_info.get('size', 0)} bytes

🔄 *Processing Status:* Image saved, ready for further analysis.

💡 *Tip:* For image content analysis or text recognition, please send relevant commands."""
    
    await slack_service.send_message(
        channel=channel_id,
        text=response,
        access_token=None
    )

async def handle_text_file(user: User, file_info: Dict[str, Any], channel_id: str, message_ts: str = None):
    """Handle text file upload"""
    file_name = file_info.get("name", "document.txt")
    
    logger.info(f"Processing text file - User: {user.slack_user_id}, File name: {file_name}, Message ID: {message_ts}")
    
    # Download and read text content
    file_content = await slack_service.download_file(file_info.get("url_private"))
    if not file_content:
        await slack_service.send_message(
            channel=channel_id,
            text=f"❌ Unable to download file `{file_name}`",
            access_token=None
        )
        return
    
    try:
        text_content = file_content.decode('utf-8')
        word_count = len(text_content.split())
        line_count = len(text_content.splitlines())
        
        response = f"""📝 *Text File Received*

📋 *File Information:*
• File Name: `{file_name}`
• Size: {file_info.get('size', 0)} bytes
• Lines: {line_count}
• Words: {word_count}

📄 *Content Preview:*
{text_content[:500]}{'...' if len(text_content) > 500 else ''}

💡 *Tip:* The file content has been processed and is ready for analysis."""
        
        await slack_service.send_message(
            channel=channel_id,
            text=response,
            access_token=None
        )
        
    except UnicodeDecodeError:
        await slack_service.send_message(
            channel=channel_id,
            text=f"❌ Unable to read the content of file `{file_name}`, it may not be a valid text file.",
            access_token=None
        )

@router.get("/test")
async def test_endpoint():
    """Test endpoint to verify the events router is working"""
    return {"message": "Slack events router is working"}