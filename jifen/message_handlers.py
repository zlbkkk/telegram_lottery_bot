import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Chat
from telegram.ext import ContextTypes
from django.utils import timezone
from asgiref.sync import sync_to_async
from .models import Group, PointRule, DailyMessageStat, MessagePoint, PointTransaction, User
from django.db import transaction

# 设置日志
logger = logging.getLogger(__name__)

async def show_message_rule_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id=None, query=None):
    """显示发言规则设置菜单"""
    user = update.effective_user
    logger.info(f"用户 {user.id} ({user.full_name}) 正在查看发言规则设置")
    
    if query is None:
        query = update.callback_query
        # 尝试回答查询，但处理可能的超时错误
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 确定我们是在哪个群组的上下文中
    chat_id = None
    back_button_callback = "back_to_points_setting"
    
    if group_id is not None:
        # 如果提供了群组ID，使用它
        chat_id = group_id
        back_button_callback = f"points_setting_{group_id}"
        logger.info(f"使用提供的群组ID: {group_id}")
    else:
        # 否则尝试获取当前聊天的ID
        chat_id = update.effective_chat.id
        logger.info(f"使用当前聊天ID: {chat_id}")
    
    # 创建四个按钮：设置获得数量、每日上限、最小字数长度限制、返回
    keyboard = [
        [
            InlineKeyboardButton("⚙️ 设置获得数量", callback_data=f"set_message_points_{chat_id}" if group_id else "set_message_points"),
            InlineKeyboardButton("⚙️ 每日上限", callback_data=f"set_message_daily_limit_{chat_id}" if group_id else "set_message_daily_limit")
        ],
        [
            InlineKeyboardButton("⚙️ 最小字数长度限制", callback_data=f"set_message_min_length_{chat_id}" if group_id else "set_message_min_length")
        ],
        [
            InlineKeyboardButton("◀️ 返回", callback_data=back_button_callback)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 获取当前群组的发言规则
    try:
        # 使用sync_to_async包装数据库操作
        @sync_to_async
        def get_point_rule(group_id):
            try:
                group = Group.objects.get(group_id=group_id)
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'message_points': 1,
                        'message_daily_limit': 50
                    }
                )
                return rule, group.group_title
            except Exception as e:
                logger.error(f"获取群组或积分规则时出错: {e}")
                return None, None
        
        rule_info = await get_point_rule(chat_id)
        if rule_info[0]:
            rule, group_title = rule_info
            
            # 显示当前发言规则
            daily_limit_text = "无限制" if rule.message_daily_limit == 0 else str(rule.message_daily_limit)
            min_length_text = "无限制" if rule.message_min_length == 0 else str(rule.message_min_length)
            
            message_text = (
                f"群组 {group_title} 的积分设置\n\n"
                f"发言规则: 发言1次，获得{rule.message_points} 积分\n"
                f"每日获取上限: {daily_limit_text} 条\n"
                f"最小字数长度限制: {min_length_text}"
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
            message_text = f"获取群组 {chat_id} 的发言规则时出错，可能是群组不存在或机器人未添加到该群组"
            
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
        logger.error(f"获取发言规则时出错: {e}")
        # 使用try-except块包装消息编辑操作
        try:
            await query.edit_message_text(
                text=f"获取群组 {chat_id} 的发言规则时出错，请稍后再试",
                reply_markup=reply_markup
            )
        except Exception as edit_error:
            logger.error(f"编辑错误消息时出错: {edit_error}")
            # 如果编辑失败，尝试发送新消息
            try:
                await update.effective_chat.send_message(
                    text=f"获取群组 {chat_id} 的发言规则时出错，请稍后再试",
                    reply_markup=reply_markup
                )
            except Exception as send_error:
                logger.error(f"发送新错误消息也失败: {send_error}") 

async def set_message_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置发言积分数量的请求"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击设置发言获得数量按钮")
    logger.info(f"开始处理设置发言获得数量请求: {query.data}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    back_callback = "back_to_message_rule"
    
    if callback_data.startswith("set_message_points_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[3])
        back_callback = f"message_rule_{group_id}"
        logger.info(f"用户正在设置群组 {group_id} 的发言积分")
    else:
        logger.info(f"用户正在设置当前聊天的发言积分")
    
    # 获取当前积分设置
    chat_id = group_id if group_id else update.effective_chat.id
    logger.info(f"使用chat_id: {chat_id} 获取发言积分设置")
    
    @sync_to_async
    def get_current_points(chat_id):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'message_points': 1,
                    'message_daily_limit': 50
                }
            )
            logger.info(f"数据库查询结果: 群组={group.group_title}, 发言积分={rule.message_points}, 新创建={created}")
            return rule.message_points, group.group_title
        except Exception as e:
            logger.error(f"获取当前发言积分设置时出错: {e}", exc_info=True)
            return 1, "未知群组" # 默认值为1
    
    try:
        points_info = await get_current_points(chat_id)
        current_points, group_title = points_info
        
        logger.info(f"群组 {group_title} (ID: {chat_id}) 当前发言积分为: {current_points}")
        
        # 将用户置于等待输入状态
        context.user_data['waiting_for_message_points'] = True
        context.user_data['chat_id'] = chat_id
        context.user_data['back_callback'] = back_callback
        logger.info(f"已设置用户等待状态: waiting_for_message_points={True}, chat_id={chat_id}")
        
        # 创建界面内容，确保与图2格式一致
        message_text = f"发言积分\n\n当前设置:{current_points}\n\n👉 输入内容进行设置:"
        
        # 创建返回按钮，与图2一致
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # 发送提示消息，让用户输入积分数量
            await query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup
            )
            logger.info(f"已显示发言积分设置界面，等待用户输入")
            
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}", exc_info=True)
            try:
                await update.effective_chat.send_message(
                    text=message_text,
                    reply_markup=reply_markup
                )
                logger.info(f"通过新消息显示发言积分设置界面")
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}", exc_info=True)
                
    except Exception as e:
        logger.error(f"处理设置发言积分数量请求时出错: {e}", exc_info=True)
        try:
            await update.effective_chat.send_message(
                text="获取发言积分设置时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
        except Exception as msg_error:
            logger.error(f"发送错误消息失败: {msg_error}")

# 创建一个新函数来处理用户输入的发言积分数量
async def handle_message_points_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的发言积分数量"""
    # 检查用户是否在等待输入发言积分数量的状态
    if not context.user_data.get('waiting_for_message_points'):
        logger.debug(f"用户 {update.effective_user.id} 发送了消息，但不在等待输入发言积分状态")
        return
    
    user = update.effective_user
    text = update.message.text.strip()
    logger.info(f"用户 {user.id} ({user.full_name}) 正在设置发言积分数量为: {text}")
    
    # 获取群组ID
    chat_id = context.user_data.get('chat_id')
    back_callback = context.user_data.get('back_callback')
    
    if not chat_id:
        logger.error("找不到chat_id，用户状态可能已丢失")
        await update.message.reply_text("操作失败，请重试")
        return
    
    logger.info(f"处理用户输入，将为群组 {chat_id} 设置发言积分值: {text}")
    
    # 尝试将文本转换为整数
    try:
        points = int(text)
        if points < 0:
            logger.warning(f"用户尝试设置负数积分: {points}")
            await update.message.reply_text("积分不能为负数，请重新输入")
            return
    except ValueError:
        logger.warning(f"用户输入了无效数字: {text}")
        await update.message.reply_text("请输入有效的数字")
        return
    
    # 更新数据库
    @sync_to_async
    def update_points(chat_id, points):
        from django.db import transaction
        
        try:
            with transaction.atomic():  # 使用原子事务确保操作完整性
                group = Group.objects.get(group_id=chat_id)
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'message_points': 1,
                        'message_daily_limit': 50
                    }
                )
                
                # 记录旧值，便于日志
                old_points = rule.message_points
                
                # 更新积分值
                rule.message_points = points
                rule.save()
                
                # 确认数据已保存
                rule_check = PointRule.objects.get(id=rule.id)
                logger.info(f"验证保存: 更新后从数据库重新读取的积分值={rule_check.message_points}")
                
                logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的发言积分已从 {old_points} 更新为 {points}")
                return True, group.group_title
        except Exception as e:
            logger.error(f"更新发言积分设置时出错: {e}", exc_info=True)
            return False, "未知群组"
    
    result = await update_points(chat_id, points)
    success, group_title = result
    
    # 重置用户状态
    context.user_data.pop('waiting_for_message_points', None)
    context.user_data.pop('chat_id', None)
    context.user_data.pop('back_callback', None)
    
    if success:
        # 发送成功消息
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"发言积分设置成功，显示成功消息")
        await update.message.reply_text(
            f"✅ 设置成功，点击按钮返回。",
            reply_markup=reply_markup
        )
    else:
        logger.error(f"发言积分设置失败")
        await update.message.reply_text("设置失败，请重试")

async def set_message_daily_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置发言每日积分上限的请求"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击设置每日上限按钮")
    logger.info(f"开始处理设置每日上限请求: {query.data}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    back_callback = "back_to_message_rule"
    
    if callback_data.startswith("set_message_daily_limit_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[4])
        back_callback = f"message_rule_{group_id}"
        logger.info(f"用户正在设置群组 {group_id} 的每日上限")
    else:
        logger.info(f"用户正在设置当前聊天的每日上限")
    
    # 获取当前积分设置
    chat_id = group_id if group_id else update.effective_chat.id
    logger.info(f"使用chat_id: {chat_id} 获取每日上限设置")
    
    @sync_to_async
    def get_current_daily_limit(chat_id):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'message_points': 1,
                    'message_daily_limit': 50
                }
            )
            daily_limit_text = "无限制" if rule.message_daily_limit == 0 else str(rule.message_daily_limit)
            logger.info(f"数据库查询结果: 群组={group.group_title}, 每日上限={daily_limit_text}, 新创建={created}")
            return rule.message_daily_limit, group.group_title
        except Exception as e:
            logger.error(f"获取当前每日上限设置时出错: {e}", exc_info=True)
            return 50, "未知群组" # 默认值为50
    
    try:
        limit_info = await get_current_daily_limit(chat_id)
        current_limit, group_title = limit_info
        current_limit_text = "无限制" if current_limit == 0 else str(current_limit)
        
        logger.info(f"群组 {group_title} (ID: {chat_id}) 当前每日上限为: {current_limit_text}")
        
        # 将用户置于等待输入状态
        context.user_data['waiting_for_daily_limit'] = True
        context.user_data['chat_id'] = chat_id
        context.user_data['back_callback'] = back_callback
        logger.info(f"已设置用户等待状态: waiting_for_daily_limit={True}, chat_id={chat_id}")
        
        # 创建界面内容，确保与图2格式一致
        message_text = f"发言每日上限\n\n当前设置:{current_limit_text}\n\n👉 输入内容进行设置:"
        
        # 创建返回按钮，与图2一致
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # 发送提示消息，让用户输入每日上限
            await query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup
            )
            logger.info(f"已显示每日上限设置界面，等待用户输入")
            
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}", exc_info=True)
            try:
                await update.effective_chat.send_message(
                    text=message_text,
                    reply_markup=reply_markup
                )
                logger.info(f"通过新消息显示每日上限设置界面")
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}", exc_info=True)
                
    except Exception as e:
        logger.error(f"处理设置每日上限请求时出错: {e}", exc_info=True)
        try:
            await update.effective_chat.send_message(
                text="获取每日上限设置时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
        except Exception as msg_error:
            logger.error(f"发送错误消息失败: {msg_error}")

# 处理用户输入的每日上限
async def handle_daily_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的每日上限"""
    # 检查用户是否在等待输入每日上限的状态
    if not context.user_data.get('waiting_for_daily_limit'):
        logger.debug(f"用户 {update.effective_user.id} 发送了消息，但不在等待输入每日上限状态")
        return
    
    user = update.effective_user
    text = update.message.text.strip()
    logger.info(f"用户 {user.id} ({user.full_name}) 正在设置每日上限为: {text}")
    
    # 获取群组ID
    chat_id = context.user_data.get('chat_id')
    back_callback = context.user_data.get('back_callback')
    
    if not chat_id:
        logger.error("找不到chat_id，用户状态可能已丢失")
        await update.message.reply_text("操作失败，请重试")
        return
    
    logger.info(f"处理用户输入，将为群组 {chat_id} 设置每日上限值: {text}")
    
    # 尝试将文本转换为整数
    try:
        limit = int(text)
        if limit < 0:
            logger.warning(f"用户尝试设置负数上限: {limit}")
            await update.message.reply_text("上限不能为负数，请重新输入")
            return
    except ValueError:
        logger.warning(f"用户输入了无效数字: {text}")
        await update.message.reply_text("请输入有效的数字")
        return
    
    # 更新数据库
    @sync_to_async
    def update_daily_limit(chat_id, limit):
        from django.db import transaction
        
        try:
            with transaction.atomic():  # 使用原子事务确保操作完整性
                group = Group.objects.get(group_id=chat_id)
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'message_points': 1,
                        'message_daily_limit': 50
                    }
                )
                
                # 记录旧值，便于日志
                old_limit = rule.message_daily_limit
                old_limit_text = "无限制" if old_limit == 0 else str(old_limit)
                new_limit_text = "无限制" if limit == 0 else str(limit)
                
                # 更新每日上限值
                rule.message_daily_limit = limit
                rule.save()
                
                # 确认数据已保存
                rule_check = PointRule.objects.get(id=rule.id)
                check_limit_text = "无限制" if rule_check.message_daily_limit == 0 else str(rule_check.message_daily_limit)
                logger.info(f"验证保存: 更新后从数据库重新读取的每日上限={check_limit_text}")
                
                logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的每日上限已从 {old_limit_text} 更新为 {new_limit_text}")
                return True, group.group_title
        except Exception as e:
            logger.error(f"更新每日上限设置时出错: {e}", exc_info=True)
            return False, "未知群组"
    
    result = await update_daily_limit(chat_id, limit)
    success, group_title = result
    
    # 重置用户状态
    context.user_data.pop('waiting_for_daily_limit', None)
    context.user_data.pop('chat_id', None)
    context.user_data.pop('back_callback', None)
    
    if success:
        # 发送成功消息
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"每日上限设置成功，显示成功消息")
        await update.message.reply_text(
            f"✅ 设置成功，点击按钮返回。",
            reply_markup=reply_markup
        )
    else:
        logger.error(f"每日上限设置失败")
        await update.message.reply_text("设置失败，请重试")

