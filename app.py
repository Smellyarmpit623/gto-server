#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GTO 服务器 - License Key 系统 + GTO API 模拟 + Socket.IO
完整版：Dashboard + API + WebSocket
"""

from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from datetime import datetime, timezone, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import secrets
import hashlib
import uuid

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'gto-license-super-secret-key-2024-xyz')
CORS(app)

# Socket.IO (生产环境使用 gevent)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# 管理员密码
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'SW1024sw..')

# PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise Exception("❌ DATABASE_URL 环境变量未设置！")

# ============================================
# 数据库操作
# ============================================

def get_db():
    """获取数据库连接"""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    """初始化数据库"""
    db = get_db()
    cursor = db.cursor()
    
    # License Key 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS licenses (
            id SERIAL PRIMARY KEY,
            license_key VARCHAR(50) NOT NULL UNIQUE,
            hwid VARCHAR(100),
            email VARCHAR(255),
            ggid VARCHAR(100),
            expiry_date TIMESTAMP NOT NULL,
            stake_level INTEGER DEFAULT 25,
            max_devices INTEGER DEFAULT 1,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP,
            notes TEXT
        )
    ''')
    
    # 日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id SERIAL PRIMARY KEY,
            action VARCHAR(255) NOT NULL,
            target_key VARCHAR(50),
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 使用统计表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_stats (
            id SERIAL PRIMARY KEY,
            license_key VARCHAR(50) NOT NULL,
            hwid VARCHAR(100),
            ip_address VARCHAR(50),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    db.commit()
    db.close()
    print('✅ 数据库初始化完成')

def log_action(action, target_key=None, details=None):
    """记录管理员操作"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO admin_logs (action, target_key, details)
            VALUES (%s, %s, %s)
        ''', (action, target_key, details))
        db.commit()
        db.close()
    except Exception as e:
        print(f'[LOG ERROR] {e}')

def log_usage(license_key, hwid, ip_address):
    """记录使用统计"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO usage_stats (license_key, hwid, ip_address)
            VALUES (%s, %s, %s)
        ''', (license_key, hwid, ip_address))
        
        # 更新 last_used
        cursor.execute('''
            UPDATE licenses SET last_used = CURRENT_TIMESTAMP
            WHERE license_key = %s
        ''', (license_key,))
        
        db.commit()
        db.close()
    except Exception as e:
        print(f'[USAGE ERROR] {e}')

def generate_license_key():
    """生成 License Key"""
    # 格式: GTO-XXXX-YYYY-ZZZZ
    parts = [
        'GTO',
        secrets.token_hex(2).upper(),
        secrets.token_hex(2).upper(),
        secrets.token_hex(2).upper()
    ]
    return '-'.join(parts)

# ============================================
# API 端点 - License 验证
# ============================================

