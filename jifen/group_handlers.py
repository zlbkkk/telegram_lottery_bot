import logging
from telegram import Update, Chat, ChatMember, ChatMemberUpdated
from telegram.ext import ContextTypes
from django.utils import timezone
from django.db import transaction
from asgiref.sync import sync_to_async
from .models import Group, User

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
                        
                    # 不发送欢迎消息
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
                    
                    # 记录添加机器人的用户到该频道的记录
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
                            logger.info(f"创建了用户 {cause_user.full_name} 在频道 {chat.title} 的记录")
                        else:
                            logger.info(f"更新了用户 {cause_user.full_name} 在频道 {chat.title} 的记录")
                    except Exception as e:
                        logger.error(f"将用户添加到频道记录时出错: {e}")
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
            else:
                logger.warning(f"找不到群组记录: {chat.id} - {chat.title}")
        except Exception as e:
            logger.error(f"处理用户加入群组时出错: {e}")
    
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
                ).update)(is_active=False)
                
                logger.info(f"用户 {member_user.id} ({member_user.full_name}) 已被标记为在群组 {chat.id} 中非活跃")
                
                # 清除该用户的群组缓存，确保立即更新显示
                clear_user_groups_cache(member_user.id)
                logger.info(f"已清除用户 {member_user.id} 的群组缓存，群组列表将立即更新")
        except Exception as e:
            logger.error(f"处理用户离开群组时出错: {e}") 