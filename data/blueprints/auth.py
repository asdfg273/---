from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from config import USERS_DB

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_data = USERS_DB.get(username)
        if user_data and user_data['password'] == password:
            session['username'] = username
            session['role'] = user_data['role']
            flash('登录成功!', 'success')
            return redirect(url_for('files.list_files_root'))
        else:
            flash('用户名或密码错误', 'danger')
    if 'username' in session: # 如果已登录，直接跳转
        return redirect(url_for('files.list_files_root'))
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    flash('已注销', 'info')
    return redirect(url_for('auth.login'))
