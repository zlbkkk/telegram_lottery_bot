import logging
from telegram import Update
from telegram.ext import ContextTypes
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.db import models
import asyncio
from .models import User, Group, PointTransaction

# 设置日志
logger = logging.getLogger(__name__)

async def query_user_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理用户在群组中发送"积分"时的积分查询请求
    回复用户当前的积分余额
    """
    # 确保是群组消息
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        logger.debug("非群组消息，不处理积分查询")
        return False
    
    # 获取消息和用户信息
    message = update.message
    user = update.effective_user
    if not message or not user:
        logger.warning("消息或用户信息为空，无法处理积分查询")
        return False
    
    # 检查消息文本是否为"积分"
    text = message.text.strip() if message.text else ""
    if text != "积分":
        logger.debug(f"消息文本不是'积分'，不处理: {text}")
        return False
    
    logger.info(f"用户 {user.id} ({user.full_name}) 在群组 {chat.id} ({chat.title}) 查询积分")
    
    # 从数据库查询用户积分
    @sync_to_async
    def get_user_points():
        try:
            group = Group.objects.filter(group_id=chat.id, is_active=True).first()
            if not group:
                logger.warning(f"群组 {chat.id} 不存在或非活跃")
                return None, 0, 0, 0, 0
            
            user_obj = User.objects.filter(telegram_id=user.id, group=group, is_active=True).first()
            if not user_obj:
                logger.warning(f"用户 {user.id} 在群组 {chat.id} 中不存在或非活跃")
                return group, 0, 0, 0, 0
            
            # 获取用户总积分
            total_points = user_obj.points
            
            # 获取今日签到积分
            today = timezone.now().date()
            today_checkin_points = PointTransaction.objects.filter(
                user=user_obj,
                group=group,
                type='CHECKIN',
                transaction_date=today
            ).values_list('amount', flat=True).first() or 0
            
            # 获取今日发言积分
            today_message_points = PointTransaction.objects.filter(
                user=user_obj,
                group=group,
                type='MESSAGE',
                transaction_date=today
            ).aggregate(total=models.Sum('amount'))['total'] or 0
            
            # 获取今日邀请积分
            today_invite_points = PointTransaction.objects.filter(
                user=user_obj,
                group=group,
                type='INVITE',
                transaction_date=today
            ).aggregate(total=models.Sum('amount'))['total'] or 0
            
            logger.info(f"用户 {user.id} 积分信息: 总积分={total_points}, 今日签到={today_checkin_points}, "
                       f"今日发言={today_message_points}, 今日邀请={today_invite_points}")
            
            return group, total_points, today_checkin_points, today_message_points, today_invite_points
        
        except Exception as e:
            logger.error(f"查询用户积分时出错: {e}", exc_info=True)
            return None, 0, 0, 0, 0
    
    # 获取积分信息
    group, total_points, today_checkin, today_message, today_invite = await get_user_points()
    
    if not group:
        # 发送查询失败消息，30秒后自动删除
        error_message = await message.reply_text(
            "❌ 查询失败，请确保您已在系统中注册。",
            reply_to_message_id=message.message_id
        )
        
        # 创建定时删除任务
        async def delete_error_message_later():
            try:
                await asyncio.sleep(10)  # 等待10秒
                # 删除错误消息
                await error_message.delete()
                logger.info(f"已删除用户 {user.id} 的查询失败消息")
                
                # 删除用户的原始查询消息
                try:
                    await message.delete()
                    logger.info(f"已删除用户 {user.id} 的原始积分查询消息")
                except Exception as e:
                    logger.error(f"删除用户原始积分查询消息时出错: {e}")
            except Exception as e:
                logger.error(f"删除查询失败消息时出错: {e}")
        
        # 启动异步任务
        asyncio.create_task(delete_error_message_later())
        
        return True
    
    # 构建积分信息消息
    today_total = today_checkin + today_message + today_invite
    
    # 获取今天的日期，格式化为中文形式
    today = timezone.now()
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    weekday_cn = weekday_names[today.weekday()]
    today_date = f"{today.year}年{today.month}月{today.day}日 星期{weekday_cn}"
    
    points_info = (
        f"💰 <b>{user.full_name}</b> 的积分信息：\n\n"
        f"当前积分：<b>{total_points}</b> 分\n"
        f"--------------------------------\n"
        f"📆 {today_date}\n"
        f"今日获得：<b>{today_total}</b> 分\n"
        f"└─ 签到：<b>{today_checkin}</b> 分\n"
        f"└─ 发言：<b>{today_message}</b> 分\n"
        f"└─ 邀请：<b>{today_invite}</b> 分"
    )
    
    # 回复用户并艾特他
    try:
        # 发送消息并设置10秒后自动删除
        sent_message = await message.reply_text(
            points_info,
            parse_mode="HTML",
            reply_to_message_id=message.message_id
        )
        logger.info(f"已向用户 {user.id} 发送积分查询结果，10秒后将自动删除")
        
        # 创建定时删除任务
        async def delete_message_later():
            try:
                await asyncio.sleep(10)  # 等待10秒
                # 删除机器人的回复消息
                await sent_message.delete()
                logger.info(f"已删除用户 {user.id} 的积分查询结果消息")
                
                # 删除用户的原始查询消息
                try:
                    await message.delete()
                    logger.info(f"已删除用户 {user.id} 的原始积分查询消息")
                except Exception as e:
                    logger.error(f"删除用户原始积分查询消息时出错: {e}")
            except Exception as e:
                logger.error(f"删除积分查询结果消息时出错: {e}")
        
        # 启动异步任务但不等待它完成
        asyncio.create_task(delete_message_later())
        
        return True
    except Exception as e:
        logger.error(f"发送积分查询结果时出错: {e}", exc_info=True)
        try:
            # 简化版本，尝试再次发送
            sent_message = await message.reply_text(
                f"您的当前积分：{total_points} 分",
                reply_to_message_id=message.message_id
            )
            
            # 简化版也设置10秒后删除
            async def delete_simple_message_later():
                try:
                    await asyncio.sleep(10)  # 等待10秒
                    # 删除简化版回复消息
                    await sent_message.delete()
                    logger.info(f"已删除简化版积分查询结果消息")
                    
                    # 删除用户的原始查询消息
                    try:
                        await message.delete()
                        logger.info(f"已删除用户 {user.id} 的原始积分查询消息")
                    except Exception as e:
                        logger.error(f"删除用户原始积分查询消息时出错: {e}")
                except Exception as e:
                    logger.error(f"删除简化积分查询结果消息时出错: {e}")
            
            asyncio.create_task(delete_simple_message_later())
            
            return True
        except Exception as e2:
            logger.error(f"发送简化积分查询结果也失败: {e2}")
            return False 