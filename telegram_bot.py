import logging
import asyncio
import os
import sys
import threading
import time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeAllPrivateChats, InlineKeyboardButton, BotCommandScopeAllGroupChats, BotCommandScopeAllChatAdministrators, BotCommandScopeDefault, MenuButtonCommands, MenuButtonDefault
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
    handle_checkin_text_input,
    process_group_message
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
    handle_min_length_input,
    process_message_points
)

# 导入邀请规则处理模块
from jifen.invite_handlers import (
    show_invite_rule_settings,
    set_invite_points,
    set_invite_daily_limit,
    back_to_invite_rule,
    handle_invite_points_input,
    handle_invite_daily_limit_input,
    generate_invite_link,
    create_group_invite_link,
    handle_invite_start_parameter
)

# 导入群组处理模块
from jifen.group_handlers import (
    handle_my_chat_member,
    handle_chat_member,
    set_cache_clear_function
)

# 导入需要的模型
from jifen.models import Group, User

# 导入新的 points_handlers 模块中的函数
from jifen.points_handlers import (
    show_points_settings, enable_points, disable_points
)

# 导入积分查询功能
from jifen.points_query import query_user_points

# 导入抽奖处理模块
from choujiang.lottery_handlers import lottery_setup_handler, get_lottery_handlers, direct_check_lottery, view_lottery

# 导入抽奖模型
from choujiang.models import Lottery

# 其他模块将在需要时导入
# from choujiang.list_lotteries import view_group_lotteries

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

# 初始化一个简单的内存缓存，用于存储用户群组信息
# 格式: {user_id: (timestamp, groups_data)}
user_groups_cache = {}
# 缓存过期时间（秒）
CACHE_EXPIRY = 60  # 1分钟

# 清除特定用户的群组缓存
def clear_user_groups_cache(telegram_id):
    """清除特定用户的群组缓存"""
    if telegram_id in user_groups_cache:
        del user_groups_cache[telegram_id]
        logger.info(f"已清除用户 {telegram_id} 的群组缓存")

# 设置缓存清除函数的引用到group_handlers模块
set_cache_clear_function(clear_user_groups_cache)

@sync_to_async
def is_user_admin(telegram_id):
    """检查用户是否是管理员"""
    try:
        from jifen.models import User
        return User.objects.filter(telegram_id=telegram_id, is_admin=True).exists()
    except Exception as e:
        logger.error(f"检查用户管理员状态时出错: {e}")
        return False

@sync_to_async
def get_user_active_groups(telegram_id, force_refresh=False):
    """
    获取用户所在的所有活跃群组，带缓存功能
    
    参数:
    telegram_id: 用户的Telegram ID
    force_refresh: 是否强制刷新缓存，默认为False
    """
    # 如果强制刷新或在用户加入/离开群组后调用，跳过缓存
    if force_refresh and telegram_id in user_groups_cache:
        clear_user_groups_cache(telegram_id)
        logger.info(f"强制刷新用户 {telegram_id} 的群组数据")
    
    # 检查缓存
    current_time = time.time()
    if telegram_id in user_groups_cache:
        cache_time, groups_data = user_groups_cache[telegram_id]
        if current_time - cache_time < CACHE_EXPIRY:
            logger.info(f"从缓存获取用户 {telegram_id} 的群组数据")
            return groups_data
    
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
        
        # 更新缓存
        user_groups_cache[telegram_id] = (current_time, groups_info)
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
    logger.info("正在初始化机器人命令...")
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
        
    logger.info("机器人命令初始化完成")

