#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GTO 许可证管理系统 - PostgreSQL 版本
Dashboard + API + PostgreSQL
"""

from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session
from datetime import datetime, timezone, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import os

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'gto-license-super-secret-key-2024-xyz')

# 管理员密码
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'SW1024sw..')

# PostgreSQL 数据库 URL
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    raise Exception("❌ DATABASE_URL 环境变量未设置！请在 Railway 添加 PostgreSQL 数据库")

def get_db():
    """获取数据库连接"""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    """初始化数据库"""
    db = get_db()
    cursor = db.cursor()
    
    # 创建许可证表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS licenses (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            ggid VARCHAR(100),
            mac_address VARCHAR(100),
            expiry_date TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            notes TEXT
        )
    ''')
    
    # 创建日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id SERIAL PRIMARY KEY,
            action VARCHAR(255) NOT NULL,
            target_email VARCHAR(255),
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    db.commit()
    db.close()
    print('✅ 数据库初始化完成')

def log_action(action, target_email=None, details=None):
    """记录管理员操作"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO admin_logs (action, target_email, details)
            VALUES (%s, %s, %s)
        ''', (action, target_email, details))
        db.commit()
        db.close()
        print(f'[LOG] {action}: {target_email} - {details}')
    except Exception as e:
        print(f'[LOG ERROR] {e}')

# HTML 模板（包含登录和管理界面）
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GTO 许可证管理系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }
        .logout-btn {
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(255,255,255,0.2);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 1em;
        }
        .logout-btn:hover { background: rgba(255,255,255,0.3); }
        .card {
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 30px;
        }
        .card h2 {
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.8em;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 600;
        }
        .form-group input, .form-group select {
            width: 100%;
            padding: 12px;
            border: 2px solid #e1e8ed;
            border-radius: 8px;
            font-size: 1em;
        }
        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 14px 30px;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
            font-weight: 600;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }
        .action-btn {
            padding: 8px 16px;
            margin: 0 5px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9em;
        }
        .action-btn.extend { background: #28a745; color: white; }
        .action-btn.extend:hover { background: #218838; }
        .action-btn.delete { background: #dc3545; color: white; }
        .action-btn.delete:hover { background: #c82333; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        table th, table td {
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid #e1e8ed;
        }
        table th {
            background: #f7f9fc;
            color: #667eea;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85em;
        }
        table tr:hover { background: #f7f9fc; }
        .status {
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
        }
        .status.valid { background: #d4edda; color: #155724; }
        .status.expired { background: #f8d7da; color: #721c24; }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .stat-card .number {
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
        }
        .stat-card .label { color: #666; font-size: 0.9em; }
        .alert {
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: none;
        }
        .alert.success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    </style>
</head>
<body>
    <div class="container">
        <button class="logout-btn" onclick="logout()">登出</button>
        
        <div class="header">
            <h1>🔐 GTO 许可证管理系统</h1>
            <p>License Management Dashboard - PostgreSQL</p>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="number">{{ stats.total }}</div>
                <div class="label">总用户数</div>
            </div>
            <div class="stat-card">
                <div class="number">{{ stats.valid }}</div>
                <div class="label">有效许可证</div>
            </div>
            <div class="stat-card">
                <div class="number">{{ stats.expired }}</div>
                <div class="label">已过期</div>
            </div>
        </div>
        
        <div class="card">
            <h2>➕ 添加新用户</h2>
            <div id="alertBox" class="alert"></div>
            <form id="addUserForm">
                <div class="form-group">
                    <label for="email">📧 邮箱</label>
                    <input type="email" id="email" name="email" required placeholder="user@example.com">
                </div>
                <div class="form-group">
                    <label for="ggid">🆔 GG ID（可选）</label>
                    <input type="text" id="ggid" name="ggid" placeholder="GG123456">
                </div>
                <div class="form-group">
                    <label for="duration">⏰ 有效期</label>
                    <select id="duration" name="duration">
                        <option value="0.167">4小时</option>
                        <option value="1">1天</option>
                        <option value="7">7天</option>
                        <option value="30" selected>30天（1个月）</option>
                        <option value="90">90天（3个月）</option>
                        <option value="180">180天（6个月）</option>
                        <option value="365">365天（1年）</option>
                        <option value="3650">3650天（10年）</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="notes">📝 备注（可选）</label>
                    <input type="text" id="notes" name="notes" placeholder="备注信息">
                </div>
                <button type="submit" class="btn">添加用户</button>
            </form>
        </div>
        
        <div class="card">
            <h2>📋 用户列表</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>邮箱</th>
                        <th>GG ID</th>
                        <th>MAC 地址</th>
                        <th>到期时间</th>
                        <th>状态</th>
                        <th>创建时间</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td>{{ user.id }}</td>
                        <td>{{ user.email }}</td>
                        <td>{{ user.ggid or '-' }}</td>
                        <td>{{ user.mac_address or '<span style="color:#999;">未绑定</span>' }}</td>
                        <td>{{ user.expiry_date }}</td>
                        <td>
                            {% if user.status == 'valid' %}
                            <span class="status valid">有效</span>
                            {% else %}
                            <span class="status expired">已过期</span>
                            {% endif %}
                        </td>
                        <td>{{ user.created_at }}</td>
                        <td>
                            <button class="action-btn extend" onclick="extendLicense({{ user.id }}, '{{ user.email }}')">延期</button>
                            <button class="action-btn extend" onclick="updateExpiry({{ user.id }}, '{{ user.email }}')">修改</button>
                            {% if user.mac_address %}
                            <button class="action-btn extend" onclick="resetMac({{ user.id }}, '{{ user.email }}')">重置MAC</button>
                            {% endif %}
                            <button class="action-btn delete" onclick="deleteUser({{ user.id }}, '{{ user.email }}')">删除</button>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="card">
            <h2>📜 操作日志（最近20条）</h2>
            <table>
                <thead>
                    <tr>
                        <th>时间</th>
                        <th>操作</th>
                        <th>目标邮箱</th>
                        <th>详情</th>
                    </tr>
                </thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                        <td>{{ log.timestamp }}</td>
                        <td>{{ log.action }}</td>
                        <td>{{ log.target_email or '-' }}</td>
                        <td>{{ log.details or '-' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        function showAlert(message, type) {
            const alertBox = document.getElementById('alertBox');
            alertBox.textContent = message;
            alertBox.className = 'alert ' + type;
            alertBox.style.display = 'block';
            setTimeout(() => alertBox.style.display = 'none', 5000);
        }
        
        document.getElementById('addUserForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            try {
                const response = await fetch('/api/add_user', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const result = await response.json();
                
                if (result.success) {
                    showAlert('✅ 用户添加成功！', 'success');
                    setTimeout(() => location.reload(), 1500);
                } else {
                    showAlert('❌ ' + result.error, 'error');
                }
            } catch (err) {
                showAlert('❌ 网络错误：' + err.message, 'error');
            }
        });
        
        async function extendLicense(id, email) {
            const days = prompt(`延长许可证有效期（天数）\\n用户：${email}`, '30');
            if (!days) return;
            
            try {
                const response = await fetch('/api/extend_license', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id, days: parseFloat(days) })
                });
                const result = await response.json();
                
                if (result.success) {
                    alert('✅ 许可证已延长！');
                    location.reload();
                } else {
                    alert('❌ ' + result.error);
                }
            } catch (err) {
                alert('❌ 网络错误：' + err.message);
            }
        }
        
        async function updateExpiry(id, email) {
            const datetime = prompt(`设置新的到期时间\\n用户：${email}\\n\\n格式：YYYY-MM-DD HH:MM:SS`, '');
            if (!datetime) return;
            
            try {
                const response = await fetch('/api/update_expiry', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id, datetime })
                });
                const result = await response.json();
                
                if (result.success) {
                    alert('✅ 到期时间已更新！');
                    location.reload();
                } else {
                    alert('❌ ' + result.error);
                }
            } catch (err) {
                alert('❌ 网络错误：' + err.message);
            }
        }
        
        async function resetMac(id, email) {
            if (!confirm(`确定要重置 MAC 地址吗？\\n用户：${email}\\n\\n重置后该用户可以在新设备上登录`)) return;
            
            try {
                const response = await fetch('/api/reset_mac', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id })
                });
                const result = await response.json();
                
                if (result.success) {
                    alert('✅ MAC 地址已重置！');
                    location.reload();
                } else {
                    alert('❌ ' + result.error);
                }
            } catch (err) {
                alert('❌ 网络错误：' + err.message);
            }
        }
        
        async function deleteUser(id, email) {
            if (!confirm(`确定要删除用户吗？\\n${email}`)) return;
            
            try {
                const response = await fetch('/api/delete_user', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id })
                });
                const result = await response.json();
                
                if (result.success) {
                    alert('✅ 用户已删除！');
                    location.reload();
                } else {
                    alert('❌ ' + result.error);
                }
            } catch (err) {
                alert('❌ 网络错误：' + err.message);
            }
        }
        
        function logout() {
            if (confirm('确定要登出吗？')) {
                window.location.href = '/logout';
            }
        }
    </script>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - GTO 许可证管理系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .login-box {
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            width: 400px;
        }
        .login-box h1 {
            color: #667eea;
            margin-bottom: 30px;
            text-align: center;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 600;
        }
        .form-group input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e1e8ed;
            border-radius: 8px;
            font-size: 1em;
        }
        .form-group input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            width: 100%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 14px;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
            font-weight: 600;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }
        .error {
            color: #dc3545;
            margin-top: 10px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>🔐 管理员登录</h1>
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="password">密码</label>
                <input type="password" id="password" name="password" required autofocus>
            </div>
            <button type="submit" class="btn">登录</button>
            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}
        </form>
    </div>
</body>
</html>
'''

