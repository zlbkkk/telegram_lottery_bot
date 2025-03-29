from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from datetime import datetime, timedelta
from .models import Lottery, LotteryType
from jifen.models import Group, User
import logging
from asgiref.sync import sync_to_async

# 设置日志
logger = logging.getLogger(__name__)

# 定义对话状态
TITLE, DESCRIPTION, DRAW_TIME, CONFIRM = range(4)

async def lottery_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理抽奖设置按钮点击"""
    query = update.callback_query
    user = update.effective_user
    
    # 检查是否已经处理过这个回调
    callback_id = f"lottery_settings_{query.id}"
    if context.user_data.get(callback_id):
        logger.info(f"回调 {query.id} 已经被处理过，跳过")
        return ConversationHandler.END
    
    # 标记这个回调已经被处理
    context.user_data[callback_id] = True
    
    logger.info(f"用户 {user.id} 点击了抽奖设置按钮")
    
    # 获取当前群组ID
    group_id = context.user_data.get('current_group_id')
    if not group_id:
        await query.message.reply_text("无法确定当前群组，请返回群组列表重新选择。")
        return ConversationHandler.END
    
    try:
        # 使用sync_to_async包装数据库操作
        group = await sync_to_async(Group.objects.get)(group_id=group_id)
        
        # 修改：获取特定群组中的用户记录
        user_obj = await sync_to_async(lambda: User.objects.filter(
            telegram_id=user.id,
            group=group
        ).first())()
        
        # 如果找不到用户记录，创建一个新的
        if not user_obj:
            user_obj = await sync_to_async(User.objects.create)(
                telegram_id=user.id,
                username=user.username or "",
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                group=group,
                is_active=True,
                joined_at=datetime.now()
            )
        
        # 存储群组和用户信息到上下文
        context.user_data['lottery_setup'] = {
            'group_id': group_id,
            'group': group,
            'user': user_obj
        }
        
        # 发送标题输入提示
        try:
            await query.message.edit_text(
                "📝 抽奖基本信息设置\n\n"
                "请输入抽奖活动的标题：\n"
                "(例如: \"周末大抽奖\"、\"新品上市庆祝抽奖\")"
            )
        except Exception as e:
            # 如果编辑消息失败（可能是因为消息已经被修改），则发送新消息
            logger.warning(f"编辑消息失败: {e}，尝试发送新消息")
            await query.message.reply_text(
                "📝 抽奖基本信息设置\n\n"
                "请输入抽奖活动的标题：\n"
                "(例如: \"周末大抽奖\"、\"新品上市庆祝抽奖\")"
            )
        
        logger.info(f"已向用户 {user.id} 发送抽奖标题输入提示")
        return TITLE
        
    except Group.DoesNotExist:
        await query.message.reply_text("找不到当前群组信息，请联系管理员。")
        logger.error(f"找不到群组ID为 {group_id} 的群组")
        return ConversationHandler.END
        
    except Exception as e:
        await query.message.reply_text(f"设置抽奖时出错：{str(e)}")
        logger.error(f"设置抽奖时出错: {e}", exc_info=True)
        return ConversationHandler.END

async def title_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理标题输入"""
    title = update.message.text
    user = update.effective_user
    
    logger.info(f"用户 {user.id} 输入了抽奖标题: {title}")
    
    # 存储标题
    context.user_data['lottery_setup']['title'] = title
    
    # 请求输入描述
    await update.message.reply_text(
        "请输入抽奖活动的描述：\n"
        "(可以包含活动背景、规则说明等)"
    )
    
    logger.info(f"已向用户 {user.id} 发送抽奖描述输入提示")
    return DESCRIPTION