# start命令处理函数
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理/start命令，显示基本介绍和群组选择"""
    user = update.effective_user
    
    logger.info(f"处理/start命令，用户ID={user.id}，用户名={user.first_name}，参数={context.args}")
    
    # 添加一条明确的测试消息
    await update.message.reply_text(f"👋 你好，{user.first_name}！我是机器人，正在处理你的请求...")
    
    try:
        # 检查是否有深度链接参数
        if context.args:
            # 转发给lottery_handlers.py中的handle_start_command处理
            from choujiang.lottery_handlers import handle_start_command
            logger.info(f"检测到深度链接参数，转发给handle_start_command处理: {context.args}")
            return await handle_start_command(update, context)
        
        # 检查用户是否是管理员
        is_admin = await is_user_admin(user.id)
        
        if is_admin:
            # 管理员: 发送群组列表
            # 获取用户关联的群组
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
            
            # 添加"生成邀请链接"按钮
            keyboard.append([InlineKeyboardButton("🔗 生成邀请链接", callback_data="generate_invite")])
            
            # 构建欢迎消息
            welcome_text = "欢迎使用Telegram积分抽奖机器人！\n"
            
            if user_groups:
                welcome_text += "\n🏘️ 您已加入的群组：\n"
                for _, group_title in user_groups:
                    welcome_text += f"• {group_title}\n"
                welcome_text += "\n点击群组名称管理该群设置，或添加机器人到新群组。"
            else:
                welcome_text += "\n您还没有加入任何群组，请点击下方按钮将机器人添加到群组。"
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 发送欢迎消息
            await update.message.reply_text(welcome_text, reply_markup=reply_markup)
            logger.info(f"已向管理员 {user.id} 发送欢迎消息和群组列表")
            return
        
        # 普通用户: 先发送简单的欢迎消息和查看抽奖按钮
        # 获取一个活跃的抽奖ID
        @sync_to_async
        def get_active_lottery_id():
            from choujiang.models import Lottery
            lottery = Lottery.objects.filter(status='ACTIVE').order_by('-created_at').first()
            return lottery.id if lottery else None
            
        lottery_id = await get_active_lottery_id()
        logger.info(f"获取到活跃的抽奖ID: {lottery_id}")
        
        if lottery_id:
            # 创建一个带有抽奖ID的按钮
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 查看抽奖详情", callback_data=f"view_lottery_{lottery_id}")]
            ])
            
            await update.message.reply_text(
                f"👋 你好，{user.first_name}！\n\n"
                f"欢迎使用Telegram积分抽奖机器人！\n\n"
                f"我们有一个正在进行的抽奖活动，点击下方按钮立即查看详情。",
                reply_markup=keyboard
            )
            logger.info(f"已向用户 {user.id} 发送抽奖查看按钮，抽奖ID={lottery_id}")
        else:
            # 没有活跃的抽奖，只显示欢迎消息
            await update.message.reply_text(
                f"👋 你好，{user.first_name}！\n\n"
                f"欢迎使用Telegram积分抽奖机器人！\n\n"
                f"目前没有正在进行的抽奖活动，请稍后再来查看，或输入 /check_lottery 命令查询所有抽奖。"
            )
            logger.info(f"已向用户 {user.id} 发送欢迎消息，没有找到活跃抽奖")
        
    except Exception as e:
        logger.error(f"处理/start命令时出错: {e}", exc_info=True)
        await update.message.reply_text("加载抽奖活动时出错，请手动输入 /check_lottery 命令查看可参与的抽奖。")

# 菜单按钮回调处理
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    user = update.effective_user
    
    logger.info(f"用户 {user.id} ({user.full_name}) 点击了按钮，数据: {query.data}")
    
    try:
        # 先回复查询以避免Telegram超时错误
        await query.answer()
        
        # 检查是否是查看抽奖的回调
        if query.data.startswith("view_lottery_"):
            # 这是查看抽奖的回调，调用lottery_handlers.py中的view_lottery函数
            from choujiang.lottery_handlers import view_lottery
            logger.info(f"检测到查看抽奖回调, 调用view_lottery函数: {query.data}")
            return await view_lottery(update, context)
        
        # 根据回调数据分别处理其他情况
        if query.data == "menu":
            # 显示菜单
            await show_menu(update, context)
        
        # 处理生成邀请链接
        elif query.data == "generate_invite":
            await generate_invite_link(update, context)
            
        # 处理特定群组的邀请链接请求
        elif query.data.startswith("invite_link_"):
            await create_group_invite_link(update, context)
        
        # 处理群组按钮的回调
        elif query.data.startswith("group_"):
            group_id = int(query.data.split("_")[1])
            
            # 创建群组特定的菜单
            keyboard = [
                [
                    InlineKeyboardButton("积分设置", callback_data=f"points_setting_{group_id}"),
                    InlineKeyboardButton("抽奖设置", callback_data=f"raffle_setting_{group_id}")
                ],
                [
                    InlineKeyboardButton("📊 查看抽奖列表", callback_data=f"list_lotteries_{group_id}")
                ],
                [
                    InlineKeyboardButton("🔗 生成邀请链接", callback_data=f"invite_link_{group_id}")
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
        
        # 处理查看群组抽奖列表
        elif query.data.startswith("list_lotteries_"):
            from choujiang.list_lotteries import view_group_lotteries
            await view_group_lotteries(update, context)
        
        elif query.data == "back_to_groups":
            # 返回群组列表
            user = update.effective_user
            # 强制刷新缓存，确保显示最新的群组列表
            user_groups = await get_user_active_groups(user.id, force_refresh=True)
            
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
            
            # 添加"生成邀请链接"按钮
            keyboard.append([InlineKeyboardButton("🔗 生成邀请链接", callback_data="generate_invite")])
            
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
            
            # 为特定群组显示积分总设置页面
            await show_points_settings(update, context, group_id, query)
        elif query.data == "checkin_rule":
            # 调用jifen/checkin_handlers.py中的处理函数
            await show_checkin_rule_settings(update, context)
        elif query.data == "back_to_points_setting":
            # 返回到积分设置主菜单
            await show_points_settings(update, context)
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
            # 调用jifen/invite_handlers.py中的处理函数
            await show_invite_rule_settings(update, context)
        elif query.data == "back_to_invite_rule":
            # 返回到邀请规则设置
            await back_to_invite_rule(update, context)
        elif query.data.startswith("set_invite_points"):
            # 设置邀请积分数量
            await set_invite_points(update, context)
        elif query.data.startswith("set_invite_daily_limit"):
            # 设置邀请每日上限
            await set_invite_daily_limit(update, context)
        
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
            
            # 调用invitation_handlers.py中的处理函数
            await show_invite_rule_settings(update, context, group_id)
            
        elif query.data.startswith("set_message_points"):
            # 设置发言获得数量
            await set_message_points(update, context)
        elif query.data.startswith("set_message_daily_limit"):
            # 设置每日上限
            await set_message_daily_limit(update, context)
        elif query.data.startswith("set_message_min_length"):
            # 设置最小字数长度限制
            await set_message_min_length(update, context)
        elif query.data.startswith("edit_checkin_text"):
            # 修改签到文字
            await edit_checkin_text(update, context)
        elif query.data.startswith("set_checkin_points"):
            # 设置签到获得数量
            await set_checkin_points(update, context)
        elif query.data.startswith("enable_points"):
            # 启用积分功能
            await enable_points(update, context)
        elif query.data.startswith("disable_points"):
            # 关闭积分功能
            await disable_points(update, context)
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

# 定义组合处理函数，先检查签到，再处理发言积分
async def combined_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    组合消息处理器，先检查是否是签到消息，如果不是，再处理发言积分
    """
    # 检查是否是"邀请链接"请求
    if update.message.text and update.message.text.strip() == "邀请链接":
        logger.info(f"用户 {update.effective_user.id} 在群组中请求生成邀请链接")
        await generate_invite_link(update, context)
        return
    
    # 检查是否是"积分"查询请求
    if update.message.text and update.message.text.strip() == "积分":
        logger.info(f"用户 {update.effective_user.id} 在群组中查询积分")
        is_queried = await query_user_points(update, context)
        if is_queried:
            return
    
    # 先调用签到处理函数
    is_checkin = await process_group_message(update, context)
    
    # 如果不是签到消息，再处理发言积分
    if not is_checkin:
        await process_message_points(update, context)

