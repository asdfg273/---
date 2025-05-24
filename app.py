# my_cloud_app/app.py
from flask import Flask, session, redirect, url_for, g, request, flash, render_template, jsonify
import os
import psutil
import json
import sys
import logging
from datetime import datetime

# CSRF保护
from flask_wtf.csrf import CSRFProtect, CSRFError

# 打印一些初始调试信息
print(f"DEBUG: app.py - Module loading started.")
print(f"DEBUG: app.py - current working directory = {os.getcwd()}")
print(f"DEBUG: app.py - sys.path = {sys.path}")

# ---- 应用工厂或直接创建App实例 ----
print(f"DEBUG: app.py - Creating Flask app instance...")
app = Flask(__name__)
print(f"DEBUG: app.py - Flask app instance created.")

# ---- 配置加载 ----
print(f"DEBUG: app.py - Attempting to load config from 'config.py'...")
try:
    app.config.from_object('config') # 从 config.py 加载配置
    print(f"DEBUG: app.py - app.config.from_object('config') successful.")
    # 验证关键配置是否加载
    print(f"DEBUG (after from_object): APP_ROOT in app.config: {app.config.get('APP_ROOT')}")
    print(f"DEBUG (after from_object): USER_FILES_BASE_DIR in app.config: {app.config.get('USER_FILES_BASE_DIR')}")
    print(f"DEBUG (after from_object): USERS_DB keys in app.config: {list(app.config.get('USERS_DB', {}).keys())}")
    print(f"DEBUG (after from_object): SECRET_KEY is set: {'SECRET_KEY' in app.config and bool(app.config.get('SECRET_KEY'))}")

except ImportError:
    print(f"ERROR: app.py - Could not import 'config.py'. Make sure it exists and is in PYTHONPATH.")
    # 考虑是否要在这里退出或使用默认配置
except Exception as e:
    print(f"ERROR: app.py - Exception during config loading: {e}")

# ---- CSRF保护初始化 ----
print(f"DEBUG: app.py - Initializing CSRFProtect...")
csrf = CSRFProtect(app)
print(f"DEBUG: app.py - CSRFProtect initialized.")

# ---- 数据库和目录初始化 ----
# （确保 USERS_DB 和 USER_FILES_BASE_DIR 已从配置中加载）
USERS_DB = app.config.get('USERS_DB', {})
USER_FILES_BASE_DIR = app.config.get('USER_FILES_BASE_DIR')
HIDDEN_FILES_PATH = app.config.get('HIDDEN_FILES_PATH')
SHARED_FILES_PATH = app.config.get('SHARED_FILES_PATH') # <--- 新增

if not USER_FILES_BASE_DIR:
    print("CRITICAL ERROR: USER_FILES_BASE_DIR is not configured. Exiting.")
    sys.exit(1) # 或者抛出异常

# 创建用户家目录 (如果尚未创建)
print(f"DEBUG: app.py - Starting directory creation logic...")
if not os.path.exists(USER_FILES_BASE_DIR):
    try:
        os.makedirs(USER_FILES_BASE_DIR)
        app.logger.info(f"Base user files directory created: {USER_FILES_BASE_DIR}")
    except OSError as e:
        app.logger.error(f"Could not create base user files directory {USER_FILES_BASE_DIR}: {e}")

for username, data in USERS_DB.items():
    user_home = data.get('home_dir')
    if user_home:
        if not os.path.exists(user_home):
            try:
                os.makedirs(user_home)
                app.logger.info(f"Home directory created for user {username}: {user_home}")
            except OSError as e:
                app.logger.error(f"Could not create home directory for user {username} at {user_home}: {e}")
        # else:
            # print(f"DEBUG: app.py - Home directory for {username} already exists or was not created: {user_home}")
    else:
        app.logger.warning(f"User {username} does not have a 'home_dir' defined in USERS_DB.")


# 加载隐藏文件配置
if HIDDEN_FILES_PATH and os.path.exists(HIDDEN_FILES_PATH):
    try:
        with open(HIDDEN_FILES_PATH, 'r') as f:
            app.config['HIDDEN_FILES_DB'] = json.load(f)
        print(f"DEBUG: app.py - HIDDEN_FILES_DB loaded from {HIDDEN_FILES_PATH}")
    except Exception as e:
        app.config['HIDDEN_FILES_DB'] = {}
        print(f"ERROR: app.py - Failed to load hidden files DB: {e}. Initializing to empty.")
else:
    app.config['HIDDEN_FILES_DB'] = {}
    print(f"DEBUG: app.py - HIDDEN_FILES_PATH not found or not set. Initializing HIDDEN_FILES_DB to empty.")
    # Optionally create an empty file if it doesn't exist
    if HIDDEN_FILES_PATH:
        try:
            with open(HIDDEN_FILES_PATH, 'w') as f:
                json.dump({}, f)
            print(f"DEBUG: app.py - Created empty HIDDEN_FILES_DB file at {HIDDEN_FILES_PATH}")
        except Exception as e:
            print(f"ERROR: app.py - Could not create empty HIDDEN_FILES_DB file: {e}")


# 加载共享文件配置 <--- 新增
if SHARED_FILES_PATH and os.path.exists(SHARED_FILES_PATH):
    try:
        with open(SHARED_FILES_PATH, 'r') as f:
            app.config['SHARED_FILES_DB'] = json.load(f)
        print(f"DEBUG: app.py - SHARED_FILES_DB loaded from {SHARED_FILES_PATH}")
    except Exception as e:
        app.config['SHARED_FILES_DB'] = {}
        print(f"ERROR: app.py - Failed to load shared files DB: {e}. Initializing to empty.")
