import sys
import os
import json
import asyncio
import random
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QProcess, Qt, QThread, pyqtSignal
from hydrogram import Client
from hydrogram.errors import FloodWait, SessionPasswordNeeded

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# .exe 실행 환경과 파이썬 스크립트 실행 환경 모두 완벽 대응
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "joiner_config.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ==========================================
# 🎨 1. 커스텀 타이틀바 (기존 코드에서 추출)
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
# ⚙️ 2. 텔레그램 백그라운드 워커 (로그인/인입)
# ==========================================
class LoginWorker(QThread):
    log_signal = pyqtSignal(str)
    auth_code_needed = pyqtSignal(str)
    login_success = pyqtSignal()

    def __init__(self, api_id, api_hash, phone, phone_code_hash=None, auth_code=None):
        super().__init__()
        self.api_id, self.api_hash, self.phone = api_id, api_hash, phone
        self.phone_code_hash, self.auth_code = phone_code_hash, auth_code

    def run(self): asyncio.run(self.process_login())

    async def process_login(self):
        app = Client("joiner_session", api_id=self.api_id, api_hash=self.api_hash, workdir=DATA_DIR)
        await app.connect()
        try:
            if not self.auth_code:
                self.log_signal.emit("텔레그램 서버로 인증번호 발송 요청 중...")
                sent = await app.send_code(self.phone)
                self.log_signal.emit("✅ 인증번호 발송 완료! 앱을 확인해주세요.")
                self.auth_code_needed.emit(sent.phone_code_hash)
            else:
                self.log_signal.emit("로그인 승인 진행 중...")
                await app.sign_in(self.phone, self.phone_code_hash, self.auth_code)
                self.log_signal.emit("✅ 로그인 성공! 이제 세션이 유지됩니다.")
                self.login_success.emit()
        except SessionPasswordNeeded:
            self.log_signal.emit("❌ 2단계 인증이 설정되어 있습니다. 해제 후 다시 시도해주세요.")
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

    def run(self): asyncio.run(self.auto_join())

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
                        
                        # 사람처럼 보이도록 불규칙한 안전 딜레이 적용 (15~35초)
                        delay = random.uniform(15, 35)
                        self.log_signal.emit(f"휴식: {int(delay)}초 대기...")
                        await asyncio.sleep(delay)

                    except FloodWait as e:
                        wait_time = e.value
                        self.log_signal.emit(f"🚨 [플러드 웨이트 감지] 서버 제한 조치로 {wait_time}초 동안 1차 대기합니다.")
                        await asyncio.sleep(wait_time)
                        
                        # 제한 해제 직후 즉시 재가입 방지를 위한 3~5분(180~300초) 추가 랜덤 딜레이
                        extra_delay = random.uniform(180, 300)
                        self.log_signal.emit(f"🛡️ [계정 보호] 제한이 풀렸으나 안전을 위해 {int(extra_delay)}초(약 {int(extra_delay/60)}분) 추가 대기합니다...")
                        await asyncio.sleep(extra_delay)
                        
                        self.log_signal.emit(f"🔄 안전 대기 종료. {link} 입장 재시도 진행...")
                        
                    except Exception as e:
                        self.log_signal.emit(f"❌ 입장 실패 ({link}): {e}")
                        break # 알 수 없는 오류(방 삭제 등) 시 다음 방으로 넘어감
                        
        self.finished_signal.emit()

