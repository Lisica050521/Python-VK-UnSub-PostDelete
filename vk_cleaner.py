import json
import time
import requests
import config
import sys
import os
from datetime import datetime, timedelta

def get_log_path():
    if getattr(sys, 'frozen', False):
        # Если запущен как exe
        return os.path.join(os.path.dirname(sys.executable), 'vk_limits.log')
    else:
        # Если запущен как скрипт
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vk_limits.log')

LOG_FILE = get_log_path()

VK_API_URL = 'https://api.vk.com/method/'

def get_next_day_reset(last_reset_timestamp):
    """Возвращает 00:01 следующего дня для подписчиков"""
    last_reset_date = datetime.fromtimestamp(last_reset_timestamp).date()
    return datetime.combine(last_reset_date + timedelta(days=1), datetime.min.time().replace(minute=1))

class GracefulInterrupt:
    def __init__(self):
        self.interrupted = False

    def handler(self):
        self.interrupted = True

def manage_limits(action, data=None):
    if action == 'read':
        try:
            with open(LOG_FILE, 'r') as f:
                limits = json.load(f)
            
            current_time = time.time()
            # Для постов (оставляем часовой сброс)
            if current_time - limits['last_post_reset'] > 3600:
                limits['posts_deleted'] = 0
                limits['last_post_reset'] = current_time  # Сброс по фактическому времени

            # Для подписчиков (суточный сброс в 00:01)
            next_reset = get_next_day_reset(limits['last_user_reset'])
            if current_time >= next_reset.timestamp():
                limits['users_deleted'] = 0
                limits['last_user_reset'] = int(next_reset.timestamp())
                        
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

def vk_api_request(method, params, interrupt):
    params.update({
        'access_token': config.config["ACCESS_TOKEN"],
        'v': config.config["VERSION"],
        'timestamp': int(time.time()),
        'random_id': int(time.time() * 1000)
    })
    
    try:
        response = requests.get(VK_API_URL + method, params=params, timeout=30)
        result = response.json()
        
        if 'error' in result:
            error = result['error']
            error_code = error.get('error_code')
            
            # Обработка невалидного токена
            if error_code == 4:  # User authorization failed
                print("\n❌ Ошибка: Токен не активен. Получите новый токен по инструкции в приложении")
                return None
        
            # Обработка флуд-контроля и Rate Limit
            if error_code in [9, 29]:
                # Динамическая задержка: начнем с 5 сек, удваиваем при каждом повторе (макс 300 сек)
                current_delay = getattr(vk_api_request, 'current_delay', 5)
                delay = min(current_delay * 2, 300) if error_code == 29 else 10
                vk_api_request.current_delay = delay
                
                print(f"⏳ Лимит запросов ({error['error_msg']}). Пауза {delay} сек...")
                for _ in range(delay):
                    if interrupt.interrupted:
                        print("🛑 Обнаружено прерывание во время ожидания")
                        return None
                    time.sleep(1)
                
                return vk_api_request(method, params, interrupt)
            
        # Сброс задержки при успешном запросе
        vk_api_request.current_delay = 5
        return result
        
    except Exception as e:
        print(f"⚠️ Ошибка соединения: {e}")
        return None

def safe_delete_post(group_id, post_id, limits, interrupt):
    if interrupt.interrupted:
        return False
    if limits['posts_deleted'] >= config.config["MAX_POSTS_PER_HOUR"]:
        return False
    
    result = vk_api_request('wall.delete', {
        'owner_id': group_id,
        'post_id': post_id
    }, interrupt)  # Добавлен параметр interrupt
    
    if result and 'response' in result and result['response'] == 1:
        limits['posts_deleted'] += 1
        time.sleep(config.config["DELAY"])
        return True
    return False

def safe_remove_user(group_id, user_id, limits, interrupt):
    if interrupt.interrupted:
        return False
        
    if limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
        return False
    
    # 1. Текущий пользователь (скрипт не может удалить сам себя) - пропускаем БЕЗ сообщения
    if user_id == int(config.config.get("USER_ID", 0)):
        return False
    
    result = vk_api_request('groups.removeUser', {
        'group_id': abs(group_id),
        'user_id': user_id
    }, interrupt)
    
    if not result:
        return False
        
    if result.get('response') == 1:
        limits['users_deleted'] += 1
        time.sleep(config.config.get("REQUEST_DELAY", 3))
        return True
        
    error = result.get('error', {})
    error_code = error.get('error_code')

    if error_code in [100, 15, 7]:  # Админы/создатели
        print(f"⏩ Обнаружен руководитель группы (ID: {user_id}). Удалите его вручную через:")
        print("Управление сообществом → Участники → Исключить")
        return False
    elif error_code == 9:  # Флуд-контроль
        delay = config.config.get("FLOOD_DELAY", 10)
        print(f"⏳ Флуд-контроль. Ждем {delay} сек...")
        time.sleep(delay)
        return safe_remove_user(group_id, user_id, limits, interrupt)
    else:
        print(f"⛔ Ошибка при удалении {user_id}: {error.get('error_msg', 'Неизвестная ошибка')}")
        return False
    
