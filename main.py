import sys
import os
import json
import asyncio
import random
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from hydrogram import Client
from hydrogram.errors import FloodWait, SessionPasswordNeeded

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "joiner_config.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ==========================================
# 🎨 1. 커스텀 타이틀바
# ==========================================
class CustomTitleBar(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setStyleSheet("background-color: transparent; border-top-left-radius: 16px; border-top-right-radius: 16px; border-bottom: 1px solid #1e293b;")
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 10, 0)

        lbl_logo = QtWidgets.QLabel("💎 노바 텔레그램 자동 인입기")
        lbl_logo.setStyleSheet("color: #e2e8f0; font-weight: 900; font-size: 15px; letter-spacing: 1px; border: none;")
        layout.addWidget(lbl_logo)
        layout.addStretch()

        btn_min = QtWidgets.QPushButton("—")
        btn_close = QtWidgets.QPushButton("✕")
        
        for btn in [btn_min, btn_close]:
            btn.setFixedSize(36, 36)
            btn.setCursor(QtGui.QCursor(Qt.PointingHandCursor))
            layout.addWidget(btn)

        btn_min.setStyleSheet("QPushButton { color: #94a3b8; background: transparent; border: none; font-weight: bold; font-size: 14px; border-radius: 8px; } QPushButton:hover { color: #e2e8f0; background: #334155; }")
        btn_close.setStyleSheet("QPushButton { background-color: #991b1b; color: #fca5a5; border: 1px solid #7f1d1d; border-radius: 4px; font-weight: bold; } QPushButton:hover { background-color: #dc2626; color: white; border: 1px solid #ef4444; }")

        btn_min.clicked.connect(self.window().showMinimized)
        btn_close.clicked.connect(self.window().close)
        self.drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = event.globalPos() - self.window().pos()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() == Qt.LeftButton:
            self.window().move(event.globalPos() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None

# ==========================================
# ⚙️ 2. 텔레그램 백그라운드 워커 (단계별 로그인 분기)
# ==========================================
class LoginWorker(QThread):
    log_signal = pyqtSignal(str)
    auth_code_needed = pyqtSignal(str)
    password_needed = pyqtSignal()
    login_success = pyqtSignal()

    def __init__(self, api_id, api_hash, phone, phone_code_hash=None, auth_code=None, password=None):
        super().__init__()
        self.api_id, self.api_hash, self.phone = api_id, api_hash, phone
        self.phone_code_hash, self.auth_code, self.password = phone_code_hash, auth_code, password

    def run(self): 
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(self.process_login())

    async def process_login(self):
        app = Client("joiner_session", api_id=self.api_id, api_hash=self.api_hash, workdir=DATA_DIR)
        await app.connect()
        try:
            # 케이스 1: 2단계 인증 비밀번호 검증 단계
            if self.password:
                self.log_signal.emit("🔐 2단계 인증 비밀번호 확인 중...")
                await app.check_password(self.password)
                self.log_signal.emit("✅ 2단계 인증 및 로그인 최종 성공! 세션이 안전하게 저장됩니다.")
                self.login_success.emit()
            
            # 케이스 2: 최초 전화번호 입력 후 인증번호 발송 요청 단계
            elif not self.auth_code:
                self.log_signal.emit("텔레그램 서버로 인증번호 발송 요청 중...")
                sent = await app.send_code(self.phone)
                self.log_signal.emit("✅ 인증번호 발송 완료! 텔레그램 공식 앱을 확인해주세요.")
                self.auth_code_needed.emit(sent.phone_code_hash)
            
            # 케이스 3: 발송된 인증번호를 받아 sign_in을 시도하는 단계
            else:
                self.log_signal.emit("인증번호 확인 및 로그인 시도 중...")
                try:
                    await app.sign_in(self.phone, self.phone_code_hash, self.auth_code)
                    self.log_signal.emit("✅ 로그인 성공! 세션이 유지됩니다.")
                    self.login_success.emit()
                except SessionPasswordNeeded:
                    # 인증번호는 맞았으나 계정에 2단계 보안 설정이 걸려있는 경우 발생
                    self.log_signal.emit("🔒 이 계정은 2단계 인증(비밀번호)이 설정되어 있습니다.")
                    self.password_needed.emit()
                    
        except SessionPasswordNeeded:
            self.log_signal.emit("🔒 2단계 인증(비밀번호)이 필요합니다.")
            self.password_needed.emit()
        except Exception as e:
            self.log_signal.emit(f"❌ 로그인 실패: {e}")
        finally:
            await app.disconnect()

class JoinWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, api_id, api_hash, links):
        super().__init__()
        self.api_id, self.api_hash, self.links = api_id, api_hash, links

    def run(self): 
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(self.auto_join())

    async def auto_join(self):
        app = Client("joiner_session", api_id=self.api_id, api_hash=self.api_hash, workdir=DATA_DIR)
        self.log_signal.emit("\n🚀 자동 인입 매크로 가동 시작...")
        
        async with app:
            for link in self.links:
                link = link.strip()
                if not link: continue
                
                joined = False
                while not joined:
                    try:
                        self.log_signal.emit(f"▶ 입장 시도 중: {link}")
                        await app.join_chat(link)
                        self.log_signal.emit(f"✅ 입장 완료: {link}")
                        joined = True
                        
                        delay = random.uniform(15, 35)
                        self.log_signal.emit(f"휴식: {int(delay)}초 대기...")
                        await asyncio.sleep(delay)

                    except FloodWait as e:
                        wait_time = e.value
                        self.log_signal.emit(f"🚨 [플러드 웨이트 감지] 서버 제한 조치로 {wait_time}초 동안 1차 대기합니다.")
                        await asyncio.sleep(wait_time)
                        
                        extra_delay = random.uniform(180, 300)
                        self.log_signal.emit(f"🛡️ [계정 보호] 제한이 풀렸으나 안전을 위해 {int(extra_delay)}초(약 {int(extra_delay/60)}분) 추가 대기합니다...")
                        await asyncio.sleep(extra_delay)
                        
                        self.log_signal.emit(f"🔄 안전 대기 종료. {link} 입장 재시도 진행...")
                        
                    except Exception as e:
                        self.log_signal.emit(f"❌ 입장 실패 ({link}): {e}")
                        break 
                        
        self.finished_signal.emit()

