from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)
from datetime import datetime, timedelta, timezone as dt_timezone
from .models import Lottery, LotteryType, LotteryRequirement
from jifen.models import Group, User
import logging
from asgiref.sync import sync_to_async
import traceback
from django.utils import timezone
import asyncio

# 设置日志
logger = logging.getLogger(__name__)

# 定义对话状态
TITLE = 1
DESCRIPTION = 2  # 描述输入状态
REQUIREMENT = 3  # 添加参与条件状态
PRIZE_SETUP = 4  # 奖品信息设置状态
PRIZE_NAME = 5   # 奖项名称输入状态
PRIZE_DESC = 6   # 奖品内容输入状态
PRIZE_COUNT = 7  # 中奖人数输入状态
POINTS_REQUIRED = 8  # 设置参与抽奖扣除的积分
MEDIA_UPLOAD = 9  # 媒体上传状态
SIGNUP_DEADLINE = 10  # 报名截止时间设置状态
DRAW_TIME = 11    # 开奖时间设置状态
CUSTOM_DEADLINE = 12  # 自定义截止时间输入状态
CUSTOM_DRAW_TIME = 13  # 自定义开奖时间输入状态
NOTIFY_PRIVATE = 14   # 设置是否私信通知中奖者
ANNOUNCE_GROUP = 15   # 设置是否在群组内公布结果
PIN_RESULTS = 16      # 设置是否置顶结果