# ========== 路由 ==========

@app.route('/')
def index():
    """主页面（需要登录）"""
    if 'logged_in' not in session:
        return redirect(url_for('login_page'))
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        # 获取所有用户
        cursor.execute('''
            SELECT id, email, ggid, mac_address, expiry_date, is_active, created_at,
                   CASE 
                       WHEN is_active = FALSE THEN 'inactive'
                       WHEN expiry_date < NOW() + INTERVAL '8 hours' THEN 'expired'
                       ELSE 'valid'
                   END AS status
            FROM licenses
            ORDER BY created_at DESC
        ''')
        users = [dict(row) for row in cursor.fetchall()]
        
        # 统计信息
        cursor.execute("SELECT COUNT(*) as total FROM licenses")
        total = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as valid FROM licenses WHERE is_active = TRUE AND expiry_date > NOW() + INTERVAL '8 hours'")
        valid = cursor.fetchone()['valid']
        
        expired = total - valid
        stats = {'total': total, 'valid': valid, 'expired': expired}
        
        # 获取最近日志
        cursor.execute('''
            SELECT * FROM admin_logs
            ORDER BY timestamp DESC
            LIMIT 20
        ''')
        logs = [dict(row) for row in cursor.fetchall()]
        
        db.close()
        
        return render_template_string(HTML_TEMPLATE, users=users, stats=stats, logs=logs)
        
    except Exception as e:
        return f"数据库错误: {str(e)}", 500

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    """登录页面"""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            log_action('管理员登录', details='成功')
            return redirect(url_for('index'))
        else:
            log_action('管理员登录', details='密码错误')
            return render_template_string(LOGIN_TEMPLATE, error='密码错误')
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    """登出"""
    session.pop('logged_in', None)
    log_action('管理员登出')
    return redirect(url_for('login_page'))

