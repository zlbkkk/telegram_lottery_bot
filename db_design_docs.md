# Telegram抽奖机器人数据库设计文档

本文档详细描述了Telegram抽奖机器人的数据库结构设计，包括表结构、字段说明和表之间的关系。

## 数据库表概览

1. `groups` - 群组信息表
2. `users` - 用户信息表
3. `point_rules` - 积分规则表
4. `checkins` - 签到记录表
5. `message_points` - 发言积分记录表
6. `daily_message_stats` - 发言每日统计表
7. `invites` - 邀请记录表
8. `daily_invite_stats` - 邀请每日统计表
9. `point_transactions` - 积分变动记录表
10. `raffles` - 抽奖活动表
11. `subscription_requirements` - 关注要求表
12. `raffle_participants` - 抽奖参与记录表

## 表结构详细说明

### 1. 群组表 (groups)

存储机器人加入的Telegram群组信息。

```sql
CREATE TABLE `groups` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `group_id` bigint NOT NULL COMMENT 'Telegram群组ID',
  `group_title` varchar(255) DEFAULT NULL COMMENT '群组名称',
  `group_type` enum('GROUP','SUPERGROUP','CHANNEL') NOT NULL COMMENT '群组类型',
  `member_count` int DEFAULT NULL COMMENT '成员数量',
  `is_active` tinyint(1) NOT NULL DEFAULT 1 COMMENT '是否激活',
  `bot_is_admin` tinyint(1) NOT NULL DEFAULT 0 COMMENT '机器人是否为管理员',
  `joined_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '机器人加入时间',
  `last_activity` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后活动时间',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_group_id` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='群组信息表';
```

**主要字段说明**：
- `group_id`: Telegram群组的唯一标识
- `group_title`: 群组名称
- `group_type`: 群组类型(普通群组、超级群组或频道)
- `bot_is_admin`: 标记机器人是否在该群组中拥有管理员权限
- `is_active`: 标记群组是否处于活跃状态

### 2. 用户表 (users)

存储与机器人交互的用户信息及其所在群组。每个用户在每个群组中都有一条记录。

```sql
CREATE TABLE `users` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `telegram_id` bigint NOT NULL COMMENT 'Telegram用户ID',
  `username` varchar(64) DEFAULT NULL COMMENT 'Telegram用户名',
  `first_name` varchar(64) DEFAULT NULL,
  `last_name` varchar(64) DEFAULT NULL,
  `group_id` bigint NOT NULL COMMENT '用户所在群组ID',
  `points` int NOT NULL DEFAULT 0 COMMENT '在该群组中的积分',
  `is_admin` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否为管理员',
  `is_active` tinyint(1) NOT NULL DEFAULT 1 COMMENT '是否在群组中活跃',
  `joined_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_telegram_id_group` (`telegram_id`, `group_id`),
  KEY `idx_group_id` (`group_id`),
  KEY `idx_telegram_id` (`telegram_id`),
  CONSTRAINT `fk_user_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户信息表';
```

**主要字段说明**：
- `telegram_id`: Telegram用户的唯一标识
- `username`: 用户的Telegram用户名
- `group_id`: 用户所在的群组ID
- `points`: 用户在该群组中的积分
- `is_admin`: 标记用户是否为管理员
- `is_active`: 标记用户在该群组中是否活跃

**关系**：
- 通过`group_id`与`groups`表关联

### 3. 积分规则表 (point_rules)

存储每个群组的积分规则配置。

```sql
CREATE TABLE `point_rules` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `group_id` bigint NOT NULL COMMENT '群组ID',
  
  /* 签到规则 */
  `checkin_keyword` varchar(50) NOT NULL DEFAULT '签到' COMMENT '签到关键词',
  `checkin_points` int NOT NULL DEFAULT 5 COMMENT '签到获得积分',
  
  /* 发言规则 */
  `message_points_enabled` tinyint(1) NOT NULL DEFAULT 1 COMMENT '是否启用发言积分',
  `message_points` int NOT NULL DEFAULT 1 COMMENT '每条消息获得积分',
  `message_daily_limit` int NOT NULL DEFAULT 50 COMMENT '每日发言积分上限',
  `message_min_length` int NOT NULL DEFAULT 0 COMMENT '发言最小字数长度限制，0表示无限制',
  
  /* 邀请规则 */
  `invite_points_enabled` tinyint(1) NOT NULL DEFAULT 1 COMMENT '是否启用邀请积分',
  `invite_points` int NOT NULL DEFAULT 10 COMMENT '邀请一人获得积分',
  `invite_daily_limit` int NOT NULL DEFAULT 0 COMMENT '每日邀请积分上限，0表示无限制',
  
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_group_id` (`group_id`),
  CONSTRAINT `fk_rules_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='积分规则表';
```

