import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from asgiref.sync import sync_to_async
from .models import Group, PointRule

# 设置日志
logger = logging.getLogger(__name__)

async def show_points_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id=None, query=None):
    """显示积分总开关设置菜单"""
    user = update.effective_user
    logger.info(f"用户 {user.id} ({user.full_name}) 正在查看积分总开关设置")
    
    if query is None:
        query = update.callback_query
        # 尝试回答查询，但处理可能的超时错误
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 确定我们是在哪个群组的上下文中
    chat_id = None
    back_button_callback = "menu"
    
    if group_id is not None:
        # 如果提供了群组ID，使用它
        chat_id = group_id
        back_button_callback = f"group_{group_id}"
        logger.info(f"使用提供的群组ID: {group_id}")
    else:
        # 否则尝试获取当前聊天的ID
        chat_id = update.effective_chat.id
        logger.info(f"使用当前聊天ID: {chat_id}")
    
    # 创建键盘按钮
    keyboard = [
        [InlineKeyboardButton("✅ 启用积分功能", callback_data=f"enable_points_{chat_id}" if group_id else "enable_points"),
         InlineKeyboardButton("❌ 关闭积分功能", callback_data=f"disable_points_{chat_id}" if group_id else "disable_points")],
        [
            InlineKeyboardButton("🔧 签到规则", callback_data=f"checkin_rule_{chat_id}" if group_id else "checkin_rule"),
            InlineKeyboardButton("🔧 发言规则", callback_data=f"message_rule_{chat_id}" if group_id else "message_rule")
        ],
        [
            InlineKeyboardButton("🔧 邀请规则", callback_data=f"invite_rule_{chat_id}" if group_id else "invite_rule")
        ],
        [
            InlineKeyboardButton("◀️ 返回", callback_data=back_button_callback)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 获取当前群组的积分规则
    try:
        # 使用sync_to_async包装数据库操作
        @sync_to_async
        def get_point_rule(group_id):
            try:
                group = Group.objects.get(group_id=group_id)
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'points_enabled': True
                    }
                )
                return rule, group.group_title
            except Exception as e:
                logger.error(f"获取群组或积分规则时出错: {e}")
                return None, None
        
        rule_info = await get_point_rule(chat_id)
        if rule_info[0]:
            rule, group_title = rule_info
            
            # 显示当前积分规则
            message_text = (
                f"群组 {group_title} 的积分设置\n\n"
                f"积分功能: {'✅ 已启用' if rule.points_enabled else '❌ 已关闭'}\n\n"
                f"当前积分规则设置:\n"
                f"• 签到: 发送\"{rule.checkin_keyword}\" 获得 {rule.checkin_points} 积分\n"
                f"• 发言: 每条消息 {rule.message_points} 积分，每日上限 {rule.message_daily_limit} 积分\n"
                f"• 邀请: 每邀请一人 {rule.invite_points} 积分，每日上限 {'无限制' if rule.invite_daily_limit == 0 else rule.invite_daily_limit} 积分"
            )
            
            # 使用try-except块包装消息编辑操作
            try:
                await query.edit_message_text(
                    text=message_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"编辑消息时出错: {e}")
                # 如果编辑失败，尝试发送新消息
                try:
                    await update.effective_chat.send_message(
                        text=message_text,
                        reply_markup=reply_markup
                    )
                except Exception as send_error:
                    logger.error(f"发送新消息也失败: {send_error}")
        else:
            # 没有找到规则
            message_text = f"获取群组 {chat_id} 的积分规则时出错，可能是群组不存在或机器人未添加到该群组"
            
            try:
                await query.edit_message_text(
                    text=message_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"编辑错误消息时出错: {e}")
                try:
                    await update.effective_chat.send_message(
                        text=message_text,
                        reply_markup=reply_markup
                    )
                except Exception as send_error:
                    logger.error(f"发送新错误消息也失败: {send_error}")
            
    except Exception as e:
        logger.error(f"获取积分规则时出错: {e}")
        # 使用try-except块包装消息编辑操作
        try:
            await query.edit_message_text(
                text=f"获取群组 {chat_id} 的积分规则时出错，请稍后再试",
                reply_markup=reply_markup
            )
        except Exception as edit_error:
            logger.error(f"编辑错误消息时出错: {edit_error}")
            # 如果编辑失败，尝试发送新消息
            try:
                await update.effective_chat.send_message(
                    text=f"获取群组 {chat_id} 的积分规则时出错，请稍后再试",
                    reply_markup=reply_markup
                )
            except Exception as send_error:
                logger.error(f"发送新错误消息也失败: {send_error}")

async def enable_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """启用积分功能"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在启用积分功能")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    
    if callback_data.startswith("enable_points_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[2])
        logger.info(f"用户正在启用群组 {group_id} 的积分功能")
    else:
        logger.info(f"用户正在启用当前聊天的积分功能")
    
    # 获取当前积分设置
    chat_id = group_id if group_id else update.effective_chat.id
    
    # 更新数据库
    @sync_to_async
    def update_points_status(chat_id, enabled):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'points_enabled': enabled
                }
            )
            
            # 更新启用状态
            rule.points_enabled = enabled
            rule.save()
            
            logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的积分功能已{'启用' if enabled else '关闭'}")
            return True
        except Exception as e:
            logger.error(f"更新积分功能状态时出错: {e}", exc_info=True)
            return False
    
    success = await update_points_status(chat_id, True)
    
    if success:
        # 返回更新后的积分规则设置页面
        await show_points_settings(update, context, group_id, query)
    else:
        # 显示错误消息
        try:
            await query.edit_message_text(
                text="更新积分功能状态时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data="menu")]
                ])
            )
        except Exception as e:
            logger.error(f"显示错误消息时出错: {e}")

async def disable_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """关闭积分功能"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在关闭积分功能")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    
    if callback_data.startswith("disable_points_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[2])
        logger.info(f"用户正在关闭群组 {group_id} 的积分功能")
    else:
        logger.info(f"用户正在关闭当前聊天的积分功能")
    
    # 获取当前积分设置
    chat_id = group_id if group_id else update.effective_chat.id
    
    # 更新数据库
    @sync_to_async
    def update_points_status(chat_id, enabled):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'points_enabled': enabled
                }
            )
            
            # 更新启用状态
            rule.points_enabled = enabled
            rule.save()
            
            logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的积分功能已{'启用' if enabled else '关闭'}")
            return True
        except Exception as e:
            logger.error(f"更新积分功能状态时出错: {e}", exc_info=True)
            return False
    
    success = await update_points_status(chat_id, False)
    
    if success:
        # 返回更新后的积分规则设置页面
        await show_points_settings(update, context, group_id, query)
    else:
        # 显示错误消息
        try:
            await query.edit_message_text(
                text="更新积分功能状态时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data="menu")]
                ])
            )
        except Exception as e:
            logger.error(f"显示错误消息时出错: {e}") 