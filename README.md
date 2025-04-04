# Telegram积分抽奖机器人

一个基于Django和python-telegram-bot的Telegram群组积分系统，支持签到、发言、邀请获取积分，以及抽奖功能。

## 功能特点

- 签到获取积分
- 发言获取积分
- 邀请用户获取积分
- 积分排行榜
- 积分抽奖活动

## 安装步骤

1. 安装依赖包：

```bash
pip install -r requirements.txt
```

2. 配置数据库（默认使用MySQL）：

```bash
python manage.py migrate
```

3. 启动服务：

只需要一个命令同时启动Django和Telegram机器人：

```bash
python manage.py runserver
```

机器人将在Django启动的同时自动在后台启动。

或者，如果您想分别启动两个服务，可以使用批处理文件：

```bash
run_bot.bat
```

或者手动分别启动：

```bash
# 一个命令行窗口启动Django
python manage.py runserver

# 另一个命令行窗口启动机器人
python telegram_bot.py
```

## 使用方法

在Telegram中搜索您的机器人，并发送 `/start` 命令开始使用。

机器人菜单功能：
- 查询积分 - 查看您在当前群组中的积分
- 每日签到 - 执行每日签到获取积分
- 积分排行 - 查看群组积分排行榜
- 参与抽奖 - 查看并参与当前的抽奖活动
- 帮助说明 - 获取机器人使用帮助

## 开发者信息

本项目基于Django 3.2和python-telegram-bot 20.4开发。 