async def start_lottery_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理抽奖设置按钮点击"""
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    await query.answer()
    
    # 从回调数据中提取群组ID
    group_id = int(query.data.split("_")[2])
    logger.info(f"[抽奖设置] 用户 {user.id} ({user.username or user.first_name}) 开始设置抽奖，群组ID: {group_id}, chat_id: {chat_id}")
    
    try:
        # 获取群组信息
        group = await sync_to_async(Group.objects.get)(group_id=group_id)
        logger.info(f"[抽奖设置] 成功获取群组信息: {group.group_title} (ID: {group.group_id})")
        
        # 获取用户信息（使用sync_to_async包装整个查询操作）
        @sync_to_async
        def get_user():
            return User.objects.select_related('group').filter(telegram_id=user.id, group=group).first()
        
        user_obj = await get_user()
        
        # 使用sync_to_async包装字符串表示
        @sync_to_async
        def get_user_str(user_obj):
            if user_obj:
                return f"{user_obj.first_name} {user_obj.last_name} ({user_obj.telegram_id}) in {user_obj.group.group_title}"
            return "User not found"
            
        user_str = await get_user_str(user_obj)
        logger.info(f"[抽奖设置] 获取用户信息: {user_str}")
        
        if not user_obj:
            logger.warning(f"[抽奖设置] 用户 {user.id} 不是群组 {group_id} 的成员")
            await query.message.reply_text("您不是该群组的成员，无法设置抽奖。")
            return ConversationHandler.END
        
        # 存储群组和用户信息到上下文
        context.user_data['lottery_setup'] = {
            'group_id': group_id,
            'group': group,
            'user': user_obj,
            'chat_id': chat_id
        }
        logger.info(f"[抽奖设置] 已将设置信息存入上下文: {context.user_data['lottery_setup']}")
        
        # 发送标题输入提示
        await query.edit_message_text(
            "📝 抽奖基本信息设置\n\n"
            "请输入抽奖活动的标题：\n"
            "(例如: \"周末大抽奖\"、\"新品上市庆祝抽奖\")"
        )
        logger.info(f"[抽奖设置] 已发送标题输入提示，等待用户在chat_id {chat_id}中输入标题")
        
        return TITLE
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理抽奖设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def title_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理标题输入"""
    message = update.message
    title = message.text
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    logger.info(f"[抽奖设置] 用户 {user.id} ({user.username or user.first_name}) 在chat_id {chat_id}中输入了抽奖标题: {title}")
    
    try:
        lottery_data = context.user_data.get('lottery_setup')
        logger.info(f"[抽奖设置] 从上下文获取的lottery_data: {lottery_data}")
        
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
            
        if chat_id != lottery_data.get('chat_id'):
            logger.warning(f"[抽奖设置] chat_id不匹配: 期望{lottery_data.get('chat_id')}，实际{chat_id}")
            return
        
        # 存储标题到上下文
        lottery_data['title'] = title
        logger.info(f"[抽奖设置] 已保存标题到上下文: {title}")
        
        # 请求输入描述
        await message.reply_text(
            "请输入抽奖活动的描述：\n"
            "(可以包含活动背景、规则说明等)"
        )
        logger.info("[抽奖设置] 已发送描述输入提示")
        
        return DESCRIPTION
        
    except Exception as e:
        error_message = f"保存标题时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def description_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理描述输入"""
    message = update.message
    description = message.text
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    logger.info(f"[抽奖设置] 用户 {user.id} ({user.username or user.first_name}) 在chat_id {chat_id}中输入了抽奖描述")
    
    try:
        lottery_data = context.user_data.get('lottery_setup')
        logger.info(f"[抽奖设置] 从上下文获取的lottery_data: {lottery_data}")
        
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
            
        if chat_id != lottery_data.get('chat_id'):
            logger.warning(f"[抽奖设置] chat_id不匹配: 期望{lottery_data.get('chat_id')}，实际{chat_id}")
            return
        
        # 存储描述到上下文
        lottery_data['description'] = description
        logger.info(f"[抽奖设置] 已保存描述到上下文")
        
        # 获取或创建默认抽奖类型
        @sync_to_async
        def get_or_create_lottery_type():
            return LotteryType.objects.get_or_create(
                name="常规抽奖",
                defaults={"description": "常规抽奖活动"}
            )
            
        lottery_type_result = await get_or_create_lottery_type()
        lottery_type = lottery_type_result[0]
        logger.info(f"[抽奖设置] 获取到抽奖类型: {lottery_type.name} (ID: {lottery_type.id})")
        
        # 创建抽奖活动
        try:
            @sync_to_async
            def create_lottery():
                return Lottery.objects.create(
                    title=lottery_data['title'],
                    description=description,
                    group=lottery_data['group'],
                    creator=lottery_data['user'],
                    lottery_type=lottery_type,
                    status='DRAFT'
                )
                
            lottery = await create_lottery()
            lottery_data['lottery'] = lottery
            logger.info(f"[抽奖设置] 成功创建抽奖活动: ID={lottery.id}, 标题={lottery.title}")
            
        except Exception as e:
            logger.error(f"[抽奖设置] 创建抽奖活动时出错: {e}\n{traceback.format_exc()}")
            raise
        
        # 显示参与条件设置选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 必须关注特定频道/群组", callback_data=f"req_channel_{lottery.id}")],
            [InlineKeyboardButton("⏭️ 跳过设置参与条件", callback_data=f"skip_requirement_{lottery.id}")]
        ])
        
        await message.reply_text(
            "🔍 设置参与条件\n\n"
            "用户需要满足哪些条件才能参与抽奖？",
            reply_markup=keyboard
        )
        logger.info(f"[抽奖设置] 已发送参与条件设置提示")
        
        return REQUIREMENT
        
    except Exception as e:
        error_message = f"创建抽奖活动时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def requirement_channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择设置频道/群组关注要求"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[2])
        logger.info(f"[抽奖设置] 用户 {user.id} 选择为抽奖ID={lottery_id}设置频道/群组关注要求")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'lottery' not in lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在或lottery未创建")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 将lottery_id保存到上下文
        lottery_data['current_lottery_id'] = lottery_id
        
        await query.edit_message_text(
            "请输入用户需要关注的频道或群组链接:\n\n"
            "格式: @channel_name 或 https://t.me/channel_name\n"
            "例如: @telegram 或 https://t.me/telegram"
        )
        
        # 设置用户状态为等待输入频道/群组链接
        context.user_data['waiting_for_channel_link'] = True
        
        return REQUIREMENT
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理频道/群组要求设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def requirement_link_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户输入的频道/群组链接"""
    message = update.message
    channel_link = message.text
    user = update.effective_user
    
    if not context.user_data.get('waiting_for_channel_link'):
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_channel_link', None)
    
    try:
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning("[抽奖设置] lottery_setup 或 current_lottery_id 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        lottery_id = lottery_data['current_lottery_id']
        logger.info(f"[抽奖设置] 用户 {user.id} 输入了频道/群组链接: {channel_link} 用于抽奖ID={lottery_id}")
        
        # 创建抽奖条件记录
        try:
            # 使用sync_to_async包装创建LotteryRequirement记录
            @sync_to_async
            def create_requirement(lottery_id, channel_link):
                from .models import Lottery, LotteryRequirement
                lottery = Lottery.objects.get(id=lottery_id)
                
                requirement = LotteryRequirement(
                    lottery=lottery,
                    requirement_type='GROUP',  # 默认设置为群组，后续可优化判断
                    chat_identifier=channel_link
                )
                
                # 处理链接格式
                identifier = channel_link.strip()
                if identifier.startswith('https://t.me/'):
                    identifier = identifier[13:]
                elif identifier.startswith('@'):
                    identifier = identifier[1:]
                if '/' in identifier:
                    identifier = identifier.split('/')[0]
                
                requirement.group_username = identifier
                requirement.save()
                return requirement
                
            requirement = await create_requirement(lottery_id, channel_link)
            logger.info(f"[抽奖设置] 成功创建抽奖条件: {requirement}")
            
            # 提供继续添加或下一步的选项
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ 继续添加频道/群组", callback_data=f"add_more_channel_{lottery_id}")],
                [InlineKeyboardButton("⏭️ 下一步", callback_data=f"next_step_after_requirement_{lottery_id}")]
            ])
            
            await message.reply_text(
                f"✅ 已添加参与条件: 必须关注 {channel_link}\n\n"
                f"您可以继续添加更多频道/群组，或进入下一步。",
                reply_markup=keyboard
            )
            
            # 不清理上下文数据，保留以便继续添加
            return REQUIREMENT
            
        except Exception as e:
            logger.error(f"[抽奖设置] 创建抽奖条件时出错: {e}\n{traceback.format_exc()}")
            raise
        
    except Exception as e:
        error_message = f"设置抽奖条件时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def add_more_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择继续添加频道/群组"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[3])
        logger.info(f"[抽奖设置] 用户 {user.id} 选择为抽奖ID={lottery_id}继续添加频道/群组")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 更新lottery_id
        lottery_data['current_lottery_id'] = lottery_id
        
        await query.edit_message_text(
            "请输入用户需要关注的另一个频道或群组链接:\n\n"
            "格式: @channel_name 或 https://t.me/channel_name\n"
            "例如: @telegram 或 https://t.me/telegram"
        )
        
        # 设置用户状态为等待输入频道/群组链接
        context.user_data['waiting_for_channel_link'] = True
        
        return REQUIREMENT
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理继续添加频道/群组时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def next_step_after_requirement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户完成添加参与条件，进入奖品信息设置"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[4])
        logger.info(f"[抽奖设置] 用户 {user.id} 已完成添加参与条件，进入奖品信息设置")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 获取已设置的参与条件
        @sync_to_async
        def get_requirements(lottery_id):
            from .models import Lottery, LotteryRequirement
            lottery = Lottery.objects.get(id=lottery_id)
            return list(LotteryRequirement.objects.filter(lottery=lottery))
            
        requirements = await get_requirements(lottery_id)
        
        # 构建条件列表文本
        requirements_text = ""
        for req in requirements:
            if req.requirement_type == 'CHANNEL':
                display_name = req.channel_username or req.channel_id
                requirements_text += f"• 关注频道: {display_name}\n"
            elif req.requirement_type == 'GROUP':
                display_name = req.group_username or req.group_id
                requirements_text += f"• 加入群组: {display_name}\n"
        
        if not requirements_text:
            requirements_text = "无特殊参与条件"
        
        # 提供奖品信息设置选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1个奖项", callback_data=f"setup_single_prize_{lottery_id}")],
            [InlineKeyboardButton("多个奖项", callback_data=f"setup_multiple_prize_{lottery_id}")]
        ])
        
        await query.edit_message_text(
            f"🎁 设置奖品信息\n\n"
            f"您想设置多少个奖项？",
            reply_markup=keyboard
        )
        
        # 更新上下文状态，标记当前是在设置奖品信息阶段
        lottery_data['prize_setup_stage'] = True
        
        return PRIZE_SETUP  # 返回新的对话状态
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理完成参与条件设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def skip_requirement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户跳过设置参与条件"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[2])
        logger.info(f"[抽奖设置] 用户 {user.id} 跳过为抽奖ID={lottery_id}设置参与条件")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 提供奖品信息设置选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1个奖项", callback_data=f"setup_single_prize_{lottery_id}")],
            [InlineKeyboardButton("多个奖项", callback_data=f"setup_multiple_prize_{lottery_id}")]
        ])
        
        await query.edit_message_text(
            f"🎁 设置奖品信息\n\n"
            f"您想设置多少个奖项？",
            reply_markup=keyboard
        )
        
        # 更新上下文状态，标记当前是在设置奖品信息阶段
        lottery_data['prize_setup_stage'] = True
        lottery_data['current_lottery_id'] = lottery_id
        
        return PRIZE_SETUP
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理跳过参与条件时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def cancel_lottery_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """取消抽奖设置"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    logger.info(f"用户 {user.id} 取消了抽奖设置")
    
    # 清理上下文数据
    if 'lottery_setup' in context.user_data:
        del context.user_data['lottery_setup']
    
    # 返回群组管理菜单
    group_id = int(query.data.split("_")[3])
    keyboard = [
        [
            InlineKeyboardButton("积分设置", callback_data=f"points_setting_{group_id}"),
            InlineKeyboardButton("抽奖设置", callback_data=f"raffle_setting_{group_id}")
        ],
        [
            InlineKeyboardButton("🔗 生成邀请链接", callback_data=f"invite_link_{group_id}")
        ],
        [
            InlineKeyboardButton("◀️ 返回群组列表", callback_data="back_to_groups")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "已取消抽奖设置。\n"
        "您可以继续管理群组设置。",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

async def setup_single_prize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择设置1个奖项"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[3])
        logger.info(f"[抽奖设置] 用户 {user.id} 选择为抽奖ID={lottery_id}设置1个奖项")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 标记为单奖项模式
        lottery_data['single_prize_mode'] = True
        lottery_data['current_lottery_id'] = lottery_id
        
        await query.edit_message_text(
            "请输入奖项名称：\n\n"
            "例如：一等奖、特等奖、幸运奖等"
        )
        
        # 设置用户状态为等待输入奖项名称
        context.user_data['waiting_for_prize_name'] = True
        
        return PRIZE_NAME
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理设置单个奖项时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def setup_multiple_prize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择设置多个奖项"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[3])
        logger.info(f"[抽奖设置] 用户 {user.id} 选择为抽奖ID={lottery_id}设置多个奖项")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 标记为多奖项模式
        lottery_data['single_prize_mode'] = False
        lottery_data['current_lottery_id'] = lottery_id
        lottery_data['prizes'] = []  # 初始化奖品列表
        
        await query.edit_message_text(
            "请输入第一个奖项的名称：\n\n"
            "例如：一等奖、特等奖、幸运奖等"
        )
        
        # 设置用户状态为等待输入奖项名称
        context.user_data['waiting_for_prize_name'] = True
        context.user_data['current_prize_index'] = 0
        
        return PRIZE_NAME
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理设置多个奖项时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def prize_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户输入的奖项名称"""
    message = update.message
    prize_name = message.text
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if not context.user_data.get('waiting_for_prize_name'):
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_prize_name', None)
    
    try:
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning("[抽奖设置] lottery_setup 或 current_lottery_id 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 将奖项名称保存到上下文
        if lottery_data.get('single_prize_mode', True):
            lottery_data['prize_name'] = prize_name
        else:
            # 对于多奖项模式，使用列表记录每个奖项
            index = context.user_data.get('current_prize_index', 0)
            if 'prizes' not in lottery_data:
                lottery_data['prizes'] = []
            
            # 如果是新奖项，添加到列表
            if index >= len(lottery_data['prizes']):
                lottery_data['prizes'].append({})
            
            lottery_data['prizes'][index]['name'] = prize_name
        
        logger.info(f"[抽奖设置] 用户 {user.id} 输入了奖项名称: {prize_name}")
        
        # 请求输入奖品内容
        await message.reply_text(
            "请输入奖品内容：\n\n"
            "例如：iPhone 15 Pro一台、100元现金红包等"
        )
        
        # 设置用户状态为等待输入奖品内容
        context.user_data['waiting_for_prize_desc'] = True
        
        return PRIZE_DESC
        
    except Exception as e:
        error_message = f"保存奖项名称时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def prize_description_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户输入的奖品内容"""
    message = update.message
    prize_desc = message.text
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if not context.user_data.get('waiting_for_prize_desc'):
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_prize_desc', None)
    
    try:
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning("[抽奖设置] lottery_setup 或 current_lottery_id 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 将奖品内容保存到上下文
        if lottery_data.get('single_prize_mode', True):
            lottery_data['prize_desc'] = prize_desc
        else:
            index = context.user_data.get('current_prize_index', 0)
            lottery_data['prizes'][index]['description'] = prize_desc
        
        logger.info(f"[抽奖设置] 用户 {user.id} 输入了奖品内容: {prize_desc}")
        
        # 请求输入中奖人数
        await message.reply_text(
            "请输入中奖人数：\n\n"
            "例如：1、3、5等数字"
        )
        
        # 设置用户状态为等待输入中奖人数
        context.user_data['waiting_for_prize_count'] = True
        
        return PRIZE_COUNT
        
    except Exception as e:
        error_message = f"保存奖品内容时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def prize_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户输入的中奖人数"""
    message = update.message
    prize_count_text = message.text
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if not context.user_data.get('waiting_for_prize_count'):
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_prize_count', None)
    
    try:
        # 验证输入是否为有效数字
        try:
            prize_count = int(prize_count_text)
            if prize_count <= 0:
                await message.reply_text("中奖人数必须大于0，请重新输入：")
                context.user_data['waiting_for_prize_count'] = True
                return PRIZE_COUNT
        except ValueError:
            await message.reply_text("请输入有效的数字，例如：1、3、5等")
            context.user_data['waiting_for_prize_count'] = True
            return PRIZE_COUNT
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning("[抽奖设置] lottery_setup 或 current_lottery_id 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        lottery_id = lottery_data['current_lottery_id']
        
        # 将中奖人数保存到上下文
        if lottery_data.get('single_prize_mode', True):
            lottery_data['prize_count'] = prize_count
            
            # 单奖项模式直接保存奖品信息
            try:
                # 使用sync_to_async包装创建Prize记录
                @sync_to_async
                def create_prize(lottery_id, name, desc, count):
                    from .models import Lottery, Prize
                    lottery = Lottery.objects.get(id=lottery_id)
                    
                    prize = Prize(
                        lottery=lottery,
                        name=name,
                        description=desc,
                        quantity=count,
                        order=0  # 单奖项默认顺序为0
                    )
                    prize.save()
                    return prize
                
                prize = await create_prize(
                    lottery_id, 
                    lottery_data['prize_name'], 
                    lottery_data['prize_desc'], 
                    prize_count
                )
                logger.info(f"[抽奖设置] 成功创建奖品: {prize}")
                
                # 构建奖品列表文本
                prizes_text = f"• {lottery_data['prize_name']}: {lottery_data['prize_desc']} ({prize_count}名)\n"
                
                # 设置参与积分
                await message.reply_text(
                    f"💰 设置参与积分\n\n"
                    f"请设置用户参与此次抽奖需要消耗的积分数量：\n"
                    f"(设置为0表示不需要积分即可参与)"
                )
                
                # 设置用户状态为等待输入积分
                context.user_data['waiting_for_points_required'] = True
                context.user_data['current_lottery_id'] = lottery_id
                
                return POINTS_REQUIRED
                
            except Exception as e:
                logger.error(f"[抽奖设置] 创建奖品时出错: {e}\n{traceback.format_exc()}")
                raise
        else:
            # 多奖项模式，处理当前奖项并询问是否继续添加
            index = context.user_data.get('current_prize_index', 0)
            lottery_data['prizes'][index]['quantity'] = prize_count
            lottery_data['prizes'][index]['order'] = index  # 设置显示顺序
            
            # 保存当前奖项到数据库
            try:
                @sync_to_async
                def create_prize(lottery_id, prize_data):
                    from .models import Lottery, Prize
                    lottery = Lottery.objects.get(id=lottery_id)
                    
                    prize = Prize(
                        lottery=lottery,
                        name=prize_data['name'],
                        description=prize_data['description'],
                        quantity=prize_data['quantity'],
                        order=prize_data['order']
                    )
                    prize.save()
                    return prize
                
                prize = await create_prize(lottery_id, lottery_data['prizes'][index])
                logger.info(f"[抽奖设置] 成功创建奖品: {prize}")
                
                # 询问是否继续添加奖项
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ 继续添加奖项", callback_data=f"add_more_prize_{lottery_id}")],
                    [InlineKeyboardButton("✅ 完成奖品设置", callback_data=f"finish_prize_setup_{lottery_id}")]
                ])
                
                await message.reply_text(
                    f"✅ 已添加奖项: {lottery_data['prizes'][index]['name']}\n\n"
                    f"您可以继续添加更多奖项，或完成设置。",
                    reply_markup=keyboard
                )
                
                return PRIZE_SETUP
                
            except Exception as e:
                logger.error(f"[抽奖设置] 创建奖品时出错: {e}\n{traceback.format_exc()}")
                raise
        
    except Exception as e:
        error_message = f"处理中奖人数时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def add_more_prize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择继续添加奖项"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[3])
        logger.info(f"[抽奖设置] 用户 {user.id} 选择为抽奖ID={lottery_id}继续添加奖项")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 更新当前奖项索引
        current_index = context.user_data.get('current_prize_index', 0) + 1
        context.user_data['current_prize_index'] = current_index
        
        await query.edit_message_text(
            f"请输入第{current_index + 1}个奖项的名称：\n\n"
            "例如：二等奖、三等奖等"
        )
        
        # 设置用户状态为等待输入奖项名称
        context.user_data['waiting_for_prize_name'] = True
        
        return PRIZE_NAME
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理继续添加奖项时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def finish_prize_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户完成奖品设置"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[3])
        logger.info(f"[抽奖设置] 用户 {user.id} 完成抽奖ID={lottery_id}的奖品设置")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 获取所有已设置的奖品
        @sync_to_async
        def get_prizes(lottery_id):
            from .models import Lottery, Prize
            lottery = Lottery.objects.get(id=lottery_id)
            return list(Prize.objects.filter(lottery=lottery).order_by('order'))
            
        prizes = await get_prizes(lottery_id)
        
        # 构建奖品列表文本
        prizes_text = ""
        for prize in prizes:
            prizes_text += f"• {prize.name}: {prize.description} ({prize.quantity}名)\n"
        
        # 设置参与积分
        await query.edit_message_text(
            f"💰 设置参与积分\n\n"
            f"请设置用户参与此次抽奖需要消耗的积分数量：\n"
            f"(设置为0表示不需要积分即可参与)"
        )
        
        # 设置用户状态为等待输入积分
        context.user_data['waiting_for_points_required'] = True
        context.user_data['current_lottery_id'] = lottery_id
        
        return POINTS_REQUIRED
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理完成奖品设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def set_signup_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择报名截止时间"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取天数和抽奖ID
        data_parts = query.data.split("_")
        option = data_parts[2]
        lottery_id = int(data_parts[3])
        
        logger.info(f"[抽奖设置] 用户 {user.id} 选择了报名截止时间选项: {option}, 抽奖ID={lottery_id}")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 如果用户选择自定义时间
        if option == "custom":
            await query.edit_message_text(
                "请输入自定义报名截止时间 (格式: YYYY-MM-DD HH:MM)\n\n"
                "例如: 2024-06-30 18:00"
            )
            context.user_data['waiting_for_custom_deadline'] = True
            return CUSTOM_DEADLINE
        
        # 计算截止时间 - 使用北京时间 (UTC+8)
        days = int(option)
        beijing_tz = dt_timezone(timedelta(hours=8))
        # 获取北京时间但是无时区信息
        now = datetime.now(beijing_tz)
        if timezone.is_aware(now):
            now = timezone.make_naive(now, beijing_tz)
        
        deadline = now + timedelta(days=days)
        
        # 保存截止时间到上下文
        lottery_data['signup_deadline'] = deadline
        logger.info(f"[抽奖设置] 已设置报名截止时间: {deadline}")
        
        # 提供开奖时间选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("报名结束后立即开奖", callback_data=f"draw_time_auto_{lottery_id}")],
            [InlineKeyboardButton("自定义开奖时间", callback_data=f"draw_time_custom_{lottery_id}")]
        ])
        
        await query.edit_message_text(
            "请选择开奖时间：",
            reply_markup=keyboard
        )
        
        return DRAW_TIME
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理报名截止时间选择时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def custom_deadline_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户输入的自定义报名截止时间"""
    message = update.message
    deadline_text = message.text
    user = update.effective_user
    
    if not context.user_data.get('waiting_for_custom_deadline'):
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_custom_deadline', None)
    
    try:
        # 解析用户输入的时间
        try:
            # 直接解析为naive datetime（无时区信息）
            naive_deadline = datetime.strptime(deadline_text, "%Y-%m-%d %H:%M")
            
            # 验证时间是否在未来
            beijing_tz = dt_timezone(timedelta(hours=8))
            now = datetime.now(beijing_tz)
            if timezone.is_aware(now):
                now = timezone.make_naive(now, beijing_tz)
                
            if naive_deadline <= now:
                await message.reply_text(
                    "报名截止时间必须在未来。请重新输入 (格式: YYYY-MM-DD HH:MM)："
                )
                context.user_data['waiting_for_custom_deadline'] = True
                return CUSTOM_DEADLINE
                
        except ValueError:
            await message.reply_text(
                "时间格式不正确。请使用格式: YYYY-MM-DD HH:MM\n"
                "例如: 2024-06-30 18:00"
            )
            context.user_data['waiting_for_custom_deadline'] = True
            return CUSTOM_DEADLINE
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning("[抽奖设置] lottery_setup 或 current_lottery_id 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        lottery_id = lottery_data['current_lottery_id']
        
        # 保存截止时间到上下文 - 使用不带时区的datetime
        lottery_data['signup_deadline'] = naive_deadline
        logger.info(f"[抽奖设置] 已设置自定义报名截止时间: {naive_deadline}")
        
        # 提供开奖时间选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("报名结束后立即开奖", callback_data=f"draw_time_auto_{lottery_id}")],
            [InlineKeyboardButton("自定义开奖时间", callback_data=f"draw_time_custom_{lottery_id}")]
        ])
        
        await message.reply_text(
            "请选择开奖时间：",
            reply_markup=keyboard
        )
        
        return DRAW_TIME
        
    except Exception as e:
        error_message = f"处理自定义报名截止时间时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def set_draw_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择开奖时间"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取选项和抽奖ID
        data_parts = query.data.split("_")
        option = data_parts[2]
        lottery_id = int(data_parts[3])
        
        logger.info(f"[抽奖设置] 用户 {user.id} 选择了开奖时间选项: {option}, 抽奖ID={lottery_id}")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 如果用户选择自定义时间
        if option == "custom":
            await query.edit_message_text(
                "请输入自定义开奖时间 (格式: YYYY-MM-DD HH:MM)\n\n"
                "例如: 2024-06-30 18:00"
            )
            context.user_data['waiting_for_custom_draw_time'] = True
            return CUSTOM_DRAW_TIME
        
        # 自动开奖（与报名截止时间相同）
        draw_time = lottery_data.get('signup_deadline')
        lottery_data['draw_time'] = draw_time
        lottery_data['auto_draw'] = True
        
        # 添加通知设置选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("是", callback_data=f"notify_private_yes_{lottery_id}")],
            [InlineKeyboardButton("否", callback_data=f"notify_private_no_{lottery_id}")]
        ])
        
        await query.edit_message_text(
            "🔔 设置通知方式\n\n"
            "开奖后是否通过私聊通知中奖者？",
            reply_markup=keyboard
        )
        
        return NOTIFY_PRIVATE
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理开奖时间选择时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def custom_draw_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户输入的自定义开奖时间"""
    message = update.message
    draw_time_text = message.text
    user = update.effective_user
    
    if not context.user_data.get('waiting_for_custom_draw_time'):
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_custom_draw_time', None)
    
    try:
        # 解析用户输入的时间
        try:
            # 直接解析为naive datetime（无时区信息）
            naive_draw_time = datetime.strptime(draw_time_text, "%Y-%m-%d %H:%M")
            
            # 验证开奖时间是否在报名截止时间之后
            lottery_data = context.user_data.get('lottery_setup')
            signup_deadline = lottery_data.get('signup_deadline')
            
            # 确保都是naive datetime（无时区）
            beijing_tz = dt_timezone(timedelta(hours=8))
            if timezone.is_aware(signup_deadline):
                signup_deadline = timezone.make_naive(signup_deadline, beijing_tz)
                
            if naive_draw_time < signup_deadline:
                await message.reply_text(
                    "开奖时间必须晚于报名截止时间。请重新输入 (格式: YYYY-MM-DD HH:MM)："
                )
                context.user_data['waiting_for_custom_draw_time'] = True
                return CUSTOM_DRAW_TIME
                
        except ValueError:
            await message.reply_text(
                "时间格式不正确。请使用格式: YYYY-MM-DD HH:MM\n"
                "例如: 2024-06-30 18:00"
            )
            context.user_data['waiting_for_custom_draw_time'] = True
            return CUSTOM_DRAW_TIME
        
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning("[抽奖设置] lottery_setup 或 current_lottery_id 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        lottery_id = lottery_data['current_lottery_id']
        
        # 保存开奖时间到上下文 - 使用不带时区的datetime
        lottery_data['draw_time'] = naive_draw_time
        lottery_data['auto_draw'] = False  # 自定义时间，不是自动开奖
        
        # 添加通知设置选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("是", callback_data=f"notify_private_yes_{lottery_id}")],
            [InlineKeyboardButton("否", callback_data=f"notify_private_no_{lottery_id}")]
        ])
        
        await message.reply_text(
            "🔔 设置通知方式\n\n"
            "开奖后是否通过私聊通知中奖者？",
            reply_markup=keyboard
        )
        
        return NOTIFY_PRIVATE
        
    except Exception as e:
        error_message = f"处理自定义开奖时间时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def set_notify_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户是否通过私聊通知中奖者的选择"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取选项和抽奖ID
        data_parts = query.data.split("_")
        option = data_parts[2]  # yes 或 no
        lottery_id = int(data_parts[3])
        
        logger.info(f"[抽奖设置] 用户 {user.id} 选择了私聊通知中奖者选项: {option}, 抽奖ID={lottery_id}")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 保存选择到上下文
        lottery_data['notify_winners_privately'] = (option == 'yes')
        
        # 显示下一个设置选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("是", callback_data=f"announce_group_yes_{lottery_id}")],
            [InlineKeyboardButton("否", callback_data=f"announce_group_no_{lottery_id}")]
        ])
        
        await query.edit_message_text(
            "开奖结果是否公布在群组内？",
            reply_markup=keyboard
        )
        
        return ANNOUNCE_GROUP
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理私聊通知设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def set_announce_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户是否在群组内公布结果的选择"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取选项和抽奖ID
        data_parts = query.data.split("_")
        option = data_parts[2]  # yes 或 no
        lottery_id = int(data_parts[3])
        
        logger.info(f"[抽奖设置] 用户 {user.id} 选择了群组内公布结果选项: {option}, 抽奖ID={lottery_id}")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 保存选择到上下文
        lottery_data['announce_results_in_group'] = (option == 'yes')
        
        # 显示下一个设置选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("是", callback_data=f"pin_results_yes_{lottery_id}")],
            [InlineKeyboardButton("否", callback_data=f"pin_results_no_{lottery_id}")]
        ])
        
        await query.edit_message_text(
            "开奖结果是否置顶在群组内？",
            reply_markup=keyboard
        )
        
        return PIN_RESULTS
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理群组公布结果设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def set_pin_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户是否将结果置顶在群组内的选择"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取选项和抽奖ID
        data_parts = query.data.split("_")
        option = data_parts[2]  # yes 或 no
        lottery_id = int(data_parts[3])
        
        logger.info(f"[抽奖设置] 用户 {user.id} 选择了结果置顶选项: {option}, 抽奖ID={lottery_id}")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 保存选择到上下文
        lottery_data['pin_results'] = (option == 'yes')
        
        # 更新数据库中的抽奖活动
        try:
            @sync_to_async
            def update_lottery_settings(lottery_id, data):
                from .models import Lottery
                lottery = Lottery.objects.get(id=lottery_id)
                
                # 时间设置
                beijing_tz = dt_timezone(timedelta(hours=8))
                
                # 处理signup_deadline
                signup_deadline = data.get('signup_deadline')
                if timezone.is_aware(signup_deadline):
                    lottery.signup_deadline = timezone.make_naive(signup_deadline, beijing_tz)
                else:
                    lottery.signup_deadline = signup_deadline
                
                # 处理draw_time
                draw_time = data.get('draw_time')
                if timezone.is_aware(draw_time):
                    lottery.draw_time = timezone.make_naive(draw_time, beijing_tz)
                else:
                    lottery.draw_time = draw_time
                
                # 积分要求
                lottery.points_required = data.get('points_required', 0)
                
                # 其他设置
                lottery.auto_draw = data.get('auto_draw', True)
                lottery.notify_winners_privately = data.get('notify_winners_privately', True)
                lottery.announce_results_in_group = data.get('announce_results_in_group', True)
                lottery.pin_results = data.get('pin_results', False)
                lottery.status = 'ACTIVE'  # 设置为进行中状态
                
                lottery.save()
                return lottery
            
            lottery = await update_lottery_settings(
                lottery_id, 
                {
                    'signup_deadline': lottery_data['signup_deadline'],
                    'draw_time': lottery_data['draw_time'],
                    'auto_draw': lottery_data.get('auto_draw', True),
                    'notify_winners_privately': lottery_data.get('notify_winners_privately', True),
                    'announce_results_in_group': lottery_data.get('announce_results_in_group', True),
                    'pin_results': lottery_data.get('pin_results', False),
                    'points_required': lottery_data.get('points_required', 0)
                }
            )
            
            logger.info(f"[抽奖设置] 已更新抽奖设置: ID={lottery_id}")
            
            # 格式化日期时间显示 (北京时间)
            beijing_time_format = "%Y-%m-%d %H:%M"
            beijing_tz = dt_timezone(timedelta(hours=8))
            
            # 确保用于格式化的时间对象是naive的
            signup_deadline = lottery_data['signup_deadline']
            draw_time_obj = lottery_data['draw_time']
            
            # 去除时区信息（如果有）
            if timezone.is_aware(signup_deadline):
                signup_deadline = timezone.make_naive(signup_deadline, beijing_tz)
            if timezone.is_aware(draw_time_obj):
                draw_time_obj = timezone.make_naive(draw_time_obj, beijing_tz)
            
            signup_deadline_str = signup_deadline.strftime(beijing_time_format)
            draw_time_str = draw_time_obj.strftime(beijing_time_format)
            
            # 获取奖品信息
            @sync_to_async
            def get_prizes(lottery_id):
                from .models import Lottery, Prize
                lottery = Lottery.objects.get(id=lottery_id)
                return list(Prize.objects.filter(lottery=lottery).order_by('order'))
            
            prizes = await get_prizes(lottery_id)
            
            # 单奖项模式，增强显示效果
            if 'single_prize_mode' in lottery_data and lottery_data['single_prize_mode']:
                prizes_text = f"• <b>{lottery_data['prize_name']}:</b> {lottery_data['prize_desc']} ({lottery_data['prize_count']}名)\n"
            else:
                # 多奖项模式，增强显示效果
                prizes_text = ""
                for prize in prizes:
                    prizes_text += f"• <b>{prize.name}:</b> {prize.description} ({prize.quantity}名)\n"
            
            # 简化通知设置，不显示在预览信息中
            # notify_text部分不再使用
            
            # 获取参与条件
            @sync_to_async
            def get_requirements(lottery_id):
                from .models import Lottery, LotteryRequirement
                lottery = Lottery.objects.get(id=lottery_id)
                return list(LotteryRequirement.objects.filter(lottery=lottery))
            
            requirements = await get_requirements(lottery_id)
            
            # 简化参与条件文本，但使用更醒目的格式
            requirements_text = ""
            if requirements:
                for req in requirements:
                    if req.requirement_type == 'CHANNEL':
                        requirements_text += f"• 必须关注: @{req.channel_username}\n"
                    elif req.requirement_type == 'GROUP':
                        requirements_text += f"• 必须加入: @{req.group_username}\n"
                    elif req.requirement_type == 'REGISTRATION_TIME':
                        requirements_text += f"• 账号注册时间: >{req.min_registration_days}天\n"
            else:
                requirements_text = "无限制\n"
            
            # 获取抽奖描述
            description = lottery_data.get('description') or lottery_data.get('lottery').description or ""
            
            # 构建预览信息，加入清晰的标题和格式化，但保持简洁
            preview_message = (
                f"🎁 <b>抽奖活动</b> 🎁\n\n"
                f"<b>{lottery_data['lottery'].title}</b>\n"
                f"{description}\n\n"
                f"<b>📋 参与条件:</b>\n{requirements_text}\n"
                f"<b>💰 参与所需积分:</b> {lottery_data.get('points_required', 0)}\n"
                f"<b>🏆 奖项设置:</b>\n{prizes_text}\n"
                f"<b>⏱ 报名截止:</b> {signup_deadline_str}\n"
                f"<b>🎯 开奖时间:</b> {draw_time_str}\n"
            )
            
            # 添加确认发布按钮
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ 确认发布", callback_data=f"publish_lottery_{lottery_id}")],
                [InlineKeyboardButton("返回群组设置", callback_data=f"group_{lottery_data['group_id']}")]
            ])
            
            # 保存预览信息到上下文，供确认发布时使用
            lottery_data['preview_message'] = preview_message
            
            await query.edit_message_text(
                preview_message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"[抽奖设置] 更新抽奖设置时出错: {e}\n{traceback.format_exc()}")
            raise
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理结果置顶设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def publish_lottery_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户确认发布抽奖活动到群组"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取抽奖ID
        lottery_id = int(query.data.split("_")[2])
        logger.info(f"[抽奖发布] 用户 {user.id} 确认发布抽奖ID={lottery_id}到群组")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖发布] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return
        
        group_id = lottery_data.get('group_id')
        if not group_id:
            logger.warning("[抽奖发布] 群组ID不存在")
            await query.message.reply_text("无法确定要发布到的群组，请重新设置抽奖。")
            return
        
        # 获取抽奖活动信息
        @sync_to_async
        def get_lottery(lottery_id):
            from .models import Lottery
            return Lottery.objects.get(id=lottery_id)
            
        lottery = await get_lottery(lottery_id)
        
        # 发送抽奖信息到群组
        try:
            # 使用存储在上下文中的预览消息
            preview_message = lottery_data.get('preview_message')
            if not preview_message:
                logger.warning("[抽奖发布] 预览消息不存在")
                await query.message.reply_text("预览信息丢失，无法发布，请重新设置抽奖。")
                return
            
            # 添加参与按钮
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 参与抽奖", callback_data=f"join_lottery_{lottery_id}")]
            ])
            
            # 根据媒体类型选择发送方式
            media_type = lottery.media_type
            media_file_id = lottery.media_file_id
            
            sent_message = None
            
            # 创建更明确但仍然简洁的群组发布版本
            group_message = preview_message + "\n<b>👇 点击下方按钮参与抽奖 👇</b>"
            
            # 修改获取预览信息的方式，不再添加标识符
            if media_type == 'PHOTO' and media_file_id:
                logger.info(f"[抽奖发布] 发送带图片的抽奖信息，file_id={media_file_id}")
                # 使用更小的缩略图预览
                sent_message = await context.bot.send_photo(
                    chat_id=group_id,
                    photo=media_file_id,
                    caption=group_message,
                    reply_markup=keyboard,
                    parse_mode='HTML'
                )
            elif media_type == 'VIDEO' and media_file_id:
                logger.info(f"[抽奖发布] 发送带视频的抽奖信息，file_id={media_file_id}")
                sent_message = await context.bot.send_video(
                    chat_id=group_id,
                    video=media_file_id,
                    caption=group_message,
                    reply_markup=keyboard,
                    parse_mode='HTML',
                    supports_streaming=True  # 使视频支持流式播放，可以提高加载速度
                )
            else:
                logger.info("[抽奖发布] 发送纯文本抽奖信息")
                sent_message = await context.bot.send_message(
                    chat_id=group_id,
                    text=group_message,
                    reply_markup=keyboard,
                    parse_mode='HTML'
                )
            
            # 更新抽奖记录，保存消息ID
            @sync_to_async
            def update_lottery_message_id(lottery_id, message_id):
                from .models import Lottery
                lottery = Lottery.objects.get(id=lottery_id)
                lottery.message_id = message_id
                lottery.save()
                return lottery
                
            await update_lottery_message_id(lottery_id, sent_message.message_id)
            
            # 通知用户发布成功
            await query.edit_message_text(
                f"✅ 抽奖活动已成功发布到群组！\n"
                f"您可以在群组中查看抽奖信息并管理参与者。",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回群组设置", callback_data=f"group_{group_id}")]
                ])
            )
            
            logger.info(f"[抽奖发布] 成功发布抽奖ID={lottery_id}到群组ID={group_id}, 消息ID={sent_message.message_id}")
            
            # 清理上下文数据
            del context.user_data['lottery_setup']
            logger.info("[抽奖发布] 已清理上下文数据")
            
        except Exception as e:
            logger.error(f"[抽奖发布] 发送抽奖信息到群组时出错: {e}\n{traceback.format_exc()}")
            await query.message.reply_text(f"发布抽奖活动时出错: {str(e)}")
            
    except Exception as e:
        logger.error(f"[抽奖发布] 处理确认发布时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")

