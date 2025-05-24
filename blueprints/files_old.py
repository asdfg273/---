# /home/pi/my_cloud_app/blueprints/files.py

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    send_from_directory, flash, current_app, g, send_file, jsonify
)
from werkzeug.utils import secure_filename
import os
import shutil
# from PIL import Image, UnidentifiedImageError # 保留，以防未来用于生成缩略图等
import mimetypes
import json
import math
from datetime import datetime
# from .utils import get_user_home_dir # 看起来你的 get_user_home_dir_abs 已经内联了
from decorators import login_required, admin_required # 假设你的 decorators.py 在 my_cloud_app 包的根目录下

files_bp = Blueprint('files', __name__, template_folder='../templates/files')


# --- 辅助函数 ---

def get_user_home_dir_abs(username):
    # 从 app.config 获取 USERS_DB (假设在 app.py 中加载并设置)
    users_db = current_app.config.get('USERS_DB', {})
    user_data = users_db.get(username)
    if user_data and 'home_dir' in user_data:
        # 确保 home_dir 是绝对路径或相对于 USER_FILES_BASE_DIR (如果存在)
        base_dir_config = current_app.config.get('USER_FILES_BASE_DIR')
        if base_dir_config and not os.path.isabs(user_data['home_dir']):
            # current_app.logger.debug(f"User '{username}' home_dir '{user_data['home_dir']}' is relative. Resolving against USER_FILES_BASE_DIR '{base_dir_config}'.")
            # return os.path.abspath(os.path.join(base_dir_config, user_data['home_dir']))
             # 修正：直接使用 USERS_DB 中的 home_dir，它应该是绝对路径或相对于 USER_FILES_BASE_DIR 的子目录名
            return os.path.abspath(os.path.join(base_dir_config, username)) # 通常是 base_dir/username
        
        # 如果 USERS_DB 中的 home_dir 已经是绝对路径，则直接使用
        # current_app.logger.debug(f"User '{username}' home_dir '{user_data['home_dir']}' is absolute.")
        # return os.path.abspath(user_data['home_dir']) # 已废弃，home_dir 现在应该是相对于 USER_FILES_BASE_DIR 的

    # Fallback if USERS_DB doesn't have specific home_dir for user, or if USERS_DB itself is missing
    # Default to USER_FILES_BASE_DIR/username
    user_files_base = current_app.config.get('USER_FILES_BASE_DIR')
    if not user_files_base:
        current_app.logger.error(f"USER_FILES_BASE_DIR is not configured. Cannot determine home for {username}.")
        return None
    # current_app.logger.debug(f"Defaulting user '{username}' home to USER_FILES_BASE_DIR/username: {os.path.join(user_files_base, username)}")
    return os.path.abspath(os.path.join(user_files_base, username))


def get_absolute_path(username_for_home_dir, relative_path=""):
    user_home_abs = get_user_home_dir_abs(username_for_home_dir)
    if not user_home_abs:
        current_app.logger.error(f"Cannot get absolute path: User home for '{username_for_home_dir}' not found.")
        return None
    
    # Normalize and sanitize relative_path
    if relative_path:
        normalized_relative_path = os.path.normpath(relative_path.lstrip('/\\'))
        if normalized_relative_path.startswith('..'+os.sep) or normalized_relative_path == '..':
            current_app.logger.warning(f"Potentially unsafe relative path '{relative_path}' for user {username_for_home_dir}.")
            return None # More strict: return None for unsafe paths

        parts = normalized_relative_path.split(os.sep)
        if len(parts) > 1 and any(part in ('', '.') for part in parts if part != parts[-1]): # Allow last part to be . if single
             current_app.logger.warning(f"Invalid component in relative path '{relative_path}' for user {username_for_home_dir}.")
             return None # More strict

        full_path_abs = os.path.join(user_home_abs, normalized_relative_path)
    else:
        full_path_abs = user_home_abs

    resolved_abs_path = os.path.abspath(full_path_abs)
    user_home_abs_norm = os.path.abspath(user_home_abs) # Normalize for comparison

    if not resolved_abs_path.startswith(user_home_abs_norm):
        current_app.logger.error(f"Path traversal attempt or invalid path construction: Resulting path '{resolved_abs_path}' is outside user '{username_for_home_dir}' home '{user_home_abs_norm}'.")
        return None # More strict
        
    return resolved_abs_path


def get_relative_path_to_home(username_for_home_dir, absolute_path_to_check):
    user_home_abs = get_user_home_dir_abs(username_for_home_dir)
    if not user_home_abs: return None
    
    abs_path_norm = os.path.abspath(absolute_path_to_check)
    user_home_abs_norm = os.path.abspath(user_home_abs) 

    if not abs_path_norm.startswith(user_home_abs_norm): return None
    
    relative_path = os.path.relpath(abs_path_norm, user_home_abs_norm)
    return "" if relative_path == "." else relative_path.replace("\\", "/") 


