import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Chat
from telegram.ext import ContextTypes
from django.utils import timezone
from asgiref.sync import sync_to_async
from .models import Group, PointRule, CheckIn, PointTransaction, User
from django.db import transaction

# 设置日志
logger = logging.getLogger(__name__)

async def show_checkin_rule_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id=None, query=None):
    """显示签到规则设置菜单"""
    user = update.effective_user
    logger.info(f"用户 {user.id} ({user.full_name}) 正在查看签到规则设置")
    
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
    
    # 创建键盘按钮
    keyboard = [
        [
            InlineKeyboardButton("🔧 修改签到文字", callback_data=f"edit_checkin_text_{chat_id}" if group_id else "edit_checkin_text"),
            InlineKeyboardButton("🔧 设置获得数量", callback_data=f"set_checkin_points_{chat_id}" if group_id else "set_checkin_points")
        ],
        [
            InlineKeyboardButton("◀️ 返回", callback_data=back_button_callback)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 获取当前群组的签到规则
    try:
        # 使用sync_to_async包装数据库操作
        @sync_to_async
        def get_point_rule(group_id):
            try:
                group = Group.objects.get(group_id=group_id)
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'checkin_keyword': '签到',
                        'checkin_points': 1
                    }
                )
                return rule, group.group_title
            except Exception as e:
                logger.error(f"获取群组或积分规则时出错: {e}")
                return None, None
        
        rule_info = await get_point_rule(chat_id)
        if rule_info[0]:
            rule, group_title = rule_info
            
            # 显示当前签到规则
            message_text = (
                f"群组 {group_title} 的积分设置\n\n"
                f"签到规则: 发送 \"{rule.checkin_keyword}\"，每日签到获得 {rule.checkin_points} 积分\n"
                f"当前状态: {'✅ 已启用' if rule.points_enabled else '❌ 已关闭'}"
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
            message_text = f"获取群组 {chat_id} 的签到规则时出错，可能是群组不存在或机器人未添加到该群组"
            
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
        logger.error(f"获取签到规则时出错: {e}")
        # 使用try-except块包装消息编辑操作
        try:
            await query.edit_message_text(
                text=f"获取群组 {chat_id} 的签到规则时出错，请稍后再试",
                reply_markup=reply_markup
            )
        except Exception as edit_error:
            logger.error(f"编辑错误消息时出错: {edit_error}")
            # 如果编辑失败，尝试发送新消息
            try:
                await update.effective_chat.send_message(
                    text=f"获取群组 {chat_id} 的签到规则时出错，请稍后再试",
                    reply_markup=reply_markup
                )
            except Exception as send_error:
                logger.error(f"发送新错误消息也失败: {send_error}")

async def edit_checkin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理修改签到文字的请求"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击修改签到文字按钮")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    back_callback = "back_to_checkin_rule"
    
    if callback_data.startswith("edit_checkin_text_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[3])
        back_callback = f"checkin_rule_{group_id}"
        logger.info(f"用户正在修改群组 {group_id} 的签到文字")
    else:
        logger.info(f"用户正在修改当前聊天的签到文字")
    
    # 获取当前签到文字设置
    chat_id = group_id if group_id else update.effective_chat.id
    logger.info(f"使用chat_id: {chat_id} 获取签到文字设置")
    
    @sync_to_async
    def get_current_keyword(chat_id):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'checkin_keyword': '签到',
                    'checkin_points': 0
                }
            )
            logger.info(f"数据库查询结果: 群组={group.group_title}, 签到文字={rule.checkin_keyword}, 新创建={created}")
            return rule.checkin_keyword, group.group_title
        except Exception as e:
            logger.error(f"获取当前签到文字设置时出错: {e}", exc_info=True)
            return "签到", "未知群组"  # 默认值
    
    try:
        keyword_info = await get_current_keyword(chat_id)
        current_keyword, group_title = keyword_info
        
        logger.info(f"群组 {group_title} (ID: {chat_id}) 当前签到文字为: {current_keyword}")
        
        # 将用户置于等待输入状态
        context.user_data['waiting_for_checkin_text'] = True
        context.user_data['chat_id'] = chat_id
        context.user_data['back_callback'] = back_callback
        logger.info(f"已设置用户等待状态: waiting_for_checkin_text={True}, chat_id={chat_id}")
        
        # 创建界面内容，确保与图2格式一致
        message_text = f"积分\n\n当前设置:{current_keyword}\n\n👉 输入内容进行设置:"
        
        # 创建返回按钮，与图2一致
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # 发送提示消息，让用户输入新的签到文字
            await query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup
            )
            logger.info(f"已显示签到文字设置界面，等待用户输入")
            
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}", exc_info=True)
            try:
                await update.effective_chat.send_message(
                    text=message_text,
                    reply_markup=reply_markup
                )
                logger.info(f"通过新消息显示签到文字设置界面")
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}", exc_info=True)
                
    except Exception as e:
        logger.error(f"处理设置签到文字请求时出错: {e}", exc_info=True)
        try:
            await update.effective_chat.send_message(
                text="获取签到文字设置时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
        except Exception as msg_error:
            logger.error(f"发送错误消息失败: {msg_error}")

# 创建一个新函数来处理用户输入的签到文字
async def handle_checkin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的签到文字"""
    # 检查用户是否在等待输入签到文字的状态
    if not context.user_data.get('waiting_for_checkin_text'):
        logger.debug(f"用户 {update.effective_user.id} 发送了消息，但不在等待输入签到文字状态")
        return
    
    user = update.effective_user
    text = update.message.text.strip()
    logger.info(f"用户 {user.id} ({user.full_name}) 正在设置签到文字为: {text}")
    
    # 获取群组ID
    chat_id = context.user_data.get('chat_id')
    back_callback = context.user_data.get('back_callback')
    
    if not chat_id:
        logger.error("找不到chat_id，用户状态可能已丢失")
        await update.message.reply_text("操作失败，请重试")
        return
    
    logger.info(f"处理用户输入，将为群组 {chat_id} 设置签到文字: {text}")
    
    # 检查签到文字的长度，不能太长
    if len(text) > 30:
        logger.warning(f"用户输入的签到文字过长: {len(text)} 字符")
        await update.message.reply_text("签到文字太长了，请不要超过30个字符")
        return
    
    # 更新数据库
    @sync_to_async
    def update_checkin_text(chat_id, text):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'checkin_keyword': '签到',
                    'checkin_points': 0
                }
            )
            
            # 记录旧值，便于日志
            old_keyword = rule.checkin_keyword
            
            # 更新签到文字
            rule.checkin_keyword = text
            rule.save()
            
            logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的签到文字已从 '{old_keyword}' 更新为 '{text}'")
            return True, group.group_title
        except Exception as e:
            logger.error(f"更新签到文字设置时出错: {e}", exc_info=True)
            return False, "未知群组"
    
    result = await update_checkin_text(chat_id, text)
    success, group_title = result
    
    # 重置用户状态
    context.user_data.pop('waiting_for_checkin_text', None)
    context.user_data.pop('chat_id', None)
    context.user_data.pop('back_callback', None)
    
    if success:
        # 发送成功消息
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"签到文字设置成功，显示成功消息")
        await update.message.reply_text(
            f"✅ 设置成功，点击按钮返回。",
            reply_markup=reply_markup
        )
    else:
        logger.error(f"签到文字设置失败")
        await update.message.reply_text("设置失败，请重试")

async def set_checkin_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置签到积分数量的请求"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击设置获得数量按钮")
    logger.info(f"开始处理设置获得数量请求: {query.data}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    back_callback = "back_to_checkin_rule"
    
    if callback_data.startswith("set_checkin_points_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[3])
        back_callback = f"checkin_rule_{group_id}"
        logger.info(f"用户正在设置群组 {group_id} 的签到积分")
    else:
        logger.info(f"用户正在设置当前聊天的签到积分")
    
    # 获取当前积分设置
    chat_id = group_id if group_id else update.effective_chat.id
    logger.info(f"使用chat_id: {chat_id} 获取积分设置")
    
    @sync_to_async
    def get_current_points(chat_id):
        try:
            group = Group.objects.get(group_id=chat_id)
            rule, created = PointRule.objects.get_or_create(
                group=group,
                defaults={
                    'checkin_keyword': '签到',
                    'checkin_points': 0
                }
            )
            logger.info(f"数据库查询结果: 群组={group.group_title}, 积分={rule.checkin_points}, 新创建={created}")
            return rule.checkin_points, group.group_title
        except Exception as e:
            logger.error(f"获取当前积分设置时出错: {e}", exc_info=True)
            return 0, "未知群组" # 默认值为0，与界面显示一致
    
    try:
        points_info = await get_current_points(chat_id)
        current_points, group_title = points_info
        
        logger.info(f"群组 {group_title} (ID: {chat_id}) 当前签到积分为: {current_points}")
        
        # 将用户置于等待输入状态
        context.user_data['waiting_for_points'] = True
        context.user_data['chat_id'] = chat_id
        context.user_data['back_callback'] = back_callback
        logger.info(f"已设置用户等待状态: waiting_for_points={True}, chat_id={chat_id}")
        
        # 创建界面内容，确保与图2格式一致
        message_text = f"签到积分\n\n当前设置:{current_points}\n\n👉 输入内容进行设置:"
        
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
            logger.info(f"已显示积分设置界面，等待用户输入")
            
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}", exc_info=True)
            try:
                await update.effective_chat.send_message(
                    text=message_text,
                    reply_markup=reply_markup
                )
                logger.info(f"通过新消息显示积分设置界面")
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}", exc_info=True)
                
    except Exception as e:
        logger.error(f"处理设置签到积分数量请求时出错: {e}", exc_info=True)
        try:
            await update.effective_chat.send_message(
                text="获取积分设置时出错，请稍后再试",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data=back_callback)]
                ])
            )
        except Exception as msg_error:
            logger.error(f"发送错误消息失败: {msg_error}")
            
# 创建一个新函数来处理用户输入的积分数量
async def handle_points_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的签到积分数量"""
    # 检查用户是否在等待输入积分数量的状态
    if not context.user_data.get('waiting_for_points'):
        logger.debug(f"用户 {update.effective_user.id} 发送了消息，但不在等待输入积分状态")
        return
    
    user = update.effective_user
    text = update.message.text.strip()
    logger.info(f"用户 {user.id} ({user.full_name}) 正在设置积分数量为: {text}")
    
    # 获取群组ID
    chat_id = context.user_data.get('chat_id')
    back_callback = context.user_data.get('back_callback')
    
    if not chat_id:
        logger.error("找不到chat_id，用户状态可能已丢失")
        await update.message.reply_text("操作失败，请重试")
        return
    
    logger.info(f"处理用户输入，将为群组 {chat_id} 设置积分值: {text}")
    
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
                    'checkin_keyword': '签到',
                    'checkin_points': 0
                }
            )
            
            # 记录旧值，便于日志
            old_points = rule.checkin_points
            
            # 更新积分值
            rule.checkin_points = points
            rule.save()
            
            logger.info(f"群组 {group.group_title} (ID: {chat_id}) 的签到积分已从 {old_points} 更新为 {points}")
            return True, group.group_title
        except Exception as e:
            logger.error(f"更新积分设置时出错: {e}", exc_info=True)
            return False, "未知群组"
    
    result = await update_points(chat_id, points)
    success, group_title = result
    
    # 重置用户状态
    context.user_data.pop('waiting_for_points', None)
    context.user_data.pop('chat_id', None)
    context.user_data.pop('back_callback', None)
    
    if success:
        # 发送成功消息
        keyboard = [
            [InlineKeyboardButton("返回", callback_data=back_callback)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"积分设置成功，显示成功消息")
        await update.message.reply_text(
            f"✅ 设置成功，点击按钮返回。",
            reply_markup=reply_markup
        )
    else:
        logger.error(f"积分设置失败")
        await update.message.reply_text("设置失败，请重试")

async def back_to_points_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回到积分设置主菜单"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击返回积分设置按钮")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否有群组ID (如points_setting_123456789)
    callback_data = query.data
    if callback_data.startswith("points_setting_"):
        # 这是一个群组特定的回调，提取群组ID
        group_id = int(callback_data.split("_")[2])
        
        # 创建针对特定群组的按钮
        keyboard = [
            [
                InlineKeyboardButton("🔧 签到规则", callback_data=f"checkin_rule_{group_id}"),
                InlineKeyboardButton("🔧 发言规则", callback_data=f"message_rule_{group_id}"),
                InlineKeyboardButton("🔧 邀请规则", callback_data=f"invite_rule_{group_id}")
            ],
            [
                InlineKeyboardButton("◀️ 返回群组设置", callback_data=f"group_{group_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 尝试获取群组名称
        @sync_to_async
        def get_group_name(group_id):
            try:
                group = Group.objects.get(group_id=group_id)
                return group.group_title
            except Exception:
                return "未知群组"
        
        group_name = await get_group_name(group_id)
        
        try:
            await query.edit_message_text(
                text=f"您正在管理 {group_name} 的积分规则设置。请选择要查看的积分规则：",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}")
            try:
                await update.effective_chat.send_message(
                    text=f"您正在管理 {group_name} 的积分规则设置。请选择要查看的积分规则：",
                    reply_markup=reply_markup
                )
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}")
    else:
        # 普通的回调，创建普通的积分设置按钮
        keyboard = [
            [
                InlineKeyboardButton("🔧 签到规则", callback_data="checkin_rule"),
                InlineKeyboardButton("🔧 发言规则", callback_data="message_rule"),
                InlineKeyboardButton("🔧 邀请规则", callback_data="invite_rule")
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                text="请选择要查看的积分规则：",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"编辑消息时出错: {e}")
            try:
                await update.effective_chat.send_message(
                    text="请选择要查看的积分规则：",
                    reply_markup=reply_markup
                )
            except Exception as send_error:
                logger.error(f"发送新消息也失败: {send_error}")

async def back_to_checkin_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回到签到规则设置"""
    user = update.effective_user
    query = update.callback_query
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击返回签到规则按钮")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
    
    # 检查是否包含群组ID
    callback_data = query.data
    group_id = None
    
    if callback_data.startswith("checkin_rule_"):
        # 从回调数据中提取群组ID
        group_id = int(callback_data.split("_")[2])
    
    # 返回到签到规则设置菜单
    await show_checkin_rule_settings(update, context, group_id, query)

async def process_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群聊中的消息，检查是否包含签到关键词，并更新用户积分
    
    返回:
    - True: 如果消息被作为签到处理并已回复用户
    - False: 如果消息不是签到关键词或其他原因没有处理
    """
    # 跳过非文本消息
    if not update.message or not update.message.text:
        return False
    
    # 跳过非群组消息
    chat = update.effective_chat
    if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        return False
    
    # 获取消息内容和发送者
    text = update.message.text.strip()
    user = update.effective_user
    chat_id = chat.id
    
    logger.info(f"处理群组 {chat_id} 中用户 {user.id} ({user.full_name}) 的消息: {text}")
    
    try:
        # 检查是否为签到关键词
        @sync_to_async
        def check_checkin_keyword(chat_id, user_id, text):
            try:
                # 获取群组对象
                group = Group.objects.get(group_id=chat_id, is_active=True)
                
                # 获取该群组的签到规则
                rule = PointRule.objects.filter(group=group).first()
                if not rule or not rule.points_enabled:
                    logger.debug(f"群组 {chat_id} 未设置签到规则或积分功能已关闭")
                    return None, None, None
                
                # 检查消息是否与签到关键词匹配
                if text != rule.checkin_keyword:
                    logger.debug(f"消息 '{text}' 与签到关键词 '{rule.checkin_keyword}' 不匹配")
                    return None, None, None
                
                # 获取用户对象
                user_obj = User.objects.filter(telegram_id=user_id, group=group, is_active=True).first()
                if not user_obj:
                    logger.warning(f"用户 {user_id} 在群组 {chat_id} 中不存在或非活跃")
                    return None, None, None
                
                # 检查今天是否已经签到过
                today = timezone.now().date()
                existing_checkin = CheckIn.objects.filter(
                    user=user_obj,
                    group=group,
                    checkin_date=today
                ).first()
                
                if existing_checkin:
                    logger.info(f"用户 {user_id} 今天已经在群组 {chat_id} 中签到过了")
                    return group, user_obj, None
                
                # 创建签到记录并更新用户积分
                with transaction.atomic():
                    # 创建签到记录
                    checkin = CheckIn.objects.create(
                        user=user_obj,
                        group=group,
                        points_awarded=rule.checkin_points,
                        checkin_date=today
                    )
                    
                    # 更新用户积分
                    user_obj.points += rule.checkin_points
                    user_obj.save()
                    
                    # 创建积分变动记录
                    PointTransaction.objects.create(
                        user=user_obj,
                        group=group,
                        amount=rule.checkin_points,
                        type='CHECKIN',
                        description=f"签到获得 {rule.checkin_points} 积分",
                        transaction_date=today
                    )
                    
                    logger.info(f"用户 {user_id} 在群组 {chat_id} 签到成功，获得 {rule.checkin_points} 积分")
                    return group, user_obj, rule.checkin_points
            except Exception as e:
                logger.error(f"处理签到消息时出错: {e}", exc_info=True)
                return None, None, None
        
        # 执行签到检查
        group, user_obj, points_awarded = await check_checkin_keyword(chat_id, user.id, text)
        
        # 如果签到成功
        if group and user_obj and points_awarded:
            # 发送签到成功提示，按照要求显示已签到和获得的积分数量
            await update.message.reply_text(
                f"@{user.username if user.username else user.full_name} 已签到，获得 {points_awarded} 积分"
            )
            logger.info(f"向用户 {user.id} 发送了签到成功消息")
            return True
        # 如果已经签到过
        elif group and user_obj:
            # 发送已签到过的提示，按照要求显示今天已签到，请明天再来
            await update.message.reply_text(
                f"@{user.username if user.username else user.full_name} 今天已签到，请明天再来"
            )
            logger.info(f"向用户 {user.id} 发送了已签到过消息")
            return True
        
        # 如果不是签到消息，返回False继续处理
        return False
    except Exception as e:
        logger.error(f"处理签到消息时出错: {e}", exc_info=True)
        return False 