def delete_posts(limits, interrupt):
    offset = 0
    count = 100
    deleted = 0
    max_attempts = 3
    attempts = 0
    
    while not interrupt.interrupted and attempts < max_attempts:
        if limits['posts_deleted'] >= config.config["MAX_POSTS_PER_HOUR"]:
            reset_time = datetime.fromtimestamp(limits['last_post_reset'] + 3600)
            print(f"\nЛимит удаления постов достигнут! Вернитесь после {reset_time.strftime('%d.%m.%Y %H:%M')}")
            break
            
        response = vk_api_request('wall.get', {
            'owner_id': int(config.config["GROUP_ID"]),
            'count': count,
            'offset': offset
        }, interrupt)  # Добавлен параметр interrupt
        
        if not response:
            attempts += 1
            time.sleep(5)
            continue
            
        if 'items' not in response.get('response', {}):
            print("\nПосты закончились")
            break
            
        items = response['response']['items']
        if not items:
            print("\nБольше нет постов для удаления")
            break
            
        for post in items:
            if interrupt.interrupted or limits['posts_deleted'] >= config.config["MAX_POSTS_PER_HOUR"]:
                break
                
            if safe_delete_post(int(config.config["GROUP_ID"]), post['id'], limits, interrupt):
                deleted += 1
                print(f"Удален пост {post['id']} ({deleted} в этой сессии)")
        
        offset += count
        attempts = 0
        
    return deleted

def remove_users(limits, interrupt):
    offset = 0
    count = min(100, config.config.get("MEMBERS_PER_REQUEST", 100))
    removed = 0
    retry_count = 0
    max_retries = config.config.get("API_RETRY_LIMIT", 3)
    has_regular_members = False

    #Вычисляем reset_time один раз в начале функции
    reset_time = get_next_day_reset(limits['last_user_reset'])
    
    if limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
        print(f"⏳ Лимит удалений подписчиков достигнут! Вернитесь после {reset_time.strftime('%d.%m.%Y %H:%M')}")
        return 0
    
    while not interrupt.interrupted and retry_count < max_retries:
        if interrupt.interrupted:
            print("🛑 Обнаружено прерывание!")
            break
            
        response = vk_api_request('groups.getMembers', {
            'group_id': abs(int(config.config["GROUP_ID"])),
            'count': count,
            'offset': offset,
            'fields': 'role'
        }, interrupt)
        
        if not response:
            retry_count += 1
            time.sleep(5)
            continue
            
        if 'error' in response:
            error = response['error']
            error_code = error.get('error_code')
            
            if error_code in [15, 7, 100]:  # Админы/создатели/руководители 
                continue
            elif error_code == 9:  # Флуд-контроль
                delay = config.config.get("FLOOD_DELAY", 10)
                print(f"⏳ Флуд-контроль. Ждем {delay} сек...")
                time.sleep(delay)
                continue
            else:
                print(f"⛔ Ошибка API [{error_code}]: {error.get('error_msg', 'Неизвестная ошибка')}")
            
            retry_count += 1
            continue
            
        members = response.get('response', {}).get('items', [])
        if not members:
            if removed > 0 and not has_regular_members:
                print("\nПодписчики закончились")
                print("\n🎉 Поздравляю! Все подписчики удалены!")
                print("Для завершения удалите руководителей группы вручную через:")
                print("Управление сообществом → Участники → Исключить")
            break
            
        for member in members:
            if interrupt.interrupted:
                break
                
            user_id = member['id']
            role = member.get('role', 'member')
            
            if role != 'member':  # Пропускаем всех руководителей
                continue
                
            # Обычные подписчики
            has_regular_members = True
            if safe_remove_user(int(config.config["GROUP_ID"]), user_id, limits, interrupt):
                removed += 1
                print(f"❌ Удалён подписчик {user_id} ({removed}/{config.config['MAX_USERS_PER_DAY']})")
                
                if limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
                    print(f"⚠️ Достигнут дневной лимит удалений! Вернитесь после {reset_time.strftime('%d.%m.%Y %H:%M')}")
                    break
                    
        offset += len(members)
        retry_count = 0

    return removed

def main(interrupt):
    if getattr(sys, 'frozen', False):
        import shutil
        temp_dir = os.path.join(os.environ.get('TEMP', ''), 'vk_cleaner_cache')
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    try:
        limits = manage_limits('read')
        
        print("\n=== VK UnSub & PostDelete ===")
        print(f"Лимиты:")
        print(f"📝 Постов: {limits['posts_deleted']}/{config.config['MAX_POSTS_PER_HOUR']} (час)")
        print(f"👥 Подписчиков: {limits['users_deleted']}/{config.config['MAX_USERS_PER_DAY']} (день)")
        
        # Обработка постов
        if not interrupt.interrupted:
            print("\n[1] Удаление постов...")
            deleted_posts = delete_posts(limits, interrupt)
            print(f"\nУдалено постов: {deleted_posts}")
        
        # Обработка подписчиков
        if not interrupt.interrupted and limits['users_deleted'] < config.config["MAX_USERS_PER_DAY"]:
            print("\n[2] Удаление подписчиков...")
            removed_users = remove_users(limits, interrupt)
            print(f"\nУдалено подписчиков: {removed_users}")
            
    except KeyboardInterrupt:
        print("\n🛑 Получен сигнал прерывания!")
        interrupt.handler()
    except Exception as e:
        print(f"\n🔥 Критическая ошибка: {e}")
    finally:
        if 'limits' in locals():
            manage_limits('write', limits)
            print("\n📊 Итоговые лимиты:")
            print(f"📝 Постов: {limits['posts_deleted']}/{config.config['MAX_POSTS_PER_HOUR']}")
            print(f"👥 Подписчиков: {limits['users_deleted']}/{config.config['MAX_USERS_PER_DAY']}")
        print("\n📊 Статистика сохранена!")