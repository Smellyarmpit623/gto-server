#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time

def test_server():
    """测试服务器是否正常运行"""
    base_url = "http://localhost:5000"
    
    print("正在测试服务器...")
    
    # 等待服务器启动
    time.sleep(3)
    
    try:
        # 测试首页（定价页面）
        print("测试首页 (定价页面)...")
        response = requests.get(f"{base_url}/", timeout=10)
        if response.status_code == 200:
            print("✅ 首页正常 - 状态码:", response.status_code)
            if "TYGTO" in response.text:
                print("✅ 页面内容包含 TYGTO")
            else:
                print("❌ 页面内容不包含 TYGTO")
        else:
            print("❌ 首页异常 - 状态码:", response.status_code)
            
        # 测试管理后台
        print("\n测试管理后台...")
        response = requests.get(f"{base_url}/admin", timeout=10)
        if response.status_code == 200:
            print("✅ 管理后台正常 - 状态码:", response.status_code)
        elif response.status_code == 302:
            print("✅ 管理后台重定向到登录页面 - 状态码:", response.status_code)
        else:
            print("❌ 管理后台异常 - 状态码:", response.status_code)
            
        # 测试登录页面
        print("\n测试登录页面...")
        response = requests.get(f"{base_url}/login", timeout=10)
        if response.status_code == 200:
            print("✅ 登录页面正常 - 状态码:", response.status_code)
        else:
            print("❌ 登录页面异常 - 状态码:", response.status_code)
            
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到服务器，请确保服务器正在运行")
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    test_server()
