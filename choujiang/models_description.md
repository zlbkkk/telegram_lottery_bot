# 抽奖模块数据库设计文档

本文档详细描述了Telegram抽奖机器人中抽奖模块的数据库结构设计，包括表结构、字段说明和表之间的关系。

## 数据库表概览

1. `LotteryType` - 抽奖类型表
2. `Lottery` - 抽奖活动表
3. `LotteryRequirement` - 抽奖参与条件表
4. `Prize` - 奖品表
5. `Participant` - 抽奖参与者表
6. `LotteryLog` - 抽奖日志表

## 表结构详细说明

### 1. 抽奖类型表 (LotteryType)

存储系统支持的抽奖类型信息。

```python
class LotteryType(models.Model):
    name = models.CharField(max_length=50, verbose_name="类型名称")
    description = models.TextField(blank=True, null=True, verbose_name="类型描述")
```

**主要字段说明**：
- `name`: 类型名称，如"常规抽奖"、"积分抽奖"等
- `description`: 类型描述，对此类型抽奖的说明

### 2. 抽奖活动表 (Lottery)

存储抽奖活动的基本信息。

```python
class Lottery(models.Model):
    title = models.CharField(max_length=100, verbose_name="标题")
    description = models.TextField(blank=True, null=True, verbose_name="描述")
    group = models.ForeignKey('jifen.Group', on_delete=models.CASCADE, verbose_name="群组")
    creator = models.ForeignKey('jifen.User', on_delete=models.CASCADE, verbose_name="创建者")
    lottery_type = models.ForeignKey(LotteryType, on_delete=models.CASCADE, verbose_name="抽奖类型")
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
    pin_results = models.BooleanField(default=False, verbose_name="置顶结果")
    message_id = models.BigIntegerField(null=True, blank=True, verbose_name="抽奖消息ID")
    result_message_id = models.BigIntegerField(null=True, blank=True, verbose_name="结果消息ID")
```

**主要字段说明**：
- `title`: 抽奖标题，如"周末大抽奖"、"新品上市庆祝抽奖"
- `description`: 抽奖描述，可包含活动背景、规则说明等
- `group`: 关联的群组ID，表示此抽奖活动所属的群组
- `creator`: 创建者用户ID，表示创建此抽奖活动的用户
- `lottery_type`: 抽奖类型，关联到LotteryType表
- `created_at`: 创建时间，记录抽奖活动的创建时间
- `updated_at`: 更新时间，记录抽奖活动的最后更新时间
- `status`: 抽奖状态，包括'DRAFT'(草稿)、'ACTIVE'(进行中)、'PAUSED'(已暂停)、'ENDED'(已结束)、'CANCELLED'(已取消)
- `signup_deadline`: 报名截止时间，用户可以参与抽奖的最后时间
- `draw_time`: 开奖时间，系统自动开奖的时间
- `auto_draw`: 是否自动开奖，True表示到时间自动开奖，False表示需手动开奖
- `notify_winners_privately`: 是否私信通知中奖者
- `announce_results_in_group`: 是否在群组内公布结果
- `pin_results`: 是否置顶结果消息
- `message_id`: 抽奖消息ID，记录发布抽奖公告的消息ID
- `result_message_id`: 抽奖结果消息ID，记录发布抽奖结果的消息ID

**属性方法**：
- `is_active`: 判断抽奖是否进行中
- `is_ended`: 判断抽奖是否已结束
- `can_join`: 判断当前是否可以参与抽奖
- `should_draw`: 判断是否应该进行开奖

### 3. 抽奖参与条件表 (LotteryRequirement)

存储参与抽奖需要满足的条件。

```python
class LotteryRequirement(models.Model):
    TYPE_CHOICES = [
        ('CHANNEL', '关注频道'),
        ('GROUP', '加入群组'),
        ('REGISTRATION_TIME', '账号注册时间'),
        ('NONE', '无条件'),
    ]
    
    lottery = models.ForeignKey(Lottery, on_delete=models.CASCADE, related_name="requirements")
    requirement_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    channel_username = models.CharField(max_length=100, blank=True, null=True)
    channel_id = models.BigIntegerField(blank=True, null=True)
    group_username = models.CharField(max_length=100, blank=True, null=True)
    group_id = models.BigIntegerField(blank=True, null=True)
    min_registration_days = models.IntegerField(default=0)
    chat_identifier = models.CharField(max_length=255, blank=True, null=True)
```

**主要字段说明**：
- `lottery`: 关联的抽奖ID，表示此条件属于哪个抽奖活动
- `requirement_type`: 条件类型，包括'CHANNEL'(关注频道)、'GROUP'(加入群组)、'REGISTRATION_TIME'(账号注册时间)、'NONE'(无条件)
- `channel_username`: 频道用户名，当条件类型为'CHANNEL'时使用
- `channel_id`: 频道ID，当条件类型为'CHANNEL'时使用
- `group_username`: 群组用户名，当条件类型为'GROUP'时使用
- `group_id`: 群组ID，当条件类型为'GROUP'时使用
- `min_registration_days`: 最小注册天数，当条件类型为'REGISTRATION_TIME'时使用
- `chat_identifier`: 聊天标识符，用户输入的原始频道/群组链接或ID

