from flask import Blueprint, render_template, request, session, flash, current_app, g, redirect, url_for
import subprocess
import os
import tempfile
from decorators import admin_required, login_required # 确保这些装饰器在 decorators.py 中定义正确

code_runner_bp = Blueprint('code_runner', __name__, template_folder='../templates/code_runner') # 确保模板路径正确

# 辅助函数：获取当前管理员用户的家目录 (如果需要从其文件区加载代码)
def get_admin_user_home_for_code_loading():
    if not (hasattr(g, 'user') and g.user and g.user.get('role') == 'admin'):
        current_app.logger.warning("get_admin_user_home_for_code_loading: No admin user in g.")
        return None

    admin_username = g.user.get('username')
    user_files_base_dir = current_app.config.get('USER_FILES_BASE_DIR')

    if not admin_username or not user_files_base_dir:
        current_app.logger.warning("get_admin_user_home_for_code_loading: Username or USER_FILES_BASE_DIR missing.")
        return None

    # (4) 这里的 admin_username 需要和 USERS_DB 中 home_dir 的子目录名一致
    admin_home_abs = os.path.abspath(os.path.join(user_files_base_dir, admin_username))
    
    if not os.path.isdir(admin_home_abs):
        current_app.logger.warning(f"Admin home directory not found or not a directory: {admin_home_abs}")
        return None
        
    return admin_home_abs


