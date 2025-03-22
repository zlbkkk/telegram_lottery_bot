import logging
import asyncio
import os
import sys
import threading
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, BotCommandScopeAllChatAdministrators, BotCommandScopeDefault, MenuButtonCommands, MenuButtonDefault
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, filters, ChatMemberHandler, MessageHandler
from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Q

# 只有在非Django环境中才需要设置Django环境
if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'telegram_lottery_bot.settings')
    import django
    django.setup()

# 导入签到规则处理模块
from jifen.checkin_handlers import (
    show_checkin_rule_settings, 
    edit_checkin_text, 
    set_checkin_points, 
    back_to_points_setting,
    back_to_checkin_rule,
    handle_points_input,
    handle_checkin_text_input
)

# 导入发言规则处理模块
from jifen.message_handlers import (
    show_message_rule_settings,
    set_message_points,
    set_message_daily_limit,
    set_message_min_length,
    back_to_message_rule,
    handle_message_points_input,
    handle_daily_limit_input,
    handle_min_length_input
)

# 导入群组处理模块
from jifen.group_handlers import (
    handle_my_chat_member,
    handle_chat_member
)

# 导入需要的模型
from jifen.models import Group, User

# 设置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 设置机器人token
TOKEN = "8057896490:AAHyuY9GnXIAqWsdwSoRO_SSsE3x4xIVsZ8"

# 用于防止多次启动
bot_running = False
bot_lock = threading.Lock()

# 获取用户所有活跃群组的同步函数
@sync_to_async
def get_user_active_groups(telegram_id):
    """
    获取用户所在的所有活跃群组
    """
    try:
        logger.info(f"正在获取用户 {telegram_id} 的活跃群组")
        
        # 通过User模型获取用户所在的所有活跃群组
        user_groups = User.objects.filter(
            telegram_id=telegram_id,
            is_active=True,
            group__is_active=True
        ).select_related('group')
        
        # 添加日志，记录查询到的群组数量
        group_count = user_groups.count()
        logger.info(f"找到用户 {telegram_id} 的 {group_count} 个活跃群组")
        
        # 记录每个群组的信息，帮助调试
        groups_info = []
        for user_group in user_groups:
            group_info = (user_group.group.group_id, user_group.group.group_title)
            groups_info.append(group_info)
            logger.info(f"  - 群组: {user_group.group.group_title} (ID: {user_group.group.group_id})")
        
        # 如果没有找到群组，执行一个原始SQL查询来验证数据
        if group_count == 0:
            from django.db import connection
            with connection.cursor() as cursor:
                # 检查用户记录是否存在
                cursor.execute(
                    "SELECT COUNT(*) FROM users WHERE telegram_id = %s", 
                    [telegram_id]
                )
                user_count = cursor.fetchone()[0]
                logger.info(f"数据库中用户 {telegram_id} 的记录数: {user_count}")
                
                # 检查活跃群组记录
                cursor.execute(
                    "SELECT g.group_id, g.group_title FROM groups g "
                    "JOIN users u ON u.group_id = g.id "
                    "WHERE u.telegram_id = %s AND u.is_active = true AND g.is_active = true", 
                    [telegram_id]
                )
                raw_groups = cursor.fetchall()
                logger.info(f"原始SQL查询找到 {len(raw_groups)} 个群组")
                for g in raw_groups:
                    logger.info(f"  - 原始SQL: 群组 {g[1]} (ID: {g[0]})")
        
        return groups_info
    except Exception as e:
        logger.error(f"获取用户群组时出错: {e}", exc_info=True)
        return []

# 获取所有活跃群组的同步函数
@sync_to_async
def get_all_active_groups():
    """
    获取所有活跃的群组
    """
    try:
        active_groups = Group.objects.filter(is_active=True)
        return [(group.group_id, group.group_title) for group in active_groups]
    except Exception as e:
        logger.error(f"获取活跃群组时出错: {e}")
        return []

# 清除所有范围内的机器人命令并只设置start命令
async def clear_all_commands_and_set_start(bot):
    """清除所有范围内的命令并只设置start命令"""
    # 定义需要清理和设置的所有范围
    scopes = [
        BotCommandScopeDefault(),  # 默认范围
        BotCommandScopeAllPrivateChats(),  # 所有私聊
        BotCommandScopeAllGroupChats(),  # 所有群组
        BotCommandScopeAllChatAdministrators()  # 所有管理员
    ]
    
    commands = [BotCommand("start", "开始使用")]
    
    # 对每个范围进行操作
    for scope in scopes:
        try:
            # 先删除该范围内的所有命令
            await bot.delete_my_commands(scope=scope)
            # 然后设置start命令
            await bot.set_my_commands(commands, scope=scope)
            logger.info(f"成功设置范围 {scope.__class__.__name__} 内的命令")
        except Exception as e:
            logger.warning(f"设置范围 {scope.__class__.__name__} 内的命令失败: {e}")
    
    # 确保设置了默认菜单按钮，而不是命令菜单按钮
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
        logger.info("成功设置全局默认菜单按钮")
    except Exception as e:
        logger.warning(f"设置全局默认菜单按钮失败: {e}")

