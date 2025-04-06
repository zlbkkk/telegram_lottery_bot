from django.db import models
from django.utils import timezone


class Group(models.Model):
    """群组信息表"""
    
    GROUP_TYPE_CHOICES = [
        ('GROUP', '群组'),
        ('SUPERGROUP', '超级群组'),
        ('CHANNEL', '频道'),
    ]
    
    group_id = models.BigIntegerField(unique=True, help_text="Telegram群组ID")
    group_title = models.CharField(max_length=255, null=True, blank=True, help_text="群组名称")
    group_type = models.CharField(max_length=20, choices=GROUP_TYPE_CHOICES, help_text="群组类型")
    member_count = models.IntegerField(null=True, blank=True, help_text="成员数量")
    is_active = models.BooleanField(default=True, help_text="是否激活")
    bot_is_admin = models.BooleanField(default=False, help_text="机器人是否为管理员")
    joined_at = models.DateTimeField(default=timezone.now, help_text="机器人加入时间")
    last_activity = models.DateTimeField(auto_now=True, help_text="最后活动时间")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")
    
    class Meta:
        db_table = 'groups'
        verbose_name = '群组'
        verbose_name_plural = '群组'
        
    def __str__(self):
        return f"{self.group_title} ({self.group_id})"


class User(models.Model):
    """用户信息表，每个用户在每个群组中有一条记录"""
    
    telegram_id = models.BigIntegerField(help_text="Telegram用户ID")
    username = models.CharField(max_length=64, null=True, blank=True, help_text="Telegram用户名")
    first_name = models.CharField(max_length=64, null=True, blank=True, help_text="名")
    last_name = models.CharField(max_length=64, null=True, blank=True, help_text="姓")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, help_text="用户所在群组ID")
    points = models.IntegerField(default=0, help_text="在该群组中的积分")
    is_admin = models.BooleanField(default=False, help_text="是否为管理员")
    is_active = models.BooleanField(default=True, help_text="是否在群组中活跃")
    joined_at = models.DateTimeField(auto_now_add=True, help_text="加入时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")
    
    class Meta:
        db_table = 'users'
        verbose_name = '用户'
        verbose_name_plural = '用户'
        unique_together = ('telegram_id', 'group')
        indexes = [
            models.Index(fields=['telegram_id']),
            models.Index(fields=['group']),
        ]
        
    def __str__(self):
        if self.username:
            return f"@{self.username} ({self.telegram_id}) in {self.group.group_title}"
        return f"{self.first_name} {self.last_name} ({self.telegram_id}) in {self.group.group_title}"


class PointRule(models.Model):
    """积分规则表"""
    
    group = models.OneToOneField(Group, on_delete=models.CASCADE, help_text="群组ID")
    
    # 总开关
    points_enabled = models.BooleanField(default=True, help_text="总积分功能开关，控制所有积分功能")
    
    # 签到规则
    checkin_keyword = models.CharField(max_length=50, default='签到', help_text="签到关键词")
    checkin_points = models.IntegerField(default=5, help_text="签到获得积分")
    
    # 发言规则
    message_points = models.IntegerField(default=1, help_text="每条消息获得积分")
    message_daily_limit = models.IntegerField(default=50, help_text="每日发言积分上限")
    message_min_length = models.IntegerField(default=0, help_text="发言最小字数长度限制，0表示无限制")
    
    # 邀请规则
    invite_points = models.IntegerField(default=10, help_text="邀请一人获得积分")
    invite_daily_limit = models.IntegerField(default=0, help_text="每日邀请积分上限，0表示无限制")
    
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")
    
    class Meta:
        db_table = 'point_rules'
        verbose_name = '积分规则'
        verbose_name_plural = '积分规则'
        
    def __str__(self):
        return f"积分规则 - {self.group.group_title}"


