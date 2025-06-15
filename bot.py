import asyncio
from telethon import TelegramClient, events
import os
import logging
import json
from datetime import datetime, timedelta
import re
import hashlib
import subprocess
import time
from filelock import FileLock

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

# 监控的群组及其对应的 bot 列表
MONITORING_CHATS = config.get('MONITORING_CHATS', {})

# 设置会话文件路径
SESSION_FILE = config.get('SESSION_FILE', '/app/sessions/session_name')

# 创建 Telegram 客户端
user_client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

# 创建机器人客户端
from telegram import Bot
bot = Bot(BOT_TOKEN)

# 指定固定的文件路径，用于存储提取的文本内容
EXTRACTED_TEXT_FILE = config.get('EXTRACTED_TEXT_FILE', '/app/extracted_text.txt')

# 监控的文件路径
DYDZ_TXT_PATH = config.get('DYDZ_TXT_PATH', '/app/dydzt.txt')

# MD5 文件存储路径
MD5_FILE_PATH = config.get('MD5_FILE_PATH', '/app/dydzt.md5')

# dymb.py 文件路径
DYNB_PY_PATH = config.get('DYNB_PY_PATH', '/app/dymb.py')

# dymb.py 中的 subscriptions 数组的代码片段
DYNB_PY_SUBSCRIPTIONS_TEMPLATE = """
subscriptions = [
    {subscriptions}
]
"""

def extract_remaining_days(text):
    logger.info("开始提取剩余时间")
    
    # 正则表达式模式：匹配“剩余时间: XX天”、“剩余时间: XX天XX小时”、“剩余时间: XX天XX小时XX分”、“剩余时间: XX天XX小时XX分XX秒”
    pattern = r'剩余时间:\s*(\d+)天(?:(\d+)小时)?(?:(\d+)分)?(?:(\d+)秒)?'
    match = re.search(pattern, text)
    
    if match:
        days = int(match.group(1))
        hours = int(match.group(2)) if match.group(2) else 0
        minutes = int(match.group(3)) if match.group(3) else 0
        seconds = int(match.group(4)) if match.group(4) else 0
        
        # 转换为总天数（浮点数形式）
        total_days = days + hours / 24 + minutes / (24 * 60) + seconds / (24 * 60 * 60)
        logger.info(f"提取到剩余时间: {days}天{hours}小时{minutes}分{seconds}秒，总计{total_days:.4f}天")
        
        return total_days
    else:
        logger.info("未找到剩余时间或格式不符合要求")
        return None

def extract_links(text):
    logger.info("开始提取链接")
    logger.info(f"读取到的文件内容:\n{text}")  # 打印文件内容到日志
    
    links = []
    # 按照 "----------------------------------------" 分割文本
    entries = text.split("----------------------------------------")
    for entry in entries:
        if not entry.strip():
            continue
        
        lines = entry.strip().split('\n')
        available_gb = None
        remaining_days = None
        link = None
        
        for line in lines:
            if '剩余可用' in line:
                available_gb_str = line.split(':')[-1].strip().replace('GB', '')
                try:
                    available_gb = float(available_gb_str)
                    logger.info(f"检查剩余可用: {available_gb} GB")
                except ValueError:
                    logger.info(f"无法转换剩余可用值: {available_gb_str}")
            
            if '剩余时间' in line:
                remaining_days = extract_remaining_days(line)
            
            if '订阅链接' in line:
                link = line.split(':')[-1].strip()
                if link.startswith('//'):
                    link = 'http:' + link  # 或者使用 'https:'，根据实际情况选择
                logger.info(f"找到订阅链接: {link}")
        
        # 检查条件并添加链接
        if available_gb is not None and available_gb > 50.00 and remaining_days is not None and remaining_days > 20:
            logger.info(f"符合条件: 链接={link}, 剩余可用={available_gb} GB, 剩余时间={remaining_days:.2f}天")
            links.append(link)
        else:
            if available_gb is None:
                logger.info("剩余可用信息未找到或格式错误，跳过此条目")
            if remaining_days is None:
                logger.info("剩余时间信息未找到或格式错误，跳过此条目")
            if link is None:
                logger.info("订阅链接未找到，跳过此条目")
    
    logger.info(f"提取到的链接数量: {len(links)}")
    return links

def deduplicate_links(file_path):
    """去除文件中的重复链接"""
    if not os.path.exists(file_path):
        logger.info(f"文件 {file_path} 不存在，无需去重")
        return
    
    # 读取文件内容
    with open(file_path, 'r', encoding='utf-8') as f:
        links = f.readlines()
    
    # 去重
    unique_links = list(dict.fromkeys(links))  # 保留顺序并去重
    
    # 写回文件
    with open(file_path, 'w', encoding='utf-8') as f:
        for link in unique_links:
            f.write(link)
    
    logger.info(f"已去除文件 {file_path} 中的重复链接，最终链接数量: {len(unique_links)}")

