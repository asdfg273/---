# my_cloud_app/config.py
import os

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
USER_FILES_BASE_DIR = '/mnt/mydisk/my_cloud_storage' # 确保这是你外部硬盘的挂载点
USER_FILES_ROOT = USER_FILES_BASE_DIR
SECRET_KEY = 'your_very_secret_key_for_sessions_CHANGE_ME_PLEASE' # !!!务必修改!!!
DATA_DIR = os.path.join(APP_ROOT, 'data')
SHARES_DB_PATH = os.path.join(DATA_DIR, 'shares.json') # 用于文件分享
HIDDEN_FILES_PATH = os.path.join(DATA_DIR, 'hidden_files.json') # 用于隐藏文件
if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR)
        print(f"DEBUG: config.py - Created DATA_DIR: {DATA_DIR}")
    except OSError as e:
        print(f"ERROR: config.py - Could not create DATA_DIR {DATA_DIR}: {e}")
# 用户数据库 (示例，实际中你可能有更复杂的管理方式)
USERS_DB = {
    'admin': {'password': 'admin_password', 'role': 'admin', 'home_dir': os.path.join(USER_FILES_BASE_DIR, 'admin')},
    'user1': {'password': 'user1_password', 'role': 'user', 'home_dir': os.path.join(USER_FILES_BASE_DIR, 'user1')},
    'user2': {'password': 'user2_password', 'role': 'user', 'home_dir': os.path.join(USER_FILES_BASE_DIR, 'user2')},
    # 添加更多用户...
}

# 隐藏文件配置的持久化路径
print(f"DEBUG: config.py - SHARES_DB_PATH defined as: {SHARES_DB_PATH}")
# 确保基础用户目录存在 (为所有在 USERS_DB 中的用户创建家目录)
# 这部分可以移到 app.py 的初始化中，或者保留在这里确保配置时即准备好
if not os.path.exists(USER_FILES_BASE_DIR):
    try:
        os.makedirs(USER_FILES_BASE_DIR, exist_ok=True)
        current_app.logger.info(f"Base user files directory created: {USER_FILES_BASE_DIR}")
    except OSError as e:
        # 在配置阶段，current_app 可能还不可用，所以用 print
        print(f"ERROR: Could not create base user files directory {USER_FILES_BASE_DIR}: {e}")


print(f"DEBUG: config.py - APP_ROOT defined as: {APP_ROOT}")
print(f"DEBUG: config.py - USER_FILES_BASE_DIR defined as: {USER_FILES_BASE_DIR}")
print(f"DEBUG: config.py - USERS_DB keys: {list(USERS_DB.keys())}")
print("DEBUG: config.py - FINISHED LOADING")