@app.route('/api/verify', methods=['POST', 'OPTIONS'])
def verify_license():
    """验证 License Key"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        data = request.json
        license_key = data.get('license_key', '').strip()
        hwid = data.get('hwid', '').strip()
        
        if not license_key or not hwid:
            return jsonify({'error': '缺少 license_key 或 hwid'}), 400
        
        db = get_db()
        cursor = db.cursor()
        
        # 查询 License
        cursor.execute('''
            SELECT * FROM licenses 
            WHERE license_key = %s AND is_active = TRUE
        ''', (license_key,))
        
        license_data = cursor.fetchone()
        
        if not license_data:
            db.close()
            return jsonify({'error': '无效的 License Key'}), 401
        
        # 检查过期
        expiry_date = license_data['expiry_date']
        if expiry_date.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            db.close()
            return jsonify({'error': 'License 已过期'}), 401
        
        # HWID 绑定检查
        stored_hwid = license_data['hwid']
        if stored_hwid is None:
            # 首次使用，绑定 HWID
            cursor.execute('''
                UPDATE licenses SET hwid = %s 
                WHERE license_key = %s
            ''', (hwid, license_key))
            db.commit()
            print(f'[BIND] {license_key} → {hwid}')
        elif stored_hwid != hwid:
            # HWID 不匹配
            db.close()
            return jsonify({'error': 'HWID 不匹配，此 License 已绑定其他设备'}), 403
        
        db.close()
        
        # 记录使用
        log_usage(license_key, hwid, request.remote_addr)
        
        # 返回成功
        return jsonify({
            'success': True,
            'license_key': license_key,
            'expiry_date': expiry_date.isoformat(),
            'stake_level': license_data['stake_level'],
            'days_remaining': (expiry_date.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
        }), 200
        
    except Exception as e:
        print(f'[VERIFY ERROR] {e}')
        return jsonify({'error': f'服务器错误: {str(e)}'}), 500

@app.route('/api/config/<license_key>', methods=['GET'])
def get_config(license_key):
    """获取用户配置"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT stake_level, expiry_date FROM licenses 
            WHERE license_key = %s AND is_active = TRUE
        ''', (license_key,))
        
        license_data = cursor.fetchone()
        db.close()
        
        if not license_data:
            return jsonify({'error': '无效的 License'}), 401
        
        return jsonify({
            'stake_level': license_data['stake_level'],
            'expiry_date': license_data['expiry_date'].isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# API 端点 - GTO API 模拟
# ============================================

@app.route('/api/versions', methods=['GET', 'OPTIONS'])
def api_versions():
    """模拟版本检查 - 完整字段"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    return jsonify({
        "data": [
            {
                "id": 49,
                "attributes": {
                    "gui_version": "135.3.0",
                    "core_version": "135.2.0",
                    "core_url": "https://s3.ggpk.quest/v11/ace/135.2.0/chrome.zip",
                    "res_url": "https://s3.ggpk.quest/v11/res/3.0.0/res.zip",
                    "changelog": None,
                    "changelog_cn": None,
                    "spingo_url": None,
                    "createdAt": "2025-09-16T02:51:08.936Z",
                    "updatedAt": "2025-09-16T02:51:08.936Z",
                    "type": "tygto",
                    "published": None,
                    "is_minimum_version": None
                }
            },
            {
                "id": 50,
                "attributes": {
                    "gui_version": "137.4.1",
                    "core_version": "10.1.8",
                    "core_url": "https://s3.ggpk.quest/v11/ace/10.1.8/chrome.zip",
                    "res_url": "https://s3.ggpk.quest/v11/res/3.1.0/res.zip",
                    "changelog": None,
                    "changelog_cn": None,
                    "spingo_url": None,
                    "createdAt": "2025-09-18T09:30:02.242Z",
                    "updatedAt": "2025-09-22T03:15:18.242Z",
                    "type": "tygto",
                    "published": None,
                    "is_minimum_version": None
                }
            },
            {
                "id": 51,
                "attributes": {
                    "gui_version": "137.5.0",
                    "core_version": "10.1.8",
                    "core_url": "https://s3.ggpk.quest/v11/ace/10.1.8/chrome.zip",
                    "res_url": "https://s3.ggpk.quest/v11/res/3.1.0/res.zip",
                    "changelog": "1.Preflop strategies now support stack depth matching with new depth options: 50BB, 60BB, 70BB, 80BB, 150BB, and 200BB\\n2.Fixed position recognition error in NLH mode",
                    "changelog_cn": None,
                    "spingo_url": None,
                    "createdAt": "2025-09-22T09:34:43.607Z",
                    "updatedAt": "2025-09-22T10:15:15.191Z",
                    "type": "tygto",
                    "published": True,
                    "is_minimum_version": None
                }
            },
            {
                "id": 9,
                "attributes": {
                    "gui_version": "8.2.0",
                    "core_version": "8.6.29",
                    "core_url": "https://s3.ggpk.quest/v11/ace/8.6.29/chrome.zip",
                    "res_url": "https://s3.ggpk.quest/v11/res/8.0.0/res.zip",
                    "changelog": None,
                    "changelog_cn": None,
                    "spingo_url": None,
                    "createdAt": "2025-02-10T16:38:39.524Z",
                    "updatedAt": "2025-10-04T17:51:31.265Z",
                    "type": "nutsgto",
                    "published": True,
                    "is_minimum_version": None
                }
            },
            {
                "id": 47,
                "attributes": {
                    "gui_version": "137.0.2",
                    "core_version": "10.0.14",
                    "core_url": "https://s3.ggpk.quest/v11/ace/10.0.14/chrome.zip",
                    "res_url": "https://s3.ggpk.quest/v11/res/3.0.0/res.zip",
                    "changelog": "This version introduces 8 built-in GTOWizard preflop strategies that automatically adapt to opponents' opening sizes. TYGTO now automatically selects the appropriate preflop range based on your opponent's open sizing.",
                    "changelog_cn": None,
                    "spingo_url": None,
                    "createdAt": "2025-08-03T12:46:49.490Z",
                    "updatedAt": "2025-08-07T06:13:00.829Z",
                    "type": "tygto",
                    "published": True,
                    "is_minimum_version": None
                }
            },
            {
                "id": 45,
                "attributes": {
                    "gui_version": "135.0.0",
                    "core_version": "135.1.1",
                    "core_url": "https://s3.ggpk.quest/v11/ace/135.1.1/chrome.zip",
                    "res_url": "https://s3.ggpk.quest/v11/res/2.0.7/res.zip",
                    "changelog": None,
                    "changelog_cn": None,
                    "spingo_url": None,
                    "createdAt": "2025-07-22T05:26:39.447Z",
                    "updatedAt": "2025-08-15T23:58:40.463Z",
                    "type": "tygto",
                    "published": None,
                    "is_minimum_version": None
                }
            },
            {
                "id": 48,
                "attributes": {
                    "gui_version": "137.4.0",
                    "core_version": "10.0.14",
                    "core_url": "https://s3.ggpk.quest/v11/ace/10.0.14/chrome.zip",
                    "res_url": "https://s3.ggpk.quest/v11/res/3.0.0/res.zip",
                    "changelog": "Added Simplified Chinese and Traditional Chinese language support",
                    "changelog_cn": None,
                    "spingo_url": None,
                    "createdAt": "2025-09-15T11:57:38.965Z",
                    "updatedAt": "2025-09-15T11:57:38.965Z",
                    "type": "tygto",
                    "published": True,
                    "is_minimum_version": None
                }
            }
        ],
        "meta": {
            "pagination": {
                "page": 1,
                "pageSize": 25,
                "pageCount": 1,
                "total": 7
            }
        }
    }), 200

@app.route('/api/auth/local', methods=['POST', 'OPTIONS'])
def api_auth():
    """模拟登录 - 根据 License Key 动态返回 Stake Level"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    data = request.json or {}
    email = data.get('email', 'wwe6hb9ij2eip7le@gmail.com')
    
    # 获取 License Key（从请求头或请求体）
    license_key = request.headers.get('X-License-Key') or data.get('license_key')
    
    # 默认 Stake Level
    stake_level = 50
    ggid = None
    
    # 如果提供了 License Key，从数据库查询
    if license_key:
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('SELECT stake_level, ggid FROM licenses WHERE license_key = %s', (license_key,))
            result = cursor.fetchone()
            if result:
                stake_level = result['stake_level'] or 50
                ggid = result.get('ggid')
            db.close()
        except Exception as e:
            print(f'[ERROR] 查询 License 失败: {e}')
    
    # 固定的假 JWT（与原版一致）
    fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6NDcxLCJpYXQiOjE3NjA5NDQ3ODEsImV4cCI6MTc2MTU0OTU4MX0.VGeIpOoNMCh20rHgOT-1SGr23Chce8S1b73hBc170k4"
    
    return jsonify({
        "jwt": fake_jwt,
        "user": {
            "id": 471,
            "username": "WWE6HB9IJ2EIP7LE",
            "email": email,
            "provider": "local",
            "confirmed": True,
            "blocked": False,
            "expired_at": None,
            "plan": "Pro",
            "userPlan": "Pro",
            "nickname": "WWE6HB9IJ2EIP7LE",
            "is_adat": False,
            "stakes_level": stake_level,
            "gas": 0,
            "game_types": ["cash"],
            "createdAt": "2025-09-28T05:53:16.997Z",
            "updatedAt": "2025-10-20T06:44:16.129Z",
            "max_devices": None,
            "gg_nickname": ggid,
            "enable_recording": False,
            "settlement": "day",
            "minutes": 0,
            "isPro": True
        }
    }), 200

@app.route('/users/me', methods=['GET', 'OPTIONS'])
def users_me():
    """模拟用户信息 - 根据 License Key 动态返回 Stake Level"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    # 获取 License Key（从请求头或查询参数）
    license_key = request.headers.get('X-License-Key') or request.args.get('license_key')
    
    # 默认 Stake Level
    stake_level = 50
    ggid = None
    
    # 如果提供了 License Key，从数据库查询
    if license_key:
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('SELECT stake_level, ggid FROM licenses WHERE license_key = %s', (license_key,))
            result = cursor.fetchone()
            if result:
                stake_level = result['stake_level'] or 50
                ggid = result.get('ggid')
            db.close()
        except Exception as e:
            print(f'[ERROR] 查询 License 失败: {e}')
    
    return jsonify({
        "id": 471,
        "username": "WWE6HB9IJ2EIP7LE",
        "email": "wwe6hb9ij2eip7le@gmail.com",
        "provider": "local",
        "confirmed": True,
        "blocked": False,
        "expired_at": None,
        "plan": "Pro",
        "userPlan": "Pro",
        "nickname": "WWE6HB9IJ2EIP7LE",
        "is_adat": False,
        "stakes_level": stake_level,
        "gas": 0,
        "game_types": ["cash"],
        "createdAt": "2025-09-28T05:53:16.997Z",
        "updatedAt": "2025-10-20T06:44:16.129Z",
        "max_devices": None,
        "gg_nickname": ggid,
        "enable_recording": False,
        "settlement": "day",
        "minutes": 0,
        "isPro": True
    }), 200

@app.route('/appconfig.json', methods=['GET', 'OPTIONS'])
def appconfig():
    """模拟应用配置 - 完整字段"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    return jsonify({
        "server_status": "",
        "postflop_status": "",
        "game_modes": [
            {
                "code": "rush",
                "value": "Rush & Cash",
                "label": "Rush & Cash",
                "type": "cash",
                "max": 6,
                "available": True
            },
            {
                "code": "nlh",
                "value": "NLH",
                "label": "NLH 6max",
                "type": "cash",
                "max": 6,
                "available": True
            }
        ]
    }), 200

# ============================================
# Socket.IO - WebSocket 模拟
# ============================================

@socketio.on('connect')
def handle_connect():
    """主命名空间连接"""
    print(f'[WS] Client connected: {request.sid}')
    emit('connected', {
        'status': 'ok',
        'plan': 'Pro',
        'message': 'Welcome to GTO Pro'
    })

@socketio.on('disconnect')
def handle_disconnect():
    """主命名空间断开"""
    print(f'[WS] Client disconnected: {request.sid}')

@socketio.on('ping')
def handle_ping():
    """Ping-Pong"""
    emit('pong', {'timestamp': datetime.now(timezone.utc).isoformat()})

@socketio.on('join')
def handle_join(data):
    """加入房间"""
    room = data.get('room', 'default')
    join_room(room)
    emit('swap done', {'room': room, 'status': 'joined'}, room=room)

# /rtd 命名空间
@socketio.on('connect', namespace='/rtd')
def rtd_connect():
    """RTD 命名空间连接"""
    print(f'[WS/rtd] Client connected: {request.sid}')
    emit('connected', {'namespace': 'rtd', 'status': 'ok'})

@socketio.on('ping', namespace='/rtd')
def rtd_ping():
    """RTD Ping"""
    emit('pong', {'namespace': 'rtd'})

@socketio.on('disconnect', namespace='/rtd')
def rtd_disconnect():
    """RTD 断开"""
    print(f'[WS/rtd] Client disconnected: {request.sid}')

# /home 命名空间
@socketio.on('connect', namespace='/home')
def home_connect():
    """Home 命名空间连接"""
    print(f'[WS/home] Client connected: {request.sid}')
    emit('connected', {'namespace': 'home', 'status': 'ok'})

@socketio.on('disconnect', namespace='/home')
def home_disconnect():
    """Home 断开"""
    print(f'[WS/home] Client disconnected: {request.sid}')

# ============================================
# Dashboard - 管理界面
# ============================================

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GTO License Dashboard</title>
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
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 30px;
            text-align: center;
        }
        .header h1 {
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        .header p {
            color: #666;
            font-size: 1.1em;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-card h3 {
            color: #666;
            font-size: 0.9em;
            margin-bottom: 10px;
            text-transform: uppercase;
        }
        .stat-card .number {
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
        }
        .main-content {
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        .section-title {
            font-size: 1.5em;
            color: #333;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #333;
            font-weight: 500;
        }
        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1em;
            transition: border-color 0.3s;
        }
        .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
            outline: none;
            border-color: #667eea;
        }
        .form-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        .btn {
            padding: 12px 30px;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.3);
        }
        .btn-danger {
            background: #e74c3c;
            color: white;
        }
        .btn-danger:hover {
            background: #c0392b;
        }
        .btn-success {
            background: #27ae60;
            color: white;
        }
        .btn-success:hover {
            background: #229954;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th, td {
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid #e0e0e0;
        }
        th {
            background: #f8f9fa;
            color: #333;
            font-weight: 600;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .status-active {
            color: #27ae60;
            font-weight: 600;
        }
        .status-expired {
            color: #e74c3c;
            font-weight: 600;
        }
        .action-buttons {
            display: flex;
            gap: 10px;
        }
        .action-buttons button {
            padding: 6px 12px;
            font-size: 0.9em;
        }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .tab {
            padding: 12px 24px;
            background: #f8f9fa;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1em;
            font-weight: 500;
            transition: all 0.3s;
        }
        .tab.active {
            background: #667eea;
            color: white;
        }
        .tab:hover {
            background: #e8e9eb;
        }
        .tab.active:hover {
            background: #5568d3;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .message {
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .message-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .message-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .logout {
            float: right;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎮 GTO License Dashboard</h1>
            <p>License Key 管理系统</p>
            <button class="btn btn-danger logout" onclick="logout()">退出登录</button>
        </div>

        {% if message %}
        <div class="message message-{{ message_type }}">
            {{ message }}
        </div>
        {% endif %}
        
        <div class="stats">
            <div class="stat-card">
                <h3>总 License 数</h3>
                <div class="number">{{ stats.total }}</div>
            </div>
            <div class="stat-card">
                <h3>激活中</h3>
                <div class="number">{{ stats.active }}</div>
            </div>
            <div class="stat-card">
                <h3>已过期</h3>
                <div class="number">{{ stats.expired }}</div>
            </div>
            <div class="stat-card">
                <h3>今日使用</h3>
                <div class="number">{{ stats.today_usage }}</div>
            </div>
        </div>
        
        <div class="main-content">
            <div class="tabs">
                <button class="tab active" onclick="switchTab('licenses')">License 管理</button>
                <button class="tab" onclick="switchTab('create')">生成 License</button>
                <button class="tab" onclick="switchTab('logs')">操作日志</button>
        </div>
        
            <!-- License 列表 -->
            <div id="licenses" class="tab-content active">
                <h2 class="section-title">License 列表</h2>
            <table>
                <thead>
                    <tr>
                            <th>License Key</th>
                            <th>HWID</th>
                        <th>到期时间</th>
                            <th>Stake Level</th>
                            <th>最后使用</th>
                        <th>状态</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                        {% for lic in licenses %}
                        <tr>
                            <td><code>{{ lic.license_key }}</code></td>
                            <td><small>{{ lic.hwid[:20] if lic.hwid else '未绑定' }}</small></td>
                            <td>{{ lic.expiry_date.strftime('%Y-%m-%d %H:%M') }}</td>
                            <td>{{ lic.stake_level }}</td>
                            <td>{{ lic.last_used.strftime('%Y-%m-%d %H:%M') if lic.last_used else '从未使用' }}</td>
                            <td>
                                {% if lic.is_active and lic.expiry_date > now %}
                                <span class="status-active">✅ 激活</span>
                            {% else %}
                                <span class="status-expired">❌ 过期</span>
                            {% endif %}
                        </td>
                            <td>
                                <div class="action-buttons">
                                    <form method="POST" action="/extend" style="display:inline;">
                                        <input type="hidden" name="license_key" value="{{ lic.license_key }}">
                                        <button type="submit" class="btn btn-success">+30天</button>
                                    </form>
                                    <form method="POST" action="/reset-hwid" style="display:inline;">
                                        <input type="hidden" name="license_key" value="{{ lic.license_key }}">
                                        <button type="submit" class="btn btn-primary">重置HWID</button>
                                    </form>
                                    <form method="POST" action="/delete" style="display:inline;">
                                        <input type="hidden" name="license_key" value="{{ lic.license_key }}">
                                        <button type="submit" class="btn btn-danger" onclick="return confirm('确定删除？')">删除</button>
                                    </form>
                                </div>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
            <!-- 生成 License -->
            <div id="create" class="tab-content">
                <h2 class="section-title">生成新 License</h2>
                <form method="POST" action="/create-license">
                    <div class="form-row">
                        <div class="form-group">
                            <label>有效期（天）</label>
                            <input type="number" name="days" value="30" required>
                        </div>
                        <div class="form-group">
                            <label>Stake Level</label>
                            <input type="number" name="stake_level" value="25" required>
                        </div>
                        <div class="form-group">
                            <label>最大设备数</label>
                            <input type="number" name="max_devices" value="1" required>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>邮箱（可选）</label>
                        <input type="email" name="email" placeholder="user@example.com">
                    </div>
                    <div class="form-group">
                        <label>GGID（可选）</label>
                        <input type="text" name="ggid" placeholder="用户的 GG ID">
                    </div>
                    <div class="form-group">
                        <label>备注（可选）</label>
                        <textarea name="notes" rows="3" placeholder="备注信息..."></textarea>
                    </div>
                    <button type="submit" class="btn btn-primary">🎁 生成 License Key</button>
                </form>
            </div>

            <!-- 操作日志 -->
            <div id="logs" class="tab-content">
                <h2 class="section-title">操作日志</h2>
            <table>
                <thead>
                    <tr>
                        <th>时间</th>
                        <th>操作</th>
                            <th>License Key</th>
                        <th>详情</th>
                    </tr>
                </thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                            <td>{{ log.timestamp.strftime('%Y-%m-%d %H:%M:%S') }}</td>
                        <td>{{ log.action }}</td>
                            <td><code>{{ log.target_key }}</code></td>
                            <td><small>{{ log.details }}</small></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            </div>
        </div>
    </div>
    
    <script>
        function switchTab(tabName) {
            // 隐藏所有内容
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            
            // 显示选中的
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
        }
        
        function logout() {
            if (confirm('确定退出登录？')) {
                window.location.href = '/logout';
            }
        }
    </script>
</body>
</html>
'''

LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GTO Dashboard - 登录</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-box {
            background: white;
            padding: 50px 40px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 400px;
            text-align: center;
        }
        .login-box h1 {
            color: #667eea;
            font-size: 2em;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
            text-align: left;
        }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
        }
        .form-group input {
            width: 100%;
            padding: 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 1em;
            transition: border-color 0.3s;
        }
        .form-group input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            width: 100%;
            padding: 15px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1.1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        .btn:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(102, 126, 234, 0.3);
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>🎮 GTO Dashboard</h1>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST" action="/login">
            <div class="form-group">
                <label>管理员密码</label>
                <input type="password" name="password" required autofocus>
            </div>
            <button type="submit" class="btn">登录</button>
        </form>
    </div>
</body>
</html>
'''

@app.route('/')
def index():
    """首页 - Dashboard"""
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        # 确保表存在（防御性编程）
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'licenses'
            ) AS exists_table
        """)
        exists_table = cursor.fetchone()
        if not exists_table or not exists_table.get('exists_table'):
            return '<h1>⚠️ 数据库未初始化</h1><p>请访问 <a href="/init-db">/init-db</a> 初始化数据库</p>', 503
        
        # 获取所有 License
        cursor.execute('''
            SELECT * FROM licenses 
            ORDER BY created_at DESC
        ''')
        licenses_raw = cursor.fetchall()
        
        # 确保所有 datetime 字段都有时区信息（为模板准备）
        licenses = []
        for lic in licenses_raw:
            lic_dict = dict(lic)
            # 给所有 datetime 字段添加 UTC 时区
            if lic_dict.get('expiry_date') and lic_dict['expiry_date'].tzinfo is None:
                lic_dict['expiry_date'] = lic_dict['expiry_date'].replace(tzinfo=timezone.utc)
            if lic_dict.get('created_at') and lic_dict['created_at'].tzinfo is None:
                lic_dict['created_at'] = lic_dict['created_at'].replace(tzinfo=timezone.utc)
            if lic_dict.get('last_used') and lic_dict['last_used'].tzinfo is None:
                lic_dict['last_used'] = lic_dict['last_used'].replace(tzinfo=timezone.utc)
            licenses.append(lic_dict)
        
        # 统计
        now = datetime.now(timezone.utc)
        total = len(licenses)
        active = sum(1 for lic in licenses if lic['is_active'] and lic['expiry_date'] > now)
        expired = total - active
        
        # 今日使用
        cursor.execute('''
            SELECT COUNT(DISTINCT license_key) AS today_total
            FROM usage_stats 
            WHERE DATE(timestamp) = CURRENT_DATE
        ''')
        result = cursor.fetchone()
        today_usage = result['today_total'] if result and result.get('today_total') is not None else 0
        
        # 操作日志
        cursor.execute('''
            SELECT * FROM admin_logs
            ORDER BY timestamp DESC
            LIMIT 50
        ''')
        logs_raw = cursor.fetchall()
        
        # 确保 logs 的时区信息
        logs = []
        for log in logs_raw:
            log_dict = dict(log)
            if log_dict.get('timestamp') and log_dict['timestamp'].tzinfo is None:
                log_dict['timestamp'] = log_dict['timestamp'].replace(tzinfo=timezone.utc)
            logs.append(log_dict)
        
        db.close()
        
        return render_template_string(DASHBOARD_HTML, 
            licenses=licenses,
            logs=logs,
            stats={
                'total': total,
                'active': active,
                'expired': expired,
                'today_usage': today_usage
            },
            now=now,
            message=session.pop('message', None),
            message_type=session.pop('message_type', 'success')
        )
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f'[ERROR] Dashboard 错误: {str(e)}')
        print(error_detail)
        return f'<h1>数据库错误</h1><pre>{str(e)}</pre><pre>{error_detail}</pre>', 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录"""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('index'))
        else:
            return render_template_string(LOGIN_HTML, error='密码错误')
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    """登出"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/create-license', methods=['POST'])
def create_license():
    """生成新 License"""
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    try:
        days = int(request.form.get('days', 30))
        stake_level = int(request.form.get('stake_level', 25))
        max_devices = int(request.form.get('max_devices', 1))
        email = request.form.get('email', '').strip()
        ggid = request.form.get('ggid', '').strip()
        notes = request.form.get('notes', '').strip()
        
        # 生成 License Key
        license_key = generate_license_key()
        expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            INSERT INTO licenses (license_key, expiry_date, stake_level, max_devices, email, ggid, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (license_key, expiry_date, stake_level, max_devices, email or None, ggid or None, notes or None))
        
        db.commit()
        db.close()
        
        log_action('创建 License', license_key, f'有效期: {days}天, Stake: {stake_level}')
        
        session['message'] = f'✅ License 创建成功！Key: {license_key}'
        session['message_type'] = 'success'
        
    except Exception as e:
        session['message'] = f'❌ 创建失败: {str(e)}'
        session['message_type'] = 'error'
    
    return redirect(url_for('index'))

@app.route('/extend', methods=['POST'])
def extend_license():
    """延长 License"""
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    try:
        license_key = request.form.get('license_key')
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            UPDATE licenses 
            SET expiry_date = expiry_date + INTERVAL '30 days'
            WHERE license_key = %s
        ''', (license_key,))
        
        db.commit()
        db.close()
        
        log_action('延长 License', license_key, '延长 30 天')
        
        session['message'] = f'✅ {license_key} 已延长 30 天'
        session['message_type'] = 'success'
        
    except Exception as e:
        session['message'] = f'❌ 延长失败: {str(e)}'
        session['message_type'] = 'error'
    
    return redirect(url_for('index'))

