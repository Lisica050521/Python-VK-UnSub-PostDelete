import sys
import threading
import queue
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, 
    QLabel, QLineEdit, QPushButton, QTextEdit, QFrame
)
from PyQt6.QtCore import Qt, QTimer
import requests
import config
from vk_cleaner import main, GracefulInterrupt

class ConsoleText(QTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setReadOnly(False)
        self.setFontFamily("Consolas")
        self.setFontPointSize(10)
        self.setStyleSheet("background-color: #2b2b2b; color: white;")

class VKCleanerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VK UnSub & PostDelete")
        self.setGeometry(100, 100, 800, 600)
        
        self.log_queue = queue.Queue()
        self.thread = None
        self.interrupt = GracefulInterrupt()
        
        self.setup_ui()
        
        # Таймер для обработки очереди логов
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(100)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # Токен VK
        token_label = QLabel("Токен VK:")
        self.token_entry = QLineEdit()
        self.token_entry.setText(config.config["ACCESS_TOKEN"])
        layout.addWidget(token_label)
        layout.addWidget(self.token_entry)

        # ID Группы
        group_id_label = QLabel("ID Группы:")
        self.group_id_entry = QLineEdit()
        self.group_id_entry.setText(config.config["GROUP_ID"])
        layout.addWidget(group_id_label)
        layout.addWidget(self.group_id_entry)

        # Кнопки
        btn_frame = QFrame()
        btn_layout = QVBoxLayout(btn_frame)
        btn_layout.setSpacing(5)
        
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self.save_config)
        
        self.check_token_btn = QPushButton("Проверить токен")
        self.check_token_btn.clicked.connect(self.check_token)
        
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.check_token_btn)
        layout.addWidget(btn_frame)

        # Лог
        self.log_text = ConsoleText()
        layout.addWidget(self.log_text)

        # Управление
        control_frame = QFrame()
        control_layout = QVBoxLayout(control_frame)
        
        self.start_btn = QPushButton("Старт")
        self.start_btn.setStyleSheet("background-color: green; color: white;")
        self.start_btn.clicked.connect(self.start_cleaner)
        
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setStyleSheet("background-color: red; color: white;")
        self.stop_btn.clicked.connect(self.stop_cleaner)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        layout.addWidget(control_frame)

    def save_config(self):
        config.config["ACCESS_TOKEN"] = self.token_entry.text()
        config.config["GROUP_ID"] = self.group_id_entry.text()
        config.save_config(config.config)
        self.log("Настройки сохранены!")

    def check_token(self):
        token = config.config["ACCESS_TOKEN"]
        if not token:
            self.log("Ошибка: токен не введен!")
            return
            
        try:
            response = requests.get('https://api.vk.com/method/users.get', 
                                 params={'access_token': token, 'v': '5.131'},
                                 timeout=10)
            data = response.json()
            
            if 'response' in data:
                self.log(f"✓ Токен действителен! ID: {data['response'][0]['id']}")
            
            else:
                error_data = data.get('error', {})
                error_code = error_data.get('error_code')
                error_msg = error_data.get('error_msg', 'Неизвестная ошибка')

                # Проверяем и код ошибки, и текст
                if error_code == 5 or "(4)" in error_msg:
                    self.log("❌ Ошибка: Токен не активен. Получите новый токен по инструкции в приложении")
                else:
                    self.log(f"× Ошибка: {error_msg}")
        except Exception as e:
            self.log(f"! Ошибка проверки: {str(e)}")

    def start_cleaner(self):
        if not config.config["GROUP_ID"]:
            self.log("Ошибка: введите ID группы!")
            return
            
        if self.thread and self.thread.is_alive():
            self.log("Процесс уже запущен!")
            return
            
        self.interrupt.interrupted = False
        self.thread = threading.Thread(target=self.run_cleaner, daemon=True)
        self.thread.start()

    def stop_cleaner(self):
        self.interrupt.interrupted = True
        self.log("Запрошена остановка...")

    def run_cleaner(self):
        old_stdout = sys.stdout
        sys.stdout = self
        
        try:
            main(self.interrupt)
        except Exception as e:
            self.log(f"Ошибка: {str(e)}")
        finally:
            sys.stdout = old_stdout

    def write(self, text):
        self.log_queue.put(text)

    def flush(self):
        pass

    def process_queue(self):
        while not self.log_queue.empty():
            text = self.log_queue.get()
            self.log_text.insertPlainText(text)
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )

    def log(self, message):
        self.log_text.insertPlainText(message + "\n")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VKCleanerApp()
    window.show()
    sys.exit(app.exec())