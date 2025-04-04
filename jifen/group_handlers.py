import logging
from telegram import Update, Chat, ChatMember, ChatMemberUpdated
from telegram.ext import ContextTypes
from django.utils import timezone
from django.db import transaction
from asgiref.sync import sync_to_async
from .models import Group, User, PointRule, Invite, DailyInviteStat, PointTransaction
from datetime import datetime

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

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理群组成员变化事件"""
    # 检查是否有bot_data
    if not hasattr(context, 'bot_data'):
        return
    
    chat_member_updated = update.chat_member
    if not chat_member_updated:
        return
    
    # 获取相关信息
    chat = chat_member_updated.chat
    user = chat_member_updated.new_chat_member.user
    from_user = chat_member_updated.from_user
    
    # 只处理群组消息
    if chat.type not in ["group", "supergroup"]:
        return
    
    # 检查是否是新加入的成员
    if chat_member_updated.old_chat_member.status in ['left', 'kicked'] and chat_member_updated.new_chat_member.status in ['member', 'restricted']:
        logger.info(f"用户 {user.id} ({user.full_name}) 加入了群组 {chat.id} ({chat.title})")
        logger.info(f"加入详情: 由用户 {from_user.id} ({from_user.full_name}) 操作, old_status={chat_member_updated.old_chat_member.status}, new_status={chat_member_updated.new_chat_member.status}")
        
        # 调试: 显示所有当前的pending_invites，帮助诊断问题
        if "pending_invites" in context.bot_data:
            active_invites = {code: invite for code, invite in context.bot_data["pending_invites"].items() 
                             if not invite.get('completed', False) and 
                                timezone.datetime.fromisoformat(invite.get('created_at', timezone.now().isoformat())).date() >= (timezone.now().date() - timezone.timedelta(days=2))}
            
            if active_invites:
                logger.info(f"当前有 {len(active_invites)} 个活跃的邀请记录:")
                for code, invite in active_invites.items():
                    logger.info(f"邀请码: {code}, 邀请人: {invite.get('inviter_id')} ({invite.get('inviter_name')}), "
                               f"群组: {invite.get('group_id')} ({invite.get('group_title')}), "
                               f"创建时间: {invite.get('created_at')}, "
                               f"链接: {invite.get('link_url', '无链接')}, "
                               f"官方标记: {invite.get('is_official_invite', False)}")
            else:
                logger.info("当前没有活跃的邀请记录")
        else:
            logger.info("上下文中没有pending_invites记录")
        
        # 记录邀请链接信息（如果有）
        invite_link_obj = getattr(chat_member_updated, 'invite_link', None)
        link_url = None
        if invite_link_obj:
            try:
                invite_link_str = str(invite_link_obj)
                invite_link_url = getattr(invite_link_obj, 'invite_link', 'unknown')
                invite_link_creator = getattr(invite_link_obj, 'creator', None)
                creator_id = getattr(invite_link_creator, 'id', 'unknown') if invite_link_creator else 'unknown'
                creator_name = getattr(invite_link_creator, 'full_name', 'unknown') if invite_link_creator else 'unknown'
                
                logger.info(f"完整邀请链接对象: {invite_link_str}")
                logger.info(f"邀请链接URL: {invite_link_url}")
                logger.info(f"邀请链接创建者: {creator_id} ({creator_name})")
                
                # 设置link_url供后续使用
                link_url = invite_link_url
            except Exception as e:
                logger.error(f"解析邀请链接对象信息时出错: {e}")
        else:
            logger.info("没有邀请链接信息")
        
        # 检查积分规则
        # 首先检查群组是否存在
        @sync_to_async
        def check_or_create_group():
            from .models import Group
            try:
                group, created = Group.objects.get_or_create(
                    group_id=chat.id,
                    defaults={
                        'group_title': chat.title,
                        'is_active': True
                    }
                )
                return group
            except Exception as e:
                logger.error(f"检查或创建群组时出错: {e}")
                return None
        
        @sync_to_async
        def get_point_rule(group):
            from .models import PointRule
            try:
                rule, created = PointRule.objects.get_or_create(
                    group=group,
                    defaults={
                        'invite_points': 1,
                        'invite_daily_limit': 0
                    }
                )
                return rule
            except Exception as e:
                logger.error(f"获取积分规则时出错: {e}")
                return None
                
        # 初始化邀请者变量
        inviter_id = None
        inviter_name = None
        
        # 优先级1: 检查是不是通过官方邀请链接加入的
        if from_user.id != user.id:
            logger.info(f"用户 {user.id} 由 {from_user.id} ({from_user.full_name}) 直接邀请加入群组 {chat.id}")
            # 不再自动将from_user设为邀请人，而是检查这个from_user是否创建过邀请链接
            # 检查pending_invites中是否有此用户创建的针对此群组的链接
            if "pending_invites" in context.bot_data:
                for code, invite in context.bot_data["pending_invites"].items():
                    if 'inviter_id' in invite and invite['inviter_id'] == from_user.id and 'group_id' in invite and invite['group_id'] == chat.id:
                        logger.info(f"找到匹配: 用户 {from_user.id} 之前创建过群组 {chat.id} 的邀请链接")
                        inviter_id = from_user.id
                        inviter_name = from_user.full_name
                        break
                
                if not inviter_id:
                    logger.info(f"用户 {from_user.id} 没有创建过此群组的邀请链接，不认为是邀请人")
            else:
                logger.info("没有pending_invites记录，不能确认邀请人身份")
        
        # 优先级2: 检查是否通过之前生成的邀请链接加入
        link_match_found = False
        if "pending_invites" in context.bot_data:
            logger.info(f"检查用户 {user.id} 是否通过跟踪的邀请链接加入")
            
            # 不再重复获取邀请链接信息，使用上面已经获取的link_url
            if link_url:
                logger.info(f"用户使用链接 {link_url} 加入群组")
                # 记录链接信息以便调试
                try:
                    if "+" in link_url:
                        link_core = link_url.split("+")[1] if "+" in link_url else ""
                        logger.info(f"用户链接核心部分: +{link_core}")
                    elif "/c/" in link_url:
                        link_core = link_url.split("/c/")[1] if len(link_url.split("/c/")) > 1 else ""
                        logger.info(f"用户链接核心部分: /c/{link_core}")
                except Exception as e:
                    logger.warning(f"提取用户链接核心部分时出错: {e}")
            else:
                logger.info("用户加入时没有提供邀请链接信息")
            
            # 记录所有候选邀请信息用于调试
            candidates = []
            for code, invite in context.bot_data["pending_invites"].items():
                if 'group_id' in invite and invite['group_id'] == chat.id:
                    candidates.append({
                        'code': code,
                        'inviter_id': invite.get('inviter_id'),
                        'inviter_name': invite.get('inviter_name'),
                        'created_at': invite.get('created_at'),
                        'completed': invite.get('completed', False),
                        'is_official_invite': invite.get('is_official_invite', False)
                    })
            
            if candidates:
                logger.info(f"找到 {len(candidates)} 个该群组的邀请记录: {candidates}")
            else:
                logger.info(f"没有找到针对群组 {chat.id} 的邀请记录")
            
            # 优先查找基于链接URL的匹配
            if link_url:  # 当有链接URL时进行链接匹配
                for code, invite in context.bot_data["pending_invites"].items():
                    if 'link_url' not in invite or 'group_id' not in invite:
                        continue
                        
                    if invite['group_id'] == chat.id:
                        invite_saved_url = invite.get('link_url', '')
                        logger.info(f"检查邀请记录 {code}: link_url={invite_saved_url}, 邀请人={invite.get('inviter_name')}")
                        
                        # 检查链接是否匹配当前加入链接
                        link_matched = False
                        
                        # 首先检查是否有官方标记
                        if invite.get('is_official_invite', False):
                            logger.info(f"发现官方邀请记录标记，比较链接是否匹配")
                            
                            # 提取链接的核心部分进行比较
                            # Telegram链接格式一般为https://t.me/+XXXX或https://t.me/c/XXXX
                            def extract_core_link(url):
                                if not url:
                                    return ""
                                try:
                                    # 提取+号或/c/后面的ID部分
                                    if "+" in url:  # 提取+后面的部分作为核心ID
                                        return url.split("+")[1] if "+" in url else url
                                    elif "/c/" in url:
                                        parts = url.split("/c/")
                                        return parts[1] if len(parts) > 1 else url
                                    return url
                                except Exception as e:
                                    logger.warning(f"提取链接核心部分时出错: {e}, url={url}")
                                    return url
                            
                            saved_core = extract_core_link(invite_saved_url)
                            current_core = extract_core_link(link_url)
                            
                            logger.info(f"链接核心部分比较: 存储={saved_core}, 当前={current_core}")
                            
                            if saved_core and current_core and saved_core == current_core:
                                link_matched = True
                                logger.info(f"链接核心完全匹配: {saved_core}")
                            elif saved_core and current_core and (saved_core in current_core or current_core in saved_core):
                                link_matched = True
                                logger.info(f"链接核心部分匹配: 存储={saved_core}, 当前={current_core}")
                            elif invite_saved_url and link_url == invite_saved_url:
                                link_matched = True
                                logger.info(f"链接完全匹配: {link_url}")
                            elif invite_saved_url and (link_url in invite_saved_url or invite_saved_url in link_url):
                                link_matched = True
                                logger.info(f"链接部分匹配: 用户链接={link_url}, 存储链接={invite_saved_url}")
                        else:
                            # 旧版本记录没有官方标记，使用普通匹配
                            if invite_saved_url and link_url == invite_saved_url:
                                link_matched = True
                                logger.info(f"链接完全匹配(旧版本): {link_url}")
                            elif invite_saved_url and (link_url in invite_saved_url or invite_saved_url in link_url):
                                link_matched = True
                                logger.info(f"链接部分匹配(旧版本): 用户链接={link_url}, 存储链接={invite_saved_url}")
                                
                        if link_matched:
                            logger.info(f"发现链接匹配! 用户 {user.id} 通过由 {invite.get('inviter_id')} ({invite.get('inviter_name')}) 创建的链接加入")
                            logger.info(f"邀请记录详情: {invite}")
                            
                            # 更新邀请人信息 - 这里覆盖之前可能设置的inviter_id
                            inviter_id = invite.get('inviter_id')
                            inviter_name = invite.get('inviter_name')
                            link_match_found = True
                            
                            # 不再将邀请记录标记为已完成，而是保留未完成状态使其可以被再次使用
                            # 只记录最近的被邀请人信息，但不影响下次使用
                            invite["last_invitee_id"] = user.id
                            invite["last_invitee_name"] = user.full_name
                            invite["last_used_at"] = timezone.now().isoformat()
                            context.bot_data["pending_invites"][code] = invite
                            
                            logger.info(f"已更新邀请记录 {code}，记录最近使用，但保持链接可重复使用，邀请者: {inviter_name}, 被邀请者: {user.full_name}")
                            break
            
            # 如果没有找到基于链接的匹配，尝试基于群组的匹配
            if not link_match_found:
                logger.info("没有找到链接URL匹配，尝试基于群组ID和时间的智能匹配")
                
                # 查找最近创建的、针对该群组的、带官方标记的邀请 (不再要求未完成)
                current_time = timezone.now()
                best_invite_code = None
                best_invite = None
                best_time_diff = float('inf')
                
                for code, invite in context.bot_data["pending_invites"].items():
                    if not (invite.get('group_id') == chat.id and 
                          invite.get('is_official_invite', False)):
                        continue
                    
                    # 计算创建时间与当前时间的差距
                    try:
                        if 'created_at' in invite:
                            created_time = timezone.datetime.fromisoformat(invite['created_at'])
                            time_diff = (current_time - created_time).total_seconds() / 60  # 转换为分钟
                            
                            # 只考虑48小时内创建的邀请
                            if time_diff <= 48 * 60:  # 48小时 = 2880分钟
                                if time_diff < best_time_diff:
                                    best_time_diff = time_diff
                                    best_invite_code = code
                                    best_invite = invite
                    except Exception as e:
                        logger.error(f"计算邀请时间差异时出错: {e}")
                
                # 使用找到的最佳匹配
                if best_invite:
                    logger.info(f"智能匹配: 找到最近的邀请记录，创建于 {best_time_diff:.1f} 分钟前")
                    logger.info(f"邀请记录详情: {best_invite}")
                    
                    # 更新邀请人信息
                    inviter_id = best_invite.get('inviter_id')
                    inviter_name = best_invite.get('inviter_name')
                    link_match_found = True
                    
                    # 更新邀请记录但不标记为completed
                    best_invite["last_invitee_id"] = user.id
                    best_invite["last_invitee_name"] = user.full_name
                    best_invite["last_used_at"] = timezone.now().isoformat()
                    best_invite["matched_by"] = "group_time_match"  # 标记匹配方式
                    context.bot_data["pending_invites"][best_invite_code] = best_invite
                    
                    logger.info(f"已通过群组时间匹配更新邀请记录 {best_invite_code}，记录最近使用，但保持链接可重复使用")
                    logger.info(f"邀请者: {inviter_name}, 被邀请者: {user.full_name}")
            
            # 如果找到了邀请链接匹配，记录日志
            if link_match_found:
                logger.info(f"已找到邀请链接匹配，使用邀请人 {inviter_id} ({inviter_name})")
        
        # 如果没有找到邀请链接匹配，且用户是自己加入的，尝试检查之前通过bot私聊点击链接的记录
        if not inviter_id and from_user.id == user.id:
            logger.info(f"用户 {user.id} 自己加入群组，检查是否通过bot私聊中的跟踪链接")
            
            if "pending_invites" in context.bot_data:
                # 寻找匹配的邀请记录
                found_perfect_match = False
                matched_invite_code = None
                
                # 遍历所有邀请记录，寻找用户ID和群组ID匹配的记录
                for code, invite in context.bot_data["pending_invites"].items():
                    if 'user_id' in invite and invite['user_id'] == user.id and 'group_id' in invite:
                        invite_group_id = invite['group_id']
                        # 确保群组ID格式一致进行比较
                        if isinstance(invite_group_id, str) and invite_group_id.isdigit():
                            invite_group_id = int(invite_group_id)
                        
                        if invite_group_id == chat.id:
                            logger.info(f"找到完美匹配的邀请记录: 用户ID={user.id}, 群组ID={chat.id}")
                            inviter_id = invite['inviter_id']
                            inviter_name = invite['inviter_name']
                            found_perfect_match = True
                            matched_invite_code = code
                            break
                
                # 如果没有完美匹配，尝试通过时间窗口匹配
                if not found_perfect_match:
                    logger.info("没有找到精确匹配，尝试通过时间窗口匹配")
                    current_time = timezone.now()
                    time_window_minutes = 30  # 设置30分钟的时间窗口
                    
                    for code, invite in context.bot_data["pending_invites"].items():
                        if 'user_id' in invite and invite['user_id'] == user.id:
                            # 检查加入时间是否在最近的时间窗口内
                            if 'joined_at' in invite:
                                try:
                                    joined_time = timezone.datetime.fromisoformat(invite['joined_at'])
                                    time_diff = (current_time - joined_time).total_seconds() / 60
                                    
                                    if time_diff <= time_window_minutes:
                                        logger.info(f"找到时间窗口内的邀请记录: {time_diff}分钟前")
                                        inviter_id = invite['inviter_id']
                                        inviter_name = invite['inviter_name']
                                        matched_invite_code = code
                                        break
                                except Exception as e:
                                    logger.error(f"解析加入时间出错: {e}")
                
                # 如果找到了匹配，更新邀请记录，但不标记为已完成
                if matched_invite_code:
                    # 只记录最近使用
                    context.bot_data["pending_invites"][matched_invite_code]["last_used_at"] = timezone.now().isoformat()
                    context.bot_data["pending_invites"][matched_invite_code]["last_invitee_id"] = user.id
                    context.bot_data["pending_invites"][matched_invite_code]["last_invitee_name"] = user.full_name
                    logger.info(f"已更新邀请记录 {matched_invite_code}，记录最近使用，但保持链接可重复使用")
        
        # 如果到这里还没有找到邀请人，记录日志并且不分配积分
        if not inviter_id:
            logger.info(f"未找到有效的邀请匹配记录，用户 {user.id} ({user.full_name}) 加入群组不会给任何人分配积分")
        
        # 处理积分奖励 - 只有在找到有效邀请人的情况下才执行
        if inviter_id:
            group = await check_or_create_group()
            if group:
                rule = await get_point_rule(group)
                if rule and rule.invite_points > 0:
                    # 检查是否达到每日限制
                    @sync_to_async
                    def check_daily_limit_and_add_points():
                        from .models import User, PointTransaction, Invite, DailyInviteStat
                        from django.db.models import Sum, Count
                        from django.utils import timezone
                        import datetime
                        
                        try:
                            # 获取今天的日期
                            today = timezone.now().date()
                            tomorrow = today + datetime.timedelta(days=1)
                            today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
                            today_end = timezone.make_aware(datetime.datetime.combine(tomorrow, datetime.time.min))
                            
                            # 查找邀请人在数据库中的记录
                            logger.info(f"开始处理邀请奖励: 邀请人={inviter_id} ({inviter_name}), 被邀请人={user.id} ({user.full_name}), 群组ID={chat.id}")
                            inviter_user = User.objects.filter(telegram_id=inviter_id, group__group_id=chat.id).first()
                            if not inviter_user:
                                # 如果不存在，创建用户记录
                                group_obj = Group.objects.get(group_id=chat.id)
                                logger.info(f"邀请人 {inviter_id} 在数据库中不存在，创建新记录")
                                inviter_user = User.objects.create(
                                    telegram_id=inviter_id,
                                    username=None,  # 没有这个信息
                                    first_name=inviter_name.split()[0] if ' ' in inviter_name else inviter_name,
                                    last_name=inviter_name.split(' ', 1)[1] if ' ' in inviter_name else '',
                                    group=group_obj,
                                    points=0
                                )
                                logger.info(f"为用户 {inviter_id} 创建了新记录，ID={inviter_user.id}")
                            else:
                                logger.info(f"找到邀请人记录: ID={inviter_user.id}, 当前积分={inviter_user.points}")
                            
                            # 找到被邀请人的用户记录
                            invitee_user = User.objects.filter(telegram_id=user.id, group__group_id=chat.id).first()
                            if not invitee_user:
                                # 如果不存在，创建用户记录
                                group_obj = Group.objects.get(group_id=chat.id)
                                logger.info(f"被邀请人 {user.id} 在数据库中不存在，创建新记录")
                                invitee_user = User.objects.create(
                                    telegram_id=user.id,
                                    username=user.username,
                                    first_name=user.first_name,
                                    last_name=user.last_name,
                                    group=group_obj,
                                    points=0
                                )
                                logger.info(f"为用户 {user.id} 创建了新记录，ID={invitee_user.id}")
                            else:
                                logger.info(f"找到被邀请人记录: ID={invitee_user.id}, 当前积分={invitee_user.points}")
                            
                            # 检查今日邀请数量而不是积分
                            today_invite_count = Invite.objects.filter(
                                inviter=inviter_user,
                                invite_date=today
                            ).count()
                            
                            logger.info(f"用户 {inviter_id} 今日已邀请 {today_invite_count} 人，奖励规则积分={rule.invite_points}, 每日限制={rule.invite_daily_limit}")
                            
                            # 检查是否达到每日限制
                            if rule.invite_daily_limit > 0 and today_invite_count >= rule.invite_daily_limit:
                                logger.info(f"用户 {inviter_id} 今天已达到邀请人数上限 {rule.invite_daily_limit} 人")
                                return False, today_invite_count, rule.invite_daily_limit
                            
                            # 检查是否已经存在邀请记录
                            existing_invite = Invite.objects.filter(inviter=inviter_user, invitee=invitee_user).first()
                            if existing_invite:
                                logger.info(f"已存在邀请记录：{inviter_id} 邀请 {user.id}，创建于 {existing_invite.created_at}")
                                logger.info(f"⚠️ 不给予积分：用户 {user.full_name} (ID: {user.id}) 已被 {inviter_name} (ID: {inviter_id}) 邀请过此群组，重复邀请不计分")
                                return False, today_invite_count, rule.invite_daily_limit
                            
                            # 增加积分
                            previous_points = inviter_user.points
                            inviter_user.points += rule.invite_points
                            inviter_user.save()
                            logger.info(f"用户 {inviter_id} 积分已更新: {previous_points} -> {inviter_user.points} (+{rule.invite_points})")
                            
                            # 记录积分变动
                            transaction = PointTransaction.objects.create(
                                user=inviter_user,
                                group=group,
                                amount=rule.invite_points,
                                type='INVITE',
                                description=f"邀请用户 {user.full_name} 加入群组",
                                transaction_date=today
                            )
                            logger.info(f"创建积分交易记录 ID: {transaction.id}, 数量: {rule.invite_points}, 描述: {transaction.description}")
                            
                            # 创建邀请记录
                            invite = Invite.objects.create(
                                inviter=inviter_user,
                                invitee=invitee_user,
                                group=group,
                                points_awarded=rule.invite_points,
                                invite_date=today
                            )
                            logger.info(f"创建了邀请记录: {inviter_name} 邀请 {user.full_name}, 记录ID: {invite.id}")
                            
                            # 更新每日邀请统计
                            daily_stat, created = DailyInviteStat.objects.get_or_create(
                                user=inviter_user,
                                group=group,
                                invite_date=today,
                                defaults={
                                    'invite_count': 1,
                                    'points_awarded': rule.invite_points
                                }
                            )
                            
                            if not created:
                                daily_stat.invite_count += 1
                                daily_stat.points_awarded += rule.invite_points
                                daily_stat.save()
                                
                            logger.info(f"更新了每日邀请统计: {inviter_name} 今日已邀请 {daily_stat.invite_count} 人，获得 {daily_stat.points_awarded} 积分")
                            
                            return True, today_invite_count + 1, rule.invite_daily_limit
                        except Exception as e:
                            logger.error(f"检查每日限制并添加积分时出错: {e}", exc_info=True)
                            return False, 0, 0
                    
                    success, today_points, daily_limit = await check_daily_limit_and_add_points()
                    if success:
                        logger.info(f"用户 {inviter_id} ({inviter_name}) 成功获得 {rule.invite_points} 积分，今日总计: {today_points}")
                        
                        # 发送通知
                        try:
                            # 给邀请人发送私聊通知
                            limit_text = f"，今日已获得 {today_points}/{daily_limit}" if daily_limit > 0 else ""
                            notification = f"🎉 恭喜！你邀请 {user.full_name} 加入群组 {chat.title} 获得了 {rule.invite_points} 积分{limit_text}"
                            try:
                                await context.bot.send_message(chat_id=inviter_id, text=notification)
                            except Exception as e:
                                logger.warning(f"无法向邀请人发送私聊通知: {e}，尝试在群组内通知")
                                # 失败时不再尝试，因为用户可能已经在群组欢迎消息中看到相关信息
                            
                            # 在群组中发送欢迎消息
                            welcome_message = f"👋 欢迎 {user.mention_html()} 加入！\n💎 感谢 {inviter_name} 的邀请，已获得 {rule.invite_points} 积分奖励。"
                            try:
                                await context.bot.send_message(
                                    chat_id=chat.id,
                                    text=welcome_message,
                                    parse_mode='HTML'
                                )
                                logger.info(f"已在群组 {chat.id} 发送欢迎消息")
                            except Exception as e:
                                logger.error(f"在群组中发送欢迎消息时出错: {e}")
                        except Exception as e:
                            logger.error(f"发送邀请积分通知时出错: {e}")
                    else:
                        logger.info(f"用户 {inviter_id} 未能获得邀请积分，可能已达到每日限制")
                    
                    # 检查是否是因为重复邀请而未给积分
                    @sync_to_async
                    def check_invite_reason():
                        from .models import User, Invite
                        inviter_user = User.objects.filter(telegram_id=inviter_id, group__group_id=chat.id).first()
                        invitee_user = User.objects.filter(telegram_id=user.id, group__group_id=chat.id).first()
                        if inviter_user and invitee_user:
                            existing_invite = Invite.objects.filter(inviter=inviter_user, invitee=invitee_user).first()
                            if existing_invite:
                                return "duplicate", existing_invite.created_at
                        # 检查是否达到每日上限
                        if rule.invite_daily_limit > 0:
                            today = timezone.now().date()
                            today_invite_count = Invite.objects.filter(
                                inviter=inviter_user,
                                invite_date=today
                            ).count()
                            if today_invite_count >= rule.invite_daily_limit:
                                return "limit", today_invite_count
                        return "unknown", None
                    
                    reason, detail = await check_invite_reason()
                    
                    try:
                        # 给邀请人发送不同原因的提示
                        if reason == "duplicate":
                            formatted_date = detail.strftime("%Y-%m-%d %H:%M:%S") if detail else "之前"
                            notification = f"⚠️ 提示：你已经在 {formatted_date} 邀请过用户 {user.full_name} 加入群组 {chat.title}，重复邀请不会获得额外积分。"
                            try:
                                await context.bot.send_message(chat_id=inviter_id, text=notification)
                                logger.info(f"已向用户 {inviter_id} 发送重复邀请提示")
                            except Exception as e:
                                logger.warning(f"无法向邀请人发送重复邀请提示: {e}")
                        elif reason == "limit":
                            notification = f"⚠️ 提示：你今日已达到邀请上限 ({rule.invite_daily_limit} 人)，无法获得更多邀请积分。"
                            try:
                                await context.bot.send_message(chat_id=inviter_id, text=notification)
                                logger.info(f"已向用户 {inviter_id} 发送达到邀请上限提示")
                            except Exception as e:
                                logger.warning(f"无法向邀请人发送达到邀请上限提示: {e}")
                        
                        # 无论如何都在群组中发送欢迎消息，但不提及积分
                        welcome_message = f"👋 欢迎 {user.mention_html()} 加入群组！"
                        await context.bot.send_message(
                            chat_id=chat.id,
                            text=welcome_message,
                            parse_mode='HTML'
                        )
                        logger.info(f"已在群组 {chat.id} 发送普通欢迎消息")
                    except Exception as e:
                        logger.error(f"发送邀请失败提示时出错: {e}")
    
    # 处理成员离开事件
    elif chat_member_updated.old_chat_member.status in ['member', 'restricted'] and chat_member_updated.new_chat_member.status in ['left', 'kicked']:
        logger.info(f"用户 {user.id} ({user.full_name}) 离开了群组 {chat.id} ({chat.title})")
        
        # 这里可以添加处理成员离开的逻辑 
    
    # 确保所有加入群组的用户都在数据库中有记录
    if chat_member_updated.new_chat_member.status in ['member', 'restricted']:
        @sync_to_async
        def ensure_user_record():
            from .models import User, Group
            
            try:
                # 检查用户是否已有记录
                user_record = User.objects.filter(telegram_id=user.id, group__group_id=chat.id).first()
                if not user_record:
                    # 检查群组是否存在
                    group_obj = Group.objects.filter(group_id=chat.id).first()
                    if not group_obj:
                        # 如果群组不存在，创建群组记录
                        group_obj = Group.objects.create(
                            group_id=chat.id,
                            group_title=chat.title,
                            is_active=True
                        )
                        logger.info(f"为群组 {chat.id} ({chat.title}) 创建了新记录")
                    
                    # 创建用户记录
                    user_record = User.objects.create(
                        telegram_id=user.id,
                        username=user.username,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        group=group_obj,
                        points=0
                    )
                    logger.info(f"【通用记录创建】为用户 {user.id} ({user.full_name}) 在群组 {chat.id} ({chat.title}) 创建了新记录")
                    return True
                return False
            except Exception as e:
                logger.error(f"确保用户记录存在时出错: {e}", exc_info=True)
                return False
        
        created = await ensure_user_record()
        if created:
            logger.info(f"已为用户 {user.id} 创建群组 {chat.id} 的记录") 