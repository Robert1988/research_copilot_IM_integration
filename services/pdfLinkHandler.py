import aiohttp
import re
from urllib.parse import urlparse
import os
import asyncio
import logging

from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import multiprocessing

import PyPDF2
import aiohttp
import cv2
import numpy as np
import pytesseract
from motor.motor_asyncio import AsyncIOMotorClient
from pdf2image import convert_from_path
from tqdm.asyncio import tqdm_asyncio
from config import settings
import hashlib
from .analyzer import PaperAnalyzer
from .user_plan_manager import UserPlanManager
from .config_user_plan import get_feature_credit_cost
from .license_validation import LicenseValidator

from datetime import datetime, timezone
from typing import Dict, List

from bson import ObjectId

# Poppler路径配置
POPPLER_PATH = os.getenv('POPPLER_PATH', None)

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# 定义PDF保存目录（在当前目录下的pdfs文件夹）
PDF_DIR = os.path.join(current_dir, 'pdfs')
os.makedirs(PDF_DIR, exist_ok=True)
TXT_DIR = os.path.join(current_dir, 'txts')
os.makedirs(TXT_DIR, exist_ok=True)

from typing import Optional, Dict, Tuple, Union
from models import PDFProcessingTask, PDFProcessingStatus
from .auth import get_db
from urllib.parse import urlparse