**主要字段说明**：
- `group_id`: 关联的群组ID
- `checkin_keyword`: 触发签到的关键词
- `checkin_points`: 签到获得的积分
- `message_points_enabled`: 是否启用发言积分
- `message_points`: 每条消息获得的积分
- `message_daily_limit`: 每日发言积分上限
- `message_min_length`: 发言最小字数长度限制
- `invite_points_enabled`: 是否启用邀请积分
- `invite_points`: 邀请一个新成员获得的积分
- `invite_daily_limit`: 每日邀请积分上限，0表示无限制

**关系**：
- 通过`group_id`与`groups`表关联，使用级联删除

### 4. 签到记录表 (checkins)

记录用户的签到情况。

```sql
CREATE TABLE `checkins` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `group_id` bigint NOT NULL COMMENT '群组ID',
  `points_awarded` int NOT NULL DEFAULT 0 COMMENT '获得积分',
  `checkin_date` date NOT NULL COMMENT '签到日期',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_user_group_date` (`user_id`, `group_id`, `checkin_date`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_group_id` (`group_id`),
  KEY `idx_checkin_date` (`checkin_date`),
  CONSTRAINT `fk_checkin_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_checkin_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='签到记录表';
```

**主要字段说明**：
- `user_id`: 签到用户的ID
- `group_id`: 签到群组的ID
- `points_awarded`: 签到获得的积分
- `checkin_date`: 签到日期

**关系**：
- 通过`user_id`与`users`表关联
- 通过`group_id`与`groups`表关联

### 5. 发言积分记录表 (message_points)

记录用户因发言获得积分的情况。

```sql
CREATE TABLE `message_points` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `group_id` bigint NOT NULL COMMENT '群组ID',
  `message_id` bigint NOT NULL COMMENT '消息ID',
  `points_awarded` int NOT NULL DEFAULT 0 COMMENT '获得积分',
  `message_date` date NOT NULL COMMENT '消息日期',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_message_id` (`message_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_group_id` (`group_id`),
  KEY `idx_message_date` (`message_date`),
  CONSTRAINT `fk_message_point_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_message_point_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='发言积分记录表';
```

**主要字段说明**：
- `user_id`: 发言用户的ID
- `group_id`: 发言群组的ID
- `message_id`: Telegram消息的ID
- `points_awarded`: 获得的积分
- `message_date`: 消息日期

**关系**：
- 通过`user_id`与`users`表关联
- 通过`group_id`与`groups`表关联

### 6. 发言每日统计表 (daily_message_stats)

统计用户每日在群组中的发言情况和积分获取。

```sql
CREATE TABLE `daily_message_stats` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `group_id` bigint NOT NULL COMMENT '群组ID',
  `message_date` date NOT NULL COMMENT '统计日期',
  `message_count` int NOT NULL DEFAULT 0 COMMENT '消息数量',
  `points_awarded` int NOT NULL DEFAULT 0 COMMENT '获得积分',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_user_group_date` (`user_id`, `group_id`, `message_date`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_group_id` (`group_id`),
  CONSTRAINT `fk_daily_stats_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_daily_stats_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='发言每日统计表';
```

**主要字段说明**：
- `user_id`: 用户ID
- `group_id`: 群组ID
- `message_date`: 统计日期
- `message_count`: 当日发言数量
- `points_awarded`: 当日获得的积分总数

**关系**：
- 通过`user_id`与`users`表关联
- 通过`group_id`与`groups`表关联

### 7. 邀请记录表 (invites)

记录用户邀请新成员的情况。

```sql
CREATE TABLE `invites` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `inviter_id` bigint NOT NULL COMMENT '邀请人ID',
  `invitee_id` bigint NOT NULL COMMENT '被邀请人ID',
  `group_id` bigint NOT NULL COMMENT '群组ID',
  `points_awarded` int NOT NULL DEFAULT 0 COMMENT '获得积分',
  `invite_date` date NOT NULL COMMENT '邀请日期',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_inviter_invitee_group` (`inviter_id`, `invitee_id`, `group_id`),
  KEY `idx_inviter_id` (`inviter_id`),
  KEY `idx_group_id` (`group_id`),
  KEY `idx_invite_date` (`invite_date`),
  CONSTRAINT `fk_invite_inviter` FOREIGN KEY (`inviter_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_invite_invitee` FOREIGN KEY (`invitee_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_invite_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='邀请记录表';
```

**主要字段说明**：
- `inviter_id`: 邀请人用户ID
- `invitee_id`: 被邀请人用户ID
- `group_id`: 群组ID
- `points_awarded`: 邀请人获得的积分
- `invite_date`: 邀请日期

**关系**：
- `inviter_id`和`invitee_id`都与`users`表关联
- 通过`group_id`与`groups`表关联

### 8. 邀请每日统计表 (daily_invite_stats)

统计用户每日在群组中的邀请情况和积分获取。

```sql
CREATE TABLE `daily_invite_stats` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `group_id` bigint NOT NULL COMMENT '群组ID',
  `invite_date` date NOT NULL COMMENT '统计日期',
  `invite_count` int NOT NULL DEFAULT 0 COMMENT '邀请人数',
  `points_awarded` int NOT NULL DEFAULT 0 COMMENT '获得积分',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_user_group_date` (`user_id`, `group_id`, `invite_date`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_group_id` (`group_id`),
  CONSTRAINT `fk_daily_invite_stats_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_daily_invite_stats_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='邀请每日统计表';
```

**主要字段说明**：
- `user_id`: 用户ID
- `group_id`: 群组ID
- `invite_date`: 统计日期
- `invite_count`: 当日邀请人数
- `points_awarded`: 当日获得的积分总数

**关系**：
- 通过`user_id`与`users`表关联
- 通过`group_id`与`groups`表关联

### 9. 积分变动记录表 (point_transactions)

记录所有积分变动情况。

```sql
CREATE TABLE `point_transactions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `group_id` bigint NOT NULL COMMENT '群组ID',
  `amount` int NOT NULL COMMENT '变动数量',
  `type` enum('CHECKIN','MESSAGE','INVITE','RAFFLE_PARTICIPATION','ADMIN_ADJUST','OTHER') NOT NULL COMMENT '变动类型',
  `description` varchar(255) DEFAULT NULL COMMENT '变动描述',
  `transaction_date` date NOT NULL COMMENT '交易日期',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_group_id` (`group_id`),
  KEY `idx_type` (`type`),
  KEY `idx_transaction_date` (`transaction_date`),
  CONSTRAINT `fk_transaction_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_transaction_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='积分变动记录表';
```

**主要字段说明**：
- `user_id`: 用户ID
- `group_id`: 群组ID
- `amount`: 积分变动数量（正值为增加，负值为减少）
- `type`: 变动类型（签到、发言、邀请、参与抽奖、管理员调整等）
- `description`: 变动描述
- `transaction_date`: 交易日期

**关系**：
- 通过`user_id`与`users`表关联
- 通过`group_id`与`groups`表关联

### 10. 抽奖活动表 (raffles)

存储抽奖活动信息。

```sql
CREATE TABLE `raffles` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `group_id` bigint NOT NULL COMMENT '关联的群组ID，抽奖活动所属群组',
  `title` varchar(255) NOT NULL COMMENT '抽奖标题',
  `description` text COMMENT '抽奖描述',
  `prize_description` text NOT NULL COMMENT '奖品描述',
  `min_points` int NOT NULL DEFAULT 0 COMMENT '参与所需最低积分',
  `points_cost` int NOT NULL DEFAULT 0 COMMENT '参与消耗积分',
  `max_participants` int DEFAULT NULL COMMENT '最大参与人数，NULL表示不限',
  `winner_count` int NOT NULL DEFAULT 1 COMMENT '中奖人数',
  `raffle_type` enum('RANDOM','MANUAL') NOT NULL DEFAULT 'RANDOM' COMMENT '开奖方式：随机/手动指定',
  `open_type` enum('TIME','COUNT') NOT NULL COMMENT '开奖条件：时间/人数',
  `open_time` datetime DEFAULT NULL COMMENT '定时开奖时间',
  `open_count` int DEFAULT NULL COMMENT '满人开奖人数',
  `status` enum('PENDING','ONGOING','ENDED','CANCELLED') NOT NULL DEFAULT 'PENDING' COMMENT '抽奖状态',
  `created_by` bigint NOT NULL COMMENT '创建者用户ID',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_status` (`status`),
  KEY `idx_created_by` (`created_by`),
  KEY `idx_group_id` (`group_id`),
  CONSTRAINT `fk_raffle_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_raffle_group` FOREIGN KEY (`group_id`) REFERENCES `groups` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='抽奖活动表';
```

**主要字段说明**：
- `group_id`: 抽奖所属的群组ID
- `title`和`description`: 抽奖活动的标题和描述
- `prize_description`: 奖品描述
- `min_points`: 参与所需最低积分
- `points_cost`: 参与消耗积分
- `winner_count`: 中奖人数
- `raffle_type`: 开奖方式（随机或手动指定）
- `open_type`, `open_time`, `open_count`: 开奖条件
- `status`: 抽奖状态
- `created_by`: 创建者用户ID

**关系**：
- 通过`group_id`与`groups`表关联
- 通过`created_by`与`users`表关联

### 11. 关注要求表 (subscription_requirements)

存储参与抽奖需要关注的频道或群组。

```sql
CREATE TABLE `subscription_requirements` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `raffle_id` bigint NOT NULL COMMENT '关联的抽奖ID',
  `entity_type` enum('CHANNEL','GROUP') NOT NULL COMMENT '实体类型：频道/群组',
  `entity_id` varchar(255) NOT NULL COMMENT '频道/群组ID',
  `entity_username` varchar(64) DEFAULT NULL COMMENT '频道/群组用户名',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_raffle_id` (`raffle_id`),
  CONSTRAINT `fk_requirement_raffle` FOREIGN KEY (`raffle_id`) REFERENCES `raffles` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='抽奖关注要求表';
```

**主要字段说明**：
- `raffle_id`: 关联的抽奖ID
- `entity_type`: 实体类型（频道或群组）
- `entity_id`: 频道或群组的ID
- `entity_username`: 频道或群组的用户名

**关系**：
- 通过`raffle_id`与`raffles`表关联，使用级联删除

### 12. 抽奖参与记录表 (raffle_participants)

记录用户参与抽奖的情况。

```sql
CREATE TABLE `raffle_participants` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `raffle_id` bigint NOT NULL COMMENT '抽奖ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `points_deducted` int NOT NULL DEFAULT 0 COMMENT '扣除的积分',
  `is_winner` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否中奖',
  `join_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '参与时间',
  `selected_at` timestamp NULL DEFAULT NULL COMMENT '中奖时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_raffle_user` (`raffle_id`,`user_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_is_winner` (`is_winner`),
  CONSTRAINT `fk_participant_raffle` FOREIGN KEY (`raffle_id`) REFERENCES `raffles` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_participant_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='抽奖参与记录表';
```

**主要字段说明**：
- `raffle_id`: 抽奖ID
- `user_id`: 参与用户ID
- `points_deducted`: 参与扣除的积分
- `is_winner`: 是否被选为中奖者
- `join_time`: 参与时间
- `selected_at`: 中奖时间（为NULL表示未中奖）

**关系**：
- 通过`raffle_id`与`raffles`表关联，使用级联删除
- 通过`user_id`与`users`表关联

## 用户信息同步触发器

为确保同一用户在不同群组中的基本信息保持一致，系统使用以下触发器：

```sql
DELIMITER $$

CREATE TRIGGER `after_user_update` 
AFTER UPDATE ON `users` 
FOR EACH ROW
BEGIN
    IF OLD.username != NEW.username OR OLD.first_name != NEW.first_name OR OLD.last_name != NEW.last_name THEN
        UPDATE users 
        SET username = NEW.username, first_name = NEW.first_name, last_name = NEW.last_name 
        WHERE telegram_id = NEW.telegram_id AND id != NEW.id;
    END IF;
END$$

DELIMITER ;
```

这个触发器确保当用户的基本信息（用户名、名字、姓氏）在一个群组中更新时，其在所有其他群组中的记录也会同步更新。

## 表关系图

```
groups <---- users <---- point_transactions
   ^          ^  ^           |
   |          |  |           |
   |          |  |           v
   |          |  |        raffles <---- subscription_requirements
   |          |  |           ^
   |          |  |           |
   |          |  |           |
   |          |  |     raffle_participants
   |          |  |
   |          |  |
point_rules   |  |
   ^          |  |
   |          |  |
   |          |  |
checkins      |  |
message_points|  |
daily_message_stats
daily_invite_stats
   ^          |  |
   |          |  |
   |          |  |
   v          v  v
        invites
```

## 数据库设计总结

1. **用户管理**：通过`users`表直接记录用户在每个群组中的信息和积分
2. **积分系统**：支持签到、发言和邀请三种主要积分获取方式
   - 支持对每种积分获取方式设置细粒度的规则，如每日上限、邀请积分等
   - 通过每日统计表（`daily_message_stats`、`daily_invite_stats`）跟踪用户的每日活动
3. **抽奖功能**：可创建抽奖活动，设置参与条件，跟踪参与和中奖记录
4. **数据分析**：通过各种记录表和统计表支持用户活跃度和积分获取分析
5. **关系维护**：使用外键约束确保数据完整性，部分表使用级联删除

这套数据库设计能够满足Telegram抽奖机器人的所有功能需求，结构清晰，易于维护和扩展。通过添加邀请每日统计表和邀请每日上限字段，系统现在可以更精细地控制邀请积分的获取，防止滥用行为并提供更好的用户体验。 