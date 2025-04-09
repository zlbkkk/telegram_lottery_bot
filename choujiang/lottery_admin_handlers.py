from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)
from .models import Lottery, Participant
from jifen.models import User
import logging
from asgiref.sync import sync_to_async
import traceback
from django.utils import timezone

# 设置日志
logger = logging.getLogger(__name__)

# 定义对话状态
SELECT_LOTTERY = 1
SELECT_WINNERS = 2
CONFIRM_WINNERS = 3

async def update_user_info(telegram_user):
    """更新用户信息（如用户名）到数据库"""
    @sync_to_async
    def update_user_in_db():
        try:
            # 查找用户的所有记录，而不仅仅是第一条
            users = User.objects.filter(telegram_id=telegram_user.id)
            if not users.exists():
                return None
                
            updated_count = 0
            for user in users:
                is_updated = False
                # 更新用户名
                if telegram_user.username and user.username != telegram_user.username:
                    user.username = telegram_user.username
                    is_updated = True
                # 更新名字和姓氏
                if telegram_user.first_name and user.first_name != telegram_user.first_name:
                    user.first_name = telegram_user.first_name
                    is_updated = True
                if telegram_user.last_name and (user.last_name or "") != (telegram_user.last_name or ""):
                    user.last_name = telegram_user.last_name
                    is_updated = True
                    
                if is_updated:
                    user.save()
                    updated_count += 1
            
            if updated_count > 0:
                logger.info(f"[用户信息] 已更新用户 {telegram_user.id} 的 {updated_count} 条记录，用户名: {telegram_user.username}")
                
            # 返回第一条记录，保持原有函数返回行为
            return users.first()
        except Exception as e:
            logger.error(f"[用户信息] 更新用户信息时出错: {e}\n{traceback.format_exc()}")
        return None
    
    return await update_user_in_db()

