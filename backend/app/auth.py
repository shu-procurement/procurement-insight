"""
精简版用户认证模块
只保留 Token 解析功能，不再负责注册和密码校验（由 Django 负责）
"""
import os

from jose import JWTError, jwt
from fastapi import HTTPException, status
from fastapi.security import HTTPBearer

# 这里的秘钥和算法必须和 Django 签发 Token 时用的一模一样！
SECRET_KEY = os.environ.get("FASTAPI_SECRET_KEY", "dev-only-change-me")
ALGORITHM = "HS256"

# 用于 FastAPI 依赖注入，从请求头自动提取 Bearer Token
# 这里的 tokenUrl 只是给 Swagger UI 测试用的，实际业务中前端已经从 Django 拿到 Token 了
security_scheme = HTTPBearer()

def verify_token(token: str) -> dict:
    """验证并解析前端传来的 JWT token"""
    try:
        # 解码并验证签名
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"无效的 token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )