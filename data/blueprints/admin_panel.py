from flask import Blueprint, render_template, request, flash, current_app, session, redirect, url_for, g
from decorators import admin_required, login_required # 确保从 decorators.py 导入
import os
import json # 用于保存和加载 HIDDEN_FILES.json
from .utils import get_absolute_path

admin_panel_bp = Blueprint('admin_panel', __name__, template_folder='../templates/admin_panel')

def get_all_user_files_recursive(user_home_abs_path, base_path_for_relative=""):
    """
    递归获取指定绝对路径下的所有文件和文件夹。
    返回一个列表，每个元素是字典 {'path': '相对于扫描起始点的路径', 'is_dir': True/False}。
    base_path_for_relative: 内部递归使用，外部调用时为空字符串。
    """
    items = []
    try:
        for item_name in os.listdir(user_home_abs_path):
            current_item_abs_path = os.path.join(user_home_abs_path, item_name)
            # 构建相对于最初扫描目录的路径
            relative_path = os.path.join(base_path_for_relative, item_name).replace(os.sep, '/') # 统一使用 / 作为路径分隔符
            
            items.append({"path": relative_path, "is_dir": os.path.isdir(current_item_abs_path)})
            
            if os.path.isdir(current_item_abs_path):
                # 递归进入子目录
                items.extend(get_all_user_files_recursive(current_item_abs_path, relative_path))
    except FileNotFoundError:
        current_app.logger.warning(f"Directory not found during scan: {user_home_abs_path}")
    except PermissionError:
        current_app.logger.warning(f"Permission denied while scanning: {user_home_abs_path}")
    return items

def load_hidden_files_config():
    """从 JSON 文件加载隐藏文件配置"""
    try:
        with open(current_app.config['HIDDEN_FILES_PATH'], 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        current_app.logger.info(f"Hidden files config not found or invalid at {current_app.config['HIDDEN_FILES_PATH']}. Returning empty config.")
        return {} # 如果文件不存在或格式错误，返回空字典

def save_hidden_files_config(config_data):
    """将隐藏文件配置保存到 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(current_app.config['HIDDEN_FILES_PATH']), exist_ok=True) # 确保目录存在
        with open(current_app.config['HIDDEN_FILES_PATH'], 'w') as f:
            json.dump(config_data, f, indent=4)
        current_app.config['HIDDEN_FILES'] = config_data # 更新内存中的配置 (如果 app.py 中有这个逻辑)
        return True
    except IOError as e:
        current_app.logger.error(f"Error saving hidden files config: {e}")
        return False

@admin_panel_bp.route('/', methods=['GET', 'POST'])
@login_required
@admin_required
def panel_home():
    users_db = current_app.config.get('USERS_DB', {})
    user_files_root_dir = current_app.config.get('USER_FILES_ROOT') # 从 config.py 获取用户文件总根目录

    if not user_files_root_dir:
        flash("配置错误：USER_FILES_ROOT 未设置！", "danger")
        return render_template('panel_home.html', non_admin_users={}, selected_user_for_management=None, user_files_to_manage=[])

    # 获取所有非管理员用户
    non_admin_users = {username: data for username, data in users_db.items() if data.get('role') != 'admin'}
    
    # 从查询参数获取当前要管理的用户，或从表单提交获取
    selected_user_for_management = request.args.get('manage_user')
    if request.method == 'POST' and 'target_user' in request.form:
         selected_user_for_management = request.form.get('target_user')


    user_files_to_manage = []
    hidden_files_config = load_hidden_files_config() # 加载最新的隐藏配置

    if request.method == 'POST':
        action = request.form.get('action')
        target_user_for_post = request.form.get('target_user') # POST请求中的目标用户
        
        if action == 'update_hidden_files' and target_user_for_post and target_user_for_post in non_admin_users:
            # 获取所有提交的、name 为 "hidden_paths_for_user_USERNAME" 的复选框的值
            # 这些值应该是文件/文件夹相对于该用户家目录的路径
            hidden_paths_submitted = request.form.getlist(f'hidden_paths_for_user_{target_user_for_post}')
            
            # 更新该用户的隐藏文件列表
            hidden_files_config[target_user_for_post] = hidden_paths_submitted
            
            if save_hidden_files_config(hidden_files_config):
                flash(f"用户 '{target_user_for_post}' 的文件隐藏设置已更新。", "success")
            else:
                flash("保存隐藏文件配置失败！", "danger")
            
            # 重定向到同一个用户的管理页面，以显示更新后的状态
            return redirect(url_for('.panel_home', manage_user=target_user_for_post))

    # --- 为GET请求或POST后重新加载页面准备数据 ---
    if selected_user_for_management and selected_user_for_management in non_admin_users:
        user_home_abs = os.path.abspath(os.path.join(user_files_root_dir, selected_user_for_management))
        
        current_app.logger.debug(f"Managing files for user: {selected_user_for_management}")
        current_app.logger.debug(f"Absolute home path for user: {user_home_abs}")

        if os.path.isdir(user_home_abs):
            all_files_raw = get_all_user_files_recursive(user_home_abs) # 扫描用户家目录
            
            # 排序，文件夹在前，文件在后，然后按路径
            all_files_raw.sort(key=lambda x: (not x['is_dir'], x['path']))
            
            current_user_hidden_list = hidden_files_config.get(selected_user_for_management, [])
            
            for file_item in all_files_raw:
                user_files_to_manage.append({
                    'path': file_item['path'], # 相对于用户家目录的路径
                    'is_dir': file_item['is_dir'],
                    'is_hidden': file_item['path'] in current_user_hidden_list
                })
            
            current_app.logger.debug(f"Files found for user {selected_user_for_management}: {len(user_files_to_manage)}")
            if not user_files_to_manage:
                 flash(f"用户 '{selected_user_for_management}' 的主目录中没有文件或文件夹。", "info")

        else:
            flash(f"用户 '{selected_user_for_management}' 的主目录 '{user_home_abs}' 未找到或不是有效目录。", "warning")
            current_app.logger.warning(f"User home directory not found or invalid: {user_home_abs}")
            selected_user_for_management = None # 清除选择，避免后续逻辑错误

    return render_template('panel_home.html',
                           non_admin_users=non_admin_users,
                           selected_user_for_management=selected_user_for_management,
                           user_files_to_manage=user_files_to_manage)
