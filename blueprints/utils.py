# /home/pi/my_cloud_app/blueprints/utils.py
import os
from flask import current_app, g

def get_user_home_dir(username=None):
    """
    获取指定用户或当前登录用户的主目录绝对路径。
    """
    if username is None:
        if hasattr(g, 'user') and g.user and 'username' in g.user:
            username_to_use = g.user['username']
        else:
            current_app.logger.error("get_user_home_dir: Cannot determine username (g.user not set or no username).")
            return None
    else:
        username_to_use = username

    user_files_base = current_app.config.get('USER_FILES_BASE_DIR')
    if not user_files_base:
        current_app.logger.error("get_user_home_dir: USER_FILES_BASE_DIR is not configured.")
        return None

    # 2024-03-29: USER_FILES_ROOT 已被 USER_FILES_BASE_DIR 替代
    # user_files_root = current_app.config.get('USER_FILES_ROOT') # 旧的配置名
    # if not user_files_root:
    #     current_app.logger.error("get_user_home_dir: USER_FILES_ROOT is not configured.")
    #     return None

    home_dir = os.path.join(user_files_base, username_to_use)
    # current_app.logger.debug(f"Calculated home directory for {username_to_use}: {home_dir}")
    return os.path.abspath(home_dir)

def get_absolute_path(username, relative_path=""):
    """
    根据用户名和相对路径获取绝对路径。
    如果 relative_path 为空，则返回用户的主目录。
    """
    user_home = get_user_home_dir(username)
    if not user_home:
        current_app.logger.error(f"get_absolute_path: Could not get home directory for user {username}.")
        return None

    # 防止路径遍历攻击
    # normpath 会解析 ".." 等，我们要确保最终路径仍在用户目录下
    # os.path.join 会自动处理空 relative_path
    prospective_path = os.path.normpath(os.path.join(user_home, relative_path))

    # 关键安全检查：确保解析后的路径仍然以用户主目录开头
    if not prospective_path.startswith(user_home):
        current_app.logger.warning(
            f"Path traversal attempt prevented for user {username}. "
            f"Relative path: '{relative_path}', Resolved: '{prospective_path}', User home: '{user_home}'"
        )
        return None # 或者抛出异常，或者返回用户主目录

    return prospective_path

# 你可以将其他通用的辅助函数也放在这里
# 例如： get_human_readable_size (如果 files.py 之外也需要用)
