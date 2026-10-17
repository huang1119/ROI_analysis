"""启动 Web 应用。用法：python -m scripts.web"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn  # noqa: E402

from src import auth  # noqa: E402
from src.web.app import app  # noqa: E402


def main():
    if auth.auth_enabled() and not auth._auth_cfg().get("users"):
        print("=" * 64)
        print("未配置用户，使用内置默认管理员：admin / admin123")
        print("登录后请到 config/settings.json 的 auth.users 修改密码")
        print("=" * 64)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