async def set_message_min_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置最小字数长度限制的请求"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击设置最小字数长度限制按钮")
    logger.info(f"开始处理设置最小字数长度限制请求: {query.data}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    back_callback = "back_to_message_rule"
    
    if callback_data.startswith("set_message_min_length_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[4])
        back_callback = f"message_rule_{group_id}"
        logger.info(f"用户正在设置群组 {group_id} 的最小字数长度限制")
    else:
        logger.info(f"用户正在设置当前聊天的最小字数长度限制")
    
    # 获取当前设置
    chat_id = group_id if group_id else update.effective_chat.id
    logger.info(f"使用chat_id: {chat_id} 获取最小字数长度限制设置")
    
    @sync_to_async
    def get_current_min_length(chat_id):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'message_points': 1,
                    'message_daily_limit': 50,
                    'message_min_length': 0
                }
            )
            min_length_text = "无限制" if rule.message_min_length == 0 else str(rule.message_min_length)
            logger.info(f"数据库查询结果: 群组={group.group_title}, 最小字数长度限制={min_length_text}, 新创建={created}")
            return rule.message_min_length, group.group_title
        except Exception as e:
            logger.error(f"获取当前最小字数长度限制设置时出错: {e}", exc_info=True)
            return 0, "未知群组" # 默认值为0，表示无限制
    
    try:
        length_info = await get_current_min_length(chat_id)
        current_length, group_title = length_info
        current_length_text = "无限制" if current_length == 0 else str(current_length)
        
        logger.info(f"群组 {group_title} (ID: {chat_id}) 当前最小字数长度限制为: {current_length_text}")
        
        # 将用户置于等待输入状态
        context.user_data['waiting_for_min_length'] = True
        context.user_data['chat_id'] = chat_id
        context.user_data['back_callback'] = back_callback
        logger.info(f"已设置用户等待状态: waiting_for_min_length={True}, chat_id={chat_id}")
        
        # 创建界面内容，确保与图2格式一致
        message_text = f"发言最小字数\n\n当前设置:{current_length_text}\n\n👉 输入内容进行设置:"
        
        # 创建返回按钮，与图2一致
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # 发送提示消息，让用户输入最小字数长度限制
            await query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup
            )
            logger.info(f"已显示最小字数长度限制设置界面，等待用户输入")
            
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}", exc_info=True)
            try:
                await update.effective_chat.send_message(
                    text=message_text,
                    reply_markup=reply_markup
                )
                logger.info(f"通过新消息显示最小字数长度限制设置界面")
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}", exc_info=True)
    except Exception as e:
        logger.error(f"处理设置最小字数长度限制请求时出错: {e}", exc_info=True)
        try:
            await update.effective_chat.send_message(
                text="获取最小字数长度限制设置时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
        except Exception as msg_error:
            logger.error(f"发送错误消息失败: {msg_error}")

# 处理用户输入的最小字数长度限制
async def handle_min_length_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的最小字数长度限制"""
    # 检查用户是否在等待输入最小字数长度限制的状态
    if not context.user_data.get('waiting_for_min_length'):
        logger.debug(f"用户 {update.effective_user.id} 发送了消息，但不在等待输入最小字数长度限制状态")
        return
    
    user = update.effective_user
    text = update.message.text.strip()
    logger.info(f"用户 {user.id} ({user.full_name}) 正在设置最小字数长度限制为: {text}")
    
    # 获取群组ID
    chat_id = context.user_data.get('chat_id')
    back_callback = context.user_data.get('back_callback')
    
    if not chat_id:
        logger.error("找不到chat_id，用户状态可能已丢失")
        await update.message.reply_text("操作失败，请重试")
        return
    
    logger.info(f"处理用户输入，将为群组 {chat_id} 设置最小字数长度限制值: {text}")
    
    # 尝试将文本转换为整数
    try:
        min_length = int(text)
        if min_length < 0:
            logger.warning(f"用户尝试设置负数最小字数长度限制: {min_length}")
            await update.message.reply_text("最小字数不能为负数，请重新输入")
            return
    except ValueError:
        logger.warning(f"用户输入了无效数字: {text}")
        await update.message.reply_text("请输入有效的数字")
        return
    
    # 更新数据库中的最小字数长度限制
    @sync_to_async
    def update_min_length(chat_id, min_length):
        from django.db import transaction
        
        try:
            with transaction.atomic():  # 使用原子事务确保操作完整性
                group = Group.objects.get(group_id=chat_id)
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'message_points': 1,
                        'message_daily_limit': 50,
                        'message_min_length': 0
                    }
                )
                
                # 记录旧值，便于日志
                old_length = rule.message_min_length
                old_length_text = "无限制" if old_length == 0 else str(old_length)
                
                # 更新最小字数长度限制值
                rule.message_min_length = min_length
                rule.save()
                
                new_length_text = "无限制" if min_length == 0 else str(min_length)
                logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的最小字数长度限制已从 {old_length_text} 更新为 {new_length_text}")
                
                # 验证保存是否成功
                rule_check = PointRule.objects.get(id=rule.id)
                logger.info(f"验证保存: 更新后从数据库重新读取的最小字数长度限制值={rule_check.message_min_length}")
                
                return True, group.group_title
        except Exception as e:
            logger.error(f"更新最小字数长度限制设置时出错: {e}", exc_info=True)
            return False, "未知群组"
    
    result = await update_min_length(chat_id, min_length)
    success, group_title = result
    
    # 重置用户状态
    context.user_data.pop('waiting_for_min_length', None)
    context.user_data.pop('chat_id', None)
    context.user_data.pop('back_callback', None)
    
    if success:
        # 发送成功消息
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        min_length_text = "无限制" if min_length == 0 else str(min_length)
        logger.info(f"最小字数长度限制设置成功，显示成功消息")
        await update.message.reply_text(
            f"✅ 设置成功，最小字数长度限制已设为 {min_length_text}。点击按钮返回。",
            reply_markup=reply_markup
        )
    else:
        logger.error(f"最小字数长度限制设置失败")
        await update.message.reply_text("设置失败，请重试")

async def back_to_message_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回到发言规则设置"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击返回发言规则按钮")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    
    if callback_data.startswith("message_rule_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[2])
    
    # 返回到发言规则设置菜单
    await show_message_rule_settings(update, context, group_id, query)

async def process_message_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群聊中的消息，根据发言规则更新用户积分
    """
    # 跳过非文本消息
    if not update.message or not update.message.text:
        logger.debug("跳过非文本消息")
        return
    
    # 跳过非群组消息
    chat = update.effective_chat
    if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        logger.debug(f"跳过非群组消息，当前类型: {chat.type}")
        return
    
    # 获取消息内容和发送者
    text = update.message.text.strip()
    user = update.effective_user
    chat_id = chat.id
    message_id = update.message.message_id
    
    logger.info(f"开始处理群组 {chat_id} 中用户 {user.id} ({user.full_name}) 的发言积分, 消息ID: {message_id}, 消息内容: {text[:20]}...")
    
    try:
        # 处理发言积分
        @sync_to_async
        def process_message_points_for_user(chat_id, user_id, message_id, text):
            try:
                # 获取群组对象
                logger.info(f"尝试获取群组对象: {chat_id}")
                group = Group.objects.get(group_id=chat_id, is_active=True)
                logger.info(f"成功获取群组: {group.group_title} (ID: {group.id})")
                
                # 获取该群组的积分规则
                logger.info(f"尝试获取群组积分规则")
                rule = PointRule.objects.filter(group=group).first()
                logger.info(f"积分规则获取结果: {'成功' if rule else '失败'}")
                
                if not rule:
                    logger.warning(f"群组 {chat_id} 未设置积分规则")
                    return None, None, None
                
                logger.info(f"积分规则: points_enabled={rule.points_enabled}, message_points={rule.message_points}, daily_limit={rule.message_daily_limit}, min_length={rule.message_min_length}")
                
                if not rule.points_enabled:
                    logger.warning(f"群组 {chat_id} 的积分功能已关闭")
                    return None, None, None
                
                # 检查消息是否与签到关键字匹配，如果匹配则跳过长度检查
                if text == rule.checkin_keyword:
                    logger.info(f"消息 '{text}' 与签到关键字 '{rule.checkin_keyword}' 匹配，跳过长度检查")
                # 检查消息长度是否满足最小字数要求
                elif rule.message_min_length > 0 and len(text) < rule.message_min_length:
                    logger.debug(f"消息长度 {len(text)} 小于最小要求 {rule.message_min_length}")
                    return None, None, None
                
                # 获取用户对象
                logger.info(f"尝试获取用户对象: {user_id}")
                user_obj = User.objects.filter(telegram_id=user_id, group=group, is_active=True).first()
                if not user_obj:
                    logger.warning(f"用户 {user_id} 在群组 {chat_id} 中不存在或非活跃")
                    return None, None, None
                
                logger.info(f"成功获取用户: {user_obj.id}, 当前积分: {user_obj.points}")
                
                # 检查每日积分上限
                today = timezone.now().date()
                
                # 获取用户今日已获得的发言积分
                logger.info(f"尝试获取用户今日发言统计")
                daily_stat = DailyMessageStat.objects.filter(
                    user=user_obj,
                    group=group,
                    message_date=today
                ).first()
                
                # 如果没有今日记录，创建一个
                if not daily_stat:
                    logger.info(f"未找到今日发言统计，将创建新记录")
                    daily_stat = DailyMessageStat(
                        user=user_obj,
                        group=group,
                        message_date=today,
                        message_count=0,
                        points_awarded=0
                    )
                else:
                    logger.info(f"今日已发言 {daily_stat.message_count} 次，已获得 {daily_stat.points_awarded} 积分")
                
                # 检查是否达到每日上限
                if rule.message_daily_limit > 0 and daily_stat.points_awarded >= rule.message_daily_limit:
                    logger.info(f"用户 {user_id} 在群组 {chat_id} 中已达到每日发言积分上限 {rule.message_daily_limit}")
                    return group, user_obj, 0
                
                # 计算本次可获得的积分
                points_to_award = rule.message_points
                
                # 如果有每日上限，确保不超过上限
                if rule.message_daily_limit > 0:
                    remaining_points = rule.message_daily_limit - daily_stat.points_awarded
                    if points_to_award > remaining_points:
                        points_to_award = remaining_points
                    logger.info(f"今日剩余可获得积分: {remaining_points}, 本次将获得: {points_to_award}")
                
                # 如果没有积分可获得，直接返回
                if points_to_award <= 0:
                    logger.info(f"没有积分可获得，跳过积分更新")
                    return group, user_obj, 0
                
                # 创建消息积分记录并更新用户积分
                with transaction.atomic():
                    try:
                        logger.info(f"开始事务处理: 创建消息积分记录并更新用户积分")
                        # 创建消息积分记录
                        MessagePoint.objects.create(
                            user=user_obj,
                            group=group,
                            message_id=message_id,
                            points_awarded=points_to_award,
                            message_date=today
                        )
                        logger.info(f"已创建消息积分记录")
                        
                        # 更新用户积分
                        old_points = user_obj.points
                        user_obj.points += points_to_award
                        user_obj.save()
                        logger.info(f"已更新用户积分: {old_points} → {user_obj.points}")
                        
                        # 更新每日统计
                        daily_stat.message_count += 1
                        daily_stat.points_awarded += points_to_award
                        daily_stat.save()
                        logger.info(f"已更新每日统计: message_count={daily_stat.message_count}, points_awarded={daily_stat.points_awarded}")
                        
                        # 创建积分变动记录
                        PointTransaction.objects.create(
                            user=user_obj,
                            group=group,
                            amount=points_to_award,
                            type='MESSAGE',
                            description=f"发言获得 {points_to_award} 积分",
                            transaction_date=today
                        )
                        logger.info(f"已创建积分变动记录")
                        
                        logger.info(f"用户 {user_id} 在群组 {chat_id} 发言获得 {points_to_award} 积分，当前总积分: {user_obj.points}")
                        return group, user_obj, points_to_award
                    except Exception as e:
                        # 记录具体的错误信息
                        logger.error(f"创建发言积分记录或更新积分时出错: {e}", exc_info=True)
                        # 事务回滚，确保数据一致性
                        raise
            except Group.DoesNotExist:
                logger.error(f"群组 {chat_id} 不存在或非活跃")
                return None, None, None
            except Exception as e:
                logger.error(f"处理发言积分时出错: {e}", exc_info=True)
                return None, None, None
        
        # 执行发言积分处理
        logger.info(f"调用async处理用户 {user.id} 的发言积分")
        group, user_obj, points_awarded = await process_message_points_for_user(chat_id, user.id, message_id, text)
        logger.info(f"发言积分处理结果: group={group is not None}, user_obj={user_obj is not None}, points_awarded={points_awarded}")
        
        # 不需要发送通知消息，静默增加积分
    except Exception as e:
        logger.error(f"处理发言积分时出现未捕获异常: {e}", exc_info=True) 