@code_runner_bp.route('/', methods=['GET', 'POST'])
@login_required
@admin_required
def run_code():
    output = None
    error = None
    code_content = request.form.get('code', '')
    language = request.form.get('language', 'python')

    file_to_load_rel_path = request.args.get('load_file')
    if file_to_load_rel_path and request.method == 'GET':
        admin_home_abs = get_admin_user_home_for_code_loading()
        if admin_home_abs:
            absolute_file_path = os.path.abspath(os.path.join(admin_home_abs, file_to_load_rel_path))
            
            # (5) 路径安全检查改进
            # if absolute_file_path.startswith(admin_home_abs + os.sep) and os.path.isfile(absolute_file_path): # 更严格
            # 更简洁且通常足够安全的做法是，确认 admin_home_abs 是 absolute_file_path 的前缀
            if os.path.commonpath([admin_home_abs, absolute_file_path]) == admin_home_abs and os.path.isfile(absolute_file_path):
                try:
                    with open(absolute_file_path, 'r', encoding='utf-8') as f:
                        code_content = f.read()
                    flash(f"已加载文件: {os.path.basename(file_to_load_rel_path)}", "info")
                    _, ext = os.path.splitext(file_to_load_rel_path)
                    if ext == '.py':
                        language = 'python'
                    elif ext in ['.c', '.cpp']:
                        language = 'cpp'
                except Exception as e:
                    flash(f"加载文件失败: {e}", "danger")
                    code_content = f"# 无法加载文件: {file_to_load_rel_path}\n# 错误: {e}"
            else:
                flash("无法加载指定文件或文件不存在于您的主目录中。", "warning")
                code_content = f"# 无法加载文件: {file_to_load_rel_path}"
        else:
            flash("无法确定管理员主目录以加载文件。", "danger")
            # 不重定向，允许页面显示，但 code_content 可能为空或错误信息

    if request.method == 'POST':
        # code_content 和 language 已经从表单获取

        if not code_content.strip():
            flash("请输入要运行的代码。", "warning")
        else:
            # 使用 Firejail 进行沙箱隔离
            # tmp_private_dir 将作为沙箱的根目录和工作目录
            with tempfile.TemporaryDirectory(prefix="code_run_") as tmp_private_dir:
                execution_cwd = tmp_private_dir # 所有执行都在这个临时目录内进行

                if language == 'python':
                    temp_script_name = "script.py" # 在沙箱内的脚本名
                    temp_script_path_in_sandbox = os.path.join(tmp_private_dir, temp_script_name)
                    with open(temp_script_path_in_sandbox, 'w', encoding='utf-8') as f:
                        f.write(code_content)

                    firejail_cmd = [
                        'firejail', '--quiet', '--seccomp', '--net=none',
                        f'--private={tmp_private_dir}', # 使用临时目录作为私有目录
                        'python3', temp_script_name    # 在沙箱内执行脚本
                    ]
                    
                    try:
                        process = subprocess.run(
                            firejail_cmd,
                            capture_output=True, text=True, timeout=15, cwd=execution_cwd # cwd 确保在沙箱目录内执行
                        )
                        output = process.stdout
                        if process.stderr:
                            error = process.stderr
                    except subprocess.TimeoutExpired:
                        error = "代码执行超时！(15秒)"
                    except FileNotFoundError:
                        error = "执行错误: Firejail或Python3未安装或不在PATH中。"
                    except Exception as e:
                        error = f"执行时发生未知错误: {str(e)}"

                elif language == 'cpp':
                    source_filename = "program.cpp"
                    executable_filename = "program.exe" # 在沙箱内的可执行文件名
                    
                    temp_source_path = os.path.join(tmp_private_dir, source_filename)
                    # 编译后的可执行文件也会在 tmp_private_dir 中，因为编译命令指定了输出路径
                    # temp_executable_path_in_sandbox = os.path.join(tmp_private_dir, executable_filename) # 编译命令会创建这个

                    with open(temp_source_path, 'w', encoding='utf-8') as f:
                        f.write(code_content)

                    # 编译命令 (g++ 应该在系统PATH中)
                    # 输出文件直接放到沙箱目录中
                    compile_cmd = [
                        'g++', source_filename, '-o', executable_filename, # 输出到当前目录(即沙箱目录)
                        '-std=c++17', '-Wall', '-O2'
                    ]
                    
                    # 注意：编译步骤本身不在Firejail内。更安全的是用Firejail包装编译。
                    # 例如: ['firejail', '--profile=compiler', 'g++', ...]
                    # 为了简化，这里编译在外部进行，但工作目录是 tmp_private_dir
                    compile_process = subprocess.run(
                        compile_cmd,
                        capture_output=True, text=True, timeout=20, cwd=execution_cwd # 编译在沙箱目录中进行
                    )

                    if compile_process.returncode != 0:
                        error = "编译失败:\n" + compile_process.stderr + compile_process.stdout
                    else: # 编译成功
                        if compile_process.stdout: # 编译可能有警告
                            output = "编译输出 (警告等):\n" + compile_process.stdout + "\n\n"
                        
                        firejail_cmd = [
                            'firejail', '--quiet', '--seccomp', '--net=none',
                            f'--private={tmp_private_dir}',
                            f'./{executable_filename}' # 在沙箱内执行编译好的程序
                        ]
                        
                        try:
                            process = subprocess.run(
                                firejail_cmd,
                                capture_output=True, text=True, timeout=10, cwd=execution_cwd
                            )
                            output = (output or "") + "执行输出:\n" + process.stdout
                            if process.stderr:
                                error = (error or "") + "\n执行错误 (stderr):\n" + process.stderr
                        except subprocess.TimeoutExpired:
                            error = (error or "") + "\n代码执行超时！(10秒)"
                        except FileNotFoundError:
                            error = (error or "") + "\n执行错误: Firejail未安装或不在PATH中。"
                        except Exception as e:
                            error = (error or "") + f"\n执行时发生未知错误: {str(e)}"
                else:
                    error = f"不支持的语言: {language}"

    # 确保模板能接收到这些变量
    # 模板应命名为 templates/code_runner/code_runner.html (根据 Blueprint 定义)
    return render_template('code_runner.html',
                           code_content=code_content,
                           output=output,
                           error=error,
                           current_language=language)  # 当前选择的语言

# 以下是之前重复定义的路由，我注释掉了，因为上面的 run_code 已经处理了 GET 和 POST
# @code_runner_bp.route('/')
# @admin_required 
# def code_runner_page():
#     return render_template('code_runner/code_runner.html') # 假设模板名一致

