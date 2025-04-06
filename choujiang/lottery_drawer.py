import logging
import asyncio
import random
import traceback
from datetime import datetime, timedelta
from asgiref.sync import sync_to_async
from django.utils import timezone
import threading

from choujiang.models import Lottery, Participant, Prize, LotteryLog
from jifen.models import User, Group, PointTransaction

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class LotteryDrawer:
    """抽奖开奖器类，处理自动开奖和指定中奖者功能"""
    
    def __init__(self, bot):
        """初始化抽奖开奖器"""
        self.bot = bot
    
    async def check_and_draw_lotteries(self):
        """检查并执行所有需要开奖的抽奖"""
        try:
            # 获取所有需要开奖的抽奖
            @sync_to_async
            def get_lotteries_to_draw():
                now = timezone.now()
                
                # 找到状态为ACTIVE，已到开奖时间，且设置了自动开奖的抽奖
                lotteries = Lottery.objects.filter(
                    status='ACTIVE',
                    auto_draw=True,
                    draw_time__lte=now
                )
                
                return list(lotteries)
                
            lotteries_to_draw = await get_lotteries_to_draw()
            
            if not lotteries_to_draw:
                logger.info("[自动开奖] 没有需要开奖的抽奖")
                return
                
            logger.info(f"[自动开奖] 发现 {len(lotteries_to_draw)} 个需要开奖的抽奖")
            
            # 依次执行开奖
            for lottery in lotteries_to_draw:
                logger.info(f"[自动开奖] 准备开奖: ID={lottery.id}, 标题={lottery.title}")
                success = await self.draw_lottery(lottery.id)
                if success:
                    logger.info(f"[自动开奖] 抽奖ID={lottery.id}开奖成功")
                else:
                    logger.error(f"[自动开奖] 抽奖ID={lottery.id}开奖失败")
                    
        except Exception as e:
            logger.error(f"[自动开奖] 检查开奖任务时出错: {e}\n{traceback.format_exc()}")
    
    async def draw_lottery(self, lottery_id, specified_winners=None):
        """
        执行抽奖开奖操作
        
        参数:
        lottery_id: 抽奖ID
        specified_winners: 指定的中奖者ID列表，如果提供则使用手动指定中奖者模式
        
        返回:
        bool: 是否成功开奖
        """
        try:
            # 获取抽奖信息
            @sync_to_async
            def get_lottery_with_participants():
                try:
                    # 使用prefetch_related和select_related预加载相关对象
                    lottery = Lottery.objects.select_related('group', 'creator').get(id=lottery_id)
                    # 获取所有参与者，同时预加载user关系
                    participants = list(Participant.objects.filter(lottery=lottery, is_winner=False).select_related('user'))
                    # 获取所有奖品
                    prizes = list(Prize.objects.filter(lottery=lottery).order_by('order'))
                    
                    # 在同步环境下预先访问关系字段，确保它们被加载
                    if lottery.group:
                        group_id = lottery.group.group_id
                        group_title = lottery.group.group_title
                        logger.info(f"[抽奖开奖] 预加载群组信息: ID={group_id}, 标题={group_title}")
                    
                    return lottery, participants, prizes
                except Lottery.DoesNotExist:
                    logger.error(f"[抽奖开奖] 抽奖ID={lottery_id}不存在")
                    return None, [], []
                except Exception as e:
                    logger.error(f"[抽奖开奖] 获取抽奖信息时出错: {e}\n{traceback.format_exc()}")
                    return None, [], []
                    
            lottery, participants, prizes = await get_lottery_with_participants()
            
            if not lottery:
                logger.error(f"[抽奖开奖] 无法获取抽奖ID={lottery_id}的信息")
                return False
                
            if lottery.status != 'ACTIVE':
                logger.warning(f"[抽奖开奖] 抽奖ID={lottery_id}不是活跃状态，无法开奖")
                return False
                
            # 参与人数检查
            if not participants:
                logger.warning(f"[抽奖开奖] 抽奖ID={lottery_id}没有参与者，无法开奖")
                
                # 更新抽奖状态为已结束
                @sync_to_async
                def update_lottery_status():
                    lottery.status = 'ENDED'
                    lottery.save()
                    
                    # 添加日志
                    LotteryLog.objects.create(
                        lottery=lottery,
                        user=lottery.creator,
                        action='DRAW',
                        details=f"自动开奖：无参与者，抽奖结束"
                    )
                    
                await update_lottery_status()
                
                # 发送无人参与的通知
                try:
                    # 仅在群组中公布结果
                    if lottery.announce_results_in_group:
                        result_text = (
                            f"🎁 抽奖活动结束\n\n"
                            f"标题: {lottery.title}\n"
                            f"描述: {lottery.description}\n\n"
                            f"❗ 很遗憾，本次抽奖没有人参与，抽奖已结束。"
                        )
                        
                        # 使用sync_to_async处理群组ID获取
                        @sync_to_async
                        def get_group_id():
                            return lottery.group.group_id
                            
                        group_id = await get_group_id()
                        
                        message = await self.bot.send_message(
                            chat_id=group_id,
                            text=result_text
                        )
                        
                        # 置顶抽奖结果
                        if lottery.pin_results:
                            try:
                                # 再次使用sync_to_async处理群组ID获取
                                group_id = await get_group_id()
                                
                                await self.bot.pin_chat_message(
                                    chat_id=group_id,
                                    message_id=message.message_id
                                )
                                logger.info(f"[抽奖开奖] 已置顶无人参与的抽奖结果消息，群组ID={group_id}")
                            except Exception as e:
                                logger.error(f"[抽奖开奖] 置顶消息失败: {e}")
                        
                        # 保存结果消息ID
                        @sync_to_async
                        def save_result_message_id():
                            lottery.result_message_id = message.message_id
                            lottery.save()
                            
                        await save_result_message_id()
                except Exception as e:
                    logger.error(f"[抽奖开奖] 发送无人参与通知时出错: {e}\n{traceback.format_exc()}")
                    
                return True
                
            # 检查奖品设置
            if not prizes:
                logger.warning(f"[抽奖开奖] 抽奖ID={lottery_id}没有设置奖品，无法开奖")
                return False
                
            # 计算总中奖人数
            total_winners = sum(prize.quantity for prize in prizes)
            
            # 如果参与人数少于总中奖人数，调整中奖人数
            if len(participants) < total_winners:
                logger.warning(f"[抽奖开奖] 参与人数({len(participants)})少于中奖人数({total_winners})，将按参与人数抽取")
                # 调整奖品数量以适应参与人数
                remaining_participants = len(participants)
                for prize in prizes:
                    if remaining_participants <= 0:
                        prize.quantity = 0
                    else:
                        prize.quantity = min(prize.quantity, remaining_participants)
                        remaining_participants -= prize.quantity
            
            # 分配奖品
            winners = []
            
            if specified_winners:
                # 手动指定中奖者模式
                await self._draw_with_specified_winners(lottery, prizes, participants, specified_winners, winners)
            else:
                # 随机抽取中奖者模式
                await self._draw_randomly(lottery, prizes, participants, winners)
            
            if not winners:
                logger.warning(f"[抽奖开奖] 抽奖ID={lottery_id}没有选出中奖者")
                return False
            
            # 保存中奖信息到数据库
            @sync_to_async
            def save_winners():
                try:
                    for winner_info in winners:
                        participant = winner_info['participant']
                        prize = winner_info['prize']
                        
                        # 更新参与者信息
                        participant.is_winner = True
                        participant.prize = prize
                        participant.save()
                        
                    # 更新抽奖状态
                    lottery.status = 'ENDED'
                    lottery.save()
                    
                    # 添加日志
                    LotteryLog.objects.create(
                        lottery=lottery,
                        user=lottery.creator,
                        action='DRAW',
                        details=f"开奖完成：{len(winners)}人中奖"
                    )
                    
                    return True
                except Exception as e:
                    logger.error(f"[抽奖开奖] 保存中奖信息时出错: {e}\n{traceback.format_exc()}")
                    return False
                    
            success = await save_winners()
            if not success:
                logger.error(f"[抽奖开奖] 保存中奖信息失败")
                return False
            
            # 构建中奖结果文本
            result_text = (
                f"🎁 抽奖活动开奖结果 🎁\n\n"
                f"标题: {lottery.title}\n"
                f"描述: {lottery.description}\n\n"
                f"👥 共有 {len(participants)} 人参与\n"
                f"🏆 恭喜以下用户中奖:\n\n"
            )
            
            # 按奖品分组显示中奖者
            current_prize = None
            for winner in winners:
                if current_prize != winner['prize'].name:
                    current_prize = winner['prize'].name
                    result_text += f"\n{winner['prize_name']} ({winner['prize_desc']}):\n"
                
                result_text += f"- {winner['username']}\n"
            
            # 发送中奖通知
            try:
                # 群组公布结果
                if lottery.announce_results_in_group:
                    # 使用sync_to_async处理群组ID获取
                    @sync_to_async
                    def get_group_id():
                        return lottery.group.group_id
                        
                    @sync_to_async
                    def get_group_title():
                        return lottery.group.group_title
                        
                    group_id = await get_group_id()
                    
                    group_message = await self.bot.send_message(
                        chat_id=group_id,
                        text=result_text
                    )
                    
                    # 置顶抽奖结果
                    if lottery.pin_results:
                        try:
                            group_id = await get_group_id()
                            await self.bot.pin_chat_message(
                                chat_id=group_id,
                                message_id=group_message.message_id
                            )
                            logger.info(f"[抽奖开奖] 已置顶抽奖结果消息，群组ID={group_id}")
                        except Exception as e:
                            logger.error(f"[抽奖开奖] 置顶消息失败: {e}")
                    
                    # 保存结果消息ID
                    @sync_to_async
                    def save_result_message_id():
                        lottery.result_message_id = group_message.message_id
                        lottery.save()
                        
                    await save_result_message_id()
                
                # 私信通知中奖者
                if lottery.notify_winners_privately:
                    group_title = await get_group_title()
                    
                    for winner in winners:
                        try:
                            private_text = (
                                f"🎉 恭喜您在「{lottery.title}」抽奖中获得 {winner['prize_name']} ({winner['prize_desc']})！\n\n"
                                f"抽奖详情: {lottery.description}\n\n"
                                f"群组: {group_title}\n"
                                f"请联系群管理员领取奖品。"
                            )
                            
                            await self.bot.send_message(
                                chat_id=winner['user_id'],
                                text=private_text
                            )
                            
                            logger.info(f"[抽奖开奖] 已私信通知中奖者 {winner['username']} (ID: {winner['user_id']})")
                        except Exception as e:
                            logger.error(f"[抽奖开奖] 私信通知中奖者 {winner['username']} 时出错: {e}")
                            continue
                            
            except Exception as e:
                logger.error(f"[抽奖开奖] 发送中奖通知时出错: {e}\n{traceback.format_exc()}")
                
            logger.info(f"[抽奖开奖] 抽奖ID={lottery_id}已成功开奖，{len(winners)}人中奖")
            return True
                
        except Exception as e:
            logger.error(f"[抽奖开奖] 开奖过程中出错: {e}\n{traceback.format_exc()}")
            return False
            
    async def _draw_randomly(self, lottery, prizes, participants, winners):
        """随机抽取中奖者"""
        # 随机打乱参与者列表
        random.shuffle(participants)
        
        # 分配奖品
        remaining_participants = participants.copy()
        
        for prize in prizes:
            actual_quantity = min(prize.quantity, len(remaining_participants))
            
            if actual_quantity <= 0:
                continue
                
            # 从剩余参与者中抽取指定数量
            prize_winners = remaining_participants[:actual_quantity]
            remaining_participants = remaining_participants[actual_quantity:]
            
            # 记录中奖信息
            for participant in prize_winners:
                winners.append({
                    'participant': participant,
                    'prize': prize,
                    'user_id': participant.user.telegram_id,
                    'username': participant.user.username or participant.user.first_name,
                    'prize_name': prize.name,
                    'prize_desc': prize.description
                })
    
    async def _draw_with_specified_winners(self, lottery, prizes, participants, specified_winners, winners):
        """指定中奖者抽奖"""
        # 将参与者转换为字典，以telegram_id为键
        participants_dict = {p.user.telegram_id: p for p in participants}
        
        # 检查指定中奖者是否都在参与者列表中
        valid_specified_winners = []
        for telegram_id in specified_winners:
            if telegram_id in participants_dict:
                valid_specified_winners.append(telegram_id)
            else:
                logger.warning(f"[抽奖开奖] 指定的中奖者ID={telegram_id}不在参与者列表中")
        
        # 如果有效的指定中奖者数量大于奖品数量，则裁剪
        total_prizes = sum(prize.quantity for prize in prizes)
        if len(valid_specified_winners) > total_prizes:
            valid_specified_winners = valid_specified_winners[:total_prizes]
            logger.warning(f"[抽奖开奖] 指定的中奖者数量({len(specified_winners)})大于奖品数量({total_prizes})，已裁剪")
        
        # 如果有效的指定中奖者数量小于奖品数量，则随机抽取剩余中奖者
        remaining_participants = [p for p in participants if p.user.telegram_id not in valid_specified_winners]
        random.shuffle(remaining_participants)
        
        # 分配奖品
        # 先分配给指定中奖者
        remaining_prizes = prizes.copy()
        
        for telegram_id in valid_specified_winners:
            if not remaining_prizes:
                break
                
            prize = remaining_prizes[0]
            
            # 记录中奖信息
            participant = participants_dict[telegram_id]
            winners.append({
                'participant': participant,
                'prize': prize,
                'user_id': telegram_id,
                'username': participant.user.username or participant.user.first_name,
                'prize_name': prize.name,
                'prize_desc': prize.description
            })
            
            # 更新奖品数量
            prize.quantity -= 1
            if prize.quantity <= 0:
                remaining_prizes.pop(0)
        
        # 如果还有剩余奖品，随机分配
        if remaining_prizes and remaining_participants:
            for prize in remaining_prizes:
                actual_quantity = min(prize.quantity, len(remaining_participants))
                
                if actual_quantity <= 0:
                    continue
                    
                # 从剩余参与者中抽取指定数量
                prize_winners = remaining_participants[:actual_quantity]
                remaining_participants = remaining_participants[actual_quantity:]
                
                # 记录中奖信息
                for participant in prize_winners:
                    winners.append({
                        'participant': participant,
                        'prize': prize,
                        'user_id': participant.user.telegram_id,
                        'username': participant.user.username or participant.user.first_name,
                        'prize_name': prize.name,
                        'prize_desc': prize.description
                    })
    
    async def run_scheduler(self):
        """运行定时器，定期检查需要开奖的抽奖"""
        while True:
            try:
                logger.info("[自动开奖] 开始检查需要开奖的抽奖")
                await self.check_and_draw_lotteries()
            except Exception as e:
                logger.error(f"[自动开奖] 运行定时器时出错: {e}\n{traceback.format_exc()}")
            
            # 每分钟检查一次
            await asyncio.sleep(60)
    
    async def manual_draw(self, lottery_id, specified_winners=None):
        """
        手动开奖
        
        参数:
        lottery_id: 抽奖ID
        specified_winners: 指定中奖者的telegram_id列表，如果为None则随机抽取
        
        返回:
        bool: 是否成功开奖
        """
        logger.info(f"[手动开奖] 开始手动开奖，抽奖ID={lottery_id}")
        
        if specified_winners:
            logger.info(f"[手动开奖] 使用指定中奖者模式，指定的中奖者: {specified_winners}")
        else:
            logger.info(f"[手动开奖] 使用随机抽取模式")
            
        return await self.draw_lottery(lottery_id, specified_winners)

