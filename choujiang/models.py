from django.db import models
from django.utils import timezone
from datetime import datetime, timedelta, timezone as dt_timezone
from telegram import Bot
import telegram
from django.utils.timezone import make_aware, make_naive, is_aware

class LotteryType(models.Model):
    """抽奖类型"""
    name = models.CharField(max_length=50, verbose_name="类型名称")
    description = models.TextField(blank=True, null=True, verbose_name="类型描述")
    
    class Meta:
        verbose_name = "抽奖类型"
        verbose_name_plural = "抽奖类型"
    
    def __str__(self):
        return self.name

class Lottery(models.Model):
    """抽奖活动"""
    title = models.CharField(max_length=100, verbose_name="标题")
    description = models.TextField(blank=True, null=True, verbose_name="描述")
    group = models.ForeignKey('jifen.Group', on_delete=models.CASCADE, verbose_name="群组")
    creator = models.ForeignKey('jifen.User', on_delete=models.CASCADE, verbose_name="创建者")
    lottery_type = models.CharField(max_length=50, default='STANDARD', verbose_name="抽奖类型")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    status = models.CharField(
        max_length=20,
        choices=[
            ('DRAFT', '草稿'),
            ('ACTIVE', '进行中'),
            ('PAUSED', '已暂停'),
            ('ENDED', '已结束'),
            ('CANCELLED', '已取消')
        ],
        default='DRAFT',
        verbose_name="状态"
    )
    signup_deadline = models.DateTimeField(null=True, blank=True, verbose_name="报名截止时间")
    draw_time = models.DateTimeField(null=True, blank=True, verbose_name="开奖时间")
    auto_draw = models.BooleanField(default=True, verbose_name="自动开奖")
    notify_winners_privately = models.BooleanField(default=True, verbose_name="私信通知中奖者")
    announce_results_in_group = models.BooleanField(default=True, verbose_name="群内公布结果")
    points_required = models.IntegerField(default=0, verbose_name="参与所需积分")
    
    # 通知设置
    pin_results = models.BooleanField(default=False, verbose_name="置顶结果")
    
    # 媒体信息
    media_file_id = models.CharField(max_length=255, blank=True, null=True, verbose_name="媒体文件ID")
    media_type = models.CharField(
        max_length=10, 
        choices=[
            ('PHOTO', '图片'), 
            ('VIDEO', '视频'), 
            ('NONE', '无')
        ],
        default='NONE',
        verbose_name="媒体类型"
    )
    
    # 状态
    message_id = models.BigIntegerField(null=True, blank=True, verbose_name="抽奖消息ID")
    result_message_id = models.BigIntegerField(null=True, blank=True, verbose_name="结果消息ID")
    
    # 指定中奖者
    specified_winners = models.TextField(blank=True, null=True, verbose_name="指定中奖者ID列表", help_text="以逗号分隔的Telegram ID列表")
    
    def save(self, *args, **kwargs):
        # 使用北京时间 (UTC+8)
        beijing_tz = dt_timezone(timedelta(hours=8))
        
        # 当USE_TZ=False时，所有datetime需要是naive的
        # 获取当前北京时间，但确保是naive datetime
        now = datetime.now(beijing_tz)
        now = timezone.make_naive(now, beijing_tz) if timezone.is_aware(now) else now
        
        # 新建对象时设置创建时间
        if not self.id:
            self.created_at = now
        # 每次保存都更新更新时间
        self.updated_at = now
        
        # 确保报名截止时间和开奖时间使用北京时间但是naive datetime
        if self.signup_deadline:
            # 如果报名截止时间已经带有时区信息，将其转换为naive datetime
            if timezone.is_aware(self.signup_deadline):
                self.signup_deadline = timezone.make_naive(self.signup_deadline, beijing_tz)
            
        if self.draw_time:
            # 如果开奖时间已经带有时区信息，将其转换为naive datetime
            if timezone.is_aware(self.draw_time):
                self.draw_time = timezone.make_naive(self.draw_time, beijing_tz)
        
        # 调用父类的save方法
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "抽奖活动"
        verbose_name_plural = "抽奖活动"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
    
    @property
    def is_active(self):
        """判断抽奖是否进行中"""
        return self.status == 'ACTIVE'
    
    @property
    def is_ended(self):
        """判断抽奖是否已结束"""
        return self.status == 'ENDED'
    
    @property
    def can_join(self):
        """判断是否可以参与抽奖"""
        # 使用北京时间 (UTC+8)
        beijing_tz = dt_timezone(timedelta(hours=8))
        now = datetime.now(beijing_tz)
        
        # 确保报名截止时间使用北京时区
        deadline = self.signup_deadline
        if deadline and not timezone.is_aware(deadline):
            deadline = timezone.make_aware(deadline, beijing_tz)
        elif deadline:
            deadline = deadline.astimezone(beijing_tz)
            
        return self.is_active and now < deadline
    
    @property
    def should_draw(self):
        """判断是否应该开奖"""
        # 使用北京时间 (UTC+8)
        beijing_tz = dt_timezone(timedelta(hours=8))
        now = datetime.now(beijing_tz)
        
        # 确保开奖时间使用北京时区
        draw_time = self.draw_time
        if draw_time and not timezone.is_aware(draw_time):
            draw_time = timezone.make_aware(draw_time, beijing_tz)
        elif draw_time:
            draw_time = draw_time.astimezone(beijing_tz)
            
        return self.is_active and self.auto_draw and now >= draw_time

