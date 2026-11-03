import sys
import os
import json
import asyncio
import random
import re
import time
from collections import deque
from urllib.parse import urlsplit
from datetime import datetime
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from hydrogram import Client, filters
from hydrogram.handlers import MessageHandler, EditedMessageHandler
from hydrogram.errors import FloodWait, SessionPasswordNeeded, UserAlreadyParticipant
from hydrogram.types import InlineKeyboardMarkup

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

    # 신규 인증 메시지는 이 시간 동안 탐색합니다. 전체 3분 제한과는 다르게,
    # 인증 문구가 *도착하는 시점*을 기다리는 시간입니다.
    INITIAL_VERIFY_WAIT = 40.0
    FOLLOWUP_VERIFY_WAIT = 12.0
    MAX_VERIFY_WINDOW = 180.0

    # 본인 계정 지정이 없는 일반 인증 메시지를 자동으로 누르지 않습니다.
    # 다른 신규 입장자의 버튼을 누르는 사고를 방지하기 위한 설정입니다.
    REQUIRE_PERSONAL_TARGET = True

    VERIFY_TERMS = ("인증", "확인", "입장", "참여", "구독", "가입", "버튼", "verify", "verification", "join")
    VERIFY_BUTTONS = ("인증", "확인", "완료", "입장", "참여", "통과", "시작", "verify", "check", "confirm", "continue", "start")
    CHANNEL_BUTTONS = ("채널", "구독", "가입", "join", "subscribe")
    DANGEROUS_BUTTONS = ("취소", "거절", "탈퇴", "나가기", "차단", "신고", "cancel", "reject", "leave", "report")

    def __init__(self, api_id, api_hash, links):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.links = links
        self._is_running = True

    def stop(self):
        self._is_running = False

    async def cancellable_sleep(self, delay):
        end_time = time.monotonic() + max(0, delay)
        while self._is_running and time.monotonic() < end_time:
            await asyncio.sleep(min(0.2, max(0.0, end_time - time.monotonic())))

    def run(self):
        try:
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            asyncio.run(self.auto_join())
        except Exception as e:
            self.log_signal.emit(f"❌ 작업 스레드 오류: {type(e).__name__}: {e}")
        finally:
            self.finished_signal.emit()

    @staticmethod
    def normalize_link(link):
        link = link.strip()
        if link.startswith('@'):
            return link[1:], True
        if not link.startswith(('https://', 'http://')) and 't.me/' in link:
            link = 'https://' + link
        if link.startswith(('https://', 'http://')):
            parsed = urlsplit(link)
            if parsed.hostname not in ('t.me', 'telegram.me', 'www.t.me'):
                raise ValueError("지원하지 않는 그룹 링크 도메인입니다.")
            path = parsed.path.strip('/')
            if not path:
                raise ValueError("그룹 링크가 비어 있습니다.")
            if path.startswith('+') or path.startswith('joinchat/'):
                return link, False  # 비공개 링크는 잘라내지 않고 그대로 사용
            if '/' not in path and path not in ('c', 's'):
                return path, True
            raise ValueError(f"그룹 링크의 형식을 인식하지 못했습니다: {link}")
        if re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{4,31}', link):
            return link, True
        raise ValueError(f"지원하지 않는 링크 형식입니다: {link}")

    @staticmethod
    def _is_recent(message, joined_at):
        # UTC datetime 혹은 timestamp를 비교합니다. 입장 직전부터의 메시지만 탐색합니다.
        msg_date = getattr(message, 'date', None)
        edit_date = getattr(message, 'edit_date', None)
        timestamps = []
        for dt in (msg_date, edit_date):
            if dt is None:
                continue
            try:
                # Hydrogram의 naive date는 UTC로 취급
                from datetime import timezone
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                timestamps.append(dt.timestamp())
            except (AttributeError, ValueError, TypeError):
                pass
        return bool(timestamps) and max(timestamps) >= joined_at - 3.0

    @staticmethod
    def _is_for_me(msg, me):
        if getattr(msg, 'mentioned', False):
            return True
        text = str(getattr(msg, 'text', None) or getattr(msg, 'caption', None) or '')
        username = getattr(me, 'username', None)
        if username and re.search(r'(?<!\w)@' + re.escape(username) + r'(?!\w)', text, flags=re.IGNORECASE):
            return True
        if re.search(r'(?<!\d)' + re.escape(str(me.id)) + r'(?!\d)', text):
            return True
        # 표시 이름만으로 판정하면 동명이인 오인식이 생길 수 있어
        # "홍길동님" 같은 호칭이 있는 경우로 한정합니다.
        first_name = getattr(me, 'first_name', None)
        if first_name and len(first_name) >= 2:
            if re.search(r'(?<!\w)' + re.escape(first_name) + r'\s*님(?!\w)', text):
                return True
        for entity in ((getattr(msg, 'entities', None) or []) + (getattr(msg, 'caption_entities', None) or [])):
            user = getattr(entity, 'user', None)
            if user and getattr(user, 'id', None) == me.id:
                return True
            url = str(getattr(entity, 'url', '') or '')
            if re.search(r'tg://user\?id=' + re.escape(str(me.id)) + r'(?!\d)', url):
                return True
        replied = getattr(msg, 'reply_to_message', None)
        if replied:
            author = getattr(replied, 'from_user', None)
            if author and getattr(author, 'id', None) == me.id:
                return True
            for member in (getattr(replied, 'new_chat_members', None) or []):
                if getattr(member, 'id', None) == me.id:
                    return True
        return False

    @staticmethod
    def _is_tg_channel_url(url):
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ('https', 'http') or parsed.hostname not in ('t.me', 'telegram.me', 'www.t.me'):
                return False
            path = parsed.path.strip('/')
            # Bot start 링크/댓글 링크/웹앱은 채널 참가 링크와 달라 자동 처리하지 않음
            if not path or path.startswith(('s/', 'c/', 'share/', 'addstickers/')):
                return False
            if parsed.query and ('start=' in parsed.query or 'startapp=' in parsed.query):
                return False
            return path.startswith('+') or path.startswith('joinchat/') or '/' not in path
        except Exception:
            return False

    async def _process_verification_message(self, app, msg, me, joined_at,
                                            completed_steps, subscribed_channels):
        markup = getattr(msg, 'reply_markup', None)
        if not isinstance(markup, InlineKeyboardMarkup):
            return False, False
        if not getattr(msg, 'chat', None) or not self._is_recent(msg, joined_at):
            return False, False

        sender = getattr(msg, 'from_user', None)
        if not sender or not getattr(sender, 'is_bot', False):
            return False, False  # 인증봇 이외 메시지는 자동 클릭하지 않음

        text = str(getattr(msg, 'text', None) or getattr(msg, 'caption', None) or '')
        rows = markup.inline_keyboard or []
        buttons = [button for row in rows for button in row]
        button_labels = ' '.join(str(getattr(b, 'text', '') or '') for b in buttons).lower()
        hint = (text + ' ' + button_labels).lower()
        if not any(term in hint for term in self.VERIFY_TERMS):
            return False, False

        targeted = self._is_for_me(msg, me)
        if not targeted and self.REQUIRE_PERSONAL_TARGET:
            self.log_signal.emit(
                f"⚠️ [{msg.chat.id}] 인증 형태 메시지 발견 (ID {msg.id}), "
                "하지만 내 계정 대상인지 확인되지 않아 자동 클릭 생략"
            )
            return False, False

        acted = False
        subscription_failed = False
        for button in buttons:
            label = str(getattr(button, 'text', '') or '')
            label_lower = label.lower()
            url = getattr(button, 'url', None)
            if not url or not any(word in label_lower for word in self.CHANNEL_BUTTONS):
                continue
            if not self._is_tg_channel_url(url):
                self.log_signal.emit(f"ℹ️ [{msg.chat.id}] 직접 처리 필요한 외부/봇 링크: {label} ({url})")
                subscription_failed = True
                continue
            if url in subscribed_channels:
                continue
            self.log_signal.emit(f"🔗 [{msg.chat.id}] '{label}' 채널 링크 참가 시도: {url}")
            try:
                await app.join_chat(url)
                subscribed_channels.add(url)
                acted = True
                self.log_signal.emit(f"✅ [{msg.chat.id}] 채널 참가 요청 처리됨: {label}")
            except UserAlreadyParticipant:
                subscribed_channels.add(url)
                acted = True
                self.log_signal.emit(f"✅ [{msg.chat.id}] 이미 구독 중인 채널: {label}")
            except Exception as e:
                subscription_failed = True
                self.log_signal.emit(f"⚠️ [{msg.chat.id}] 채널 참가 실패: {type(e).__name__}: {e}")
                if isinstance(e, FloodWait):
                    return acted, True

        # 채널 구독이 실패했으면 구독 완료 버튼을 눌러 성공인 것처럼 표시하지 않습니다.
        if subscription_failed:
            self.log_signal.emit(f"⚠️ [{msg.chat.id}] 구독 선행 조건 미완료. 콜백 클릭 보류")
            return acted, True

        callback_buttons = []
        for button in buttons:
            data = getattr(button, 'callback_data', None)
            if data is None:
                continue
            label = str(getattr(button, 'text', '') or '')
            lower = label.lower()
            if any(blocked in lower for blocked in self.DANGEROUS_BUTTONS):
                continue
            if any(word in lower for word in self.VERIFY_BUTTONS):
                callback_buttons.append(button)

        # '60초 이내 버튼 클릭' 등의 안내가 있는데 콜백 버튼이 한 개인 경우
        # 버튼 이름이 특이해도 검증 버튼으로 간주합니다. 단, 위험 레이블 제외.
        if not callback_buttons:
            available = [b for b in buttons if getattr(b, 'callback_data', None) is not None
                         and not any(x in str(getattr(b, 'text', '') or '').lower() for x in self.DANGEROUS_BUTTONS)]
            if len(available) == 1 and any(w in hint for w in ('1분', '3분', '60초', '180초', 'within', '버튼')):
                callback_buttons = available

        if callback_buttons:
            # 다수의 콜백을 무작정 모두 누르지 않고 가장 가능성이 높은 하나만 처리
            priority = ('구독 완료', '구독완료', '가입 완료', '인증 완료', '인증', '확인', '입장', '완료', 'verify', 'confirm')
            callback_buttons.sort(key=lambda b: next(
                (i for i, p in enumerate(priority) if p in str(getattr(b, 'text', '') or '').lower()),
                len(priority)))
            button = callback_buttons[0]
            label = str(getattr(button, 'text', '') or '')
            raw_data = getattr(button, 'callback_data', None)
            signature = (msg.chat.id, msg.id, str(raw_data))
            if signature not in completed_steps:
                try:
                    self.log_signal.emit(f"👆 [{msg.chat.id}] '{label}' 버튼 누르는 중...")
                    response = await app.request_callback_answer(
                        chat_id=msg.chat.id, message_id=msg.id,
                        callback_data=raw_data, timeout=10
                    )
                    completed_steps.add(signature)
                    acted = True
                    answer = getattr(response, 'message', None)
                    if answer:
                        self.log_signal.emit(f"🤖 [{msg.chat.id}] 인증봇 응답: {answer}")
                    else:
                        self.log_signal.emit(f"✅ [{msg.chat.id}] '{label}' 콜백 요청 전송됨 (인증 최종 성공은 별도 확인 필요)")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ [{msg.chat.id}] '{label}' 버튼 실패: {type(e).__name__}: {e}")
                    if isinstance(e, FloodWait):
                        return acted, True
        return acted, True

    async def handle_bot_verification(self, app, chat_id, me, joined_at, message_queue, buffer):
        self.log_signal.emit(f"🔍 [{chat_id}] 봇 인증 탐색 시작 (기본 {int(self.INITIAL_VERIFY_WAIT)}초)...")
        completed_steps = set()
        subscribed_channels = set()
        examined = set()
        actions = 0
        candidates = list(buffer)
        try:
            async for message in app.get_chat_history(chat_id, limit=30):
                candidates.append(message)
        except Exception as e:
            self.log_signal.emit(f"⚠️ [{chat_id}] 최근 메시지 조회 실패: {e}")

        async def process(message):
            nonlocal actions
            if not getattr(message, 'chat', None) or message.chat.id != chat_id:
                return False
            # edit_version이 다를 때 같은 메시지를 다시 확인
            version = str(getattr(message, 'edit_date', None) or '')
            keyboard = getattr(getattr(message, 'reply_markup', None), 'inline_keyboard', []) or []
            signature = (message.id, version, str([(getattr(b, 'text', None), getattr(b, 'callback_data', None)) for r in keyboard for b in r]))
            if signature in examined:
                return False
            examined.add(signature)
            acted, relevant = await self._process_verification_message(
                app, message, me, joined_at, completed_steps, subscribed_channels
            )
            if acted:
                actions += 1
            return relevant

        for message in candidates:
            if not self._is_running:
                break
            await process(message)

        absolute_end = time.monotonic() + self.MAX_VERIFY_WINDOW
        idle_end = time.monotonic() + (self.FOLLOWUP_VERIFY_WAIT if actions else self.INITIAL_VERIFY_WAIT)
        while self._is_running:
            seconds = min(idle_end, absolute_end) - time.monotonic()
            if seconds <= 0:
                break
            try:
                # 1초 간격으로 중단 여부를 확인하여 종료 버튼에 빠르게 반응합니다.
                message = await asyncio.wait_for(message_queue.get(), timeout=min(seconds, 1.0))
            except asyncio.TimeoutError:
                continue
            relevant = await process(message)
            if relevant:
                # 유관 메시지를 감지한 뒤에는 후속 편집/봇 메시지를 추가로 기다림
                idle_end = min(absolute_end, time.monotonic() + self.FOLLOWUP_VERIFY_WAIT)

        if actions:
            self.log_signal.emit(f"✅ [{chat_id}] 인증 관련 조작 {actions}회 수행. 최종 가입 권한은 직접/추가 검증 필요")
        else:
            self.log_signal.emit(f"ℹ️ [{chat_id}] 본인 대상 인증 조작 없음 (미존재/미감지/수동 인증 필요 가능)")

    async def join_and_verify(self, app, target, me):
        # 반드시 join_chat 실행 전에 핸들러를 등록합니다.
        # 입장 이벤트와 동시에 도착하는 인증 메시지의 누락을 방지합니다.
        messages = asyncio.Queue(maxsize=120)
        early_messages = deque(maxlen=120)
        current_chat_id = None

        async def watch_message(client, message):
            if not getattr(message, 'chat', None):
                return
            if current_chat_id is None:
                early_messages.append(message)
            elif message.chat.id == current_chat_id:
                if messages.full():
                    try:
                        messages.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                messages.put_nowait(message)

        handler_new = app.add_handler(MessageHandler(watch_message, filters.group), group=70)
        handler_edit = app.add_handler(EditedMessageHandler(watch_message, filters.group), group=70)
        try:
            joined_at = time.time()
            joined_chat = await app.join_chat(target)
            current_chat_id = joined_chat.id
            self.log_signal.emit(f"✅ 입장 완료: {target} (채팅 ID: {current_chat_id})")
            await self.handle_bot_verification(
                app, current_chat_id, me, joined_at, messages, list(early_messages)
            )
            return joined_chat
        finally:
            app.remove_handler(*handler_new)
            app.remove_handler(*handler_edit)

    async def auto_join(self):
        app = Client('joiner_session', api_id=self.api_id, api_hash=self.api_hash, workdir=DATA_DIR)
        self.log_signal.emit("\n🚀 자동 인입 + 가입 후 인증 탐색 시작...")
        async with app:
            me = await app.get_me()
            self.log_signal.emit(f"👤 계정 인식: {me.first_name} (ID: {me.id})")
            joined_public_chats = set()
            try:
                async for dialog in app.get_dialogs():
                    if not self._is_running:
                        break
                    if dialog.chat and dialog.chat.username:
                        joined_public_chats.add(dialog.chat.username.lower())
                self.log_signal.emit(f"💡 이미 가입한 공개방 {len(joined_public_chats)}개 확인")
            except Exception as e:
                self.log_signal.emit(f"⚠️ 기존 가입 목록 조회 오류: {e}")

            for idx, link in enumerate(self.links, start=1):
                if not self._is_running:
                    self.log_signal.emit('🛑 중단 요청 감지')
                    break
                if not link.strip():
                    continue
                self.log_signal.emit(f"\n📊 [{idx}/{len(self.links)}] 처리: {link}")
                try:
                    target, is_public = self.normalize_link(link)
                except ValueError as e:
                    self.log_signal.emit(f"❌ 링크 형식 오류: {e}")
                    continue
                if is_public and target.lower() in joined_public_chats:
                    self.log_signal.emit(f"⏩ 이미 참가한 공개방 스킵: {target}")
                    continue
                while self._is_running:
                    try:
                        await self.join_and_verify(app, target, me)
                        if is_public:
                            joined_public_chats.add(target.lower())
                        await self.cancellable_sleep(random.uniform(15, 35))
                        break
                    except UserAlreadyParticipant:
                        self.log_signal.emit(f"⏩ 이미 참가한 방 스킵: {link}")
                        if is_public:
                            joined_public_chats.add(target.lower())
                        break
                    except FloodWait as e:
                        wait_time = int(e.value)
                        self.log_signal.emit(f"🚨 서버 요청 제한: {wait_time}초 대기")
                        await self.cancellable_sleep(wait_time)
                        if not self._is_running:
                            break
                        await self.cancellable_sleep(random.uniform(60, 120))
                    except Exception as e:
                        self.log_signal.emit(f"❌ 그룹 참가/검증 실패 ({link}): {type(e).__name__}: {e}")
                        break

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
            QPushButton:disabled { background-color: #0f172a; color: #334155; border: 1px solid #1e293b; }
            
            QPushButton#LoginBtn { background-color: #1e232d; color: #60a5fa; border: 1px solid #2d3748; border-radius: 10px; font-size: 15px; font-weight: bold; }
            QPushButton#LoginBtn:hover { background-color: #2a3140; border: 1px solid #3b82f6; color: #93c5fd; }
            QPushButton#LoginBtn:pressed { background-color: #1a1e27; padding-top: 2px; }
            
            QPushButton#StartBtn { background-color: #172a22; color: #4ade80; border: 1px solid #204a31; border-radius: 10px; font-size: 16px; font-weight: bold; letter-spacing: 1px; }
            QPushButton#StartBtn:hover { background-color: #1e3b2e; border: 1px solid #22c55e; color: #86efac; }
            QPushButton#StartBtn:pressed { background-color: #111f18; padding-top: 2px; }
            QPushButton#StartBtn:disabled { background-color: #0f172a; color: #334155; border: 1px solid #1e293b; }

            QPushButton#StopBtn { background-color: #2d1e23; color: #f87171; border: 1px solid #4a2d35; border-radius: 10px; font-size: 16px; font-weight: bold; letter-spacing: 1px; }
            QPushButton#StopBtn:hover { background-color: #3f2a31; border: 1px solid #ef4444; color: #fca5a5; }
            QPushButton#StopBtn:pressed { background-color: #1a1e27; padding-top: 2px; }
            QPushButton#StopBtn:disabled { background-color: #0f172a; color: #334155; border: 1px solid #1e293b; }
            
            QPushButton#DelBtn { background-color: #2d1e23; color: #f87171; border: 1px solid #4a2d35; border-radius: 8px; font-size: 13px; font-weight: bold; }
            QPushButton#DelBtn:hover { background-color: #3f2a31; border: 1px solid #ef4444; color: #fca5a5; }

            QPushButton#LoadTxtBtn { background-color: #1e3a8a; color: #bfdbfe; border: 1px solid #1e40af; border-radius: 8px; font-size: 13px; font-weight: bold; }
            QPushButton#LoadTxtBtn:hover { background-color: #1e40af; border: 1px solid #3b82f6; color: #ffffff; }
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
        self.btn_add_link.setFixedWidth(60)
        self.btn_add_link.clicked.connect(self.add_link)

        self.btn_load_txt = QtWidgets.QPushButton("TXT 불러오기")
        self.btn_load_txt.setObjectName("LoadTxtBtn")
        self.btn_load_txt.setFixedHeight(40)
        self.btn_load_txt.setFixedWidth(100)
        self.btn_load_txt.clicked.connect(self.load_txt_file)
        
        self.btn_del_link = QtWidgets.QPushButton("선택 삭제")
        self.btn_del_link.setObjectName("DelBtn")
        self.btn_del_link.setFixedHeight(40)
        self.btn_del_link.setFixedWidth(80)
        self.btn_del_link.clicked.connect(self.del_link)
        
        link_input_row.addWidget(self.inp_new_link)
        link_input_row.addWidget(self.btn_add_link)
        link_input_row.addWidget(self.btn_load_txt)
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
        self.log_view.setStyleSheet("background-color: #090d16; color: #38bdf8; font-family: 'Consolas', monospace; font-size: 12px; border: 1px solid #1f2937; border-radius: 8px; padding: 10px;")
        log_layout.addWidget(self.log_view)
        content_layout.addWidget(log_group)

        # --- 4. 하단 컨트롤 버튼 ---
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setSpacing(10)

        self.btn_start = QtWidgets.QPushButton("▶ 홍보방 자동 인입 시작")
        self.btn_start.setObjectName("StartBtn")
        self.btn_start.setFixedHeight(55)
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_macro)

        self.btn_stop = QtWidgets.QPushButton("⏹ 인입 중단")
        self.btn_stop.setObjectName("StopBtn")
        self.btn_stop.setFixedHeight(55)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_macro)

        bottom_layout.addWidget(self.btn_start)
        bottom_layout.addWidget(self.btn_stop)
        
        content_layout.addLayout(bottom_layout)
        main_layout.addLayout(content_layout)

    # ----------------------------------------
    # 데이터 로드 / 세이브 / 텍스트 불러오기
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
            existing_links = [self.list_links.item(i).text() for i in range(self.list_links.count())]
            if link not in existing_links:
                self.list_links.addItem(link)
                self.inp_new_link.clear()
                self.save_config()
            else:
                QtWidgets.QMessageBox.warning(self, "중복", "이미 리스트에 존재하는 링크입니다.")

    def del_link(self):
        current_row = self.list_links.currentRow()
        if current_row >= 0:
            self.list_links.takeItem(current_row)
            self.save_config()

    def load_txt_file(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "메모장 파일 불러오기", "", "Text Files (*.txt);;All Files (*)")
        if not file_path:
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='cp949') as f:
                    lines = f.readlines()
            except Exception as e:
                return QtWidgets.QMessageBox.critical(self, "파일 읽기 실패", f"파일을 읽는 중 오류가 발생했습니다:\n{str(e)}")
        except Exception as e:
            return QtWidgets.QMessageBox.critical(self, "파일 읽기 실패", f"파일을 읽는 중 오류가 발생했습니다:\n{str(e)}")

        added_count = 0
        existing_links = [self.list_links.item(i).text() for i in range(self.list_links.count())]

        for line in lines:
            link = line.strip()
            if link and link not in existing_links:
                self.list_links.addItem(link)
                existing_links.append(link)
                added_count += 1
        
        if added_count > 0:
            self.save_config()
            self.log(f"📁 텍스트 파일에서 {added_count}개의 링크를 성공적으로 불러왔습니다.")
            QtWidgets.QMessageBox.information(self, "불러오기 완료", f"총 {added_count}개의 링크가 성공적으로 추가되었습니다.")
        else:
            QtWidgets.QMessageBox.warning(self, "불러오기 결과", "추가할 새로운 링크가 없거나 파일이 비어있습니다.")

    def check_session(self):
        if os.path.exists(os.path.join(DATA_DIR, "joiner_session.session")):
            self.log("✅ 기존 로그인 세션이 발견되었습니다. 바로 인입 시작이 가능합니다.")
            self.btn_start.setEnabled(True)

    def log(self, text):
        time_str = datetime.now().strftime("%H:%M:%S")
        
        if text.startswith("\n"):
            clean_text = text.lstrip('\n')
            formatted_text = f"\n[{time_str}] {clean_text}"
        else:
            formatted_text = f"[{time_str}] {text}"
            
        self.log_view.append(formatted_text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    # ----------------------------------------
    # 다이얼로그 로그인 로직
    # ----------------------------------------
    async def perform_full_login(self, phone, api_id, api_hash):
        app = Client("joiner_session", api_id=api_id, api_hash=api_hash, workdir=DATA_DIR)
        await app.connect()
        try:
            self.log("텔레그램 서버로 인증번호 발송 요청 중...")
            sent = await app.send_code(phone)
            
            code, ok = QtWidgets.QInputDialog.getText(self, "인증번호 입력", f"{phone} 계정으로 전송된\n숫자 인증번호를 입력하세요:")
            if not ok or not code.strip(): 
                raise ValueError("인증번호 입력이 취소되었습니다.")
                
            try:
                self.log("로그인 승인 진행 중...")
                await app.sign_in(phone, sent.phone_code_hash, code.strip())
            except SessionPasswordNeeded:
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
    # 자동 인입기 작동 및 중단 제어
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
        self.btn_stop.setEnabled(True)
        
        self.join_worker = JoinWorker(api_id, self.inp_api_hash.text().strip(), links)
        self.join_worker.log_signal.connect(self.log)
        self.join_worker.finished_signal.connect(self.on_macro_finished)
        self.join_worker.start()

    def stop_macro(self):
        if hasattr(self, 'join_worker') and self.join_worker.isRunning():
            self.log("⚠️ 중단 신호 전송 완료... 현재 작업을 안전하게 종료하는 중입니다.")
            self.btn_stop.setEnabled(False)
            self.btn_stop.setText("종료 대기 중...")
            self.join_worker.stop()

    def on_macro_finished(self):
        self.log("✅ 인입 스크립트가 안전하게 종료되었습니다.")
        self.btn_start.setEnabled(True)
        self.btn_start.setText("▶ 홍보방 자동 인입 시작")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("⏹ 인입 중단")

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
