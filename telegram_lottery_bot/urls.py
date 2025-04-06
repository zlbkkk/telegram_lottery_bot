"""telegram_lottery_bot URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.http import HttpResponse
import logging
import asyncio
from choujiang.lottery_drawer import initialize_lottery_drawer_for_django
from telegram import Bot
import threading

logger = logging.getLogger(__name__)

# 全局变量，用于跟踪抽奖开奖器是否已初始化
lottery_drawer_initialized = False
init_lock = threading.Lock()

# 视图函数，用于手动触发抽奖开奖器初始化
def initialize_lottery_drawer_view(request):
    global lottery_drawer_initialized
    
    with init_lock:
        if lottery_drawer_initialized:
            return HttpResponse("抽奖开奖器已经初始化过了")
        
        try:
            # 导入机器人Token
            from telegram_bot import TOKEN
            bot = Bot(token=TOKEN)
            
            # 使用新的初始化函数
            success = initialize_lottery_drawer_for_django(bot)
            
            if success:
                lottery_drawer_initialized = True
                logger.info("抽奖开奖器初始化成功")
                return HttpResponse("抽奖开奖器初始化成功")
            else:
                logger.error("抽奖开奖器初始化失败")
                return HttpResponse("抽奖开奖器初始化失败")
        except Exception as e:
            logger.error(f"初始化抽奖开奖器时出错: {e}")
            return HttpResponse(f"初始化抽奖开奖器时出错: {e}")

urlpatterns = [
    path('admin/', admin.site.urls),
    path('init-lottery-drawer/', initialize_lottery_drawer_view, name='init_lottery_drawer'),
]

# 尝试在Django启动时自动初始化抽奖开奖器
try:
    logger.info("尝试在Django启动时初始化抽奖开奖器...")
    with init_lock:
        if not lottery_drawer_initialized:
            # 导入机器人Token
            from telegram_bot import TOKEN
            bot = Bot(token=TOKEN)
            
            # 使用新的初始化函数
            success = initialize_lottery_drawer_for_django(bot)
            
            if success:
                lottery_drawer_initialized = True
                logger.info("抽奖开奖器自动初始化成功")
            else:
                logger.error("抽奖开奖器自动初始化失败")
except Exception as e:
    logger.error(f"自动初始化抽奖开奖器时出错: {e}")