# ==========================================
# 🚀 3. 메인 UI
# ==========================================
class AutoJoinerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(600, 800)
        self.phone_code_hash = None
        self.init_ui()
        self.load_config()
        self.check_session()

    def init_ui(self):
        self.central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.central_widget)
        self.central_widget.setObjectName("MainContainer")
        
        self.central_widget.setStyleSheet("""
            * { font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif; }
            QWidget#MainContainer { background-color: #0b0f19; border-radius: 16px; border: 1px solid #1e293b; }
            QLabel { color: #e2e8f0; font-size: 13px; font-weight: bold; }
            QLineEdit, QTextEdit, QListWidget { 
                background-color: #1e293b; border: 2px solid #334155; border-radius: 8px; 
                padding: 10px; color: #f8fafc; font-weight: bold; font-size: 13px; outline: none;
            }
            QListWidget::item { padding: 5px; border-bottom: 1px solid #334155; }
            QListWidget::item:selected { background-color: #2563eb; color: white; border-radius: 4px; }
            QPushButton#ActionBtn { background-color: #1e232d; color: #60a5fa; border: 1px solid #2d3748; border-radius: 8px; font-size: 13px; font-weight: bold; }
            QPushButton#ActionBtn:hover { background-color: #2a3140; border: 1px solid #3b82f6; color: #93c5fd; }
            QPushButton#DelBtn { background-color: #2d1e23; color: #f87171; border: 1px solid #4a2d35; border-radius: 8px; font-size: 13px; font-weight: bold; }
            QPushButton#DelBtn:hover { background-color: #3f2a31; border: 1px solid #ef4444; color: #fca5a5; }
            QPushButton#StartBtn { background-color: #172a22; color: #4ade80; border: 1px solid #204a31; border-radius: 10px; font-size: 16px; font-weight: bold; letter-spacing: 1px; }
            QPushButton#StartBtn:hover { background-color: #1e3b2e; border: 1px solid #22c55e; color: #86efac; }
            QPushButton#StartBtn:disabled { background-color: #0f172a; color: #475569; border: 1px solid #1e293b; }
        """)

        main_layout = QtWidgets.QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        main_layout.addWidget(self.title_bar)

        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setContentsMargins(20, 10, 20, 20)
        content_layout.setSpacing(15)

        # 1. API 로그인 섹션
        api_group = QtWidgets.QGroupBox("1. API 및 계정 연동 (단계별 인증)")
        api_layout = QtWidgets.QVBoxLayout(api_group)
        
        row1 = QtWidgets.QHBoxLayout()
        self.inp_api_id = QtWidgets.QLineEdit(); self.inp_api_id.setPlaceholderText("API ID")
        self.inp_api_hash = QtWidgets.QLineEdit(); self.inp_api_hash.setPlaceholderText("API HASH")
        row1.addWidget(self.inp_api_id); row1.addWidget(self.inp_api_hash)
        api_layout.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        self.inp_phone = QtWidgets.QLineEdit(); self.inp_phone.setPlaceholderText("전화번호 (+82...)")
        self.btn_send_code = QtWidgets.QPushButton("인증 요청")
        self.btn_send_code.setObjectName("ActionBtn")
        self.btn_send_code.clicked.connect(self.request_auth_code)
        row2.addWidget(self.inp_phone); row2.addWidget(self.btn_send_code)
        api_layout.addLayout(row2)

        # 텔레그램 인증번호 입력 위젯
        self.auth_widget = QtWidgets.QWidget()
        auth_layout = QtWidgets.QHBoxLayout(self.auth_widget)
        auth_layout.setContentsMargins(0, 0, 0, 0)
        self.inp_code = QtWidgets.QLineEdit()
        self.inp_code.setPlaceholderText("텔레그램 인증번호 5자리")
        self.btn_login = QtWidgets.QPushButton("인증번호 확인")
        self.btn_login.setObjectName("ActionBtn")
        self.btn_login.clicked.connect(self.submit_auth_code)
        auth_layout.addWidget(self.inp_code)
        auth_layout.addWidget(self.btn_login)
        self.auth_widget.setVisible(False)
        api_layout.addWidget(self.auth_widget)

        # 2단계 인증 비밀번호 입력 위젯
        self.two_fa_widget = QtWidgets.QWidget()
        two_fa_layout = QtWidgets.QHBoxLayout(self.two_fa_widget)
        two_fa_layout.setContentsMargins(0, 0, 0, 0)
        self.inp_password = QtWidgets.QLineEdit()
        self.inp_password.setPlaceholderText("2단계 비밀번호 입력")
        self.inp_password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.btn_login_2fa = QtWidgets.QPushButton("비밀번호 승인")
        self.btn_login_2fa.setObjectName("ActionBtn")
        self.btn_login_2fa.clicked.connect(self.submit_2fa_password)
        two_fa_layout.addWidget(self.inp_password)
        two_fa_layout.addWidget(self.btn_login_2fa)
        self.two_fa_widget.setVisible(False)
        api_layout.addWidget(self.two_fa_widget)

        content_layout.addWidget(api_group)

        # 2. 홍보방 리스트 관리 섹션
        link_group = QtWidgets.QGroupBox("2. 타겟 홍보방 링크 리스트")
        link_layout = QtWidgets.QVBoxLayout(link_group)
        
        link_input_row = QtWidgets.QHBoxLayout()
        self.inp_new_link = QtWidgets.QLineEdit()
        self.inp_new_link.setPlaceholderText("https://t.me/...")
        
        self.btn_add_link = QtWidgets.QPushButton("추가")
        self.btn_add_link.setObjectName("ActionBtn")
        self.btn_add_link.clicked.connect(self.add_link)
        
        self.btn_del_link = QtWidgets.QPushButton("선택 삭제")
        self.btn_del_link.setObjectName("DelBtn")
        self.btn_del_link.clicked.connect(self.del_link)
        
        link_input_row.addWidget(self.inp_new_link)
        link_input_row.addWidget(self.btn_add_link)
        link_input_row.addWidget(self.btn_del_link)
        
        self.list_links = QtWidgets.QListWidget()
        
        link_layout.addLayout(link_input_row)
        link_layout.addWidget(self.list_links)
        content_layout.addWidget(link_group)

        # 3. 콘솔 로그 섹션
        log_group = QtWidgets.QGroupBox("💻 시스템 라이브 콘솔 로그")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #090d16; color: #38bdf8; font-family: 'Consolas', monospace; font-size: 12px; border: 1px solid #1f2937;")
        log_layout.addWidget(self.log_view)
        content_layout.addWidget(log_group)

        # 4. 하단 시작 버튼
        self.btn_start = QtWidgets.QPushButton("▶ 홍보방 자동 인입 시작")
        self.btn_start.setObjectName("StartBtn")
        self.btn_start.setFixedHeight(50)
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_macro)
        content_layout.addWidget(self.btn_start)

        main_layout.addLayout(content_layout)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.inp_api_id.setText(data.get("api_id", ""))
                    self.inp_api_hash.setText(data.get("api_hash", ""))
                    self.inp_phone.setText(data.get("phone", ""))
                    
                    links = data.get("links", [])
                    if isinstance(links, str): 
                        links = links.split('\n')
                    for link in links:
                        if link.strip():
                            self.list_links.addItem(link.strip())
            except: pass

    def save_config(self):
        links = [self.list_links.item(i).text() for i in range(self.list_links.count())]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "api_id": self.inp_api_id.text(),
                "api_hash": self.inp_api_hash.text(),
                "phone": self.inp_phone.text(),
                "links": links
            }, f, indent=4)

    def add_link(self):
        link = self.inp_new_link.text().strip()
        if link:
            self.list_links.addItem(link)
            self.inp_new_link.clear()
            self.save_config()

    def del_link(self):
        current_row = self.list_links.currentRow()
        if current_row >= 0:
            self.list_links.takeItem(current_row)
            self.save_config()

    def check_session(self):
        if os.path.exists(os.path.join(DATA_DIR, "joiner_session.session")):
            self.log("✅ 기존 로그인 세션이 발견되었습니다. 바로 인입 시작이 가능합니다.")
            self.btn_start.setEnabled(True)

    def request_auth_code(self):
        self.save_config()
        if not all([self.inp_api_id.text(), self.inp_api_hash.text(), self.inp_phone.text()]):
            return self.log("⚠️ API ID, HASH, 전화번호를 모두 입력하세요.")
        
        try:
            safe_api_id = int(self.inp_api_id.text().strip())
        except ValueError:
            return self.log("⚠️ 오류: API ID는 숫자만 입력해야 합니다.")
        
        self.btn_send_code.setEnabled(False)
        self.login_worker = LoginWorker(safe_api_id, self.inp_api_hash.text().strip(), self.inp_phone.text().strip())
        self.login_worker.log_signal.connect(self.log)
        self.login_worker.auth_code_needed.connect(self.show_auth_input)
        self.login_worker.password_needed.connect(self.show_2fa_input)
        self.login_worker.start()

    def show_auth_input(self, phone_code_hash):
        self.phone_code_hash = phone_code_hash
        self.auth_widget.setVisible(True)
        self.two_fa_widget.setVisible(False)
        self.btn_send_code.setEnabled(True)

    def submit_auth_code(self):
        code = self.inp_code.text().strip()
        if not code: return
        
        try:
            safe_api_id = int(self.inp_api_id.text().strip())
        except ValueError:
            return self.log("⚠️ 오류: API ID는 숫자만 입력해야 합니다.")

        self.btn_login.setEnabled(False)
        
        # 인증번호를 받아 sign_in 시도 (2단계 비밀번호가 걸려있다면 여기서 에러를 감지하고 2FA 입력창으로 분기)
        self.login_worker = LoginWorker(safe_api_id, self.inp_api_hash.text().strip(), self.inp_phone.text().strip(), self.phone_code_hash, code)
        self.login_worker.log_signal.connect(self.log)
        self.login_worker.password_needed.connect(self.show_2fa_input)
        self.login_worker.login_success.connect(self.on_login_success)
        self.login_worker.start()

    def show_2fa_input(self):
        self.auth_widget.setVisible(False)
        self.two_fa_widget.setVisible(True)
        self.btn_login.setEnabled(True)
        self.btn_send_code.setEnabled(True)

    def submit_2fa_password(self):
        pwd = self.inp_password.text().strip()
        if not pwd: return
        
        try:
            safe_api_id = int(self.inp_api_id.text().strip())
        except ValueError:
            return self.log("⚠️ 오류: API ID는 숫자만 입력해야 합니다.")

        self.btn_login_2fa.setEnabled(False)
        
        # 2단계 인증 비밀번호 검증 실행
        self.login_worker = LoginWorker(safe_api_id, self.inp_api_hash.text().strip(), self.inp_phone.text().strip(), password=pwd)
        self.login_worker.log_signal.connect(self.log)
        self.login_worker.login_success.connect(self.on_login_success)
        self.login_worker.start()

    def on_login_success(self):
        self.auth_widget.setVisible(False)
        self.two_fa_widget.setVisible(False)
        self.btn_start.setEnabled(True)
        self.btn_login.setEnabled(True)
        self.btn_login_2fa.setEnabled(True)
        self.btn_send_code.setEnabled(True)

    def start_macro(self):
        self.save_config()
        links = [self.list_links.item(i).text() for i in range(self.list_links.count())]
        
        if not links:
            return self.log("⚠️ 추가된 홍보방 링크가 없습니다.")
            
        try:
            safe_api_id = int(self.inp_api_id.text().strip())
        except ValueError:
            return self.log("⚠️ 오류: API ID는 숫자만 입력해야 합니다.")
            
        self.btn_start.setEnabled(False)
        self.btn_start.setText("⏳ 인입 작업 진행 중...")
        
        self.join_worker = JoinWorker(safe_api_id, self.inp_api_hash.text().strip(), links)
        self.join_worker.log_signal.connect(self.log)
        self.join_worker.finished_signal.connect(self.on_macro_finished)
        self.join_worker.start()

    def on_macro_finished(self):
        self.log("✅ 모든 방 인입 스크립트가 종료되었습니다.")
        self.btn_start.setEnabled(True)
        self.btn_start.setText("▶ 홍보방 자동 인입 시작")

    def log(self, text):
        self.log_view.append(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = AutoJoinerApp()
    win.show()
    sys.exit(app.exec_())