# ========== API 端点 ==========

@app.route('/api/verify', methods=['POST'])
def api_verify():
    """验证许可证（供应用程序调用）"""
    try:
        data = request.json
        email = data.get('email')
        mac_address = data.get('mac_address')
        
        if not email:
            return jsonify({'success': False, 'error': '邮箱不能为空'}), 400
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT * FROM licenses
            WHERE email = %s AND is_active = TRUE
        ''', (email,))
        
        license_data = cursor.fetchone()
        
        if not license_data:
            db.close()
            return jsonify({'success': False, 'error': '许可证不存在或未激活'}), 404
        
        license_dict = dict(license_data)
        
        # 检查是否过期（数据库存储北京时间）
        expiry_dt = license_dict['expiry_date']
        beijing_tz = timezone(timedelta(hours=8))
        expiry_beijing = expiry_dt.replace(tzinfo=beijing_tz)
        expiry_utc = expiry_beijing.astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        
        if expiry_utc < now_utc:
            db.close()
            return jsonify({'success': False, 'error': '许可证已过期'}), 403
        
        # MAC 地址验证
        if mac_address:
            if not license_dict['mac_address']:
                # 首次登录，绑定 MAC
                cursor.execute('UPDATE licenses SET mac_address = %s WHERE email = %s', (mac_address, email))
                db.commit()
                license_dict['mac_address'] = mac_address
                log_action('首次登录（绑定MAC）', email, f'MAC: {mac_address}')
            elif license_dict['mac_address'] != mac_address:
                # MAC 不匹配
                db.close()
                return jsonify({
                    'success': False,
                    'error': 'MAC 地址不匹配',
                    'bound_mac': license_dict['mac_address'],
                    'current_mac': mac_address
                }), 403
        
        db.close()
        
        return jsonify({
            'success': True,
            'license': {
                'email': license_dict['email'],
                'ggid': license_dict['ggid'],
                'expiry_date': expiry_utc.isoformat(),
                'is_active': license_dict['is_active'],
                'mac_address': license_dict['mac_address']
            }
        }), 200
        
    except Exception as e:
        print(f'[API ERROR] {e}')
        return jsonify({'success': False, 'error': '服务器内部错误'}), 500

@app.route('/api/add_user', methods=['POST'])
def api_add_user():
    """添加新用户"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401
    
    try:
        data = request.json
        email = data.get('email')
        ggid = data.get('ggid')
        duration = float(data.get('duration', 30))
        notes = data.get('notes')
        
        if not email:
            return jsonify({'success': False, 'error': '邮箱不能为空'}), 400
        
        # 计算到期时间（北京时间）
        beijing_tz = timezone(timedelta(hours=8))
        now_beijing = datetime.now(beijing_tz)
        expiry_date = now_beijing + timedelta(days=duration)
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO licenses (email, ggid, expiry_date, notes)
            VALUES (%s, %s, %s, %s)
        ''', (email, ggid, expiry_date, notes))
        db.commit()
        db.close()
        
        log_action('添加用户', email, f'有效期: {duration}天')
        
        return jsonify({'success': True})
        
    except psycopg2.IntegrityError:
        return jsonify({'success': False, 'error': '该邮箱已存在'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/extend_license', methods=['POST'])
def api_extend_license():
    """延长许可证"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401
    
    try:
        data = request.json
        user_id = data.get('id')
        days = float(data.get('days', 30))
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT email FROM licenses WHERE id = %s', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404
        
        cursor.execute('''
            UPDATE licenses 
            SET expiry_date = expiry_date + INTERVAL '%s days',
                is_active = TRUE
            WHERE id = %s
        ''', (days, user_id))
        db.commit()
        db.close()
        
        log_action('延长许可证', user['email'], f'+{days}天')
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_expiry', methods=['POST'])
def api_update_expiry():
    """修改到期时间"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401
    
    try:
        data = request.json
        user_id = data.get('id')
        datetime_str = data.get('datetime')
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT email FROM licenses WHERE id = %s', (user_id,))
        user = cursor.fetchone()
        
        cursor.execute('UPDATE licenses SET expiry_date = %s WHERE id = %s', (datetime_str, user_id))
        db.commit()
        db.close()
        
        log_action('修改到期时间', user['email'], f'新时间: {datetime_str}')
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reset_mac', methods=['POST'])
def api_reset_mac():
    """重置 MAC 地址"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401
    
    try:
        data = request.json
        user_id = data.get('id')
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT email, mac_address FROM licenses WHERE id = %s', (user_id,))
        user = cursor.fetchone()
        
        cursor.execute('UPDATE licenses SET mac_address = NULL WHERE id = %s', (user_id,))
        db.commit()
        db.close()
        
        log_action('重置MAC地址', user['email'], f'旧MAC: {user["mac_address"]}')
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    """删除用户"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401
    
    try:
        data = request.json
        user_id = data.get('id')
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT email FROM licenses WHERE id = %s', (user_id,))
        user = cursor.fetchone()
        
        cursor.execute('DELETE FROM licenses WHERE id = %s', (user_id,))
        db.commit()
        db.close()
        
        log_action('删除用户', user['email'])
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    """健康检查"""
    return jsonify({'status': 'ok', 'database': 'PostgreSQL'}), 200

if __name__ == '__main__':
    print("=" * 60)
    print("🔐 GTO 许可证管理系统 - PostgreSQL 版本")
    print("=" * 60)
    print("")
    
    # 初始化数据库
    try:
        print("📊 初始化数据库...")
        init_db()
    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")
        print("⚠️  请确保 DATABASE_URL 环境变量已设置")
    
    # Railway 需要使用 $PORT 环境变量
    port = int(os.getenv('PORT', 8000))
    
    print(f"📊 Dashboard: http://0.0.0.0:{port}")
    print(f"🔌 API端点: http://0.0.0.0:{port}/api/verify")
    print("🔑 管理员密码: SW1024sw..")
    print("🐘 数据库: PostgreSQL")
    print("")
    print("⚠️  按 Ctrl+C 停止服务器")
    print("=" * 60)
    print("")
    
    app.run(host='0.0.0.0', port=port, debug=False)
