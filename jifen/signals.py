import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

# 可以在这里添加Django信号处理器，用于处理数据库事件
# 例如，当积分变动时，可以发送通知给用户

logger = logging.getLogger(__name__) 