class CheckIn(models.Model):
    """签到记录表"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="用户ID")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, help_text="群组ID")
    points_awarded = models.IntegerField(default=0, help_text="获得积分")
    checkin_date = models.DateField(help_text="签到日期")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    
    class Meta:
        db_table = 'checkins'
        verbose_name = '签到记录'
        verbose_name_plural = '签到记录'
        unique_together = ('user', 'group', 'checkin_date')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['group']),
            models.Index(fields=['checkin_date']),
        ]
        
    def __str__(self):
        return f"{self.user} - {self.checkin_date} - {self.points_awarded}点"


class MessagePoint(models.Model):
    """发言积分记录表"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="用户ID")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, help_text="群组ID")
    message_id = models.BigIntegerField(unique=True, help_text="消息ID")
    points_awarded = models.IntegerField(default=0, help_text="获得积分")
    message_date = models.DateField(help_text="消息日期")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    
    class Meta:
        db_table = 'message_points'
        verbose_name = '发言积分记录'
        verbose_name_plural = '发言积分记录'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['group']),
            models.Index(fields=['message_date']),
        ]
        
    def __str__(self):
        return f"{self.user} - {self.message_id} - {self.points_awarded}点"


class DailyMessageStat(models.Model):
    """发言每日统计表"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="用户ID")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, help_text="群组ID")
    message_date = models.DateField(help_text="统计日期")
    message_count = models.IntegerField(default=0, help_text="消息数量")
    points_awarded = models.IntegerField(default=0, help_text="获得积分")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")
    
    class Meta:
        db_table = 'daily_message_stats'
        verbose_name = '发言每日统计'
        verbose_name_plural = '发言每日统计'
        unique_together = ('user', 'group', 'message_date')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['group']),
        ]
        
    def __str__(self):
        return f"{self.user} - {self.message_date} - {self.message_count}条消息"


class Invite(models.Model):
    """邀请记录表"""
    
    inviter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invites_sent', help_text="邀请人ID")
    invitee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invites_received', help_text="被邀请人ID")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, help_text="群组ID")
    points_awarded = models.IntegerField(default=0, help_text="获得积分")
    invite_date = models.DateField(help_text="邀请日期")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    
    class Meta:
        db_table = 'invites'
        verbose_name = '邀请记录'
        verbose_name_plural = '邀请记录'
        unique_together = ('inviter', 'invitee', 'group')
        indexes = [
            models.Index(fields=['inviter']),
            models.Index(fields=['group']),
            models.Index(fields=['invite_date']),
        ]
        
    def __str__(self):
        return f"{self.inviter} 邀请 {self.invitee} 到 {self.group}"


class PointTransaction(models.Model):
    """积分变动记录表"""
    
    TRANSACTION_TYPE_CHOICES = [
        ('CHECKIN', '签到'),
        ('MESSAGE', '发言'),
        ('INVITE', '邀请'),
        ('RAFFLE_PARTICIPATION', '参与抽奖'),
        ('ADMIN_ADJUST', '管理员调整'),
        ('OTHER', '其他'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="用户ID")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, help_text="群组ID")
    amount = models.IntegerField(help_text="变动数量")
    type = models.CharField(max_length=30, choices=TRANSACTION_TYPE_CHOICES, help_text="变动类型")
    description = models.CharField(max_length=255, null=True, blank=True, help_text="变动描述")
    transaction_date = models.DateField(help_text="交易日期")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    
    class Meta:
        db_table = 'point_transactions'
        verbose_name = '积分变动记录'
        verbose_name_plural = '积分变动记录'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['group']),
            models.Index(fields=['type']),
            models.Index(fields=['transaction_date']),
        ]
        
    def __str__(self):
        return f"{self.user} - {self.get_type_display()} - {self.amount}点"


class Raffle(models.Model):
    """抽奖活动表"""
    
    STATUS_CHOICES = [
        ('PENDING', '待开始'),
        ('ONGOING', '进行中'),
        ('ENDED', '已结束'),
        ('CANCELLED', '已取消'),
    ]
    
    RAFFLE_TYPE_CHOICES = [
        ('RANDOM', '随机抽取'),
        ('MANUAL', '手动指定'),
    ]
    
    OPEN_TYPE_CHOICES = [
        ('TIME', '定时开奖'),
        ('COUNT', '满人开奖'),
    ]
    
    group = models.ForeignKey(Group, on_delete=models.CASCADE, help_text="关联的群组ID")
    title = models.CharField(max_length=255, help_text="抽奖标题")
    description = models.TextField(null=True, blank=True, help_text="抽奖描述")
    prize_description = models.TextField(help_text="奖品描述")
    min_points = models.IntegerField(default=0, help_text="参与所需最低积分")
    points_cost = models.IntegerField(default=0, help_text="参与消耗积分")
    max_participants = models.IntegerField(null=True, blank=True, help_text="最大参与人数")
    winner_count = models.IntegerField(default=1, help_text="中奖人数")
    raffle_type = models.CharField(max_length=20, choices=RAFFLE_TYPE_CHOICES, default='RANDOM', help_text="开奖方式")
    open_type = models.CharField(max_length=20, choices=OPEN_TYPE_CHOICES, help_text="开奖条件")
    open_time = models.DateTimeField(null=True, blank=True, help_text="定时开奖时间")
    open_count = models.IntegerField(null=True, blank=True, help_text="满人开奖人数")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', help_text="抽奖状态")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, help_text="创建者用户ID")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")
    
    class Meta:
        db_table = 'raffles'
        verbose_name = '抽奖活动'
        verbose_name_plural = '抽奖活动'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_by']),
            models.Index(fields=['group']),
        ]
        
    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"


class SubscriptionRequirement(models.Model):
    """关注要求表"""
    
    ENTITY_TYPE_CHOICES = [
        ('CHANNEL', '频道'),
        ('GROUP', '群组'),
    ]
    
    raffle = models.ForeignKey(Raffle, on_delete=models.CASCADE, related_name='subscription_requirements', help_text="关联的抽奖ID")
    entity_type = models.CharField(max_length=20, choices=ENTITY_TYPE_CHOICES, help_text="实体类型")
    entity_id = models.CharField(max_length=255, help_text="频道/群组ID")
    entity_username = models.CharField(max_length=64, null=True, blank=True, help_text="频道/群组用户名")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    
    class Meta:
        db_table = 'subscription_requirements'
        verbose_name = '关注要求'
        verbose_name_plural = '关注要求'
        indexes = [
            models.Index(fields=['raffle']),
        ]
        
    def __str__(self):
        return f"{self.get_entity_type_display()} - {self.entity_username or self.entity_id}"


class RaffleParticipant(models.Model):
    """抽奖参与记录表"""
    
    raffle = models.ForeignKey(Raffle, on_delete=models.CASCADE, related_name='participants', help_text="抽奖ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="用户ID")
    points_deducted = models.IntegerField(default=0, help_text="扣除的积分")
    is_winner = models.BooleanField(default=False, help_text="是否中奖")
    join_time = models.DateTimeField(auto_now_add=True, help_text="参与时间")
    selected_at = models.DateTimeField(null=True, blank=True, help_text="中奖时间")
    
    class Meta:
        db_table = 'raffle_participants'
        verbose_name = '抽奖参与记录'
        verbose_name_plural = '抽奖参与记录'
        unique_together = ('raffle', 'user')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['is_winner']),
        ]
        
    def __str__(self):
        status = "中奖" if self.is_winner else "参与"
        return f"{self.user} {status} {self.raffle.title}"


class DailyInviteStat(models.Model):
    """邀请每日统计表"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="用户ID")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, help_text="群组ID")
    invite_date = models.DateField(help_text="统计日期")
    invite_count = models.IntegerField(default=0, help_text="邀请人数")
    points_awarded = models.IntegerField(default=0, help_text="获得积分")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")
    
    class Meta:
        db_table = 'daily_invite_stats'
        verbose_name = '邀请每日统计'
        verbose_name_plural = '邀请每日统计'
        unique_together = ('user', 'group', 'invite_date')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['group']),
        ]
        
    def __str__(self):
        return f"{self.user} - {self.invite_date} - {self.invite_count}人" 