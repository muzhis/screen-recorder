from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QPoint, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from screen_recorder.recorder.audio import AudioRecorder, list_input_devices, list_wasapi_output_devices
from screen_recorder.recorder.encoder import FFmpegVideoEncoder, mux_video_and_audio
from screen_recorder.recorder.screen import ScreenRecorder
from screen_recorder.ui.region_selector import RegionFrame, RegionSelector
from screen_recorder.utils.config import AppConfig, RecordingRegion


class RecordingWorker(QThread):
    status = pyqtSignal(str)
    failed = pyqtSignal(str)
    finished_recording = pyqtSignal(str)

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self._screen: ScreenRecorder | None = None
        self._audio: AudioRecorder | None = None
        self._encoder: FFmpegVideoEncoder | None = None
        self._stopping = False

    def run(self) -> None:
        try:
            self.config.prepare_paths()
            self.status.emit("启动音频...")
            self._audio = AudioRecorder(self.config)
            self.status.emit(self._audio.start())

            self.status.emit("启动编码...")
            self._encoder = FFmpegVideoEncoder(self.config)
            self._encoder.start()

            self.status.emit("录制中...")
            self._screen = ScreenRecorder(self.config, self._encoder.write_frame)
            self._screen.record_until_stopped(lambda: self._stopping)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            try:
                self._cleanup()
            except Exception as exc:
                self.failed.emit(f"停止录制时出错：{exc}")

    def stop(self) -> None:
        self._stopping = True

    def _cleanup(self) -> None:
        if self._screen:
            self._screen.stop()
        if self._encoder:
            self.status.emit("结束编码...")
            self._encoder.stop()
        if self._audio:
            self.status.emit("保存音频...")
            self._audio.stop()

        if self._stopping and self.config.temp_video_path.exists():
            self.status.emit("合成 MP4...")
            mux_video_and_audio(self.config)
            self.finished_recording.emit(str(self.config.output_path))


