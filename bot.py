import asyncio
from telethon import TelegramClient, events
import os
import logging
import json
from telegram import Bot

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()  # 确保日志输出到标准输出
    ]
)
logger = logging.getLogger(__name__)

# 从配置文件读取配置
def load_config():
    config_file_path = os.environ.get('CONFIG_FILE_PATH', '/app/config.json')
    try:
        with open(config_file_path, 'r') as config_file:
            return json.load(config_file)
    except Exception as e:
        logger.error(f"读取配置文件出错: {e}")
        raise

config = load_config()

# 从配置文件获取配置
API_ID = config.get('API_ID')
API_HASH = config.get('API_HASH')
SOURCE_CHAT_IDS = list(map(int, config.get('SOURCE_CHAT_IDS', [])))  # 默认为空列表
TARGET_CHAT_ID = config.get('TARGET_CHAT_ID')
BOT_TOKEN = config.get('BOT_TOKEN')
BOT_TO_MONITOR_USERNAME = config.get('BOT_TO_MONITOR_USERNAME')  # 要监控的 bot 的用户名
BOT_MONITORING_CHAT_ID = config.get('BOT_MONITORING_CHAT_ID')  # 监控 bot 的特定群组 ID

# 设置会话文件路径
SESSION_FILE = config.get('SESSION_FILE', '/app/sessions/session_name')

# 创建 Telegram 客户端
user_client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

# 创建机器人客户端
bot = Bot(BOT_TOKEN)

@user_client.on(events.NewMessage(chats=SOURCE_CHAT_IDS))
async def handler(event):
    # 获取消息文本
    message_text = event.message.text
    if not message_text:
        logger.info("收到非文本消息，跳过复制")
        return

    # 检查消息是否来自指定的 bot 和指定的群组
    sender = await event.get_sender()
    chat_id = str(event.chat_id)  # 将 chat_id 转换为字符串以便与配置文件中的值比较

    # 如果是需要监控 bot 的特定群组
    if chat_id == BOT_MONITORING_CHAT_ID:
        if sender.username != BOT_TO_MONITOR_USERNAME:
            logger.info(f"消息不是来自指定的 bot({BOT_TO_MONITOR_USERNAME})，跳过复制")
            return
    # 如果不是需要监控 bot 的特定群组，则正常转发所有消息
    else:
        try:
            # 使用机器人发送消息到目标群组
            await bot.send_message(TARGET_CHAT_ID, message_text)
            logger.info(f"消息已通过机器人发送到目标群组: {message_text}")
            return  # 跳出函数不再，执行后续代码
        except Exception as e:
            logger.error(f"发送消息出错: {e}")
            return

    try:
        # 使用机器人发送消息到目标群组
        await bot.send_message(TARGET_CHAT_ID, message_text)
        logger.info(f"消息已通过机器人发送到目标群组: {message_text}")
    except Exception as e:
        logger.error(f"发送消息出错: {e}")

async def main():
    await user_client.start()
    logger.info("监控已启动")
    await user_client.run_until_disconnected()

if __name__ == "__main__":
    with user_client:
        user_client.loop.run_until_complete(main())