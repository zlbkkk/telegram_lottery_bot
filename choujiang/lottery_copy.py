import logging
import traceback
from datetime import datetime

from asgiref.sync import sync_to_async
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def copy_lottery_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理管理员在抽奖详情页点击"发送到群组"按钮"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取抽奖ID
        callback_data = query.data.split("_")
        logger.info(f"[抽奖复制] 回调数据解析: {callback_data}")
        
        # 根据回调数据格式提取lottery_id
        if len(callback_data) >= 3 and callback_data[0] == "send" and callback_data[1] == "to" and callback_data[2] == "group":
            # 格式: send_to_group_{lottery_id}
            lottery_id = int(callback_data[3])
        else:
            logger.warning(f"[抽奖复制] 未识别的回调数据格式: {query.data}, 尝试使用最后一部分作为lottery_id")
            # 尝试使用最后一部分作为lottery_id
            lottery_id = int(callback_data[-1])
            
        logger.info(f"[抽奖复制] 用户 {user.id} 请求复制抽奖ID={lottery_id}到其他群组")
        
        # 检查用户是否是管理员
        @sync_to_async
        def is_user_admin(user_id):
            from jifen.models import User
            try:
                return User.objects.filter(telegram_id=user_id, is_admin=True).exists()
            except Exception as e:
                logger.error(f"[抽奖复制] 检查用户管理员权限时出错: {e}")
                return False
                
        is_admin = await is_user_admin(user.id)
        if not is_admin:
            await query.message.reply_text("❌ 只有管理员才能将抽奖复制到其他群组。")
            return
        
        # 获取用户管理的群组列表
        @sync_to_async
        def get_user_admin_groups(user_id):
            from jifen.models import User, Group
            try:
                # 获取用户作为管理员的所有活跃群组
                groups = Group.objects.filter(
                    user__telegram_id=user_id,
                    user__is_admin=True,
                    user__is_active=True,
                    is_active=True
                ).distinct()
                
                return [(group.id, group.group_title, group.group_id) for group in groups]
            except Exception as e:
                logger.error(f"[抽奖复制] 获取用户管理群组时出错: {e}")
                return []
                
        admin_groups = await get_user_admin_groups(user.id)
        
        if not admin_groups:
            await query.message.reply_text("❌ 您没有管理任何群组，无法复制抽奖。")
            return
        
        # 获取当前抽奖信息
        @sync_to_async
        def get_lottery_info(lottery_id):
            from choujiang.models import Lottery
            try:
                lottery = Lottery.objects.get(id=lottery_id)
                return lottery
            except Lottery.DoesNotExist:
                logger.error(f"[抽奖复制] 抽奖ID={lottery_id}不存在")
                return None
                
        lottery = await get_lottery_info(lottery_id)
        
        if not lottery:
            await query.message.reply_text("❌ 抽奖不存在或已被删除。")
            return
        
        # 创建群组选择按钮
        @sync_to_async
        def prepare_buttons(lottery, admin_groups):
            from choujiang.models import Lottery
            
            buttons = []
            lottery_group_id = lottery.group.id
            
            for group_id, group_title, telegram_group_id in admin_groups:
                # 跳过当前抽奖所在的群组
                if group_id == lottery_group_id:
                    continue
                    
                buttons.append([
                    InlineKeyboardButton(
                        f"{group_title}", 
                        callback_data=f"copy_lottery_to_{lottery.id}_{group_id}"
                    )
                ])
                
            # 添加取消按钮
            buttons.append([InlineKeyboardButton("❌ 取消", callback_data=f"cancel_copy_lottery")])
            
            return buttons, lottery.title
            
        buttons, lottery_title = await prepare_buttons(lottery, admin_groups)
        
        # 如果没有其他可选群组（只有当前群组）
        if len(buttons) == 1:  # 只有取消按钮
            await query.message.reply_text("⚠️ 您没有管理其他群组，无法复制抽奖。")
            return
            
        # 显示群组选择界面
        keyboard = InlineKeyboardMarkup(buttons)
        await query.message.reply_text(
            f"📋 请选择要将抽奖 「{lottery_title}」 复制到的群组:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"[抽奖复制] 准备复制抽奖时出错: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("处理请求时出错，请重试。")

async def cancel_copy_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户取消复制抽奖的操作"""
    query = update.callback_query
    await query.answer()
    
    # 删除原消息
    await query.message.delete()
    await query.message.reply_text("✅ 已取消复制抽奖操作。")

async def copy_lottery_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户选择群组后复制抽奖的操作"""
    query = update.callback_query
    user = update.effective_user
    
    await query.answer()
    
    try:
        # 从回调数据中提取抽奖ID和目标群组ID
        # 格式: copy_lottery_to_{lottery_id}_{group_id}
        callback_data = query.data.split("_")
        logger.info(f"[抽奖复制] 回调数据解析: {callback_data}")
        
        if len(callback_data) >= 5 and callback_data[0] == "copy" and callback_data[1] == "lottery" and callback_data[2] == "to":
            lottery_id = int(callback_data[3])
            group_id = int(callback_data[4])
        else:
            logger.warning(f"[抽奖复制] 未识别的回调数据格式: {query.data}")
            await query.message.edit_text("❌ 无效的操作，请重试。")
            return
        
        logger.info(f"[抽奖复制] 用户 {user.id} 复制抽奖ID={lottery_id}到群组ID={group_id}")
        
        # 复制抽奖到目标群组
        @sync_to_async
        def copy_lottery(lottery_id, target_group_id, user_id):
            from choujiang.models import Lottery, LotteryRequirement, Prize
            from jifen.models import User, Group
            from django.utils import timezone
            
            try:
                # 获取源抽奖和目标群组
                source_lottery = Lottery.objects.get(id=lottery_id)
                target_group = Group.objects.get(id=target_group_id)
                creator = User.objects.get(telegram_id=user_id, group=target_group)
                
                # 创建新抽奖记录
                new_lottery = Lottery(
                    title=source_lottery.title,
                    description=source_lottery.description,
                    group=target_group,
                    creator=creator,
                    lottery_type=source_lottery.lottery_type,
                    status='DRAFT',  # 设置为草稿状态，需要手动发布
                    signup_deadline=source_lottery.signup_deadline,
                    draw_time=source_lottery.draw_time,
                    auto_draw=source_lottery.auto_draw,
                    notify_winners_privately=source_lottery.notify_winners_privately,
                    announce_results_in_group=source_lottery.announce_results_in_group,
                    points_required=source_lottery.points_required,
                    pin_results=source_lottery.pin_results,
                    media_file_id=source_lottery.media_file_id,
                    media_type=source_lottery.media_type if hasattr(source_lottery, 'media_type') else None,
                )
                new_lottery.save()
                
                # 复制参与条件
                for req in LotteryRequirement.objects.filter(lottery=source_lottery):
                    new_req = LotteryRequirement(
                        lottery=new_lottery,
                        requirement_type=req.requirement_type,
                        channel_username=req.channel_username,
                        channel_id=req.channel_id,
                        group_username=req.group_username,
                        group_id=req.group_id,
                        min_registration_days=req.min_registration_days,
                        chat_identifier=req.chat_identifier
                    )
                    new_req.save()
                
                # 复制奖品信息
                for prize in Prize.objects.filter(lottery=source_lottery):
                    new_prize = Prize(
                        lottery=new_lottery,
                        name=prize.name,
                        description=prize.description,
                        quantity=prize.quantity,
                        image=prize.image,
                        order=prize.order
                    )
                    new_prize.save()
                
                return new_lottery, target_group.group_title
            except Exception as e:
                logger.error(f"[抽奖复制] 复制抽奖数据时出错: {e}\n{traceback.format_exc()}")
                return None, None
        
        # 执行复制操作
        new_lottery, target_group_title = await copy_lottery(lottery_id, group_id, user.id)
        
        if not new_lottery:
            await query.message.edit_text("❌ 复制抽奖时出错，请重试。")
            return
            
        # 删除选择群组的消息
        await query.message.delete()
        
        # 获取奖品信息用于预览消息
        @sync_to_async
        def get_prizes(lottery_id):
            from choujiang.models import Prize
            prizes = Prize.objects.filter(lottery_id=lottery_id).order_by('order')
            return list(prizes)
            
        prizes = await get_prizes(new_lottery.id)
        
        # 获取参与条件信息
        @sync_to_async
        def get_requirements(lottery_id):
            from choujiang.models import LotteryRequirement
            requirements = LotteryRequirement.objects.filter(lottery_id=lottery_id)
            return list(requirements)
            
        requirements = await get_requirements(new_lottery.id)
        
        # 获取实际的 Telegram 群组ID
        @sync_to_async
        def get_telegram_group_id(group_id):
            from jifen.models import Group
            try:
                group = Group.objects.get(id=group_id)
                return group.group_id, group.group_title
            except Exception as e:
                logger.error(f"[抽奖复制] 获取Telegram群组ID时出错: {e}")
                return None, None
                
        telegram_group_id, group_title = await get_telegram_group_id(group_id)
        if not telegram_group_id:
            await query.message.reply_text("❌ 获取群组信息失败，无法完成复制操作。")
            return
            
        logger.info(f"[抽奖复制] 获取到Telegram群组ID: {telegram_group_id}, 群组标题: {group_title}")
        
        # 构建奖品信息文本
        prizes_text = ""
        for prize in prizes:
            prizes_text += f"• {prize.name}: {prize.description} ({prize.quantity}名)\n"
            
        # 构建参与条件文本
        requirements_text = ""
        for req in requirements:
            if req.requirement_type == 'CHANNEL' and req.channel_username:
                username = req.channel_username
                if not username.startswith('@'):
                    username = f"@{username}"
                requirements_text += f"• 必须加入: {username}\n"
            elif req.requirement_type == 'GROUP' and req.group_username:
                username = req.group_username
                if not username.startswith('@'):
                    username = f"@{username}"
                requirements_text += f"• 必须加入: {username}\n"
            elif req.requirement_type == 'GROUP' and req.chat_identifier:
                requirements_text += f"• 必须加入: {req.chat_identifier}\n"
            elif req.requirement_type == 'CHANNEL' and req.chat_identifier:
                requirements_text += f"• 必须加入: {req.chat_identifier}\n"
        
        # 构建完整的预览消息
        preview_message = (
            f"🎁 <b>{new_lottery.title}</b>\n\n"
            f"{new_lottery.description}\n\n"
            f"⏱ 报名截止: {new_lottery.signup_deadline.strftime('%Y-%m-%d %H:%M')}\n"
            f"🕒 开奖时间: {new_lottery.draw_time.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"🏆 奖品设置:\n{prizes_text}\n"
        )
        
        # 如果有参与条件，添加到预览消息
        if requirements_text:
            preview_message += f"📝 参与条件:\n{requirements_text}\n"
        
        # 如果有积分要求，添加积分信息
        if new_lottery.points_required > 0:
            preview_message += f"💰 参与所需积分: {new_lottery.points_required}\n"
        
        # 创建查看新抽奖和发布按钮
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 查看抽奖详情", callback_data=f"view_lottery_{new_lottery.id}")],
            [InlineKeyboardButton("📢 发布到群组", callback_data=f"publish_lottery_{new_lottery.id}")]
        ])
        
        # 设置user_data，为发布做准备
        # 创建lottery_setup字典，包含publish_lottery_to_group所需的数据
        context.user_data['lottery_setup'] = {
            'lottery': new_lottery,
            'group_id': telegram_group_id,
            'group_title': group_title,
            'current_lottery_id': new_lottery.id,
            'preview_message': preview_message
        }
        
        logger.info(f"[抽奖复制] 已设置用户 {user.id} 的lottery_setup数据，为发布做准备")
        
        # 通知用户复制成功
        await query.message.reply_text(
            f"✅ 抽奖已成功复制到群组 「{group_title}」！\n\n"
            f"抽奖标题: {new_lottery.title}\n"
            f"抽奖ID: {new_lottery.id}\n\n"
            f"您可以查看抽奖详情或直接发布到群组。",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"[抽奖复制] 复制抽奖到群组时出错: {e}\n{traceback.format_exc()}")
        await query.message.edit_text("❌ 处理复制抽奖请求时出错，请重试。")

# 获取处理器列表
def get_lottery_copy_handlers():
    """返回抽奖复制功能的处理器列表"""
    handlers = [
        {
            'callback_pattern': r'^send_to_group_(\d+)$',
            'callback_handler': copy_lottery_button
        },
        {
            'callback_pattern': r'^send_to_group_id_(\d+)$',
            'callback_handler': copy_lottery_button
        },
        {
            'callback_pattern': r'^copy_lottery_to_(\d+)_(\d+)$',
            'callback_handler': copy_lottery_to_group
        },
        {
            'callback_pattern': r'^cancel_copy_lottery$',
            'callback_handler': cancel_copy_lottery
        }
    ]
    
    return handlers 