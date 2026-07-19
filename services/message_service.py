import asyncio
from math import log
import re
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from services.database_service import db_service
from services.slack_service import slack_service
from services.subscription_service import subscription_service
from services.slack_interactive_service import slack_interactive_service
from services.pdfLinkHandler import PDFLinkHandler
from services.github_service import github_service
from services.agent_work_flow import AgentWorkFlow
from models import MessageType, User, Subscription, SubscriptionStatus, SubscriptionPlan

class MessageService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def process_message(self, user: User, message_text: str, channel_id: str, message_ts: str) -> Optional[str]:
        """Process incoming message and generate response"""
        start_time = datetime.utcnow()
        
        try:
            # Log incoming message
            await db_service.create_message_log({
                "slack_user_id": user.slack_user_id,
                "slack_channel_id": channel_id,
                "slack_message_ts": message_ts,
                "message_type": MessageType.RECEIVED,
                "original_message": message_text
            })
            
            # Update usage stats
            await db_service.update_usage_stats(user.slack_user_id, MessageType.RECEIVED)
            
            # Process the message (this is where you'd add your custom logic)
            processed_response = await self._generate_response(message_text, user, channel_id, message_ts)
            
            # Calculate processing time
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            # Log outgoing message
            await db_service.create_message_log({
                "slack_user_id": user.slack_user_id,
                "slack_channel_id": channel_id,
                "slack_message_ts": message_ts,
                "message_type": MessageType.SENT,
                "original_message": message_text,
                "processed_message": message_text,
                "response_message": processed_response,
                "processing_time_ms": int(processing_time)
            })
            
            # Update usage stats for sent message
            await db_service.update_usage_stats(user.slack_user_id, MessageType.SENT, int(processing_time))
            
            return processed_response
            
        except Exception as e:
            # Log error
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            await db_service.create_message_log({
                "slack_user_id": user.slack_user_id,
                "slack_channel_id": channel_id,
                "slack_message_ts": message_ts,
                "message_type": MessageType.RECEIVED,
                "original_message": message_text,
                "error": str(e),
                "processing_time_ms": int(processing_time)
            })
            
            # Update error stats
            await db_service.update_usage_stats(user.slack_user_id, MessageType.RECEIVED, int(processing_time), error=True)
            
            return "❌ Sorry, I encountered an error processing your message. Please try again later."
    
    async def _generate_response(self, message_text: str, user: User, channel_id: str = None, message_ts: str = None) -> str:
        """Generate response based on input message - customize this method"""
        # This is a simple example - replace with your actual message processing logic
        
        message_lower = message_text.lower().strip()
        
        # Check if message contains PDF URL
        pdf_url = self._extract_pdf_url(message_text)
        if pdf_url:
            await self._handle_pdf_url(pdf_url, user, channel_id, message_ts)
        
        # Step 1: Process GitHub URL (store to database for Agent workflow use)
        github_urls = github_service.extract_github_urls(message_text)
        if github_urls:
            await self._handle_github_urls(github_urls, user, channel_id, message_text, message_ts)
        
        # Step 2: Detect @Agent
        if "@agent" in message_lower:
            # Step 3: Verify user eligibility
            eligibility_check = await self._check_agent_usage_eligibility(user)
            if eligibility_check != "eligible":
                return eligibility_check
            
            self.logger.info(f"✅ Agent workflow eligibility check passed for user {user.slack_user_id}")
            # Send confirmation message
            print(f'user {user} sent _generate_response')
            await self.send_response(
                channel=channel_id,
                text="🤖 *Agent workflow started!* Processing your request...",
                user_id=user.slack_user_id,
                team_id=user.slack_team_id
            )
            
            try:
                # Step 4: Start Agent workflow
                # Step 5: Agent workflow will get GitHub content from database
                result = await self._handle_agent_workflow(message_text, user, channel_id, message_ts)
                
                # Step 6: Deduct usage after successful execution
                if result and not result.startswith("❌"):
                    await self._deduct_agent_usage(user, message_ts)
                    self.logger.info(f"✅ Agent workflow completed successfully for user {user.slack_user_id}, usage deducted")
                else:
                    self.logger.warning(f"⚠️ Agent workflow failed for user {user.slack_user_id}, no usage deducted")
                
                return result
                
            except Exception as e:
                self.logger.error(f"❌ Agent workflow execution failed for user {user.slack_user_id}: {e}")
                return f"❌ *Agent workflow execution failed:* {str(e)}"
        
        # Simple command handling
        if message_lower in ["hello", "hi", "hey", "hello", "hi"]:
            return """👋 Hello! I'm your AI coding assistant that transforms ideas into *working code* and *beyond*!

🔬 *What I Do:*
• Idea Implementation - Transform ideas into working code
• Execution and Insights - Run code and generate actionable insights
• Auto-Generated Repositories - All code saved to GitHub with execution logs

💡 *Pro Tips:* Share relevant PDFs and existing code repositories to provide rich context - this helps me understand your methodology and generate more targeted implementations!


📊 *Usage Example:*
*You:* "@Agent Design a Bayesian A/B testing framework with sequential analysis for early stopping. Here's my current setup: https://github.com/yourname/ab-testing and relevant paper: [PDF doc]"

*Me:* I'll analyze your codebase and document, implement sequential Bayesian testing with proper stopping rules, generate synthetic data for validation, run comprehensive simulations, and deliver a complete experimental framework with final result analysis!

🚀 Ready to start? Just type *@Agent* followed by your new hypotheses or ideas!"""
        
        elif message_lower in ["help", "?", "帮助"]:
            return f"""🤖 *Slack Assistant Help*

*📋 Available Commands:*
• `subscribe` - View and manage subscription plans
• `history` - View conversation history
• `help` - Show this help information
• `status` - Check account status


*🔧 Core Capabilities:*
Transform your ideas into fully functional, executable code with automatic execution and comprehensive result analysis. All generated code and execution processes are systematically saved to GitHub repositories for version control and collaboration.

*💡 Pro Tips:*
Type *@Agent* followed by your request to activate the AI assistant.
Providing documents and code repository links alongside your conversation helps our AI better understand the context, enabling more precise and requirement-focused code generation that perfectly matches your needs.

Need more help? Contact our support team."""
        
        elif message_lower.startswith("echo ") or message_lower.startswith("echo "):
            if message_lower.startswith("echo "):
                echo_text = message_text[5:].strip()
            else:
                echo_text = message_text[5:].strip()
            return f"🔄 *Echo:* {echo_text}"
        
        elif message_lower in ["history", "history", "conversation history"]:
            # Get conversation history from Slack (limited to 10 recent messages)
            if channel_id:
                try:
                    history = await slack_service.get_full_conversation_history(
                        channel=channel_id,
                        access_token=None,  # Use bot token instead of user token
                        team_id=user.slack_team_id,  # 传入team_id以获取对应工作区的token
                        limit=10  # Limit to 10 recent messages
                    )
                    
                    if history:
                        # Adjust max_message_length parameter as needed, default 200 characters
                        formatted_history = slack_service.format_conversation_history(
                            history, 
                            user.slack_user_id, 
                            max_message_length=150  # Adjust this value to control max length per message
                        )
                        return f"""📚 *Recent Conversation History*

{formatted_history}

---
*Showing recent {len(history)} message records (max 150 characters per message)*"""
                    else:
                        return """📚 *Conversation History*"""
                        
                except Exception as e:
                    print(f"Error retrieving conversation history: {e}")
                    return "❌ Something went wrong. Please try again or contact support team."
            else:
                return "❌ *Channel info is missing. Please try again or contact support team"
        
        elif message_lower in ["register", "register", "signup"]:
            # Handle registration command
            return f"""🔐 *Registration Guide*

👋 Welcome! You're already registered by installing this Slack app.

*🎉 What you have:*
• Free subscription plan
• Message processing capabilities
• Conversation history

*🚀 Available commands:*
• `help` - View help information
• `subscribe` - Manage subscription
• `status` - Check account status

Need more features? Use `subscribe` to explore our plans."""
        
        elif message_lower in ["subscribe", "subscribe", "subscription"]:
            # Handle subscription command - show plans and purchase options
            response = await self._handle_subscription_command(user)
            # Send interactive message with subscription options
            # Get user's active subscriptions, if no active subscription get the latest subscription
            active_subscriptions = await db_service.get_user_active_subscriptions(user.slack_user_id)
            subscription = active_subscriptions[0] if active_subscriptions else await db_service.get_user_subscription(user.slack_user_id)
            blocks = await slack_interactive_service.create_subscription_blocks(user)
            self.logger.info(f"user info debug: {user}")
            await self.send_response(channel=channel_id, text=response, blocks=blocks, user_id=user.slack_user_id, team_id=user.slack_team_id)
            return ""  # Return empty string to avoid duplicate sending
        
        elif message_lower in ["plans", "plans", "pricing"]:
            # Handle plans command - show available subscription plans
            response = await self._handle_plans_command()
            return response
        
        elif message_lower in ["upgrade", "upgrade"]:
            # Handle upgrade command - show upgrade options
            response = await self._handle_upgrade_command(user)
            # For upgrade command, also send interactive message if user can upgrade
            # Get user's active subscriptions, if no active subscription get the latest subscription
            active_subscriptions = await db_service.get_user_active_subscriptions(user.slack_user_id)
            subscription = active_subscriptions[0] if active_subscriptions else await db_service.get_user_subscription(user.slack_user_id)
            current_plan = subscription.plan if subscription else SubscriptionPlan.FREE
            if current_plan != SubscriptionPlan.PRO:
                blocks = await slack_interactive_service.create_subscription_blocks(user)
                await self.send_response(channel=channel_id, text=response, blocks=blocks, user_id=user.slack_user_id, team_id=user.slack_team_id)
            else:
                await self.send_response(channel=channel_id, text=response, user_id=user.slack_user_id, team_id=user.slack_team_id)
            return ""  # Return empty string to avoid duplicate sending
        
        elif message_lower in ["billing", "billing", "payment"]:
            # Handle billing command - show billing information
            response = await self._handle_billing_command(user)
            await self.send_response(channel=channel_id, text=response, user_id=user.slack_user_id, team_id=user.slack_team_id)
            return response
        
        elif message_lower in ["status", "status", "stat"]:
            # Handle status command - show subscription status and usage statistics
            response = await self._handle_status_command(user)
            # await self.send_response(channel=channel_id, text=response, user_id=user.slack_user_id, team_id=user.slack_team_id)
            return response # Return empty string to avoid duplicate sending
        
        else:
            return """👋 Hello! I'm your AI coding assistant that transforms ideas into *working code* and *beyond*!

🔬 *What I Do:*
• Idea Implementation - Transform ideas into working code
• Execution and Insights - Run code and generate actionable insights 
• Auto-Generated Repositories - All code saved to GitHub with execution logs

💡 *Pro Tips:* Share relevant PDFs and existing code repositories to provide rich context - this helps me understand your methodology and generate more targeted implementations!


📊 *Usage Example:*
*You:* "@Agent Design a Bayesian A/B testing framework with sequential analysis for early stopping. Here's my current setup: https://github.com/yourname/ab-testing and relevant paper: [PDF doc]"

*Me:* I'll analyze your codebase and paper, implement sequential Bayesian testing with proper stopping rules, generate synthetic data for validation, run comprehensive simulations, and deliver a complete experimental framework with final result analysis!

🚀 Ready to start? Just type *@Agent* followed by your new hypotheses or ideas!"""

    
    async def send_response(self, channel: str, text: str = None, blocks: list = None, user_id: str = None, team_id: str = None):
        """Send response message to Slack channel or user"""
        try:
            # Check if this is a DM channel (starts with 'D')
            is_dm_channel = channel.startswith('D')
            
            print(f"发送直接消息给用户 {user_id} team {team_id}")

            if is_dm_channel:
                # For DM channels, we need to get the user ID and use send_direct_message
                if user_id:
                    # If we have user_id, use send_direct_message
                    if blocks:
                        # For blocks, we still need to use send_message with the DM channel
                        # But first try to send via user ID
                        try:
                            await slack_service.send_message(
                                channel=user_id,  # Try with user ID first
                                blocks=blocks,
                                text=text or "Subscription Options",
                                team_id=team_id
                            )
                        except Exception:
                            # Fallback to DM channel ID
                            await slack_service.send_message(
                                channel=channel,
                                blocks=blocks,
                                text=text or "Subscription Options",
                                user_id=user_id,
                                team_id=team_id
                            )
                    else:
                        # For text messages, use send_direct_message with team_id
                        await slack_service.send_direct_message(user_id, text, team_id=team_id)
                else:
                    # If no user_id provided, try to extract from channel or use channel directly
                    self.logger.warning(f"DM channel {channel} detected but no user_id provided, trying direct channel send")
                    if blocks:
                        await slack_service.send_message(
                            channel=channel,
                            blocks=blocks,
                            text=text or "Subscription Options",
                            team_id=team_id
                        )
                    else:
                        await slack_service.send_message(
                            channel=channel,
                            text=text,
                            team_id=team_id
                        )
            else:
                # For regular channels, use send_message as before
                if blocks:
                    await slack_service.send_message(
                        channel=channel,
                        blocks=blocks,
                        text=text or "Subscription Options",
                        team_id=team_id
                    )
                else:
                    await slack_service.send_message(
                        channel=channel,
                        text=text,
                        team_id=team_id
                    )
            return True  # 返回成功状态
        except Exception as e:
            self.logger.error(f"Error sending response: {str(e)}")
            # Enhanced fallback strategy
            try:
                if channel.startswith('D') and user_id:
                    # For DM channels, try send_direct_message as fallback with team_id
                    await slack_service.send_direct_message(user_id, text or "❌ 发送消息时出错", team_id=team_id)
                else:
                    # For regular channels or when no user_id available
                    await slack_service.send_message(
                        channel=channel,
                        text=text or "❌ 发送消息时出错",
                        team_id=team_id
                    )
                return True  # 备用发送成功
            except Exception as fallback_error:
                self.logger.error(f"Fallback send also failed: {str(fallback_error)}")
                return False  # 完全失败
    
    async def get_user_message_history(self, user: User, limit: int = 50) -> list:
        """Get user's message history"""
        messages = await db_service.get_user_message_history(user.slack_user_id, limit)
        
        return [
            {
                "id": msg.id,
                "message_type": msg.message_type,
                "original_message": msg.original_message,
                "response_message": msg.response_message,
                "timestamp": msg.timestamp,
                "processing_time_ms": msg.processing_time_ms,
                "error": msg.error
            }
            for msg in messages
        ]
    
    async def _handle_subscription_command(self, user: User) -> str:
        """Handle subscription command - show current subscription and purchase options"""
        try:
            # Get all active subscriptions
            active_subscriptions = await db_service.get_user_active_subscriptions(user.slack_user_id)
            
            self.logger.info(f"Active subscriptions for user {user.slack_user_id}: {active_subscriptions}")
    
            if active_subscriptions:
                # Build subscription info for multiple plans
                subscription_info = "💎 *Subscription Management*\n\n"
                
                # Get total monthly usage
                monthly_usage = await db_service.get_user_monthly_usage(user.id)
                
                # Calculate total usage limit from all active subscriptions
                total_usage_limit = sum(sub.usage_limit for sub in active_subscriptions)
                
                for i, subscription in enumerate(active_subscriptions, 1):
                    status_emoji = "✅" if subscription.status == SubscriptionStatus.ACTIVE else "⏳" if subscription.status == SubscriptionStatus.TRIAL else "❌"
                    plan_name = subscription.plan.value.title()
                    
                    subscription_info += f"{status_emoji} *Plan {i}:* {plan_name}\n"
                    subscription_info += f"📊 *Status:* {subscription.status.value}\n"

                    # Add expiration info if available
                    if subscription.expires_at:
                        subscription_info += f"📈 *Usage Limit:* {subscription.usage_limit} AI-generated messages/month\n"
                        subscription_info += f"📅 *Expires:* {subscription.expires_at.strftime('%Y-%m-%d')}\n"
                    else:
                        subscription_info += f"📈 *Usage Limit:* {subscription.usage_limit}\n"
                    # Add subscription ID for reference
                    if subscription.external_subscription_id:
                        subscription_info += f"🔗 *ID:* {subscription.external_subscription_id[:12]}...\n"
                    
                    subscription_info += "\n"
                
                # Add total usage summary
                subscription_info += f"📊 *Total Usage:* {monthly_usage}/{total_usage_limit} messages this month\n\n"
                subscription_info += "Use the buttons below to manage your subscriptions."
                
                return subscription_info
            else:
                return """💎 *Subscription Plans*
    
    🆓 *Current Plan:* Free Plan
    📊 *Status:* Active
    
    Choose a plan below to upgrade your experience."""
            
        except Exception as e:
            self.logger.error(f"Error retrieving subscription information: {str(e)}")
            return f"❌ Error retrieving subscription information: {str(e)}"
    
    async def _handle_plans_command(self) -> str:
        """Handle plans command - show detailed plan comparison"""
        return """💎 *Subscription Plans Comparison*
    
    ```
    ┌─────────────────────────────────────────────────────────┐
    │                    🆓 Free Plan                         │
    ├─────────────────────────────────────────────────────────┤
    │ • 20 AI generated messages in total                    │
    │ • Basic message processing                             │
    │ • Price: Free                                          │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │                    ⭐ Base Plan                         │
    ├─────────────────────────────────────────────────────────┤
    │ • 40 monthly AI generated messages                     │
    │ • Basic features only                                  │
    │ • Price: $3.9/month                                    │
    └─────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────┐
    │                    🚀 Pro Plan                         │
    ├─────────────────────────────────────────────────────────┤
    │ • 200 monthly AI generated messages                    │
    │ • All advanced features                                │
    │ • Price: $19.9/month                                   │
    └─────────────────────────────────────────────────────────┘
    ```
    
    🛒 *Purchase Now:* Send `upgrade` command to start upgrade process"""
    
    async def _handle_upgrade_command(self, user: User) -> str:
        """Handle upgrade command - show upgrade options"""
        try:
            # Get current subscription
            subscription = await db_service.get_user_subscription(user.slack_user_id)
            current_plan = subscription.plan if subscription else SubscriptionPlan.FREE
            
            if current_plan == SubscriptionPlan.PRO:
                return """✅ *You're already on the highest plan!*
    
    Thank you for your support!"""
            
            return f"""🚀 *Upgrade Your Plan*
    
    📋 *Current Plan:* {current_plan.value.title()}
    
    Use the buttons below to upgrade to a higher plan with more features and messages."""
            
        except Exception as e:
            return f"❌ Error getting upgrade information: {str(e)}"
    
    async def _handle_billing_command(self, user: User) -> str:
        """Handle billing command - show billing information"""
        try:
            # Get current subscription
            subscription = await db_service.get_user_subscription(user.slack_user_id)
            
            if not subscription:
                return """💳 *Billing Information*
    
    ❌ *No active subscription found*
    
    Send `subscribe` command to view available plans."""
            
            # Get usage statistics
            monthly_usage = await db_service.get_user_monthly_usage(user.slack_user_id)
            
            return f"""💳 *Billing Information*
    
    📋 *Current Plan:* {subscription.plan.value.title()}
    📊 *Status:* {subscription.status.value}
    📈 *Usage:* {monthly_usage}/{subscription.usage_limit} messages this month
    
    Use the buttons below to manage your subscription."""
            
        except Exception as e:
            return f"❌ Error getting billing information: {str(e)}"

    async def _handle_status_command(self, user: User) -> str:
        """Handle status command - show subscription status and usage statistics"""
        try:
            # Get all subscriptions (active and cancelled)
            all_subscriptions = await db_service.get_user_subscriptions(user.slack_user_id)
            
            # Filter for active and cancelled subscriptions
            relevant_subscriptions = [
                sub for sub in all_subscriptions 
                if sub.status in [SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED]
            ]
            
            if not relevant_subscriptions:
                return """📊 *Account Status*
    
    ❌ *No active or cancelled subscriptions found*
    
    Send `subscribe` command to view available plans."""
            

            # Build status response
            status_info = "📊 *Account Status & Usage Statistics*\n\n"
            
            # Show subscription information
            status_info += "💎 *Subscriptions:*\n"
            
            for i, subscription in enumerate(relevant_subscriptions, 1):
                status_emoji = "✅" if subscription.status == SubscriptionStatus.ACTIVE else "⏸️"
                plan_name = subscription.plan.value.title()
                
                status_info += f"{status_emoji} *Plan {i}:* {plan_name}\n"
                status_info += f"   📊 Status: {subscription.status.value}\n"
                if subscription.expires_at:                    
                    # 检查是否已过期
                    if subscription.expires_at < datetime.utcnow():
                        status_info += f"   ⚠️ *This subscription has expired*\n"
                    else:
                        expires_str = subscription.expires_at.strftime("%Y-%m-%d %H:%M UTC")
                        status_info += f"   ⏰ Expires: {expires_str}\n"
                        status_info += f"   🎯 Usage Limit: {subscription.usage_limit} AI-generated messages/month\n"
                        current_usage = getattr(subscription, 'current_usage', 0)
                        status_info += f"   📈 Current Usage: {current_usage}/{subscription.usage_limit}\n"      
                else:
                    status_info += f"   ⏰ Expires: Never\n"
                    status_info += f"   🎯 Usage Limit: {subscription.usage_limit}\n"
                    current_usage = getattr(subscription, 'current_usage', 0)
                    status_info += f"   📈 Current Usage: {current_usage}/{subscription.usage_limit}\n"      

                if subscription.cancelled_at and subscription.status == SubscriptionStatus.CANCELLED:
                    cancelled_str = subscription.cancelled_at.strftime("%Y-%m-%d %H:%M UTC")
                    status_info += f"   🚫 Cancelled: {cancelled_str}\n"
                
                status_info += "\n"
            
            return status_info
            
        except Exception as e:
            return f"❌ Error getting status information: {str(e)}"

    def _extract_pdf_url(self, message_text: str) -> Optional[str]:
        """Extract PDF URL from message text"""
        # Look for URLs that end with .pdf or contain PDF-related patterns
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+\.pdf(?:\?[^\s<>"{}|\\^`\[\]]*)?'
        matches = re.findall(url_pattern, message_text, re.IGNORECASE)
        
        if matches:
            return matches[0]  # Return the first PDF URL found
        
        # Also check for general URLs that might be PDFs
        general_url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(general_url_pattern, message_text)
        
        for url in urls:
            # Check if URL path suggests it's a PDF
            if 'pdf' in url.lower() or url.lower().endswith('.pdf'):
                return url
        
        return None
    
    async def _handle_pdf_url(self, pdf_url: str, user: User, channel_id: str, message_ts: str = None) -> str:
        """Handle PDF URL processing"""
        try:
            print(f"[DEBUG] 检测到PDF URL: {pdf_url}")
            print(f"[DEBUG] 用户ID: {user.slack_user_id}")
            print(f"[DEBUG] 频道ID: {channel_id}")
            
            # Create PDF handler
            pdf_handler = PDFLinkHandler(pdf_url)
            
            # Validate if it's actually a PDF URL
            is_pdf = await pdf_handler.is_pdf_url(pdf_url)
            if not is_pdf:
                print(f"[DEBUG] URL不是有效的PDF: {pdf_url}")
                return f"❌ 提供的链接不是有效的PDF文件: {pdf_url}"
            
            print(f"[DEBUG] 确认为PDF URL，开始处理...")
            
            # Send initial processing message
            await self.send_response(
                channel=channel_id,
                text="📄 检测到PDF文件，正在处理中，请稍候...",
                user_id=user.slack_user_id,
                team_id=user.slack_team_id
            )
            
            # Process PDF asynchronously
            try:
                pdf_text = await pdf_handler.process_url_download_extract(enforce_license_check=False)
                
                if pdf_text:
                    print(f"[DEBUG] PDF处理成功，文本长度: {len(pdf_text)}")
                    
                    # Save PDF content to MongoDB
                    try:
                        from urllib.parse import urlparse
                        parsed_url = urlparse(pdf_url)
                        file_name = parsed_url.path.split('/')[-1] or "document.pdf"
                        
                        # Create PDF document for MongoDB
                        pdf_document = {
                            "slack_user_id": user.slack_user_id,
                            "file_name": file_name,
                            "file_url": pdf_url,
                            "extracted_text": pdf_text,
                            "text_length": len(pdf_text),
                            "word_count": len(pdf_text.split()),
                            "processed_at": datetime.utcnow(),
                            "source": "url_processing"
                        }
                        
                        # Add slack_message_ts if provided
                        if message_ts:
                            pdf_document["slack_message_ts"] = message_ts
                            print(f"[DEBUG] 添加Slack消息ID到PDF文档: {message_ts}")
                        
                        # Save to database
                        db = await db_service.get_db()
                        result = await db.pdf_documents.insert_one(pdf_document)
                        print(f"[DEBUG] PDF内容已保存到MongoDB，ID: {result.inserted_id}")
                        
                    except Exception as save_error:
                        print(f"[DEBUG] 保存PDF到MongoDB失败: {str(save_error)}")
                        # 继续处理，不因保存失败而中断用户体验
                    
                    # Send success message with summary
                    response = f"""✅ *PDF处理完成！*

📄 *文件链接:* {pdf_url}
📊 *提取文本长度:* {len(pdf_text)} 字符
💾 *数据保存:* 已保存到数据库

---
💡 *提示:* PDF内容已保存，您可以继续提问相关问题。"""
                    
                    # Send initial processing message
                    await self.send_response(
                        channel=channel_id,
                        text=response
                    )

                else:
                    print(f"[DEBUG] PDF处理失败，无结果返回")
                    await self.send_response(
                        channel=channel_id,
                        text="❌ PDF处理失败，无法提取内容或进行分析。"
                    )
                    
            except ValueError as ve:
                print(f"[DEBUG] PDF处理被拒绝: {str(ve)}")
                await self.send_response(
                        channel=channel_id,
                        text="❌ PDF处理失败，无法提取内容或进行分析。"
                    )

            except Exception as e:
                print(f"[DEBUG] PDF处理异常: {str(e)}")
                await self.send_response(
                        channel=channel_id,
                        text="❌ PDF处理失败，无法提取内容或进行分析。"
                    )
                
        except Exception as e:
            print(f"[DEBUG] PDF URL处理异常: {str(e)}")
            await self.send_response(
                        channel=channel_id,
                        text="❌ PDF处理失败，无法提取内容或进行分析。"
                    )

    async def _handle_github_urls(self, github_urls: list, user: User, channel_id: str, message_text: str, message_ts: str = None) -> str:
        """Handle GitHub URLs processing"""
        try:
            self.logger.info(f"Detected {len(github_urls)} GitHub URLs")
            
            # Send initial processing message
            await self.send_response(
                channel=channel_id,
                text="🔍 GitHub repository link detected, reading code and converting to Markdown format, please wait...",
                user_id=user.slack_user_id,
                team_id=user.slack_team_id
            )
            
            processed_repos = []
            
            for url_info in github_urls:
                try:
                    github_url = url_info['url']
                    url_type = url_info['type']
                    owner = url_info['owner']
                    repo_name = url_info['repo_name']
                    branch = url_info.get('branch', 'main')
                    
                    self.logger.info(f"Processing GitHub repository: {owner}/{repo_name} (type: {url_type})")
                    
                    # Create repository record
                    repo_data = {
                        'slack_user_id': user.slack_user_id,
                        'slack_message_ts': message_ts or '',
                        'slack_channel_id': channel_id,
                        'github_url': github_url,
                        'owner': owner,
                        'repo_name': repo_name,
                        'branch': branch,
                        'url_type': url_type,
                        'processing_status': 'processing',
                        'markdown_content': ''
                    }
                    repo_record = await db_service.create_github_repository(repo_data)
                    self.logger.info(f"Created new repository record: {owner}/{repo_name}")
                
                    # Read repository code
                    if url_type == 'gist':
                        gist_id = url_info.get('gist_id')
                        file_contents = await github_service.get_gist_content(gist_id)
                    else:
                        file_contents = await github_service.read_repository_code(owner, repo_name, branch)
                    
                    if not file_contents:
                        await db_service.update_github_repository(repo_record.id, {
                            'processing_status': 'failed',
                            'error_message': 'No code files found or repository is private'
                        })
                        processed_repos.append({
                            'url': github_url,
                            'status': 'failed',
                            'error': 'No code files found or repository is private'
                        })
                        continue
                    
                    # Convert to markdown
                    markdown_content = github_service.convert_to_markdown(file_contents, url_info)
                    
                    # Calculate statistics
                    file_extensions = list(set([
                        '.' + path.split('.')[-1] if '.' in path else 'no-ext'
                        for path in file_contents.keys()
                    ]))
                    
                    total_size = sum(len(content.encode('utf-8')) for content in file_contents.values())
                    
                    # Update repository record
                    await db_service.update_github_repository(repo_record.id, {
                        'total_files': len(file_contents),
                        'processed_files': len(file_contents),
                        'total_size_bytes': total_size,
                        'markdown_content': markdown_content,
                        'file_extensions': file_extensions,
                        'processing_status': 'completed',
                        'processed_at': datetime.utcnow()
                    })
                    
                    processed_repos.append({
                        'url': github_url,
                        'status': 'completed',
                        'repo_id': repo_record.id,
                        'owner': owner,
                        'repo_name': repo_name,
                        'files_count': len(file_contents),
                        'total_size': total_size
                    })
                    
                except Exception as e:
                    self.logger.error(f"Failed to process GitHub URL {url_info['url']}: {e}")
                    processed_repos.append({
                        'url': url_info['url'],
                        'status': 'failed',
                        'error': str(e)
                    })
            
            # Generate response message
            response_parts = ["🎉 *GitHub Code Processing Completed!*\n"]
            
            for repo in processed_repos:
                if repo['status'] == 'completed':
                    response_parts.append(
                        f"✅ *{repo['owner']}/{repo['repo_name']}*\n"
                        f"   📁 Files: {repo['files_count']}\n"
                        f"   📊 Total Size: {repo['total_size']:,} bytes\n"
                        f"   🔗 URL: {repo['url']}\n"
                    )
                elif repo['status'] == 'cached':
                    response_parts.append(
                        f"📋 *{repo['owner']}/{repo['repo_name']}* (Cached)\n"
                        f"   🔗 URL: {repo['url']}\n"
                    )
                else:
                    response_parts.append(
                        f"❌ *Processing Failed*: {repo['url']}\n"
                        f"   Error: {repo.get('error', 'Unknown error')}\n"
                    )
            
            response_parts.append(
                "\n💾 *All code has been converted to Markdown format and saved to database*\n"
                "📝 You can view the complete code content through message history\n"
                "🔍 If you need to view specific files or have other questions, please feel free to ask!"
            )
            
            response_text = "\n".join(response_parts)

            # Send final processing message
            await self.send_response(
                channel=channel_id,
                text=response_text,
                user_id=user.slack_user_id,
                team_id=user.slack_team_id
            )
            
            
        except Exception as e:
            self.logger.error(f"Error occurred while processing GitHub URLs: {e}")
            return f"❌ Error occurred while processing GitHub repository: {str(e)}"

    async def _check_agent_usage_eligibility(self, user: User) -> str:
        """
        Check if user is eligible to use @Agent functionality
        Returns 'eligible' if user can use the service, otherwise returns error message
        
        Conditions:
        1) Free Plan: current_usage < usage_limit
        2) Base Plan: (status == active OR (status == cancelled AND expires_at > current_time)) AND current_usage < usage_limit
        3) Pro Plan: (status == active OR (status == cancelled AND expires_at > current_time)) AND current_usage < usage_limit
        """
        try:
            # Get user's all subscriptions (returns list of subscriptions)
            subscriptions = await subscription_service.get_user_subscriptions(user.slack_user_id)
            
            if not subscriptions:
                return """❌ *No Active Subscription*

You need an active subscription to use the @Agent feature.

*Available Plans:*
• *Free Plan* - 20 AI-generated messages (one-time total)
• *Base Plan* - 40 AI-generated messages monthly
• *Pro Plan* - 200 AI-generated messages monthly

Use the `subscribe` command to view and select a plan."""

            current_time = datetime.utcnow()
            
            # Check each subscription to find one that meets the conditions
            for subscription in subscriptions:
                current_usage = subscription.current_usage or 0
                usage_limit = subscription.usage_limit or 0

                # Condition 1: Free Plan - only check usage limit
                if subscription.plan == SubscriptionPlan.FREE:
                    if current_usage < usage_limit:
                        return "eligible"
                    # Continue to check other subscriptions if this one is over limit

                # Condition 2: Base Plan - check status and expiry, then usage limit
                elif subscription.plan == SubscriptionPlan.BASE:
                    # Check if subscription is valid (active OR cancelled but not expired)
                    is_valid_subscription = False
                    
                    if subscription.status == SubscriptionStatus.ACTIVE:
                        is_valid_subscription = True
                    elif subscription.status == SubscriptionStatus.CANCELLED and subscription.expires_at:
                        if subscription.expires_at > current_time:
                            is_valid_subscription = True
                    
                    # If valid and under usage limit, user is eligible
                    if is_valid_subscription and current_usage < usage_limit:
                        return "eligible"

                # Condition 3: Pro Plan - check status and expiry, then usage limit
                elif subscription.plan == SubscriptionPlan.PRO:
                    # Check if subscription is valid (active OR cancelled but not expired)
                    is_valid_subscription = False
                    
                    if subscription.status == SubscriptionStatus.ACTIVE:
                        is_valid_subscription = True
                    elif subscription.status == SubscriptionStatus.CANCELLED and subscription.expires_at:
                        if subscription.expires_at > current_time:
                            is_valid_subscription = True
                    
                    # If valid and under usage limit (or unlimited), user is eligible
                    if is_valid_subscription and (usage_limit == 0 or current_usage < usage_limit):
                        return "eligible"

            # If no subscription meets the conditions, return appropriate error message
            # Find the best subscription to show error for (prioritize Pro > Base > Free)
            best_subscription = None
            for subscription in subscriptions:
                if subscription.plan == SubscriptionPlan.PRO:
                    best_subscription = subscription
                    break
                elif subscription.plan == SubscriptionPlan.BASE and (not best_subscription or best_subscription.plan == SubscriptionPlan.FREE):
                    best_subscription = subscription
                elif subscription.plan == SubscriptionPlan.FREE and not best_subscription:
                    best_subscription = subscription

            if best_subscription:
                current_usage = best_subscription.current_usage or 0
                usage_limit = best_subscription.usage_limit or 0
                
                if best_subscription.plan == SubscriptionPlan.FREE:
                    return f"""❌ *Free Plan Usage Limit Reached*

You have used {current_usage}/{usage_limit} @Agent requests this month.

*Upgrade Options:*
• *Base Plan* - 40 AI-generated messages monthly
• *Pro Plan* - 200 AI-generated messages monthly

Use the `subscribe` command to upgrade your plan."""

                elif best_subscription.plan == SubscriptionPlan.BASE:
                    if current_usage >= usage_limit:
                        return f"""❌ *Base Plan Usage Limit Reached*

You have used {current_usage}/{usage_limit} @Agent requests this month.

*Upgrade Option:*  
• *Pro Plan* - 200 AI-generated messages monthly

Use the `subscribe` command to upgrade to Pro Plan."""
                    else:
                        return """❌ *Base Plan Subscription Invalid*

Your Base Plan subscription is either cancelled and expired, or in an invalid state.

Use the `subscribe` command to renew or upgrade your subscription."""

                elif best_subscription.plan == SubscriptionPlan.PRO:
                    if usage_limit > 0 and current_usage >= usage_limit:
                        return f"""❌ *Pro Plan Usage Limit Reached*

You have used {current_usage}/{usage_limit} @Agent requests this month.

Please wait for next month's reset or purchase another plan today."""
                    else:
                        return """❌ *Pro Plan Subscription Invalid*

Your Pro Plan subscription is either cancelled and expired, or in an invalid state.

Use the `subscribe` command to renew your subscription."""

            return """❌ *No Valid Subscription*

None of your subscriptions meet the requirements for @Agent usage.

Use the `subscribe` command to check your subscription status."""

        except Exception as e:
            self.logger.error(f"Error checking agent usage eligibility for user {user.slack_user_id}: {e}")
            return """❌ *System Error*

Unable to verify your subscription status. Please try again later or contact support."""

    async def _deduct_agent_usage(self, user: User, message_ts: str) -> None:
        """
        Deduct one usage count from user's subscription
        Args:
            user: User object
            message_ts: Original message timestamp
        """
        try:
            # Step 1: 获取用户所有订阅，找到符合扣减条件的订阅
            subscriptions = await subscription_service.get_user_subscriptions(user.slack_user_id)
            
            if not subscriptions:
                self.logger.error(f"❌ No subscriptions found for user {user.slack_user_id}")
                return
            
            current_time = datetime.utcnow()
            eligible_subscription = None
            
            # 使用与 _check_agent_usage_eligibility 相同的逻辑找到符合条件的订阅
            for subscription in subscriptions:
                current_usage = subscription.current_usage or 0
                
                if subscription.plan == SubscriptionPlan.FREE:
                    # Free Plan: current_usage < usage_limit
                    if current_usage < subscription.usage_limit:
                        eligible_subscription = subscription
                        break
                        
                elif subscription.plan in [SubscriptionPlan.BASE, SubscriptionPlan.PRO]:
                    # Base/Pro Plan: (status == active OR (status == cancelled AND expires_at > current_time)) AND current_usage < usage_limit
                    if ((subscription.status == SubscriptionStatus.ACTIVE) or 
                        (subscription.status == SubscriptionStatus.CANCELLED and 
                         subscription.expires_at and subscription.expires_at > current_time)):
                        
                        if current_usage < subscription.usage_limit:
                            eligible_subscription = subscription
                            break
            
            if not eligible_subscription:
                self.logger.error(f"❌ No eligible subscription found for deduction for user {user.slack_user_id}")
                return
            
            # Step 2: 更新订阅的 current_usage + 1
            new_usage = (eligible_subscription.current_usage or 0) + 1
            await db_service.update_subscription(
                eligible_subscription.id, 
                {"current_usage": new_usage}
            )
            
            # Step 3: 记录使用统计，包括详细信息
            await db_service.update_usage_stats(
                slack_user_id=user.slack_user_id,
                message_type="agent_workflow",
                processing_time_ms=0,
                error=False,
                subscription_id=str(eligible_subscription.id),  # 确保转换为字符串
                external_subscription_id=eligible_subscription.external_subscription_id,
                message_ts=message_ts,
                deduction_time=current_time
            )
            
            self.logger.info(f"✅ Successfully deducted @Agent usage for user {user.slack_user_id}, "
                            f"plan: {eligible_subscription.plan.value}, "
                            f"new usage: {new_usage}/{eligible_subscription.usage_limit}, "
                            f"subscription_id: {eligible_subscription.external_subscription_id}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to deduct @Agent usage for user {user.slack_user_id}: {e}")

    async def _handle_agent_workflow(self, message_text: str, user: User, channel_id: str, message_ts: str) -> str:
        """Handle @Agent workflow with PDF and GitHub content from recent messages"""
        try:
            self.logger.info(f"🤖 Starting @Agent workflow - User: {user.slack_user_id}")
            
            # Step 1: Get recent messages (last 10)
            recent_messages = await self._get_recent_messages(user, channel_id, limit=20)
            
            # Step 2: Extract PDF and GitHub content from recent messages
            pdf_contents = []
            github_contents = []
            
            self.logger.info(f"📋 Starting to extract PDF and GitHub content from {len(recent_messages)} historical messages")
            
            # Only collect the most recent PDF content and GitHub content
            latest_pdf_found = False
            latest_github_found = False
            
            for i, msg in enumerate(recent_messages):
                msg_ts = msg.get('slack_message_ts')
                original_msg = msg.get('original_message', '')
                
                self.logger.info(f"  📝 Message {i+1}: timestamp={msg_ts}, content length={len(original_msg)}")
                
                # Check for PDF content - only collect the most recent one
                if msg_ts and not latest_pdf_found:
                    self.logger.info(f"    🔍 Checking message {i+1} for PDF content...")
                    pdf_content = await self._get_pdf_content_by_message_ts(user.slack_user_id, msg_ts)
                    if pdf_content:
                        pdf_contents.append(pdf_content)
                        latest_pdf_found = True  # Stop collecting after finding the most recent PDF
                        self.logger.info(f"    ✅ Found most recent PDF content: {pdf_content['file_name']}, text length: {len(pdf_content['extracted_text'])}")
                    else:
                        self.logger.info(f"    ❌ Message {i+1} has no PDF content")
                elif latest_pdf_found:
                    self.logger.info(f"    ⏭️ Most recent PDF already found, skipping PDF check for message {i+1}")
                
                # Check for GitHub content - only collect the most recent one
                if msg_ts and not latest_github_found:
                    self.logger.info(f"    🔍 Checking message {i+1} for GitHub content...")
                    github_content = await self._get_github_content_by_message_ts(user.slack_user_id, msg_ts)
                    if github_content:
                        github_contents.append(github_content)
                        latest_github_found = True  # Stop collecting after finding the most recent GitHub
                        self.logger.info(f"    ✅ Found most recent GitHub content: {github_content['github_url']}")
                    else:
                        self.logger.info(f"    ❌ Message {i+1} has no GitHub content")
                elif latest_github_found:
                    self.logger.info(f"    ⏭️ Most recent GitHub already found, skipping GitHub check for message {i+1}")
                elif not msg_ts:
                    self.logger.info(f"    ⚠️ Message {i+1} has no timestamp, skipping content check")
            
            self.logger.info(f"📊 Content extraction completed - PDF documents: {len(pdf_contents)}, GitHub repositories: {len(github_contents)}")
            
            # Step 3: Prepare content for code generation
            chat_messages = [msg.get('original_message', '') for msg in recent_messages if msg.get('original_message')]
            pdf_text = '\n\n'.join([pdf['extracted_text'] for pdf in pdf_contents])
            github_markdown = '\n\n'.join([github['markdown_content'] for github in github_contents])
            
            self.logger.info(f"📝 Preparing workflow content:")
            self.logger.info(f"  💬 Chat messages: {len(chat_messages)} messages, total length: {len(''.join(chat_messages))} characters")
            self.logger.info(f"  📄 PDF text: length: {len(pdf_text)} characters")
            self.logger.info(f"  🔗 GitHub content: length: {len(github_markdown)} characters")
            
            # Step 4: Initialize AgentWorkFlow and execute
            from services.agent_work_flow import AgentWorkFlow
            
            # Create workflow instance with chat mode
            workflow = AgentWorkFlow(
                post_id="slack_dm"+message_ts,
                comment_id=message_ts,
                output_path=f"dm_{message_ts.replace('.', '_')}",
                paper_summary="",  # May not have paper summary in DM
                new_ideas=message_text,  # User's message content as new ideas
                paper_txt="",  # May not have full paper text in DM
                chat_messages=chat_messages,  # Recent 50 DM records
                code_repo_content=github_markdown,  # Most recent code repository content
                pdf_content=pdf_text,  # Most recent PDF document content
                generation_mode="chat"  # Set to chat mode
            )
            
            # Set the content for code generation
            workflow.chat_messages = chat_messages
            workflow.pdf_content = pdf_text
            workflow.code_repo_content = github_markdown
            
            self.logger.info(f"🚀 Workflow content setup completed:")
            self.logger.info(f"  workflow.pdf_content length: {len(workflow.pdf_content)} characters")
            self.logger.info(f"  workflow.code_repo_content length: {len(workflow.code_repo_content)} characters")
            self.logger.info(f"  workflow.chat_messages count: {len(workflow.chat_messages)} messages")
            
            # Execute the workflow
            result = await workflow.execute_workflow()
            
            if result:
                return f"""✅ *@Agent Workflow Completed!*

*Result Analysis:* {result}

📊 *Processing Statistics:*
• Historical Messages: {len(chat_messages)} messages
• PDF Documents: {len(pdf_contents)} documents
• GitHub Repositories: {len(github_contents)} repositories

🔗 *Generated Code Repository:* {workflow.repo_link if hasattr(workflow, 'repo_link') else 'Processing...'}

💡 *Tip:* Code has been automatically generated and deployed. You can check the repository for detailed information."""
            else:
                return "❌ *@Agent Workflow Failed*\n\nPlease check your input content or try again later."
                
        except Exception as e:
            self.logger.error(f"@Agent workflow execution failed: {e}")
            return f"❌ *@Agent Workflow Error:* {str(e)}"

    async def _get_recent_messages(self, user: User, channel_id: str, limit: int = 10) -> list:
        """Get recent messages from both database and Slack"""
        try:
            # Get from database first
            db_messages = await db_service.get_user_message_history(user.slack_user_id, limit)
            
            # Convert to list format
            messages = []
            for msg in db_messages:
                messages.append({
                    'original_message': msg.original_message,
                    'response_message': msg.response_message,
                    'slack_message_ts': msg.slack_message_ts,
                    'timestamp': msg.timestamp
                })
            
            # If we don't have enough messages from DB, try to get from Slack
            if len(messages) < limit and channel_id:
                try:
                    slack_history = await slack_service.get_full_conversation_history(
                        channel=channel_id,
                        access_token=None,
                        team_id=user.slack_team_id,  # 传入team_id以获取对应工作区的token
                        limit=limit
                    )
                    
                    if slack_history:
                        for slack_msg in slack_history:
                            if len(messages) >= limit:
                                break
                            
                            # Skip if we already have this message
                            msg_ts = slack_msg.get('ts')
                            if any(m.get('slack_message_ts') == msg_ts for m in messages):
                                continue
                            
                            messages.append({
                                'original_message': slack_msg.get('text', ''),
                                'response_message': None,
                                'slack_message_ts': msg_ts,
                                'timestamp': datetime.fromtimestamp(float(msg_ts)) if msg_ts else datetime.utcnow()
                            })
                            
                except Exception as e:
                    self.logger.warning(f"Failed to get Slack history: {e}")
            
            # Sort by timestamp and limit
            messages.sort(key=lambda x: x['timestamp'], reverse=True)
            return messages[:limit]
            
        except Exception as e:
            self.logger.error(f"Error getting recent messages: {e}")
            return []

    async def _get_pdf_content_by_message_ts(self, user_id: str, message_ts: str) -> dict:
        """Get PDF content by message timestamp"""
        try:
            self.logger.info(f"🔍 查找PDF内容 - 用户ID: {user_id}, 消息时间戳: {message_ts}")
            
            db = await db_service.get_db()

            # 查找特定时间戳的PDF文档
            pdf_doc = await db.pdf_documents.find_one({
                "slack_user_id": user_id,
                "slack_message_ts": message_ts
            })
            
            if pdf_doc:
                extracted_text = pdf_doc.get('extracted_text', '')
                file_name = pdf_doc.get('file_name', '')
                file_url = pdf_doc.get('file_url', '')
                
                self.logger.info(f"✅ 找到匹配的PDF文档 - 文件名: {file_name}, 文本长度: {len(extracted_text)}")
                
                return {
                    'extracted_text': extracted_text,
                    'file_name': file_name,
                    'file_url': file_url
                }
            else:
                self.logger.warning(f"❌ 未找到匹配的PDF文档 - 用户ID: {user_id}, 时间戳: {message_ts}")
                return None
            
        except Exception as e:
            self.logger.error(f"Error getting PDF content: {e}")
            return None

    async def _get_github_content_by_message_ts(self, user_id: str, message_ts: str) -> dict:
        """Get GitHub content by message timestamp"""
        try:
            github_repo = await db_service.get_github_repository_by_message(user_id, message_ts)
            
            if github_repo and github_repo.markdown_content:
                return {
                    'markdown_content': github_repo.markdown_content,
                    'github_url': github_repo.github_url,
                    'owner': github_repo.owner,
                    'repo_name': github_repo.repo_name
                }
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting GitHub content: {e}")
            return None

# Global message service instance
message_service = MessageService()