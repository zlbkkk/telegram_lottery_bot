import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from django.utils import timezone
from .models import Group, PointRule

# 设置日志
logger = logging.getLogger(__name__)

async def show_checkin_rule_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """显示签到规则设置菜单"""
    if query is None:
        query = update.callback_query
    
    # 创建两个按钮：修改签到文字、设置获取数量
    keyboard = [
        [
            InlineKeyboardButton("🔧 修改签到文字", callback_data="edit_checkin_text"),
            InlineKeyboardButton("🔧 设置获得数量", callback_data="set_checkin_points")
        ],
        [
            InlineKeyboardButton("◀️ Back 返回", callback_data="back_to_points_setting")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 获取当前群组的签到规则
    chat_id = update.effective_chat.id
    try:
        group = Group.objects.get(group_id=chat_id)
        rule, created = PointRule.objects.get_or_create(
            group=group,
            defaults={
                'checkin_keyword': '签到',
                'checkin_points': 1
            }
        )
        
        # 显示当前签到规则
        message_text = (
            f"积分\n\n"
            f"签到积分规则:发送\"{rule.checkin_keyword}\"，每日签到获得:{rule.checkin_points}积分"
        )
        
        await query.edit_message_text(
            text=message_text,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"获取签到规则时出错: {e}")
        await query.edit_message_text(
            text="获取签到规则时出错，请稍后再试",
            reply_markup=reply_markup
        )

async def edit_checkin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理修改签到文字的请求"""
    query = update.callback_query
    await query.answer()
    
    # 此处应实现修改签到文字的逻辑
    # 在实际实现中，可能需要进入一个对话状态来接收用户输入的新签到文字
    await query.edit_message_text(
        text="请输入新的签到文字（功能开发中...）",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back 返回", callback_data="back_to_checkin_rule")]
        ])
    )

async def set_checkin_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置签到积分数量的请求"""
    query = update.callback_query
    await query.answer()
    
    # 此处应实现设置签到积分数量的逻辑
    # 在实际实现中，可能需要进入一个对话状态来接收用户输入的新积分数量
    await query.edit_message_text(
        text="请输入签到可获得的积分数量（功能开发中...）",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back 返回", callback_data="back_to_checkin_rule")]
        ])
    )

async def back_to_points_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回到积分设置主菜单"""
    query = update.callback_query
    await query.answer()
    
    # 创建积分设置的三个按钮
    keyboard = [
        [
            InlineKeyboardButton("🔧 签到规则", callback_data="checkin_rule"),
            InlineKeyboardButton("🔧 发言规则", callback_data="message_rule"),
            InlineKeyboardButton("🔧 邀请规则", callback_data="invite_rule")
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="请选择要查看的积分规则：",
        reply_markup=reply_markup
    )

async def back_to_checkin_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回到签到规则设置"""
    query = update.callback_query
    await query.answer()
    
    # 返回到签到规则设置菜单
    await show_checkin_rule_settings(update, context, query) 