async def start_admin_draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理管理员开始设置中奖用户的命令"""
    user = update.effective_user
    
    # 处理从命令或回调进入的情况
    if update.message:
        chat_id = update.effective_chat.id
        message = update.message
    elif update.callback_query:
        chat_id = update.callback_query.message.chat_id
        message = update.callback_query.message
        # 回答回调查询
        await update.callback_query.answer()
    else:
        return ConversationHandler.END
    
    logger.info(f"[管理员抽奖] 用户 {user.id} ({user.username or user.first_name}) 开始设置中奖用户")
    
    try:
        # 更新用户信息（如用户名）
        await update_user_info(user)
        
        # 获取用户信息
        @sync_to_async
        def get_user():
            return User.objects.filter(telegram_id=user.id).first()
        
        user_obj = await get_user()
        
        if not user_obj or not user_obj.is_admin:
            logger.warning(f"[管理员抽奖] 用户 {user.id} 不是管理员")
            if update.callback_query:
                await update.callback_query.edit_message_text("您没有管理员权限，无法使用此功能。")
            else:
                await message.reply_text("您没有管理员权限，无法使用此功能。")
            return ConversationHandler.END
        
        # 获取所有进行中的抽奖
        @sync_to_async
        def get_active_lotteries():
            return list(Lottery.objects.filter(status='ACTIVE'))
        
        lotteries = await get_active_lotteries()
        
        if not lotteries:
            if update.callback_query:
                await update.callback_query.edit_message_text("当前没有进行中的抽奖活动。")
            else:
                await message.reply_text("当前没有进行中的抽奖活动。")
            return ConversationHandler.END
        
        # 创建抽奖选择键盘
        keyboard = []
        for lottery in lotteries:
            keyboard.append([InlineKeyboardButton(
                f"{lottery.title} (ID: {lottery.id})",
                callback_data=f"select_lottery_{lottery.id}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "请选择要设置中奖用户的抽奖活动：",
                reply_markup=reply_markup
            )
        else:
            await message.reply_text(
                "请选择要设置中奖用户的抽奖活动：",
                reply_markup=reply_markup
            )
        
        return SELECT_LOTTERY
        
    except Exception as e:
        logger.error(f"[管理员抽奖] 处理命令时出错: {e}\n{traceback.format_exc()}")
        error_message = "处理请求时出错，请重试。"
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await message.reply_text(error_message)
        return ConversationHandler.END

async def select_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理选择抽奖的回调"""
    query = update.callback_query
    user = update.effective_user
    lottery_id = int(query.data.split("_")[2])
    
    await query.answer()
    
    try:
        # 更新用户信息（如用户名）
        await update_user_info(user)
        
        # 获取抽奖信息
        @sync_to_async
        def get_lottery():
            return Lottery.objects.get(id=lottery_id)
        
        lottery = await get_lottery()
        
        # 获取参与者列表及其telegram_id
        @sync_to_async
        def get_participants_with_telegram_ids():
            participants_list = list(Participant.objects.filter(lottery=lottery).select_related('user'))
            # 在数据库查询中一次性获取所有需要的数据
            return participants_list, [p.user.telegram_id for p in participants_list]
        
        participants, participant_telegram_ids = await get_participants_with_telegram_ids()
        
        if not participants:
            await query.edit_message_text("该抽奖活动还没有参与者。")
            return ConversationHandler.END
        
        # 存储抽奖信息到上下文
        context.user_data['admin_draw'] = {
            'lottery_id': lottery_id,
            'participants': participant_telegram_ids
        }
        
        # 获取参与者详细信息
        @sync_to_async
        def get_participants_details():
            result = []
            for participant in participants:
                user = participant.user
                result.append({
                    'telegram_id': user.telegram_id,
                    'first_name': user.first_name,
                    'last_name': user.last_name or '',
                    'username': user.username or '无用户名'
                })
            return result
        
        participant_details = await get_participants_details()
        
        # 创建参与者选择键盘
        keyboard = []
        for p_detail in participant_details:
            keyboard.append([InlineKeyboardButton(
                f"{p_detail['first_name']} {p_detail['last_name']} (@{p_detail['username']})",
                callback_data=f"select_winner_{p_detail['telegram_id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("完成选择", callback_data="finish_selection")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"请选择中奖用户（抽奖：{lottery.title}）：\n"
            "点击用户名称选择/取消选择，完成后点击'完成选择'",
            reply_markup=reply_markup
        )
        
        return SELECT_WINNERS
        
    except Exception as e:
        logger.error(f"[管理员抽奖] 处理选择抽奖时出错: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def select_winner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理选择中奖用户的回调"""
    query = update.callback_query
    user_id = int(query.data.split("_")[2])
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 更新当前管理员用户信息
        await update_user_info(user)
        
        admin_draw_data = context.user_data.get('admin_draw', {})
        selected_winners = admin_draw_data.get('selected_winners', set())
        
        if user_id in selected_winners:
            selected_winners.remove(user_id)
        else:
            selected_winners.add(user_id)
        
        admin_draw_data['selected_winners'] = selected_winners
        context.user_data['admin_draw'] = admin_draw_data
        
        # 重新获取抽奖信息
        @sync_to_async
        def get_lottery():
            return Lottery.objects.get(id=admin_draw_data['lottery_id'])
        
        lottery = await get_lottery()
        
        # 重新获取参与者列表及其详细信息
        @sync_to_async
        def get_participants_details():
            participants_list = list(Participant.objects.filter(lottery=lottery).select_related('user'))
            result = []
            for participant in participants_list:
                user = participant.user
                result.append({
                    'telegram_id': user.telegram_id,
                    'first_name': user.first_name,
                    'last_name': user.last_name or '',
                    'username': user.username or '无用户名'
                })
            return result
        
        participant_details = await get_participants_details()
        
        # 更新键盘显示
        keyboard = []
        for p_detail in participant_details:
            is_selected = p_detail['telegram_id'] in selected_winners
            keyboard.append([InlineKeyboardButton(
                f"{'✅ ' if is_selected else ''}{p_detail['first_name']} {p_detail['last_name']} (@{p_detail['username']})",
                callback_data=f"select_winner_{p_detail['telegram_id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("完成选择", callback_data="finish_selection")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"已选择 {len(selected_winners)} 位中奖用户\n"
            f"抽奖：{lottery.title}\n"
            "点击用户名称选择/取消选择，完成后点击'完成选择'",
            reply_markup=reply_markup
        )
        
        return SELECT_WINNERS
        
    except Exception as e:
        logger.error(f"[管理员抽奖] 处理选择中奖用户时出错: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def finish_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理完成选择的回调"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 更新当前管理员用户信息
        await update_user_info(user)
        
        admin_draw_data = context.user_data.get('admin_draw', {})
        selected_winners = admin_draw_data.get('selected_winners', set())
        
        if not selected_winners:
            await query.edit_message_text("请至少选择一位中奖用户。")
            return SELECT_WINNERS
        
        # 获取抽奖信息
        @sync_to_async
        def get_lottery():
            return Lottery.objects.get(id=admin_draw_data['lottery_id'])
        
        lottery = await get_lottery()
        
        # 创建确认键盘
        keyboard = [
            [InlineKeyboardButton("确认", callback_data="confirm_winners")],
            [InlineKeyboardButton("重新选择", callback_data="reselect_winners")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 获取中奖用户信息并同时更新用户信息
        @sync_to_async
        def get_winner_info():
            winners = list(User.objects.filter(telegram_id__in=selected_winners))
            # 这里不需要更新用户信息，因为用户信息是从Telegram API获取的，而不是从数据库获取
            return winners
        
        winners = await get_winner_info()
        
        # 使用集合来跟踪已经处理过的telegram_id，避免重复
        processed_ids = set()
        winners_text = ""
        counter = 1
        
        # 逐个处理中奖者，确保每个用户只出现一次
        for w in winners:
            if w.telegram_id not in processed_ids:
                processed_ids.add(w.telegram_id)
                winners_text += f"{counter}. {w.first_name} {w.last_name or ''} (@{w.username or '无用户名'})\n"
                counter += 1
        
        await query.edit_message_text(
            f"确认以下用户为抽奖 {lottery.title} 的中奖者：\n\n"
            f"{winners_text}\n\n"
            "请确认或重新选择：",
            reply_markup=reply_markup
        )
        
        return CONFIRM_WINNERS
        
    except Exception as e:
        logger.error(f"[管理员抽奖] 处理完成选择时出错: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def confirm_winners(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理确认中奖用户的回调"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 更新当前管理员用户信息
        await update_user_info(user)
        
        admin_draw_data = context.user_data.get('admin_draw', {})
        selected_winners = list(admin_draw_data.get('selected_winners', set()))
        lottery_id = admin_draw_data['lottery_id']
        
        # 获取抽奖信息
        @sync_to_async
        def get_lottery():
            return Lottery.objects.get(id=lottery_id)
        
        lottery = await get_lottery()
        
        # 执行抽奖 - 修改导入和调用方式
        from .lottery_drawer import get_drawer_instance
        drawer = get_drawer_instance()
        if drawer:
            await drawer.manual_draw(lottery_id, selected_winners)
        else:
            logger.error("[管理员抽奖] 无法获取抽奖开奖器实例")
            await query.edit_message_text("处理请求时出错，请重试。")
            return ConversationHandler.END
        
        await query.edit_message_text(
            f"抽奖 {lottery.title} 的中奖用户已设置完成！\n"
            "系统将自动通知中奖用户。"
        )
        
        # 清理上下文数据
        if 'admin_draw' in context.user_data:
            del context.user_data['admin_draw']
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"[管理员抽奖] 处理确认中奖用户时出错: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def reselect_winners(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理重新选择中奖用户的回调"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 更新当前管理员用户信息
        await update_user_info(user)
        
        admin_draw_data = context.user_data.get('admin_draw', {})
        lottery_id = admin_draw_data['lottery_id']
        
        # 获取抽奖信息
        @sync_to_async
        def get_lottery():
            return Lottery.objects.get(id=lottery_id)
        
        lottery = await get_lottery()
        
        # 获取参与者列表及其详细信息
        @sync_to_async
        def get_participants_details():
            participants_list = list(Participant.objects.filter(lottery=lottery).select_related('user'))
            result = []
            for participant in participants_list:
                user = participant.user
                result.append({
                    'telegram_id': user.telegram_id,
                    'first_name': user.first_name,
                    'last_name': user.last_name or '',
                    'username': user.username or '无用户名'
                })
            return result
        
        participant_details = await get_participants_details()
        
        # 创建参与者选择键盘
        keyboard = []
        for p_detail in participant_details:
            is_selected = p_detail['telegram_id'] in admin_draw_data.get('selected_winners', set())
            keyboard.append([InlineKeyboardButton(
                f"{'✅ ' if is_selected else ''}{p_detail['first_name']} {p_detail['last_name']} (@{p_detail['username']})",
                callback_data=f"select_winner_{p_detail['telegram_id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("完成选择", callback_data="finish_selection")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"请重新选择中奖用户（抽奖：{lottery.title}）：\n"
            "点击用户名称选择/取消选择，完成后点击'完成选择'",
            reply_markup=reply_markup
        )
        
        return SELECT_WINNERS
        
    except Exception as e:
        logger.error(f"[管理员抽奖] 处理重新选择时出错: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("处理请求时出错，请重试。")
        return ConversationHandler.END

def get_admin_draw_conversation_handler():
    """返回管理员抽奖对话处理器"""
    return ConversationHandler(
        entry_points=[
            CommandHandler("setwinners", start_admin_draw),
            CallbackQueryHandler(start_admin_draw, pattern="^set_winners$")
        ],
        states={
            SELECT_LOTTERY: [CallbackQueryHandler(select_lottery, pattern="^select_lottery_")],
            SELECT_WINNERS: [
                CallbackQueryHandler(select_winner, pattern="^select_winner_"),
                CallbackQueryHandler(finish_selection, pattern="^finish_selection$")
            ],
            CONFIRM_WINNERS: [
                CallbackQueryHandler(confirm_winners, pattern="^confirm_winners$"),
                CallbackQueryHandler(reselect_winners, pattern="^reselect_winners$")
            ]
        },
        fallbacks=[],
        allow_reentry=True
    ) 