async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择添加图片"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[2])
        logger.info(f"[抽奖设置] 用户 {user.id} 选择为抽奖ID={lottery_id}添加图片")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 更新lottery_id和媒体类型
        lottery_data['current_lottery_id'] = lottery_id
        lottery_data['media_type'] = 'PHOTO'
        
        # 强化设置等待上传图片状态
        context.user_data['waiting_for_photo'] = True
        logger.info(f"[抽奖设置] 已设置用户 {user.id} 的等待上传图片状态")
        
        await query.edit_message_text(
            "请发送抽奖活动的图片：\n\n"
            "图片将显示在抽奖信息的最前面，建议使用清晰的奖品图片或精美的活动海报。\n"
            "发送后请稍等，图片上传需要一点时间处理。"
        )
        
        return MEDIA_UPLOAD
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理添加图片时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def add_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择添加视频"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[2])
        logger.info(f"[抽奖设置] 用户 {user.id} 选择为抽奖ID={lottery_id}添加视频")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 更新lottery_id和媒体类型
        lottery_data['current_lottery_id'] = lottery_id
        lottery_data['media_type'] = 'VIDEO'
        
        # 强化设置等待上传视频状态
        context.user_data['waiting_for_video'] = True
        logger.info(f"[抽奖设置] 已设置用户 {user.id} 的等待上传视频状态")
        
        await query.edit_message_text(
            "请发送抽奖活动的视频：\n\n"
            "视频将显示在抽奖信息的最前面，建议使用简短的奖品展示视频或活动介绍视频。\n"
            "视频大小不应超过50MB，时长建议在30秒以内。\n"
            "发送后请稍等，视频上传需要一点时间处理。"
        )
        
        return MEDIA_UPLOAD
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理添加视频时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def skip_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户跳过媒体上传"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        lottery_id = int(query.data.split("_")[2])
        logger.info(f"[抽奖设置] 用户 {user.id} 跳过为抽奖ID={lottery_id}添加媒体")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 设置媒体类型为无
        lottery_data['media_type'] = 'NONE'
        
        # 更新数据库中的抽奖活动
        @sync_to_async
        def update_lottery_media(lottery_id, media_type):
            from .models import Lottery
            lottery = Lottery.objects.get(id=lottery_id)
            lottery.media_type = media_type
            lottery.media_file_id = None
            lottery.save()
            return lottery
            
        await update_lottery_media(lottery_id, 'NONE')
        
        # 显示报名截止时间选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1天后", callback_data=f"signup_deadline_1_{lottery_id}")],
            [InlineKeyboardButton("3天后", callback_data=f"signup_deadline_3_{lottery_id}")],
            [InlineKeyboardButton("7天后", callback_data=f"signup_deadline_7_{lottery_id}")],
            [InlineKeyboardButton("自定义", callback_data=f"signup_deadline_custom_{lottery_id}")]
        ])
        
        await query.edit_message_text(
            "⏱️ 设置时间参数\n\n"
            "请选择报名截止时间：",
            reply_markup=keyboard
        )
        
        return SIGNUP_DEADLINE
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理跳过媒体上传时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def photo_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户上传的图片"""
    message = update.message
    photo = message.photo[-1]  # 获取最大分辨率的图片
    user = update.effective_user
    
    logger.info(f"[抽奖设置] photo_upload_handler被调用，用户ID={user.id}，检查等待状态")
    
    # 如果不是在等待图片上传状态，则忽略
    if not context.user_data.get('waiting_for_photo'):
        logger.warning(f"[抽奖设置] 收到图片但不在等待图片状态，忽略处理。用户数据：{context.user_data}")
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_photo', None)
    logger.info(f"[抽奖设置] 已清除用户{user.id}的waiting_for_photo状态")
    
    try:
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning(f"[抽奖设置] lottery_setup或current_lottery_id数据不存在。用户数据：{context.user_data}")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        lottery_id = lottery_data['current_lottery_id']
        logger.info(f"[抽奖设置] 获取到抽奖ID={lottery_id}，准备处理图片上传")
        
        # 保存图片信息
        file_id = photo.file_id
        lottery_data['media_file_id'] = file_id
        
        # 更新数据库中的抽奖活动
        @sync_to_async
        def update_lottery_photo(lottery_id, file_id):
            from .models import Lottery
            try:
                lottery = Lottery.objects.get(id=lottery_id)
                lottery.media_type = 'PHOTO'
                lottery.media_file_id = file_id
                lottery.save()
                logger.info(f"[抽奖设置] 成功更新lottery对象，ID={lottery_id}，media_type=PHOTO，file_id={file_id}")
                return lottery
            except Exception as e:
                logger.error(f"[抽奖设置] 更新lottery对象时出错: {e}")
                raise
            
        await update_lottery_photo(lottery_id, file_id)
        
        logger.info(f"[抽奖设置] 用户 {user.id} 上传了图片，file_id={file_id}")
        
        # 设置报名截止时间选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1天后", callback_data=f"signup_deadline_1_{lottery_id}")],
            [InlineKeyboardButton("3天后", callback_data=f"signup_deadline_3_{lottery_id}")],
            [InlineKeyboardButton("7天后", callback_data=f"signup_deadline_7_{lottery_id}")],
            [InlineKeyboardButton("自定义", callback_data=f"signup_deadline_custom_{lottery_id}")]
        ])
        
        await message.reply_text(
            "✅ 图片已成功上传！\n\n"
            "⏱️ 设置时间参数\n\n"
            "请选择报名截止时间：",
            reply_markup=keyboard
        )
        
        logger.info(f"[抽奖设置] 已向用户{user.id}发送报名截止时间选项")
        return SIGNUP_DEADLINE
        
    except Exception as e:
        error_message = f"处理图片上传时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def video_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户上传的视频"""
    message = update.message
    video = message.video
    user = update.effective_user
    
    logger.info(f"[抽奖设置] video_upload_handler被调用，用户ID={user.id}，检查等待状态")
    
    # 如果不是在等待视频上传状态，则忽略
    if not context.user_data.get('waiting_for_video'):
        logger.warning(f"[抽奖设置] 收到视频但不在等待视频状态，忽略处理。用户数据：{context.user_data}")
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_video', None)
    logger.info(f"[抽奖设置] 已清除用户{user.id}的waiting_for_video状态")
    
    try:
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning(f"[抽奖设置] lottery_setup或current_lottery_id数据不存在。用户数据：{context.user_data}")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        lottery_id = lottery_data['current_lottery_id']
        logger.info(f"[抽奖设置] 获取到抽奖ID={lottery_id}，准备处理视频上传")
        
        # 保存视频信息
        file_id = video.file_id
        lottery_data['media_file_id'] = file_id
        
        # 更新数据库中的抽奖活动
        @sync_to_async
        def update_lottery_video(lottery_id, file_id):
            from .models import Lottery
            try:
                lottery = Lottery.objects.get(id=lottery_id)
                lottery.media_type = 'VIDEO'
                lottery.media_file_id = file_id
                lottery.save()
                logger.info(f"[抽奖设置] 成功更新lottery对象，ID={lottery_id}，media_type=VIDEO，file_id={file_id}")
                return lottery
            except Exception as e:
                logger.error(f"[抽奖设置] 更新lottery对象时出错: {e}")
                raise
            
        await update_lottery_video(lottery_id, file_id)
        
        logger.info(f"[抽奖设置] 用户 {user.id} 上传了视频，file_id={file_id}, 大小={video.file_size}字节")
        
        # 设置报名截止时间选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1天后", callback_data=f"signup_deadline_1_{lottery_id}")],
            [InlineKeyboardButton("3天后", callback_data=f"signup_deadline_3_{lottery_id}")],
            [InlineKeyboardButton("7天后", callback_data=f"signup_deadline_7_{lottery_id}")],
            [InlineKeyboardButton("自定义", callback_data=f"signup_deadline_custom_{lottery_id}")]
        ])
        
        await message.reply_text(
            "✅ 视频已成功上传！\n\n"
            "⏱️ 设置时间参数\n\n"
            "请选择报名截止时间：",
            reply_markup=keyboard
        )
        
        logger.info(f"[抽奖设置] 已向用户{user.id}发送报名截止时间选项")
        return SIGNUP_DEADLINE
        
    except Exception as e:
        error_message = f"处理视频上传时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def points_required_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户输入的参与抽奖扣除积分"""
    message = update.message
    points_text = message.text
    user = update.effective_user
    
    if not context.user_data.get('waiting_for_points_required'):
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_for_points_required', None)
    
    try:
        # 验证积分输入是否为非负整数
        try:
            points = int(points_text)
            if points < 0:
                raise ValueError("积分不能为负数")
        except ValueError:
            await message.reply_text(
                "请输入有效的非负整数作为积分。\n"
                "例如：0、10、100等"
            )
            context.user_data['waiting_for_points_required'] = True
            return POINTS_REQUIRED
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data or 'current_lottery_id' not in lottery_data:
            logger.warning("[抽奖设置] lottery_setup 或 current_lottery_id 数据不存在")
            await message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        lottery_id = lottery_data['current_lottery_id']
        
        # 保存积分设置到上下文
        lottery_data['points_required'] = points
        logger.info(f"[抽奖设置] 用户 {user.id} 设置了参与抽奖扣除积分: {points}")
        
        # 构造回调数据
        confirm_callback = f"confirm_points_{lottery_id}"
        edit_callback = f"edit_points_{lottery_id}"
        logger.info(f"[抽奖设置] 创建按钮回调数据: 确认={confirm_callback}, 修改={edit_callback}")
        
        # 提供确认和修改选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("确认并继续", callback_data=confirm_callback)],
            [InlineKeyboardButton("修改积分设置", callback_data=edit_callback)]
        ])
        
        await message.reply_text(
            f"您已设置参与本次抽奖需要消耗{points}积分。\n\n"
            f"用户参与抽奖时将扣除相应积分，未中奖用户的积分不予退还。",
            reply_markup=keyboard
        )
        
        return POINTS_REQUIRED
        
    except Exception as e:
        error_message = f"设置参与积分时出错：{str(e)}"
        logger.error(f"[抽奖设置] {error_message}\n{traceback.format_exc()}")
        await message.reply_text(error_message)
        return ConversationHandler.END

