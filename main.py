"""
RemoteLink Android Client
Build with Buildozer → APK

Features:
- Share Android screen to PC (via WebSocket)
- View PC screen and control it with touch
- Virtual keyboard relay
- Android key events (back, home, etc.)
"""

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.image import Image as KivyImage
from kivy.uix.scrollview import ScrollView
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.utils import platform

import asyncio
import websockets
import threading
import json
import io
import time
import logging
import base64

# Android screen capture (Kivy/Android)
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from jnius import autoclass, cast
    MediaProjectionManager = autoclass('android.media.projection.MediaProjectionManager')
    ImageReader = autoclass('android.media.ImageReader')
    PixelFormat = autoclass('android.graphics.PixelFormat')
    Surface = autoclass('android.view.Surface')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── CONFIG ─────────────────────────────────────────────────────────────────
SERVER_URL = "ws://89.167.32.140:8765"  # <-- Change this!
ROOM_ID = "myroom123"
SCREEN_FPS = 8
SCREEN_QUALITY = 35
# ────────────────────────────────────────────────────────────────────────────

class RemoteLinkAndroid(App):
    def __init__(self):
        super().__init__()
        self.ws = None
        self.loop = None
        self.connected = False
        self.streaming = False
        self.pc_frame_texture = None
        self.last_touch_pos = None
        
    def build(self):
        Window.clearcolor = (0.07, 0.07, 0.11, 1)
        
        # Request Android permissions
        if platform == 'android':
            request_permissions([
                Permission.INTERNET,
                Permission.RECORD_AUDIO,
            ])
        
        root = BoxLayout(orientation='vertical', spacing=0)
        
        # ── Header ──
        header = BoxLayout(size_hint_y=None, height=55, padding=[10,5])
        with header.canvas.before:
            Color(0.086, 0.129, 0.243, 1)
            self.header_rect = Rectangle(size=header.size, pos=header.pos)
        header.bind(size=lambda w,s: setattr(self.header_rect, 'size', s))
        header.bind(pos=lambda w,p: setattr(self.header_rect, 'pos', p))
        
        header.add_widget(Label(text='[b]RemoteLink[/b]', markup=True,
                                  font_size='18sp', color=(0.914, 0.271, 0.376, 1),
                                  size_hint_x=0.5, halign='left'))
        
        self.status_lbl = Label(text='● Disconnected', font_size='12sp',
                                  color=(1, 0.42, 0.42, 1), size_hint_x=0.5, halign='right')
        header.add_widget(self.status_lbl)
        root.add_widget(header)
        
        # ── Connection bar ──
        conn = BoxLayout(size_hint_y=None, height=45, padding=[8,5], spacing=5)
        with conn.canvas.before:
            Color(0.086, 0.129, 0.243, 1)
            self.conn_rect = Rectangle(size=conn.size, pos=conn.pos)
        conn.bind(size=lambda w,s: setattr(self.conn_rect, 'size', s))
        conn.bind(pos=lambda w,p: setattr(self.conn_rect, 'pos', p))
        
        self.server_input = TextInput(text=SERVER_URL, multiline=False,
                                       background_color=(0.06, 0.204, 0.376, 1),
                                       foreground_color=(1,1,1,1),
                                       font_size='12sp', size_hint_x=0.55,
                                       hint_text='ws://SERVER_IP:8765')
        conn.add_widget(self.server_input)
        
        self.room_input = TextInput(text=ROOM_ID, multiline=False,
                                     background_color=(0.06, 0.204, 0.376, 1),
                                     foreground_color=(1,1,1,1),
                                     font_size='12sp', size_hint_x=0.25,
                                     hint_text='Room')
        conn.add_widget(self.room_input)
        
        self.conn_btn = Button(text='Connect', size_hint_x=0.2,
                                background_color=(0.914, 0.271, 0.376, 1),
                                font_size='12sp', bold=True)
        self.conn_btn.bind(on_press=self.toggle_connection)
        conn.add_widget(self.conn_btn)
        root.add_widget(conn)
        
        # ── Tabs ──
        tabs = TabbedPanel(do_default_tab=False)
        
        # Tab 1: PC Screen Viewer
        pc_tab = TabbedPanelItem(text='🖥 PC Screen')
        pc_tab.add_widget(self.build_pc_screen_tab())
        tabs.add_widget(pc_tab)
        
        # Tab 2: Share my screen
        share_tab = TabbedPanelItem(text='📱 My Screen')
        share_tab.add_widget(self.build_share_tab())
        tabs.add_widget(share_tab)
        
        # Tab 3: Chat
        chat_tab = TabbedPanelItem(text='💬 Chat')
        chat_tab.add_widget(self.build_chat_tab())
        tabs.add_widget(chat_tab)
        
        root.add_widget(tabs)
        return root
    
    def build_pc_screen_tab(self):
        """Shows PC screen, touch to control"""
        layout = BoxLayout(orientation='vertical', padding=5, spacing=5)
        
        info = Label(text='Touch to control PC mouse', font_size='11sp',
                      color=(0.659, 0.659, 0.7, 1), size_hint_y=None, height=25)
        layout.add_widget(info)
        
        # PC screen image
        self.pc_screen = KivyImage(allow_stretch=True, keep_ratio=True)
        self.pc_screen.bind(on_touch_down=self.on_touch_pc)
        self.pc_screen.bind(on_touch_move=self.on_drag_pc)
        self.pc_screen.bind(on_touch_up=self.on_release_pc)
        layout.add_widget(self.pc_screen)
        
        # PC control buttons
        btn_row = GridLayout(cols=4, size_hint_y=None, height=45, spacing=3)
        pc_keys = [('Win', 'win'), ('Alt+F4', 'alt_f4'), ('Ctrl+Z', 'ctrl_z'),
                   ('Enter', 'enter'), ('Esc', 'escape'), ('Tab', 'tab'),
                   ('Copy', 'ctrl_c'), ('Paste', 'ctrl_v')]
        for label, key in pc_keys:
            b = Button(text=label, background_color=(0.086, 0.129, 0.243, 1),
                        font_size='11sp', bold=True)
            b.bind(on_press=lambda btn, k=key: self.send_pc_key(k))
            btn_row.add_widget(b)
        layout.add_widget(btn_row)
        
        # Type text for PC
        type_row = BoxLayout(size_hint_y=None, height=40, spacing=5)
        self.type_input = TextInput(hint_text='Type text to PC...', multiline=False,
                                     background_color=(0.06, 0.204, 0.376, 1),
                                     foreground_color=(1,1,1,1), font_size='13sp')
        self.type_input.bind(on_text_validate=self.send_type_to_pc)
        type_row.add_widget(self.type_input)
        send_btn = Button(text='Send', size_hint_x=0.2,
                           background_color=(0.302, 0.8, 0.639, 1),
                           bold=True, font_size='12sp')
        send_btn.bind(on_press=self.send_type_to_pc)
        type_row.add_widget(send_btn)
        layout.add_widget(type_row)
        
        return layout
    
    def build_share_tab(self):
        """Share Android screen"""
        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)
        
        layout.add_widget(Label(text='Share your Android screen to PC',
                                  font_size='14sp', color=(0.659, 0.659, 0.7, 1)))
        
        self.share_status_lbl = Label(text='Not streaming', font_size='16sp',
                                        color=(0.659, 0.659, 0.7, 1))
        layout.add_widget(self.share_status_lbl)
        
        note = Label(
            text='[b]Note:[/b] On Android, screen capture requires\nMediaProjection permission.\nA permission dialog will appear when you start.',
            markup=True, font_size='11sp', color=(1, 0.8, 0.3, 1),
            halign='center'
        )
        layout.add_widget(note)
        
        self.share_btn = Button(text='▶  Start Sharing', font_size='16sp', bold=True,
                                  background_color=(0.302, 0.8, 0.639, 1),
                                  color=(0.07, 0.07, 0.11, 1),
                                  size_hint_y=None, height=60)
        self.share_btn.bind(on_press=self.toggle_share)
        layout.add_widget(self.share_btn)
        
        # FPS/Quality info
        layout.add_widget(Label(text=f'FPS: {SCREEN_FPS}  |  Quality: {SCREEN_QUALITY}%',
                                  font_size='11sp', color=(0.5, 0.5, 0.5, 1)))
        
        return layout
    
    def build_chat_tab(self):
        layout = BoxLayout(orientation='vertical', padding=5, spacing=5)
        
        sv = ScrollView()
        self.chat_label = Label(text='', markup=True, font_size='12sp',
                                   color=(0.88, 0.88, 0.88, 1), size_hint_y=None,
                                   halign='left', valign='top', text_size=(Window.width-20, None))
        self.chat_label.bind(texture_size=lambda w,s: setattr(w, 'height', s[1]))
        sv.add_widget(self.chat_label)
        layout.add_widget(sv)
        
        row = BoxLayout(size_hint_y=None, height=45, spacing=5)
        self.chat_input = TextInput(hint_text='Message...', multiline=False,
                                     background_color=(0.06, 0.204, 0.376, 1),
                                     foreground_color=(1,1,1,1), font_size='13sp')
        self.chat_input.bind(on_text_validate=self.send_chat)
        row.add_widget(self.chat_input)
        
        send_btn = Button(text='Send', size_hint_x=0.2,
                           background_color=(0.914, 0.271, 0.376, 1), bold=True)
        send_btn.bind(on_press=self.send_chat)
        row.add_widget(send_btn)
        layout.add_widget(row)
        
        return layout
    
    # ── Connection ──────────────────────────────────────────────────────────────
    
    def toggle_connection(self, *args):
        if not self.connected:
            url = self.server_input.text.strip()
            room = self.room_input.text.strip()
            
            self.loop = asyncio.new_event_loop()
            t = threading.Thread(target=self._run_ws, args=(url, room), daemon=True)
            t.start()
        else:
            self.disconnect()
    
    def _run_ws(self, url, room):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._ws_client(url, room))
    
    async def _ws_client(self, url, room):
        try:
            self._update_status("Connecting...", (1, 0.8, 0, 1))
            async with websockets.connect(url, max_size=20*1024*1024) as ws:
                self.ws = ws
                self.connected = True
                
                await ws.send(json.dumps({
                    'type': 'join',
                    'room_id': room,
                    'role': 'android',
                    'name': 'Android Device'
                }))
                
                self._update_status("✅ Connected", (0.302, 0.8, 0.639, 1))
                Clock.schedule_once(lambda dt: setattr(self.conn_btn, 'text', 'Disconnect'))
                
                async for message in ws:
                    await self.handle_message(message)
                    
        except Exception as e:
            self._update_status(f"❌ {str(e)[:30]}", (1, 0.42, 0.42, 1))
        finally:
            self.connected = False
            self.ws = None
            self._update_status("● Disconnected", (1, 0.42, 0.42, 1))
            Clock.schedule_once(lambda dt: setattr(self.conn_btn, 'text', 'Connect'))
    
    async def handle_message(self, message):
        if isinstance(message, bytes):
            # PC screen frame
            Clock.schedule_once(lambda dt: self.update_pc_frame(message))
            return
        
        try:
            data = json.loads(message)
            t = data.get('type')
            
            if t == 'joined':
                self.append_chat(f"[color=4ecca3][System] Joined room. Peers: {data.get('peers',0)}[/color]")
            elif t == 'peer_joined':
                self.append_chat(f"[color=4ecca3][System] {data.get('name')} connected![/color]")
            elif t == 'peer_left':
                self.append_chat(f"[color=ff6b6b][System] {data.get('name')} left[/color]")
            elif t == 'control':
                Clock.schedule_once(lambda dt: self.execute_android_control(data))
            elif t == 'chat':
                self.append_chat(f"[color=e94560]🖥 {data.get('from')}:[/color] {data.get('text')}")
                
        except Exception as e:
            logger.error(f"Msg error: {e}")
    
    def update_pc_frame(self, frame_bytes):
        """Display PC screen frame"""
        try:
            import numpy as np
            from PIL import Image as PILImage
            
            img = PILImage.open(io.BytesIO(frame_bytes)).convert('RGB')
            img_data = img.tobytes()
            
            texture = Texture.create(size=(img.width, img.height), colorfmt='rgb')
            texture.blit_buffer(img_data, colorfmt='rgb', bufferfmt='ubyte')
            texture.flip_vertical()
            
            self.pc_screen.texture = texture
        except Exception as e:
            logger.error(f"Frame update error: {e}")
    
    def execute_android_control(self, data):
        """Execute control on Android (PC is controlling us)"""
        action = data.get('action')
        
        if platform == 'android':
            try:
                if action == 'android_key':
                    key = data.get('key')
                    # Map PC key commands to Android actions
                    from android import activity
                    if key == 'back':
                        activity.onBackPressed()
                    elif key == 'home':
                        Intent = autoclass('android.content.Intent')
                        intent = Intent(Intent.ACTION_MAIN)
                        intent.addCategory(Intent.CATEGORY_HOME)
                        activity.startActivity(intent)
            except Exception as e:
                logger.error(f"Android control error: {e}")
    
    # ── Screen Sharing ───────────────────────────────────────────────────────────
    
    def toggle_share(self, *args):
        if not self.connected:
            self.append_chat("[color=ff6b6b]Not connected![/color]")
            return
        
        if not self.streaming:
            self.streaming = True
            self.share_btn.text = '⬛ Stop Sharing'
            self.share_btn.background_color = (0.914, 0.271, 0.376, 1)
            self.share_status_lbl.text = '🔴 Streaming...'
            
            t = threading.Thread(target=self._stream_screen, daemon=True)
            t.start()
        else:
            self.streaming = False
            self.share_btn.text = '▶  Start Sharing'
            self.share_btn.background_color = (0.302, 0.8, 0.639, 1)
            self.share_status_lbl.text = 'Not streaming'
    
    def _stream_screen(self):
        """Capture Android screen and send to server"""
        from kivy.graphics.opengl import glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE
        import ctypes
        
        interval = 1.0 / SCREEN_FPS
        last_time = 0
        
        while self.streaming and self.connected:
            now = time.time()
            if now - last_time < interval:
                time.sleep(0.01)
                continue
            
            try:
                # Capture Kivy window as fallback (works on Android too)
                Clock.schedule_once(lambda dt: self._capture_and_send())
                last_time = now
                
            except Exception as e:
                logger.error(f"Stream error: {e}")
                time.sleep(0.5)
    
    def _capture_and_send(self):
        """Capture current Kivy frame and send"""
        try:
            from kivy.graphics.fbo import Fbo
            from kivy.graphics.opengl import glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE
            
            w, h = Window.size
            
            # Read pixels from OpenGL buffer
            data = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
            
            from PIL import Image as PILImage
            import numpy as np
            
            img_array = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
            img_array = np.flipud(img_array)  # Flip vertically
            
            img = PILImage.fromarray(img_array, 'RGBA').convert('RGB')
            
            # Scale down
            new_w = int(w * 0.5)
            new_h = int(h * 0.5)
            img = img.resize((new_w, new_h), PILImage.LANCZOS)
            
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=SCREEN_QUALITY)
            frame_bytes = buf.getvalue()
            
            if self.ws and self.loop:
                asyncio.run_coroutine_threadsafe(self.ws.send(frame_bytes), self.loop)
                
        except Exception as e:
            logger.error(f"Capture error: {e}")
    
    # ── Touch → PC Control ───────────────────────────────────────────────────────
    
    def on_touch_pc(self, widget, touch):
        if widget.collide_point(*touch.pos):
            rx, ry = self._to_relative(touch.pos, widget)
            self.send_control({'action': 'mouse_click', 'x': rx, 'y': ry})
            return True
    
    def on_drag_pc(self, widget, touch):
        if widget.collide_point(*touch.pos):
            rx, ry = self._to_relative(touch.pos, widget)
            self.send_control({'action': 'mouse_move', 'x': rx, 'y': ry})
            return True
    
    def on_release_pc(self, widget, touch):
        pass
    
    def _to_relative(self, pos, widget):
        """Convert absolute touch pos to relative 0-1"""
        wx, wy = widget.pos
        ww, wh = widget.size
        rx = (pos[0] - wx) / ww
        ry = 1.0 - (pos[1] - wy) / wh  # Flip Y
        return max(0, min(1, rx)), max(0, min(1, ry))
    
    def send_pc_key(self, key):
        self.send_control({'action': 'key', 'key': key})
    
    def send_type_to_pc(self, *args):
        text = self.type_input.text.strip()
        if text:
            self.type_input.text = ''
            self.send_control({'action': 'type', 'text': text})
    
    def send_control(self, data):
        if not self.connected or not self.ws:
            return
        data['type'] = 'control'
        try:
            asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(data)), self.loop)
        except Exception as e:
            logger.error(f"Send error: {e}")
    
    # ── Chat ─────────────────────────────────────────────────────────────────────
    
    def send_chat(self, *args):
        text = self.chat_input.text.strip()
        if not text or not self.connected:
            return
        self.chat_input.text = ''
        self.append_chat(f"[color=4ecca3]📱 Me:[/color] {text}")
        self.send_control({'type': 'chat', 'text': text})
    
    def append_chat(self, text):
        def _update(dt):
            self.chat_label.text += f"{text}\n"
        Clock.schedule_once(_update)
    
    def _update_status(self, text, color):
        def _do(dt):
            self.status_lbl.text = text
            self.status_lbl.color = color
        Clock.schedule_once(_do)
    
    def disconnect(self):
        self.streaming = False
        self.connected = False
        if self.ws and self.loop:
            asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)

if __name__ == '__main__':
    RemoteLinkAndroid().run()