def get_human_readable_size(size_bytes):
    if size_bytes is None or not isinstance(size_bytes, (int, float)) or size_bytes < 0: return "-" 
    if size_bytes == 0: return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    if size_bytes < 1: # Handle very small non-zero sizes
        return f"{size_bytes:.2f} B"
    i = int(math.floor(math.log(size_bytes, 1024)))
    if i >= len(size_name): i = len(size_name) - 1 # Cap at YB
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def get_display_file_type(item_abs_path, item_name): # item_abs_path might be None if file deleted
    _, ext = os.path.splitext(item_name)
    ext = ext.lower()

    if item_abs_path and os.path.isdir(item_abs_path): return "文件夹"

    # Prioritize specific known extensions for common web/cloud types
    if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.tiff', '.tif']: return "图片"
    if ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv']: return "视频"
    if ext in ['.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a']: return "音频"
    if ext == '.pdf': return "PDF文档"
    if ext in ['.zip', '.rar', '.tar', '.gz', '.7z', '.bz2']: return "压缩包"
    
    text_like_exts = current_app.config.get('TEXT_PREVIEW_EXTENSIONS', []) + \
                     ['.txt', '.md', '.log', '.csv', '.json', '.xml', '.yaml', '.yml', '.ini', '.conf', '.cfg', '.srt', '.vtt']
    if ext in text_like_exts: return "文本文件"

    code_like_exts = current_app.config.get('CODE_EXECUTION_EXTENSIONS', []) + \
                     ['.html', '.css', '.js', '.py', '.c', '.cpp', '.h', '.hpp', '.java', '.sh', '.rb', '.php', '.pl', '.bat', '.cs', '.go', '.rs', '.swift', '.kt']
    if ext in code_like_exts: return "代码文件"


    office_exts = ['.doc', '.docx', '.rtf', '.odt', 
                   '.xls', '.xlsx', '.ods', '.csv', # csv also text
                   '.ppt', '.pptx', '.odp']
    if ext in office_exts: return "Office文档"


    # Fallback to MIME type if available and path exists
    if item_abs_path and os.path.exists(item_abs_path):
        mime_type, _ = mimetypes.guess_type(item_abs_path)
        if mime_type:
            if mime_type.startswith('image/'): return "图片"
            if mime_type.startswith('text/'): return "文本/代码" # Generic for text/*
            if mime_type.startswith('video/'): return "视频"
            if mime_type.startswith('audio/'): return "音频"
            if mime_type == 'application/pdf': return "PDF文档"
            if mime_type in ['application/zip', 'application/x-rar-compressed', 'application/x-7z-compressed', 'application/gzip', 'application/x-tar']: return "压缩包"

    return f"{ext[1:].upper() if ext else '未知'} 文件" if ext else "文件"


