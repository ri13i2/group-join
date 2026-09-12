import sys
import json
import os
import asyncio
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QTextEdit, 
                             QPushButton, QMessageBox, QGroupBox)
from PyQt5.QtCore import QThread, pyqtSignal
from hydrogram import Client
from hydrogram.errors import FloodWait, SessionPasswordNeeded

CONFIG_FILE = "config.json"

# ==========================================
# 1. 백그라운드 작업 스레드 (로그인 처리)
# ==========================================
class LoginWorker(QThread):
    log_signal = pyqtSignal(str)
    auth_code_needed = pyqtSignal(str)  # 인증코드 요청 시그널 (phone_code_hash 전달)
    login_success = pyqtSignal()

    def __init__(self, api_id, api_hash, phone, phone_code_hash=None, auth_code=None):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.phone_code_hash = phone_code_hash
        self.auth_code = auth_code

    def run(self):
        asyncio.run(self.process_login())

    async def process_login(self):
        app = Client("my_session", api_id=self.api_id, api_hash=self.api_hash)
        await app.connect()
        try:
            # 1단계: 인증번호 발송 요청
            if not self.auth_code:
                self.log_signal.emit("텔레그램 서버로 인증번호 발송을 요청합니다...")
                sent_code = await app.send_code(self.phone)
                self.log_signal.emit("인증번호가 발송되었습니다. 텔레그램 앱을 확인해주세요.")
                self.auth_code_needed.emit(sent_code.phone_code_hash)
            
            # 2단계: 인증번호 입력 후 로그인 승인
            else:
                self.log_signal.emit("로그인 인증을 시도합니다...")
                await app.sign_in(self.phone, self.phone_code_hash, self.auth_code)
                self.log_signal.emit("로그인 성공! 이제 세션이 유지됩니다.")
                self.login_success.emit()
                
        except SessionPasswordNeeded:
            self.log_signal.emit("[오류] 2단계 인증(2FA) 비밀번호가 설정되어 있습니다. 코드를 수정해야 합니다.")
        except Exception as e:
            self.log_signal.emit(f"[오류] 로그인 실패: {e}")
        finally:
            await app.disconnect()


# ==========================================
# 2. 백그라운드 작업 스레드 (매크로 처리)
# ==========================================
class MacroWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, api_id, api_hash, links):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.links = links

    def run(self):
        asyncio.run(self.join_groups())

    async def join_groups(self):
        app = Client("my_session", api_id=self.api_id, api_hash=self.api_hash)
        self.log_signal.emit("자동 인입 매크로를 시작합니다...")
        
        async with app:
            for link in self.links:
                link = link.strip()
                if not link: continue
                
                joined = False
                while not joined:
                    try:
                        self.log_signal.emit(f"입장 시도 중: {link}")
                        await app.join_chat(link)
                        self.log_signal.emit(f"입장 완료: {link}")
                        joined = True
                        
                        # 인입 간 안전 딜레이 (10~20초 권장)
                        await asyncio.sleep(15) 

                    except FloodWait as e:
                        wait_time = e.value
                        self.log_signal.emit(f"[플러드 웨이트] {wait_time}초 대기 후 자동으로 재시도합니다.")
                        await asyncio.sleep(wait_time)
                        
                    except Exception as e:
                        self.log_signal.emit(f"[오류] {link} 가입 실패: {e}")
                        break
                        
        self.finished_signal.emit()


