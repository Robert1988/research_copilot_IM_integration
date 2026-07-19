import logging
import os
import asyncio
import aiohttp
import boto3
import base64
import json
import re
from pathlib import Path
from base64 import b64encode
from nacl import encoding, public
from dotenv import load_dotenv
# 使用标准 logging 模块
import ast
from botocore.config import Config
from botocore.exceptions import ClientError  # 新增：记录更详细的 ECR ClientError
# 导入新的代码生成处理器
from services.code_generate_handler import CodeGenerateHandler
from services.code_fix_handler import CodeFixHandler
from services.user_reply_handler import UserReplyHandler
from typing import Optional
# 修改：使用项目的 database_service 而不是直接连接 MongoDB
from services.database_service import db_service
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings
from datetime import datetime


class AgentWorkFlow:
    """代理工作流类，负责管理从实验代码生成到AWS部署的完整流程"""
    
    def __init__(self, post_id: str, comment_id: str, output_path: str = "auto_generated_project",
     paper_summary:str="", new_ideas:str="",paper_txt:str="", 
     chat_messages: list = [], code_repo_content: str = "", pdf_content: str = "", 
     generation_mode: str = "paper", reply_to_content: str = "", reply_to_code_mark_down: str=''):
        # 确保环境变量被加载
        load_dotenv()
        
        self.post_id = post_id
        self.comment_id = comment_id
        self.repo_link = None
    
        self.output_path = output_path
        # 使用标准 logging 模块初始化 logger
        self.logger = logging.getLogger(__name__)
        # 在初始化时获取GitHub用户信息
        self.github_user = os.getenv("GITHUB_USERNAME")
        # 添加GitHub token到初始化
        self.github_token = os.getenv("GITHUB_TOKEN")
        # 添加AWS相关信息到初始化
        self.aws_access_key = os.getenv("AWS_ACCESS_KEY")
        self.aws_secret_key = os.getenv("AWS_SECRET_KEY")
        self.aws_account_id = os.getenv("AWS_ACCOUNT_ID")
        self.aws_region = os.getenv("AWS_REGION")
        # 移除直接的 MongoDB 连接
        # self.mongo_uri = os.getenv("MONGODB_URI")
        self.paper_summary = paper_summary
        self.new_ideas = new_ideas
        self.paper_txt = paper_txt
        
        # 新增的参数
        self.chat_messages = chat_messages
        self.code_repo_content = code_repo_content
        self.pdf_content = pdf_content
        self.generation_mode = generation_mode  # "paper" 或 "chat"
    
        # 初始化代码生成和修复处理器
        self.code_generate_handler = CodeGenerateHandler(output_path=output_path, 
            paper_summary=paper_summary, new_ideas=new_ideas, paper_txt=paper_txt,
            reply_to_content=reply_to_content,
            reply_to_code_mark_down=reply_to_code_mark_down
            )
        
        self.code_fix_handler = CodeFixHandler()
        # 初始化用户回复处理器
        self.user_reply_handler = UserReplyHandler()
        # 添加新的初始化变量
        self.experiment_file_path = None
        self.reply = None
    
        self.user_id = 'agent_101'
        
        # 移除直接的 MongoDB 连接，使用 database_service
        # if AgentWorkFlow._mongo_client is None:
        #         AgentWorkFlow._mongo_client = AsyncIOMotorClient(self.mongo_uri)
        # self.db = AgentWorkFlow._mongo_client[settings.MONGODB_DB_NAME]

        self.reply_to_content = reply_to_content
        self.reply_to_code_mark_down = reply_to_code_mark_down
    
    # ==================== 实验代码生成相关方法 ====================
    
    async def _generate_experiment_code(self) -> None:
        """生成实验代码的主函数"""
        if self.generation_mode == "chat":
            await self._generate_experiment_code_in_chat()
        else:
            await self.code_generate_handler.generate_experiment_code()
    
    async def _generate_experiment_code_in_chat(self) -> None:
        """基于私聊文本、代码仓库和PDF内容生成实验代码"""
        # 将chat_messages列表转换为字符串
        chat_messages_str = "\n".join([f"message{i+1}: {msg}" for i, msg in enumerate(self.chat_messages)]) if self.chat_messages else ""
        
        await self.code_generate_handler.generate_experiment_code_in_chat(
            chat_messages=chat_messages_str,
            code_repo_content=self.code_repo_content,
            pdf_content=self.pdf_content
        )
    
    # ==================== GitHub 上传相关方法 ====================
    
    def _encrypt(self, public_key: str, secret_value: str) -> str:
        """使用公钥加密字符串"""
        public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder)
        sealed_box = public.SealedBox(public_key_obj)
        encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
        return b64encode(encrypted).decode("utf-8")
    
    async def _update_repo_secrets(self, owner: Optional[str], repo: str):
        """Update GitHub repository secrets"""
        token = self.github_token
        secrets = {
            "AWS_ACCESS_KEY_ID": self.aws_access_key,
            "AWS_SECRET_ACCESS_KEY": self.aws_secret_key,
            "AWS_REGION": self.aws_region,
            "AWS_ACCOUNT_ID": self.aws_account_id,
        }
        
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/public-key",
                headers=headers,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"获取公钥失败: {response.status}, {error_text}")
                
                public_key_data = await response.json()
                public_key = public_key_data["key"]
                key_id = public_key_data["key_id"]
                
                for secret_name, secret_value in secrets.items():
                    if secret_value is None:
                        self.logger.error(f"环境变量 {secret_name} 未设置")
                        continue
                    encrypted_value = self._encrypt(public_key, secret_value)
                    data = {"encrypted_value": encrypted_value, "key_id": key_id}
                    
                    async with session.put(
                        f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{secret_name}",
                        headers=headers,
                        json=data,
                    ) as response:
                        if response.status in [201, 204]:
                            self.logger.info(f"Secret {secret_name} 设置成功")
                        else:
                            error_text = await response.text()
                            self.logger.error(f"设置 {secret_name} 失败: {response.status}, {error_text}")
    
    async def _delete_repo_secrets(self, owner: Optional[str], repo: str, secret_names=None):
        """删除 GitHub 仓库的 secrets"""
        token = self.github_token
        
        if secret_names is None:
            secret_names = [
                "AWS_ACCESS_KEY",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_REGION",
                "AWS_ACCOUNT_ID",
            ]
        
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        
        async with aiohttp.ClientSession() as session:
            for secret_name in secret_names:
                async with session.delete(
                    f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{secret_name}",
                    headers=headers,
                ) as response:
                    if response.status == 204:
                        self.logger.info(f"Secret {secret_name} 删除成功")
                    elif response.status == 404:
                        self.logger.info(f"Secret {secret_name} 不存在")
                    else:
                        error_text = await response.text()
                        self.logger.error(f"删除 {secret_name} 失败: {response.status}, {error_text}")

    async def _delete_ecr_images(self, repository_name: str):
        """删除 ECR 仓库中的所有镜像"""
        try:
            self.logger.info(f"开始删除 ECR 仓库镜像，repo={repository_name}")
            
            creds = self._get_aws_credentials()
            region = creds["region"]
            self.logger.info(f"ECR 区域: {region}，仓库: {repository_name}")
            ecr_client = boto3.client(
                'ecr',
                aws_access_key_id=creds["access_key"],
                aws_secret_access_key=creds["secret_key"],
                region_name=region,
            )
            
            try:
                # 分页获取所有镜像
                image_ids = []
                next_token = None
                page = 1
                while True:
                    params = {"repositoryName": repository_name}
                    if next_token:
                        params["nextToken"] = next_token
                    resp = ecr_client.list_images(**params)
                    ids = resp.get("imageIds", [])
                    self.logger.info(f"第 {page} 页获取到 {len(ids)} 个镜像")
                    image_ids.extend(ids)
                    next_token = resp.get("nextToken")
                    page += 1
                    if not next_token:
                        break

                self.logger.info(f"总计发现 {len(image_ids)} 个镜像待删除")
                if not image_ids:
                    self.logger.info(f"ECR 仓库 {repository_name} 中没有镜像需要删除")
                    return

                # 预览前几个镜像标识
                preview = []
                for item in image_ids[:5]:
                    tag = item.get("imageTag")
                    digest = item.get("imageDigest")
                    preview.append(tag or digest)
                self.logger.info(f"待删除镜像示例（最多5个）: {preview}")

                # 按批次删除（ECR 一次最多 100 个）
                batch_size = 100
                total_deleted = 0
                total_failures = 0
                for start in range(0, len(image_ids), batch_size):
                    batch = image_ids[start:start + batch_size]
                    batch_index = start // batch_size + 1
                    self.logger.info(f"开始删除第 {batch_index} 批，共 {len(batch)} 个镜像")
                    delete_response = ecr_client.batch_delete_image(
                        repositoryName=repository_name,
                        imageIds=batch
                    )
                    deleted_images = delete_response.get('imageIds', [])
                    failures = delete_response.get('failures', [])
                    total_deleted += len(deleted_images)
                    total_failures += len(failures)
                    self.logger.info(f"第 {batch_index} 批删除完成：成功 {len(deleted_images)} 个，失败 {len(failures)} 个")
                    if failures:
                        for failure in failures[:5]:
                            self.logger.warning(f"删除失败详情（示例）: {failure}")

                self.logger.info(f"删除完成：成功 {total_deleted} 个，失败 {total_failures} 个")
                        
            except ecr_client.exceptions.RepositoryNotFoundException:
                self.logger.info(f"ECR 仓库 {repository_name} 不存在，无需删除镜像")
            except ClientError as e:
                self.logger.error(f"删除 ECR 镜像时发生 ClientError: {e.response.get('Error', {})}")
            except Exception as e:
                self.logger.error(f"删除 ECR 镜像时出错: {str(e)}")
                
        except Exception as e:
            self.logger.error(f"删除 ECR 镜像失败: {str(e)}")
            # 不抛出异常，因为这是清理操作，不应该影响主流程
    
    async def _upload_to_github(self, project_path):
        """Upload project to GitHub using API"""
        try:
            if isinstance(project_path, str):
                project_path = Path(project_path)
            

            token = self.github_token
            
            repo_name = project_path.name
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }
            data = {"name": repo_name, "auto_init": False, "private": True}
            
            async with aiohttp.ClientSession() as session:
                # 检查仓库是否已存在
                await asyncio.sleep(2)
                
                async with session.get(
                    f"https://api.github.com/repos/{self.github_user}/{repo_name}",
                    headers=headers,
                ) as check_response:
                    self.logger.info(f"check_response: {repo_name}")
                
                    if check_response.status == 200:
                        # 仓库已存在，删除它
                        async with session.delete(
                            f"https://api.github.com/repos/{self.github_user}/{repo_name}",
                            headers=headers,
                        ) as delete_response:
                            if delete_response.status >= 400:
                                error_text = await delete_response.text()
                                raise Exception(f"Failed to delete repository: {error_text}")
                            self.logger.info(f"Deleted existing repository: {repo_name}")
                
                # 创建仓库
                async with session.post(
                    "https://api.github.com/user/repos", headers=headers, json=data
                ) as response:
                    if response.status >= 400:
                        error_text = await response.text()
                        raise Exception(f"Failed to create repository: {error_text}")
                    response_data = await response.json()
                    repo_url = response_data["html_url"]
                    owner_login = response_data["owner"]["login"]
                
                # 添加延迟，等待仓库准备就绪
                await asyncio.sleep(2)
                
                # Upload files
                for file_path in project_path.glob("**/*"):
                    if file_path.is_file():
                        relative_path = str(file_path.relative_to(project_path)).replace(
                            "\\", "/"
                        )
                        with open(file_path, 'rb') as f:
                            content = base64.b64encode(f.read()).decode('utf-8')
                        
                        upload_url = f"https://api.github.com/repos/{owner_login}/{repo_name}/contents/{relative_path}"
                        upload_data = {
                            "message": f"Add {relative_path}",
                            "content": content,
                        }
                        
                        # 添加重试逻辑
                        max_retries = 3
                        retry_delay = 1
                        
                        for attempt in range(max_retries):
                            try:
                                async with session.put(
                                    upload_url, headers=headers, json=upload_data
                                ) as upload_response:
                                    if upload_response.status >= 400:
                                        error_text = await upload_response.text()
                                        if attempt < max_retries - 1:
                                            self.logger.warning(
                                                f"Attempt {attempt+1} failed to upload {relative_path}: {error_text}. Retrying..."
                                            )
                                            await asyncio.sleep(retry_delay)
                                            retry_delay *= 2
                                        else:
                                            raise Exception(
                                                f"Failed to upload {relative_path}: {error_text}"
                                            )
                                    else:
                                        break
                            except aiohttp.ClientError as e:
                                if attempt < max_retries - 1:
                                    self.logger.warning(
                                        f"Network error on attempt {attempt+1} for {relative_path}: {str(e)}. Retrying..."
                                    )
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2
                                else:
                                    raise
            
            self.logger.info(f"Project uploaded to GitHub: {repo_url}")
            return repo_url
        except Exception as e:
            self.logger.error(f"Error uploading to GitHub: {str(e)}")
            raise
    
    # ==================== AWS 部署相关方法 ====================
    
    def _get_aws_credentials(self):
        """Load AWS credentials from .env"""
        load_dotenv("auto_generated_project/.env")
        return {
            "access_key": self.aws_access_key,
            "secret_key": self.aws_secret_key,
            "region": self.aws_region,
        }
    
    async def _trigger_github_workflow_async(self, repo_url):
        """异步触发GitHub部署工作流"""
        try:
            repo_path = repo_url.split("github.com/")[1]
            owner, repo = repo_path.split("/")
            
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
            }
            url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/build-deployment-prod.yaml/dispatches"
            data = {"ref": "main"}
            
            async with aiohttp.ClientSession() as session:
                # 触发工作流
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 204:
                        self.logger.info("GitHub工作流触发成功")
                        
                        # 等待一段时间让工作流开始
                        await asyncio.sleep(5)
                        
                        # 获取最新的工作流运行ID
                        runs_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
                        async with session.get(runs_url, headers=headers) as runs_response:
                            if runs_response.status == 200:
                                runs_data = await runs_response.json()
                                if runs_data["workflow_runs"]:
                                    # 获取最新的工作流运行ID
                                    latest_run = runs_data["workflow_runs"][0]
                                    workflow_id = latest_run["id"]
                                    self.logger.info(f"获取到工作流运行ID: {workflow_id}")
                                    return workflow_id
                                else:
                                    self.logger.warning("未找到工作流运行记录")
                                    return None
                            else:
                                error_text = await runs_response.text()
                                self.logger.error(f"获取工作流运行列表失败: {runs_response.status}, {error_text}")
                                return None
        except Exception as e:
            self.logger.error(f"触发GitHub工作流时出错: {str(e)}")
            return None
    
    async def _check_workflow_status(self, repo, workflow_id=None):
        """异步检查GitHub工作流状态"""
        try:
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
            }
            
            async with aiohttp.ClientSession() as session:
                url = f"https://api.github.com/repos/{self.github_user}/{repo}/actions/runs/{workflow_id}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["status"], data["conclusion"]
                    else:
                        error_text = await response.text()
                        self.logger.error(
                            f"获取工作流状态失败: {response.status}, {error_text}"
                        )
                        return None, None
        except Exception as e:
            self.logger.error(f"检查工作流状态时出错: {str(e)}")
            return None, None
    
    async def _create_ecr_repository(self, repository_name):
        """创建 ECR 仓库（如果不存在）"""
        try:
            self.logger.info(f"正在检查/创建 ECR 仓库: {repository_name}")
            
            creds = self._get_aws_credentials()
            ecr_client = boto3.client(
                'ecr',
                aws_access_key_id=creds["access_key"],
                aws_secret_access_key=creds["secret_key"],
                region_name=creds["region"],
            )
            
            try:
                response = ecr_client.describe_repositories(
                    repositoryNames=[repository_name]
                )
                self.logger.info(f"ECR 仓库 {repository_name} 已存在")
                return response['repositories'][0]['repositoryUri']
            except ecr_client.exceptions.RepositoryNotFoundException:
                response = ecr_client.create_repository(repositoryName=repository_name)
                self.logger.info(f"已创建 ECR 仓库 {repository_name}")
                return response['repository']['repositoryUri']
        except Exception as e:
            self.logger.error(f"创建 ECR 仓库时出错: {str(e)}")
            raise
    
    async def _deploy_to_lambda(self, repo_url):
        """部署到AWS Lambda的函数"""
        try:
            self.logger.info("Starting AWS Lambda deployment process")
            
            repo_path = repo_url.split("github.com/")[1]
            owner, repo = repo_path.split("/")
            
            # 创建 ECR 仓库
            repository_uri = await self._create_ecr_repository(repo)
            self.logger.info(f"确保 ECR 仓库存在: {repository_uri}")
            
            # 触发GitHub工作流
            workflow_id = await self._trigger_github_workflow_async(repo_url)
            if not workflow_id:
                raise Exception("Failed to trigger GitHub workflow")
            
            # 等待工作流完成
            self.logger.info("等待GitHub工作流完成...")
            await asyncio.sleep(30)  # 等待工作流开始
            
            # 检查工作流状态
            max_wait_time = 600  # 最大等待时间（秒）
            check_interval = 30  # 检查间隔（秒）
            elapsed_time = 0
            
            while elapsed_time < max_wait_time:
                status, conclusion = await self._check_workflow_status(repo, workflow_id)
                if status == "completed":
                    if conclusion == "success":
                        self.logger.info("GitHub工作流执行成功")
                        break
                    else:
                        raise Exception(f"GitHub工作流执行失败: {conclusion}")
                elif status in ["cancelled", "failure"]:
                    raise Exception(f"GitHub工作流状态异常: {status}")
                
                self.logger.info(f"工作流状态: {status}, 继续等待...")
                await asyncio.sleep(check_interval)
                elapsed_time += check_interval
            
            if elapsed_time >= max_wait_time:
                self.logger.warning("工作流等待超时，继续执行Lambda调用")
            
            creds = self._get_aws_credentials()
            lambda_client = boto3.client(
                'lambda',
                aws_access_key_id=creds["access_key"],
                aws_secret_access_key=creds["secret_key"],
                region_name=creds["region"],
                config=Config(
                    read_timeout=300,  # 15分钟读取超时，与Lambda函数超时时间一致
                    connect_timeout=60,  # 1分钟连接超时
                    retries={'max_attempts': 0}  # 禁用重试避免额外延迟
                )
            )
            # self.logger.info(f"creds {creds}")

            # 调用Lambda函数
            account_id = self.aws_account_id
            self.logger.info(f"account_id in deploying lambda{account_id}")
            region = creds["region"]
            image_uri = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{repo}:latest"

            lambda_function_name = f"lambda-{repo}"
            # 检查Lambda函数是否已存在
            try:
                lambda_client.get_function(FunctionName=lambda_function_name)
                function_exists = True
            except lambda_client.exceptions.ResourceNotFoundException:
                function_exists = False

            # 设置通用的Lambda配置参数
            lambda_config = {
                "FunctionName": lambda_function_name,
                "PackageType": "Image",
                "MemorySize": 3008,  # 约3GB内存
                "Timeout": 900,      # 15分钟超时
                "Environment": {
                    "Variables": {
                        "PYTHONUNBUFFERED": "1",
                        "PYTHONDONTWRITEBYTECODE": "1"
                    }
                }
            }

            if not function_exists:
                # 创建新的Lambda函数
                self.logger.info("Creating new Lambda function")
                # 添加创建特有的参数
                lambda_config.update({
                    "Code": {"ImageUri": image_uri},
                    "Role": os.getenv("LAMBDA_EXECUTION_ROLE_ARN")  # 需要在.env中设置
                })
                
                # 如果KMS密钥存在，添加到配置中
                kms_key_arn = os.getenv("KMS_KEY_ARN")
                if kms_key_arn:
                    lambda_config["KMSKeyArn"] = kms_key_arn
                
                response = lambda_client.create_function(**lambda_config)
            else:
                # 更新现有Lambda函数
                self.logger.info("Updating existing Lambda function")
                
                # 先更新函数代码
                response = lambda_client.update_function_code(
                    FunctionName=lambda_function_name,
                    ImageUri=image_uri
                )

                # 等待函数代码更新完成
                function_name = response["FunctionName"]
                self.logger.info(f"Waiting for Lambda function code update to complete...")
                waiter = lambda_client.get_waiter('function_updated')
                waiter.wait(FunctionName=function_name)
                
                # 然后更新函数配置
                # 对于容器镜像类型的Lambda，不需要设置Handler参数
                response = lambda_client.update_function_configuration(
                    FunctionName=lambda_function_name,
                    MemorySize=lambda_config["MemorySize"],
                    Timeout=lambda_config["Timeout"],
                    Environment=lambda_config["Environment"]
                )
            
            # 等待Lambda函数更新完成
            function_name = response["FunctionName"]
            self.logger.info(f"Waiting for Lambda function {function_name} to be ready...")
            waiter = lambda_client.get_waiter('function_active')
            waiter.wait(FunctionName=function_name)

            self.logger.info("Invoking Lambda function")
            lambda_response = None
            lambda_request_id = None  # 初始化变量，避免未绑定错误
            # 在_deploy_to_lambda函数中
            try:
                response = lambda_client.invoke(
                    FunctionName=function_name,
                    InvocationType='RequestResponse',  # 同步调用
                    Payload=json.dumps({}),
                    LogType='Tail'
                )
                
                # 保存原始响应对象
                lambda_response = response
                # 提取本次调用的 RequestId
                lambda_request_id = response.get("ResponseMetadata", {}).get("RequestId")
                self.logger.info(f"Lambda RequestId: {lambda_request_id}")
                
                await asyncio.sleep(5)

                # 获取状态码
                status_code = response['StatusCode']
                self.logger.info(f"Lambda execution status code: {status_code}")
                
                # 获取日志结果（base64编码，需要解码）
                log_result_encoded = response.get('LogResult', '')
                if log_result_encoded:
                    import base64
                    log_result = base64.b64decode(log_result_encoded).decode('utf-8')
                    self.logger.info(f"Lambda execution logs:\n{log_result}")
                else:
                    log_result = "No logs available"
                    self.logger.warning("No execution logs returned from Lambda")

            except lambda_client.exceptions.ResourceNotFoundException:
                self.logger.error(f"Lambda函数 {function_name} 不存在")
                log_result = f"Error: Lambda function {function_name} not found"
            except Exception as e:
                self.logger.error(f"调用Lambda函数时出错: {str(e)}")
                log_result = f"Error invoking Lambda: {str(e)}"
                
            # 获取详细的Lambda日志
            try:
                logs_client = boto3.client(
                    'logs',
                    aws_access_key_id=creds["access_key"],
                    aws_secret_access_key=creds["secret_key"],
                    region_name=creds["region"],
                )
                
                log_group_name = f"/aws/lambda/{function_name}"
                
                # 获取最新的日志流
                streams_response = logs_client.describe_log_streams(
                    logGroupName=log_group_name,
                    orderBy='LastEventTime',
                    descending=True,
                    limit=1
                )
                
                if streams_response['logStreams']:
                    latest_stream = streams_response['logStreams'][0]['logStreamName']
                    
                    # 获取日志事件
                    log_events = logs_client.get_log_events(
                        logGroupName=log_group_name,
                        logStreamName=latest_stream,
                        startFromHead=True,
                        limit=1000,
                    )
                    
                    complete_logs = '\n'.join(
                        [event['message'] for event in log_events['events']]
                    )
                    self.logger.info(f"Complete Lambda logs:\n{complete_logs}")
                    
                    # ==================== 新增：保存logs到文件并上传到GitHub ====================
                    # 保存logs到execution_log.txt文件，只保存最新一次运行的日志
                    log_file_path = Path(self.output_path) / "execution_log.txt"
                    with open(log_file_path, 'w', encoding='utf-8') as f:
                        f.write("Lambda Execution Result (Latest Run):\n")
                        f.write(complete_logs + "\n")
                    
                    self.logger.info(f"Latest execution logs saved to {log_file_path}")
                    
                    # 上传execution_log.txt到GitHub
                    await self._upload_single_file_to_github(owner, repo, log_file_path, "execution_log.txt")
                    
                else:
                    self.logger.warning(f"No log streams found for {function_name}")
                    complete_logs = log_result
            
            except Exception as e:
                self.logger.error(f"Error retrieving complete logs: {str(e)}")
                complete_logs = log_result
            
            self.logger.info("AWS Lambda deployment completed successfully")
            return log_result, complete_logs, lambda_request_id
        except Exception as e:
            self.logger.error(f"AWS Lambda deployment failed: {str(e)}")
            raise
    
    async def _upload_single_file_to_github(self, owner: str, repo: str, file_path: Path, github_file_path: str):
        """上传单个文件到GitHub仓库"""
        try:
            token = self.github_token
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }
            
            # 读取文件内容并编码
            with open(file_path, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
            
            upload_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{github_file_path}"
            
            async with aiohttp.ClientSession() as session:
                # 检查文件是否已存在
                async with session.get(upload_url, headers=headers) as check_response:
                    upload_data = {
                        "message": f"Update {github_file_path}",
                        "content": content,
                    }
                    
                    # 如果文件已存在，需要提供sha值
                    if check_response.status == 200:
                        existing_file = await check_response.json()
                        upload_data["sha"] = existing_file["sha"]
                        self.logger.info(f"File {github_file_path} exists, updating...")
                    else:
                        upload_data["message"] = f"Add {github_file_path}"
                        self.logger.info(f"File {github_file_path} does not exist, creating...")
                
                # 上传文件
                async with session.put(upload_url, headers=headers, json=upload_data) as upload_response:
                    if upload_response.status in [200, 201]:
                        self.logger.info(f"Successfully uploaded {github_file_path} to GitHub")
                    else:
                        error_text = await upload_response.text()
                        raise Exception(f"Failed to upload {github_file_path}: {error_text}")
                        
        except Exception as e:
            self.logger.error(f"Error uploading {github_file_path} to GitHub: {str(e)}")
            raise
    
    async def _archive_repository(self, repo: str):
        """Archive GitHub repository"""
        token = self.github_token
        
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        
        data = {"archived": True}
        
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                f"https://api.github.com/repos/{self.github_user}/{repo}",
                headers=headers,
                json=data,
            ) as response:
                if response.status == 200:
                    self.logger.info(f"Repository {self.github_user}/{repo} archived successfully")
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to archive repository {self.github_user}/{repo}: {response.status}, {error_text}")

    async def _set_repository_public(self, repo: str):
        """Set GitHub repository visibility to public"""
        token = self.github_token
        
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        
        data = {"private": False}
        
        async with aiohttp.ClientSession() as session:
            repo_url = f"https://api.github.com/repos/{self.github_user}/{repo}"
            # 设置前先读取仓库当前状态
            try:
                async with session.get(repo_url, headers=headers) as before_resp:
                    if before_resp.status == 200:
                        before_info = await before_resp.json()
                        self.logger.info(f"设置前仓库状态: private={before_info.get('private')}, archived={before_info.get('archived')}, visibility={before_info.get('visibility')}")
                    else:
                        before_err = await before_resp.text()
                        self.logger.warning(f"获取设置前仓库状态失败: {before_resp.status}, {before_err}")
            except Exception as e:
                self.logger.warning(f"获取设置前仓库状态时异常: {str(e)}")

            self.logger.info(f"准备将仓库设置为 public: repo={self.github_user}/{repo}, payload={data}")
            async with session.patch(
                repo_url,
                headers=headers,
                json=data,
            ) as response:
                if response.status == 200:
                    self.logger.info(f"Repository {self.github_user}/{repo} set to public successfully，开始校验更新结果")
                    # 设置成功后再次获取状态校验
                    try:
                        async with session.get(repo_url, headers=headers) as after_resp:
                            if after_resp.status == 200:
                                after_info = await after_resp.json()
                                self.logger.info(f"设置后仓库状态: private={after_info.get('private')}, archived={after_info.get('archived')}, visibility={after_info.get('visibility')}")
                            else:
                                after_err = await after_resp.text()
                                self.logger.warning(f"获取设置后仓库状态失败: {after_resp.status}, {after_err}")
                    except Exception as e:
                        self.logger.warning(f"获取设置后仓库状态时异常: {str(e)}")
                else:
                    error_text = await response.text()
                    if response.status == 403:
                        self.logger.error(f"Failed to set repository {self.github_user}/{repo} to public (可能权限不足或仓库处于归档状态): {response.status}, {error_text}")
                    elif response.status == 404:
                        self.logger.error(f"Failed to set repository {self.github_user}/{repo} to public (仓库不存在或 token 无权限): {response.status}, {error_text}")
                    else:
                        self.logger.error(f"Failed to set repository {self.github_user}/{repo} to public: {response.status}, {error_text}")

    # ==================== 主要工作流方法 ====================
    
    async def execute_workflow(self) -> Optional[str]:
        """执行完整的工作流程
        
        Args:
            paper_summary_file: 论文摘要文件路径
            
        Returns:
            str: user reply info
            
        """
        try:
            # Step 1: Generate experiment code
            self.logger.info("Starting experiment code generation")
            await self._generate_experiment_code()
        
            # Step 2: Upload to GitHub
            self.logger.info("Uploading project to GitHub")
            repo_url = await self._upload_to_github(self.output_path)
        
            # Step 3: Deploy to AWS Lambda
            self.logger.info("Uploading repo secrets")
            # 使用初始化时获取的用户信息
            await self._update_repo_secrets(self.github_user, self.output_path)
        
            self.logger.info("Deploying to AWS Lambda")
            log_results, logs_history, lambda_request_id = await self._deploy_to_lambda(repo_url)
            # self.logger.info(f"Lambda 执行日志: {log_results}")
            self.logger.info(f"lambda_request_id: {lambda_request_id}")

        
            self.experiment_file_path = Path(self.output_path) / "experiment.py"
            max_fix_attempts = 3
            
            # 读取 Lambda 响应并获取状态码
            experiment_status_code, extract_log = self.extractLogInfo(logs_history,request_id = lambda_request_id)

            self.logger.info(f"Lambda 执行状态码: {experiment_status_code}")
            self.logger.info(f"Lambda 执行日志完整: {logs_history}")
            self.logger.info(f"Lambda 执行日志抽取部分: {extract_log}")
            
            attempt = 0
            for attempt in range(max_fix_attempts):
                # 检查是否有错误需要修正
                if experiment_status_code == 200:
                    self.logger.info("代码执行成功，无需修正")
                    break
                else:
                    self.logger.info(f"Lambda返回状态码: {experiment_status_code}，需要修正代码")
                
                
                self.logger.info(f"开始第 {attempt + 1} 次代码修正尝试")
                self.logger.info(f"第 {attempt + 1} 次修正尝试错误日志: {logs_history}")
                
                # 尝试修正代码
                fix_success = await self.code_fix_handler.fix_experiment_code(
                    str(self.experiment_file_path),
                    logs_history
                )
                
                if not fix_success:
                    self.logger.error(f"第 {attempt + 1} 次代码修正失败")
                    if attempt == max_fix_attempts - 1:
                        self.logger.error("已达到最大修正次数，修正失败")
                        break
                    continue
                
                # 重新上传到 GitHub
                try:
                    self.logger.info(f"第 {attempt + 1} 次重新上传到 GitHub")
                    repo_url = await self._upload_to_github(self.output_path)

                    self.logger.info(f"第 {attempt + 1} Uploading repo secrets")
                    # 使用初始化时获取的用户信息
                    await self._update_repo_secrets(self.github_user, self.output_path)
                except Exception as e:
                    self.logger.error(f"第 {attempt + 1} 次上传到 GitHub 失败: {str(e)}")
                    if attempt == max_fix_attempts - 1:
                        break
                    continue
                
                # 重新部署到 Lambda
                try:
                    self.logger.info(f"第 {attempt + 1} 次重新部署到 Lambda")
                    log_results, logs_history, lambda_request_id = await self._deploy_to_lambda(repo_url)

                    # 检查新的部署结果
                    try:
                        experiment_status_code, complete_log = self.extractLogInfo(logs_history,request_id = lambda_request_id)
            
                        if experiment_status_code == 200:
                            self.logger.info(f"第 {attempt + 1} 次修正成功，代码执行正常")
                            break
                        else:
                            self.logger.warning(f"第 {attempt + 1} 次修正后仍有错误，准备下一次尝试")
                    except Exception as e:
                        self.logger.warning(f"解析Lambda响应失败: {str(e)}，使用原有错误检测方法")

                except Exception as e:
                    self.logger.error(f"第 {attempt + 1} 次部署到 Lambda 失败: {str(e)}")
                    logs = f"部署失败: {str(e)}"
                    if attempt == max_fix_attempts - 1:
                        break
                    continue
            
            self.logger.info("Deleting repo secrets")
            await self._delete_repo_secrets(self.github_user, self.output_path)
        
            # 删除 ECR 镜像
            self.logger.info(f"开始删除 ECR 镜像（repo={self.output_path}）")
            await self._delete_ecr_images(self.output_path)
            self.logger.info(f"结束删除 ECR 镜像（repo={self.output_path}）")
        
            # 设置仓库为public
            self.logger.info("Setting repository to public")
            await self._set_repository_public(self.output_path)

            # 立即再次读取仓库状态进行二次校验（与方法内的校验互为补充）
            try:
                headers = {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.github_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                async with aiohttp.ClientSession() as session:
                    url = f"https://api.github.com/repos/{self.github_user}/{self.output_path}"
                    async with session.get(url, headers=headers) as verify_resp:
                        if verify_resp.status == 200:
                            info = await verify_resp.json()
                            self.logger.info(f"设置public后即时校验: private={info.get('private')}, archived={info.get('archived')}, visibility={info.get('visibility')}")
                        else:
                            err = await verify_resp.text()
                            self.logger.warning(f"设置public后即时校验失败: {verify_resp.status}, {err}")
            except Exception as e:
                self.logger.warning(f"设置public后即时校验异常: {str(e)}")

            self.logger.info("Archiving repository")
            await self._archive_repository(self.output_path)
            

            self.repo_link = f"https://github.com/{self.github_user}/{self.output_path}"


            attempt += 1
             # 添加生成用户回复的步骤
            # 在reply生成后添加保存到MongoDB的逻辑
            self.logger.info("开始生成用户回复")
            
            reply = await self.user_reply_handler.generate_reply(
                self.paper_summary,self.new_ideas, self.experiment_file_path,logs_history
            )
            
            self.reply = reply
            
            # 添加保存数据至MongoDB的逻辑
            if reply is not None:
                await self.save_to_db(success=True, cost=attempt)
                self.logger.info("用户回复生成成功并保存到数据库")
                self.logger.info("Process completed successfully")
            else:
                await self.save_to_db(success=False, cost=attempt)
                self.logger.warning("用户回复生成失败，已记录到数据库")
                self.logger.warning("Process completed with failures")
        
            return reply
    
        except Exception as e:
            self.logger.info(f"Process failed: {str(e)}")
            self.logger.error(f"Process failed: {str(e)}")
            return None
            
    async def generate_experiment_code(self) -> None:
        """生成实验代码"""
        self.logger.info("Starting experiment code generation")
        await self._generate_experiment_code()
        
    async def upload_to_github(self) -> str:
        """上传项目到GitHub"""
        self.logger.info("Uploading project to GitHub")
        return await self._upload_to_github(self.output_path)
        
    async def deploy_to_aws(self, repo_url: str) -> str:
        """部署到AWS Lambda"""
        
        self.logger.info("Uploading repo secrets")
        await self._update_repo_secrets(self.github_user, self.output_path)
        
        try:
            self.logger.info("Deploying to AWS Lambda")
            logs = await self._deploy_to_lambda(repo_url)
            return logs
        finally:
            self.logger.info("Deleting repo secrets")
            await self._delete_repo_secrets(self.github_user, self.output_path)

    def extractLogInfo(self, log_result, request_id=None):
        """
        从Lambda日志中提取experimentStatusCode、stdout和stderr的值，并将stdout和stderr拼接成完整日志
        如果提供 request_id，则仅分析该 RequestId 对应 START 之后到日志结尾的片段（兼容出现 END/REPORT 后仍有输出的情况）
        
        Args:
            log_result: 已解码的Lambda日志文本
            request_id: 当前这次调用的 RequestId（可选，若提供则仅分析该调用对应的日志片段）
        
        Returns:
            tuple: (experimentStatusCode, complete_log) 元组，其中complete_log是stdout和stderr的拼接
        """
        try:
            # 初始化返回值
            experiment_status_code = None
            stdout = ""
            stderr = ""
        
            # 如果提供了 RequestId，则只截取该次调用的日志片段
            segment = log_result
            self.logger.info(f"Lambda 日志: {log_result}")

            # 使用更鲁棒的方法提取JSON
            import re
            import json
            
            # 查找包含 experimentStatusCode 的 JSON 块
            json_pattern = r'\{[^{}]*"experimentStatusCode"[^{}]*\}'
            
            # 首先尝试简单匹配
            matches = list(re.finditer(json_pattern, segment, re.DOTALL))
            
            if not matches:
                # 如果简单匹配失败，尝试更复杂的匹配，处理嵌套结构
                brace_count = 0
                start_pos = -1
                
                for i, char in enumerate(segment):
                    if char == '{':
                        if brace_count == 0:
                            start_pos = i
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0 and start_pos != -1:
                            json_candidate = segment[start_pos:i+1]
                            if '"experimentStatusCode"' in json_candidate:
                                try:
                                    json_data = json.loads(json_candidate)
                                    experiment_status_code = json_data.get('experimentStatusCode')
                                    
                                    # 获取body中的stdout和stderr
                                    if 'body' in json_data and isinstance(json_data['body'], dict):
                                        body = json_data['body']
                                        stdout = body.get('stdout', '') or ''
                                        stderr = body.get('stderr', '') or ''
                                        
                                        self.logger.info(f"成功解析JSON - experimentStatusCode: {experiment_status_code}")
                                        self.logger.info(f"stdout长度: {len(stdout)}, stderr长度: {len(stderr)}")
                                        break
                                except json.JSONDecodeError:
                                    continue
            else:
                # 使用简单匹配的结果
                json_str = matches[-1].group(0)
                try:
                    json_data = json.loads(json_str)
                    experiment_status_code = json_data.get('experimentStatusCode')
                    
                    # 获取body中的stdout和stderr
                    if 'body' in json_data and isinstance(json_data['body'], dict):
                        body = json_data['body']
                        stdout = body.get('stdout', '') or ''
                        stderr = body.get('stderr', '') or ''
                        
                        self.logger.info(f"成功解析JSON - experimentStatusCode: {experiment_status_code}")
                        self.logger.info(f"stdout长度: {len(stdout)}, stderr长度: {len(stderr)}")
                except json.JSONDecodeError:
                    self.logger.warning("无法解析匹配到的JSON数据")
        
            # 拼接stdout和stderr成完整日志
            complete_log = ""
            if stdout:
                complete_log += "===== STDOUT =====\n" + stdout + "\n"
            if stderr:
                complete_log += "===== STDERR =====\n" + stderr
            
            # 如果没有找到JSON数据但有日志内容，则直接返回原始日志片段
            if not complete_log and segment:
                complete_log = "===== RAW LOG =====\n" + segment
            
            return experiment_status_code, complete_log
        
        except Exception as e:
            self.logger.error(f"提取日志信息时出错: {str(e)}")
            return None,  ""


    async def save_to_db(self, success: bool = False, cost: int = 1) -> bool:
        """保存工作流执行状态到MongoDB
        
        Args:
            success: 是否成功生成回复
        
        Returns:
            bool: 保存是否成功
        """
        try:
            # 准备要保存的数据到新的 agent_workflows 表
            document = {
                "post_id": self.post_id,
                "comment_id": self.comment_id,
                "user_id": self.user_id,
                "repo_link": self.repo_link,
                "reply": self.reply,
                "success": success,
                "created_at": datetime.utcnow(),
                "cost": cost,
                "workflow_status": "completed" if success else "failed"
            }
            
            # 使用 database_service 而不是直接的数据库连接
            db = await db_service.get_db()
            await db.agent_workflows.insert_one(document)
            
            self.logger.info(f"成功保存工作流执行状态到MongoDB agent_workflows表: {self.post_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"保存工作流执行状态到MongoDB失败: {str(e)}")
            return False
        
        
