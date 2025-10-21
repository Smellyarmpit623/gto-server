#!/usr/bin/env python3
"""
自动修复 app.py 中的数据库查询，使其兼容 PostgreSQL
"""

import re

# 读取文件
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 替换 cursor.execute 为 execute_query
# 匹配模式：cursor.execute(sql, params)
pattern = r'cursor\.execute\(\s*([\'"].*?[\'"])\s*,\s*(\([^)]*\))\s*\)'
replacement = r'execute_query(cursor, \1, \2)'

content = re.sub(pattern, replacement, content, flags=re.DOTALL)

# 替换不带参数的 cursor.execute
pattern2 = r'cursor\.execute\(\s*([\'"][^\'"]]+[\'"])\s*\)'
replacement2 = r'execute_query(cursor, \1)'

content = re.sub(pattern2, replacement2, content)

# 写回文件
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✅ 修复完成！')
print('📝 所有 cursor.execute 已替换为 execute_query')