# 组合处理器 - 用于处理所有文本消息
async def combined_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理所有文本消息，根据用户状态决定调用哪个具体的处理函数"""
    user_data = context.user_data
    logger.info(f"收到来自用户 {update.effective_user.id} 的文本消息")
    
    # 检查是否是"邀请链接"请求
    if update.message.text and update.message.text.strip() == "邀请链接":
        logger.info(f"用户 {update.effective_user.id} 在私聊中请求生成邀请链接")
        await generate_invite_link(update, context)
        return
    
    # 根据用户状态决定处理方式
    if not user_data:
        logger.debug(f"用户 {update.effective_user.id} 没有状态数据")
        return
    
    if user_data.get('waiting_for_checkin_text'):
        logger.info(f"用户处于等待输入签到文字状态，调用handle_checkin_text_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_min_length', None)
        user_data.pop('waiting_for_invite_points', None)
        await handle_checkin_text_input(update, context)
    elif user_data.get('waiting_for_points'):
        logger.info(f"用户处于等待输入签到积分状态，调用handle_points_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_min_length', None)
        user_data.pop('waiting_for_invite_points', None)
        await handle_points_input(update, context)
    elif user_data.get('waiting_for_message_points'):
        logger.info(f"用户处于等待输入发言积分状态，调用handle_message_points_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_min_length', None)
        user_data.pop('waiting_for_invite_points', None)
        await handle_message_points_input(update, context)
    elif user_data.get('waiting_for_daily_limit'):
        logger.info(f"用户处于等待输入每日上限状态，调用handle_daily_limit_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_min_length', None)
        user_data.pop('waiting_for_invite_points', None)
        await handle_daily_limit_input(update, context)
    elif user_data.get('waiting_for_min_length'):
        logger.info(f"用户处于等待输入最小字数长度限制状态，调用handle_min_length_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_invite_points', None)
        await handle_min_length_input(update, context)
    elif user_data.get('waiting_for_invite_points'):
        logger.info(f"用户处于等待输入邀请积分状态，调用handle_invite_points_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_min_length', None)
        user_data.pop('waiting_for_invite_daily_limit', None)
        await handle_invite_points_input(update, context)
    elif user_data.get('waiting_for_invite_daily_limit'):
        logger.info(f"用户处于等待输入邀请每日上限状态，调用handle_invite_daily_limit_input")
        # 确保其他输入状态被清除
        user_data.pop('waiting_for_checkin_text', None)
        user_data.pop('waiting_for_points', None)
        user_data.pop('waiting_for_message_points', None)
        user_data.pop('waiting_for_daily_limit', None)
        user_data.pop('waiting_for_min_length', None)
        user_data.pop('waiting_for_invite_points', None)
        await handle_invite_daily_limit_input(update, context)
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
        
        # 注册命令处理器
        application.add_handler(CommandHandler("start", start))
        logger.info("注册 /start 命令处理器")

        # 注册邀请命令处理器
        application.add_handler(CommandHandler("invite", generate_invite_link))
        logger.info("注册 /invite 命令处理器")

        # 注册抽奖设置处理器（放在最前面）
        application.add_handler(lottery_setup_handler)
        logger.info("注册抽奖设置处理器 [lottery_setup_handler]")

        # 注册抽奖相关的其他处理器
        lottery_handlers = get_lottery_handlers()
        logger.info(f"获取到 {len(lottery_handlers)} 个抽奖相关处理器")
        for handler in lottery_handlers:
            # 排除另一个CommandHandler("start")处理器，确保只有一个start命令处理器
            if handler.__class__.__name__ == "CommandHandler" and getattr(handler, 'command', None) == ['start']:
                logger.info(f"跳过重复的start命令处理器")
                continue
                
            if handler != lottery_setup_handler:  # 避免重复注册
                application.add_handler(handler)
                logger.info(f"注册抽奖相关处理器: {handler.__class__.__name__}, Pattern: {getattr(handler, 'pattern', 'None')}")

        # 注册回调查询处理器
        application.add_handler(CallbackQueryHandler(button_callback))
        logger.info("注册按钮回调处理器")

        # 使用组合处理器处理群组消息（同时处理签到和发言积分）
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, 
            combined_group_message_handler
        ))
        logger.info("注册组合群组消息处理器（签到+发言积分）")

        # 注册私聊消息处理器（移到最后）
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.ChatType.GROUPS, 
            combined_text_handler
        ))
        logger.info("注册私聊消息处理器")

        # 注册聊天成员处理器
        application.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
        application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
        logger.info("注册成员状态变化处理器")

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