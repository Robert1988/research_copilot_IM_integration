import os
import json
import aiohttp  # 添加 aiohttp 导入
from pathlib import Path
from typing import Optional
from datetime import datetime
import logging

class UserReplyHandler:
    """处理用户回复生成的类"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # 修改为使用 DeepSeek API 密钥
        self.deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        if not self.deepseek_api_key:
            self.logger.warning("DEEPSEEK_API_KEY 环境变量未设置")
    
    async def generate_reply(self, paper_summary: str, new_ideas: str,
     experiment_code_path: str , execution_log: str ) -> Optional[str]:
        """根据论文摘要和新想法生成简短回复
        
        Args:
            paper_summary_path: 论文摘要文件路径
            new_ideas_path: 新想法文件路径
            experiment_code_path: 实验代码文件路径（可选）
            execution_log_path: 执行日志文件路径（可选）
            
        Returns:
            Optional[str]: 生成的回复，如果生成失败则返回 None
        """
        reply = None
        if experiment_code_path and os.path.exists(experiment_code_path):
            try:
                with open(experiment_code_path, 'r', encoding='utf-8') as f:
                    experiment_code = f.read()
                
                # 调用LLM生成回复
                reply = await self._generate_reply_with_llm(paper_summary, new_ideas, experiment_code, execution_log)
        
            except Exception as e:
                self.logger.warning(f"读取实验代码文件失败: {str(e)}")
            

        if reply:
            self.logger.info("成功生成用户回复")
            return reply
        else:
            self.logger.error("生成用户回复失败")
            return None
    
    async def _generate_reply_with_llm(self, paper_summary: str, new_ideas: str, experiment_code: str , execution_log: str ) -> Optional[str]:
        """
        使用 DeepSeek API 生成回复
        
        Args:
            paper_summary: 论文摘要内容
            new_ideas: 新想法内容
            experiment_code: 最新生成的实验代码（可选）
            execution_log: 代码执行日志（可选）
            
        Returns:
            Optional[str]: 生成的回复，如果生成失败则返回 None
        """
        
        if not self.deepseek_api_key:
            self.logger.error("DEEPSEEK_API_KEY 未设置，无法调用 LLM API")
            return None
        
        prompt = """
        You are a helpful research assistant. Please generate a brief, concise response to the new research idea 
        based on the paper summary provided. Your response should be professional, insightful, and no more than 
        3-4 sentences. Focus on how the new idea relates to or extends the original research.

        Paper summary:
        {paper_summary}

        New research idea:
        {new_ideas}
        """
        
        # 如果提供了实验代码和执行日志，则添加到提示词中
        if experiment_code and execution_log:
            prompt += """

        The idea has been implemented in the following experiment code:
        ```python
        {experiment_code}
        ```

        The experiment execution results:
        ```
        {execution_log}
        ```
        """
        
        prompt += """

        Please provide a very brief, converstional response with simple terms. 
        If you can, please include the following points:
        1) Summarize what the experiment code has achieved.
        2）Insights from the execution results.
        3）Please encourage user to further explore the idea, or modify of the code, or take other further action.
        """
        
        # 当代码或日志过长时，进行中间截断（保留头尾）
        def truncate_text_middle(text: str, max_chars: int, head_ratio: float = 0.6) -> str:
            if not text:
                return ""
            if len(text) <= max_chars:
                return text
            head_len = int(max_chars * head_ratio)
            tail_len = max_chars - head_len
            return (
                text[:head_len]
                + "\n...\n[truncated]\n...\n"
                + text[-tail_len:]
            )

        MAX_CODE_SNIPPET_CHARS = 4000
        MAX_LOG_SNIPPET_CHARS = 3000

        truncated_experiment_code = truncate_text_middle(experiment_code or "", MAX_CODE_SNIPPET_CHARS)
        truncated_execution_log = truncate_text_middle(execution_log or "", MAX_LOG_SNIPPET_CHARS)

        prompt = prompt.format(
            paper_summary=paper_summary, 
            new_ideas=new_ideas,
            experiment_code=truncated_experiment_code,
            execution_log=truncated_execution_log
        )
        
        try:
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "deepseek-coder",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        content = result['choices'][0]['message']['content']
                        
                        return content.strip()
                    else:
                        error_text = await response.text()
                        self.logger.error(f"DeepSeek API 调用失败: {response.status}, {error_text}")
                        return None
                    
        except Exception as e:
            self.logger.error(f"调用 DeepSeek API 失败: {str(e)}")
            return None