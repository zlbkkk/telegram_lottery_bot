import logging
from telegram import Update, Chat, ChatMember, ChatMemberUpdated
from telegram.ext import ContextTypes
from django.utils import timezone
from django.db import transaction
from asgiref.sync import sync_to_async
from .models import Group, User, PointRule, Invite, DailyInviteStat, PointTransaction

# 设置日志
logger = logging.getLogger(__name__)

# 创建一个全局变量用于存储用户缓存清除函数的引用
_clear_user_groups_cache_func = None

# 设置缓存清除函数的引用
def set_cache_clear_function(func):
    """设置缓存清除函数的引用"""
    global _clear_user_groups_cache_func
    _clear_user_groups_cache_func = func
    logger.info("缓存清除函数引用已设置")

# 本地版本的缓存清除函数
def clear_user_groups_cache(telegram_id):
    """清除特定用户的群组缓存"""
    global _clear_user_groups_cache_func
    if _clear_user_groups_cache_func:
        _clear_user_groups_cache_func(telegram_id)
        logger.info(f"已清除用户 {telegram_id} 的群组缓存")
    else:
        logger.warning(f"缓存清除函数未设置，无法清除用户 {telegram_id} 的缓存")

def extract_status_change(chat_member_update: ChatMemberUpdated) -> tuple[bool, bool] or None:
    """
    提取ChatMemberUpdated中的状态变化
    返回一个元组，表示成员之前是否是群组成员以及现在是否是群组成员
    如果状态没有变化，则返回None
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member

# 定义同步函数来处理数据库操作
@sync_to_async
def save_group_to_db(chat_id, chat_title, chat_type, member_count, is_admin):
    """同步函数：保存或更新群组信息到数据库"""
    with transaction.atomic():
        group, created = Group.objects.update_or_create(
            group_id=chat_id,
            defaults={
                'group_title': chat_title,
                'group_type': chat_type,
                'member_count': member_count,
                'is_active': True,
                'bot_is_admin': is_admin,
                'joined_at': timezone.now()
            }
        )
    return group, created

@sync_to_async
def update_bot_admin_status(chat_id, is_admin):
    """同步函数：更新机器人的管理员状态"""
    with transaction.atomic():
        group = Group.objects.filter(group_id=chat_id).first()
        if group:
            group.bot_is_admin = is_admin
            group.save()
            return True
    return False

@sync_to_async
def save_user_to_group(telegram_id, username, first_name, last_name, group_obj, is_admin=False):
    """同步函数：将用户添加到群组或更新用户信息"""
    with transaction.atomic():
        user, created = User.objects.update_or_create(
            telegram_id=telegram_id,
            group=group_obj,
            defaults={
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'is_admin': is_admin,
                'is_active': True
            }
        )
        return user, created

@sync_to_async
def mark_group_inactive(chat_id):
    """同步函数：将群组标记为非活跃状态"""
    with transaction.atomic():
        group = Group.objects.filter(group_id=chat_id).first()
        if group:
            group.is_active = False
            group.save()
            return True
    return False

async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理机器人的成员状态变化
    当机器人被添加到群组或从群组中移除时，更新数据库
    """
    chat = update.effective_chat
    
    # 获取执行操作的用户名称（谁添加了机器人）
    cause_user = update.my_chat_member.from_user
    cause_name = cause_user.full_name
    
    # 记录更详细的日志，帮助调试
    logger.info(f"用户 {cause_user.id} ({cause_name}) 正在修改机器人在群组 {chat.id} ({chat.title}) 中的状态")
    logger.info(f"机器人成员状态变化 - 聊天ID: {chat.id}, 类型: {chat.type}, 操作人: {cause_name} ({cause_user.id})")
    
    # 获取机器人的新旧状态
    old_chat_member = update.my_chat_member.old_chat_member
    new_chat_member = update.my_chat_member.new_chat_member
    old_status = old_chat_member.status
    new_status = new_chat_member.status
    
    # 获取机器人在新旧状态下是否为管理员
    old_is_admin = old_status == ChatMember.ADMINISTRATOR
    new_is_admin = new_status == ChatMember.ADMINISTRATOR
    
    logger.info(f"机器人状态: 旧状态={old_status}, 新状态={new_status}, 权限变化: {old_is_admin}->{new_is_admin}")
    
    # 检查管理员状态是否发生变化
    admin_status_changed = old_is_admin != new_is_admin
    
    # 检查成员状态变化
    result = extract_status_change(update.my_chat_member)
    
    # 处理不同的聊天类型
    if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        # 检查管理员状态是否变更（无论成员状态是否变化）
        if admin_status_changed:
            if new_is_admin:
                logger.info("%s promoted the bot to administrator in the group %s", cause_name, chat.title)
                try:
                    # 更新数据库中的管理员状态
                    success = await update_bot_admin_status(chat.id, True)
                    if success:
                        logger.info(f"Bot admin status updated to True for group {chat.title} ({chat.id})")
                except Exception as e:
                    logger.error(f"Error updating bot admin status in database: {e}")
            else:
                logger.info("%s demoted the bot from administrator in the group %s", cause_name, chat.title)
                try:
                    # 更新数据库中的管理员状态
                    success = await update_bot_admin_status(chat.id, False)
                    if success:
                        logger.info(f"Bot admin status updated to False for group {chat.title} ({chat.id})")
                except Exception as e:
                    logger.error(f"Error updating bot admin status in database: {e}")
        
        # 处理机器人加入或离开群组的情况
        if result is not None:
            was_member, is_member = result
            
            # 机器人被添加到群组
            if not was_member and is_member:
                logger.info("%s added the bot to the group %s", cause_name, chat.title)
                
                # 记录群组信息到数据库
                try:
                    # 异步获取成员数量
                    member_count = None
                    if hasattr(chat, 'get_member_count'):
                        try:
                            member_count = await chat.get_member_count()
                        except Exception as e:
                            logger.warning(f"无法获取群组成员数量: {e}")

                    # 判断机器人是否为管理员
                    is_admin = new_is_admin
                    
                    # 使用同步函数保存数据
                    chat_type = 'SUPERGROUP' if chat.type == Chat.SUPERGROUP else 'GROUP'
                    group, created = await save_group_to_db(chat.id, chat.title, chat_type, member_count, is_admin)
                    
                    if created:
                        logger.info(f"Group {chat.title} ({chat.id}) has been added to the database")
                    else:
                        logger.info(f"Group {chat.title} ({chat.id}) has been updated in the database")
                    
                    # 记录添加机器人的用户到该群组的记录
                    try:
                        # 假设将添加机器人的用户作为管理员
                        user_is_admin = True
                        user, user_created = await save_user_to_group(
                            cause_user.id,
                            cause_user.username,
                            cause_user.first_name,
                            cause_user.last_name,
                            group,
                            user_is_admin
                        )
                        
                        if user_created:
                            logger.info(f"创建了用户 {cause_user.full_name} 在群组 {chat.title} 的记录")
                        else:
                            logger.info(f"更新了用户 {cause_user.full_name} 在群组 {chat.title} 的记录")
                            
                        # 清除该用户的群组缓存，确保立即能看到新群组
                        clear_user_groups_cache(cause_user.id)
                        logger.info(f"已清除用户 {cause_user.id} 的群组缓存，新群组将立即可见")
                    except Exception as e:
                        logger.error(f"将用户添加到群组记录时出错: {e}")
                        
                    # 不发送任何欢迎消息，让用户自行在私聊中启动机器人
                    logger.info(f"机器人已加入群组 {chat.title}，保持静默，不发送任何消息")
                except Exception as e:
                    logger.error(f"Error saving group to database: {e}")
            
            # 机器人被移除出群组
            elif was_member and not is_member:
                logger.info("%s removed the bot from the group %s", cause_name, chat.title)
                
                # 更新数据库中的群组状态
                try:
                    success = await mark_group_inactive(chat.id)
                    if success:
                        logger.info(f"Group {chat.title} ({chat.id}) has been marked as inactive")
                        
                        # 清除该用户的群组缓存，确保立即更新群组列表
                        clear_user_groups_cache(cause_user.id)
                        logger.info(f"已清除用户 {cause_user.id} 的群组缓存，群组列表将立即更新")
                except Exception as e:
                    logger.error(f"Error updating group status in database: {e}")
    
    # 处理频道
    elif chat.type == Chat.CHANNEL:
        # 检查管理员状态是否变更（无论成员状态是否变化）
        if admin_status_changed:
            if new_is_admin:
                logger.info("%s promoted the bot to administrator in the channel %s", cause_name, chat.title)
                try:
                    # 更新数据库中的管理员状态
                    success = await update_bot_admin_status(chat.id, True)
                    if success:
                        logger.info(f"Bot admin status updated to True for channel {chat.title} ({chat.id})")
                except Exception as e:
                    logger.error(f"Error updating bot admin status in database: {e}")
            else:
                logger.info("%s demoted the bot from administrator in the channel %s", cause_name, chat.title)
                try:
                    # 更新数据库中的管理员状态
                    success = await update_bot_admin_status(chat.id, False)
                    if success:
                        logger.info(f"Bot admin status updated to False for channel {chat.title} ({chat.id})")
                except Exception as e:
                    logger.error(f"Error updating bot admin status in database: {e}")
        
        # 处理机器人加入或离开频道的情况
        if result is not None:
            was_member, is_member = result
            
            if not was_member and is_member:
                logger.info("%s added the bot to the channel %s", cause_name, chat.title)
                
                # 记录频道信息到数据库
                try:
                    # 判断机器人是否为管理员
                    is_admin = new_is_admin
                    
                    # 使用同步函数保存数据
                    group, created = await save_group_to_db(chat.id, chat.title, 'CHANNEL', None, is_admin)
                    
                    if created:
                        logger.info(f"Channel {chat.title} ({chat.id}) has been added to the database")
                    else:
                        logger.info(f"Channel {chat.title} ({chat.id}) has been updated in the database")
                    
                    # 记录添加机器人的用户
                    logger.info(f"机器人已加入频道 {chat.title}，由用户 {cause_user.id} ({cause_user.full_name}) 添加")
                    
                    # 假设将添加机器人的用户作为管理员
                    user_is_admin = True
                    user, user_created = await save_user_to_group(
                        cause_user.id,
                        cause_user.username,
                        cause_user.first_name,
                        cause_user.last_name,
                        group,
                        user_is_admin
                    )
                    
                    if user_created:
                        logger.info(f"创建了用户 {cause_user.full_name} 在频道 {chat.title} 的记录")
                    else:
                        logger.info(f"更新了用户 {cause_user.full_name} 在频道 {chat.title} 的记录")
                        
                    # 清除该用户的群组缓存，确保立即能看到新频道
                    clear_user_groups_cache(cause_user.id)
                    logger.info(f"已清除用户 {cause_user.id} 的群组缓存，新频道将立即可见")
                    
                except Exception as e:
                    logger.error(f"Error saving channel to database: {e}")
            
            # 机器人被移除出频道
            elif was_member and not is_member:
                logger.info("%s removed the bot from the channel %s", cause_name, chat.title)
                
                # 更新数据库中的频道状态
                try:
                    success = await mark_group_inactive(chat.id)
                    if success:
                        logger.info(f"Channel {chat.title} ({chat.id}) has been marked as inactive")
                        
                        # 清除该用户的群组缓存，确保立即更新群组列表
                        clear_user_groups_cache(cause_user.id)
                        logger.info(f"已清除用户 {cause_user.id} 的群组缓存，群组列表将立即更新")
                except Exception as e:
                    logger.error(f"Error updating channel status in database: {e}")

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理其他用户的成员状态变化
    可用于跟踪群组成员的加入和离开
    """
    result = extract_status_change(update.chat_member)
    if result is None:
        return
    
    was_member, is_member = result
    chat = update.effective_chat
    
    # 由谁引起的变化
    cause_user = update.chat_member.from_user
    cause_name = cause_user.mention_html()
    
    # 被影响的成员
    member_user = update.chat_member.new_chat_member.user
    member_name = member_user.mention_html()
    
    logger.info(f"群组 {chat.id} ({chat.title}) 中的用户 {member_user.id} ({member_user.full_name}) 状态变化，由 {cause_user.id} ({cause_user.full_name}) 触发")
    
    # 记录用户加入或离开群组
    if not was_member and is_member:
        logger.info(f"用户 {member_user.full_name} 加入了群组 {chat.title}")
        
        try:
            # 获取群组对象
            group = await sync_to_async(Group.objects.filter(group_id=chat.id, is_active=True).first)()
            
            if group:
                # 检查该用户是否为管理员
                member = await chat.get_member(member_user.id)
                is_admin = member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
                
                # 添加用户到群组记录
                user, created = await save_user_to_group(
                    member_user.id,
                    member_user.username,
                    member_user.first_name,
                    member_user.last_name,
                    group,
                    is_admin
                )
                
                if created:
                    logger.info(f"创建了用户 {member_user.full_name} 在群组 {chat.title} 的记录")
                else:
                    logger.info(f"更新了用户 {member_user.full_name} 在群组 {chat.title} 的记录")
                
                # 清除该用户的群组缓存，确保立即能看到新群组
                clear_user_groups_cache(member_user.id)
                logger.info(f"已清除用户 {member_user.id} 的群组缓存，新群组将立即可见")
                
                # 处理邀请积分
                # 情况1: 某人直接邀请另一个人进群 (cause_user ≠ member_user)
                # 情况2: 用户通过邀请链接加入 (cause_user = member_user)，需要检查链接来源
                
                inviter_id = None
                invitation_type = None
                
                if cause_user.id != member_user.id:
                    # 直接邀请的情况
                    inviter_id = cause_user.id
                    invitation_type = "直接邀请"
                    logger.info(f"用户 {member_user.full_name} 是由 {cause_user.full_name} 直接邀请加入群组的")
                else:
                    # 可能是通过邀请链接加入
                    # 检查用户是否是通过邀请链接加入
                    if hasattr(update.effective_chat, 'invite_link') and update.effective_chat.invite_link:
                        invite_link = update.effective_chat.invite_link
                        logger.info(f"检测到邀请链接: {invite_link}")
                        
                        # 从邀请链接中提取创建者ID (如果可用)
                        if hasattr(invite_link, 'creator') and invite_link.creator:
                            inviter_id = invite_link.creator.id
                            invitation_type = "邀请链接"
                            logger.info(f"用户 {member_user.full_name} 是通过由 {invite_link.creator.full_name} 创建的邀请链接加入的")
                
                # 检查标准Telegram邀请链接 (t.me/+...)
                if not inviter_id:
                    try:
                        # 尝试获取该群组的所有邀请链接并查找最近创建的链接
                        recent_invite_links = await context.bot.get_chat_administrators(chat.id)
                        logger.info(f"获取群组管理员列表，找到 {len(recent_invite_links)} 个管理员")
                        
                        # 在管理员中寻找最近活跃的一个作为可能的邀请人
                        for admin in recent_invite_links:
                            if admin.user.id != context.bot.id:  # 排除机器人自己
                                inviter_id = admin.user.id
                                invitation_type = "最近活跃管理员邀请"
                                logger.info(f"使用最近活跃的管理员 {admin.user.full_name} (ID: {admin.user.id}) 作为可能的邀请人")
                                break
                    except Exception as e:
                        logger.error(f"尝试获取群组邀请链接时出错: {e}", exc_info=True)
                
                # 如果还没找到邀请人，检查群组创建者或第一个管理员
                if not inviter_id:
                    try:
                        # 获取群组信息，查找群组创建者
                        chat_info = await context.bot.get_chat(chat.id)
                        if hasattr(chat_info, 'permissions') and chat_info.permissions:
                            # 尝试找到群组创建者或所有者
                            logger.info(f"尝试找到群组创建者或所有者")
                            admins = await context.bot.get_chat_administrators(chat.id)
                            for admin in admins:
                                if admin.status == 'creator':
                                    inviter_id = admin.user.id
                                    invitation_type = "群组创建者"
                                    logger.info(f"使用群组创建者 {admin.user.full_name} (ID: {admin.user.id}) 作为默认邀请人")
                                    break
                            
                            # 如果没找到创建者，使用第一个管理员
                            if not inviter_id and admins:
                                inviter_id = admins[0].user.id
                                invitation_type = "群组管理员"
                                logger.info(f"使用群组管理员 {admins[0].user.full_name} (ID: {admins[0].user.id}) 作为默认邀请人")
                    except Exception as e:
                        logger.error(f"尝试获取群组信息时出错: {e}", exc_info=True)
                
                # 检查referral字段，查看是否包含了邀请者信息
                if not inviter_id and context.bot_data.get("pending_invites"):
                    for invite_code, invite_data in context.bot_data["pending_invites"].items():
                        if invite_data.get("user_id") == member_user.id and invite_data.get("group_id") == chat.id:
                            inviter_id = invite_data.get("inviter_id")
                            invitation_type = "追踪链接"
                            logger.info(f"从追踪链接中找到邀请关系: {invite_data.get('inviter_name')} 邀请了 {member_user.full_name}")
                            break
                
                # 如果找到了邀请人，处理邀请积分
                if inviter_id:
                    logger.info(f"开始处理邀请积分 ({invitation_type}): 邀请人ID={inviter_id}, 受邀人ID={member_user.id}")
                    
                    # 执行邀请积分处理
                    logger.info(f"开始处理邀请积分: 邀请人={inviter_id}, 被邀请人={member_user.id}")
                    
                    # 尝试获取邀请人信息，供内部函数使用
                    inviter_info = None
                    try:
                        inviter_info = await context.bot.get_chat_member(chat.id, inviter_id)
                        logger.info(f"获取到邀请人信息: {inviter_info.user.full_name}")
                    except Exception as e:
                        logger.warning(f"获取邀请人信息失败: {e}")
                    
                    # 异步处理邀请积分
                    success, points_awarded = await process_invite_points(inviter_id, member_user.id, group, inviter_info)
                    
                    if success:
                        logger.info(f"邀请积分处理成功，邀请人 {inviter_id} 获得 {points_awarded} 积分")
                    else:
                        logger.info("邀请积分处理未成功，可能是规则限制或已存在记录")
                    
                    # 清除邀请人的群组缓存，确保积分变更立即可见
                    clear_user_groups_cache(inviter_id)
                else:
                    logger.info(f"未找到邀请人信息，无法处理邀请积分。这可能是用户自己加入群组的情况。")
                    
            else:
                logger.warning(f"找不到群组记录: {chat.id} - {chat.title}")
        except Exception as e:
            logger.error(f"处理用户加入群组时出错: {e}", exc_info=True)
    
    # 用户离开群组
    elif was_member and not is_member:
        logger.info(f"用户 {member_user.full_name} 离开了群组 {chat.title}")
        
        try:
            # 获取群组对象
            group = await sync_to_async(Group.objects.filter(group_id=chat.id).first)()
            
            if group:
                # 将该用户在群组中标记为非活跃
                await sync_to_async(User.objects.filter(
                    telegram_id=member_user.id,
                    group__group_id=chat.id
                ).update)(is_active=False, is_admin=False)
                
                logger.info(f"用户 {member_user.id} ({member_user.full_name}) 已被标记为在群组 {chat.id} 中非活跃且非管理员")
                
                # 清除该用户的群组缓存，确保立即更新显示
                clear_user_groups_cache(member_user.id)
                logger.info(f"已清除用户 {member_user.id} 的群组缓存，群组列表将立即更新")
        except Exception as e:
            logger.error(f"处理用户离开群组时出错: {e}") 

# 异步处理邀请积分
@sync_to_async
def process_invite_points(inviter_id, invitee_id, group, inviter_info=None):
    from django.db import transaction
    from django.utils import timezone
    from .models import PointRule, User, Invite, DailyInviteStat, PointTransaction
    
    try:
        with transaction.atomic():
            # 获取邀请人信息
            inviter = User.objects.filter(
                telegram_id=inviter_id,
                group=group,
                is_active=True
            ).first()
            
            if not inviter:
                logger.warning(f"邀请人 {inviter_id} 在群组 {group.group_id} 中不存在或非活跃")
                
                # 尝试创建邀请人记录（如果不存在且有信息）
                if inviter_info:
                    try:
                        # 创建用户记录
                        member_info = inviter_info
                        inviter = User.objects.create(
                            telegram_id=inviter_id,
                            username=member_info.user.username,
                            first_name=member_info.user.first_name,
                            last_name=member_info.user.last_name,
                            group=group,
                            is_active=True,
                            is_admin=member_info.status in ['administrator', 'creator']
                        )
                        logger.info(f"为邀请人 {inviter_id} 创建了新记录")
                    except Exception as e:
                        logger.error(f"创建邀请人记录失败: {e}")
                        return False, 0
                else:
                    logger.error(f"没有邀请人信息，无法创建记录")
                    return False, 0
            
            # 获取被邀请人信息
            invitee = User.objects.filter(
                telegram_id=invitee_id,
                group=group,
                is_active=True
            ).first()
            
            if not invitee:
                logger.warning(f"被邀请人 {invitee_id} 在群组 {group.group_id} 中不存在或非活跃")
                return False, 0
            
            # 检查群组积分规则
            rule = PointRule.objects.filter(group=group).first()
            if not rule or not rule.points_enabled:
                logger.info(f"群组 {group.group_id} 未设置积分规则或积分功能已关闭")
                return False, 0
            
            # 获取今天的日期
            today = timezone.now().date()
            
            # 检查是否已经存在邀请记录
            if Invite.objects.filter(inviter=inviter, invitee=invitee, group=group).exists():
                logger.info(f"已存在邀请记录：{inviter.telegram_id} 邀请 {invitee.telegram_id}")
                return False, 0
            
            # 获取邀请人今日已获得的邀请积分
            daily_stat = DailyInviteStat.objects.filter(
                user=inviter,
                group=group,
                invite_date=today
            ).first()
            
            # 如果没有今日记录，创建一个
            if not daily_stat:
                daily_stat = DailyInviteStat(
                    user=inviter,
                    group=group,
                    invite_date=today,
                    invite_count=0,
                    points_awarded=0
                )
            
            # 检查是否达到每日上限
            # invite_points: 每邀请一个用户获得的积分
            # invite_daily_limit: 每日邀请用户的次数上限
            points_to_award = rule.invite_points  # 每次邀请获得的固定积分值
            if rule.invite_daily_limit > 0:
                if daily_stat.invite_count >= rule.invite_daily_limit:
                    logger.info(f"用户 {inviter.telegram_id} 在群组 {group.group_id} 中已达到每日邀请次数上限 {rule.invite_daily_limit}")
                    return False, 0
                
                logger.info(f"今日已邀请次数: {daily_stat.invite_count}, 上限: {rule.invite_daily_limit}, 本次将获得: {points_to_award} 积分")
            
            # 创建邀请记录
            invite = Invite(
                inviter=inviter,
                invitee=invitee,
                group=group,
                points_awarded=points_to_award,
                invite_date=today
            )
            invite.save()
            
            # 更新邀请人积分
            old_points = inviter.points
            inviter.points += points_to_award
            inviter.save()
            
            # 更新每日邀请统计
            daily_stat.invite_count += 1
            daily_stat.points_awarded += points_to_award
            daily_stat.save()
            
            # 创建积分变动记录
            PointTransaction.objects.create(
                user=inviter,
                group=group,
                amount=points_to_award,
                type='INVITE',
                description=f"邀请用户 {invitee.first_name or ''} {invitee.last_name or ''} 获得 {points_to_award} 积分",
                transaction_date=today
            )
            
            logger.info(f"用户 {inviter.telegram_id} 邀请 {invitee.telegram_id} 到群组 {group.group_id} 获得 {points_to_award} 积分")
            return True, points_to_award
    except Exception as e:
        logger.error(f"处理邀请积分时出错: {e}", exc_info=True)
        return False, 0 