class PDFLinkHandler:
    # 类变量共享client
    _client = None
    # 类变量共享线程池
    _executor = None
    
    def __init__(self, url: str, is_cdn_url: bool = False, slack_token: str = None):
        """
        初始化PDF链接处理器
        
        Args:
            url: PDF文件URL
            is_cdn_url: 是否为CDN URL
            slack_token: Slack Bot Token，用于下载私有文件
        """
        # Try multiple environment variable names for MongoDB URI
        self.mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URL")
        if self.mongo_uri is None:
            raise ValueError("MongoDB URI environment variable not set (tried MONGODB_URI and MONGODB_URL)")

        if PDFLinkHandler._client is None:
            PDFLinkHandler._client = AsyncIOMotorClient(self.mongo_uri)
        self.client = PDFLinkHandler._client
        self.logger = logging.getLogger(__name__)
        self.db = self.client[settings.MONGODB_DB_NAME]
        self.slack_token = slack_token  # 添加Slack token支持
        
        # 如果是 CDN URL，转换为 S3 URL
        if is_cdn_url:
            self.url = self._convert_cdn_to_s3_url(url)
            self.original_url = url  # 保存原始 CDN URL
        else:
            self.url = url
            self.original_url = url
        
        # 使用类共享线程池
        if PDFLinkHandler._executor is None:
            # 根据CPU核心数设置线程池大小
            # 一般建议线程数为CPU核心数的1-2倍，这里使用1.5倍
            cpu_count = multiprocessing.cpu_count()
            # max_workers = max(3, int(cpu_count * 1.5))  # 至少3个线程
            max_workers = 2
            PDFLinkHandler._executor = ThreadPoolExecutor(max_workers=max_workers)
        
        self.executor = PDFLinkHandler._executor
        self.analyzer = PaperAnalyzer()
        self.user_plan_manager = UserPlanManager()
        self.license_validator = LicenseValidator()

    def _convert_cdn_to_s3_url(self, cdn_url: str) -> str:
        """
        将 CDN URL 转换为 S3 URL
        例如: https://cdn.alignspires.com/chat/documents/6ee9274d-39b9-464a-a99a-34c336ad1643-2507.11818v1.pdf
        转换为: https://s3.amazonaws.com/bucket-name/chat/documents/6ee9274d-39b9-464a-a99a-34c336ad1643-2507.11818v1.pdf
        """
        try:
            parsed_url = urlparse(cdn_url)
            
            # 检查是否为 CDN URL 或 Slack 文件 URL
            if 'cdn.alignspires.com' not in parsed_url.netloc and 'files.slack.com' not in parsed_url.netloc:
                self.logger.warning(f"URL {cdn_url} does not appear to be a CDN URL or Slack file URL")
                return cdn_url
            
            # 如果是 Slack 文件 URL，直接返回原始 URL
            if 'files.slack.com' in parsed_url.netloc:
                self.logger.info(f"Slack file URL detected, using original URL: {cdn_url}")
                return cdn_url
            
            # 提取路径部分（去掉开头的斜杠）
            path = parsed_url.path.lstrip('/')
            
            # 构建 S3 URL
            # 这里需要根据实际的 S3 bucket 配置来调整
            s3_bucket = os.getenv('S3_CHAT_BUCKET_NAME', '')
            s3_region = os.getenv('AWS_REGION', 'us-east-1')
            
            s3_url = f"https://{s3_bucket}.s3.{s3_region}.amazonaws.com/{path}"
            
            self.logger.info(f"Converted CDN URL {cdn_url} to S3 URL {s3_url}")
            return s3_url
            
        except Exception as e:
            self.logger.error(f"Failed to convert CDN URL {cdn_url} to S3 URL: {str(e)}")
            # 如果转换失败，返回原始 URL
            return cdn_url

    @classmethod
    def close_resources(cls):
        """关闭共享资源"""
        if cls._executor is not None:
            cls._executor.shutdown()
            cls._executor = None
        
        if cls._client is not None:
            cls._client.close()
            cls._client = None
        
    def is_valid_url(self, url):
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    async def is_pdf_url(self, url):
        if not self.is_valid_url(url):
            self.logger.info(f"URL {url} invalid")  
            return False
            
        try:
            # 检查URL路径
            is_pdf_extension = re.search(r'\.pdf$', url, re.IGNORECASE) is not None
            
            # 异步发送HTTP HEAD请求
            async with aiohttp.ClientSession() as session:
                async with session.head(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=5),
                    headers={'User-Agent': 'Mozilla/5.0'}
                ) as response:
                    content_type = response.headers.get('Content-Type', '').lower()
                    return is_pdf_extension or 'application/pdf' in content_type
            
        except Exception as e:
            self.logger.info(f"Error checking PDF URL: {e}")
            return False

    async def _download_pdf_with_retry(self, url: str, title: str) -> Optional[str]:
        """带重试机制的PDF下载"""
        MAX_RETRIES = 3  # 最大重试次数
        # 文件不存在，进行下载尝试
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._download_pdf(url, title)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    self.logger.error(f"下载失败（超过最大重试次数）: {url}")
                    return None
                self.logger.warning(f"下载重试中 ({attempt + 1}/{MAX_RETRIES}): {url}")
                await asyncio.sleep(0.1)  # 重试间隔

    async def _download_pdf(self, url: str, title: str) -> str:
        """异步下载PDF文件"""
        filename = title + ".pdf"
        save_path = os.path.join(PDF_DIR, filename)

        try:
            parsed_url = urlparse(url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": base_url,
                "Connection": "keep-alive",
            }
            
            # 如果是Slack文件URL，添加Bot Token认证并使用下载URL
            if ('files.slack.com' in parsed_url.netloc or 'slack-files.com' in parsed_url.netloc) and ('files-pri' in url or 'files-tmb' in url):
                # 优先使用传入的slack_token，如果没有则使用全局设置
                slack_bot_token = self.slack_token or settings.SLACK_BOT_TOKEN
                if slack_bot_token:
                    headers["Authorization"] = f"Bearer {slack_bot_token}"
                    # 确保使用下载URL格式
                    if '/download/' not in url:
                        # 将 files-pri URL 转换为下载URL
                        # 例如: https://files.slack.com/files-pri/T09L1TN3WD6-F09LG07P76U/article.pdf
                        # 转换为: https://files.slack.com/files-pri/T09L1TN3WD6-F09LG07P76U/download/article.pdf
                        url_parts = url.split('/')
                        if len(url_parts) >= 5:
                            # 在文件名前插入 'download'
                            url_parts.insert(-1, 'download')
                            url = '/'.join(url_parts)
                            self.logger.info(f"转换为Slack下载URL: {url}")
                    
                    # 移除其他可能干扰的头部
                    headers.pop("Referer", None)
                    headers["Accept"] = "*/*"
                    self.logger.info(f"使用Slack Bot Token认证: {slack_bot_token[:10]}...")
                else:
                    self.logger.warning("未找到Slack Bot Token，可能无法下载私有文件")

            # 创建连接器，忽略内容长度检查
            connector = aiohttp.TCPConnector(limit_per_host=10)
            timeout = aiohttp.ClientTimeout(total=300)  # 5分钟超时
            
            # Use async with to ensure the session is properly closed
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                try:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            # 检查响应内容类型
                            content_type = response.headers.get('Content-Type', '').lower()
                            self.logger.info(f"响应Content-Type: {content_type}")
                            
                            # 使用 iter_chunked 方法逐块读取，避免 ContentLengthError
                            content = bytearray()
                            async for chunk in response.content.iter_chunked(8192):  # 8KB chunks
                                content.extend(chunk)
                            
                            # 检查内容是否为HTML（表示认证失败）
                            content_str = content[:1000].decode('utf-8', errors='ignore').lower()
                            if '<html' in content_str or '<!doctype html' in content_str:
                                raise Exception("下载的是HTML页面而不是PDF文件，可能是认证失败或权限不足")
                            
                            # 验证PDF文件头
                            if not content.startswith(b'%PDF'):
                                raise Exception(f"下载的文件不是有效的PDF格式。文件开头: {content[:20]}")
                            
                            with open(save_path, "wb") as f:
                                f.write(content)
                            self.logger.info(f"成功下载PDF文件: {filename}, 大小: {len(content)} bytes")
                            return save_path
                        elif response.status == 401:
                            raise Exception("文件下载失败：需要认证。这是一个私有Slack文件，需要有效的Bot Token。")
                        elif response.status == 403:
                            raise Exception("文件下载失败：权限不足。Bot可能缺少files:read权限。")
                        elif response.status == 404:
                            raise Exception("文件下载失败：文件不存在或链接已过期。")
                        else:
                            raise Exception(f"HTTP状态码 {response.status}")
                except aiohttp.ClientPayloadError as e:
                    # 处理内容长度错误，尝试使用不同的方法
                    self.logger.warning(f"内容长度错误，尝试替代方法下载: {filename} - {str(e)}")
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            # 直接读取所有可用内容，忽略 Content-Length
                            content = await response.read()
                            if content:  # 确保有内容
                                # 检查内容是否为HTML（表示认证失败）
                                content_str = content[:1000].decode('utf-8', errors='ignore').lower()
                                if '<html' in content_str or '<!doctype html' in content_str:
                                    raise Exception("下载的是HTML页面而不是PDF文件，可能是认证失败或权限不足")
                                
                                # 验证PDF文件头
                                if not content.startswith(b'%PDF'):
                                    raise Exception(f"下载的文件不是有效的PDF格式。文件开头: {content[:20]}")
                                
                                with open(save_path, "wb") as f:
                                    f.write(content)
                                self.logger.info(f"使用替代方法成功下载PDF文件: {filename}, 大小: {len(content)} bytes")
                                return save_path
                            else:
                                raise Exception("下载的内容为空")
                        elif response.status == 401:
                            raise Exception("文件下载失败：需要认证。这是一个私有Slack文件，需要有效的Bot Token。")
                        elif response.status == 403:
                            raise Exception("文件下载失败：权限不足。Bot可能缺少files:read权限。")
                        elif response.status == 404:
                            raise Exception("文件下载失败：文件不存在或链接已过期。")
                        else:
                            raise Exception(f"HTTP状态码 {response.status}")
            
        except Exception as e:
            self.logger.error(f"下载失败 {filename}: {str(e)}")
            raise


    async def _convert_to_text(self, pdf_path: str) -> str:
        """异步执行PDF转文本"""
        loop = asyncio.get_running_loop()
        txt_filename = os.path.splitext(os.path.basename(pdf_path))[0] + ".txt"
        txt_path = os.path.join(TXT_DIR, txt_filename)

        try:
            txt_string = await loop.run_in_executor(
                self.executor, self._sync_pdf_to_text, pdf_path, txt_path
            )
            return txt_string
        except Exception as e:
            self.logger.error(f"文本转换失败 {pdf_path}: {str(e)}")
            raise

    def _sync_pdf_to_text(self, pdf_path: str, output_txt: str):
        """同步的PDF转文本处理"""
        try:
            if self._is_text_based_pdf(pdf_path):
                self.logger.info(f"直接提取文本: {os.path.basename(pdf_path)}")
                return self._extract_text(pdf_path, output_txt)
            else:
                self.logger.info(f"OCR处理: {os.path.basename(pdf_path)}")
                return self._ocr_process(pdf_path, output_txt)
            logger.debug(f"成功转换: {os.path.basename(pdf_path)}")
        except Exception as e:
            self.logger.error(f"文本转换失败 {pdf_path}: {str(e)}")
            raise

    # 保持原有的 _is_text_based_pdf, _extract_text, _ocr_process 方法不变

    def _is_text_based_pdf(self, pdf_path: str, threshold=50) -> bool:
        """判断是否为文本型PDF"""
        try:
            with open(pdf_path, "rb") as file:
                reader = PyPDF2.PdfReader(file)
                text = "".join(page.extract_text() or "" for page in reader.pages[:3])
                return len(text.strip()) > threshold
        except Exception:
            return False

    def _extract_text(self, pdf_path: str, output_txt: str):
        """直接提取文本"""
        with open(pdf_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        # with open(output_txt, "w", encoding="utf-8") as f:
        #     f.write(text)
        return text

    def _ocr_process(self, pdf_path: str, output_txt: str, dpi=300):
        """OCR处理扫描版PDF"""
        # 在容器环境中，poppler_path 可以为 None
        if POPPLER_PATH:
            images = convert_from_path(pdf_path, dpi=dpi, poppler_path=POPPLER_PATH)
        else:
            images = convert_from_path(pdf_path, dpi=dpi)  # Linux 环境下不需要指定路径
        
        full_text = []
        for i, img in enumerate(images):
            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            text = pytesseract.image_to_string(thresh, lang="eng")
            full_text.append(f"Page {i + 1}:\n{text}")
    
        # with open(output_txt, "w", encoding="utf-8") as f:
        #     f.write("\n\n".join(full_text))
        return "\n\n".join(full_text)
    
    async def process_url_download_extract(self, enforce_license_check: bool = False):
        """
        下载PDF并提取文本内容
        
        Args:
            enforce_license_check: 是否强制检查license，默认为False
        """
        if not await self.is_pdf_url(self.url):
            self.logger.warning(f'URL不是有效的PDF链接: {self.url}')
            raise ValueError(f"无效的PDF链接：{self.url} 不是有效的PDF文件")
        
        # 使用新的license验证器进行license检查
        is_valid, message, license_info = await self.license_validator.validate_url_license(
            self.url, enforce_license_check
        )
        
        if not is_valid and enforce_license_check:
            self.logger.warning(message)
            raise ValueError(message)
        
        if license_info:
            self.logger.info(message)
        
        # 将license信息存储为实例变量，供后续使用
        self.license_info = license_info
        
        self.logger.info(f'开始处理PDF URL: {self.url}')
        self.urlID = hashlib.md5(self.url.encode('utf-8')).hexdigest()
        
        try:
            pdf_saved_path = await self._download_pdf_with_retry(self.url, self.urlID)
            if not pdf_saved_path:
                self.logger.error(f"PDF下载失败: {self.url}")
                raise ValueError(f"PDF下载失败：无法从 {self.url} 下载PDF文件，请检查链接是否有效")
            
            try:
                txt_string = await self._convert_to_text(pdf_saved_path)
                if not txt_string or not txt_string.strip():
                    self.logger.error(f"PDF文本提取失败: {self.url} - 提取的文本为空")
                    raise ValueError(f"PDF文本提取失败：无法从PDF中提取有效文本内容，可能是扫描版PDF或格式不支持")
                
                self.logger.info(f'PDF成功转换为文本，文本长度: {len(txt_string)} 字符')
                return txt_string
                
            except Exception as e:
                self.logger.error(f"PDF文本转换错误: {self.url} - {str(e)}")
                raise ValueError(f"PDF文本转换失败：{str(e)}")
                
        except ValueError as ve:
            # 重新抛出ValueError，保持原有的错误信息
            raise ve
        except Exception as e:
            self.logger.error(f"PDF下载过程中发生错误: {self.url} - {str(e)}")
            raise ValueError(f"PDF下载失败：{str(e)}")

    async def process_url_llm(self, txt_string):
        """
        使用LLM分析PDF文本内容
        """
        try:
            if not txt_string or not txt_string.strip():
                self.logger.error(f"LLM分析失败: 输入文本为空")
                raise ValueError("LLM分析失败：PDF文本内容为空，无法进行分析")
            
            analysis = await self.analyzer.process_full_text(txt_string)
            
            if not analysis:
                self.logger.error(f"LLM分析失败: 分析结果为空")
                raise ValueError("LLM分析失败：分析器返回空结果，可能是文本内容不符合分析要求")
            
            return analysis
            
        except ValueError as ve:
            # 重新抛出ValueError，保持原有的错误信息
            raise ve
        except Exception as e:
            self.logger.error(f"LLM分析过程中发生未预期错误: {str(e)}")
            raise ValueError(f"LLM分析失败：{str(e)}")

    async def _process_authors_with_user_linking(self, raw_authors: List[Dict]) -> List[Dict]:
        """处理作者信息，如果有邮箱则尝试关联 user_id"""
        processed_authors = []
        
        for author in raw_authors:
            author_info = author.copy()
            
            # 检查作者是否有邮箱信息
            author_email = author_info.get("email", "").strip()
            if author_email:
                try:
                    # 从 users 表中查询对应的用户
                    user = await self.db.users.find_one({"email": author_email})
                    if user:
                        # 如果找到用户，添加 user_id 字段
                        author_info["user_id"] = str(user["_id"])
                        # 如果用户有头像URL，添加 user_avatar 字段
                        if user.get("avatar_url"):
                            author_info["user_avatar"] = user["avatar_url"]
                        self.logger.info(f"成功关联作者邮箱 {author_email} 到用户 {user['_id']}")
                    else:
                        self.logger.info(f"未找到邮箱 {author_email} 对应的用户")
                except Exception as e:
                    self.logger.error(f"查询作者邮箱 {author_email} 对应用户时出错: {str(e)}")
            
            processed_authors.append(author_info)
        
        return processed_authors

    async def _validate_and_process_analysis(self, analysis: Dict) -> Dict:
        """校验和处理分析结果"""
        try:
            self.logger.info("开始校验和处理分析结果")
            
            # 创建处理后的分析结果副本
            processed_analysis = analysis.copy()
            
            # 处理作者信息，尝试关联用户
            if "authors" in processed_analysis and isinstance(processed_analysis["authors"], list):
                self.logger.info(f"开始处理 {len(processed_analysis['authors'])} 个作者信息")
                processed_authors = await self._process_authors_with_user_linking(processed_analysis["authors"])
                processed_analysis["authors"] = processed_authors
                self.logger.info(f"作者信息处理完成，共处理 {len(processed_authors)} 个作者")
            else:
                self.logger.info("分析结果中未找到作者信息或格式不正确")
            
            # 可以在这里添加其他校验和处理逻辑
            # 例如：验证必要字段、格式化数据、添加默认值等
            
            self.logger.info("分析结果校验和处理完成")
            return processed_analysis
            
        except Exception as e:
            self.logger.error(f"校验和处理分析结果时出错: {str(e)}")
            # 如果处理失败，返回原始分析结果
            return analysis

    async def process_url(self, user_id: str, enforce_license_check: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
        """
        处理PDF URL，下载、转换为文本并进行LLM分析
        积分扣除时机：成功下载并转换为txt后，LLM分析前
        """
        txt_string = ""
        
        # 第一步：下载PDF并转换为文本
        try:
            txt_string = await self.process_url_download_extract(enforce_license_check=enforce_license_check)
            if not txt_string:
                self.logger.error(f"PDF下载或转换失败: {self.url} - 无法提取文本内容，可能是PDF格式损坏或不支持的格式")
                return None, None
        except Exception as e:
            self.logger.error(f"PDF下载或转换过程中发生错误: {self.url} - {str(e)}")
            return None, None
        
        # 第二步：成功获取文本后，进行积分检查和扣除
        if user_id:
            self.logger.info(f"PDF文本提取成功，开始检查用户 {user_id} 的积分状态")
            
            # 获取PDF处理的积分消耗量
            pdf_credit_cost = get_feature_credit_cost("pdf_processing")
            
            # 检查用户是否有足够积分
            try:
                can_process = await self.user_plan_manager.can_user_start_chat(user_id, pdf_credit_cost,consume_trail_type='pdf_process')
                if not can_process:
                    self.logger.warning(f"User {user_id} has insufficient credits, requires {pdf_credit_cost} credits but balance is insufficient")
                    raise ValueError(f"LLM analysis failed: You need {pdf_credit_cost} credits to process PDF, but your current balance is insufficient. Please upgrade your subscription or purchase credit packages to continue using PDF analysis features.")
            except Exception as e:
                self.logger.error(f"Error occurred while checking user credit status: {str(e)}")
                raise ValueError(f"Credit check failed: {str(e)}")
        
        # 第三步：进行LLM分析
        try:
            self.logger.info(f"开始进行LLM分析: {self.url}")
            analysis = await self.process_url_llm(txt_string)
            self.logger.info(f"LLM分析完成: {self.url}")
            
            # 第四步：校验和处理分析结果
            processed_analysis = await self._validate_and_process_analysis(analysis)
            self.logger.info(f"分析结果校验和处理完成: {self.url}")
            
            # 扣除积分
            try:
                pdf_credit_cost = get_feature_credit_cost("pdf_processing")
                consume_result = await self.user_plan_manager.consume_credits(user_id, pdf_credit_cost, consume_trail_type='pdf_process')
                if not consume_result.success:
                    self.logger.warning(f"用户 {user_id} 积分扣除失败: {consume_result.message}")
                    raise ValueError(f"积分扣除失败：{consume_result.message}")
                
                self.logger.info(f"用户 {user_id} 成功扣除{pdf_credit_cost}个积分，剩余积分: {consume_result.total_credits_remaining}")
            except Exception as e:
                self.logger.error(f"积分扣除过程中发生错误: {str(e)}")
                raise ValueError(f"积分扣除失败：{str(e)}")

            return processed_analysis, txt_string
        except Exception as e:
            self.logger.error(f"LLM分析过程中发生错误: {self.url} - {str(e)}")
            # 注意：LLM分析失败时不返还积分，因为PDF处理资源已经消耗
            return None, None

    async def _store_to_mongodb(self, request_id: str, user_id: str, text_content: str, analysis: dict):
        """异步存储文本内容和分析结果到MongoDB，并保存任务状态, 内部使用"""
        try:
            # 原有的存储逻辑
            document = {
                "user_id": user_id,
                "request_id": request_id,
                "url": self.url,
                "url_id": self.urlID,
                "text_content": text_content,
                "analysis": analysis,
                "created_at": datetime.now(timezone.utc),
            }
            
            # 添加license信息（如果存在）
            if hasattr(self, 'license_info') :
                document["license_info"] = self.license_info
                self.logger.info(f"添加license信息到存储文档: {self.license_info}")
            
            await self.db.paper_service.insert_one(document)
            self.logger.info(f"Successfully stored analysis for URL: {self.url}")
            
        except Exception as e:
            self.logger.error(f"Failed to store analysis to MongoDB: {e}")

    async def _store_task_result(self, user_id: str, request_id: str, analysis: Optional[dict] = None, status: str = "completed", error: Optional[str] = None):
        """存储任务处理结果到 pdf_tasks 集合"""
        try:
            task_document = {
                "request_id": request_id,
                "user_id": user_id,
                "url": self.url,
                "status": status,
                "created_at": datetime.now(timezone.utc),
                "completed_at": datetime.now(timezone.utc)
            }
            
            if status == "completed" and analysis:
                # 构建响应数据
                response_data = {
                    'url': self.url,
                    'url_id': getattr(self, 'urlID', None),
                    'title': analysis.get('title', ''),
                    'authors': analysis.get('authors', ''),
                    'conerstones': {
                        'topic': analysis.get('topic', ''),
                        'methodology': analysis.get('methodology_description', ''),
                        'contribution': analysis.get('main_contribution_description', ''),
                    },
                    'future_works': [analysis.get('pro_view_claim_of_primary_future_question', ''),
                                     analysis.get('pro_view_claim_of_secondary_future_question', '')]
                }
                task_document["result"] = response_data
                self.logger.info(f"PDF处理成功: {self.url}")
            elif status == "failed":
                task_document["error"] = error or "Failed to process PDF"
                self.logger.warning(f"PDF处理失败: {self.url}")
            
            await self.db.pdf_tasks.insert_one(task_document)
            
        except Exception as e:
            self.logger.error(f"Failed to store task result: {e}")
    
    async def process_url_with_task_tracking(self, user_id: str, request_id: str, enforce_license_check: bool = False):
        """带任务跟踪的 URL 处理方法"""
        try:
            # 处理PDF URL（包含积分检查）
            self.logger.info(f"开始处理PDF URL: {self.url}, user_id: {user_id}")

            result, pdf_txt = await self.process_url(user_id, enforce_license_check=enforce_license_check)
            
            if result and pdf_txt:
                # 存储分析结果和任务状态
                await self._store_to_mongodb(request_id, user_id, pdf_txt, result)
                await self._store_task_result(user_id, request_id, result, "completed")
            else:
                # 保存失败状态
                await self._store_task_result(user_id, request_id, None, "failed", "Failed to process PDF")
                
        except ValueError as ve:
            # 处理积分不足的错误
            await self._store_task_result(user_id, request_id, None, "failed", str(ve))
            self.logger.warning(f"PDF处理被拒绝（积分不足）: {str(ve)}")
            raise ve
        except Exception as e:
            # 保存异常状态
            await self._store_task_result(user_id, request_id, None, "failed", str(e))
            self.logger.error(f"PDF异步处理错误: {str(e)}")

    async def get_pdf_request_result(self, request_id: str, user_id: str) -> dict:
        """查询PDF处理任务的状态和结果"""
        try:
            # 从 MongoDB 查询任务状态
            task_record = await self.db.pdf_tasks.find_one({
                "request_id": request_id,
                "user_id": user_id
            })
            
            if not task_record:
                # 没有找到记录，表示正在处理中
                return {
                    "success": True,
                    "status": "processing",
                    "request_id": request_id,
                    "url": None,
                    "message": "PDF processing in progress"
                }
            
            if task_record["status"] == "completed":
                return {
                    "success": True,
                    "status": "completed",
                    "data": task_record["result"],
                    "url": task_record["url"],
                    "request_id": request_id,
                    "message": "PDF processing completed"
                }
            elif task_record["status"] == "failed":
                return {
                    "success": False,
                    "status": "failed",
                    "request_id": request_id,
                    "url": None,
                    "message": task_record.get("error", "Processing failed")
                }
            
            status = task_record["status"]
            return {
                    "success": False,
                    "status": status,
                    "request_id": request_id,
                    "url": None,
                    "message": f"Processing failed. status {status}"
                }
            
        except Exception as e:
            self.logger.error(f"查询PDF结果错误: {str(e)}")
            return {
                    "success": False,
                    "status": "failed",
                    "request_id": request_id,
                    "url": None,
                    "message": f"Processing failed. {e}"
                }


    async def create_pdf_processing_task(self, message_id: str, user_id: str, media_url: str) -> str:
        """
        在MongoDB中创建PDF处理任务记录
        """
        try:
            task = PDFProcessingTask(
                message_id=message_id,
                user_id=user_id,
                original_pdf_url=media_url,
                status=PDFProcessingStatus.PROCESSING,
                txt_content=None,
                file_size=None,
                page_count=None,
                error_message=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            result = await self.db["pdf_processing_tasks"].insert_one(task.dict())
            self.logger.info(f"Created PDF processing task for message {message_id}")
            return str(result.inserted_id)
        except Exception as e:
            self.logger.error(f"Failed to create PDF processing task: {str(e)}")
            raise

    async def update_pdf_processing_task_status(
        self,
        message_id: str, 
        status: PDFProcessingStatus, 
        txt_content: Optional[str] = None,
        file_size: Optional[int] = None,
        page_count: Optional[int] = None,
        error_message: Optional[str] = None
    ):
        """
        更新PDF处理任务状态
        """
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.now(timezone.utc)
            }
            
            if txt_content is not None:
                update_data["txt_content"] = txt_content
            if file_size is not None:
                update_data["file_size"] = file_size
            if page_count is not None:
                update_data["page_count"] = page_count
            if error_message is not None:
                update_data["error_message"] = error_message
                
            await self.db["pdf_processing_tasks"].update_one(
                {"message_id": message_id},
                {"$set": update_data}
            )
            self.logger.info(f"Updated PDF processing task status for message {message_id} to {status}")
        except Exception as e:
            self.logger.error(f"Failed to update PDF processing task status: {str(e)}")
            raise

    def _get_pdf_file_info(self, pdf_path: str) -> dict:
        """
        获取PDF文件信息（大小和页数）
        """
        try:
            file_size = os.path.getsize(pdf_path)
            
            with open(pdf_path, "rb") as file:
                reader = PyPDF2.PdfReader(file)
                page_count = len(reader.pages)
            
            return {
                "file_size": file_size,
                "page_count": page_count
            }
        except Exception as e:
            self.logger.error(f"Failed to get PDF file info: {str(e)}")
            return {"file_size": None, "page_count": None}

    async def process_pdf_message_async(self, message_id: str, user_id: str, media_url: str):
        """
        异步处理PDF消息：下载PDF，转换为文本，保存到MongoDB
        复用现有的 process_url_download_extract 方法
        """
        try:
            self.logger.info(f"Starting PDF processing for message {message_id}")
            
            # 创建处理任务记录
            await self.create_pdf_processing_task(message_id, user_id, media_url)
            
            # 设置URL并调用现有的处理方法
            self.url = media_url
            txt_content = await self.process_url_download_extract()
            
            if txt_content and txt_content.strip():
                
                # 处理成功，保存文本内容到MongoDB
                await self.update_pdf_processing_task_status(
                    message_id=message_id,
                    status=PDFProcessingStatus.COMPLETED,
                    txt_content=txt_content
                )
                self.logger.info(f"PDF processing completed for message {message_id}")
            else:
                # 处理失败
                await self.update_pdf_processing_task_status(
                    message_id=message_id,
                    status=PDFProcessingStatus.FAILED,
                    error_message="Failed to extract text from PDF"
                )
                self.logger.error(f"PDF processing failed for message {message_id}: No text content extracted")
                
        except Exception as e:
            self.logger.error(f"PDF processing failed for message {message_id}: {str(e)}")
            try:
                await self.update_pdf_processing_task_status(
                    message_id=message_id,
                    status=PDFProcessingStatus.FAILED,
                    error_message=str(e)
                )
            except Exception as update_error:
                self.logger.error(f"Failed to update task status after error: {str(update_error)}")

    async def get_pdf_processing_task_status(self, message_id: str, user_id: str) -> dict:
        """
        查询PDF处理任务状态
        """
        try:
            task = await self.db["pdf_processing_tasks"].find_one({"message_id": message_id})
            
            if not task:
                return {
                    "error": "PDF processing task not found",
                    "status_code": 404
                }
            
            response_data = {
                "message_id": task["message_id"],
                "status": task["status"],
                "created_at": task["created_at"],
                "updated_at": task["updated_at"]
            }
            
            # 如果处理完成，返回文本内容
            if task["status"] == PDFProcessingStatus.COMPLETED:
                response_data.update({
                    "txt_content": task.get("txt_content"),
                    "file_size": task.get("file_size"),
                    "page_count": task.get("page_count")
                })
            elif task["status"] == PDFProcessingStatus.FAILED:
                response_data["error_message"] = task.get("error_message")
            
            return {
                "data": response_data,
                "status_code": 200
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get PDF processing status: {str(e)}")
            return {
                "error": f"Failed to get processing status: {str(e)}",
                "status_code": 500
            }
