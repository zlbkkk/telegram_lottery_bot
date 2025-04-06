#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import traceback
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from asgiref.sync import sync_to_async

# 设置日志记录
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 每页显示的抽奖数量
LOTTERIES_PER_PAGE = 9  # 3行x3列 = 9个抽奖

async def view_group_lotteries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示指定群组的抽奖列表"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取群组ID和页码
        callback_data_parts = query.data.split('_')
        group_id = int(callback_data_parts[2])
        page = 1  # 默认第一页
        
        # 如果有页码参数，解析页码
        if len(callback_data_parts) > 3:
            try:
                page = int(callback_data_parts[3])
            except ValueError:
                page = 1
        
        logger.info(f"[查看群组抽奖] 用户 {user.id} 请求查看群组ID={group_id}的抽奖列表，页码={page}")
        
        # 获取群组名称
        group_name = await get_group_name(group_id)
        
        # 获取群组的抽奖列表
        lotteries = await get_group_lotteries(group_id, page, LOTTERIES_PER_PAGE)
        total_pages = await get_total_pages(group_id, LOTTERIES_PER_PAGE)
        
        if not lotteries:
            # 如果没有抽奖，显示提示信息
            keyboard = [
                [InlineKeyboardButton("◀️ 返回", callback_data=f"group_{group_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"📊 {group_name} 的抽奖列表\n\n"
                f"目前没有设置任何抽奖活动。",
                reply_markup=reply_markup
            )
            return
        
        # 构建抽奖列表按钮
        buttons = []
        current_row = []
        
        for i, lottery in enumerate(lotteries):
            # 创建一个包含状态标志的按钮文本
            status_emoji = "🟢" if lottery['status'] == 'ACTIVE' else "⚪"
            button_text = f"{status_emoji} {lottery['title']}"
            
            current_row.append(InlineKeyboardButton(
                button_text, 
                callback_data=f"view_lottery_{lottery['id']}"
            ))
            
            # 每3个按钮一行
            if (i + 1) % 3 == 0 or i == len(lotteries) - 1:
                buttons.append(current_row)
                current_row = []
        
        # 添加分页按钮
        nav_buttons = []
        
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"list_lotteries_{group_id}_{page-1}"))
        
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"list_lotteries_{group_id}_{page+1}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        # 添加返回按钮
        buttons.append([InlineKeyboardButton("◀️ 返回", callback_data=f"group_{group_id}")])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        # 构建消息文本
        text = f"📊 {group_name} 的抽奖列表 (第{page}/{total_pages}页)\n\n"
        text += "点击抽奖查看详情\n"
        text += "🟢 = 进行中的抽奖  ⚪ = 其他状态\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"[查看群组抽奖] 处理查看群组抽奖列表时出错: {e}\n{traceback.format_exc()}")
        
        # 尝试从上下文中获取群组ID
        group_id = None
        try:
            callback_data_parts = query.data.split('_')
            if len(callback_data_parts) > 2:
                group_id = int(callback_data_parts[2])
        except:
            pass
        
        # 创建返回按钮
        keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data=f"group_{group_id}" if group_id else "back_to_groups")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "处理请求时出错，请重试。",
            reply_markup=reply_markup
        )

@sync_to_async
def get_group_name(group_id):
    """获取群组名称"""
    from jifen.models import Group
    try:
        group = Group.objects.get(group_id=group_id)
        return group.group_title or "未知群组"
    except Group.DoesNotExist:
        return "未知群组"
    except Exception as e:
        logger.error(f"获取群组名称时出错: {e}")
        return "未知群组"

@sync_to_async
def get_group_lotteries(group_id, page, page_size):
    """获取指定群组的抽奖列表"""
    from choujiang.models import Lottery
    from jifen.models import Group
    
    try:
        # 计算偏移量
        offset = (page - 1) * page_size
        
        # 获取群组
        group = Group.objects.get(group_id=group_id)
        
        # 获取该群组的所有抽奖，按创建时间倒序排列
        lotteries = Lottery.objects.filter(group=group).order_by('-created_at')[offset:offset+page_size]
        
        result = []
        for lottery in lotteries:
            result.append({
                'id': lottery.id,
                'title': lottery.title,
                'status': lottery.status,
                'points_required': lottery.points_required,
                'created_at': lottery.created_at
            })
        
        return result
    except Group.DoesNotExist:
        logger.error(f"群组ID={group_id}不存在")
        return []
    except Exception as e:
        logger.error(f"获取群组抽奖列表时出错: {e}\n{traceback.format_exc()}")
        return []

@sync_to_async
def get_total_pages(group_id, page_size):
    """获取总页数"""
    from choujiang.models import Lottery
    from jifen.models import Group
    import math
    
    try:
        # 获取群组
        group = Group.objects.get(group_id=group_id)
        
        # 获取该群组的抽奖总数
        total_count = Lottery.objects.filter(group=group).count()
        
        # 计算总页数
        return max(1, math.ceil(total_count / page_size))
    except Exception as e:
        logger.error(f"计算总页数时出错: {e}")
        return 1 