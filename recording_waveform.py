"""
Timeline editable avec blocs colores pour la lumiere
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QCursor


class RecordingWaveform(QWidget):
    """Timeline editable avec blocs colores pour la lumiere"""

    def __init__(self):
        super().__init__()
        self.blocks = []  # Blocs lumiere {start_ms, end_ms, color, level}
        self.duration = 0
        self.current_position = 0
        self.dragging_block = None
        self.drag_edge = None
        self.drag_start_x = 0
        self.drag_start_time = 0
        self.setStyleSheet("background: #1a1a1a; border-radius: 4px;")
        self.setMouseTracking(True)

    def add_block(self, start_ms, end_ms, color, level):
        """Ajoute un bloc de couleur"""
        self.blocks.append({
            'start': start_ms,
            'end': end_ms,
            'color': color,
            'level': level
        })
        self.update()

    def add_keyframe(self, time_ms, faders, pad_color, effect_name=""):
        """Convertit un keyframe en bloc"""
        if not pad_color:
            pad_color = QColor("#666666")
        self.blocks.append({
            'start':  time_ms,
            'end':    time_ms + 500,
            'color':  pad_color,
            'level':  faders[0] if faders else 0,
            'effect': effect_name,
        })
        self.update()

    def set_position(self, position_ms, duration_ms):
        """Met a jour la position actuelle"""
        self.current_position = position_ms
        self.duration = duration_ms
        self.update()

    def clear(self):
        """Efface la timeline"""
        self.blocks = []
        self.duration = 0
        self.current_position = 0
        self.update()

    def mousePressEvent(self, event):
        """Detecte les clics sur les blocs"""
        if self.duration == 0:
            return

        x = event.position().x()
        w = self.width()

        for block in self.blocks:
            start_x = (block['start'] / self.duration) * w
            end_x = (block['end'] / self.duration) * w

            if abs(x - start_x) < 5:
                self.dragging_block = block
                self.drag_edge = 'left'
                return

            if abs(x - end_x) < 5:
                self.dragging_block = block
                self.drag_edge = 'right'
                return

            if start_x < x < end_x:
                self.dragging_block = block
                self.drag_edge = 'middle'
                self.drag_start_x = x
                self.drag_start_time = block['start']
                return

    def mouseMoveEvent(self, event):
        """Gere le drag des blocs"""
        if not self.dragging_block or self.duration == 0:
            x = event.position().x()
            w = self.width()
            cursor_set = False

            for block in self.blocks:
                start_x = (block['start'] / self.duration) * w
                end_x = (block['end'] / self.duration) * w

                if abs(x - start_x) < 5 or abs(x - end_x) < 5:
                    self.setCursor(QCursor(Qt.SizeHorCursor))
                    cursor_set = True
                    break
                elif start_x < x < end_x:
                    self.setCursor(QCursor(Qt.OpenHandCursor))
                    cursor_set = True
                    break

            if not cursor_set:
                self.setCursor(QCursor(Qt.ArrowCursor))
            return

        x = event.position().x()
        w = self.width()
        time_at_x = (x / w) * self.duration

        if self.drag_edge == 'left':
            self.dragging_block['start'] = max(0, min(time_at_x, self.dragging_block['end'] - 100))
        elif self.drag_edge == 'right':
            self.dragging_block['end'] = max(self.dragging_block['start'] + 100, min(time_at_x, self.duration))
        elif self.drag_edge == 'middle':
            delta_x = x - self.drag_start_x
            delta_time = (delta_x / w) * self.duration
            new_start = self.drag_start_time + delta_time
            block_duration = self.dragging_block['end'] - self.dragging_block['start']

            if new_start < 0:
                new_start = 0
            if new_start + block_duration > self.duration:
                new_start = self.duration - block_duration

            self.dragging_block['start'] = new_start
            self.dragging_block['end'] = new_start + block_duration

        self.update()

    def mouseReleaseEvent(self, event):
        self.dragging_block = None
        self.drag_edge = None
        self.setCursor(QCursor(Qt.ArrowCursor))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # Fond
        painter.fillRect(0, 0, w, h, QColor("#1a1a1a"))

        if self.duration == 0:
            painter.setPen(QColor("#666666"))
            painter.drawText(5, 15, "Timeline Lumiere")
            return

        # Grille temporelle — pas adaptatif : ne jamais tracer plus de ~120 lignes.
        # Sans ça, un show de 40 min dessinerait 2400 lignes à chaque repaint.
        total_sec = int(self.duration / 1000)
        if total_sec > 0:
            step = max(1, total_sec // 120)
            painter.setPen(QPen(QColor("#2a2a2a"), 1))
            for sec in range(0, total_sec + 1, step):
                x = (sec * 1000 / self.duration) * w
                painter.drawLine(int(x), 0, int(x), h)

        # Blocs
        painter.setPen(Qt.NoPen)
        font = painter.font()
        font.setPixelSize(9)
        font.setBold(False)
        painter.setFont(font)
        for block in self.blocks:
            start_x = int((block['start'] / self.duration) * w)
            end_x = int((block['end'] / self.duration) * w)
            block_width = max(2, end_x - start_x)

            color = QColor(block['color'])
            opacity = int(255 * (block['level'] / 100.0)) if block['level'] > 0 else 50
            color.setAlpha(opacity)

            painter.setBrush(color)
            painter.drawRect(start_x, 0, block_width, h)

            painter.setPen(QPen(color.lighter(150), 1))
            painter.drawRect(start_x, 0, block_width, h)
            painter.setPen(Qt.NoPen)

            # Bande orange + nom d'effet
            eff = block.get('effect', '')
            if eff:
                painter.setBrush(QColor(255, 140, 0, 200))
                painter.drawRect(start_x, 0, block_width, 6)
                if block_width > 24:
                    painter.setPen(QColor("#ffffff"))
                    painter.drawText(start_x + 2, 6, block_width - 4, h - 6,
                                     Qt.AlignLeft | Qt.AlignVCenter, eff)
                    painter.setPen(Qt.NoPen)

        # Curseur
        if self.current_position > 0:
            x = int((self.current_position / self.duration) * w)
            painter.setPen(QPen(QColor("#00d4ff"), 3))
            painter.drawLine(x, 0, x, h)

        # Label
        if len(self.blocks) > 0:
            painter.setPen(QColor("#00d4ff"))
            font = painter.font()
            font.setBold(True)
            font.setPixelSize(10)
            painter.setFont(font)
            painter.drawText(5, 12, f"{len(self.blocks)} blocs")

    def get_blocks_data(self):
        """Retourne les donnees des blocs pour sauvegarde"""
        return [
            {
                'start': b['start'],
                'end': b['end'],
                'color': b['color'].name() if isinstance(b['color'], QColor) else b['color'],
                'level': b['level']
            }
            for b in self.blocks
        ]

    def load_blocks_data(self, blocks_data):
        """Charge des blocs depuis des donnees sauvegardees"""
        self.blocks = []
        for b in blocks_data:
            self.blocks.append({
                'start': b['start'],
                'end': b['end'],
                'color': QColor(b['color']),
                'level': b['level']
            })
        self.update()
