"""
Gunicorn 配置 - 企业级生产环境
"""
import os

# 服务器配置
bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
worker_class = 'geventwebsocket.gunicorn.workers.GeventWebSocketWorker'

# Worker 配置
workers = int(os.getenv('WEB_CONCURRENCY', '2'))  # Railway 推荐 2-4 个
worker_connections = 1000
timeout = 120
keepalive = 5

# 日志配置
accesslog = '-'  # 输出到 stdout
errorlog = '-'   # 输出到 stderr
loglevel = 'info'

# 进程命名
proc_name = 'gto-server'

# 安全
limit_request_line = 4094
limit_request_fields = 100

# 性能优化
preload_app = True  # 预加载应用
max_requests = 1000  # 重启前处理的最大请求数
max_requests_jitter = 50  # 随机抖动避免同时重启

# Socket.IO 优化
worker_tmp_dir = '/dev/shm'  # 使用共享内存（如果可用）

print('=' * 60)
print('🚀 GTO 服务器 - 企业级生产配置')
print('=' * 60)
print(f'绑定地址: {bind}')
print(f'Workers: {workers}')
print(f'Worker类: {worker_class}')
print(f'超时: {timeout}秒')
print(f'日志级别: {loglevel}')
print('=' * 60)

