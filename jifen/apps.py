from django.apps import AppConfig
import threading
import os


class JifenConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'jifen'
    
    def ready(self):
        # 只在主进程中启动机器人，避免在Django自动重载时重复启动
        import os
        if os.environ.get('RUN_MAIN', None) != 'true':
            return
            
        # 导入信号处理器
        from jifen import signals
        
        # 在单独的线程中启动Telegram机器人
        from telegram_bot import run_bot
        bot_thread = threading.Thread(target=run_bot)
        bot_thread.daemon = True  # 设置为守护线程，当主进程退出时，此线程也会退出
        bot_thread.start()
        print("Telegram机器人后台线程已启动!")
