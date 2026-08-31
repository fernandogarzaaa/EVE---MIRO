"""\n配置管理\n统一从项目根目录的 .env 文件加载配置\n"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示
    JSON_AS_ASCII = False
    
    # LLM: OpenAI-compatible. Default is a local GGUF server for this first run.
    # Never invent or scrape keys. Dummy key 'local' is only for 127.0.0.1:8088.
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'http://127.0.0.1:8088/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'qwen2.5-0.5b-instruct')
    
    # Zep Cloud (hard requirement unless a documented local/dev memory bypass).
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    # MIROFISH_MEMORY=local or EVE_MIRO_ALLOW_LOCAL_MEMORY=1 skips the ZEP key
    # check so the Flask app can boot. This does NOT fake Zep Cloud.
    MIROFISH_MEMORY = os.environ.get('MIROFISH_MEMORY', '').strip().lower()
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def local_memory_allowed(cls) -> bool:
        """Dev bypass: skip ZEP_API_KEY so the app can boot. Does not fake Zep Cloud."""
        mem = (getattr(cls, "MIROFISH_MEMORY", None) or os.environ.get("MIROFISH_MEMORY") or "").strip().lower()
        if mem in {"local", "dev", "skip", "none"}:
            return True
        flag = (os.environ.get("EVE_MIRO_ALLOW_LOCAL_MEMORY") or "").strip().lower()
        return flag in {"1", "true", "yes", "on"}

    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置"""
        errors: list[str] = []
        if not cls.LLM_API_KEY:
            errors.append(
                "LLM_API_KEY missing. Set LLM_API_KEY for an OpenAI-compatible "
                "endpoint (local GGUF at http://127.0.0.1:8088/v1 with dummy key "
                "'local', or another compatible provider). Do not invent keys."
            )
        if not cls.ZEP_API_KEY and not cls.local_memory_allowed():
            errors.append(
                "ZEP_API_KEY missing. Zep Cloud is required for graph memory. "
                "For a local/dev boot without Zep, set MIROFISH_MEMORY=local "
                "or EVE_MIRO_ALLOW_LOCAL_MEMORY=1 (does not fake Zep Cloud)."
            )
        if os.environ.get("ZEP_API_URL"):
            errors.append("ZEP_API_URL 不受支持；MiroFish 仅连接 Zep Cloud")
        if cls.DEBUG:
            import warnings
            warnings.warn("Flask DEBUG mode is enabled. Do not use in production.", RuntimeWarning)
        return errors