async def confirm_points_required(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户确认积分设置并继续"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取抽奖ID
        callback_data = query.data  # 格式: confirm_points_{lottery_id}
        lottery_id = int(callback_data.split("_")[2])
        logger.info(f"[抽奖设置] 用户 {user.id} 确认了参与抽奖扣除积分设置，抽奖ID={lottery_id}, 回调数据={callback_data}")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 保存积分设置到抽奖记录
        @sync_to_async
        def update_lottery_points(lottery_id, points):
            from .models import Lottery
            lottery = Lottery.objects.get(id=lottery_id)
            lottery.points_required = points
            lottery.save()
            return lottery
            
        points = lottery_data.get('points_required', 0)
        lottery = await update_lottery_points(lottery_id, points)
        logger.info(f"[抽奖设置] 成功更新抽奖ID={lottery_id}的积分要求: {points}")
        
        # 设置媒体上传选项
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("添加图片", callback_data=f"add_photo_{lottery_id}")],
            [InlineKeyboardButton("添加视频", callback_data=f"add_video_{lottery_id}")],
            [InlineKeyboardButton("跳过媒体上传", callback_data=f"skip_media_{lottery_id}")]
        ])
        
        await query.edit_message_text(
            f"✅ 已完成奖品和积分设置\n\n"
            f"参与所需积分: {points}\n\n"
            f"是否要添加抽奖活动的图片或视频？\n"
            f"添加图片或视频可以使抽奖活动更加吸引人。",
            reply_markup=keyboard
        )
        
        return MEDIA_UPLOAD
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理确认积分设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def edit_points_required(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理用户选择修改积分设置"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 记录完整的回调数据
        callback_data = query.data
        lottery_id = int(callback_data.split("_")[2])
        logger.info(f"[抽奖设置] 用户 {user.id} 选择修改参与抽奖扣除积分设置，抽奖ID={lottery_id}, 回调数据={callback_data}")
        
        lottery_data = context.user_data.get('lottery_setup')
        if not lottery_data:
            logger.warning("[抽奖设置] lottery_setup 数据不存在")
            await query.message.reply_text("设置已过期，请重新开始设置抽奖。")
            return ConversationHandler.END
        
        # 更新当前抽奖ID
        lottery_data['current_lottery_id'] = lottery_id
        
        await query.edit_message_text(
            f"💰 设置参与积分\n\n"
            f"请重新设置用户参与此次抽奖需要消耗的积分数量：\n"
            f"(设置为0表示不需要积分即可参与)"
        )
        
        # 设置用户状态为等待输入积分
        context.user_data['waiting_for_points_required'] = True
        
        return POINTS_REQUIRED
        
    except Exception as e:
        logger.error(f"[抽奖设置] 处理修改积分设置时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")
        return ConversationHandler.END

async def join_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户点击参与抽奖的回调"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取抽奖ID
        lottery_id = int(query.data.split("_")[2])
        logger.info(f"[抽奖参与] 用户 {user.id} 尝试参与抽奖ID={lottery_id}")
        
        # 获取抽奖信息
        @sync_to_async
        def get_lottery_and_check_status(lottery_id):
            from .models import Lottery
            try:
                lottery = Lottery.objects.get(id=lottery_id)
                return lottery, lottery.status == 'ACTIVE' and lottery.can_join
            except Lottery.DoesNotExist:
                return None, False
                
        lottery, is_active = await get_lottery_and_check_status(lottery_id)
        
        if not lottery:
            logger.warning(f"[抽奖参与] 抽奖ID={lottery_id}不存在")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("❌ 该抽奖活动不存在或已被删除。")
            return
            
        if not is_active:
            logger.warning(f"[抽奖参与] 抽奖ID={lottery_id}已结束或不可参与")
            await query.message.reply_text("❌ 该抽奖活动已结束或不在可参与时间内。")
            return
            
        # 检查用户是否已参与
        @sync_to_async
        def check_user_participation(lottery_id, user_id):
            from .models import Lottery, Participant
            from jifen.models import User, Group
            
            try:
                lottery = Lottery.objects.get(id=lottery_id)
                group = lottery.group
                
                # 获取用户在该群组的记录
                user = User.objects.get(telegram_id=user_id, group=group)
                
                # 检查是否已参与
                has_joined = Participant.objects.filter(lottery=lottery, user=user).exists()
                
                # 获取用户积分
                user_points = user.points
                
                # 获取抽奖所需积分
                points_required = lottery.points_required
                
                return user, has_joined, user_points, points_required, group
            except (Lottery.DoesNotExist, User.DoesNotExist):
                return None, False, 0, 0, None
                
        user_obj, has_joined, user_points, points_required, group = await check_user_participation(lottery_id, user.id)
        
        if not user_obj:
            logger.warning(f"[抽奖参与] 用户 {user.id} 不在群组中或抽奖不存在")
            await query.message.reply_text("❌ 您不是该群组的成员，无法参与抽奖。")
            return
            
        if has_joined:
            logger.info(f"[抽奖参与] 用户 {user.id} 已经参与了抽奖ID={lottery_id}")
            await query.message.reply_text("您已经参与了该抽奖活动，请勿重复参与。")
            return
            
        # 检查用户积分是否足够
        if user_points < points_required:
            logger.info(f"[抽奖参与] 用户 {user.id} 积分不足，当前积分={user_points}，需要积分={points_required}")
            message = await query.message.reply_text(
                f"❌ 您的积分不足，无法参与抽奖。\n"
                f"当前积分: {user_points}\n"
                f"所需积分: {points_required}\n"
                f"还差 {points_required - user_points} 积分"
            )
            
            # 设置10秒后自动删除消息
            async def delete_message_later():
                await asyncio.sleep(10)  # 等待10秒
                try:
                    await message.delete()
                    logger.info(f"[抽奖参与] 已自动删除用户 {user.id} 的积分不足提醒消息")
                except Exception as e:
                    logger.error(f"[抽奖参与] 自动删除积分不足提醒消息失败: {e}")
            
            # 创建异步任务，不等待它完成
            context.application.create_task(delete_message_later())
            return
            
        # 用户满足条件，可以参与抽奖
        @sync_to_async
        def join_raffle(lottery_id, user_obj, points_required):
            from .models import Lottery, Participant
            from jifen.models import PointTransaction
            from django.utils import timezone
            import datetime
            
            lottery = Lottery.objects.get(id=lottery_id)
            
            # 创建参与记录
            participant = Participant(
                lottery=lottery,
                user=user_obj,
                joined_at=timezone.now()
            )
            participant.save()
            
            # 如果需要扣除积分
            if points_required > 0:
                # 扣除用户积分
                user_obj.points -= points_required
                user_obj.save()
                
                # 记录积分变动
                transaction = PointTransaction(
                    user=user_obj,
                    group=user_obj.group,
                    amount=-points_required,
                    type='RAFFLE_PARTICIPATION',
                    description=f"参与抽奖 '{lottery.title}'",
                    transaction_date=datetime.date.today()
                )
                transaction.save()
                
            return True
            
        success = await join_raffle(lottery_id, user_obj, points_required)
        
        if success:
            if points_required > 0:
                await query.message.reply_text(
                    f"✅ 您已成功参与抽奖活动！\n"
                    f"已扣除 {points_required} 积分\n"
                    f"剩余积分: {user_points - points_required}\n"
                    f"请等待开奖结果。"
                )
            else:
                await query.message.reply_text(
                    f"✅ 您已成功参与抽奖活动！\n"
                    f"无需扣除积分\n"
                    f"请等待开奖结果。"
                )
                
            logger.info(f"[抽奖参与] 用户 {user.id} 成功参与抽奖ID={lottery_id}，扣除积分={points_required}")
        else:
            await query.message.reply_text("参与抽奖时出错，请重试。")
            logger.error(f"[抽奖参与] 用户 {user.id} 参与抽奖ID={lottery_id}失败")
            
    except Exception as e:
        logger.error(f"[抽奖参与] 处理参与抽奖时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("参与抽奖时出错，请重试。")

# 创建抽奖设置对话处理器
lottery_setup_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_lottery_setup, pattern="^raffle_setting_-?\d+$")
    ],
    states={
        TITLE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, title_input),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        DESCRIPTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, description_input),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        REQUIREMENT: [
            CallbackQueryHandler(requirement_channel_input, pattern="^req_channel_\d+$"),
            CallbackQueryHandler(skip_requirement, pattern="^skip_requirement_\d+$"),
            CallbackQueryHandler(add_more_channel, pattern="^add_more_channel_\d+$"),
            CallbackQueryHandler(next_step_after_requirement, pattern="^next_step_after_requirement_\d+$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, requirement_link_input),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        PRIZE_SETUP: [
            CallbackQueryHandler(setup_single_prize, pattern="^setup_single_prize_\d+$"),
            CallbackQueryHandler(setup_multiple_prize, pattern="^setup_multiple_prize_\d+$"),
            CallbackQueryHandler(add_more_prize, pattern="^add_more_prize_\d+$"),
            CallbackQueryHandler(finish_prize_setup, pattern="^finish_prize_setup_\d+$"),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        PRIZE_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, prize_name_input),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        PRIZE_DESC: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, prize_description_input),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        PRIZE_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, prize_count_input),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        POINTS_REQUIRED: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, points_required_input),
            CallbackQueryHandler(confirm_points_required, pattern="^confirm_points_\d+$"),
            CallbackQueryHandler(edit_points_required, pattern="^edit_points_\d+$"),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        MEDIA_UPLOAD: [
            CallbackQueryHandler(add_photo, pattern="^add_photo_\d+$"),
            CallbackQueryHandler(add_video, pattern="^add_video_\d+$"),
            CallbackQueryHandler(skip_media, pattern="^skip_media_\d+$"),
            MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_upload_handler),
            MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, video_upload_handler),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        SIGNUP_DEADLINE: [
            CallbackQueryHandler(set_signup_deadline, pattern="^signup_deadline_"),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        DRAW_TIME: [
            CallbackQueryHandler(set_draw_time, pattern="^draw_time_"),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$") 
        ],
        CUSTOM_DEADLINE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, custom_deadline_input),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        CUSTOM_DRAW_TIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, custom_draw_time_input),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        NOTIFY_PRIVATE: [
            CallbackQueryHandler(set_notify_private, pattern="^notify_private_"),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        ANNOUNCE_GROUP: [
            CallbackQueryHandler(set_announce_group, pattern="^announce_group_"),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ],
        PIN_RESULTS: [
            CallbackQueryHandler(set_pin_results, pattern="^pin_results_"),
            CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$")
        ]
    },
    fallbacks=[
        CallbackQueryHandler(cancel_lottery_setup, pattern="^cancel_lottery_setup_-?\d+$"),
        CommandHandler("cancel", cancel_lottery_setup)
    ],
    name="lottery_setup",
    persistent=False,
    per_user=True,
    per_chat=True,
    allow_reentry=True
)

# 在文件结尾处添加发布抽奖的回调处理
def get_lottery_handlers():
    """返回所有抽奖相关的处理器"""
    return [
        lottery_setup_handler,
        CallbackQueryHandler(publish_lottery_to_group, pattern="^publish_lottery_\d+$"),
        CallbackQueryHandler(join_lottery, pattern="^join_lottery_\d+$"),
        # 移除以下3个全局处理器，因为它们已经在对话处理器的MEDIA_UPLOAD状态中处理
        # CallbackQueryHandler(add_photo, pattern="^add_photo_\d+$"),
        # CallbackQueryHandler(add_video, pattern="^add_video_\d+$"),
        # CallbackQueryHandler(skip_media, pattern="^skip_media_\d+$"),
        # 这里可以添加其他抽奖相关的处理器
    ] 