**方法**：
- `set_chat_link_async`: 异步设置聊天链接并自动判断类型
- `set_chat_link`: 同步方法，设置聊天链接并自动判断类型

### 4. 奖品表 (Prize)

存储抽奖活动中的奖品信息。

```python
class Prize(models.Model):
    lottery = models.ForeignKey(Lottery, on_delete=models.CASCADE, related_name="prizes")
    name = models.CharField(max_length=100, verbose_name="奖项名称")
    description = models.TextField(verbose_name="奖品内容")
    quantity = models.IntegerField(default=1, verbose_name="中奖人数")
    image = models.CharField(max_length=255, blank=True, null=True, verbose_name="奖品图片")
    order = models.IntegerField(default=0, verbose_name="显示顺序")
```

**主要字段说明**：
- `lottery`: 关联的抽奖ID，表示此奖品属于哪个抽奖活动
- `name`: 奖项名称，如"一等奖"、"特等奖"等
- `description`: 奖品内容，如"iPhone 15 Pro一台"
- `quantity`: 中奖人数，表示该奖项将会有多少获奖者
- `image`: 奖品图片，存储奖品图片的路径或URL
- `order`: 显示顺序，数值越小越靠前显示

### 5. 抽奖参与者表 (Participant)

记录用户参与抽奖的情况。

```python
class Participant(models.Model):
    lottery = models.ForeignKey(Lottery, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey('jifen.User', on_delete=models.CASCADE, related_name="participations")
    joined_at = models.DateTimeField(verbose_name="参与时间")
    is_winner = models.BooleanField(default=False, verbose_name="是否中奖")
    prize = models.ForeignKey(Prize, on_delete=models.SET_NULL, null=True, blank=True, related_name="winners")
```

**主要字段说明**：
- `lottery`: 关联的抽奖ID，表示参与的是哪个抽奖活动
- `user`: 参与用户ID，表示哪个用户参与了抽奖
- `joined_at`: 参与时间，记录用户参与抽奖的时间
- `is_winner`: 是否中奖，标记用户是否被选为中奖者
- `prize`: 获得奖品，关联到Prize表，表示用户获得了哪个奖品（如果中奖）

### 6. 抽奖日志表 (LotteryLog)

记录抽奖活动中的各种操作日志。

```python
class LotteryLog(models.Model):
    ACTION_CHOICES = [
        ('CREATE', '创建抽奖'),
        ('UPDATE', '更新抽奖'),
        ('JOIN', '参与抽奖'),
        ('DRAW', '开奖'),
        ('CANCEL', '取消抽奖'),
    ]
    
    lottery = models.ForeignKey(Lottery, on_delete=models.CASCADE, related_name="logs")
    user = models.ForeignKey('jifen.User', on_delete=models.CASCADE, related_name="lottery_logs")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(verbose_name="操作时间")
    details = models.TextField(blank=True, null=True, verbose_name="详细信息")
```

**主要字段说明**：
- `lottery`: 关联的抽奖ID，表示此日志属于哪个抽奖活动
- `user`: 操作用户ID，表示执行操作的用户
- `action`: 操作类型，包括'CREATE'(创建抽奖)、'UPDATE'(更新抽奖)、'JOIN'(参与抽奖)、'DRAW'(开奖)、'CANCEL'(取消抽奖)
- `timestamp`: 操作时间，记录操作发生的时间
- `details`: 详细信息，记录操作的具体内容或结果

## 表关系图

```
Groups ◄─────── Users ◄────┐
  ▲               ▲         │
  │               │         │
  │               │         │
Lottery ◄───── Creator      │
  ▲  │                      │
  │  │                      │
  │  │                      │
  │  ├─────► LotteryRequirement
  │  │                      │
  │  │                      │
  │  ├─────► Prize          │
  │  │         ▲            │
  │  │         │            │
  │  │         │            │
  │  └─────► Participant ◄──┘
  │             │
  │             │
LotteryType     │
  ▲             │
  │             │
  │             │
  └─────── LotteryLog
```

## 数据流程说明

1. **创建抽奖**：
   - 管理员在群组中创建抽奖活动，设置标题、描述
   - 系统记录创建者、群组信息，生成Lottery记录
   - 创建者可以设置参与条件(LotteryRequirement)，例如需要关注特定频道

2. **参与抽奖**：
   - 用户在群组中参与抽奖
   - 系统检查用户是否满足参与条件
   - 创建Participant记录，记录参与情况

3. **开奖流程**：
   - 到达开奖时间或手动触发开奖
   - 系统从参与者中随机选择中奖者
   - 更新Participant记录中的is_winner字段
   - 生成并发送开奖结果消息

## 数据库设计特点

1. **灵活的抽奖类型**：通过LotteryType表支持多种抽奖模式
2. **完善的条件设置**：LotteryRequirement表支持多种参与条件类型
3. **详细的奖品管理**：Prize表支持设置多个不同等级的奖品
4. **全面的日志记录**：LotteryLog表记录抽奖全生命周期的操作
5. **状态追踪**：Lottery表的status字段追踪抽奖活动的当前状态
6. **丰富的辅助方法**：各表提供多种实用的属性方法，简化业务逻辑实现

这套数据库设计能够满足Telegram抽奖机器人的各种抽奖功能需求，支持从创建、参与到开奖的完整流程，具有良好的扩展性和可维护性。 