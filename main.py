import sys
import asyncio
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QVBoxLayout, QPushButton, QWidget
from PyQt5.QtCore import QThread, pyqtSignal
from hydrogram import Client
from hydrogram.errors import FloodWait

# 백그라운드 텔레그램 작업 스레드
class TelegramWorker(QThread):
    # UI로 텍스트 로그를 전달하기 위한 시그널
    log_signal = pyqtSignal(str)
    
    def __init__(self, api_id, api_hash, links):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.links = links

    def run(self):
        # QThread 내부에서 비동기 이벤트 루프 실행
        asyncio.run(self.join_groups())

    async def join_groups(self):
        # Hydrogram 클라이언트 세션 생성
        app = Client("my_session", api_id=self.api_id, api_hash=self.api_hash)
        
        async with app:
            for link in self.links:
                joined = False
                while not joined:
                    try:
                        self.log_signal.emit(f"입장 시도 중: {link}")
                        await app.join_chat(link)
                        self.log_signal.emit(f"입장 완료: {link}")
                        joined = True
                        
                        # 정상 가입 후 계정 보호용 기본 딜레이 (10~20초 권장)
                        await asyncio.sleep(15) 

                    except FloodWait as e:
                        wait_time = e.value
                        self.log_signal.emit(f"[경고] 플러드 웨이트 감지! {wait_time}초 대기 후 자동 재시도합니다.")
                        await asyncio.sleep(wait_time)
                        
                    except Exception as e:
                        self.log_signal.emit(f"[오류] {link} 입장 실패: {str(e)}")
                        break

# 메인 UI 창
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("텔레그램 자동 인입기")
        self.resize(500, 400)

        layout = QVBoxLayout()
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        self.start_btn = QPushButton("자동 입장 시작")
        self.start_btn.clicked.connect(self.start_macro)
        layout.addWidget(self.start_btn)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def start_macro(self):
        self.start_btn.setEnabled(False)
        self.log_view.append("프로그램을 시작합니다...")
        
        # API ID와 Hash, 입장할 링크 리스트 입력
        api_id = 1234567  # 본인의 API ID
        api_hash = "본인의_API_HASH"
        links = ["https://t.me/example_group1", "https://t.me/example_group2"]

        self.worker = TelegramWorker(api_id, api_hash, links)
        self.worker.log_signal.connect(self.update_log)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def update_log(self, message):
        # 텔레그램 작업 스레드에서 보낸 메시지를 UI 로그창에 출력
        self.log_view.append(message)

    def on_finished(self):
        self.log_view.append("모든 인입 작업이 종료되었습니다.")
        self.start_btn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