# 提供一个初始化抽奖开奖器的函数，便于在telegram_bot.py中调用
async def start_lottery_drawer(bot):
    """
    启动抽奖开奖器
    
    参数:
    bot: Telegram机器人实例
    """
    drawer = LotteryDrawer(bot)
    
    # 创建定时任务，不阻塞主线程
    asyncio.create_task(drawer.run_scheduler())
    
    logger.info("[抽奖开奖器] 抽奖开奖定时任务已启动")
    
    return drawer

# 创建一个线程安全的单例模式，确保抽奖开奖器只被初始化一次
_drawer_instance = None
_drawer_lock = threading.Lock()

def get_drawer_instance(bot=None):
    """
    获取抽奖开奖器实例
    
    参数:
    bot: 可选，Telegram机器人实例。仅在第一次调用时需要提供。
    
    返回:
    LotteryDrawer: 抽奖开奖器实例
    """
    global _drawer_instance
    if _drawer_instance is None:
        with _drawer_lock:
            if _drawer_instance is None:
                if bot is None:
                    raise ValueError("首次初始化抽奖开奖器时必须提供bot参数")
                # 创建事件循环
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # 创建抽奖开奖器实例并启动
                _drawer_instance = loop.run_until_complete(start_lottery_drawer(bot))
                logger.info("[抽奖开奖器] 成功初始化抽奖开奖器单例")
    
    return _drawer_instance

# 为Django应用提供的初始化函数
def initialize_lottery_drawer_for_django(bot):
    """
    为Django应用初始化抽奖开奖器
    
    参数:
    bot: Telegram机器人实例
    
    返回:
    bool: 是否成功初始化
    """
    try:
        # 使用线程安全的方式获取抽奖开奖器实例
        drawer = get_drawer_instance(bot)
        return True
    except Exception as e:
        logger.error(f"[抽奖开奖器] 在Django中初始化抽奖开奖器时出错: {e}\n{traceback.format_exc()}")
        return False 