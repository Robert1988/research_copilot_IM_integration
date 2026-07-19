import os
import requests
import json
from pathlib import Path
from typing import Optional
# 使用标准 logging 模块
import logging

class CodeFixHandler:
    """处理代码修正的类"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
        if not self.openrouter_api_key:
            self.logger.warning("OPENROUTER_API_KEY 环境变量未设置")
    
    async def fix_experiment_code(
        self, 
        experiment_file_path: str, 
        error_logs: str
    ) -> bool:
        """
        修正实验代码并保存到文件
        
        Args:
            experiment_file_path: experiment.py 文件路径
            error_logs: Lambda 执行错误日志
            
        Returns:
            bool: 是否修复成功
        """
        
        # 读取当前的 experiment.py 代码
        try:
            with open(experiment_file_path, 'r', encoding='utf-8') as f:
                current_code = f.read()
        except Exception as e:
            self.logger.error(f"读取 experiment.py 文件失败: {str(e)}")
            return False
        
        # 使用 LLM 修正代码
        try:
            fixed_code = await self._fix_code_with_llm(current_code, error_logs)
            if not fixed_code:
                self.logger.info("LLM 修正失败")
                return False
                
        except Exception as e:
            self.logger.error(f"LLM 修正出错: {str(e)}")
            return False
        
        # 保存修正后的代码
        try:
            with open(experiment_file_path, 'w', encoding='utf-8') as f:
                f.write(fixed_code)
            self.logger.info("代码修正完成，已保存到文件")
            return True
        except Exception as e:
            self.logger.error(f"保存修正后的代码失败: {str(e)}")
            return False
    
    def _has_error(self, logs: str) -> bool:
        """
        检查日志中是否包含错误信息
        
        Args:
            logs: 执行日志
            
        Returns:
            bool: 是否包含错误
        """
        error_indicators = [
            "Error", "ERROR", "Exception", "Traceback", 
            "RuntimeError", "ValueError", "TypeError", "IndexError",
            "KeyError", "AttributeError", "ImportError", "ModuleNotFoundError",
            "Lambda Function Error", "FunctionError"
        ]
        
        logs_lower = logs.lower()
        for indicator in error_indicators:
            if indicator.lower() in logs_lower:
                return True
        
        return False
    
    async def _fix_code_with_llm(self, current_code: str, error_logs: str) -> Optional[str]:
        """
        使用 OpenRouter API 修正代码
        
        Args:
            current_code: 当前的代码
            error_logs: 错误日志
            
        Returns:
            Optional[str]: 修正后的代码，如果修正失败则返回 None
        """
        
        if not self.openrouter_api_key:
            self.logger.error("OPENROUTER_API_KEY 未设置，无法调用 LLM API")
            return None
        
        prompt = """
        You are a professional Python code debugging expert. Please fix the Python code based on the following error logs.
        The code snippet is named app/experiment.py. Please follow the following steps:
        Step 1: fully understand the structure of the code snippet.
        Step 2: identify the input and output of the code snippet. 
        Step 3: identify the error location based on the error logs.
        Step 4: understand context of identified issue.
        Step 5: fix the error.
        Hint:
        1. Code sinppet would run on AWS Lambda. It is a read-only file system. Don't make file nor save file.
        2. No GPU is available. All computation shall base on CPU.
        3. Do not save any file or visualize any graph (no need to plot any graph image).
        4. Your response should be a complete Python script only.
        5. Include proper error handling and logging where appropriate. 
        6. Ensure the program exits with sys.exit(1) when encountering any critical errors that require termination, particularly during the model training process.
        7. The code you generate needs to run in serverless environments (such as AWS Lambda) and Docker containers. Please avoid generating code that requires GUI, pre-trained model downloads, or other network-dependent operations.


        Current code:
        {current_code}

        Error logs:

        {error_logs}

        Please fix the Python code based on the error logs. 
        Only return the complete fixed code without any additional explanations.
        """
        prompt = prompt.format(current_code = current_code, error_logs=error_logs)

        # self.logger.info(f"LLM修复代码调用提示词: {prompt}")

        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "Content-Type": "application/json"
                },
                data=json.dumps({
                    "model": "anthropic/claude-sonnet-4",
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.1,
                    "reasoning": {
                        "effort": "high",
                        "exclude": True  # Use reasoning but don't include it in the response
                    }
                })
            )
            
            if response.status_code == 200:
                response_data = response.json()
                if 'choices' in response_data and len(response_data['choices']) > 0:
                    content = response_data['choices'][0]['message']['content']
                    
                    # 保存大模型返回的原始内容到本地文件
                    try:
                        import os
                        from datetime import datetime
                        
                        # 创建logs目录（如果不存在）
                        logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
                        os.makedirs(logs_dir, exist_ok=True)
                        
                        # 生成带时间戳的文件名
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        content_file = os.path.join(logs_dir, f'llm_response_{timestamp}.txt')
                        
                        # 保存content到文件
                        with open(content_file, 'w', encoding='utf-8') as f:
                            f.write(f"LLM Response Content (Generated at {datetime.now()}):\n")
                            f.write("=" * 50 + "\n")
                            f.write(content)
                            f.write("\n" + "=" * 50 + "\n")
                        
                        self.logger.info(f"大模型返回内容已保存到: {content_file}")
                        
                    except Exception as e:
                        self.logger.error(f"保存大模型返回内容失败: {str(e)}")
                    
                    # 提取代码块
                    fixed_code = self._extract_code_from_response(content)
                    if fixed_code:
                        self.logger.info("LLM 成功生成修正后的代码")
                        return fixed_code
                    else:
                        self.logger.info("无法从 LLM 响应中提取代码")
                        return None
                else:
                    self.logger.error("LLM 响应格式错误")
                    return None
            else:
                self.logger.error(f"LLM API 调用失败，状态码: {response.status_code}, 响应: {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"调用 LLM API 失败: {str(e)}")
            return None

    def _extract_code_from_response(self, response: str) -> Optional[str]:
        """
        从 LLM 响应中提取代码
        
        Args:
            response: LLM 的响应
            
        Returns:
            Optional[str]: 提取的代码，如果提取失败则返回 None
        """
        
        import re

        code_pattern = r'```(?:python)?\s*\n(.*?)\n```'
        matches = re.findall(code_pattern, response, re.DOTALL)
        
        if matches:
            # 返回最后一个代码块（通常是完整的修正代码）
            code_block = matches[-1].strip()
            
            # 判断是否是完整的代码块
            if self._is_complete_code_block(code_block):
                return code_block
            else:
                self.logger.info("提取的代码块不完整，无法使用")
                return None
        
        # 如果没有找到代码块，记录日志并退出
        self.logger.info("未找到有效的代码块，LLM响应格式不正确")
        return None
        
    def _is_complete_code_block(self, code: str) -> bool:
        """
        判断代码块是否完整
        
        Args:
            code: 代码字符串
            
        Returns:
            bool: 是否是完整的代码块
        """
        
        # 基本检查：代码不能为空
        if not code or not code.strip():
            return False
        
        lines = code.strip().split('\n')
        
        # 检查是否包含基本的Python代码结构
        has_import = False
        has_class_or_function = False
        has_main_execution = False
        
        for line in lines:
            line = line.strip()
            if line.startswith('import ') or line.startswith('from '):
                has_import = True
            elif line.startswith('class ') or line.startswith('def '):
                has_class_or_function = True
            elif 'if __name__ == "__main__":' in line:
                has_main_execution = True
        
        # 检查括号是否匹配
        open_brackets = code.count('(') + code.count('[') + code.count('{')
        close_brackets = code.count(')') + code.count(']') + code.count('}')
        brackets_balanced = (open_brackets == close_brackets)
        
        # 完整代码块应该包含导入、类或函数定义，括号匹配
        is_complete = has_import and has_class_or_function and brackets_balanced
        
        if not is_complete:
            self.logger.info(f"代码块完整性检查失败: import={has_import}, class/function={has_class_or_function}, brackets_balanced={brackets_balanced}")
        
        return is_complete
        