# ==========================================
# 3. 메인 UI (PyQt5)
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("텔레그램 홍보방 자동 인입기")
        self.resize(550, 650)
        self.phone_code_hash = None
        
        self.init_ui()
        self.load_config()
        self.check_session()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # [ API & 로그인 설정 그룹 ]
        api_group = QGroupBox("1. API 및 계정 연동 (최초 1회만 진행)")
        api_layout = QVBoxLayout()

        self.input_api_id = QLineEdit(); self.input_api_id.setPlaceholderText("API ID (숫자)")
        self.input_api_hash = QLineEdit(); self.input_api_hash.setPlaceholderText("API HASH")
        self.input_phone = QLineEdit(); self.input_phone.setPlaceholderText("전화번호 (예: +821012345678)")
        
        api_layout.addWidget(QLabel("API ID:"))
        api_layout.addWidget(self.input_api_id)
        api_layout.addWidget(QLabel("API HASH:"))
        api_layout.addWidget(self.input_api_hash)
        api_layout.addWidget(QLabel("전화번호 (국가번호 포함):"))
        api_layout.addWidget(self.input_phone)

        self.btn_send_code = QPushButton("인증번호 발송")
        self.btn_send_code.clicked.connect(self.request_auth_code)
        api_layout.addWidget(self.btn_send_code)

        # 인증번호 입력부 (기본 숨김)
        self.code_widget = QWidget()
        code_layout = QHBoxLayout()
        code_layout.setContentsMargins(0, 0, 0, 0)
        self.input_auth_code = QLineEdit(); self.input_auth_code.setPlaceholderText("텔레그램으로 온 숫자 5자리")
        self.btn_login = QPushButton("로그인 확인")
        self.btn_login.clicked.connect(self.submit_auth_code)
        code_layout.addWidget(self.input_auth_code)
        code_layout.addWidget(self.btn_login)
        self.code_widget.setLayout(code_layout)
        self.code_widget.setVisible(False)
        api_layout.addWidget(self.code_widget)

        api_group.setLayout(api_layout)
        main_layout.addWidget(api_group)

        # [ 홍보방 링크 리스트 그룹 ]
        link_group = QGroupBox("2. 홍보방 리스트 (줄바꿈으로 구분)")
        link_layout = QVBoxLayout()
        self.input_links = QTextEdit()
        link_layout.addWidget(self.input_links)
        link_group.setLayout(link_layout)
        main_layout.addWidget(link_group)

        # [ 하단 컨트롤 & 로그 ]
        self.btn_start = QPushButton("자동 인입 시작 (세션 필요)")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_macro)
        main_layout.addWidget(self.btn_start)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        main_layout.addWidget(self.log_view)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    # --- 설정 저장 및 불러오기 ---
    def save_config(self):
        config = {
            "api_id": self.input_api_id.text(),
            "api_hash": self.input_api_hash.text(),
            "phone": self.input_phone.text(),
            "links": self.input_links.toPlainText()
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                self.input_api_id.setText(config.get("api_id", ""))
                self.input_api_hash.setText(config.get("api_hash", ""))
                self.input_phone.setText(config.get("phone", ""))
                self.input_links.setPlainText(config.get("links", ""))

    # --- 로그인 로직 ---
    def check_session(self):
        if os.path.exists("my_session.session"):
            self.log("기존 세션(로그인 정보)이 발견되었습니다. 바로 시작할 수 있습니다.")
            self.btn_start.setEnabled(True)
            self.btn_start.setText("▶ 자동 인입 시작")

    def request_auth_code(self):
        self.save_config() # 요청 전 정보 저장
        api_id = int(self.input_api_id.text().strip() or 0)
        api_hash = self.input_api_hash.text().strip()
        phone = self.input_phone.text().strip()

        if not api_id or not api_hash or not phone:
            QMessageBox.warning(self, "경고", "API ID, HASH, 전화번호를 모두 입력해주세요.")
            return

        self.btn_send_code.setEnabled(False)
        self.login_worker = LoginWorker(api_id, api_hash, phone)
        self.login_worker.log_signal.connect(self.log)
        self.login_worker.auth_code_needed.connect(self.show_auth_input)
        self.login_worker.start()

    def show_auth_input(self, phone_code_hash):
        self.phone_code_hash = phone_code_hash
        self.code_widget.setVisible(True)
        self.btn_send_code.setText("인증번호 재발송")
        self.btn_send_code.setEnabled(True)

    def submit_auth_code(self):
        code = self.input_auth_code.text().strip()
        if not code:
            return
            
        self.btn_login.setEnabled(False)
        api_id = int(self.input_api_id.text().strip())
        
        self.login_worker = LoginWorker(
            api_id, 
            self.input_api_hash.text().strip(), 
            self.input_phone.text().strip(),
            self.phone_code_hash, 
            code
        )
        self.login_worker.log_signal.connect(self.log)
        self.login_worker.login_success.connect(self.on_login_success)
        self.login_worker.start()

    def on_login_success(self):
        self.code_widget.setVisible(False)
        self.btn_start.setEnabled(True)
        self.btn_start.setText("▶ 자동 인입 시작")
        self.btn_login.setEnabled(True)

    # --- 매크로 실행 로직 ---
    def start_macro(self):
        self.save_config() # 시작 전 입력된 링크 저장
        api_id = int(self.input_api_id.text().strip())
        api_hash = self.input_api_hash.text().strip()
        links = self.input_links.toPlainText().split('\n')
        
        self.btn_start.setEnabled(False)
        self.macro_worker = MacroWorker(api_id, api_hash, links)
        self.macro_worker.log_signal.connect(self.log)
        self.macro_worker.finished_signal.connect(self.on_macro_finished)
        self.macro_worker.start()

    def on_macro_finished(self):
        self.log("모든 인입 작업이 종료되었습니다.")
        self.btn_start.setEnabled(True)

    def log(self, text):
        self.log_view.append(text)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