@app.route('/reset-hwid', methods=['POST'])
def reset_hwid():
    """重置 HWID"""
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    try:
        license_key = request.form.get('license_key')
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            UPDATE licenses 
            SET hwid = NULL
            WHERE license_key = %s
        ''', (license_key,))
        
        db.commit()
        db.close()
        
        log_action('重置 HWID', license_key, '已解绑设备')
        
        session['message'] = f'✅ {license_key} 的 HWID 已重置'
        session['message_type'] = 'success'
        
    except Exception as e:
        session['message'] = f'❌ 重置失败: {str(e)}'
        session['message_type'] = 'error'
    
    return redirect(url_for('index'))

@app.route('/delete', methods=['POST'])
def delete_license():
    """删除 License"""
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    try:
        license_key = request.form.get('license_key')
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('DELETE FROM licenses WHERE license_key = %s', (license_key,))
        
        db.commit()
        db.close()
        
        log_action('删除 License', license_key, '已删除')
        
        session['message'] = f'✅ {license_key} 已删除'
        session['message_type'] = 'success'
        
    except Exception as e:
        session['message'] = f'❌ 删除失败: {str(e)}'
        session['message_type'] = 'error'
    
    return redirect(url_for('index'))

# ============================================
# 健康检查
# ============================================

@app.route('/health')
def health():
    """健康检查"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now(timezone.utc).isoformat()}), 200

@app.route('/init-db')
def init_db_route():
    """初始化数据库（首次部署）"""
    try:
        init_db()
        return '✅ 数据库初始化成功！', 200
    except Exception as e:
        return f'❌ 初始化失败: {str(e)}', 500

@app.route('/migrate-ggid')
def migrate_ggid():
    """迁移：添加 GGID 字段"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # 检查列是否存在
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='licenses' AND column_name='ggid'
        """)
        
        if not cursor.fetchone():
            cursor.execute('ALTER TABLE licenses ADD COLUMN ggid VARCHAR(100)')
            db.commit()
            db.close()
            return '✅ GGID 字段添加成功！', 200
        else:
            db.close()
            return '⚠️  GGID 字段已存在', 200
        
    except Exception as e:
        return f'❌ 迁移失败: {str(e)}', 500

# ============================================
# 启动服务器
# ============================================

if __name__ == '__main__':
    print('')
    print('=' * 60)
    print('🚀 GTO 服务器 - License Key 系统 (生产模式)')
    print('=' * 60)
    print('')
    print('📡 功能：')
    print('   • License Key 验证 (/api/verify)')
    print('   • GTO API 模拟 (/api/versions, /api/auth/local, etc.)')
    print('   • Socket.IO WebSocket (/, /rtd, /home)')
    print('   • Dashboard 管理界面 (/)')
    print('')
    print('🔧 首次部署请访问: /init-db')
    print('')
    
    port = int(os.getenv('PORT', 5000))
    
    # 生产环境使用 gevent，开发环境使用 Werkzeug
    socketio.run(app, host='0.0.0.0', port=port, debug=False, 
                 allow_unsafe_werkzeug=True)
