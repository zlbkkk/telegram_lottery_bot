import logging
import asyncio
import os
import sys
import threading
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, BotCommandScopeAllChatAdministrators, BotCommandScopeDefault, MenuButtonCommands, MenuButtonDefault
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, filters, ChatMemberHandler

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
    back_to_checkin_rule
)

# 导入群组处理模块
from jifen.group_handlers import (
    handle_my_chat_member,
    handle_chat_member
)

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
    """发送start菜单"""
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
    
    keyboard = [
        [
            InlineKeyboardButton("积分设置", callback_data="points_setting"),
            InlineKeyboardButton("抽奖设置", callback_data="raffle_setting")
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "欢迎使用Telegram积分抽奖机器人！\n"
        "您可以通过以下菜单使用各项功能：",
        reply_markup=reply_markup
    )

# 菜单按钮回调处理
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    await query.answer()  # 必须回答回调查询
    
    # 确保在按钮点击后也保持Menu按钮可见
    try:
        await context.bot.set_chat_menu_button(
            chat_id=update.effective_chat.id,
            menu_button=MenuButtonDefault()
        )
    except Exception as e:
        logger.warning(f"在按钮回调中设置菜单按钮失败: {e}")
    
    # 根据回调数据处理不同的按钮
    if query.data == "points_setting":
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
    elif query.data == "edit_checkin_text":
        # 处理修改签到文字的请求
        await edit_checkin_text(update, context)
    elif query.data == "set_checkin_points":
        # 处理设置签到积分数量的请求
        await set_checkin_points(update, context)
    elif query.data == "back_to_points_setting":
        # 返回到积分设置主菜单
        await back_to_points_setting(update, context)
    elif query.data == "back_to_checkin_rule":
        # 返回到签到规则设置
        await back_to_checkin_rule(update, context)
    elif query.data == "message_rule":
        await query.message.reply_text(
            "发言规则：\n"
            "- 每条消息可获取积分\n"
            "- 相同内容不重复计分\n"
            "- 禁止刷屏获取积分\n\n"
            "此功能正在开发中..."
        )
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
        logger.info("启动Telegram机器人...")
        
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
        
        # 注册回调查询处理器
        application.add_handler(CallbackQueryHandler(button_callback))
        
        # 注册聊天成员处理器
        # 处理机器人自己的成员状态变化（如被添加到群组或移除）
        application.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
        
        # 处理其他用户的成员状态变化（如用户加入或离开群组）
        application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
        
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

if __name__ == '__main__':
    run_bot() 