async def description_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理描述输入"""
    description = update.message.text
    
    # 存储描述
    context.user_data['lottery_setup']['description'] = description
    
    # 请求输入开奖时间
    await update.message.reply_text(
        "请输入开奖时间 (格式: YYYY-MM-DD HH:MM)：\n"
        "例如: 2025-04-01 18:00"
    )
    
    return DRAW_TIME

async def draw_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理开奖时间输入"""
    draw_time_str = update.message.text
    
    try:
        # 解析时间
        draw_time = datetime.strptime(draw_time_str, "%Y-%m-%d %H:%M")
        
        # 检查时间是否有效（必须是未来时间）
        if draw_time <= datetime.now():
            await update.message.reply_text("开奖时间必须是未来时间，请重新输入。")
            return DRAW_TIME
        
        # 存储开奖时间
        context.user_data['lottery_setup']['draw_time'] = draw_time
        
        # 设置报名截止时间为开奖时间前1小时
        signup_deadline = draw_time - timedelta(hours=1)
        context.user_data['lottery_setup']['signup_deadline'] = signup_deadline
        
        # 显示确认信息
        lottery_data = context.user_data['lottery_setup']
        
        confirm_text = (
            "📋 请确认抽奖活动信息：\n\n"
            f"标题: {lottery_data['title']}\n"
            f"描述: {lottery_data['description']}\n"
            f"报名截止: {signup_deadline.strftime('%Y-%m-%d %H:%M')}\n"
            f"开奖时间: {draw_time.strftime('%Y-%m-%d %H:%M')}\n\n"
            "确认创建抽奖活动吗？"
        )
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 确认", callback_data="lottery_confirm"),
                InlineKeyboardButton("❌ 取消", callback_data="lottery_cancel")
            ]
        ])
        
        await update.message.reply_text(confirm_text, reply_markup=keyboard)
        
        return CONFIRM
        
    except ValueError:
        await update.message.reply_text(
            "时间格式不正确，请使用 YYYY-MM-DD HH:MM 格式。\n"
            "例如: 2025-04-01 18:00"
        )
        return DRAW_TIME

async def confirm_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理确认创建抽奖"""
    query = update.callback_query
    action = query.data.split("_")[1]
    
    if action == "cancel":
        await query.message.edit_text("已取消创建抽奖活动。")
        
        # 清理上下文数据
        if 'lottery_setup' in context.user_data:
            del context.user_data['lottery_setup']
        
        return ConversationHandler.END
    
    # 获取抽奖设置数据
    lottery_data = context.user_data.get('lottery_setup', {})
    
    try:
        # 获取或创建默认抽奖类型
        lottery_type = await sync_to_async(LotteryType.objects.get_or_create)(
            name="常规抽奖",
            defaults={"description": "常规抽奖活动"}
        )
        lottery_type = lottery_type[0]  # get_or_create返回(object, created)元组
        
        # 创建抽奖活动
        lottery = await sync_to_async(Lottery.objects.create)(
            title=lottery_data['title'],
            description=lottery_data['description'],
            group=lottery_data['group'],
            creator=lottery_data['user'],
            lottery_type=lottery_type,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            signup_deadline=lottery_data['signup_deadline'],
            draw_time=lottery_data['draw_time'],
            auto_draw=True,
            notify_winners_privately=True,
            announce_results_in_group=True,
            status='DRAFT'
        )
        
        await query.message.edit_text(
            f"✅ 抽奖活动「{lottery.title}」创建成功！\n\n"
            f"您可以继续设置奖品和参与条件。"
        )
        
        # 清理上下文数据
        if 'lottery_setup' in context.user_data:
            del context.user_data['lottery_setup']
        
        return ConversationHandler.END
        
    except Exception as e:
        await query.message.edit_text(f"创建抽奖活动时出错：{str(e)}")
        logger.error(f"创建抽奖活动时出错: {e}", exc_info=True)
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """取消对话"""
    await update.message.reply_text("已取消抽奖设置。")
    
    # 清理上下文数据
    if 'lottery_setup' in context.user_data:
        del context.user_data['lottery_setup']
    
    return ConversationHandler.END

# 修改抽奖设置对话处理器
lottery_settings_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(lottery_settings, pattern="^抽奖设置$")
    ],
    states={
        TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, title_input)],
        DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_input)],
        DRAW_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, draw_time_input)],
        CONFIRM: [CallbackQueryHandler(confirm_lottery, pattern="^lottery_(confirm|cancel)$")]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    name="lottery_settings",
    persistent=False,
    per_chat=True
) 