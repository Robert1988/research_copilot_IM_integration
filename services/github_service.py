import re
import aiohttp
import base64
import logging
import asyncio
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, unquote
from config import settings

logger = logging.getLogger(__name__)

class GitHubService:
    def __init__(self):
        # GitHub URL patterns with improved regex to exclude special characters
        self.github_url_patterns = [
            # Standard GitHub repository URLs
            r'https://github\.com/([^/\s>]+)/([^/\s>]+)(?:/tree/([^/\s>]+)(?:/(.+))?)?',
            # Raw GitHub content URLs
            r'https://raw\.githubusercontent\.com/([^/\s>]+)/([^/\s>]+)/([^/\s>]+)/(.+)',
            # GitHub Gist URLs
            r'https://gist\.github\.com/([^/\s>]+)/([a-f0-9]+)'
        ]
        
        # Code file extensions to process
        self.code_extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.hpp',
            '.cs', '.php', '.rb', '.go', '.rs', '.swift', '.kt', '.scala', '.sh',
            '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd', '.html', '.htm', '.css',
            '.scss', '.sass', '.less', '.xml', '.json', '.yaml', '.yml', '.toml',
            '.ini', '.cfg', '.conf', '.md', '.txt', '.sql', '.r', '.R', '.m',
            '.pl', '.lua', '.dart', '.vue', '.svelte', '.elm', '.clj', '.cljs',
            '.ex', '.exs', '.erl', '.hrl', '.fs', '.fsx', '.ml', '.mli', '.hs',
            '.lhs', '.jl', '.nim', '.cr', '.zig', '.v', '.vv'
        }

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for GitHub API requests with authentication if available"""
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'SlackBot-GitHub-Integration'
        }
        
        if settings.GITHUB_TOKEN:
            headers['Authorization'] = f'token {settings.GITHUB_TOKEN}'
            
        return headers

    async def _make_request_with_retry(self, session: aiohttp.ClientSession, url: str, max_retries: int = 3) -> Optional[Dict]:
        """Make HTTP request with exponential backoff retry for various errors, return parsed JSON data"""
        
        for attempt in range(max_retries + 1):
            try:
                logger.debug(f"Attempt {attempt + 1} for request: {url}")
                async with session.get(url, headers=self._get_headers()) as response:
                    logger.debug(f"Received response, status code: {response.status}")
                    
                    if response.status == 200:
                        try:
                            data = await response.json()
                            return data
                        except (aiohttp.ClientConnectionError, ConnectionResetError, aiohttp.ServerDisconnectedError) as e:
                            logger.warning(f"Connection error while reading response content (attempt {attempt + 1}/{max_retries + 1}): {e}")
                            if attempt < max_retries:
                                wait_time = min(2 ** attempt, 30)
                                logger.warning(f"Connection closed while reading response, retrying in {wait_time} seconds")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                logger.error(f"Failed to read response content, maximum retries reached")
                                return None
                    elif response.status == 403:
                        # Check rate limit headers
                        remaining = response.headers.get('X-RateLimit-Remaining', '0')
                        reset_time = response.headers.get('X-RateLimit-Reset', '0')
                        
                        logger.warning(f"Received 403 response, remaining requests: {remaining}, reset time: {reset_time}")
                        
                        if remaining == '0':
                            logger.warning(f"Rate limit exceeded. Reset at: {reset_time}")
                            if attempt < max_retries:
                                wait_time = min(2 ** attempt, 60)  # Exponential backoff, max 60s
                                logger.info(f"Retrying in {wait_time} seconds (attempt {attempt + 1}/{max_retries + 1})")
                                await asyncio.sleep(wait_time)
                                continue
                        else:
                            # Different type of 403 error (permissions, private repo, etc.)
                            logger.error(f"Access forbidden (403) for {url}. Remaining rate limit: {remaining}")
                            return None
                    elif response.status == 404:
                        logger.warning(f"Resource not found (404): {url}")
                        return None
                    elif response.status >= 500:
                        # Server errors - retry
                        logger.warning(f"Server error {response.status}: {url}")
                        if attempt < max_retries:
                            wait_time = min(2 ** attempt, 30)
                            logger.warning(f"Server error {response.status}, retrying in {wait_time} seconds")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Server error {response.status} after {max_retries + 1} attempts: {url}")
                            return None
                    else:
                        logger.error(f"HTTP {response.status} error for {url}")
                        return None
                        
            except asyncio.TimeoutError as e:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{max_retries + 1}): {url}, error: {e}")
                if attempt < max_retries:
                    wait_time = min(2 ** attempt, 30)
                    logger.warning(f"Request timeout, retrying in {wait_time} seconds (attempt {attempt + 1}/{max_retries + 1})")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Request timeout after {max_retries + 1} attempts: {url}")
                    return None
            except (aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError, ConnectionResetError) as e:
                logger.warning(f"Connection error (attempt {attempt + 1}/{max_retries + 1}): {url}, error type: {type(e).__name__}, error details: {e}")
                if attempt < max_retries:
                    wait_time = min(2 ** attempt, 30)
                    logger.warning(f"Connection error: {e}, retrying in {wait_time} seconds (attempt {attempt + 1}/{max_retries + 1})")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Connection error after {max_retries + 1} attempts: {e}")
                    return None
            except Exception as e:
                logger.warning(f"Unknown error (attempt {attempt + 1}/{max_retries + 1}): {url}, error type: {type(e).__name__}, error details: {e}")
                if attempt < max_retries:
                    wait_time = min(2 ** attempt, 30)
                    logger.warning(f"Request failed: {e}, retrying in {wait_time} seconds (attempt {attempt + 1}/{max_retries + 1})")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Request failed after {max_retries + 1} attempts: {e}")
                    return None
        
        logger.error(f"All retry attempts failed: {url}")
        return None

    def extract_github_urls(self, text: str) -> List[Dict[str, str]]:
        """Extract GitHub URLs from text and return structured information"""
        urls = []
        
        for pattern in self.github_url_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                url_info = self._parse_github_url(match.group(0), match.groups())
                if url_info:
                    urls.append(url_info)
        
        return urls

    def _determine_url_type(self, url: str) -> str:
        """Determine the type of GitHub URL"""
        if 'raw.githubusercontent.com' in url:
            return 'raw'
        elif 'gist.github.com' in url:
            return 'gist'
        else:
            return 'repository'

    async def get_repository_structure(self, owner: str, repo: str, branch: str = 'main') -> List[Dict]:
        """Get repository file structure from GitHub API"""
        logger.info(f"Starting to get repository structure: {owner}/{repo}, branch: {branch}")
        
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
            logger.debug(f"Built API URL: {url}")
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                logger.debug(f"Created aiohttp session, timeout setting: 30 seconds")
                
                data = await self._make_request_with_retry(session, url)
                if data:
                    tree = data.get('tree', [])
                    logger.info(f"Successfully parsed repository structure, contains {len(tree)} files/directories")
                    return tree
                else:
                    logger.warning(f"Request failed, trying master branch")
                    if branch == 'main':
                        logger.info(f"Trying 'master' branch for {owner}/{repo}")
                        return await self.get_repository_structure(owner, repo, 'master')
                    logger.error(f"Master branch also failed")
                    return []
                    
        except Exception as e:
            logger.error(f"Exception occurred while getting repository structure: {owner}/{repo}, error type: {type(e).__name__}, error details: {e}")
            import traceback
            logger.error(f"Full error stack trace: {traceback.format_exc()}")
            return []

    async def get_file_content(self, owner: str, repo: str, path: str, branch: str = 'main') -> Optional[str]:
        """Get file content from GitHub API with improved error handling"""
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                data = await self._make_request_with_retry(session, url)
                if data:
                    # Check if file is too large
                    size = data.get('size', 0)
                    if size > 1024 * 1024:  # 1MB limit
                        logger.warning(f"File {path} is too large ({size} bytes), skipping")
                        return None
                    
                    # Decode base64 content
                    content = data.get('content', '')
                    if content:
                        try:
                            decoded_content = base64.b64decode(content).decode('utf-8')
                            return decoded_content
                        except UnicodeDecodeError:
                            logger.warning(f"Cannot decode file {path} as UTF-8, skipping")
                            return None
                    
                return None
                
        except Exception as e:
            logger.error(f"Error getting file content for {path}: {e}")
            return None

    async def read_repository_code(self, owner: str, repo: str, branch: str = 'main') -> Dict[str, str]:
        """Read all code files from a GitHub repository with improved error handling"""
        try:
            # Get repository structure
            tree = await self.get_repository_structure(owner, repo, branch)
            if not tree:
                logger.error(f"Could not get repository structure for {owner}/{repo}")
                return {}
            
            # Filter code files
            code_files = []
            for item in tree:
                if item['type'] == 'blob':  # It's a file
                    file_path = item['path']
                    file_ext = '.' + file_path.split('.')[-1] if '.' in file_path else ''
                    if file_ext.lower() in self.code_extensions:
                        code_files.append(file_path)
            
            logger.info(f"Found {len(code_files)} code files in {owner}/{repo}")
            
            # Read files concurrently with semaphore to limit concurrent requests
            semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent requests
            file_contents = {}
            
            async def read_file(file_path: str):
                async with semaphore:
                    content = await self.get_file_content(owner, repo, file_path, branch)
                    if content:
                        file_contents[file_path] = content
                    else:
                        logger.warning(f"Could not read file: {file_path}")
            
            # Execute all file reads concurrently
            tasks = [read_file(file_path) for file_path in code_files]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            logger.info(f"Successfully read {len(file_contents)} files from {owner}/{repo}")
            return file_contents
            
        except Exception as e:
            logger.error(f"Error reading repository {owner}/{repo}: {e}")
            return {}

    def _parse_github_url(self, url: str, groups: Tuple) -> Optional[Dict[str, str]]:
        """Parse GitHub URL and extract information"""
        url_type = self._determine_url_type(url)
        
        if url_type == 'gist':
            return {
                'url': url,
                'type': 'gist',
                'owner': groups[0],
                'gist_id': groups[1],
                'repo_name': f"gist-{groups[1]}",
                'branch': 'main',
                'path': ''
            }
        elif url_type == 'raw':
            return {
                'url': url,
                'type': 'raw',
                'owner': groups[0],
                'repo_name': groups[1],
                'branch': groups[2],
                'path': groups[3] if len(groups) > 3 else ''
            }
        else:  # repository
            return {
                'url': url,
                'type': 'repository',
                'owner': groups[0],
                'repo_name': groups[1],
                'branch': groups[2] if groups[2] else 'main',
                'path': groups[3] if len(groups) > 3 and groups[3] else ''
            }

    async def get_gist_content(self, gist_id: str) -> Dict[str, str]:
        """Get content from a GitHub Gist with improved error handling"""
        try:
            url = f"https://api.github.com/gists/{gist_id}"
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                data = await self._make_request_with_retry(session, url)
                if data:
                    files = data.get('files', {})
                    
                    file_contents = {}
                    for filename, file_data in files.items():
                        content = file_data.get('content', '')
                        if content:
                            file_contents[filename] = content
                    
                    return file_contents
                else:
                    logger.error(f"Could not fetch gist {gist_id}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Error getting gist {gist_id}: {e}")
            return {}

    def convert_to_markdown(self, file_contents: Dict[str, str], repo_info: Dict[str, str]) -> str:
        """Convert repository code to markdown format"""
        try:
            markdown_content = []
            
            # Add header
            repo_name = f"{repo_info.get('owner', 'unknown')}/{repo_info.get('repo', 'unknown')}"
            markdown_content.append(f"# Repository: {repo_name}")
            markdown_content.append(f"*URL*: {repo_info.get('url', 'N/A')}")
            markdown_content.append(f"*Branch*: {repo_info.get('branch', 'main')}")
            markdown_content.append(f"*Files*: {len(file_contents)}")
            markdown_content.append("")
            
            # Add table of contents
            markdown_content.append("## Table of Contents")
            for file_path in sorted(file_contents.keys()):
                safe_path = file_path.replace('/', '-').replace('.', '-')
                markdown_content.append(f"- [{file_path}](#{safe_path})")
            markdown_content.append("")
            
            # Add file contents
            for file_path in sorted(file_contents.keys()):
                content = file_contents[file_path]
                file_ext = file_path.split('.')[-1] if '.' in file_path else 'text'
                
                markdown_content.append(f"## {file_path}")
                markdown_content.append("")
                markdown_content.append(f"```{file_ext}")
                markdown_content.append(content)
                markdown_content.append("```")
                markdown_content.append("")
            
            return "\n".join(markdown_content)
            
        except Exception as e:
            logger.error(f"Error converting to markdown: {e}")
            return ""

# Create global instance
github_service = GitHubService()