@user_client.on(events.NewMessage(chats=SOURCE_CHAT_IDS))
async def handler(event):
    # 获取消息文本和文件
    message_text = event.message.text
    media = event.message.media

    # 检查消息是否来自指定的 bot 和指定的群组
    sender = await event.get_sender()
    chat_id = str(event.chat_id)  # 将 chat_id 转换为字符串以便与配置文件中的值比较

    # 记录消息内容
    logger.info(f"捕获到新消息: {message_text}")
    logger.info(f"消息来自群组: {chat_id}, 发送者: {sender.username}")

    # 如果是需要监控 bot 的特定群组
    if chat_id in MONITORING_CHATS:
        logger.info(f"消息来自监控的群组: {chat_id}")
        if sender.username in MONITORING_CHATS[chat_id]:
            logger.info(f"消息来自指定的 bot: {sender.username}")
            try:
                if media:
                    # 下载文件
                    file_path = await user_client.download_media(media)
                    # 通过机器人发送文件并指定文件名
                    await bot.send_document(TARGET_CHAT_ID, open(file_path, 'rb'), filename="查询结果.txt")
                    logger.info(f"指定 bot 的文件消息已通过机器人发送到目标群组")
                    
                    # 提取文本文件内容并筛选链接
                    if file_path.endswith('.txt'):  # 确保是文本文件
                        with open(file_path, 'r', encoding='utf-8') as f:
                            text = f.read()
                        links = extract_links(text)
                        if links:
                            # 重新加载已有的链接
                            written_links = set()
                            if os.path.exists(EXTRACTED_TEXT_FILE):
                                with open(EXTRACTED_TEXT_FILE, 'r', encoding='utf-8') as f:
                                    written_links.update(line.strip() for line in f.readlines())
                            
                            # 写入新的链接，避免重复
                            new_links = []
                            for link in links:
                                if link not in written_links:
                                    new_links.append(link)
                                    written_links.add(link)
                            
                            if new_links:
                                with open(EXTRACTED_TEXT_FILE, 'a', encoding='utf-8') as f:
                                    for link in new_links:
                                        f.write(link + '\n')
                                    logger.info(f"已将符合条件的链接追加到固定文件: {EXTRACTED_TEXT_FILE}")
                            else:
                                logger.info("提取到的链接已全部写入，没有新的链接")
                        else:
                            logger.info("未找到符合条件的链接")
                    
                    # 删除下载的文件
                    os.remove(file_path)
                    logger.info(f"已删除下载的文件: {file_path}")
                else:
                    # 处理文字消息
                    text = message_text
                    # 检查是否符合预定格式
                    if '剩余可用' in text:
                        logger.info("捕获到符合预定格式的文字消息")
                        links = extract_links(text)
                        if links:
                            # 重新加载已有的链接
                            written_links = set()
                            if os.path.exists(EXTRACTED_TEXT_FILE):
                                with open(EXTRACTED_TEXT_FILE, 'r', encoding='utf-8') as f:
                                    written_links.update(line.strip() for line in f.readlines())
                            
                            # 写入新的链接，避免重复
                            new_links = []
                            for link in links:
                                if link not in written_links:
                                    new_links.append(link)
                                    written_links.add(link)
                            
                            if new_links:
                                with open(EXTRACTED_TEXT_FILE, 'a', encoding='utf-8') as f:
                                    for link in new_links:
                                        f.write(link + '\n')
                                    logger.info(f"已将符合条件的链接追加到固定文件: {EXTRACTED_TEXT_FILE}")
                            else:
                                logger.info("提取到的链接已全部写入，没有新的链接")
                        else:
                            logger.info("文字消息未找到符合条件的链接")
                    else:
                        logger.info("文字消息不符合预定格式，跳过处理")
                    
                    # 转发文字消息到目标群组
                    await bot.send_message(TARGET_CHAT_ID, message_text)
                    logger.info(f"指定 bot 的文字消息已通过机器人发送到目标群组: {message_text}")
            except Exception as e:
                logger.error(f"发送指定 bot 的消息出错: {e}")
        else:
            logger.info(f"消息不是来自指定的 bot 列表，跳过复制")
    # 如果是其他监控的群组，则正常转发所有消息
    else:
        try:
            if media:
                file_path = await user_client.download_media(media)
                await bot.send_document(TARGET_CHAT_ID, open(file_path, 'rb'), filename="查询结果.txt")
                logger.info(f"文件消息已通过机器人发送到目标群组")
                
                # 提取文本文件内容并筛选链接
                if file_path.endswith('.txt'):  # 确保是文本文件
                    with open(file_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    links = extract_links(text)
                    if links:
                        # 重新加载已有的链接
                        written_links = set()
                        if os.path.exists(EXTRACTED_TEXT_FILE):
                            with open(EXTRACTED_TEXT_FILE, 'r', encoding='utf-8') as f:
                                written_links.update(line.strip() for line in f.readlines())
                        
                        # 写入新的链接，避免重复
                        new_links = []
                        for link in links:
                            if link not in written_links:
                                new_links.append(link)
                                written_links.add(link)
                        
                        if new_links:
                            with open(EXTRACTED_TEXT_FILE, 'a', encoding='utf-8') as f:
                                for link in new_links:
                                    f.write(link + '\n')
                                logger.info(f"已将符合条件的链接追加到固定文件: {EXTRACTED_TEXT_FILE}")
                        else:
                            logger.info("提取到的链接已全部写入，没有新的链接")
                    else:
                        logger.info("未找到符合条件的链接")
                
                # 删除下载的文件
                os.remove(file_path)
                logger.info(f"已删除下载的文件: {file_path}")
            else:
                await bot.send_message(TARGET_CHAT_ID, message_text)
                logger.info(f"消息已通过机器人发送到目标群组: {message_text}")
        except Exception as e:
            logger.error(f"发送消息出错: {e}")

async def main():
    await user_client.start()
    logger.info("监控已启动")
    await user_client.run_until_disconnected()

def calculate_md5(file_path):
    """计算文件的 MD5 值"""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()

def update_subscriptions():
    """更新 dymb.py 文件中的 subscriptions 数组并执行脚本"""
    try:
        # 读取 dydz.txt 文件中的订阅地址
        with open(DYDZ_TXT_PATH, 'r', encoding='utf-8') as f:
            links = [line.strip() for line in f.readlines() if line.strip()]
        
        # 准备 subscriptions 数组的内容
        subscriptions_content = []
        for index, link in enumerate(links):
            subscription_entry = f"{{'name': '机场_{index + 1}', 'url': '{link}'}}"
            subscriptions_content.append(subscription_entry)
        
        # 读取原始 dymb.py 文件内容
        with open(DYNB_PY_PATH, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        # 构建新的 subscriptions 数组代码
        new_subscriptions_code = DYNB_PY_SUBSCRIPTIONS_TEMPLATE.format(
            subscriptions=','.join(subscriptions_content)
        )
        
        # 替换原始文件中的 subscriptions 数组
        new_content = re.sub(
            r'subscriptions = \[\s*.*?\s*\]',
            new_subscriptions_code.strip(),
            original_content,
            flags=re.DOTALL
        )
        
        # 将修改后的内容写回 dymb.py 文件
        with open(DYNB_PY_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        logger.info("subscriptions 数组已更新")
        
        # 执行 dymb.py 文件
        subprocess.run(['python', DYNB_PY_PATH], check=True)
        logger.info("dymb.py 脚本已执行")
    except Exception as e:
        logger.error(f"更新 subscriptions 或执行脚本时出错: {e}")

async def monitor_dydzt():
    """监控 dydz.txt 文件的 MD5 变化"""
    last_md5 = None
    lock = FileLock(f"{DYDZ_TXT_PATH}.lock")
    
    while True:
        try:
            with lock:  # 使用文件锁避免并发问题
                current_md5 = calculate_md5(DYDZ_TXT_PATH)
                
                if last_md5 != current_md5:
                    logger.info(f"检测到 dydz.txt 文件内容发生变化，MD5 值: {current_md5}")
                    last_md5 = current_md5
                    update_subscriptions()
        except Exception as e:
            logger.error(f"监控 dydz.txt 文件时出错: {e}")
        
        await asyncio.sleep(5)  # 每5秒检查一次

if __name__ == "__main__":
    # 去除文件中的重复链接
    deduplicate_links(EXTRACTED_TEXT_FILE)
    
    # 确保目标文件存在
    if not os.path.exists(DYDZ_TXT_PATH):
        with open(DYDZ_TXT_PATH, 'w', encoding='utf-8') as f:
            pass
    
    # 启动 Telegram 客户端
    with user_client:
        # 保存MD5到文件
        try:
            with FileLock(f"{MD5_FILE_PATH}.lock"):
                current_md5 = calculate_md5(DYDZ_TXT_PATH)
                with open(MD5_FILE_PATH, 'w', encoding='utf-8') as f:
                    f.write(current_md5)
        except Exception as e:
            logger.error(f"保存初始 MD5 时出错: {e}")
        
        # 启动监控任务和主循环
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.gather(
            main(),
            monitor_dydzt()
        ))