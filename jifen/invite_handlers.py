import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from django.utils import timezone
from asgiref.sync import sync_to_async
from .models import Group, PointRule

# 设置日志
logger = logging.getLogger(__name__)

async def show_invite_rule_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id=None, query=None):
    """显示邀请规则设置菜单"""
    user = update.effective_user
    logger.info(f"用户 {user.id} ({user.full_name}) 正在查看邀请规则设置")
    
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
    
    # 创建两个按钮：设置获得数量、每日上限
    keyboard = [
        [
            InlineKeyboardButton("⚙️ 设置获得数量", callback_data=f"set_invite_points_{chat_id}" if group_id else "set_invite_points"),
            InlineKeyboardButton("⚙️ 每日上限", callback_data=f"set_invite_daily_limit_{chat_id}" if group_id else "set_invite_daily_limit")
        ],
        [
            InlineKeyboardButton("◀️ 返回", callback_data=back_button_callback)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 获取当前群组的邀请规则
    try:
        # 使用sync_to_async包装数据库操作
        @sync_to_async
        def get_point_rule(group_id):
            try:
                group = Group.objects.get(group_id=group_id)
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'invite_points': 1,
                        'invite_daily_limit': 0
                    }
                )
                return rule, group.group_title
            except Exception as e:
                logger.error(f"获取群组或积分规则时出错: {e}")
                return None, None
        
        rule_info = await get_point_rule(chat_id)
        if rule_info[0]:
            rule, group_title = rule_info
            
            # 显示当前邀请规则
            daily_limit_text = "无限制" if rule.invite_daily_limit == 0 else str(rule.invite_daily_limit)
            
            message_text = (
                f"群组 {group_title} 的积分设置\n\n"
                f"邀请1人，获得{rule.invite_points} 积分\n"
                f"每日获取上限:{daily_limit_text} 积分"
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
            message_text = f"获取群组 {chat_id} 的邀请规则时出错，可能是群组不存在或机器人未添加到该群组"
            
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
        logger.error(f"获取邀请规则时出错: {e}")
        # 使用try-except块包装消息编辑操作
        try:
            await query.edit_message_text(
                text=f"获取群组 {chat_id} 的邀请规则时出错，请稍后再试",
                reply_markup=reply_markup
            )
        except Exception as edit_error:
            logger.error(f"编辑错误消息时出错: {edit_error}")
            # 如果编辑失败，尝试发送新消息
            try:
                await update.effective_chat.send_message(
                    text=f"获取群组 {chat_id} 的邀请规则时出错，请稍后再试",
                    reply_markup=reply_markup
                )
            except Exception as send_error:
                logger.error(f"发送新错误消息也失败: {send_error}")

async def set_invite_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置邀请积分数量的请求"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击设置邀请获得数量按钮")
    logger.info(f"开始处理设置邀请获得数量请求: {query.data}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    back_callback = "back_to_invite_rule"
    
    if callback_data.startswith("set_invite_points_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[3])
        back_callback = f"invite_rule_{group_id}"
        logger.info(f"用户正在设置群组 {group_id} 的邀请积分")
    else:
        logger.info(f"用户正在设置当前聊天的邀请积分")
    
    # 获取当前积分设置
    chat_id = group_id if group_id else update.effective_chat.id
    logger.info(f"使用chat_id: {chat_id} 获取邀请积分设置")
    
    @sync_to_async
    def get_current_points(chat_id):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'invite_points': 1
                }
            )
            logger.info(f"数据库查询结果: 群组={group.group_title}, 邀请积分={rule.invite_points}, 新创建={created}")
            return rule.invite_points, group.group_title
        except Exception as e:
            logger.error(f"获取当前邀请积分设置时出错: {e}", exc_info=True)
            return 1, "未知群组" # 默认值为1
    
    try:
        points_info = await get_current_points(chat_id)
        current_points, group_title = points_info
        
        logger.info(f"群组 {group_title} (ID: {chat_id}) 当前邀请积分为: {current_points}")
        
        # 将用户置于等待输入状态
        context.user_data['waiting_for_invite_points'] = True
        context.user_data['chat_id'] = chat_id
        context.user_data['back_callback'] = back_callback
        logger.info(f"已设置用户等待状态: waiting_for_invite_points={True}, chat_id={chat_id}")
        
        # 创建界面内容，确保与图2格式一致
        message_text = f"邀请积分\n\n当前设置:{current_points}\n\n👉 输入内容进行设置:"
        
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
            logger.info(f"已显示邀请积分设置界面，等待用户输入")
            
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}", exc_info=True)
            try:
                await update.effective_chat.send_message(
                    text=message_text,
                    reply_markup=reply_markup
                )
                logger.info(f"通过新消息显示邀请积分设置界面")
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}", exc_info=True)
                
    except Exception as e:
        logger.error(f"处理设置邀请积分数量请求时出错: {e}", exc_info=True)
        try:
            await update.effective_chat.send_message(
                text="获取邀请积分设置时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
        except Exception as msg_error:
            logger.error(f"发送错误消息失败: {msg_error}")

# 处理用户输入的邀请积分数量
async def handle_invite_points_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的邀请积分数量"""
    # 检查用户是否在等待输入邀请积分数量的状态
    if not context.user_data.get('waiting_for_invite_points'):
        logger.debug(f"用户 {update.effective_user.id} 发送了消息，但不在等待输入邀请积分状态")
        return
    
    user = update.effective_user
    text = update.message.text.strip()
    logger.info(f"用户 {user.id} ({user.full_name}) 正在设置邀请积分数量为: {text}")
    
    # 获取群组ID
    chat_id = context.user_data.get('chat_id')
    back_callback = context.user_data.get('back_callback')
    
    if not chat_id:
        logger.error("找不到chat_id，用户状态可能已丢失")
        await update.message.reply_text("操作失败，请重试")
        return
    
    logger.info(f"处理用户输入，将为群组 {chat_id} 设置邀请积分值: {text}")
    
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
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'invite_points': 1
                }
            )
            
            # 记录旧值，便于日志
            old_points = rule.invite_points
            
            # 更新积分值
            rule.invite_points = points
            rule.save()
            
            logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的邀请积分已从 {old_points} 更新为 {points}")
            return True, group.group_title
        except Exception as e:
            logger.error(f"更新邀请积分设置时出错: {e}", exc_info=True)
            return False, "未知群组"
    
    result = await update_points(chat_id, points)
    success, group_title = result
    
    # 重置用户状态
    context.user_data.pop('waiting_for_invite_points', None)
    context.user_data.pop('chat_id', None)
    context.user_data.pop('back_callback', None)
    
    if success:
        # 发送成功消息
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"邀请积分设置成功，显示成功消息")
        await update.message.reply_text(
            f"✅ 设置成功，点击按钮返回。",
            reply_markup=reply_markup
        )
    else:
        logger.error(f"邀请积分设置失败")
        await update.message.reply_text("设置失败，请重试")

async def set_invite_daily_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置邀请每日积分上限的请求"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击设置邀请每日上限按钮")
    logger.info(f"开始处理设置邀请每日上限请求: {query.data}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    back_callback = "back_to_invite_rule"
    
    if callback_data.startswith("set_invite_daily_limit_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[4])
        back_callback = f"invite_rule_{group_id}"
        logger.info(f"用户正在设置群组 {group_id} 的邀请每日上限")
    else:
        logger.info(f"用户正在设置当前聊天的邀请每日上限")
    
    # 获取当前每日上限设置
    chat_id = group_id if group_id else update.effective_chat.id
    logger.info(f"使用chat_id: {chat_id} 获取邀请每日上限设置")
    
    @sync_to_async
    def get_current_daily_limit(chat_id):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'invite_points': 1,
                    'invite_daily_limit': 0
                }
            )
            daily_limit_text = "无限制" if rule.invite_daily_limit == 0 else str(rule.invite_daily_limit)
            logger.info(f"数据库查询结果: 群组={group.group_title}, 每日邀请上限={daily_limit_text}, 新创建={created}")
            return rule.invite_daily_limit, group.group_title
        except Exception as e:
            logger.error(f"获取当前每日邀请上限设置时出错: {e}", exc_info=True)
            return 0, "未知群组" # 默认值为0，表示无限制
    
    try:
        daily_limit_info = await get_current_daily_limit(chat_id)
        current_daily_limit, group_title = daily_limit_info
        
        # 将当前设置值格式化为显示文本
        current_setting = "无限制" if current_daily_limit == 0 else str(current_daily_limit)
        logger.info(f"群组 {group_title} (ID: {chat_id}) 当前邀请每日上限为: {current_setting}")
        
        # 将用户置于等待输入状态
        context.user_data['waiting_for_invite_daily_limit'] = True
        context.user_data['chat_id'] = chat_id
        context.user_data['back_callback'] = back_callback
        logger.info(f"已设置用户等待状态: waiting_for_invite_daily_limit={True}, chat_id={chat_id}")
        
        # 创建界面内容，确保与图2格式一致
        message_text = f"邀请每日上限\n\n当前设置:{current_setting}\n\n👉 输入内容进行设置:"
        
        # 创建返回按钮，与图2一致
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # 发送提示消息
            await query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup
            )
            logger.info(f"已显示邀请每日上限设置界面，等待用户输入")
            
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}", exc_info=True)
            try:
                await update.effective_chat.send_message(
                    text=message_text,
                    reply_markup=reply_markup
                )
                logger.info(f"通过新消息显示邀请每日上限设置界面")
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}", exc_info=True)
                
    except Exception as e:
        logger.error(f"处理设置邀请每日上限请求时出错: {e}", exc_info=True)
        try:
            await update.effective_chat.send_message(
                text="获取邀请每日上限设置时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
        except Exception as msg_error:
            logger.error(f"发送错误消息失败: {msg_error}")

async def back_to_invite_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回到邀请规则设置"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击返回邀请规则按钮")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    
    if callback_data.startswith("invite_rule_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[2])
    
    # 返回到邀请规则设置菜单
    await show_invite_rule_settings(update, context, group_id, query)

# 处理用户输入的邀请每日上限
async def handle_invite_daily_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的邀请每日上限"""
    # 检查用户是否在等待输入邀请每日上限的状态
    if not context.user_data.get('waiting_for_invite_daily_limit'):
        logger.debug(f"用户 {update.effective_user.id} 发送了消息，但不在等待输入邀请每日上限状态")
        return
    
    user = update.effective_user
    text = update.message.text.strip()
    logger.info(f"用户 {user.id} ({user.full_name}) 正在设置邀请每日上限为: {text}")
    
    # 获取群组ID
    chat_id = context.user_data.get('chat_id')
    back_callback = context.user_data.get('back_callback')
    
    if not chat_id:
        logger.error(f"用户 {user.id} 的状态数据中缺少chat_id")
        await update.message.reply_text(
            "设置邀请每日上限时出错，请重试。",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("返回", callback_data="back_to_invite_rule")]
            ])
        )
        context.user_data.clear()
        return
    
    # 验证输入是否是合法的非负整数，0表示无限制
    try:
        daily_limit = int(text)
        if daily_limit < 0:
            logger.warning(f"用户输入了负数: {daily_limit}")
            await update.message.reply_text(
                "每日上限不能是负数。请输入一个非负整数（0表示无限制）。",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
            return
        
        # 使用sync_to_async更新数据库中的每日上限值
        @sync_to_async
        def update_daily_limit(chat_id, limit):
            try:
                group = Group.objects.get(group_id=chat_id)
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'invite_points': 1,
                        'invite_daily_limit': 0
                    }
                )
                
                # 记录旧值，便于日志
                old_limit = rule.invite_daily_limit
                old_limit_text = "无限制" if old_limit == 0 else str(old_limit)
                
                # 更新每日上限值
                rule.invite_daily_limit = limit
                rule.save()
                
                new_limit_text = "无限制" if limit == 0 else str(limit)
                logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的每日邀请上限已从 {old_limit_text} 更新为 {new_limit_text}")
                return True, group.group_title
            except Exception as e:
                logger.error(f"更新每日邀请上限设置时出错: {e}", exc_info=True)
                return False, "未知群组"
        
        # 更新数据库
        success, group_title = await update_daily_limit(chat_id, daily_limit)
        
        # 清除等待状态
        context.user_data.clear()
        
        if success:
            # 显示不同的消息取决于设置值
            daily_limit_text = "无限制" if daily_limit == 0 else str(daily_limit)
            
            success_message = f"✅ 设置成功，每日邀请上限已更新为 {daily_limit_text}。"
            
            await update.message.reply_text(
                success_message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回设置", callback_data=back_callback)]
                ])
            )
            logger.info(f"成功更新并显示确认消息: {success_message}")
        else:
            await update.message.reply_text(
                "更新邀请每日上限时出错，请稍后再试。",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
            logger.error(f"无法更新邀请每日上限，显示错误消息")
            
    except ValueError:
        logger.warning(f"用户输入了非整数值: {text}")
        await update.message.reply_text(
            "请输入一个有效的整数值（0表示无限制）。",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("返回", callback_data=back_callback)]
            ])
        )
    except Exception as e:
        logger.error(f"处理邀请每日上限输入时出错: {e}", exc_info=True)
        await update.message.reply_text(
            "处理您的输入时出错，请稍后再试。",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("返回", callback_data=back_callback)]
            ])
        )
        context.user_data.clear() 