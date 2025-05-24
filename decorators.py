# /home/pi/my_cloud_app/decorators.py (正式版)
from functools import wraps
from flask import session, redirect, url_for, request, flash, g, current_app
# 确保 USERS_DB 从 config.py 正确导入或通过 current_app.config 获取
# from config import USERS_DB # 如果直接导入
# 或者在函数内部通过 current_app.config.get('USERS_DB')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_app.logger.debug(f"[decorators.login_required] Attempting URL: {request.url}")
        current_app.logger.debug(f"[decorators.login_required] Session 'username': {session.get('username')}")

        if 'username' not in session:
            flash("请先登录。", "warning")
            current_app.logger.warning(f"[decorators.login_required] 'username' not in session. Redirecting to login for {request.url}.")
            return redirect(url_for('auth.login', next=request.url))

        username_from_session = session['username']
        users_db = current_app.config.get('USERS_DB') # 从 app.config 获取 USERS_DB

        if not users_db or username_from_session not in users_db:
            flash(f"用户 '{username_from_session}' 不存在或配置错误，请重新登录。", "danger")
            current_app.logger.error(f"[decorators.login_required] User '{username_from_session}' not found in USERS_DB or USERS_DB is None. Clearing session and redirecting to login.")
            session.pop('username', None) # 清除无效的 session
            return redirect(url_for('auth.login'))

        # 正确设置 g.user，包含从 USERS_DB 获取的真实角色
        g.user = {
            'username': username_from_session,
            'role': users_db[username_from_session].get('role') # 从 USERS_DB 获取角色
        }
        current_app.logger.debug(f"[decorators.login_required] User '{username_from_session}' found. g.user set to: {g.user}")
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    @login_required # 先确保用户已登录，g.user 会被 login_required 设置
    def decorated_function(*args, **kwargs):
        current_app.logger.debug(f"[decorators.admin_required] Attempting URL: {request.url}")
        current_app.logger.debug(f"[decorators.admin_required] Checking admin role for g.user: {g.user}")

        # 检查 g.user 是否存在并且角色是否为 'admin'
        if not hasattr(g, 'user') or not g.user or g.user.get('role') != 'admin':
            flash("此操作需要管理员权限。", "danger")
            current_app.logger.warning(f"[decorators.admin_required] User {g.user.get('username') if hasattr(g, 'user') and g.user else 'UNKNOWN'} does not have admin role. Redirecting to 'files.list_files_root'.")
            # 通常重定向到用户的文件列表或首页
            return redirect(url_for('files.list_files_root')) # 或者 'main.index'

        current_app.logger.debug(f"[decorators.admin_required] User {g.user.get('username')} IS admin. Proceeding.")
        return f(*args, **kwargs)
    return decorated_function


