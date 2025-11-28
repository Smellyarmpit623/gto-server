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
import jwt
import time

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'gto-license-super-secret-key-2024-xyz')
CORS(app)

# Socket.IO (生产环境使用 gevent)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# 管理员密码
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'SW1024sw..')

# JWT 配置
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'gto-jwt-secret-key-2024-ultra-secure')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_DAYS = 7  # JWT 有效期（天）

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
            plan VARCHAR(20) DEFAULT 'Pro',
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
        "core_version": "135.2.1",
        "core_url": "https://s3.ggpk.quest/v11/ace/135.2.1/chrome.zip",
        "res_url": "https://s3.ggpk.quest/v11/res/3.0.0/res.zip",
        "changelog": null,
        "changelog_cn": null,
        "spingo_url": null,
        "createdAt": "2025-09-16T02:51:08.936Z",
        "updatedAt": "2025-10-26T10:28:58.969Z",
        "type": "tygto",
        "published": null,
        "is_minimum_version": null
      }
    },
    {
      "id": 45,
      "attributes": {
        "gui_version": "135.0.0",
        "core_version": "135.2.1",
        "core_url": "https://s3.ggpk.quest/v11/ace/135.2.1/chrome.zip",
        "res_url": "https://s3.ggpk.quest/v11/res/2.0.7/res.zip",
        "changelog": null,
        "changelog_cn": null,
        "spingo_url": null,
        "createdAt": "2025-07-22T05:26:39.447Z",
        "updatedAt": "2025-10-28T03:16:00.641Z",
        "type": "tygto",
        "published": null,
        "is_minimum_version": null
      }
    },
    {
      "id": 50,
      "attributes": {
        "gui_version": "137.4.1",
        "core_version": "10.2.0",
        "core_url": "https://s3.ggpk.quest/v11/ace/10.2.0/chrome.zip",
        "res_url": "https://s3.ggpk.quest/v11/res/3.1.0/res.zip",
        "changelog": null,
        "changelog_cn": null,
        "spingo_url": null,
        "createdAt": "2025-09-18T09:30:02.242Z",
        "updatedAt": "2025-11-25T07:29:13.235Z",
        "type": "tygto",
        "published": null,
        "is_minimum_version": null
      }
    },
    {
      "id": 52,
      "attributes": {
        "gui_version": "137.5.1",
        "core_version": "10.2.1",
        "core_url": "https://s3.ggpk.quest/v11/ace/10.2.1/chrome.zip",
        "res_url": "https://s3.ggpk.quest/v11/res/3.1.0/res.zip",
        "changelog": " Improved anti-ban tech on this update",
        "changelog_cn": null,
        "spingo_url": null,
        "createdAt": "2025-11-20T15:32:23.772Z",
        "updatedAt": "2025-11-26T05:45:05.034Z",
        "type": "tygto",
        "published": true,
        "is_minimum_version": false
      }
    },
    {
      "id": 51,
      "attributes": {
        "gui_version": "137.5.0",
        "core_version": "10.2.1",
        "core_url": "https://s3.ggpk.quest/v11/ace/10.2.1/chrome.zip",
        "res_url": "https://s3.ggpk.quest/v11/res/3.1.0/res.zip",
        "changelog": "1.Preflop strategies now support stack depth matching with new depth options: 50BB, 60BB, 70BB, 80BB, 150BB, and 200BB\n2.Fixed position recognition error in NLH mode",
        "changelog_cn": null,
        "spingo_url": null,
        "createdAt": "2025-09-22T09:34:43.607Z",
        "updatedAt": "2025-11-26T05:45:12.256Z",
        "type": "tygto",
        "published": true,
        "is_minimum_version": null
      }
    },
    {
      "id": 9,
      "attributes": {
        "gui_version": "8.2.0",
        "core_version": "8.6.29",
        "core_url": "https://s3.ggpk.quest/v11/ace/8.6.29/chrome.zip",
        "res_url": "https://s3.ggpk.quest/v11/res/8.0.0/res.zip",
        "changelog": null,
        "changelog_cn": null,
        "spingo_url": null,
        "createdAt": "2025-02-10T16:38:39.524Z",
        "updatedAt": "2025-10-04T17:51:31.265Z",
        "type": "nutsgto",
        "published": true,
        "is_minimum_version": null
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
        "changelog_cn": null,
        "spingo_url": null,
        "createdAt": "2025-08-03T12:46:49.490Z",
        "updatedAt": "2025-08-07T06:13:00.829Z",
        "type": "tygto",
        "published": true,
        "is_minimum_version": null
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
        "changelog_cn": null,
        "spingo_url": null,
        "createdAt": "2025-09-15T11:57:38.965Z",
        "updatedAt": "2025-09-15T11:57:38.965Z",
        "type": "tygto",
        "published": true,
        "is_minimum_version": null
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
    """模拟登录 - 验证 License Key 和 HWID"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    data = request.json or {}
    
    # 获取 License Key 和 HWID
    license_key = request.headers.get('X-License-Key') or data.get('identifier') or data.get('password')
    hwid = request.headers.get('X-HWID') or data.get('machineId')
    
    # 必须提供 License Key
    if not license_key:
        return jsonify({"error": "License Key is required"}), 401
    
    # 从数据库查询 License
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            SELECT hwid, stake_level, ggid, expiry_date, plan 
            FROM licenses 
            WHERE license_key = %s
        ''', (license_key,))
        result = cursor.fetchone()
        db.close()
        
        # License Key 不存在
        if not result:
            print(f'[AUTH] ❌ License Key 不存在: {license_key}')
            return jsonify({"error": "Invalid License Key"}), 401
        
        # 检查是否过期
        if result['expiry_date']:
            expiry_date = result['expiry_date']
            # 确保 expiry_date 是 offset-aware
            if expiry_date.tzinfo is None:
                expiry_date = expiry_date.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expiry_date:
                print(f'[AUTH] ❌ License 已过期: {license_key}')
                return jsonify({"error": "License expired"}), 401
        
        # 验证 HWID（如果数据库中已绑定）
        db_hwid = result.get('hwid')
        if db_hwid:
            # 如果数据库中有 HWID，必须匹配
            if not hwid:
                print(f'[AUTH] ❌ 缺少 HWID: {license_key}')
                return jsonify({"error": "HWID is required"}), 401
            if hwid != db_hwid:
                print(f'[AUTH] ❌ HWID 不匹配: {license_key} (期望: {db_hwid}, 实际: {hwid})')
                return jsonify({"error": "HWID mismatch"}), 403
        else:
            # 如果数据库中没有 HWID，自动绑定
            if hwid:
                try:
                    db = get_db()
                    cursor = db.cursor()
                    cursor.execute('UPDATE licenses SET hwid = %s WHERE license_key = %s', (hwid, license_key))
                    db.commit()
                    db.close()
                    print(f'[AUTH] ✅ HWID 已绑定: {license_key} → {hwid}')
                except Exception as e:
                    print(f'[AUTH] ⚠️  HWID 绑定失败: {e}')
        
        # 验证通过，返回用户信息
        # username 和 nickname 直接用 License Key
        username = license_key
        nickname = license_key
        # email = License Key + @gmail.com
        email = f"{license_key}@gmail.com"
        # stake_level 从数据库读取，默认 25
        stake_level = result.get('stake_level') or 25
        # ggid 从数据库读取（如果有）
        ggid = result.get('ggid')
        # plan 从数据库读取，默认 Pro
        plan = result.get('plan') or 'Pro'
        
        # 格式化 expired_at（与其他时间字段格式一致：ISO 8601）
        expired_at_formatted = None
        if expiry_date:
            # 确保时区信息存在
            if expiry_date.tzinfo is None:
                expiry_date = expiry_date.replace(tzinfo=timezone.utc)
            expired_at_formatted = expiry_date.isoformat().replace('+00:00', 'Z')
        
        print(f'[AUTH] ✅ 登录成功: {username} (Email: {email}, Stake: {stake_level}, GGID: {ggid}, Plan: {plan}, Expires: {expired_at_formatted})')
        
        # 生成真实的 JWT
        iat = int(time.time())  # 签发时间
        exp = iat + (JWT_EXPIRATION_DAYS * 24 * 60 * 60)  # 过期时间
        
        jwt_payload = {
            "id": 471,  # 固定用户ID
            "license_key": license_key,  # License Key
            "username": username,
            "email": email,
            "stake_level": stake_level,
            "iat": iat,
            "exp": exp
        }
        
        real_jwt = jwt.encode(jwt_payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        
        print(f'[AUTH] 🔐 JWT 已生成: {license_key} (过期时间: {JWT_EXPIRATION_DAYS}天)')
        
        return jsonify({
            "jwt": real_jwt,
            "user": {
                "id": 471,
                "username": username,
                "email": email,
                "provider": "local",
                "confirmed": True,
                "blocked": False,
                "expired_at": expired_at_formatted,
                "plan": plan,
                "userPlan": plan,
                "nickname": nickname,
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
                "isPro": plan == "Pro"
            }
        }), 200
        
    except Exception as e:
        print(f'[AUTH] ❌ 数据库错误: {e}')
        return jsonify({"error": "Database error"}), 500

@app.route('/api/users/me', methods=['GET', 'OPTIONS'])
def users_me():
    """获取用户信息 - 通过 JWT 验证"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    # 从 Authorization header 中提取 JWT
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        print('[ME] ❌ 缺少 Authorization header 或格式错误')
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.replace('Bearer ', '').strip()
    
    try:
        # 解码并验证 JWT
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # 从 JWT 中提取信息
        license_key = payload.get('license_key')
        username = payload.get('username')
        email = payload.get('email')
        
        if not license_key:
            print('[ME] ❌ JWT 缺少 license_key')
            return jsonify({"error": "Invalid token"}), 401
        
        # 从数据库查询最新的 License 信息（确保未被删除或过期）
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            SELECT hwid, stake_level, ggid, expiry_date, is_active, plan
            FROM licenses 
            WHERE license_key = %s
        ''', (license_key,))
        result = cursor.fetchone()
        db.close()
        
        # License Key 不存在或已被删除
        if not result:
            print(f'[ME] ❌ License Key 不存在: {license_key}')
            return jsonify({"error": "License not found"}), 401
        
        # 检查是否激活
        if not result.get('is_active'):
            print(f'[ME] ❌ License 已停用: {license_key}')
            return jsonify({"error": "License deactivated"}), 401
        
        # 检查是否过期
        if result['expiry_date']:
            expiry_date = result['expiry_date']
            if expiry_date.tzinfo is None:
                expiry_date = expiry_date.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expiry_date:
                print(f'[ME] ❌ License 已过期: {license_key}')
                return jsonify({"error": "License expired"}), 401
        
        # 使用数据库中最新的 stake_level、ggid 和 plan
        db_stake_level = result.get('stake_level') or 25
        ggid = result.get('ggid')
        plan = result.get('plan') or 'Pro'
        
        # 格式化 expired_at（与其他时间字段格式一致：ISO 8601）
        expired_at_formatted = None
        if expiry_date:
            # 确保时区信息存在
            if expiry_date.tzinfo is None:
                expiry_date = expiry_date.replace(tzinfo=timezone.utc)
            expired_at_formatted = expiry_date.isoformat().replace('+00:00', 'Z')
        
        print(f'[ME] ✅ JWT 验证成功: {username} (Stake: {db_stake_level}, GGID: {ggid}, Plan: {plan}, Expires: {expired_at_formatted})')
        
        return jsonify({
            "id": 471,
            "username": username,
            "email": email,
            "provider": "local",
            "confirmed": True,
            "blocked": False,
            "expired_at": expired_at_formatted,
            "plan": plan,
            "userPlan": plan,
            "nickname": username,
            "is_adat": False,
            "stakes_level": db_stake_level,
            "gas": 0,
            "game_types": ["cash"],
            "createdAt": "2025-09-28T05:53:16.997Z",
            "updatedAt": "2025-10-20T06:44:16.129Z",
            "max_devices": None,
            "gg_nickname": ggid,
            "enable_recording": False,
            "settlement": "day",
            "minutes": 0,
            "isPro": plan == "Pro"
        }), 200
        
    except jwt.ExpiredSignatureError:
        print('[ME] ❌ JWT 已过期')
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError as e:
        print(f'[ME] ❌ JWT 验证失败: {e}')
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        print(f'[ME] ❌ 服务器错误: {e}')
        return jsonify({"error": "Server error"}), 500

@app.route('/api/appconfig.json', methods=['GET', 'OPTIONS'])
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

@app.route('/v11/appconfig.json', methods=['GET', 'OPTIONS'])
def v11_appconfig():
    """模拟 S3 配置文件 - 完整字段 (https://s3.ggpk.quest/v11/appconfig.json)"""
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

PRICING_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TYGTO - 终极扑克 RTA</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
            line-height: 1.6;
            color: #333;
        }
        
        .btn {
            padding: 10px 20px;
            border-radius: 25px;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s;
            border: none;
            cursor: pointer;
        }
        .btn-outline {
            background: transparent;
            color: #667eea;
            border: 2px solid #667eea;
        }
        .btn-outline:hover {
            background: #667eea;
            color: white;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover {
            background: #5568d3;
            transform: translateY(-2px);
        }
        
        /* 主要内容 */
        .main-content {
            margin-top: 0;
        }
        
        /* 英雄区域 */
        .hero {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 100px 0;
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        .hero::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000"><defs><radialGradient id="a" cx="50%" cy="50%"><stop offset="0%" stop-color="%23ffffff" stop-opacity="0.1"/><stop offset="100%" stop-color="%23ffffff" stop-opacity="0"/></radialGradient></defs><circle cx="200" cy="200" r="300" fill="url(%23a)"/><circle cx="800" cy="300" r="200" fill="url(%23a)"/><circle cx="500" cy="700" r="400" fill="url(%23a)"/></svg>');
            opacity: 0.3;
        }
        .hero-content {
            position: relative;
            z-index: 2;
            max-width: 800px;
            margin: 0 auto;
            padding: 0 20px;
        }
        .version-badge {
            background: rgba(255, 255, 255, 0.2);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.9em;
            margin-bottom: 20px;
            display: inline-block;
        }
        .hero h1 {
            font-size: 3.5em;
            font-weight: bold;
            margin-bottom: 20px;
            line-height: 1.2;
        }
        .hero h2 {
            font-size: 1.5em;
            margin-bottom: 30px;
            opacity: 0.9;
            font-weight: 400;
        }
        .hero p {
            font-size: 1.2em;
            margin-bottom: 40px;
            opacity: 0.8;
        }
        .hero-buttons {
            display: flex;
            gap: 20px;
            justify-content: center;
            flex-wrap: wrap;
        }
        .hero .btn {
            padding: 15px 30px;
            font-size: 1.1em;
        }
        .hero .btn-outline {
            background: rgba(255, 255, 255, 0.2);
            color: white;
            border-color: white;
        }
        .hero .btn-outline:hover {
            background: white;
            color: #667eea;
        }
        
        /* 统计数据 */
        .stats {
            background: white;
            padding: 80px 0;
        }
        .stats-container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 40px;
            text-align: center;
        }
        .stat-item {
            padding: 20px;
        }
        .stat-number {
            font-size: 3em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 10px;
        }
        .stat-label {
            font-size: 1.1em;
            color: #666;
        }
        
        /* 功能区域 */
        .features {
            background: #f8f9fa;
            padding: 100px 0;
        }
        .features-container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        .examples-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }
        .example-card {
            background: white;
            border-radius: 12px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.08);
            overflow: hidden;
        }
        .example-card img { width: 100%; display: block; }
        .section-title {
            text-align: center;
            font-size: 2.5em;
            margin-bottom: 20px;
            color: #333;
        }
        .section-subtitle {
            text-align: center;
            font-size: 1.2em;
            color: #666;
            margin-bottom: 60px;
        }
        .features-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 40px;
            margin-bottom: 80px;
        }
        .feature-card {
            background: white;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            text-align: center;
            transition: transform 0.3s;
        }
        .feature-card:hover {
            transform: translateY(-5px);
        }
        .feature-icon {
            font-size: 3em;
            margin-bottom: 20px;
        }
        .feature-title {
            font-size: 1.5em;
            font-weight: bold;
            margin-bottom: 15px;
            color: #333;
        }
        .feature-desc {
            color: #666;
            line-height: 1.6;
        }
        
        /* 定价区域 */
        .pricing {
            background: white;
            padding: 100px 0;
        }
        .pricing-container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        .pricing-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 40px;
            margin-top: 60px;
        }
        .pricing-card {
            background: white;
            border: 2px solid #e0e0e0;
            border-radius: 15px;
            padding: 40px;
            text-align: center;
            position: relative;
            transition: all 0.3s;
        }
        .pricing-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 35px rgba(0,0,0,0.1);
        }
        .pricing-card.pro {
            border-color: #667eea;
        }
        .pricing-card.premium {
            border-color: #f39c12;
            background: linear-gradient(135deg, #fef5e7 0%, #ffffff 100%);
        }
        .pricing-name {
            font-size: 1.8em;
            font-weight: bold;
            margin-bottom: 10px;
        }
        .pricing-card.pro .pricing-name {
            color: #667eea;
        }
        .pricing-card.premium .pricing-name {
            color: #f39c12;
        }
        .pricing-price {
            font-size: 3em;
            font-weight: bold;
            color: #333;
            margin-bottom: 5px;
        }
        .pricing-period {
            color: #666;
            margin-bottom: 30px;
        }
        .pricing-features {
            list-style: none;
            margin-bottom: 40px;
        }
        .pricing-features li {
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
            display: flex;
            align-items: center;
        }
        .pricing-features li:last-child {
            border-bottom: none;
        }
        .feature-check {
            color: #27ae60;
            font-weight: bold;
            margin-right: 10px;
        }
        .pricing-button {
            width: 100%;
            padding: 15px;
            font-size: 1.1em;
            font-weight: 600;
        }
        .pricing-card.pro .pricing-button {
            background: #667eea;
            color: white;
        }
        .pricing-card.premium .pricing-button {
            background: #f39c12;
            color: white;
        }
        .pricing-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        
        /* FAQ 区域 */
        .faq {
            background: #f8f9fa;
            padding: 100px 0;
        }
        .faq-container {
            max-width: 800px;
            margin: 0 auto;
            padding: 0 20px;
        }
        .faq-item {
            background: white;
            margin-bottom: 20px;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .faq-question {
            padding: 25px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.3s;
            border: none;
            background: white;
            width: 100%;
            text-align: left;
            font-size: 1.1em;
        }
        .faq-question:hover {
            background: #f8f9fa;
        }
        .faq-answer {
            padding: 0 25px 25px;
            color: #666;
            line-height: 1.6;
            display: none;
        }
        .faq-answer.show {
            display: block;
        }
        
        /* 页脚 */
        .footer {
            background: #333;
            color: white;
            padding: 40px 0;
            text-align: center;
        }
        .footer-content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        .footer-links {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .footer-links a {
            color: white;
            text-decoration: none;
            opacity: 0.8;
            transition: opacity 0.3s;
        }
        .footer-links a:hover {
            opacity: 1;
        }
        
        
        /* 响应式设计 */
        @media (max-width: 768px) {
            .nav-links {
                display: none;
            }
            .hero h1 {
                font-size: 2.5em;
            }
            .hero h2 {
                font-size: 1.2em;
            }
            .stats-container {
                grid-template-columns: repeat(2, 1fr);
            }
            .features-grid {
                grid-template-columns: 1fr;
            }
            .pricing-cards {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>

    <!-- 主要内容 -->
    <main class="main-content">
        <!-- 英雄区域 -->
        <section class="hero">
            <div class="hero-content">
                <div class="version-badge">TYGTO v137.5.0 已发布</div>
                <h1>用终极扑克 RTA 统治扑克桌</h1>
                <h2>通过先进的扑克策略和实时 AI 分析解锁您的获胜潜力，统治每一手牌</h2>
                <div class="hero-buttons">
                    <button class="btn btn-outline" onclick="copyWechat()">微信: GGteam6</button>
                    <a href="https://t.me/horseking6670" class="btn btn-primary" target="_blank">Telegram</a>
                </div>
            </div>
        </section>

        <!-- 统计数据 -->
        <section class="stats">
            <div class="stats-container">
                <div class="stat-item">
                    <div class="stat-number">500万+</div>
                    <div class="stat-label">手牌</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">3-6BB+</div>
                    <div class="stat-label">100手牌(抽水)</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">100万+</div>
                    <div class="stat-label">解决方案</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">0</div>
                    <div class="stat-label">封禁</div>
                </div>
            </div>
        </section>

        <!-- 功能区域 -->
        <section class="features">
            <div class="features-container">
                <h2 class="section-title">TYGTO</h2>
                <h3 class="section-subtitle">用我们强大的扑克引擎智胜对手，专为长期盈利和持续获胜而设计</h3>
                <p style="text-align: center; font-size: 1.1em; color: #666; margin-bottom: 60px;">
                    <strong>TYGTO 玩家实现了 6bb/100 手牌(抽水)的胜率。</strong>
                </p>
                
                <h3 class="section-title">我们提升您的胜率</h3>
                <p class="section-subtitle">我们可以帮助您实现 3-6bb/100手牌(抽水)的长期胜率</p>
                
                <div class="features-grid">
                    <div class="feature-card">
                        <div class="feature-icon">🎯</div>
                        <h3 class="feature-title">高级策略</h3>
                        <p class="feature-desc">由 GTO 专家开发的 1,000,000+ 自定义解决方案，优化长期胜率，专为实时扑克量身定制。</p>
                    </div>
                    <div class="feature-card">
                        <div class="feature-icon">🤖</div>
                        <h3 class="feature-title">AI 分析</h3>
                        <p class="feature-desc">来自超过 10,000,000 手牌的分析洞察。AI 通过分析大量扑克手牌识别获胜策略。</p>
                    </div>
                    <div class="feature-card">
                        <div class="feature-icon">🔒</div>
                        <h3 class="feature-title">安全性</h3>
                        <p class="feature-desc">TYGTO 没有封禁记录。我们使用图像识别和特殊保护技术来最小化风险并确保您的账户安全。</p>
                    </div>
                </div>
                
                <div style="text-align: center; margin-top: 60px;">
                    <h3 class="section-title">持续跟踪您的盈利能力</h3>
                    <p class="section-subtitle">确保用户隐私和数据安全，我们的分析平台基于玩家数据持续训练策略模型，不断优化策略以适应玩家池的变化。</p>
                </div>
                
                <div style="text-align: center; margin-top: 60px;">
                    <h3 class="section-title">开箱即用</h3>
                    <p class="section-subtitle">我们的软件非常用户友好，无需复杂的设置。几乎所有设置都是自动配置的，让您可以立即开始使用并专注于真正重要的事情。</p>
                </div>
            </div>
        </section>

        <!-- 用户成功案例 -->
        {% if examples %}
        <section class="features" id="examples">
            <div class="features-container">
                <h2 class="section-title">用户成功案例</h2>
                <p class="section-subtitle">来自用户提交的真实战绩与反馈（部分截图）</p>
                <div class="examples-grid">
                    {% for img in examples %}
                    <div class="example-card">
                        <img src="{{ img }}" alt="example">
                    </div>
                    {% endfor %}
                </div>
            </div>
        </section>
        {% endif %}


        <!-- FAQ 区域 -->
        <section class="faq">
            <div class="faq-container">
                <h2 class="section-title">常见问题</h2>
                
                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        TYGTO 兼容哪些扑克网站或平台？
                    </button>
                    <div class="faq-answer">
                        GGPoker 和所有 GG 网络皮肤，如 Natural8、7XL Poker、Olybet Poker、WSOP.CA、GGPuke 等。仅支持 6max 游戏。如果您对其他平台有需求，请联系我们。
                    </div>
                </div>

                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        系统要求是什么？（4-6 桌）
                    </button>
                    <div class="faq-answer">
                        <strong>Windows 平台：</strong>Windows 11 是必需的。如果您打算同时玩 4-6 桌，建议使用 NVIDIA GTX 2060 Super 6GB 或更高 GPU。此外，需要最低 2K 分辨率的显示器。如果您没有 NVIDIA GPU，需要 Intel i7-13700KF 或 AMD 7900X 或更高处理器来支持四桌游戏。<br><br>
                        <strong>macOS 平台：</strong>不支持 Intel 芯片的 Mac 设备。要同时玩 4-6 桌，需要配备至少 M4 或 M3 Pro 芯片的 Mac。
                    </div>
                </div>

                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        TYGTO 有防检测功能吗？
                    </button>
                    <div class="faq-answer">
                        该软件采用最先进的防检测功能，目前未被扑克平台检测到。但是，没有软件可以保证完全免疫扑克网站安全措施的检测。
                    </div>
                </div>

                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        TYGTO 容易设置和使用吗？
                    </button>
                    <div class="faq-answer">
                        足够简单，可以自行安装。对于 Windows 系统，需要一些额外的安全设置，但按照文档说明可以快速完成安装。
                    </div>
                </div>

                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        我可以试用吗？有特别优惠吗？
                    </button>
                    <div class="faq-answer">
                        为了更好地服务客户，我们提供试用。
                    </div>
                </div>

                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        我可以在多少台电脑上使用许可证？
                    </button>
                    <div class="faq-answer">
                        仅限单设备使用。如果您需要切换设备，请联系我们。
                    </div>
                </div>

                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        软件更新包含在内吗？多久更新一次？
                    </button>
                    <div class="faq-answer">
                        是的，更新包含在内。定期每月更新包括策略增强和错误修复。
                    </div>
                </div>

                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        TYGTO 能保证我在扑克中获胜吗？
                    </button>
                    <div class="faq-answer">
                        我们无法保证短期盈利，因为扑克具有短期波动性。但是，通过纪律性游戏可以实现统计上可预测的长期回报。
                    </div>
                </div>

                <div class="faq-item">
                    <button class="faq-question" onclick="toggleFaq(this)">
                        使用 TYGTO 最多可以同时打开多少桌？
                    </button>
                    <div class="faq-answer">
                        TYGTO 最多支持同时 6 桌。所有桌子的性能保持一致。
                    </div>
                </div>
            </div>
        </section>
    </main>

    <!-- 页脚 -->
    <footer class="footer">
        <div class="footer-content">
            <div class="footer-links">
                <a href="#terms">条款与条件</a>
                <a href="#refund">退款政策</a>
            </div>
            <p>TYGTO ©️ 2025</p>
        </div>
    </footer>

    <script>
        function toggleFaq(element) {
            const answer = element.nextElementSibling;
            const isOpen = answer.classList.contains('show');
            
            // 关闭所有其他 FAQ
            document.querySelectorAll('.faq-answer').forEach(el => el.classList.remove('show'));
            
            // 切换当前 FAQ
            if (!isOpen) {
                answer.classList.add('show');
            }
        }
        
        function copyWechat() {
            navigator.clipboard.writeText('GGteam6').then(function() {
                alert('微信账号已复制到剪贴板: GGteam6');
            }).catch(function(err) {
                // 如果复制失败，显示提示
                alert('微信账号: GGteam6');
            });
        }
        
        // 平滑滚动
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function (e) {
                e.preventDefault();
                const target = document.querySelector(this.getAttribute('href'));
                if (target) {
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            });
        });
    </script>
</body>
</html>
'''

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
        .plan-pro {
            color: #667eea;
            font-weight: 600;
            background: #e8f2ff;
            padding: 4px 8px;
            border-radius: 4px;
        }
        .plan-premium {
            color: #f39c12;
            font-weight: 600;
            background: #fef5e7;
            padding: 4px 8px;
            border-radius: 4px;
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
                            <th>计划</th>
                            <th>HWID</th>
                        <th>到期时间</th>
                            <th>Stake Level</th>
                            <th>GGID</th>
                        <th>状态</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                        {% for lic in licenses %}
                        <tr>
                            <td><code>{{ lic.license_key }}</code></td>
                            <td><span class="plan-{{ lic.plan.lower() }}">{{ lic.plan }}</span></td>
                            <td><small>{{ lic.hwid[:20] if lic.hwid else '未绑定' }}</small></td>
                            <td>{{ lic.expiry_date.strftime('%Y-%m-%d %H:%M') }}</td>
                            <td>{{ lic.stake_level }}</td>
                            <td>{{ lic.ggid if lic.ggid else '未设置' }}</td>
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
                            <label>计划类型</label>
                            <select name="plan" required>
                                <option value="Pro">Pro</option>
                                <option value="Premium">Premium</option>
                            </select>
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

from flask import send_from_directory
import os

@app.route('/resource/<path:filename>')
def resource_file(filename):
    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resource')
    return send_from_directory(base_path, filename)

@app.route('/')
def index():
    """首页 - 定价页面（含用户成功案例展示）"""
    # Collect example images from ./resource folder
    resource_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resource')
    examples = []
    try:
        if os.path.isdir(resource_dir):
            for name in sorted(os.listdir(resource_dir)):
                lower = name.lower()
                if lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    examples.append(f'/resource/{name}')
    except Exception:
        pass
    return render_template_string(PRICING_HTML, examples=examples)

@app.route('/admin')
def admin_dashboard():
    """管理后台 - Dashboard"""
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
            return redirect(url_for('admin_dashboard'))
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
        plan = request.form.get('plan', 'Pro').strip()
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
            INSERT INTO licenses (license_key, expiry_date, plan, stake_level, max_devices, email, ggid, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (license_key, expiry_date, plan, stake_level, max_devices, email or None, ggid or None, notes or None))
        
        db.commit()
        db.close()
        
        log_action('创建 License', license_key, f'有效期: {days}天, 计划: {plan}, Stake: {stake_level}')
        
        session['message'] = f'✅ License 创建成功！Key: {license_key}'
        session['message_type'] = 'success'
        
    except Exception as e:
        session['message'] = f'❌ 创建失败: {str(e)}'
        session['message_type'] = 'error'
    
    return redirect(url_for('admin_dashboard'))

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
    
    return redirect(url_for('admin_dashboard'))

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
    
    return redirect(url_for('admin_dashboard'))

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

@app.route('/migrate-plan')
def migrate_plan():
    """迁移：添加 plan 字段"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # 检查列是否存在
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='licenses' AND column_name='plan'
        """)
        
        if not cursor.fetchone():
            cursor.execute('ALTER TABLE licenses ADD COLUMN plan VARCHAR(20) DEFAULT \'Pro\'')
            # 更新现有记录为 Pro
            cursor.execute("UPDATE licenses SET plan = 'Pro' WHERE plan IS NULL")
            db.commit()
            db.close()
            return '✅ Plan 字段添加成功！所有现有 License 已设置为 Pro', 200
        else:
            db.close()
            return '⚠️  Plan 字段已存在', 200
        
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
