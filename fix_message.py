#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复lottery_handlers.py中的消息内容
"""

with open('choujiang/lottery_handlers.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复无参与条件时的消息（第一个情况）
content = content.replace(
    'f"✅ @{user.username or user.first_name} 您的积分满足参与条件！\\n\\n"\n                f"请点击下方按钮前往与机器人私聊，检查是否满足其他参与条件。\\n",',
    'f"✅ @{user.username or user.first_name} 您的积分满足参与条件！\\n\\n"\n                f"请点击下方按钮前往与机器人私聊，以完成抽奖参与。\\n"\n                f"这样我们才能在您中奖时通知您！",')

# 同时检查并修复第二种格式的消息文本
content = content.replace(
    'f"✅ @{user.username or user.first_name} 您的积分满足参与条件！\\n\\n"\n            f"请点击下方按钮前往与机器人私聊，检查是否满足其他参与条件。\\n",',
    'f"✅ @{user.username or user.first_name} 您的积分满足参与条件！\\n\\n"\n            f"请点击下方按钮前往与机器人私聊，以完成抽奖参与。\\n"\n            f"这样我们才能在您中奖时通知您！",')

with open('choujiang/lottery_handlers.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('成功修复所有消息内容！') 