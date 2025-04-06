#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
将lottery_handlers.py中的消息自动删除时间都修改为10秒
"""

with open('choujiang/lottery_handlers.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 将第二个删除消息函数中的延迟时间从15秒改为10秒
content = content.replace(
    'async def delete_message_later():\n            await asyncio.sleep(15)',
    'async def delete_message_later():\n            await asyncio.sleep(10)')

with open('choujiang/lottery_handlers.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('成功修改所有消息自动删除时间为10秒！') 