# ==========================================
# 🚀 3. 메인 UI (기존 테마 및 QSS 이식)
# ==========================================
class AutoJoinerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(600, 750)
        self.phone_code_hash = None
        self.init_ui()
        self.load_config()
        self.check_session()

    def init_ui(self):
        self.central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.central_widget)
        self.central_widget.setObjectName("MainContainer")
        
        # 🔥 기존 매크로의 메인 CSS 복사 및 이식
        self.central_widget.setStyleSheet("""
            * { font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif; }
            QWidget#MainContainer { background-color: #0b0f19; border-radius: 16px; border: 1px solid #1e293b; }
            QLabel { color: #e2e8f0; font-size: 13px; font-weight: bold; }
            QLineEdit, QTextEdit { 
                background-color: #1e293b; border: 2px solid #334155; border-radius: 8px; 
                padding: 10px; color: #f8fafc; font-weight: bold; font-size: 13px; 
            }
            QLineEdit:focus, QTextEdit:focus { border: 2px solid #3b82f6; background-color: #0f172a; color: #60a5fa; }
            QGroupBox { border: 2px solid #334155; border-radius: 12px; margin-top: 15px; padding-top: 15px; font-weight: bold; color: #94a3b8; background-color: #0f172a; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 15px; top: 0px; background-color: #1e293b; padding: 2px 10px; color: #60a5fa; border-radius: 6px;}
            QPushButton { background-color: #1e232d; color: #94a3b8; border: 1px solid #2d3748; border-radius: 8px; font-size: 13px; font-weight: bold; padding: 8px; }
            QPushButton:hover { background-color: #2a3140; border: 1px solid #475569; color: #e2e8f0; }
            QPushButton#LoginBtn { background-color: #1e232d; color: #60a5fa; border: 1px solid #2d3748; border-radius: 10px; font-size: 14px; font-weight: bold; }
            QPushButton#LoginBtn:hover { background-color: #2a3140; border: 1px solid #3b82f6; color: #93c5fd; }
            QPushButton#StartBtn { background-color: #172a22; color: #4ade80; border: 1px solid #204a31; border-radius: 10px; font-size: 16px; font-weight: bold; letter-spacing: 1px; }
            QPushButton#StartBtn:hover { background-color: #1e3b2e; border: 1px solid #22c55e; color: #86efac; }
            QPushButton#StartBtn:disabled { background-color: #0f172a; color: #475569; border: 1px solid #1e293b; }
        """)

        main_layout = QtWidgets.QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. 타이틀바
        self.title_bar = CustomTitleBar(self)
        main_layout.addWidget(self.title_bar)

        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setContentsMargins(20, 10, 20, 20)
        content_layout.setSpacing(15)

        # 2. API 로그인 섹션
        api_group = QtWidgets.QGroupBox("1. API 및 계정 연동 (세션 유지됨)")
        api_layout = QtWidgets.QVBoxLayout(api_group)
        
        row1 = QtWidgets.QHBoxLayout()
        self.inp_api_id = QtWidgets.QLineEdit(); self.inp_api_id.setPlaceholderText("API ID")
        self.inp_api_hash = QtWidgets.QLineEdit(); self.inp_api_hash.setPlaceholderText("API HASH")
        row1.addWidget(self.inp_api_id); row1.addWidget(self.inp_api_hash)
        api_layout.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        self.inp_phone = QtWidgets.QLineEdit(); self.inp_phone.setPlaceholderText("전화번호 (+82...)")
        self.btn_send_code = QtWidgets.QPushButton("인증 요청")
        self.btn_send_code.setObjectName("LoginBtn")
        self.btn_send_code.clicked.connect(self.request_auth_code)
        row2.addWidget(self.inp_phone); row2.addWidget(self.btn_send_code)
        api_layout.addLayout(row2)

        self.auth_widget = QtWidgets.QWidget()
        auth_layout = QtWidgets.QHBoxLayout(self.auth_widget)
        auth_layout.setContentsMargins(0, 0, 0, 0)
        self.inp_code = QtWidgets.QLineEdit(); self.inp_code.setPlaceholderText("텔레그램 인증번호 5자리")
        self.btn_login = QtWidgets.QPushButton("로그인 승인")
        self.btn_login.setObjectName("LoginBtn")
        self.btn_login.clicked.connect(self.submit_auth_code)
        auth_layout.addWidget(self.inp_code); auth_layout.addWidget(self.btn_login)
        self.auth_widget.setVisible(False)
        api_layout.addWidget(self.auth_widget)

        content_layout.addWidget(api_group)

        # 3. 홍보방 리스트 섹션
        link_group = QtWidgets.QGroupBox("2. 타겟 홍보방 링크 리스트 (엔터로 구분)")
        link_layout = QtWidgets.QVBoxLayout(link_group)
        self.inp_links = QtWidgets.QTextEdit()
        link_layout.addWidget(self.inp_links)
        content_layout.addWidget(link_group)

        # 4. 콘솔 로그 섹션 (기존 터미널 테마 적용)
        log_group = QtWidgets.QGroupBox("💻 시스템 라이브 콘솔 로그")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #090d16; color: #38bdf8; font-family: 'Consolas', monospace; font-size: 12px; border: 1px solid #1f2937;")
        log_layout.addWidget(self.log_view)
        content_layout.addWidget(log_group)

        # 5. 하단 시작 버튼
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
                    self.inp_links.setPlainText(data.get("links", ""))
            except: pass

    def save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "api_id": self.inp_api_id.text(),
                "api_hash": self.inp_api_hash.text(),
                "phone": self.inp_phone.text(),
                "links": self.inp_links.toPlainText()
            }, f, indent=4)

    def check_session(self):
        if os.path.exists(os.path.join(DATA_DIR, "joiner_session.session")):
            self.log("✅ 기존 로그인 세션이 발견되었습니다. 바로 인입 시작이 가능합니다.")
            self.btn_start.setEnabled(True)

    def request_auth_code(self):
        self.save_config()
        if not all([self.inp_api_id.text(), self.inp_api_hash.text(), self.inp_phone.text()]):
            return self.log("⚠️ API ID, HASH, 전화번호를 모두 입력하세요.")
        
        self.btn_send_code.setEnabled(False)
        self.login_worker = LoginWorker(int(self.inp_api_id.text()), self.inp_api_hash.text(), self.inp_phone.text())
        self.login_worker.log_signal.connect(self.log)
        self.login_worker.auth_code_needed.connect(self.show_auth_input)
        self.login_worker.start()

    def show_auth_input(self, phone_code_hash):
        self.phone_code_hash = phone_code_hash
        self.auth_widget.setVisible(True)
        self.btn_send_code.setEnabled(True)

    def submit_auth_code(self):
        code = self.inp_code.text().strip()
        if not code: return
        self.btn_login.setEnabled(False)
        
        self.login_worker = LoginWorker(int(self.inp_api_id.text()), self.inp_api_hash.text(), self.inp_phone.text(), self.phone_code_hash, code)
        self.login_worker.log_signal.connect(self.log)
        self.login_worker.login_success.connect(self.on_login_success)
        self.login_worker.start()

    def on_login_success(self):
        self.auth_widget.setVisible(False)
        self.btn_start.setEnabled(True)
        self.btn_login.setEnabled(True)

    def start_macro(self):
        self.save_config()
        links = self.inp_links.toPlainText().split('\n')
        self.btn_start.setEnabled(False)
        self.btn_start.setText("⏳ 인입 작업 진행 중...")
        
        self.join_worker = JoinWorker(int(self.inp_api_id.text()), self.inp_api_hash.text(), links)
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
