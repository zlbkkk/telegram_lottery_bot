#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修改lottery_handlers.py中的注释，使其与实际自动删除时间一致
"""

with open('choujiang/lottery_handlers.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 将注释从30秒改为10秒
content = content.replace(
    '# 设置30秒后自动删除消息',
    '# 设置10秒后自动删除消息')

with open('choujiang/lottery_handlers.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('成功修改所有注释，使其与实际自动删除时间一致！') 