class RecordingMiniWidget(QWidget):
    stop_requested = pyqtSignal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(220, 42)

        self._elapsed_seconds = 0
        self._drag_start = QPoint()
        self._window_start = QPoint()

        dot = QLabel("●")
        dot.setObjectName("recordDot")
        title = QLabel("录制中")
        title.setObjectName("miniTitle")
        self.time_label = QLabel("00:00")
        self.time_label.setObjectName("timeLabel")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        layout = QHBoxLayout()
        layout.setContentsMargins(11, 7, 8, 7)
        layout.setSpacing(7)
        layout.addWidget(dot)
        layout.addWidget(title)
        layout.addWidget(self.time_label)
        layout.addStretch()
        layout.addWidget(self.stop_btn)
        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        self.setStyleSheet(
            """
            RecordingMiniWidget {
                background: rgba(31, 35, 43, 238);
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 8px;
            }
            QLabel { color: white; font-size: 12px; }
            #recordDot { color: #ff4d4f; font-size: 15px; }
            #miniTitle { font-weight: 600; }
            #timeLabel { font-family: Consolas, monospace; min-width: 46px; }
            #stopButton {
                background: #ff4d4f;
                color: white;
                border: 0;
                border-radius: 4px;
                padding: 3px 9px;
            }
            #stopButton:hover { background: #ff7875; }
            """
        )

    def start_timer(self) -> None:
        self._elapsed_seconds = 0
        self.time_label.setText("00:00")
        self.timer.start(1000)

    def stop_timer(self) -> None:
        self.timer.stop()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPos()
            self._window_start = self.pos()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self.move(self._window_start + event.globalPos() - self._drag_start)

    def _tick(self) -> None:
        self._elapsed_seconds += 1
        minutes, seconds = divmod(self._elapsed_seconds, 60)
        self.time_label.setText(f"{minutes:02d}:{seconds:02d}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Screen Recorder")
        self.setFixedWidth(520)

        self.config = AppConfig.default()
        self.output_dir = self.config.output_path.parent
        self.worker: RecordingWorker | None = None
        self.region_frame: RegionFrame | None = None
        self.mini_widget: RecordingMiniWidget | None = None

        self.countdown_left = 0
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._tick_countdown)

        self.region_label = QLabel(self._region_text())
        self.region_label.setObjectName("regionLabel")
        self.status_label = QLabel("准备就绪")
        self.status_label.setObjectName("statusLabel")

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(5, 60)
        self.fps_spin.setSingleStep(5)
        self.fps_spin.setValue(self.config.fps)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.setFixedWidth(86)

        self.hide_frame_checkbox = QCheckBox("隐藏选区框")
        self.hide_frame_checkbox.setChecked(True)

        self.record_mic_checkbox = QCheckBox("录入")
        self.record_mic_checkbox.setChecked(True)
        self.record_system_checkbox = QCheckBox("录入")
        self.record_system_checkbox.setChecked(True)

        self.mic_combo = QComboBox()
        self.system_audio_combo = QComboBox()
        self._load_audio_devices()

        self.mic_volume_spin = QSpinBox()
        self.mic_volume_spin.setRange(0, 300)
        self.mic_volume_spin.setSingleStep(10)
        self.mic_volume_spin.setSuffix("%")
        self.mic_volume_spin.setValue(self.config.mic_volume)
        self.mic_volume_spin.setFixedWidth(72)

        self.system_volume_spin = QSpinBox()
        self.system_volume_spin.setRange(0, 300)
        self.system_volume_spin.setSingleStep(10)
        self.system_volume_spin.setSuffix("%")
        self.system_volume_spin.setValue(self.config.system_audio_volume)
        self.system_volume_spin.setFixedWidth(72)

        self.select_region_btn = QPushButton("选区")
        self.select_output_btn = QPushButton("存储位置")
        self.start_btn = QPushButton("开始")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)

        self.select_region_btn.clicked.connect(self.select_region)
        self.select_output_btn.clicked.connect(self.select_output_dir)
        self.start_btn.clicked.connect(self.start_recording)
        self.stop_btn.clicked.connect(self.stop_recording)
        self.record_mic_checkbox.toggled.connect(self._sync_audio_input_state)
        self.record_system_checkbox.toggled.connect(self._sync_audio_input_state)

        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(10, 8, 10, 10)
        root_layout.setSpacing(6)
        root_layout.addWidget(self._build_status_bar())
        root_layout.addWidget(self._build_settings_group())
        root_layout.addLayout(self._build_action_row())

        root = QWidget()
        root.setLayout(root_layout)
        self.setCentralWidget(root)
        self._sync_audio_input_state()
        self._apply_styles()

    def select_region(self) -> None:
        selector = RegionSelector(self)
        if selector.exec_():
            if self.region_frame:
                self.region_frame.close()
            self.region_frame = RegionFrame(selector.selected_logical_rect())
            self.region_frame.region_changed.connect(self._set_region_from_rect)
            self._set_region_from_rect(self.region_frame.capture_rect())

    def select_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出文件夹", str(self.output_dir))
        if path:
            self.output_dir = Path(path)
            self.status_label.setText(f"输出：{self.output_dir}")

    def start_recording(self) -> None:
        if self.worker and self.worker.isRunning():
            return

        self.config.fps = self.fps_spin.value()
        self.config.mic_device = self.mic_combo.currentData()
        self.config.system_audio_device = self.system_audio_combo.currentData()
        self.config.mic_volume = self.mic_volume_spin.value()
        self.config.system_audio_volume = self.system_volume_spin.value()
        self.config.record_mic = self.record_mic_checkbox.isChecked()
        self.config.record_system_audio = self.record_system_checkbox.isChecked()
        self.config.output_path = self._next_output_path()
        if self.region_frame:
            self._set_region_from_rect(self.region_frame.capture_rect())

        self.countdown_left = 3
        self.status_label.setText("3 秒后开始...")
        self._set_recording_ui(True)
        self.countdown_timer.start(1000)

    def stop_recording(self) -> None:
        if self.countdown_timer.isActive():
            self.countdown_timer.stop()
            self.countdown_left = 0
            self.status_label.setText("已取消")
            self._restore_full_ui()
            self._set_recording_ui(False)
            return

        if self.worker:
            self.status_label.setText("正在停止...")
            self.worker.stop()
            self.worker.wait()
        self._restore_full_ui()
        self._set_recording_ui(False)

    def on_failed(self, message: str) -> None:
        self.countdown_timer.stop()
        self._restore_full_ui()
        self._set_recording_ui(False)
        QMessageBox.warning(self, "录制失败", message)

    def on_finished(self, path: str) -> None:
        self._restore_full_ui()
        self._set_recording_ui(False)
        self.status_label.setText(f"已保存：{Path(path).name}")

    def closeEvent(self, event) -> None:
        self.countdown_timer.stop()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        if self.region_frame:
            self.region_frame.close()
        if self.mini_widget:
            self.mini_widget.close()
        event.accept()

    def _tick_countdown(self) -> None:
        self.countdown_left -= 1
        if self.countdown_left > 0:
            self.status_label.setText(f"{self.countdown_left} 秒后开始...")
            return

        self.countdown_timer.stop()
        self.status_label.setText("正在开始...")
        self._start_worker()

    def _start_worker(self) -> None:
        if self.region_frame:
            self._set_region_from_rect(self.region_frame.capture_rect())
            if self.hide_frame_checkbox.isChecked():
                self.region_frame.hide()

        self.config.prepare_paths()
        self.worker = RecordingWorker(self.config)
        self.worker.status.connect(self.status_label.setText)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished_recording.connect(self.on_finished)
        self.worker.start()
        self._show_mini_widget()
        self.hide()

    def _set_recording_ui(self, recording: bool) -> None:
        controls = [
            self.select_region_btn,
            self.select_output_btn,
            self.fps_spin,
            self.hide_frame_checkbox,
            self.record_mic_checkbox,
            self.record_system_checkbox,
            self.mic_combo,
            self.system_audio_combo,
            self.mic_volume_spin,
            self.system_volume_spin,
            self.start_btn,
        ]
        for control in controls:
            control.setEnabled(not recording)
        self.stop_btn.setEnabled(recording)
        if not recording:
            self._sync_audio_input_state()

    def _load_audio_devices(self) -> None:
        self.mic_combo.addItem("默认麦克风", None)
        for option in list_input_devices():
            self.mic_combo.addItem(option.label, option.index)

        self.system_audio_combo.addItem("默认系统声", None)
        for option in list_wasapi_output_devices():
            self.system_audio_combo.addItem(option.label, option.index)

    def _set_region_from_rect(self, rect) -> None:
        self.config.region = RecordingRegion(left=rect.left(), top=rect.top(), width=rect.width(), height=rect.height())
        self.region_label.setText(self._region_text())

    def _sync_audio_input_state(self) -> None:
        idle = self.start_btn.isEnabled()
        mic_enabled = idle and self.record_mic_checkbox.isChecked()
        system_enabled = idle and self.record_system_checkbox.isChecked()
        self.mic_combo.setEnabled(mic_enabled)
        self.mic_volume_spin.setEnabled(mic_enabled)
        self.system_audio_combo.setEnabled(system_enabled)
        self.system_volume_spin.setEnabled(system_enabled)

    def _restore_full_ui(self) -> None:
        if self.mini_widget:
            self.mini_widget.stop_timer()
            self.mini_widget.close()
            self.mini_widget = None
        if self.region_frame:
            self.region_frame.show()
            self.region_frame.raise_()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_mini_widget(self) -> None:
        if self.mini_widget:
            self.mini_widget.close()
        self.mini_widget = RecordingMiniWidget()
        self.mini_widget.stop_requested.connect(self.stop_recording)
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else self.geometry()
        self.mini_widget.move(available.right() - self.mini_widget.width() - 18, available.top() + 18)
        self.mini_widget.show()
        self.mini_widget.start_timer()

    def _next_output_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.output_dir / f"recording_{timestamp}.mp4"

    def _region_text(self) -> str:
        r = self.config.region
        return f"{r.width}x{r.height} @ ({r.left}, {r.top})"

    def _build_status_bar(self) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QLabel("区域"))
        layout.addWidget(self.region_label, 1)
        layout.addWidget(QLabel("状态"))
        layout.addWidget(self.status_label)
        box.setLayout(layout)
        return box

    def _build_settings_group(self) -> QGroupBox:
        group = QGroupBox("设置")
        grid = QGridLayout()
        grid.setContentsMargins(8, 6, 8, 8)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 0)

        grid.addWidget(QLabel("帧率"), 0, 0)
        grid.addWidget(self.fps_spin, 0, 1)
        grid.addWidget(self.hide_frame_checkbox, 0, 2, 1, 2)
        grid.addWidget(QLabel("麦克风"), 1, 0)
        mic_row = QHBoxLayout()
        mic_row.setContentsMargins(0, 0, 0, 0)
        mic_row.setSpacing(5)
        mic_row.addWidget(self.record_mic_checkbox)
        mic_row.addWidget(self.mic_combo, 1)
        grid.addLayout(mic_row, 1, 1)
        grid.addWidget(QLabel("音量"), 1, 2)
        grid.addWidget(self.mic_volume_spin, 1, 3)
        grid.addWidget(QLabel("系统声"), 2, 0)
        system_row = QHBoxLayout()
        system_row.setContentsMargins(0, 0, 0, 0)
        system_row.setSpacing(5)
        system_row.addWidget(self.record_system_checkbox)
        system_row.addWidget(self.system_audio_combo, 1)
        grid.addLayout(system_row, 2, 1)
        grid.addWidget(QLabel("音量"), 2, 2)
        grid.addWidget(self.system_volume_spin, 2, 3)

        group.setLayout(grid)
        return group

    def _build_action_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(6)
        layout.addWidget(self.select_region_btn)
        layout.addWidget(self.select_output_btn)
        layout.addStretch()
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        return layout

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f7f8fa; }
            QLabel { color: #252a33; font-size: 12px; }
            #regionLabel, #statusLabel { color: #596273; }
            QGroupBox {
                border: 1px solid #d9dde5;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 5px;
                font-size: 12px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px;
            }
            QComboBox, QSpinBox {
                min-height: 22px;
                border: 1px solid #cbd1dc;
                border-radius: 4px;
                background: white;
                padding-left: 5px;
                font-size: 12px;
            }
            QCheckBox { font-size: 12px; }
            QPushButton {
                min-width: 70px;
                min-height: 26px;
                padding: 2px 10px;
                border: 1px solid #c6ccd8;
                border-radius: 5px;
                background: white;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #eef4ff;
                border-color: #7fa7e8;
            }
            QPushButton:disabled {
                color: #9aa3b2;
                background: #edf0f5;
            }
            """
        )


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