class LotteryRequirement(models.Model):
    """抽奖参与条件"""
    TYPE_CHOICES = [
        ('CHANNEL', '关注频道'),
        ('GROUP', '加入群组'),
        ('REGISTRATION_TIME', '账号注册时间'),
        ('NONE', '无条件'),
    ]
    
    lottery = models.ForeignKey(Lottery, on_delete=models.CASCADE, related_name="requirements", verbose_name="所属抽奖")
    requirement_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="条件类型")
    channel_username = models.CharField(max_length=100, blank=True, null=True, verbose_name="频道用户名")
    channel_id = models.BigIntegerField(blank=True, null=True, verbose_name="频道ID")
    group_username = models.CharField(max_length=100, blank=True, null=True, verbose_name="群组用户名")
    group_id = models.BigIntegerField(blank=True, null=True, verbose_name="群组ID")
    min_registration_days = models.IntegerField(default=0, verbose_name="最小注册天数")
    
    # 保留chat_identifier字段用于输入
    chat_identifier = models.CharField(max_length=255, blank=True, null=True, verbose_name="聊天标识符")
    
    def save(self, *args, **kwargs):
        """保存方法，不再尝试调用Telegram API"""
        print(f"LotteryRequirement.save() 被调用，chat_identifier={self.chat_identifier}")
        
        # 不再尝试调用Telegram API，直接保存
        print("调用父类的 save() 方法")
        super().save(*args, **kwargs)
        print(f"保存完成，requirement_type={self.requirement_type}")

    async def set_chat_link_async(self, link):
        """
        异步方法：设置聊天链接并自动判断类型
        
        参数:
        link: 频道或群组链接
        
        返回:
        (bool, str): (是否成功设置, 错误信息)
        """
        print(f"set_chat_link_async 被调用，link={link}")
        
        if not link:
            return False, "请提供有效的频道或群组链接"
        
        # 设置chat_identifier
        self.chat_identifier = link
        
        # 清理标识符用于设置其他字段
        identifier = link.strip()
        # 修复格式问题：处理各种链接格式
        if identifier.startswith('@https://t.me/'):
            identifier = identifier[14:]  # 直接提取用户名部分
            print(f"移除 @https://t.me/ 前缀，结果: {identifier}")
        elif identifier.startswith('https://t.me/'):
            identifier = identifier[13:]
            print(f"移除 https://t.me/ 前缀，结果: {identifier}")
        elif identifier.startswith('@'):
            identifier = identifier[1:]
            print(f"移除 @ 前缀，结果: {identifier}")
        
        if '/' in identifier:
            identifier = identifier.split('/')[0]
            print(f"移除路径，结果: {identifier}")
        
        print(f"最终处理的标识符: {identifier}")
        
        # 默认设置为群组类型
        self.requirement_type = 'GROUP'
        self.group_username = identifier
        self.group_id = 0  # 暂时设置为0
        self.channel_id = None
        self.channel_username = None
        
        # 使用异步方式保存
        from asgiref.sync import sync_to_async
        await sync_to_async(self.save)()
        
        return True, None

    def set_chat_link(self, link):
        """
        同步方法：设置聊天链接并自动判断类型（仅用于同步环境）
        
        参数:
        link: 频道或群组链接
        
        返回:
        bool: 是否成功设置
        """
        print(f"set_chat_link 被调用，link={link}")
        
        if not link:
            return False
        
        # 设置chat_identifier
        self.chat_identifier = link
        
        # 清理chat_identifier
        identifier = link.strip()
        if identifier.startswith('@https://t.me/'):
            identifier = identifier[14:]  # 直接提取用户名部分
        elif identifier.startswith('https://t.me/'):
            identifier = identifier[13:]
        elif identifier.startswith('@'):
            identifier = identifier[1:]
        if '/' in identifier:
            identifier = identifier.split('/')[0]
        
        # 直接设置字段，不调用API
        # 这里我们假设它是频道，后续会在save()方法中通过API验证
        self.requirement_type = 'CHANNEL'
        self.channel_username = identifier
        self.channel_id = 0
        self.group_id = None
        self.group_username = None
        
        # 保存，让save()方法处理API调用
        self.save()
        return True

    class Meta:
        verbose_name = "抽奖条件"
        verbose_name_plural = "抽奖条件"
    
    def __str__(self):
        if self.requirement_type == 'CHANNEL':
            display_name = self.channel_username or self.channel_id
            return f"关注频道: {display_name}"
        elif self.requirement_type == 'GROUP':
            display_name = self.group_username or self.group_id
            return f"加入群组: {display_name}"
        elif self.requirement_type == 'REGISTRATION_TIME':
            return f"账号注册时间: {self.min_registration_days}天以上"
        else:
            return "无条件参与"