def is_file_previewable_as_image(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg']

def is_file_previewable_as_text(filename):
    ext = os.path.splitext(filename)[1].lower()
    text_exts = current_app.config.get('TEXT_PREVIEW_EXTENSIONS', []) + \
                ['.txt', '.md', '.log', '.csv', '.json', '.xml', '.yaml', '.yml', '.ini', '.conf', '.cfg', '.srt', '.vtt']
    code_exts = current_app.config.get('CODE_EXECUTION_EXTENSIONS', []) + \
                ['.html', '.css', '.js', '.py', '.c', '.cpp', '.h', '.hpp', '.java', '.sh', '.rb', '.php', '.pl', '.cs', '.go', '.rs'] # Add more as needed
    return ext in text_exts + code_exts

def is_code_file_for_runner(filename):
    ext = os.path.splitext(filename)[1].lower()
    # Ensure CODE_EXECUTION_EXTENSIONS is loaded from config, provide default if not
    code_runner_exts = current_app.config.get('CODE_EXECUTION_EXTENSIONS', ['.py', '.js', '.sh', '.c', '.cpp', '.java']) # Example default
    return ext in code_runner_exts


def _load_hidden_files_db():
    path = current_app.config.get('HIDDEN_FILES_PATH') # e.g., data/hidden_files.json
    if path and os.path.exists(path):
        try:
            with open(path, 'r') as f: return json.load(f)
        except Exception as e: 
            current_app.logger.error(f"Failed to load hidden files DB from {path}: {e}")
    return {}

def _is_file_hidden_for_user(username_of_viewer, item_abs_path, hidden_files_db):
    # The key in hidden_files_db should be relative to USER_FILES_BASE_DIR
    user_files_base = current_app.config.get('USER_FILES_BASE_DIR')
    if not user_files_base or not item_abs_path.startswith(os.path.abspath(user_files_base)):
        return False # Cannot determine if outside base

    path_relative_to_base = os.path.relpath(item_abs_path, os.path.abspath(user_files_base)).replace("\\", "/")
    user_specific_hidden_list = hidden_files_db.get(username_of_viewer, [])
    return path_relative_to_base in user_specific_hidden_list


# --- Consolidated Share DB Functions ---
def load_shares_db():
    # current_app.logger.debug("--- DEBUG TRACE: load_shares_db CALLED ---")
    db_path = current_app.config.get('SHARES_DB_PATH')
    if not db_path:
        current_app.logger.error("--- FATAL ERROR: SHARES_DB_PATH is not configured!")
        return {}

    data_dir = os.path.dirname(db_path)
    # current_app.logger.debug(f"--- DEBUG TRACE: SHARES_DB_PATH resolved to: {db_path}")
    # current_app.logger.debug(f"--- DEBUG TRACE: Data directory derived as: {data_dir}")

    if not os.path.exists(data_dir):
        # current_app.logger.info(f"--- DEBUG TRACE: Data directory {data_dir} DOES NOT EXIST. Attempting to create.")
        try:
            os.makedirs(data_dir, exist_ok=True)
            # current_app.logger.info(f"--- DEBUG TRACE: Data directory {data_dir} CREATED or already existed.")
        except OSError as e:
            current_app.logger.error(f"--- FATAL ERROR: FAILED to create data directory {data_dir}: {e}", exc_info=True)
            return {}

    if not os.path.exists(db_path):
        # current_app.logger.info(f"--- DEBUG TRACE: Shares DB file {db_path} DOES NOT EXIST. Creating empty DB.")
        try:
            with open(db_path, 'w') as f: json.dump({}, f)
            return {}
        except IOError as e:
            current_app.logger.error(f"--- FATAL ERROR: FAILED to create empty shares DB file {db_path}: {e}", exc_info=True)
            return {}
    
    try:
        with open(db_path, 'r') as f:
            content = f.read().strip()
            if not content: # Handle empty file
                # current_app.logger.info(f"--- DEBUG TRACE: Shares DB file {db_path} is empty. Returning empty DB.")
                return {}
            shared_items = json.loads(content)
        # current_app.logger.debug(f"--- DEBUG TRACE: Shares DB loaded successfully from {db_path}.")
        return shared_items
    except (IOError, json.JSONDecodeError, OSError) as e:
        current_app.logger.error(f"--- FATAL ERROR: FAILED to load or parse shares DB {db_path}: {e}. Returning empty data.", exc_info=True)
        return {}


def save_shares_db(shared_items):
    # current_app.logger.debug("--- DEBUG TRACE: save_shares_db CALLED ---")
    db_path = current_app.config.get('SHARES_DB_PATH')
    if not db_path:
        current_app.logger.error("--- FATAL ERROR (SAVE): SHARES_DB_PATH is not configured!")
        return False
    
    # current_app.logger.debug(f"--- DEBUG TRACE (SAVE): Attempting to save shares to {db_path}")
    # current_app.logger.debug(f"--- DEBUG TRACE (SAVE): Data to be saved (snippet): {str(shared_items)[:500]}")

    try:
        data_dir = os.path.dirname(db_path)
        if not os.path.exists(data_dir): 
            os.makedirs(data_dir, exist_ok=True)
            # current_app.logger.info(f"--- DEBUG TRACE (SAVE): Ensured data directory {data_dir} exists.")

        with open(db_path, 'w') as f:
            json.dump(shared_items, f, indent=4) # indent for readability
        # current_app.logger.info(f"--- DEBUG TRACE (SAVE): Shares successfully saved to {db_path}.")
        return True
    except (IOError, OSError, PermissionError) as e:
        current_app.logger.error(f"--- FATAL ERROR (SAVE): FAILED to write shares DB to {db_path}: {e}", exc_info=True)
        return False


# --- Routes ---

@files_bp.route('/')
@login_required
def list_files_root():
    current_app.logger.debug(f"[ROUTE] list_files_root called by {g.user['username']}")
    # Redirect to the list_files_with_path with an empty subpath
    return redirect(url_for('.list_files_with_path', subpath=''))


# Note: The default for subpath needs to be handled carefully.
# If you want '/files/' to be the root, then `defaults={'subpath': ''}` is good.
# If '/files/somepath' is the pattern, then a separate route for '/files/' might be needed or ensure subpath can be empty.
@files_bp.route('/list/', defaults={'subpath': ''}) # For /list/
@files_bp.route('/list/<path:subpath>')      # For /list/folderA or /list/folderA/file.txt
@login_required
def list_files_with_path(subpath):
    current_user_username = g.user['username']
    current_app.logger.debug(f"[ROUTE] list_files_with_path: User '{current_user_username}', Subpath: '{subpath}'")

    current_path_abs = get_absolute_path(current_user_username, subpath)

    if not current_path_abs or not os.path.exists(current_path_abs) or not os.path.isdir(current_path_abs):
        flash(f"路径 '{subpath if subpath else '/'}' 无效或不存在。", "danger")
        current_app.logger.warning(f"Invalid path access attempt: User '{current_user_username}', Subpath: '{subpath}', Resolved Abs: '{current_path_abs}'")
        return redirect(url_for('.list_files_root')) # Or a specific error page

    # This is the path relative to the current user's home, used for display and breadcrumbs
    current_path_relative_to_home = get_relative_path_to_home(current_user_username, current_path_abs)
    if current_path_relative_to_home is None: 
        flash("无法确定当前相对路径。", "danger") # Should not happen if current_path_abs is valid
        return redirect(url_for('.list_files_root'))

    items_data = []
    hidden_files_db_global = _load_hidden_files_db() 
    shares_db = load_shares_db() 
    user_own_shares_info = shares_db.get(current_user_username, {}) # Shares initiated by the current user

    try:
        for item_name in sorted(os.listdir(current_path_abs), key=lambda s: s.lower()):
            item_abs_path = os.path.join(current_path_abs, item_name)
            
            if _is_file_hidden_for_user(current_user_username, item_abs_path, hidden_files_db_global):
                # current_app.logger.debug(f"Item '{item_name}' in '{current_path_abs}' is hidden for user '{current_user_username}'. Skipping.")
                continue

            # This path is relative to the *current user's home directory*
            # It's used for constructing URLs for actions on items within their own home.
            item_rel_to_current_home = get_relative_path_to_home(current_user_username, item_abs_path)
            if item_rel_to_current_home is None: # Should not happen for items within current_path_abs
                current_app.logger.error(f"Could not get relative path for item '{item_name}' in '{current_path_abs}'. Skipping.")
                continue
            
            is_dir = os.path.isdir(item_abs_path)
            
            # For sharing, the key in shares_db is relative to the *owner's* home.
            # Here, current_user is the owner of the files being listed.
            is_shared_by_me = False
            shared_with_whom_list = []
            if not is_dir and item_rel_to_current_home in user_own_shares_info:
                is_shared_by_me = True
                shared_with_whom_list = user_own_shares_info[item_rel_to_current_home].get('shared_with', [])

            item_stat = None
            try:
                item_stat = os.stat(item_abs_path)
            except OSError:
                current_app.logger.warning(f"Could not stat item '{item_abs_path}'. It might have been deleted. Skipping display or marking as inaccessible.")
                # Optionally, still display it with an error, or skip
                # For now, let's try to get basic info if stat fails but exists, or skip if major issue
                if not os.path.exists(item_abs_path): continue


            item_data = {
                'name': item_name,
                'path_for_url': item_rel_to_current_home, # Used in URLs for actions (download, preview, delete) on user's own files
                'is_dir': is_dir,
                'type_display': get_display_file_type(item_abs_path, item_name),
                'size_readable': get_human_readable_size(item_stat.st_size) if item_stat and not is_dir else "-",
                'last_modified': datetime.fromtimestamp(item_stat.st_mtime).strftime('%Y-%m-%d %H:%M') if item_stat else '-',
                'is_image': is_file_previewable_as_image(item_name) and not is_dir,
                'is_text': is_file_previewable_as_text(item_name) and not is_dir,
                'is_code': is_code_file_for_runner(item_name) and not is_dir,
                
                # Share related info for the template
                'is_shared_by_owner': is_shared_by_me, # True if current user (owner) has shared this item
                'shared_with_users': shared_with_whom_list, # List of users this item is shared with
                'item_path_relative_to_owner_home_for_sharing': item_rel_to_current_home, # Key for share DB ops
                
                'owner_username': current_user_username # For clarity in template, though g.user is also available
            }
            items_data.append(item_data)
            
    except OSError as e:
        current_app.logger.error(f"Error listing files in {current_path_abs} for {current_user_username}: {e}", exc_info=True)
        flash(f"无法列出目录内容: {e}", "danger")

    is_admin_template_context = g.user.get('role') == 'admin'
    all_users_db = current_app.config.get('USERS_DB', {})
    shareable_users = [uname for uname in all_users_db if uname != current_user_username] # Users current user can share with

    # Parent path for "Up" button
    parent_dir_rel = None
    if current_path_relative_to_home: # Not in root of user's home
        parent_dir_rel = os.path.dirname(current_path_relative_to_home)
        if parent_dir_rel == ".": parent_dir_rel = "" # Root of home
        parent_dir_rel = parent_dir_rel.replace("\\", "/")


    return render_template(
        'files/home.html',
        files=items_data,  # Was items_to_render_for_template, assuming items_data is the final list
        current_path_relative=current_path_relative_to_home, # Or subpath if that's what the template expects for display
        # current_path_absolute=current_path_abs, # Often not needed directly in template if relative paths are used
        parent_dir_relative_to_home=parent_dir_rel, # Was parent_dir_rel_to_home
        # breadcrumbs=generate_breadcrumbs(current_path_relative_to_home), # Requires a breadcrumb generation function
        users_for_sharing=shareable_users, # Was users_for_sharing
        is_admin_tpl=is_admin_template_context # Was (g.user.get('role') == 'admin')
    )

# Helper for AJAX responses
def jsonify_status(status, message, status_code=200, **extra_data):
    response_data = {"status": status, "message": message}
    response_data.update(extra_data)
    return jsonify(response_data), status_code


@files_bp.route('/upload', methods=['POST'])
@login_required
def upload_file_route(): # Renamed for clarity
    current_user_username = g.user['username']
    # Path where file should be uploaded, relative to user's home
    current_path_relative_to_home = request.form.get('current_path_relative_for_upload', '') 
    current_app.logger.debug(f"[ROUTE] upload_file: User '{current_user_username}', TargetRelPath: '{current_path_relative_to_home}'")

    target_dir_abs = get_absolute_path(current_user_username, current_path_relative_to_home)

    if not target_dir_abs or not os.path.isdir(target_dir_abs):
        flash("上传目标路径无效。", "danger")
        current_app.logger.warning(f"Upload failed: Invalid target dir. User '{current_user_username}', RelPath '{current_path_relative_to_home}', AbsPath '{target_dir_abs}'")
        return redirect(request.referrer or url_for('.list_files_root')) # Redirect back

    if 'file_to_upload' not in request.files: # Ensure your form input name is 'file_to_upload'
        flash('没有文件被选择。', 'warning')
        return redirect(url_for('.list_files_with_path', subpath=current_path_relative_to_home))
    
    file = request.files['file_to_upload']
    if file.filename == '':
        flash('没有选择文件。', 'warning')
        return redirect(url_for('.list_files_with_path', subpath=current_path_relative_to_home))
    
    if file:
        filename = secure_filename(file.filename)
        if not filename: # secure_filename might return empty if original was unsafe
            flash('无效的文件名。', 'danger')
            return redirect(url_for('.list_files_with_path', subpath=current_path_relative_to_home))
        try:
            file.save(os.path.join(target_dir_abs, filename))
            flash(f"文件 '{filename}' 上传成功。", "success")
            current_app.logger.info(f"File '{filename}' uploaded by '{current_user_username}' to '{target_dir_abs}'.")
        except Exception as e:
            current_app.logger.error(f"File upload failed for {current_user_username} to {target_dir_abs}/{filename}: {e}", exc_info=True)
            flash(f"文件上传失败: {e}", "danger")
            
    return redirect(url_for('.list_files_with_path', subpath=current_path_relative_to_home))


@files_bp.route('/create-folder', methods=['POST'])
@login_required
def create_folder_route(): # Renamed
    current_user_username = g.user['username']
    current_path_relative_to_home = request.form.get('current_path_relative_for_folder', '')
    folder_name_raw = request.form.get('new_folder_name') # Ensure form field name matches
    current_app.logger.debug(f"[ROUTE] create_folder: User '{current_user_username}', ParentRelPath: '{current_path_relative_to_home}', FolderName: '{folder_name_raw}'")


    if not folder_name_raw:
        flash("文件夹名称不能为空。", "warning")
        return redirect(url_for('.list_files_with_path', subpath=current_path_relative_to_home))
    
    folder_name = secure_filename(folder_name_raw)
    if not folder_name: 
        flash("无效的文件夹名称。", "warning")
        return redirect(url_for('.list_files_with_path', subpath=current_path_relative_to_home))

    parent_dir_abs = get_absolute_path(current_user_username, current_path_relative_to_home)
    if not parent_dir_abs or not os.path.isdir(parent_dir_abs):
        flash("目标路径无效。", "danger")
        return redirect(url_for('.list_files_with_path', subpath=current_path_relative_to_home)) # Or root
    
    new_folder_path_abs = os.path.join(parent_dir_abs, folder_name)
    try:
        os.makedirs(new_folder_path_abs)
        flash(f"文件夹 '{folder_name}' 创建成功。", "success")
        current_app.logger.info(f"Folder '{folder_name}' created by '{current_user_username}' in '{parent_dir_abs}'.")
    except FileExistsError:
        flash(f"文件夹 '{folder_name}' 已存在。", "warning")
    except OSError as e:
        current_app.logger.error(f"Create folder failed for {current_user_username} at {new_folder_path_abs}: {e}", exc_info=True)
        flash(f"创建文件夹 '{folder_name}' 失败: {str(e)}", "danger")
        
    return redirect(url_for('.list_files_with_path', subpath=current_path_relative_to_home))


@files_bp.route('/delete-item', methods=['POST']) # Changed to POST and specific route
@login_required
def delete_item_route():
    current_user_username = g.user['username']
    # item_path_relative_to_home is the path of the item to delete, relative to the deleter's home.
    item_path_relative_to_home = request.form.get('item_path_to_delete') 
    # current_view_path_relative is where the user was when they clicked delete, for redirection.
    current_view_path_relative = request.form.get('current_view_path_for_redirect', '') 
    
    current_app.logger.debug(f"[ROUTE] delete_item: User '{current_user_username}', ItemRelPath: '{item_path_relative_to_home}'")

    if not item_path_relative_to_home:
        flash("未指定要删除的项目。", "danger")
        return redirect(url_for('.list_files_with_path', subpath=current_view_path_relative))

    # For deleting, subpath should always be relative to the current user's home.
    # Shared items are not deleted via this route; they are unshared or deleted by owner.
    if item_path_relative_to_home.startswith('shared/'): # Basic check
        flash("无法直接删除共享链接。请在 '与我共享' 中移除或由所有者删除原始文件。", "warning")
        return redirect(url_for('.list_files_with_path', subpath=current_view_path_relative))

    item_to_delete_abs = get_absolute_path(current_user_username, item_path_relative_to_home)

    if not item_to_delete_abs or not os.path.exists(item_to_delete_abs):
        flash("要删除的项目不存在。", "danger")
        return redirect(url_for('.list_files_with_path', subpath=current_view_path_relative))

    user_home_abs = get_user_home_dir_abs(current_user_username)
    if not user_home_abs or item_to_delete_abs == user_home_abs: # Prevent deleting user's own home dir
        flash("无法删除此项目（可能是您的根目录）。", "danger")
        return redirect(url_for('.list_files_with_path', subpath=current_view_path_relative))
    
    try:
        item_name = os.path.basename(item_to_delete_abs)
        is_dir = os.path.isdir(item_to_delete_abs)
        
        if is_dir:
            shutil.rmtree(item_to_delete_abs)
            flash(f"文件夹 '{item_name}' 删除成功。", "success")
        else:
            os.remove(item_to_delete_abs)
            flash(f"文件 '{item_name}' 删除成功。", "success")
        current_app.logger.info(f"{'Folder' if is_dir else 'File'} '{item_name}' at '{item_to_delete_abs}' deleted by '{current_user_username}'.")
        
        # If the deleted item was a file shared by this user, remove its share entries
        if not is_dir:
            shares_db = load_shares_db()
            # item_path_relative_to_home is the key for shares_db for this user
            if current_user_username in shares_db and item_path_relative_to_home in shares_db[current_user_username]:
                del shares_db[current_user_username][item_path_relative_to_home]
                current_app.logger.debug(f"Removed share entry for deleted file: Owner '{current_user_username}', FileRelPath '{item_path_relative_to_home}'.")
                if not shares_db[current_user_username]: # If owner has no more shares
                    del shares_db[current_user_username]
                    current_app.logger.debug(f"Removed owner entry for '{current_user_username}' as no shares left.")
                
                if not save_shares_db(shares_db):
                     current_app.logger.error(f"Failed to save shares_db after removing share entry for deleted file.")

    except OSError as e:
        current_app.logger.error(f"Delete failed for {current_user_username} on {item_to_delete_abs}: {e}", exc_info=True)
        flash(f"删除 '{os.path.basename(item_to_delete_abs)}' 失败: {e}", "danger")
        
    return redirect(url_for('.list_files_with_path', subpath=current_view_path_relative))


# _resolve_file_path_for_action: This function needs to correctly handle
# paths from user's own directory AND paths for shared items.
# A 'shared item path' could look like 'shared/<owner_username>/<path_rel_to_owner_home>'
def _resolve_file_path_for_action(path_from_url, requesting_user_username):
    current_app.logger.debug(f"_resolve_file_path_for_action: PathFromURL='{path_from_url}', RequestingUser='{requesting_user_username}'")
    
    if path_from_url.startswith('shared/'):
        parts = path_from_url.split('/', 2) # shared / owner / path/to/item
        if len(parts) == 3 and parts[0] == 'shared':
            shared_item_owner_username = parts[1]
            original_file_path_rel_to_owner_home = parts[2]
            current_app.logger.debug(f"  Shared item: Owner='{shared_item_owner_username}', RelPath='{original_file_path_rel_to_owner_home}'")

            # Check if requesting user has access to this shared item
            shares_db = load_shares_db()
            owner_shares = shares_db.get(shared_item_owner_username, {})
            share_info = owner_shares.get(original_file_path_rel_to_owner_home, {})
            
            allowed_to_access_share = False
            if requesting_user_username == shared_item_owner_username: # Owner can always access their own files via shared links
                allowed_to_access_share = True
            elif requesting_user_username in share_info.get('shared_with', []):
                allowed_to_access_share = True

            if not allowed_to_access_share:
                current_app.logger.warning(f"  Access DENIED: User '{requesting_user_username}' not in shared_with list for '{path_from_url}'.")
                return None, "您无权访问此共享文件。", None

            # Get absolute path to the original file in owner's storage
            file_abs = get_absolute_path(shared_item_owner_username, original_file_path_rel_to_owner_home)
            if not file_abs or not os.path.exists(file_abs): 
                 current_app.logger.warning(f"  Shared file NOT FOUND: Original file for '{path_from_url}' at '{file_abs}' does not exist.")
                 return None, f"共享文件 '{share_info.get('display_name', os.path.basename(original_file_path_rel_to_owner_home))}' 不存在或已被所有者删除。", None
            
            filename_for_action = share_info.get('display_name', os.path.basename(original_file_path_rel_to_owner_home))
            current_app.logger.debug(f"  Shared item RESOLVED: AbsPath='{file_abs}', DisplayName='{filename_for_action}'")
            return file_abs, None, filename_for_action
        else:
            current_app.logger.warning(f"  Invalid shared path format: '{path_from_url}'")
            return None, "共享文件路径格式错误。", None
    else: 
        # Path is relative to the requesting_user_username's home
        current_app.logger.debug(f"  Own item: User='{requesting_user_username}', RelPath='{path_from_url}'")
        file_abs = get_absolute_path(requesting_user_username, path_from_url)
        if not file_abs or not os.path.exists(file_abs): 
            current_app.logger.warning(f"  Own file NOT FOUND: Path '{path_from_url}' for user '{requesting_user_username}' at '{file_abs}' does not exist.")
            return None, "文件路径无效或文件不存在。", None
        
        filename_for_action = os.path.basename(path_from_url) # Or derive from file_abs if path_from_url can be '..'
        current_app.logger.debug(f"  Own item RESOLVED: AbsPath='{file_abs}', DisplayName='{filename_for_action}'")
        return file_abs, None, filename_for_action


@files_bp.route('/download/<path:path_from_url>') # path_from_url can be direct or shared path
@login_required
def download_file_route(path_from_url): # Renamed
    current_user_username = g.user['username']
    current_app.logger.debug(f"[ROUTE] download_file: User '{current_user_username}', PathFromURL: '{path_from_url}'")
    
    file_to_send_abs, error_msg, filename_for_download = _resolve_file_path_for_action(path_from_url, current_user_username)

    if error_msg:
        flash(error_msg, "danger")
        return redirect(request.referrer or url_for('.list_files_root')) # Sensible fallback
    
    if os.path.isdir(file_to_send_abs): 
        flash("无法下载文件夹。", "danger")
        # Determine redirect based on path type
        if path_from_url.startswith('shared/'):
            return redirect(url_for('.shared_with_me_route'))
        else:
            return redirect(url_for('.list_files_with_path', subpath=os.path.dirname(path_from_url) or ''))
    try:
        # Ensure filename_for_download is safe if it comes from user input or complex logic
        safe_download_name = secure_filename(filename_for_download) if filename_for_download else "downloaded_file"
        return send_file(file_to_send_abs, as_attachment=True, download_name=safe_download_name)
    except Exception as e:
        current_app.logger.error(f"Error sending file {file_to_send_abs} for download: {e}", exc_info=True)
        flash(f"下载文件时出错: {e}", "danger")
        return redirect(request.referrer or url_for('.list_files_root'))


@files_bp.route('/preview/text/<path:path_from_url>')
@login_required
def preview_text_file_route(path_from_url): # Renamed
    current_user_username = g.user['username']
    current_app.logger.debug(f"[ROUTE] preview_text_file: User '{current_user_username}', PathFromURL: '{path_from_url}'")

    file_to_preview_abs, error_msg, filename_for_preview = _resolve_file_path_for_action(path_from_url, current_user_username)

    if error_msg:
        flash(error_msg, "danger")
        return redirect(request.referrer or url_for('.list_files_root'))
    
    if os.path.isdir(file_to_preview_abs):
        flash("无法预览文件夹。", "danger")
        if path_from_url.startswith('shared/'): return redirect(url_for('.shared_with_me_route'))
        else: return redirect(url_for('.list_files_with_path', subpath=os.path.dirname(path_from_url) or ''))

    if not is_file_previewable_as_text(filename_for_preview):
        flash(f"文件 '{filename_for_preview}' 类型不支持文本预览。", "info")
        if path_from_url.startswith('shared/'): return redirect(url_for('.shared_with_me_route'))
        else: return redirect(url_for('.list_files_with_path', subpath=os.path.dirname(path_from_url) or ''))
        
    try:
        # Try common encodings
        content = None
        encodings_to_try = ['utf-8', 'gbk', 'latin-1'] # Add more if needed
        for enc in encodings_to_try:
            try:
                with open(file_to_preview_abs, 'r', encoding=enc) as f: 
                    content = f.read()
                current_app.logger.debug(f"Successfully read '{file_to_preview_abs}' with encoding '{enc}'.")
                break 
            except UnicodeDecodeError:
                current_app.logger.debug(f"Failed to decode '{file_to_preview_abs}' with encoding '{enc}'.")
                continue
        
        if content is None: # If all failed
            current_app.logger.warning(f"Could not decode file '{file_to_preview_abs}' with any tried encodings.")
            flash(f"无法解码文件 '{filename_for_preview}'。尝试了 {', '.join(encodings_to_try)} 编码。", "warning")
            # Fallback: read as bytes and replace errors (might not be pretty)
            # with open(file_to_preview_abs, 'r', errors='replace') as f: content = f.read()
            if path_from_url.startswith('shared/'): return redirect(url_for('.shared_with_me_route'))
            else: return redirect(url_for('.list_files_with_path', subpath=os.path.dirname(path_from_url) or ''))

        # Pass the original path_from_url to template if needed for "Edit" or other actions
        return render_template('preview_text.html', content=content, filename=filename_for_preview, original_path_for_actions=path_from_url)
    except Exception as e:
        current_app.logger.error(f"Error previewing text file {file_to_preview_abs}: {e}", exc_info=True)
        flash(f"预览文件时出错: {e}", "danger")
        return redirect(request.referrer or url_for('.list_files_root'))


@files_bp.route('/preview/image/<path:path_from_url>')
@login_required
def preview_image_file_route(path_from_url): # Renamed
    current_user_username = g.user['username']
    current_app.logger.debug(f"[ROUTE] preview_image_file: User '{current_user_username}', PathFromURL: '{path_from_url}'")

    file_to_preview_abs, error_msg, filename_for_preview = _resolve_file_path_for_action(path_from_url, current_user_username)

    if error_msg:
        flash(error_msg, "danger")
        return redirect(request.referrer or url_for('.list_files_root'))
    
    if os.path.isdir(file_to_preview_abs):
        flash("无法预览文件夹。", "danger")
        if path_from_url.startswith('shared/'): return redirect(url_for('.shared_with_me_route'))
        else: return redirect(url_for('.list_files_with_path', subpath=os.path.dirname(path_from_url) or ''))

    if not is_file_previewable_as_image(filename_for_preview): # filename_for_preview from _resolve...
        flash(f"文件 '{filename_for_preview}' 类型不支持图片预览。", "info")
        if path_from_url.startswith('shared/'): return redirect(url_for('.shared_with_me_route'))
        else: return redirect(url_for('.list_files_with_path', subpath=os.path.dirname(path_from_url) or ''))
        
    try:
        return send_file(file_to_preview_abs) 
    except Exception as e:
        current_app.logger.error(f"Error previewing image file {file_to_preview_abs}: {e}", exc_info=True)
        flash(f"预览图片时出错: {e}", "danger")
        return redirect(request.referrer or url_for('.list_files_root'))


# --- Share Management Routes ---

@files_bp.route('/share-actions/share-file', methods=['POST'])
@login_required
def share_file_action(): 
    owner_username = g.user['username'] # The person initiating the share is the owner
    
    # This is the path of the file *relative to the owner's home directory*
    file_path_rel_to_owner_home = request.form.get('file_path_relative_to_owner_home_for_sharing') 
    share_with_user = request.form.get('share_with_selected_username') # User to share with
    # Path where the owner was viewing their files, for redirecting back
    owner_current_view_path = request.form.get('owner_current_view_path_for_redirect', '')

    current_app.logger.debug(f"[ROUTE] share_file_action: Owner='{owner_username}', FileRelPath='{file_path_rel_to_owner_home}', ShareWith='{share_with_user}', RedirectPath='{owner_current_view_path}'")

    if not file_path_rel_to_owner_home:
        flash("未指定要分享的文件路径。", "danger")
        return redirect(url_for('.list_files_with_path', subpath=owner_current_view_path))
    if not share_with_user:
        flash("未选择要分享的用户。", "danger")
        return redirect(url_for('.list_files_with_path', subpath=owner_current_view_path))
    
    users_db = current_app.config.get('USERS_DB', {})
    if share_with_user not in users_db:
        flash(f"用户 '{share_with_user}' 不存在。", "danger")
        return redirect(url_for('.list_files_with_path', subpath=owner_current_view_path))
    if share_with_user == owner_username:
        flash("不能将文件分享给自己。", "info")
        return redirect(url_for('.list_files_with_path', subpath=owner_current_view_path))


    # Verify the file exists in the owner's directory
    file_to_share_abs = get_absolute_path(owner_username, file_path_rel_to_owner_home)
    if not file_to_share_abs or not os.path.exists(file_to_share_abs) or os.path.isdir(file_to_share_abs): 
        flash("要分享的项目无效、不存在或是文件夹（目前仅支持文件分享）。", "danger")
        current_app.logger.warning(f"Share attempt failed: Item '{file_path_rel_to_owner_home}' for owner '{owner_username}' not found or is a directory.")
        return redirect(url_for('.list_files_with_path', subpath=owner_current_view_path))
    
    # file_path_rel_to_owner_home is the key in the shares_db
    file_key_for_db = file_path_rel_to_owner_home 

    shares_db = load_shares_db()
    # Ensure owner's entry exists
    if owner_username not in shares_db:
        shares_db[owner_username] = {}
    
    owner_specific_shares = shares_db[owner_username]
    
    # Get existing share info for this file, or create new if first time sharing this file
    current_file_share_info = owner_specific_shares.get(file_key_for_db)
    if not current_file_share_info:
        current_file_share_info = {
            'shared_with': [], 
            'display_name': os.path.basename(file_key_for_db), # Default display name
            'shared_on': datetime.utcnow().isoformat() # UTC for consistency
        }
        current_app.logger.debug(f"  New share entry created for '{file_key_for_db}' by '{owner_username}'.")
    
    if share_with_user not in current_file_share_info['shared_with']:
        current_file_share_info['shared_with'].append(share_with_user)
        current_file_share_info['last_modified_share'] = datetime.utcnow().isoformat() # Track when share list was last changed
        action_msg = "已成功分享给用户"
        current_app.logger.info(f"  User '{share_with_user}' added to share list for '{file_key_for_db}'.")
    else:
        flash(f"文件 '{current_file_share_info['display_name']}' 已分享给用户 '{share_with_user}'。", "info")
        current_app.logger.info(f"  File '{file_key_for_db}' already shared with '{share_with_user}'. No change.")
        return redirect(url_for('.list_files_with_path', subpath=owner_current_view_path))

    # Update the database
    owner_specific_shares[file_key_for_db] = current_file_share_info
    # shares_db[owner_username] = owner_specific_shares # This line is redundant if owner_specific_shares is a direct reference
    
    current_app.logger.debug(f"  Preparing to save shares_db. Owner: '{owner_username}', File: '{file_key_for_db}', NewInfo: {current_file_share_info}")
    if save_shares_db(shares_db):
        flash(f"文件 '{current_file_share_info['display_name']}' {action_msg} '{share_with_user}'。", "success")
    else:
        flash("保存分享设置失败。", "danger")
        current_app.logger.error(f"Failed to save shares_db for share operation: Owner '{owner_username}', File '{file_key_for_db}'.")
    
    return redirect(url_for('.list_files_with_path', subpath=owner_current_view_path))


@files_bp.route('/share-actions/unshare-file', methods=['POST']) # AJAX endpoint
@login_required
def unshare_file_action():
    owner_username = g.user['username'] # Only owner can unshare their files
    
    # Path of the file relative to the owner's home
    file_path_rel_to_owner_home = request.form.get('file_path_to_unshare_rel_to_owner_home')
    unshare_for_user = request.form.get('username_to_unshare_from') # User whose access to revoke

    current_app.logger.debug(f"[ROUTE AJAX] unshare_file_action: Owner='{owner_username}', FileRelPath='{file_path_rel_to_owner_home}', UnshareForUser='{unshare_for_user}'")

    if not file_path_rel_to_owner_home or not unshare_for_user:
        return jsonify_status("error", "缺少必要参数 (文件路径或用户名)。", 400)

    shares_db = load_shares_db()
    if owner_username not in shares_db or \
       file_path_rel_to_owner_home not in shares_db[owner_username]:
        current_app.logger.warning(f"  Unshare failed: File '{file_path_rel_to_owner_home}' not found in shares for owner '{owner_username}'.")
        return jsonify_status("error", "文件分享记录不存在。", 404)

    file_share_info = shares_db[owner_username][file_path_rel_to_owner_home]
    
    if unshare_for_user not in file_share_info.get('shared_with', []):
        current_app.logger.info(f"  Unshare info: User '{unshare_for_user}' was not in shared_with list for '{file_path_rel_to_owner_home}'. No action taken.")
        return jsonify_status("info", f"用户 '{unshare_for_user}' 未曾被分享此文件。", 200) # Or success if idempotent

    file_share_info['shared_with'].remove(unshare_for_user)
    file_share_info['last_modified_share'] = datetime.utcnow().isoformat()
    current_app.logger.info(f"  User '{unshare_for_user}' removed from shared_with list for '{file_path_rel_to_owner_home}'.")

    # If shared_with list becomes empty, we can choose to remove the file's entire share entry
    if not file_share_info['shared_with']:
        del shares_db[owner_username][file_path_rel_to_owner_home]
        current_app.logger.info(f"  Share entry for '{file_path_rel_to_owner_home}' removed as shared_with list is empty.")
        # If the owner now has no shares at all, remove the owner's entry
        if not shares_db[owner_username]:
            del shares_db[owner_username]
            current_app.logger.info(f"  Owner entry for '{owner_username}' removed as no shares left.")
    
    if save_shares_db(shares_db):
        display_name = file_share_info.get('display_name', os.path.basename(file_path_rel_to_owner_home))
        return jsonify_status("success", f"已取消文件 '{display_name}' 对用户 '{unshare_for_user}' 的分享。")
    else:
        current_app.logger.error(f"Failed to save shares_db after unshare operation for '{file_path_rel_to_owner_home}'.")
        return jsonify_status("error", "保存分享设置失败，请检查服务器日志。", 500)


@files_bp.route('/shared-with-me')
@login_required
def shared_with_me_route(): 
    requesting_user_username = g.user['username']
    shared_items_for_template = []
    shares_db = load_shares_db()

    current_app.logger.debug(f"[ROUTE] shared_with_me_route: User: {requesting_user_username}")
    # current_app.logger.debug(f"  All Shares DB (snippet): {str(shares_db)[:500]}")

    for owner_username, owner_files_shared_out in shares_db.items():
        # Users do not see items they shared with themselves in "Shared with me" list (typically)
        # However, if an admin shares with a user, that would appear.
        # If owner_username == requesting_user_username: continue 
        
        for item_path_rel_to_owner_home, share_info in owner_files_shared_out.items():
            if requesting_user_username in share_info.get('shared_with', []):
                current_app.logger.debug(f"  Match: Item '{owner_username}/{item_path_rel_to_owner_home}' is shared with '{requesting_user_username}'.")

                # Get abs path to check existence and get metadata
                original_file_abs_path = get_absolute_path(owner_username, item_path_rel_to_owner_home)
                
                file_exists = original_file_abs_path and os.path.exists(original_file_abs_path)
                is_dir_shared = file_exists and os.path.isdir(original_file_abs_path)
                
                display_name = share_info.get('display_name', os.path.basename(item_path_rel_to_owner_home))
                
                # This path is used in URLs for actions (download, preview) on shared items.
                # It encodes the owner and original relative path.
                shared_item_path_for_url = f"shared/{owner_username}/{item_path_rel_to_owner_home}".replace("\\","/")

                item_stat = None
                if file_exists:
                    try: item_stat = os.stat(original_file_abs_path)
                    except OSError: pass # File might have been deleted between exists check and stat

                shared_on_str = share_info.get('shared_on')
                shared_on_display = '-'
                if shared_on_str:
                    try: shared_on_display = datetime.fromisoformat(shared_on_str.replace("Z", "+00:00")).strftime('%Y-%m-%d %H:%M') # Handle Z for UTC
                    except ValueError: current_app.logger.warning(f"Could not parse shared_on date: {shared_on_str}")


                item_entry = {
                    'name': display_name, 
                    'path_for_url': shared_item_path_for_url, # Used by download/preview routes
                    'is_dir': is_dir_shared,
                    'type_display': get_display_file_type(original_file_abs_path if file_exists else None, display_name),
                    'size_readable': get_human_readable_size(item_stat.st_size) if file_exists and item_stat and not is_dir_shared else ("-" if file_exists else "N/A (已删除)"),
                    'last_modified': datetime.fromtimestamp(item_stat.st_mtime).strftime('%Y-%m-%d %H:%M') if file_exists and item_stat else ('-' if file_exists else "N/A"),
                    'shared_on_display': shared_on_display,
                    'is_image': is_file_previewable_as_image(display_name) and not is_dir_shared and file_exists,
                    'is_text': is_file_previewable_as_text(display_name) and not is_dir_shared and file_exists,
                    'is_code': False, # Shared items are generally not directly runnable by recipient unless special setup
                    'owner_username': owner_username, 
                    'is_shared_item': True, # For template logic
                    'file_exists_for_recipient': file_exists # Useful for greying out or showing warning
                }
                shared_items_for_template.append(item_entry)
            # else:
            #      current_app.logger.debug(f"  No Match: {owner_username}/{item_path_rel_to_owner_home} (Shared with: {share_info.get('shared_with')}) is NOT for {requesting_user_username}")

    shared_items_for_template.sort(key=lambda x: (x['owner_username'], x['name'].lower()))

    return render_template(
        'shared_list.html', 
        items=shared_items_for_template,
        title="与我共享的文件",
        # current_path_relative="与我共享", # For breadcrumb consistency if base.html expects it
        is_admin_tpl=(g.user.get('role') == 'admin'),
        username_context=g.user['username']
    )