else:
    app.config['SHARED_FILES_DB'] = {}
    print(f"DEBUG: app.py - SHARED_FILES_PATH not found or not set. Initializing SHARED_FILES_DB to empty.")
    if SHARED_FILES_PATH:
        try:
            with open(SHARED_FILES_PATH, 'w') as f:
                json.dump({}, f)
            print(f"DEBUG: app.py - Created empty SHARED_FILES_DB file at {SHARED_FILES_PATH}")
        except Exception as e:
            print(f"ERROR: app.py - Could not create empty SHARED_FILES_DB file: {e}")

print(f"DEBUG: app.py - Directory creation logic finished.")


# ---- 蓝图注册 ----
print(f"DEBUG: app.py - Registering blueprints...")
from blueprints.auth import auth_bp
from blueprints.files import files_bp
from blueprints.code_runner import code_runner_bp
from blueprints.admin_panel import admin_panel_bp

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(files_bp, url_prefix='/files')
app.register_blueprint(code_runner_bp, url_prefix='/code')
app.register_blueprint(admin_panel_bp, url_prefix='/admin')
print(f"DEBUG: app.py - Blueprints registered.")


# ---- 请求钩子 ----
@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = USERS_DB.get(user_id)
        if g.user:
            g.user['username'] = user_id # 确保 username 字段存在于 g.user
            # current_app.logger.debug(f"User {user_id} loaded into g.user")
        # else:
            # current_app.logger.warning(f"User_id {user_id} in session but not in USERS_DB")

@app.context_processor
def inject_system_stats():
    def get_system_stats():
        try:
            temp_str = "N/A"
            # 尝试读取树莓派温度
            if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    temp = int(f.read().strip()) / 1000.0
                temp_str = f"{temp:.1f}°C"

            ram = psutil.virtual_memory()
            ram_total = f"{ram.total / (1024**3):.2f} GB"
            ram_used = f"{ram.used / (1024**3):.2f} GB ({ram.percent}%)"

            # 根分区磁盘空间
            disk_root = psutil.disk_usage('/')
            disk_root_total = f"{disk_root.total / (1024**3):.2f} GB"
            disk_root_free = f"{disk_root.free / (1024**3):.2f} GB ({disk_root.percent}%)"

            # 用户文件存储分区 (外部硬盘)
            user_disk_path = app.config.get('USER_FILES_BASE_DIR', '/')
            user_disk_total_str = "N/A"
            user_disk_free_str = "N/A"
            if os.path.exists(os.path.dirname(user_disk_path)): # 检查挂载点的父目录
                try:
                    user_disk = psutil.disk_usage(user_disk_path)
                    user_disk_total_str = f"{user_disk.total / (1024**3):.2f} GB"
                    user_disk_free_str = f"{user_disk.free / (1024**3):.2f} GB ({user_disk.percent}%)"
                except FileNotFoundError:
                    app.logger.warning(f"Path for user disk stats not found: {user_disk_path}")
                except Exception as e:
                    app.logger.error(f"Error getting user disk stats for {user_disk_path}: {e}")


            return {
                "temperature": temp_str,
                "ram_total": ram_total,
                "ram_used": ram_used,
                "disk_root_total": disk_root_total,
                "disk_root_free": disk_root_free,
                "user_disk_total": user_disk_total_str,
                "user_disk_free": user_disk_free_str,
                "user_disk_path": user_disk_path
            }
        except Exception as e:
            app.logger.error(f"Error getting system stats: {e}")
            return {} # 返回空字典，模板中需要处理
    return dict(system_stats=get_system_stats(), current_year=datetime.utcnow().year)


# ---- 错误处理 ----
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html', error=e), 404

@app.errorhandler(500)
def internal_server_error(e):
    # 可以记录更详细的错误信息 e.original_exception
    app.logger.error(f"Internal Server Error: {e.original_exception if hasattr(e, 'original_exception') else e}")
    return render_template('errors/500.html', error=e), 500

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash(f"CSRF token 错误或已过期: {e.description}", "danger")
    # 尝试重定向到 referrer，如果失败则到主页
    referrer = request.referrer or url_for('main_index') # 假设你有一个 'main_index' 路由
    return redirect(referrer)

# ---- 主页路由 ----
@app.route('/')
def main_index():
    if g.user:
        return redirect(url_for('files.list_files_root')) # 已登录则重定向到文件列表
    return redirect(url_for('auth.login')) # 未登录则重定向到登录页面


print(f"DEBUG: app.py - app.py module has been fully loaded by the Gunicorn worker.")
print(f"DEBUG: app.py - Worker should now be ready to accept requests if no prior errors occurred.")


# ---- 用于Flask开发服务器 ----
if __name__ == '__main__':
    # 确保在 app.run 之前配置日志
    if not app.debug: # 如果不是 debug 模式 (虽然下面会设为 True)
        # 可以配置更详细的生产日志
        pass
    else: # Debug 模式
        # Flask 开发服务器的日志级别已经比较详细
        pass
    
    # 为开发服务器设置日志处理器，如果还没有的话
    if not app.logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s '
            '[in %(pathname)s:%(lineno)d]'
        ))
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.DEBUG)

    print("Starting Flask development server...")
    app.run(debug=True, host='0.0.0.0', port=5000)

