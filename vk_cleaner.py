import json
import time
import os
import sys
from datetime import datetime
import requests
import signal

try:
    import config
except ImportError:
    print("Ошибка: Создайте файл config.py с настройками!")
    sys.exit(1)

# Константы
LOG_FILE = 'vk_limits.log'
VK_API_URL = 'https://api.vk.com/method/'

class GracefulInterrupt:
    """Класс для обработки прерывания"""
    def __init__(self):
        self.interrupted = False
        signal.signal(signal.SIGINT, self.handler)
        signal.signal(signal.SIGTERM, self.handler)

    def handler(self, signum, frame):
        print("\nПолучен сигнал прерывания...")
        self.interrupted = True

def manage_limits(action, data=None):
    """Управление лимитами с автосбросом по времени"""
    if action == 'read':
        try:
            with open(LOG_FILE, 'r') as f:
                limits = json.load(f)
            
            # Автоматический сброс по истечении времени
            current_time = time.time()
            if current_time - limits['last_user_reset'] > 86400:
                limits['users_deleted'] = 0
                limits['last_user_reset'] = current_time
            if current_time - limits['last_post_reset'] > 3600:
                limits['posts_deleted'] = 0
                limits['last_post_reset'] = current_time
            
            return limits
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                'users_deleted': 0,
                'posts_deleted': 0,
                'last_user_reset': int(time.time()),
                'last_post_reset': int(time.time())
            }
    elif action == 'write':
        with open(LOG_FILE, 'w') as f:
            json.dump(data, f, indent=2)

def vk_api_request(method, params):
    """Запрос к VK API с обработкой ошибок"""
    params.update({
        'access_token': config.ACCESS_TOKEN,
        'v': config.VERSION
    })
    
    try:
        response = requests.get(VK_API_URL + method, params=params, timeout=30)
        return response.json()
    except Exception as e:
        print(f"Ошибка API: {e}")
        return None

def safe_delete_post(group_id, post_id, limits):
    """Безопасное удаление поста"""
    if limits['posts_deleted'] >= config.MAX_POSTS_PER_HOUR:
        return False
    
    result = vk_api_request('wall.delete', {
        'owner_id': group_id,
        'post_id': post_id
    })
    
    if result and 'response' in result and result['response'] == 1:
        limits['posts_deleted'] += 1
        time.sleep(config.DELAY)
        return True
    return False

def safe_remove_user(group_id, user_id, limits):
    """Безопасное удаление подписчика"""
    if limits['users_deleted'] >= config.MAX_USERS_PER_DAY:
        return False
    
    result = vk_api_request('groups.removeUser', {
        'group_id': abs(group_id),
        'user_id': user_id
    })
    
    if result and 'response' in result and result['response'] == 1:
        limits['users_deleted'] += 1
        time.sleep(config.DELAY)
        return True
    return False

def delete_posts(limits, interrupt):
    """Удаление постов с обработкой прерывания"""
    offset = 0
    count = 100
    deleted = 0
    
    while not interrupt.interrupted:
        if limits['posts_deleted'] >= config.MAX_POSTS_PER_HOUR:
            reset_time = limits['last_post_reset'] + 3600
            print(f"Лимит постов достигнут! Доступно после {datetime.fromtimestamp(reset_time).strftime('%d.%m.%Y %H:%M')}")
            break
            
        response = vk_api_request('wall.get', {
            'owner_id': config.GROUP_ID,
            'count': count,
            'offset': offset
        })
        
        if not response or 'items' not in response.get('response', {}):
            break
            
        for post in response['response']['items']:
            if interrupt.interrupted:
                break
                
            if safe_delete_post(config.GROUP_ID, post['id'], limits):
                deleted += 1
                print(f"Удален пост {post['id']} ({deleted} в этой сессии)")
        
        offset += count
        
    return deleted

def remove_users(limits, interrupt):
    """Удаление подписчиков с обработкой прерывания"""
    offset = 0
    count = 1000
    removed = 0
    
    while not interrupt.interrupted:
        if limits['users_deleted'] >= config.MAX_USERS_PER_DAY:
            reset_time = limits['last_user_reset'] + 86400
            print(f"Лимит подписчиков достигнут! Доступно после {datetime.fromtimestamp(reset_time).strftime('%d.%m.%Y %H:%M')}")
            break
            
        response = vk_api_request('groups.getMembers', {
            'group_id': abs(config.GROUP_ID),
            'count': count,
            'offset': offset
        })
        
        if not response or 'items' not in response.get('response', {}):
            break
            
        for user_id in response['response']['items']:
            if interrupt.interrupted:
                break
                
            if safe_remove_user(config.GROUP_ID, user_id, limits):
                removed += 1
                print(f"Удален подписчик {user_id} ({removed} в этой сессии)")
        
        offset += count
        
    return removed

def main():
    interrupt = GracefulInterrupt()
    limits = manage_limits('read')
    
    print("=== VK Cleaner ===")
    print(f"Лимиты:")
    print(f"Постов: {limits['posts_deleted']}/{config.MAX_POSTS_PER_HOUR} (час)")
    print(f"Подписчиков: {limits['users_deleted']}/{config.MAX_USERS_PER_DAY} (день)")
    
    try:
        # Удаление постов
        print("\n[1] Удаление постов...")
        deleted_posts = delete_posts(limits, interrupt)
        print(f"Удалено постов в этой сессии: {deleted_posts}")
        
        # Удаление подписчиков
        print("\n[2] Удаление подписчиков...")
        removed_users = remove_users(limits, interrupt)
        print(f"Удалено подписчиков в этой сессии: {removed_users}")
        
    except Exception as e:
        print(f"Критическая ошибка: {e}")
    finally:
        manage_limits('write', limits)
        print("\nИтоговые лимиты:")
        print(f"Постов: {limits['posts_deleted']}/{config.MAX_POSTS_PER_HOUR}")
        print(f"Подписчиков: {limits['users_deleted']}/{config.MAX_USERS_PER_DAY}")
        print("Прогресс сохранен!")

if __name__ == "__main__":
    main()