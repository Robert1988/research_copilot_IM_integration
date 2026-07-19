import logging
import os
import aiohttp
import re
import ast
from pathlib import Path
# 使用标准 logging 模块
import logging


class CodeGenerateHandler:
    """代码生成处理器，负责实验代码的生成和相关文件的创建"""
    
    def __init__(self, output_path: str = "auto_generated_project", 
        paper_summary:str="",
        new_ideas:str="",
        paper_txt:str="",
        reply_to_content:str="",
        reply_to_code_mark_down:str=""
        ):
        self.output_path = output_path
        self.logger = logging.getLogger(__name__)
        self.paper_summary = paper_summary
        self.new_ideas = new_ideas
        self.paper_txt = paper_txt
        self.reply_to_content = reply_to_content
        self.reply_to_code_mark_down = reply_to_code_mark_down

    
    async def _call_deepseek_api(self, prompt: str) -> str:
        """调用 DeepSeek API 生成代码"""
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment variables")
        
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "deepseek-coder",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.5
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['choices'][0]['message']['content']
                else:
                    error_text = await response.text()
                    raise Exception(f"DeepSeek API call failed: {response.status}, {error_text}")
    
    def _extract_imports_from_code(self, code: str) -> list:
        """从生成的代码中提取Python导入"""
        imports = set()
        # 匹配import语句
        import_pattern = r'^\s*import\s+([^\s;]+)'
        # 匹配from...import语句
        from_import_pattern = r'^\s*from\s+([^\s.]+)'

        for line in code.split('\n'):
            if match := re.match(import_pattern, line):
                # 处理import语句，提取基础包名（第一个点之前的部分）
                for module in match.group(1).split(','):
                    base_module = module.strip().split('.')[0]
                    imports.add(base_module)
            elif match := re.match(from_import_pattern, line):
                imports.add(match.group(1).strip())

        # 过滤标准库导入（可选）
        stdlib = {'os', 'sys', 'json', 're', 'typing', 'pathlib', 'logging'}
        return list(imports - stdlib)
    
    def _generate_requirements_no_version(self, output_dir: Path) -> None:
        """生成不带版本号的requirements_no_version.txt文件
        
        扫描项目中所有Python文件的import语句，提取包名并进行映射
        """
        try:
            from config import PACKAGE_NAME_MAPPING as mapping
            from config import PYTHON_STDLIB as standard_libs
        except Exception:
            # 极简回退映射，防止 config 导入失败时卡住构建
            mapping = {
                "skimage": "scikit-image",
                "sklearn": "scikit-learn",
                "cv2": "opencv-python",
                "PIL": "Pillow",
                "bs4": "beautifulsoup4",
                "yaml": "PyYAML",
                "dateutil": "python-dateutil",
                "crypto": "pycryptodome",
                "Crypto": "pycryptodome",
                "jwt": "PyJWT",
                "dotenv": "python-dotenv",
                "fitz": "PyMuPDF",
                "imagehash": "ImageHash",
                "MySQLdb": "mysqlclient",
                "psycopg2": "psycopg2-binary",
                "googleapiclient": "google-api-python-client",
                "pdfminer": "pdfminer.six",
            }
            # 回退标准库列表
            standard_libs = {
                'os', 'sys', 'json', 'time', 'datetime', 'random', 'math', 'collections',
                'itertools', 'functools', 'operator', 're', 'string', 'io', 'pathlib',
                'urllib', 'http', 'logging', 'threading', 'multiprocessing', 'subprocess',
                'argparse', 'configparser', 'csv', 'sqlite3', 'pickle', 'base64', 'hashlib',
                'hmac', 'secrets', 'uuid', 'copy', 'typing', 'dataclasses', 'enum', 'abc',
                'contextlib', 'warnings', 'traceback', 'inspect', 'ast', 'dis', 'gc',
                'weakref', 'types', 'importlib', 'pkgutil', 'zipfile', 'tarfile', 'gzip',
                'bz2', 'lzma', 'shutil', 'tempfile', 'glob', 'fnmatch', 'linecache',
                'fileinput', 'stat', 'filecmp', 'email', 'mimetypes', 'quopri', 'uu',
                'html', 'xml', 'xmlrpc', 'ftplib', 'poplib', 'imaplib', 'nntplib',
                'smtplib', 'telnetlib', 'socketserver', 'socket', 'ssl', 'select',
                'selectors', 'asyncio', 'queue', 'sched', '_thread', 'dummy_threading',
                'concurrent', 'ctypes', 'struct', 'codecs', 'unicodedata', 'stringprep',
                'readline', 'rlcompleter', 'pprint', 'reprlib', 'locale', 'gettext',
                'calendar', 'zoneinfo', 'decimal', 'fractions', 'statistics', 'cmath',
                'array', 'heapq', 'bisect', 'weakref', 'copyreg', 'pydoc', 'doctest',
                'unittest', 'test', 'bdb', 'faulthandler', 'pdb', 'profile', 'pstats',
                'timeit', 'trace', 'py_compile', 'compileall', 'keyword', 'token',
                'tokenize', 'tabnanny', 'pyclbr', 'modulefinder', 'runpy', 'importlib',
                'site', 'user', 'builtins', '__future__', '__main__'
            }
        
        # 扫描所有 Python 文件，提取导入的包名
        imports = set()
        for py_file in output_dir.glob("**/*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.add(alias.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.add(node.module.split(".")[0])
            except Exception:
                continue
        
        # 归一化包名并过滤标准库
        normalized_packages = set()
        for import_name in imports:
            if import_name not in standard_libs:
                pkg = mapping.get(import_name, import_name)
                if pkg:
                    normalized_packages.add(pkg)
        
        # 特殊依赖规则：某些包需要额外的依赖
        special_dependencies = {
            # 深度学习框架依赖
            "keras": ["tensorflow-cpu"],  # Keras 需要 TensorFlow 后端
            "torch": ["torchvision", "torchaudio"],  # PyTorch 生态系统
            "tensorflow": ["tensorboard"],  # TensorFlow 通常需要 TensorBoard
            "tensorflow-gpu": ["tensorboard"],  # GPU 版本也需要 TensorBoard
            
            # 数据科学和机器学习
            "matplotlib": ["pillow"],  # matplotlib 图像保存需要 Pillow
            "seaborn": ["matplotlib", "pandas"],  # seaborn 依赖 matplotlib 和 pandas
            "plotly": ["pandas"],  # plotly 通常与 pandas 一起使用
            "scikit-learn": ["numpy", "scipy"],  # sklearn 核心依赖
            "xgboost": ["numpy", "scipy"],  # XGBoost 依赖
            "lightgbm": ["numpy", "scipy"],  # LightGBM 依赖
            "catboost": ["numpy", "pandas"],  # CatBoost 依赖
            
            # 计算机视觉
            "opencv-python": ["numpy"],  # OpenCV 依赖 numpy
            "opencv-python-headless": ["numpy"],  # 无头版本也需要 numpy
            "scikit-image": ["numpy", "scipy", "pillow"],  # skimage 依赖
            "imageio": ["pillow"],  # imageio 图像处理
            
            # 自然语言处理
            "transformers": ["torch", "tokenizers"],  # Hugging Face transformers
            "spacy": ["numpy"],  # spaCy 依赖
            "nltk": ["numpy"],  # NLTK 依赖
            "gensim": ["numpy", "scipy"],  # Gensim 依赖
            
            # 数据处理
            "pandas": ["numpy"],  # pandas 核心依赖
            "polars": ["numpy"],  # Polars 数据框架
            "dask": ["numpy", "pandas"],  # Dask 分布式计算
            "modin": ["pandas"],  # Modin 加速 pandas
            
            # 数值计算
            "scipy": ["numpy"],  # SciPy 依赖 NumPy
            "sympy": ["numpy"],  # SymPy 符号计算
            "numba": ["numpy"],  # Numba JIT 编译
            
            # Web 框架和 API
            "fastapi": ["uvicorn", "pydantic"],  # FastAPI 运行时依赖
            "django": ["pillow"],  # Django 图像字段支持
            "flask": ["jinja2", "werkzeug"],  # Flask 核心依赖
            "streamlit": ["pandas", "numpy"],  # Streamlit 数据应用
            
            # 数据库
            "sqlalchemy": ["psycopg2-binary"],  # SQLAlchemy PostgreSQL 驱动
            "alembic": ["sqlalchemy"],  # Alembic 数据库迁移
            "pymongo": ["dnspython"],  # MongoDB 驱动 DNS 支持
            
            # 异步和并发
            "asyncio": ["aiohttp"],  # 异步 HTTP 客户端
            "celery": ["redis"],  # Celery 任务队列
            
            # 测试框架
            "pytest": ["pytest-cov"],  # pytest 覆盖率插件
            "hypothesis": ["numpy"],  # 属性测试框架
            
            # 云服务 SDK
            "boto3": ["botocore"],  # AWS SDK
            "google-cloud-storage": ["google-auth"],  # Google Cloud 认证
            "azure-storage-blob": ["azure-core"],  # Azure 存储
            
            # 其他常见组合
            "jupyter": ["ipykernel", "notebook"],  # Jupyter 环境
            "jupyterlab": ["ipykernel"],  # JupyterLab
            "gradio": ["pillow", "pandas"],  # Gradio ML 界面
        }
        
        # 应用特殊依赖规则
        additional_packages = set()
        for package in normalized_packages:
            if package in special_dependencies:
                for dep in special_dependencies[package]:
                    additional_packages.add(dep)
                    self.logger.info(f"Added special dependency: {dep} (required by {package})")
        
        # 合并所有包
        all_packages = normalized_packages.union(additional_packages)
        
        # 生成requirements_no_version.txt
        requirements_content = "\n".join(sorted(all_packages)) + "\n"
        requirements_path = output_dir / "requirements_no_version.txt"
        requirements_path.write_text(requirements_content, encoding="utf-8")
        
        self.logger.info(f"Generated requirements_no_version.txt with {len(all_packages)} packages: {sorted(all_packages)}")
        if additional_packages:
            self.logger.info(f"Added {len(additional_packages)} special dependencies: {sorted(additional_packages)}")
        self.logger.info(f"Requirements file saved to {requirements_path}")
 
    def _generate_dockerfile(self, output_dir: Path) -> None:
        # 创建 PyTorch 包分离脚本
        torch_split_script = '''
import re
from pathlib import Path

# PyTorch 相关包列表
torch_packages = {
    "torch", "torchvision", "torchaudio", "torchtext", "torchdata",
    "pytorch-lightning", "torchmetrics", "transformers", "accelerate",
    "datasets", "tokenizers", "diffusers", "timm", "torchsummary",
    "torch-audio", "torch-vision", "torch-text", "fairseq", "detectron2"
}

req_file = Path("requirements.txt")
if not req_file.exists():
    print("requirements.txt not found, skipping torch package separation")
    exit(0)

lines = [l.strip() for l in req_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]

torch_reqs, other_reqs = [], []
for line in lines:
    pkg_name = re.split(r'[<>=\\s\\[]', line, 1)[0].lower()
    if pkg_name in torch_packages:
        torch_reqs.append(line)
    else:
        other_reqs.append(line)

if torch_reqs:
    Path("requirements_torch.txt").write_text("\\n".join(torch_reqs) + "\\n", encoding="utf-8")
    print(f"Generated requirements_torch.txt with {len(torch_reqs)} packages")

if other_reqs:
    Path("requirements_other.txt").write_text("\\n".join(other_reqs) + "\\n", encoding="utf-8")
    print(f"Generated requirements_other.txt with {len(other_reqs)} packages")
        '''
        
        # 保存 PyTorch 分离脚本
        torch_split_script_path = output_dir / "split_torch_packages.py"
        torch_split_script_path.write_text(torch_split_script, encoding="utf-8")
        
        # 生成 Dockerfile 内容
        dockerfile_content = f"""
# 使用官方 Python 3.11 镜像
FROM python:3.11-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \\
    gcc \\
    g++ \\
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 包管理工具
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 安装 pip-tools
RUN pip install --no-cache-dir pip-tools

# 设置工作目录
WORKDIR /app

# 复制代码文件
COPY . .

# 1) 使用 pip-compile 基于 requirements_no_version.txt 解析锁定兼容版本
RUN pip-compile requirements_no_version.txt --resolver=backtracking --output-file=requirements.txt

# 2) 检查是否有 torch 相关包，分别处理
RUN python split_torch_packages.py

# 3) 先安装非 torch 包
RUN if [ -f "requirements_other.txt" ]; then \\
        echo "Installing non-PyTorch packages..."; \\
        pip install --no-cache-dir --prefer-binary -r requirements_other.txt; \\
    fi

# 4) 再安装 torch 相关包（使用 CPU 索引）
RUN if [ -f "requirements_torch.txt" ]; then \\
        echo "Installing PyTorch packages with CPU index..."; \\
        pip install --no-cache-dir --prefer-binary --extra-index-url https://download.pytorch.org/whl/cpu -r requirements_torch.txt; \\
    fi

CMD ["python", "main.py"]
"""
        
        dockerfile_path = output_dir / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
        
        self.logger.info(f"Generated Dockerfile saved to {dockerfile_path}")
        self.logger.info(f"Generated split_torch_packages.py saved to {torch_split_script_path}")

    def _generate_workflow_file(self, output_dir: Path) -> None:
        """生成 GitHub Actions 工作流文件"""
        workflow_content = """
name: Build and Deploy to AWS Lambda
on:
  workflow_dispatch:
  push:
    branches: [ main ]
env:
  AWS_REGION: ${{ secrets.AWS_REGION }}
  ECR_REPOSITORY: ${{ github.event.repository.name }}
jobs:
  deploy:
    name: Deploy
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Checkout
        uses: actions/checkout@v3
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}
      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      - name: Build, tag, and push image to Amazon ECR
        id: build-image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: latest
        run: |
          # Build a docker container and push it to ECR
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          echo "image=$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" >> $GITHUB_OUTPUT
    """
        
        # 创建 .github/workflows 目录
        workflow_dir = output_dir / ".github" / "workflows"
        workflow_dir.mkdir(parents=True, exist_ok=True)
        
        workflow_path = workflow_dir / "build-deployment-prod.yaml"
        with open(workflow_path, 'w') as f:
            f.write(workflow_content)
        
        self.logger.info("Generated GitHub Actions workflow file")
    
    def _check_syntax_errors(self, code: str) -> str:
        """检查代码语法错误"""
        try:
            ast.parse(code)
            return "No syntax errors"
        except SyntaxError as e:
            return f"Line {e.lineno}: {e.msg}"
    
    def _detailed_bracket_check(self, code: str) -> str:
        """详细的括号匹配检查"""
        stack = []
        brackets = {'(': ')', '[': ']', '{': '}'}
        line_num = 1
        col_num = 1
        
        for i, char in enumerate(code):
            if char == '\n':
                line_num += 1
                col_num = 1
                continue
                
            if char in brackets:
                stack.append((char, line_num, col_num, i))
            elif char in brackets.values():
                if not stack:
                    return f"Unmatched closing bracket '{char}' at line {line_num}, column {col_num}"
                
                opening, open_line, open_col, open_pos = stack.pop()
                if brackets[opening] != char:
                    return f"Mismatched brackets: '{opening}' at line {open_line}, col {open_col} and '{char}' at line {line_num}, col {col_num}"
            
            col_num += 1
        
        if stack:
            char, line, col, pos = stack[-1]
            return f"Unmatched opening bracket '{char}' at line {line}, column {col}"
        
        return "All brackets are balanced"
    
    def _fix_missing_parentheses(self, code: str) -> str:
        """修复缺失的括号"""
        try:
            # 尝试解析代码
            ast.parse(code)
            return code  # 无错误直接返回
        except SyntaxError as e:
            # 提取错误位置
            self.logger.info(f'Syntax error detected: {e}')
            line_num = e.lineno
            offset = e.offset
            # 检查 line_num 是否为整数类型
            if not isinstance(line_num, int):
                return code
            
            lines = code.splitlines()
            if line_num > len(lines):
                return code
                
            error_line = lines[line_num - 1]
            
            # 使用详细的括号匹配算法来找到确切的错误位置
            bracket_error = self._detailed_bracket_check(code)
            
            # 处理缺少右括号的情况
            if "Unmatched opening bracket '('" in bracket_error:
                # 提取错误行号
                match = re.search(r'line (\d+)', bracket_error)
                if match:
                    error_line_num = int(match.group(1))
                    target_line = lines[error_line_num - 1]
                    
                    # 分析该行的括号平衡
                    open_count = 0
                    close_count = 0
                    
                    for i, char in enumerate(target_line):
                        if char == '(':
                            open_count += 1
                        elif char == ')':
                            close_count += 1
                    
                    # 如果有未匹配的左括号，在行末添加右括号
                    if open_count > close_count:
                        missing_brackets = open_count - close_count
                        # 找到合适的插入位置（通常在注释前或行末）
                        comment_pos = target_line.find('#')
                        if comment_pos != -1:
                            # 在注释前插入括号
                            fixed_line = target_line[:comment_pos].rstrip() + ')' * missing_brackets + '  ' + target_line[comment_pos:]
                        else:
                            # 在行末插入括号
                            fixed_line = target_line.rstrip() + ')' * missing_brackets
                        
                        lines[error_line_num - 1] = fixed_line
                        return '\n'.join(lines)
            
            # 处理其他类型的括号错误
            elif "unmatched '('" in e.msg or "unexpected EOF" in e.msg or "EOF while scanning" in e.msg:
                # 分析整个代码的括号平衡
                open_brackets = []
                for line_idx, line in enumerate(lines):
                    for char_idx, char in enumerate(line):
                        if char == '(':
                            open_brackets.append((line_idx, char_idx))
                        elif char == ')':
                            if open_brackets:
                                open_brackets.pop()
                
                # 如果有未匹配的左括号，在最后一个左括号所在行的末尾添加右括号
                if open_brackets:
                    last_open_line, last_open_pos = open_brackets[-1]
                    target_line = lines[last_open_line]
                    
                    # 在注释前或行末添加右括号
                    comment_pos = target_line.find('#')
                    if comment_pos != -1:
                        fixed_line = target_line[:comment_pos].rstrip() + ')' + '  ' + target_line[comment_pos:]
                    else:
                        fixed_line = target_line.rstrip() + ')'
                    
                    lines[last_open_line] = fixed_line
                    return '\n'.join(lines)
            
            # 处理缺少左括号的情况
            elif "unexpected ')'" in e.msg:
                if offset and offset > 1:
                    # 在错误位置前插入左括号
                    fixed_line = error_line[:offset-1] + '(' + error_line[offset-1:]
                    lines[line_num - 1] = fixed_line
                    return '\n'.join(lines)
        
        return code
    
    async def _generate_code_common(self, prompt: str, context_description: str) -> None:
        """通用的代码生成方法
        
        Args:
            prompt: 生成代码的提示词
            context_description: 上下文描述，用于日志记录
        """
        try:
            # 创建输出目录
            output_dir = Path(self.output_path)
            output_dir.mkdir(exist_ok=True)

            # 调用 API 生成代码
            self.logger.info(f"Calling DeepSeek API to generate code {context_description}...")
            generated_code = await self._call_deepseek_api(prompt)
            
            # 清理代码（移除可能的markdown标记）
            if "```python" in generated_code:
                generated_code = generated_code.split("```python")[1].split("```")[0]
            elif "```" in generated_code:
                generated_code = generated_code.split("```")[1].split("```")[0]
            
            # 保存代码
            code_path = output_dir / "experiment.py"
            with open(code_path, 'w', encoding='utf-8') as f:
                f.write(generated_code)
            
            self.logger.info(f"Generated experiment code {context_description} saved to {code_path}")
            
            self.logger.info("Checking syntax errors in generated code...")
            
            # 检查语法错误
            syntax_check_result = self._check_syntax_errors(generated_code)
            
            if syntax_check_result != "No syntax errors":
                self.logger.warning(f"Syntax errors detected: {syntax_check_result}")
                
                # 详细括号检查
                bracket_check_result = self._detailed_bracket_check(generated_code)
                self.logger.info(f"Bracket check result: {bracket_check_result}")
                
                # 尝试修复代码
                self.logger.info("Attempting to fix syntax errors...")
                fixed_code = self._fix_missing_parentheses(generated_code)
                
                # 验证修复后的代码
                fixed_syntax_check = self._check_syntax_errors(fixed_code)
                
                if fixed_syntax_check == "No syntax errors":
                    self.logger.info("✅ Code fixed successfully!")
                    
                    # 替换原文件
                    with open(code_path, 'w', encoding='utf-8') as f:
                        f.write(fixed_code)
                    
                    self.logger.info(f"Fixed code saved to {code_path}")
                    generated_code = fixed_code  # 更新生成的代码变量
                else:
                    self.logger.error(f"❌ Failed to fix syntax errors: {fixed_syntax_check}")
                    self.logger.warning("Proceeding with original code despite syntax errors")
            else:
                self.logger.info("✅ No syntax errors detected in generated code")
            
            # 生成不带版本号的requirements文件
            self._generate_requirements_no_version(output_dir)
            
            self._generate_dockerfile(output_dir)
            self._generate_workflow_file(output_dir)
            self._generate_main_file(output_dir)
            
            self.logger.info(f"Experiment code generation {context_description} completed successfully")
            
        except Exception as e:
            self.logger.error(f"Error generating experiment code {context_description}: {str(e)}")
            raise

    async def generate_experiment_code(self) -> None:
        """生成实验代码的主函数"""
        # 构建提示词
        prompt = """
        You are a highly skilled expert in scientific paper coding. 
        Your task is to generate Python code that can be executed to evaluate new ideas on top of a scientific paper.
        Your response should be a complete Python script only, named experiment.py 
        Explanations or comments, and summary of final results should be printed to the console.

        Original paper is provided in the end. The following are key arguments from the paper:
        {paper_summary}

        Previous comment:
        {reply_to_content}

        Previous code:
        {reply_to_code_mark_down}

        New ideas:
        {new_ideas}

        Above new ideas seem to be reasonable, please design an experiment to evaluate them using python code. 
        Requirements:
        1. If needed, please first implement the main algorithm or method described in the paper.
        2. If needed, please include data loading, preprocessing, and model computation. 
        3. In the end, generate concrete numbers in the final results.
        4. The code must be executable. Double check Syntax Error. 
        5. The code must be well-structured and easy to understand
        6. Make sure used packages are imported in the beginning of code snipet.
        7. No GPU is available. All computation shall base on CPU.
        8. Do not save any file or visualize any graph (no need to use matplotlib). 
        9. Your response should be a complete Python script only. 
        10. Include proper error handling and logging where appropriate. 
        11. Ensure the program exits with sys.exit(1) when encountering any critical errors that require termination, particularly during the model training process.
        12. The code you generate needs to run in serverless environments (such as AWS Lambda) and Docker containers. Please avoid generating code that requires GUI, pre-trained model downloads, or other network-dependent operations.
        13. Code sinppet would run on AWS Lambda. It is a read-only file system. Don't make file nor save file.

        Please provide the complete Python code that meets these requirements.

        Original paper:
        {paper_txt}

        Finanly repeat the requirements:
        1. If needed, please first implement the main algorithm or method described in the paper.
        2. If needed, please include data loading, preprocessing, and model computation. 
        3. In the end, generate concrete numbers in the final results.
        4. The code must be executable. Double check Syntax Error. 
        5. The code must be well-structured and easy to understand
        6. Make sure used packages are imported in the beginning of code snipet.
        7. No GPU is available. All computation shall base on CPU.
        8. Do not save any file or visualize any graph (no need to use matplotlib). 
        9. Your response should be a complete Python script only. 
        10. Include proper error handling and logging where appropriate. 
        11. Ensure the program exits with sys.exit(1) when encountering any critical errors that require termination, particularly during the model training process.
        12. The code you generate needs to run in serverless environments (such as AWS Lambda) and Docker containers. Please avoid generating code that requires GUI, pre-trained model downloads, or other network-dependent operations.
        13. Code sinppet would run on AWS Lambda. It is a read-only file system. Don't make file nor save file.

        """
        
        self.logger.info(f"reply_to_content length of characters: {len(self.reply_to_content)}")
        self.logger.info(f"reply_to_code_mark_down length of characters: {len(self.reply_to_code_mark_down)}")
        self.logger.info(f"paper_txt length of characters: {len(self.paper_txt)}")
        self.logger.info(f"paper_summary length of characters: {len(self.paper_summary)}")
        self.logger.info(f"new_ideas length of characters: {len(self.new_ideas)}")

        # === 新增：按上下文预算截断，避免超过模型最大上下文 ===
        # 估算参数（保守一些）：约 4 字符 ≈ 1 token
        CHARS_PER_TOKEN = 4
        MAX_CTX_TOKENS = 131072
        RESERVE_COMPLETION_TOKENS = 4096    # 预留给模型输出
        SAFETY_TOKENS = 4096                # 安全余量，防止估算误差
        allowed_tokens = max(0, MAX_CTX_TOKENS - RESERVE_COMPLETION_TOKENS - SAFETY_TOKENS)

        template = prompt  # 当前是指令模板
        # 估算模板自身 token（去掉占位符长度，粗略估算）
        placeholders_len = len("{paper_summary}") + len("{reply_to_content}") + len("{reply_to_code_mark_down}") + len("{new_ideas}") + len("{paper_txt}")
        template_chars = max(0, len(template) - placeholders_len)
        template_tokens = template_chars // CHARS_PER_TOKEN

        content_tokens_budget = max(0, allowed_tokens - template_tokens)
        if content_tokens_budget <= 0:
            # 模板本身就接近上限，给内容块留一个兜底预算，防止完全为空
            content_tokens_budget = 10000

        # 分配各部分的token预算
        # paper_summary 和 new_ideas 通常较短，不截断
        paper_summary_tokens = len(self.paper_summary) // CHARS_PER_TOKEN if self.paper_summary else 0
        new_ideas_tokens = len(self.new_ideas) // CHARS_PER_TOKEN if self.new_ideas else 0
        
        # 根据不同场景分配token预算
        if self.paper_txt and self.reply_to_code_mark_down:
            # 场景1: paper_txt和reply_to_code_mark_down都非空 - 当前逻辑
            reply_content_max_tokens = int(content_tokens_budget * 0.1)
            reply_code_max_tokens = int(content_tokens_budget * 0.3)
            reply_content_tokens_est = len(self.reply_to_content) // CHARS_PER_TOKEN if self.reply_to_content else 0
            reply_code_tokens_est = len(self.reply_to_code_mark_down) // CHARS_PER_TOKEN if self.reply_to_code_mark_down else 0
            
            # 剩余预算给 paper_txt
            used_tokens = paper_summary_tokens + new_ideas_tokens + min(reply_content_tokens_est, reply_content_max_tokens) + min(reply_code_tokens_est, reply_code_max_tokens)
            paper_txt_budget_tokens = max(0, content_tokens_budget - used_tokens)
            
        elif self.paper_txt and not self.reply_to_code_mark_down:
            # 场景2: paper_txt非空，reply_to_code_mark_down为空 - reply_to_content取固定比例，其余给paper_txt
            reply_content_max_tokens = int(content_tokens_budget * 0.2)  # reply_to_content取20%
            reply_content_tokens_est = len(self.reply_to_content) // CHARS_PER_TOKEN if self.reply_to_content else 0
            
            # 剩余预算给 paper_txt
            used_tokens = paper_summary_tokens + new_ideas_tokens + min(reply_content_tokens_est, reply_content_max_tokens)
            paper_txt_budget_tokens = max(0, content_tokens_budget - used_tokens)
            reply_code_max_tokens = 0
            reply_code_tokens_est = 0
            
        elif not self.paper_txt and self.reply_to_code_mark_down:
            # 场景3: paper_txt为空，reply_to_code_mark_down非空 - reply_to_content取固定比例，其余给reply_to_code_mark_down
            reply_content_max_tokens = int(content_tokens_budget * 0.2)  # reply_to_content取20%
            reply_content_tokens_est = len(self.reply_to_content) // CHARS_PER_TOKEN if self.reply_to_content else 0
            
            # 剩余预算给 reply_to_code_mark_down
            used_tokens = paper_summary_tokens + new_ideas_tokens + min(reply_content_tokens_est, reply_content_max_tokens)
            reply_code_max_tokens = max(0, content_tokens_budget - used_tokens)
            reply_code_tokens_est = len(self.reply_to_code_mark_down) // CHARS_PER_TOKEN if self.reply_to_code_mark_down else 0
            paper_txt_budget_tokens = 0
            
        else:
            # 场景4: paper_txt和reply_to_code_mark_down都为空 - 所有预留token都给reply_to_content
            used_tokens = paper_summary_tokens + new_ideas_tokens
            reply_content_max_tokens = max(0, content_tokens_budget - used_tokens)
            reply_content_tokens_est = len(self.reply_to_content) // CHARS_PER_TOKEN if self.reply_to_content else 0
            reply_code_max_tokens = 0
            reply_code_tokens_est = 0
            paper_txt_budget_tokens = 0

        def head_truncate(s: str, n_tokens: int) -> str:
            if not s or n_tokens <= 0:
                return ""
            n_chars = max(0, n_tokens * CHARS_PER_TOKEN)
            return s if len(s) <= n_chars else s[:n_chars]

        def tail_truncate(s: str, n_tokens: int) -> str:
            if not s or n_tokens <= 0:
                return ""
            n_chars = max(0, n_tokens * CHARS_PER_TOKEN)
            return s if len(s) <= n_chars else s[-n_chars:]

        # 截断各部分内容
        trimmed_reply_to_content = tail_truncate(self.reply_to_content, reply_content_max_tokens)
        trimmed_reply_to_code_mark_down = head_truncate(self.reply_to_code_mark_down, reply_code_max_tokens)
        trimmed_paper_txt = head_truncate(self.paper_txt, paper_txt_budget_tokens)

        self.logger.info(f"[ContextBudget] reply_to_content: est={reply_content_tokens_est}t, budget={reply_content_max_tokens}t -> {len(trimmed_reply_to_content)} chars")
        self.logger.info(f"[ContextBudget] reply_to_code_mark_down: est={reply_code_tokens_est}t, budget={reply_code_max_tokens}t -> {len(trimmed_reply_to_code_mark_down)} chars")
        self.logger.info(f"[ContextBudget] paper_txt: budget={paper_txt_budget_tokens}t -> {len(trimmed_paper_txt)} chars")
        
        prompt = prompt.format(
            paper_txt=trimmed_paper_txt, 
            paper_summary=self.paper_summary,
            new_ideas=self.new_ideas,
            reply_to_content=trimmed_reply_to_content,
            reply_to_code_mark_down=trimmed_reply_to_code_mark_down
        )
        
        self.logger.info(f"Final prompt length of characters: {len(prompt)}")
        
        await self._generate_code_common(prompt, "from paper analysis")

    async def generate_experiment_code_in_chat(self, chat_messages: str, code_repo_content: str, pdf_content: str) -> None:
        """Generate experiment code from chat context with improved budget allocation"""
        template = """
        Based on the following chat conversation, code repository context, and PDF research content, please generate a complete Python experiment script.

        Requirements:
        1. Analyze the chat conversation to understand what the user wants to implement.
        2. Use the code repository as reference for implementation patterns and structure.
        3. Incorporate insights from the PDF content if relevant to the implementation.
        4. Generate executable Python code that implements the discussed functionality.
        5. The code must be well-structured and easy to understand. Make comments in code and print logs line by line.
        6. Make sure used packages are imported in the beginning of code snippet.
        7. No GPU is available. All computation shall base on CPU.
        8. Do not save any file or visualize any graph (no need to plot any graph image).
        9. Your response should be a complete Python script only.
        10. Include proper error handling and logging where appropriate. 
        11. Ensure the program exits with sys.exit(1) when encountering any critical errors that require termination, particularly during the model training process.
        12. The code you generate needs to run in serverless environments (such as AWS Lambda) and Docker containers. Please avoid generating code that requires GUI, pre-trained model downloads, or other network-dependent operations.
        13. Code sinppet would run on AWS Lambda. It is a read-only file system. Don't make file nor save file.
        Please provide the complete Python code that meets these requirements.
        
        Code repository context:
        {code_repo_content}

        PDF research content:
        {pdf_content}

        Chat conversation:
        {chat_messages}

        Repeat requirments:
        1. Analyze the chat conversation to understand what the user wants to implement.
        2. Use the code repository as reference for implementation patterns and structure.
        3. Incorporate insights from the PDF content if relevant to the implementation.
        4. Generate executable Python code that implements the discussed functionality.
        5. The code must be well-structured and easy to understand. Make comments in code and print logs line by line.
        6. Make sure used packages are imported in the beginning of code snippet.
        7. No GPU is available. All computation shall base on CPU.
        8. Do not save any file or visualize any graph (no need to plot any graph image).
        9. Your response should be a complete Python script only.
        10. Include proper error handling and logging where appropriate. 
        11. Ensure the program exits with sys.exit(1) when encountering any critical errors that require termination, particularly during the model training process.
        12. The code you generate needs to run in serverless environments (such as AWS Lambda) and Docker containers. Please avoid generating code that requires GUI, pre-trained model downloads, or other network-dependent operations.
        13. Code sinppet would run on AWS Lambda. It is a read-only file system. Don't make file nor save file.
        """

        # === 修改开始：更严格的预算控制 ===
        CHARS_PER_TOKEN = 4
        MAX_TOKENS = 131072  # DeepSeek 模型限制
        RESPONSE_TOKENS = 4000  # 为响应预留的token
        TEMPLATE_TOKENS = len(template) // CHARS_PER_TOKEN
        
        # 可用于内容的token预算
        content_tokens_budget = MAX_TOKENS - RESPONSE_TOKENS - TEMPLATE_TOKENS
        
        if content_tokens_budget <= 0:
            # 模板本身就接近上限，给内容块留一个兜底预算，防止完全为空
            content_tokens_budget = 10000

        # === 修改开始：更保守的预算分配 ===
        chat_tokens_est = len(chat_messages) // CHARS_PER_TOKEN if chat_messages else 0
        chat_max_tokens = int(content_tokens_budget * 0.15)  # 减少到15%

        # 初始分配：先确定 chat 的预算
        if chat_tokens_est <= chat_max_tokens:
            # 不截断 chat，实际预算就是它自身长度
            chat_budget_tokens = chat_tokens_est
            chat_mode = "no-cut"
        else:
            # 仅当超过 15% 时才截断到 15%
            chat_budget_tokens = chat_max_tokens
            chat_mode = "tail"

        remaining_tokens = max(0, content_tokens_budget - chat_budget_tokens)

        # 给 code/pdf 分配剩余预算（更保守的权重分配）
        code_weight = 0.5  # 减少到50%
        pdf_weight = 0.3   # 减少到30%
        # 剩余20%作为安全缓冲
        
        non_empty_weights = []
        if code_repo_content:
            non_empty_weights.append(("code", code_weight))
        if pdf_content:
            non_empty_weights.append(("pdf", pdf_weight))
        
        # 计算实际可用的预算（保留20%缓冲）
        usable_remaining = int(remaining_tokens * 0.8)
        total_w = sum(w for _, w in non_empty_weights) or 1.0

        code_budget_tokens = 0
        pdf_budget_tokens = 0
        if usable_remaining > 0 and non_empty_weights:
            for name, w in non_empty_weights:
                portion = int(usable_remaining * (w / total_w))
                if name == "code":
                    code_budget_tokens = portion
                else:
                    pdf_budget_tokens = portion

        def head_truncate(s: str, n_tokens: int) -> str:
            if not s or n_tokens <= 0:
                return ""
            n_chars = max(0, n_tokens * CHARS_PER_TOKEN)
            return s if len(s) <= n_chars else s[:n_chars]

        def tail_truncate(s: str, n_tokens: int) -> str:
            if not s or n_tokens <= 0:
                return ""
            n_chars = max(0, n_tokens * CHARS_PER_TOKEN)
            return s if len(s) <= n_chars else s[-n_chars:]

        trimmed_chat = chat_messages if chat_mode == "no-cut" else tail_truncate(chat_messages, chat_budget_tokens)
        trimmed_code = head_truncate(code_repo_content, code_budget_tokens)
        trimmed_pdf = head_truncate(pdf_content, pdf_budget_tokens)

        self.logger.info(f"[ContextBudget] chat mode={chat_mode}, est={chat_tokens_est}t, budget={chat_budget_tokens}t -> {len(trimmed_chat)} chars")
        self.logger.info(f"[ContextBudget] code budget={code_budget_tokens}t -> {len(trimmed_code)} chars")
        self.logger.info(f"[ContextBudget] pdf  budget={pdf_budget_tokens}t -> {len(trimmed_pdf)} chars")

        chat_messages = trimmed_chat
        code_repo_content = trimmed_code
        pdf_content = trimmed_pdf
        # === 修改结束 ===

        prompt = template.format(
            chat_messages=chat_messages,
            code_repo_content=code_repo_content,
            pdf_content=pdf_content
        )
        
        # 最终检查prompt长度
        final_tokens = len(prompt) // CHARS_PER_TOKEN
        self.logger.info(f"Prompt length of characters: {len(prompt)}")
        self.logger.info(f"Estimated tokens: {final_tokens} (limit: {MAX_TOKENS - RESPONSE_TOKENS})")
        
        if final_tokens > (MAX_TOKENS - RESPONSE_TOKENS):
            self.logger.warning(f"Prompt still too long after trimming: {final_tokens} tokens")
            # 进一步紧急裁剪
            emergency_budget = MAX_TOKENS - RESPONSE_TOKENS - TEMPLATE_TOKENS
            if emergency_budget > 0:
                # 按比例进一步裁剪
                scale_factor = emergency_budget / (chat_budget_tokens + code_budget_tokens + pdf_budget_tokens)
                if scale_factor < 1:
                    trimmed_chat = head_truncate(trimmed_chat, int(chat_budget_tokens * scale_factor))
                    trimmed_code = head_truncate(trimmed_code, int(code_budget_tokens * scale_factor))
                    trimmed_pdf = head_truncate(trimmed_pdf, int(pdf_budget_tokens * scale_factor))
                    
                    prompt = template.format(
                        chat_messages=trimmed_chat,
                        code_repo_content=trimmed_code,
                        pdf_content=trimmed_pdf
                    )
                    self.logger.info(f"Emergency trimmed prompt length: {len(prompt)} chars")

        await self._generate_code_common(prompt, "from chat context")

    def _generate_main_file(self, output_dir: Path) -> None:
        """生成main.py文件作为Lambda handler"""
        main_py_content = '''import json
import subprocess
import sys
import traceback
import os
from pathlib import Path

def lambda_handler(event, context):
    """
    AWS Lambda handler function that executes experiment.py as a subprocess
    """
    try:
        # 设置环境变量
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        
        # 获取experiment.py的路径
        experiment_path = Path(__file__).parent / "experiment.py"
        
        # 检查文件是否存在
        if not experiment_path.exists():
            raise FileNotFoundError(f"experiment.py not found at {experiment_path}")
        
        # 使用subprocess执行experiment.py
        result = subprocess.run(
            [sys.executable, str(experiment_path)],
            capture_output=True,
            text=True,
            timeout=840,  # 14分钟超时，留1分钟给Lambda清理
            env=env,
            cwd=str(experiment_path.parent)  # 设置工作目录
        )
        
        # 强信号 + 导入失败类型（大小写不敏感）
        has_error = result.returncode != 0
        if not has_error:
            combined_output = (result.stdout or "") + (result.stderr or "")
            combined_output_lower = combined_output.lower()
            strong_error_signals = [
                "traceback",
                "exception:",
                "experiment failed",
                "importerror",
                "modulenotfounderror",
                "no module named",
                "cannot import name",
            ]
            if any(sig in combined_output_lower for sig in strong_error_signals):
                has_error = True
        
        response = {
            'experimentStatusCode': 500 if has_error else 200,
            'body': {
                'message': 'Experiment failed' if has_error else 'Experiment completed successfully',
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'execution_time': context.get_remaining_time_in_millis() if context else None
            }
        }
        
        # 输出执行结果
        if result.stdout:
            print("=== Experiment Output ===")
            print(result.stdout)
        
        if result.stderr:
            print("=== Experiment Errors ===")
            print(result.stderr)
        
        return response
        
    except subprocess.TimeoutExpired:
        error_response = {
            'statusCode': 500,  # 改为500，不再使用408
            'body': {
                'message': 'Experiment execution timeout',
                'error': 'Process exceeded timeout limit'
            }
        }
        
        print("Experiment execution timeout")
        return error_response
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        
        error_response = {
            'statusCode': 500,
            'body': {
                'message': 'Lambda handler failed',
                'error': str(e),
                'traceback': error_traceback
            }
        }
        
        print(f"Lambda handler failed with error: {str(e)}")
        print(f"Traceback: {error_traceback}")
        return error_response

if __name__ == "__main__": 
    # 直接执行时的逻辑 
    result = lambda_handler({}, None) 
    print(json.dumps(result, indent=2))
        
        '''
    
        main_py_path = output_dir / "main.py"
        with open(main_py_path, 'w', encoding='utf-8') as f:
            f.write(main_py_content)
        
        self.logger.info(f"Generated main.py Lambda handler saved to {main_py_path}")