class Prize(models.Model):
    """奖品"""
    lottery = models.ForeignKey(Lottery, on_delete=models.CASCADE, related_name="prizes", verbose_name="所属抽奖")
    name = models.CharField(max_length=100, verbose_name="奖项名称")  # 如：一等奖、特等奖
    description = models.TextField(verbose_name="奖品内容")  # 如：iPhone 15 Pro一台
    quantity = models.IntegerField(default=1, verbose_name="中奖人数")
    image = models.CharField(max_length=255, blank=True, null=True, verbose_name="奖品图片")
    order = models.IntegerField(default=0, verbose_name="显示顺序")  # 数值越小越靠前
    
    class Meta:
        verbose_name = "奖品"
        verbose_name_plural = "奖品"
        ordering = ['order']
    
    def __str__(self):
        return f"{self.name}: {self.description} ({self.quantity}名)"

class Participant(models.Model):
    """抽奖参与者"""
    lottery = models.ForeignKey(Lottery, on_delete=models.CASCADE, related_name="participants", verbose_name="所属抽奖")
    user = models.ForeignKey('jifen.User', on_delete=models.CASCADE, related_name="participations", verbose_name="参与用户")
    joined_at = models.DateTimeField(verbose_name="参与时间")
    is_winner = models.BooleanField(default=False, verbose_name="是否中奖")
    prize = models.ForeignKey(Prize, on_delete=models.SET_NULL, null=True, blank=True, related_name="winners", verbose_name="获得奖品")
    points_spent = models.IntegerField(default=0, verbose_name="消耗积分")
    
    def save(self, *args, **kwargs):
        # 新建对象时设置参与时间
        if not self.id:
            self.joined_at = datetime.now()
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "参与者"
        verbose_name_plural = "参与者"
        unique_together = ['lottery', 'user']  # 一个用户只能参与一次同一个抽奖
    
    def __str__(self):
        return f"{self.user} - {self.lottery}"

class LotteryLog(models.Model):
    """抽奖日志"""
    ACTION_CHOICES = [
        ('CREATE', '创建抽奖'),
        ('UPDATE', '更新抽奖'),
        ('JOIN', '参与抽奖'),
        ('DRAW', '开奖'),
        ('CANCEL', '取消抽奖'),
    ]
    
    lottery = models.ForeignKey(Lottery, on_delete=models.CASCADE, related_name="logs", verbose_name="抽奖活动")
    user = models.ForeignKey('jifen.User', on_delete=models.CASCADE, related_name="lottery_logs", verbose_name="操作用户")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="操作类型")
    timestamp = models.DateTimeField(verbose_name="操作时间")
    details = models.TextField(blank=True, null=True, verbose_name="详细信息")
    
    def save(self, *args, **kwargs):
        # 新建对象时设置操作时间
        if not self.id:
            self.timestamp = datetime.now()
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "抽奖日志"
        verbose_name_plural = "抽奖日志"
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.get_action_display()} - {self.lottery.title}"
