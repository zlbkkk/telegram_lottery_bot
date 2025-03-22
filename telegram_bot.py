import logging
import asyncio
import os
import sys
import threading
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, BotCommandScopeAllChatAdministrators, BotCommandScopeDefault, MenuButtonCommands, MenuButtonDefault
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, filters, ChatMemberHandler
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
    back_to_checkin_rule
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
    
    # 添加积分设置和抽奖设置按钮
    keyboard.append([
        InlineKeyboardButton("积分设置", callback_data="points_setting"),
        InlineKeyboardButton("抽奖设置", callback_data="raffle_setting")
    ])
    
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
    
    welcome_text += "\n\n您也可以通过以下菜单使用各项功能："
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup
    )

# 菜单按钮回调处理
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    
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
            
            # 添加积分设置和抽奖设置按钮
            keyboard.append([
                InlineKeyboardButton("积分设置", callback_data="points_setting"),
                InlineKeyboardButton("抽奖设置", callback_data="raffle_setting")
            ])
            
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
            
            welcome_text += "\n\n您也可以通过以下菜单使用各项功能："
            
            await query.edit_message_text(
                text=welcome_text,
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