# start命令处理函数
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """发送start菜单，显示用户加入的群组和添加机器人到新群组的按钮"""
    user = update.effective_user
    logger.info(f"用户 {user.id} ({user.full_name}) 正在执行 /start 命令")
    
    # 清除所有范围内的命令并只设置start命令
    try:
        await clear_all_commands_and_set_start(context.bot)
        
        # 明确地设置当前聊天的菜单按钮为默认菜单，保持左下角的Menu按钮
        await context.bot.set_chat_menu_button(
            chat_id=update.effective_chat.id,
            menu_button=MenuButtonDefault()
        )
        
        logger.info("成功设置机器人命令列表，只保留start命令")
    except Exception as e:
        logger.warning(f"设置命令列表失败: {e}")
    
    user = update.effective_user
    
    # 获取用户所在的群组列表
    user_groups = await get_user_active_groups(user.id)
    
    # 准备键盘按钮
    keyboard = []
    
    # 如果用户有加入的群组，为每个群组创建一个按钮
    if user_groups:
        for group_id, group_title in user_groups:
            # 使用callback_data格式"group_{group_id}"来标识不同群组
            keyboard.append([InlineKeyboardButton(f"🏘️ {group_title}", callback_data=f"group_{group_id}")])
    
    # 添加"添加机器人到群组"按钮
    bot_username = context.bot.username
    invite_url = f"https://t.me/{bot_username}?startgroup=true"
    keyboard.append([InlineKeyboardButton("➕ 添加机器人到群组", url=invite_url)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 构建欢迎消息
    welcome_text = "欢迎使用Telegram积分抽奖机器人！\n"
    
    if user_groups:
        welcome_text += "\n🏘️ 您已加入的群组：\n"
        for _, group_title in user_groups:
            welcome_text += f"• {group_title}\n"
        welcome_text += "\n点击群组名称管理该群设置，或添加机器人到新群组。"
    else:
        welcome_text += "\n您还没有加入任何群组，请点击下方按钮将机器人添加到群组。"
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup
    )

# 菜单按钮回调处理
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    
    # 记录用户点击按钮的日志
    user = update.effective_user
    button_data = query.data
    logger.info(f"用户 {user.id} ({user.full_name}) 正在点击 {button_data} 按钮")
    
    try:
        # 使用try-except块包裹查询回答操作
        await query.answer()  # 必须回答回调查询
    except Exception as e:
        logger.warning(f"回答回调查询时发生错误: {e}")
        # 回调查询可能已超时，但我们可以继续处理
    
    # 确保在按钮点击后也保持Menu按钮可见
    try:
        await context.bot.set_chat_menu_button(
            chat_id=update.effective_chat.id,
            menu_button=MenuButtonDefault()
        )
    except Exception as e:
        logger.warning(f"在按钮回调中设置菜单按钮失败: {e}")
    
    # 根据回调数据处理不同的按钮
    try:
        # 直接处理签到积分设置按钮
        if query.data.startswith("set_checkin_points"):
            logger.info(f"直接调用set_checkin_points函数处理按钮点击: {query.data}")
            await set_checkin_points(update, context)
            return
            
        # 直接处理修改签到文字按钮
        if query.data.startswith("edit_checkin_text"):
            logger.info(f"直接调用edit_checkin_text函数处理按钮点击: {query.data}")
            await edit_checkin_text(update, context)
            return
        
        # 处理群组按钮的回调
        if query.data.startswith("group_"):
            group_id = int(query.data.split("_")[1])
            
            # 创建群组特定的菜单
            keyboard = [
                [
                    InlineKeyboardButton("积分设置", callback_data=f"points_setting_{group_id}"),
                    InlineKeyboardButton("抽奖设置", callback_data=f"raffle_setting_{group_id}")
                ],
                [
                    InlineKeyboardButton("◀️ 返回群组列表", callback_data="back_to_groups")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 尝试获取群组名称
            group_name = "未知群组"
            all_groups = await get_all_active_groups()
            for gid, gtitle in all_groups:
                if gid == group_id:
                    group_name = gtitle
                    break
            
            await query.edit_message_text(
                text=f"您正在管理 {group_name} 的设置。请选择操作：",
                reply_markup=reply_markup
            )
        
        elif query.data == "back_to_groups":
            # 返回群组列表
            user = update.effective_user
            user_groups = await get_user_active_groups(user.id)
            
            # 准备键盘按钮
            keyboard = []
            
            # 为每个群组创建一个按钮
            if user_groups:
                for group_id, group_title in user_groups:
                    keyboard.append([InlineKeyboardButton(f"🏘️ {group_title}", callback_data=f"group_{group_id}")])
            
            # 添加"添加机器人到群组"按钮
            bot_username = context.bot.username
            invite_url = f"https://t.me/{bot_username}?startgroup=true"
            keyboard.append([InlineKeyboardButton("➕ 添加机器人到群组", url=invite_url)])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 构建消息
            welcome_text = "欢迎使用Telegram积分抽奖机器人！\n"
            
            if user_groups:
                welcome_text += "\n🏘️ 您已加入的群组：\n"
                for _, group_title in user_groups:
                    welcome_text += f"• {group_title}\n"
                welcome_text += "\n点击群组名称管理该群设置，或添加机器人到新群组。"
            else:
                welcome_text += "\n您还没有加入任何群组，请点击下方按钮将机器人添加到群组。"
            
            await query.edit_message_text(
                text=welcome_text,
                reply_markup=reply_markup
            )
        
        # 处理群组特定的积分设置    
        elif query.data.startswith("points_setting_"):
            # 从回调数据中提取群组ID
            group_id = int(query.data.split("_")[2])
            
            # 创建三个按钮：签到规则、发言规则、邀请规则
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
            group_name = "未知群组"
            all_groups = await get_all_active_groups()
            for gid, gtitle in all_groups:
                if gid == group_id:
                    group_name = gtitle
                    break
            
            await query.edit_message_text(
                text=f"您正在管理 {group_name} 的积分规则设置。请选择要查看的积分规则：",
                reply_markup=reply_markup
            )
            
        elif query.data == "points_setting":
            # 创建三个按钮：签到规则、发言规则、邀请规则
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
        elif query.data == "checkin_rule":
            # 调用jifen/checkin_handlers.py中的处理函数
            await show_checkin_rule_settings(update, context)
        elif query.data == "back_to_points_setting":
            # 返回到积分设置主菜单
            await back_to_points_setting(update, context)
        elif query.data == "back_to_checkin_rule":
            # 返回到签到规则设置
            await back_to_checkin_rule(update, context)
        elif query.data == "message_rule":
            # 调用jifen/message_handlers.py中的处理函数
            await show_message_rule_settings(update, context)
        elif query.data == "back_to_message_rule":
            # 返回到发言规则设置
            await back_to_message_rule(update, context)
        elif query.data == "invite_rule":
            await query.message.reply_text(
                "邀请规则：\n"
                "- 邀请新用户加入可获取积分\n"
                "- 被邀请用户留存时间越长奖励越多\n"
                "- 恶意邀请将被取消资格\n\n"
                "此功能正在开发中..."
            )
        elif query.data == "raffle_setting":
            await query.message.reply_text(
                "抽奖设置功能：\n"
                "- 创建新抽奖\n"
                "- 管理现有抽奖\n"
                "- 设置抽奖规则\n"
                "- 查看抽奖历史\n\n"
                "此功能正在开发中..."
            )
        
        # 处理群组特定的规则回调
        elif query.data.startswith("checkin_rule_"):
            # 从回调数据中提取群组ID
            group_id = int(query.data.split("_")[2])
            
            # 传递群组ID给签到规则处理函数
            await show_checkin_rule_settings(update, context, group_id)
            
        elif query.data.startswith("message_rule_"):
            # 处理群组特定的发言规则
            group_id = int(query.data.split("_")[2])
            await show_message_rule_settings(update, context, group_id)
            
        elif query.data.startswith("invite_rule_"):
            # 从回调数据中提取群组ID
            group_id = int(query.data.split("_")[2])
            
            # 尝试获取群组名称
            group_name = "未知群组"
            all_groups = await get_all_active_groups()
            for gid, gtitle in all_groups:
                if gid == group_id:
                    group_name = gtitle
                    break
            
            # 创建返回按钮
            keyboard = [
                [InlineKeyboardButton("◀️ 返回积分设置", callback_data=f"points_setting_{group_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=f"群组 {group_name} 的邀请规则：\n"
                "- 邀请新用户加入可获取积分\n"
                "- 被邀请用户留存时间越长奖励越多\n"
                "- 恶意邀请将被取消资格\n\n"
                "此功能正在开发中...",
                reply_markup=reply_markup
            )
            
        elif query.data.startswith("raffle_setting_"):
            # 从回调数据中提取群组ID
            group_id = int(query.data.split("_")[2])
            
            # 尝试获取群组名称
            group_name = "未知群组"
            all_groups = await get_all_active_groups()
            for gid, gtitle in all_groups:
                if gid == group_id:
                    group_name = gtitle
                    break
            
            # 创建返回按钮
            keyboard = [
                [InlineKeyboardButton("◀️ 返回群组设置", callback_data=f"group_{group_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=f"群组 {group_name} 的抽奖设置功能：\n"
                "- 创建新抽奖\n"
                "- 管理现有抽奖\n"
                "- 设置抽奖规则\n"
                "- 查看抽奖历史\n\n"
                "此功能正在开发中...",
                reply_markup=reply_markup
            )
        elif query.data.startswith("set_message_points"):
            # 设置发言获得数量
            await set_message_points(update, context)
        elif query.data.startswith("set_message_daily_limit"):
            # 设置每日上限
            await set_message_daily_limit(update, context)
        elif query.data.startswith("set_message_min_length"):
            # 设置最小字数长度限制
            await set_message_min_length(update, context)
    except Exception as e:
        logger.error(f"处理按钮回调时发生错误: {e}")
        try:
            # 如果可能，发送错误消息给用户
            await update.effective_chat.send_message(
                "处理您的请求时出现了问题，请稍后再试。"
            )
        except Exception:
            # 如果连发送错误消息都失败，只记录日志
            pass

# 组合处理器 - 用于处理所有文本消息
async def combined_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理所有文本消息，根据用户状态决定调用哪个具体的处理函数"""
    # 获取用户状态
    user_data = context.user_data
    
    # 记录接收到的消息，便于调试
    user = update.effective_user
    text = update.message.text
    logger.info(f"用户 {user.id} ({user.full_name}) 发送消息: {text}")
    logger.info(f"用户当前状态: {user_data}")
    
    # 根据用户状态调用相应的处理函数
    if user_data.get('waiting_for_checkin_text'):
        logger.info(f"用户处于等待输入签到文字状态，调用handle_checkin_text_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_min_length', None)
        await handle_checkin_text_input(update, context)
    elif user_data.get('waiting_for_points'):
        logger.info(f"用户处于等待输入积分状态，调用handle_points_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_min_length', None)
        await handle_points_input(update, context)
    elif user_data.get('waiting_for_message_points'):
        logger.info(f"用户处于等待输入发言积分状态，调用handle_message_points_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_min_length', None)
        await handle_message_points_input(update, context)
    elif user_data.get('waiting_for_daily_limit'):
        logger.info(f"用户处于等待输入每日上限状态，调用handle_daily_limit_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_min_length', None)
        await handle_daily_limit_input(update, context)
    elif user_data.get('waiting_for_min_length'):
        logger.info(f"用户处于等待输入最小字数长度限制状态，调用handle_min_length_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        await handle_min_length_input(update, context)
    else:
        # 非特定状态下的消息无需处理
        logger.debug(f"用户未处于特定状态，不处理消息")
        return

def run_bot():
    """运行机器人，线程安全的方式"""
    global bot_running
    
    # 使用锁确保线程安全
    with bot_lock:
        if bot_running:
            logger.info("机器人已经在运行中")
            return
        bot_running = True
    
    try:
        logger.info("正在启动Telegram机器人...")
        
        # 避免事件循环问题
        if sys.platform.startswith('win'):
            # 在Windows上，设置策略为WindowsSelectorEventLoopPolicy
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # 创建应用
        application = ApplicationBuilder().token(TOKEN).build()
        
        # 只注册start命令处理器
        application.add_handler(CommandHandler("start", start))
        logger.info("注册 /start 命令处理器")
        
        # 注册回调查询处理器
        application.add_handler(CallbackQueryHandler(button_callback))
        logger.info("注册按钮回调处理器")
        
        # 注册消息处理器 - 用于处理所有文本消息
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, combined_text_handler))
        logger.info("注册消息处理器 - 处理所有文本消息（包括积分数量和签到文字）")
        
        # 注册聊天成员处理器
        # 处理机器人自己的成员状态变化（如被添加到群组或移除）
        application.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
        logger.info("注册机器人成员状态变化处理器")
        
        # 处理其他用户的成员状态变化（如用户加入或离开群组）
        application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
        logger.info("注册群组成员状态变化处理器")
        
        # 初始化时清除所有范围内的命令并只设置start命令
        loop.run_until_complete(clear_all_commands_and_set_start(application.bot))
        
        logger.info("Telegram机器人已启动并等待命令...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("机器人已通过键盘中断停止运行")
    except Exception as e:
        logger.error(f"启动机器人时发生错误: {e}")
    finally:
        # 无论如何都重置运行状态
        with bot_lock:
            bot_running = False
            logger.info("机器人运行状态已重置")

if __name__ == '__main__':
    run_bot() 