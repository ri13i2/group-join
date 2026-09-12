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

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.dirname(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "joiner_config.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ==========================================
# 🎨 1. 커스텀 타이틀바 (VIP 대시보드 테마 적용)
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

        btn_min.setStyleSheet("""
            QPushButton { color: #94a3b8; background: transparent; border: none; font-weight: bold; font-size: 14px; border-radius: 8px; } 
            QPushButton:hover { color: #e2e8f0; background: #334155; }
        """)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #991b1b; color: #fca5a5; border: 1px solid #7f1d1d; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover {
                background-color: #dc2626; color: white; border: 1px solid #ef4444;
            }
        """)

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
# ⚙️ 2. 자동 인입 백그라운드 워커
# ==========================================
class JoinWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, api_id, api_hash, links):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.links = links

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
                        self.log_signal.emit(f"🚨 [플러드 웨이트] 서버 제한 조치로 {wait_time}초 대기합니다.")
                        await asyncio.sleep(wait_time)
                        
                        extra_delay = random.uniform(180, 300)
                        self.log_signal.emit(f"🛡️ [계정 보호] 추가로 {int(extra_delay)}초 대기합니다...")
                        await asyncio.sleep(extra_delay)
                        
                    except Exception as e:
                        self.log_signal.emit(f"❌ 입장 실패 ({link}): {e}")
                        break 
                        
        self.finished_signal.emit()

# ==========================================
# 🚀 3. 메인 대시보드 UI
# ==========================================
class AutoJoinerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(650, 850)
        
        self.init_ui()
        self.load_config()
        self.check_session()

    def init_ui(self):
        self.central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.central_widget)
        self.central_widget.setObjectName("MainContainer")
        
        # 제공해주신 VIP 대시보드 테마 CSS 완벽 이식
        self.central_widget.setStyleSheet("""
            * { font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif; }
            QWidget#MainContainer { background-color: #0b0f19; border-radius: 16px; border: 1px solid #1e293b; }
            QLabel { color: #e2e8f0; font-size: 14px; font-weight: bold; }
            
            QLineEdit, QTextEdit { 
                background-color: #1e293b; border: 2px solid #334155; border-radius: 8px; 
                padding: 10px 12px; color: #f8fafc; font-weight: bold; font-size: 13px; 
                selection-background-color: #3b82f6; selection-color: #ffffff;
            }
            QLineEdit:focus, QTextEdit:focus { 
                border: 2px solid #3b82f6; background-color: #0f172a; color: #60a5fa;
            }
            
            QListWidget { background-color: #1e293b; border: 2px solid #334155; border-radius: 8px; color: #f8fafc; outline: none; }
            QListWidget::item { padding: 8px 10px; font-weight: bold; font-size: 13px; border-radius: 6px; margin-bottom: 4px; background-color: #1e232d; border: 1px solid #2d3748; }
            QListWidget::item:hover { background-color: #2a3140; border: 1px solid #475569; color: #e2e8f0; }
            QListWidget::item:selected { background-color: #2563eb; color: #ffffff; border: 1px solid #1d4ed8; }
            
            QGroupBox { border: 2px solid #334155; border-radius: 12px; margin-top: 18px; padding-top: 20px; font-weight: bold; color: #94a3b8; background-color: #0f172a; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 20px; top: 0px; background-color: #1e293b; padding: 0 12px; color: #60a5fa; font-size: 14px; letter-spacing: 1px; border-radius: 6px;}
            
            QPushButton { 
                background-color: #1e232d; color: #94a3b8; border: 1px solid #2d3748; 
                border-radius: 8px; font-size: 13px; font-weight: bold; padding: 8px;
            }
            QPushButton:hover { background-color: #2a3140; border: 1px solid #475569; color: #e2e8f0; }
            QPushButton:pressed { background-color: #1a1e27; padding-top: 10px; padding-bottom: 6px; }
            QPushButton:disabled { background-color: #0f172a; color: #475569; border: 1px solid #1e293b; }
            
            QPushButton#LoginBtn { background-color: #1e232d; color: #60a5fa; border: 1px solid #2d3748; border-radius: 10px; font-size: 15px; font-weight: bold; }
            QPushButton#LoginBtn:hover { background-color: #2a3140; border: 1px solid #3b82f6; color: #93c5fd; }
            QPushButton#LoginBtn:pressed { background-color: #1a1e27; padding-top: 2px; }
            
            QPushButton#StartBtn { background-color: #172a22; color: #4ade80; border: 1px solid #204a31; border-radius: 10px; font-size: 16px; font-weight: bold; letter-spacing: 1px; }
            QPushButton#StartBtn:hover { background-color: #1e3b2e; border: 1px solid #22c55e; color: #86efac; }
            QPushButton#StartBtn:pressed { background-color: #111f18; padding-top: 2px; }
            
            QPushButton#DelBtn { background-color: #2d1e23; color: #f87171; border: 1px solid #4a2d35; border-radius: 8px; font-size: 13px; font-weight: bold; }
            QPushButton#DelBtn:hover { background-color: #3f2a31; border: 1px solid #ef4444; color: #fca5a5; }
        """)

        main_layout = QtWidgets.QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        main_layout.addWidget(self.title_bar)

        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setContentsMargins(20, 15, 20, 20)
        content_layout.setSpacing(15)

        # --- 1. API 및 로그인 섹션 ---
        api_group = QtWidgets.QGroupBox("1. API 및 계정 연동 (다이얼로그 로그인)")
        api_layout = QtWidgets.QVBoxLayout(api_group)
        api_layout.setContentsMargins(15, 25, 15, 15)
        api_layout.setSpacing(12)
        
        row1 = QtWidgets.QHBoxLayout()
        self.inp_api_id = QtWidgets.QLineEdit(); self.inp_api_id.setPlaceholderText("API ID (숫자)")
        self.inp_api_hash = QtWidgets.QLineEdit(); self.inp_api_hash.setPlaceholderText("API HASH")
        self.inp_api_id.setFixedHeight(45); self.inp_api_hash.setFixedHeight(45)
        row1.addWidget(self.inp_api_id); row1.addWidget(self.inp_api_hash)
        api_layout.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        self.inp_phone = QtWidgets.QLineEdit(); self.inp_phone.setPlaceholderText("전화번호 입력 (+82...)")
        self.inp_phone.setFixedHeight(45)
        
        self.btn_login = QtWidgets.QPushButton("텔레그램 보안 로그인")
        self.btn_login.setObjectName("LoginBtn")
        self.btn_login.setFixedHeight(45)
        self.btn_login.clicked.connect(self.start_login_sequence)
        
        row2.addWidget(self.inp_phone); row2.addWidget(self.btn_login)
        api_layout.addLayout(row2)
        content_layout.addWidget(api_group)

        # --- 2. 타겟 홍보방 관리 섹션 ---
        link_group = QtWidgets.QGroupBox("2. 타겟 홍보방 링크 리스트")
        link_layout = QtWidgets.QVBoxLayout(link_group)
        link_layout.setContentsMargins(15, 25, 15, 15)
        link_layout.setSpacing(10)
        
        link_input_row = QtWidgets.QHBoxLayout()
        self.inp_new_link = QtWidgets.QLineEdit()
        self.inp_new_link.setPlaceholderText("https://t.me/...")
        self.inp_new_link.setFixedHeight(40)
        
        self.btn_add_link = QtWidgets.QPushButton("추가")
        self.btn_add_link.setFixedHeight(40)
        self.btn_add_link.setFixedWidth(80)
        self.btn_add_link.clicked.connect(self.add_link)
        
        self.btn_del_link = QtWidgets.QPushButton("선택 삭제")
        self.btn_del_link.setObjectName("DelBtn")
        self.btn_del_link.setFixedHeight(40)
        self.btn_del_link.setFixedWidth(90)
        self.btn_del_link.clicked.connect(self.del_link)
        
        link_input_row.addWidget(self.inp_new_link)
        link_input_row.addWidget(self.btn_add_link)
        link_input_row.addWidget(self.btn_del_link)
        link_layout.addLayout(link_input_row)
        
        self.list_links = QtWidgets.QListWidget()
        link_layout.addWidget(self.list_links)
        content_layout.addWidget(link_group)

        # --- 3. 시스템 로그 섹션 ---
        log_group = QtWidgets.QGroupBox("💻 시스템 라이브 콘솔 로그")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        log_layout.setContentsMargins(15, 25, 15, 15)
        
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        # 터미널 느낌의 로그 뷰 디자인
        self.log_view.setStyleSheet("background-color: #090d16; color: #38bdf8; font-family: 'Consolas', monospace; font-size: 12px; border: 1px solid #1f2937; border-radius: 8px; padding: 10px;")
        log_layout.addWidget(self.log_view)
        content_layout.addWidget(log_group)

        # --- 4. 하단 컨트롤 버튼 ---
        self.btn_start = QtWidgets.QPushButton("▶ 홍보방 자동 인입 시작")
        self.btn_start.setObjectName("StartBtn")
        self.btn_start.setFixedHeight(55)
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_macro)
        content_layout.addWidget(self.btn_start)

        main_layout.addLayout(content_layout)

    # ----------------------------------------
    # 데이터 로드 / 세이브
    # ----------------------------------------
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.inp_api_id.setText(str(data.get("api_id", "")))
                    self.inp_api_hash.setText(data.get("api_hash", ""))
                    self.inp_phone.setText(data.get("phone", ""))
                    
                    for link in data.get("links", []):
                        if link.strip():
                            self.list_links.addItem(link.strip())
            except: pass

    def save_config(self):
        links = [self.list_links.item(i).text() for i in range(self.list_links.count())]
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "api_id": self.inp_api_id.text().strip(),
                    "api_hash": self.inp_api_hash.text().strip(),
                    "phone": self.inp_phone.text().strip(),
                    "links": links
                }, f, indent=4)
        except: pass

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

    def log(self, text):
        self.log_view.append(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    # ----------------------------------------
    # 제공해주신 VIP 대시보드 다이얼로그 로그인 로직 완벽 이식
    # ----------------------------------------
    async def perform_full_login(self, phone, api_id, api_hash):
        app = Client("joiner_session", api_id=api_id, api_hash=api_hash, workdir=DATA_DIR)
        await app.connect()
        try:
            self.log("텔레그램 서버로 인증번호 발송 요청 중...")
            sent = await app.send_code(phone)
            
            # 1단계: 인증번호 다이얼로그
            code, ok = QtWidgets.QInputDialog.getText(self, "인증번호 입력", f"{phone} 계정으로 전송된\n숫자 인증번호를 입력하세요:")
            if not ok or not code.strip(): 
                raise ValueError("인증번호 입력이 취소되었습니다.")
                
            try:
                self.log("로그인 승인 진행 중...")
                await app.sign_in(phone, sent.phone_code_hash, code.strip())
            except SessionPasswordNeeded:
                # 2단계: 2차 암호 다이얼로그
                self.log("🔒 2단계 인증(비밀번호)이 감지되었습니다.")
                pwd, ok = QtWidgets.QInputDialog.getText(self, "2단계 인증 필요", "해당 계정은 2단계 보안이 설정되어 있습니다.\n텔레그램 암호를 입력해주세요:", QtWidgets.QLineEdit.Password)
                if not ok or not pwd.strip(): 
                    raise ValueError("2단계 암호 입력이 취소되었습니다.")
                
                await app.check_password(pwd.strip())
                
        finally:
            await app.disconnect()

    def start_login_sequence(self):
        self.save_config()
        phone = self.inp_phone.text().strip()
        api_id_str = self.inp_api_id.text().strip()
        api_hash = self.inp_api_hash.text().strip()
        
        if not all([api_id_str, api_hash, phone]):
            return QtWidgets.QMessageBox.warning(self, "입력 오류", "API ID, HASH, 전화번호를 모두 입력해주세요.")
            
        try:
            api_id = int(api_id_str)
        except ValueError:
            return QtWidgets.QMessageBox.warning(self, "입력 오류", "API ID는 숫자만 입력해야 합니다.")

        self.btn_login.setText("텔레그램 보안 연결 중...")
        self.btn_login.setEnabled(False)
        QtWidgets.QApplication.processEvents()

        try:
            # VIP 대시보드에서 사용한 asyncio.run 방식 그대로 적용
            asyncio.run(self.perform_full_login(phone, api_id, api_hash))
            QtWidgets.QMessageBox.information(self, "로그인 성공", "계정 연동이 완벽하게 완료되었습니다!")
            self.log("✅ 로그인 성공! 이제 세션이 유지되며 인입 시작이 가능합니다.")
            self.btn_start.setEnabled(True)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "로그인 실패", f"오류가 발생했습니다:\n{str(e)}")
            self.log(f"❌ 로그인 실패: {str(e)}")
        finally:
            self.btn_login.setText("텔레그램 보안 로그인")
            self.btn_login.setEnabled(True)

    # ----------------------------------------
    # 자동 인입기 작동
    # ----------------------------------------
    def start_macro(self):
        self.save_config()
        links = [self.list_links.item(i).text() for i in range(self.list_links.count())]
        
        if not links:
            return QtWidgets.QMessageBox.warning(self, "경고", "추가된 타겟 홍보방 링크가 없습니다.")
            
        try:
            api_id = int(self.inp_api_id.text().strip())
        except ValueError:
            return QtWidgets.QMessageBox.warning(self, "경고", "API ID 설정이 올바르지 않습니다.")
            
        self.btn_start.setEnabled(False)
        self.btn_start.setText("⏳ 인입 작업 진행 중...")
        
        # 백그라운드 워커 실행
        self.join_worker = JoinWorker(api_id, self.inp_api_hash.text().strip(), links)
        self.join_worker.log_signal.connect(self.log)
        self.join_worker.finished_signal.connect(self.on_macro_finished)
        self.join_worker.start()

    def on_macro_finished(self):
        self.log("✅ 모든 방 인입 스크립트가 종료되었습니다.")
        self.btn_start.setEnabled(True)
        self.btn_start.setText("▶ 홍보방 자동 인입 시작")

if __name__ == "__main__":
    QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QtWidgets.QApplication(sys.argv)
    
    font = QtGui.QFont("Pretendard", 10)
    font.setStyleStrategy(QtGui.QFont.PreferAntialias)
    app.setFont(font)
    
    win = AutoJoinerApp()
    win.show()
    sys.exit(app.exec_())
