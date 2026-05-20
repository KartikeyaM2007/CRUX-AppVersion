import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None


APP_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
WEB_SOURCE_DIR = RESOURCE_DIR / "bundled_web"
CATALOG_PATH = RESOURCE_DIR / "model_catalog.json"
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("CRUX_PORT", "8000"))
LOCAL_URL = f"http://{LOCAL_HOST}:{DEFAULT_PORT}"

USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "Crux"
DESKTOP_CONFIG_PATH = USER_DATA_DIR / "desktop_config.json"


def get_web_dir():
    if not getattr(sys, "frozen", False):
        return WEB_SOURCE_DIR

    runtime_web = USER_DATA_DIR / "bundled_web"
    if WEB_SOURCE_DIR.exists():
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copytree(WEB_SOURCE_DIR, runtime_web, dirs_exist_ok=True)
    return runtime_web


def server_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--serve-web"]
    return [sys.executable, str(Path(__file__).resolve()), "--serve-web"]


def local_url(port):
    return f"http://{LOCAL_HOST}:{port}"


def can_bind_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((LOCAL_HOST, port))
            return True
        except OSError:
            return False


def url_is_ready(url, timeout=0.7):
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def find_available_port(start_port=DEFAULT_PORT):
    for port in range(start_port, start_port + 20):
        if can_bind_port(port):
            return port
    return start_port


def run_text_command(args, timeout=8):
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception:
        return None


def installed_ollama_models():
    result = run_text_command(["ollama", "list"])
    if result is None or result.returncode != 0:
        return []

    models = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0].strip())
    return models


def model_matches(model_id, installed_name):
    wanted = model_id.lower()
    found = installed_name.lower()
    if found == wanted:
        return True
    if ":" not in wanted and found.startswith(wanted + ":"):
        return True
    return found.split(":")[0] == wanted.split(":")[0]


def is_model_installed(model_id, installed):
    return any(model_matches(model_id, name) for name in installed)


def load_desktop_config():
    if not DESKTOP_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(DESKTOP_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_desktop_config(model_id, installed, url=LOCAL_URL):
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_CONFIG_PATH.write_text(
        json.dumps(
            {
                "repair_model": model_id,
                "installed_ollama_models": installed,
                "local_url": url,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


class CommandWorker(QThread):
    line = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, commands, cwd=None):
        super().__init__()
        self.commands = commands
        self.cwd = cwd or APP_DIR

    def run(self):
        try:
            for command in self.commands:
                self.line.emit(f"$ {command}")
                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=str(self.cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                assert process.stdout is not None
                for output in process.stdout:
                    self.line.emit(output.rstrip())
                code = process.wait()
                if code != 0:
                    raise RuntimeError(f"Command failed with exit code {code}: {command}")
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class ServerWorker(QThread):
    line = Signal(str)
    ready = Signal()
    failed = Signal(str)

    def __init__(self, model_id, port):
        super().__init__()
        self.model_id = model_id
        self.port = port
        self.url = local_url(port)
        self.process = None
        self.stopping = False

    def run(self):
        try:
            web_dir = get_web_dir()
            command = server_command()
            env = os.environ.copy()
            env["CRUX_OLLAMA_MODEL"] = self.model_id
            env["CRUX_PORT"] = str(self.port)
            env.setdefault("PYTHONIOENCODING", "utf-8")

            self.line.emit(f"Using repair model: {self.model_id}")
            self.line.emit(f"Using local URL: {self.url}")
            self.line.emit(f"$ cd {web_dir}")
            self.line.emit(f"$ {' '.join(command)}")
            self.process = subprocess.Popen(
                command,
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            start = time.time()
            while time.time() - start < 30:
                if self.process.poll() is not None:
                    output = self.process.stdout.read() if self.process.stdout else ""
                    raise RuntimeError(output or "Crux web engine exited during startup.")
                try:
                    with urlopen(self.url, timeout=1) as response:
                        if response.status == 200:
                            self.ready.emit()
                            break
                except Exception:
                    time.sleep(0.4)
            else:
                raise RuntimeError("Crux web engine did not become ready within 30 seconds.")

            assert self.process.stdout is not None
            for output in self.process.stdout:
                self.line.emit(output.rstrip())
            code = self.process.wait()
            if code and not self.stopping:
                raise RuntimeError(f"Crux web engine exited with code {code}.")
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
        self.stopping = True
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


class CruxDesktop(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Crux")
        self.setMinimumSize(1180, 780)
        self.port = find_available_port()
        self.local_url = local_url(self.port)
        self.catalog = self.load_catalog()
        self.installed_models = installed_ollama_models()
        self.model_buttons = {}
        self.model_status_labels = {}
        self.engine_checks = {}
        self.command_worker = None
        self.server_worker = None
        self.web_view = None
        self.runtime_panel = None
        self.runtime_toggle_button = None
        self.runtime_collapsed = False
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.build_setup_page()
        self.build_app_page()
        self.build_menu()
        self.apply_styles()
        if any(is_model_installed(item["id"], self.installed_models) for item in self.catalog if item["provider"] == "Ollama" and item.get("recommended")):
            self.stack.setCurrentIndex(1)

    def load_catalog(self):
        with CATALOG_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)

    def build_menu(self):
        open_action = QAction("Open in browser", self)
        open_action.triggered.connect(lambda: webbrowser.open(self.local_url))
        setup_action = QAction("Model setup", self)
        setup_action.triggered.connect(lambda: self.stack.setCurrentIndex(0))
        app_action = QAction("Crux app", self)
        app_action.triggered.connect(lambda: self.stack.setCurrentIndex(1))
        self.menuBar().addAction(setup_action)
        self.menuBar().addAction(app_action)
        self.menuBar().addAction(open_action)

    def build_setup_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("setupHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 20, 24, 20)
        hero_layout.setSpacing(18)

        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(8)
        eyebrow = QLabel("LOCAL FIRST SETUP")
        eyebrow.setObjectName("setupEyebrow")
        title = QLabel("Crux Local Setup")
        title.setObjectName("title")
        subtitle = QLabel(
            "Pick one Ollama repair model, confirm the tabular generation engine, then launch the exact Crux interface inside the desktop shell."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        hero_copy.addWidget(eyebrow)
        hero_copy.addWidget(title)
        hero_copy.addWidget(subtitle)
        hero_layout.addLayout(hero_copy, stretch=3)

        hero_stats = QFrame()
        hero_stats.setObjectName("setupHeroStats")
        stat_layout = QVBoxLayout(hero_stats)
        stat_layout.setContentsMargins(14, 14, 14, 14)
        stat_layout.setSpacing(8)
        detected = ", ".join(self.installed_models) if self.installed_models else "none detected"
        local_badge = QLabel(f"Detected models: {detected}")
        local_badge.setObjectName("setupStat")
        local_badge.setWordWrap(True)
        no_api = QLabel("No API used. CSV processing stays local.")
        no_api.setObjectName("setupStatStrong")
        no_api.setWordWrap(True)
        self.refresh_button = QPushButton("Refresh models")
        self.refresh_button.clicked.connect(self.refresh_installed_models)
        self.llama_terminal_button = QPushButton("Open llama3 terminal")
        self.llama_terminal_button.clicked.connect(self.open_llama_terminal)
        stat_layout.addWidget(no_api)
        stat_layout.addWidget(local_badge)
        stat_layout.addWidget(self.refresh_button)
        stat_layout.addWidget(self.llama_terminal_button)
        hero_layout.addWidget(hero_stats, stretch=2)
        layout.addWidget(hero)

        model_label = QLabel("1. Local repair model")
        model_label.setObjectName("sectionLabel")
        layout.addWidget(model_label)
        self.model_group = QButtonGroup(self)
        self.model_group.setExclusive(True)

        model_grid = QGridLayout()
        model_grid.setSpacing(10)
        model_index = 0
        for item in self.catalog:
            if item["provider"] != "Ollama":
                continue
            card, radio, status = self.model_card(item)
            self.model_group.addButton(radio)
            self.model_buttons[item["id"]] = radio
            self.model_status_labels[item["id"]] = status
            model_grid.addWidget(card, model_index // 2, model_index % 2)
            model_index += 1
        layout.addLayout(model_grid)

        self.choose_default_model()
        self.refresh_model_status_labels()

        engine_label = QLabel("2. Local engines")
        engine_label.setObjectName("sectionLabel")
        layout.addWidget(engine_label)
        engine_card = QFrame()
        engine_card.setObjectName("engineCard")
        engine_layout = QVBoxLayout(engine_card)
        engine_layout.setContentsMargins(16, 14, 16, 14)
        engine_layout.setSpacing(6)
        for item in self.catalog:
            if item["provider"] == "Ollama":
                continue
            check = QCheckBox(f"{item['name']} - {item['purpose']}")
            check.setChecked(item.get("recommended", False))
            self.engine_checks[item["id"]] = check
            engine_layout.addWidget(check)
        layout.addWidget(engine_card)

        action_row = QHBoxLayout()
        action_row.setSpacing(12)
        self.download_button = QPushButton("Download selected")
        self.download_button.setObjectName("primaryButton")
        self.download_button.clicked.connect(self.download_selected)
        self.skip_button = QPushButton("Continue to app")
        self.skip_button.clicked.connect(self.continue_to_app)
        action_row.addWidget(self.download_button)
        action_row.addWidget(self.skip_button)
        layout.addLayout(action_row)

        self.setup_log = QTextEdit()
        self.setup_log.setReadOnly(True)
        self.setup_log.setPlaceholderText("Setup logs will appear here...")
        detected = ", ".join(self.installed_models) if self.installed_models else "none detected"
        self.setup_log.append(f"Detected Ollama models: {detected}")
        layout.addWidget(self.setup_log, stretch=1)
        self.stack.addWidget(page)

    def build_app_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        shell_bar = QFrame()
        shell_bar.setObjectName("desktopTopBar")
        header = QHBoxLayout(shell_bar)
        header.setContentsMargins(10, 8, 10, 8)
        header.setSpacing(8)
        title = QLabel("Crux Desktop")
        title.setObjectName("appTitle")
        header.addWidget(title)

        self.status_label = QLabel("Status: not running")
        self.status_label.setObjectName("status")
        header.addWidget(self.status_label, stretch=1)

        self.start_button = QPushButton("Start local engine")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_server)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_server)
        self.open_browser_button = QPushButton("Open browser")
        self.open_browser_button.clicked.connect(lambda: webbrowser.open(self.local_url))
        self.runtime_toggle_button = QPushButton("Hide logs <")
        self.runtime_toggle_button.setObjectName("logsToggle")
        self.runtime_toggle_button.clicked.connect(self.toggle_runtime_logs)
        header.addWidget(self.start_button)
        header.addWidget(self.stop_button)
        header.addWidget(self.open_browser_button)
        header.addWidget(self.runtime_toggle_button)
        layout.addWidget(shell_bar)

        workspace = QHBoxLayout()
        workspace.setSpacing(8)

        if QWebEngineView is not None:
            self.web_view = QWebEngineView()
            self.web_view.setHtml("<h2 style='font-family:Arial'>Start the local engine to load Crux.</h2>")
            workspace.addWidget(self.web_view, stretch=5)
        else:
            fallback = QLabel("Qt WebEngine is not installed. Use the Open browser button after starting the engine.")
            fallback.setWordWrap(True)
            workspace.addWidget(fallback, stretch=5)

        log_panel = QFrame()
        log_panel.setObjectName("runtimePanel")
        self.runtime_panel = log_panel
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(6)
        log_title = QLabel("Runtime Logs")
        log_title.setObjectName("runtimeTitle")
        log_layout.addWidget(log_title)

        self.runtime_log = QTextEdit()
        self.runtime_log.setReadOnly(True)
        self.runtime_log.setPlaceholderText("Runtime logs...")
        log_layout.addWidget(self.runtime_log, stretch=1)
        log_panel.setMinimumWidth(320)
        log_panel.setMaximumWidth(420)
        workspace.addWidget(log_panel, stretch=2)
        layout.addLayout(workspace, stretch=1)
        self.stack.addWidget(page)

    def toggle_runtime_logs(self):
        self.runtime_collapsed = not self.runtime_collapsed
        if self.runtime_panel is not None:
            self.runtime_panel.setVisible(not self.runtime_collapsed)
        if self.runtime_toggle_button is not None:
            self.runtime_toggle_button.setText("Show logs >" if self.runtime_collapsed else "Hide logs <")

    def model_card(self, item):
        frame = QFrame()
        frame.setObjectName("modelCard")
        row = QVBoxLayout(frame)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(8)

        radio = QRadioButton(f"{item['name']}{' (preferred)' if item.get('recommended') else ''}")
        radio.setObjectName("modelRadio")

        top = QHBoxLayout()
        top.setSpacing(10)
        status = QLabel("")
        status.setObjectName("modelStatus")
        status.setMinimumWidth(120)
        top.addWidget(radio, stretch=1)
        top.addWidget(status)

        purpose = QLabel(item["purpose"])
        purpose.setObjectName("modelPurpose")
        purpose.setWordWrap(True)
        command = QLabel(item["download_command"])
        command.setObjectName("modelCommand")
        command.setWordWrap(True)

        row.addLayout(top)
        row.addWidget(purpose)
        row.addWidget(command)
        return frame, radio, status

    def choose_default_model(self):
        saved_model = load_desktop_config().get("repair_model")
        if saved_model in self.model_buttons:
            self.model_buttons[saved_model].setChecked(True)
            return

        for item in self.catalog:
            if item["provider"] == "Ollama" and item.get("recommended") and is_model_installed(item["id"], self.installed_models):
                self.model_buttons[item["id"]].setChecked(True)
                return

        for item in self.catalog:
            if item["provider"] == "Ollama" and item.get("recommended"):
                self.model_buttons[item["id"]].setChecked(True)
                return

    def refresh_model_status_labels(self):
        for item in self.catalog:
            if item["provider"] != "Ollama":
                continue
            label = self.model_status_labels[item["id"]]
            installed = is_model_installed(item["id"], self.installed_models)
            if installed:
                label.setText("Installed locally")
                label.setStyleSheet("color:#2d5a27; font-weight:900;")
            else:
                label.setText("Not detected")
                label.setStyleSheet("color:#8a5a20; font-weight:900;")

    def refresh_installed_models(self):
        self.installed_models = installed_ollama_models()
        self.refresh_model_status_labels()
        detected = ", ".join(self.installed_models) if self.installed_models else "none detected"
        self.setup_log.append(f"Refreshed Ollama models: {detected}")

    def selected_model_id(self):
        for model_id, radio in self.model_buttons.items():
            if radio.isChecked():
                return model_id
        return "llama3"

    def persist_config(self):
        model_id = self.selected_model_id()
        save_desktop_config(model_id, self.installed_models, self.local_url)
        return model_id

    def selected_commands(self):
        commands = []
        selected_model = self.selected_model_id()
        for item in self.catalog:
            if item["provider"] == "Ollama" and item["id"] == selected_model:
                if is_model_installed(item["id"], self.installed_models):
                    self.setup_log.append(f"{item['name']} is already installed locally. Skipping pull.")
                else:
                    commands.append(item["download_command"])
            if item["provider"] != "Ollama" and self.engine_checks.get(item["id"]) and self.engine_checks[item["id"]].isChecked():
                commands.append(item["download_command"])
        return commands

    def download_selected(self):
        self.persist_config()
        commands = self.selected_commands()
        if not commands:
            self.setup_log.append("All selected local components are already ready.")
            self.refresh_installed_models()
            self.continue_to_app()
            return
        self.download_button.setEnabled(False)
        self.setup_log.append("Starting Crux setup...")
        self.command_worker = CommandWorker(commands, cwd=APP_DIR)
        self.command_worker.line.connect(self.setup_log.append)
        self.command_worker.finished_ok.connect(self.download_finished)
        self.command_worker.failed.connect(self.download_failed)
        self.command_worker.start()

    def download_finished(self):
        self.download_button.setEnabled(True)
        self.setup_log.append("Setup complete.")
        self.refresh_installed_models()
        self.persist_config()
        QMessageBox.information(self, "Crux setup", "Selected models and engines are ready.")
        self.stack.setCurrentIndex(1)

    def download_failed(self, message):
        self.download_button.setEnabled(True)
        self.setup_log.append(f"ERROR: {message}")
        QMessageBox.critical(self, "Crux setup failed", message)

    def continue_to_app(self):
        model_id = self.persist_config()
        if not is_model_installed(model_id, self.installed_models):
            self.setup_log.append(
                f"Warning: {model_id} is not detected. Use Download selected or Open llama3 terminal before repair jobs."
            )
        self.stack.setCurrentIndex(1)

    def open_llama_terminal(self):
        command = "ollama run llama3"
        self.setup_log.append(f"$ {command}")
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["powershell.exe", "-NoExit", "-Command", command], cwd=str(APP_DIR))
            else:
                subprocess.Popen(["x-terminal-emulator", "-e", command], cwd=str(APP_DIR))
        except Exception as exc:
            self.setup_log.append(f"ERROR: could not open terminal: {exc}")

    def start_server(self):
        if self.server_worker and self.server_worker.isRunning():
            self.runtime_log.append("Crux engine is already running.")
            return
        model_id = self.persist_config()
        if not is_model_installed(model_id, self.installed_models):
            self.runtime_log.append(f"Warning: selected model '{model_id}' is not currently detected by ollama list.")

        if url_is_ready(self.local_url):
            self.runtime_log.append(f"Reusing already-running Crux engine at {self.local_url}.")
            self.status_label.setText(f"Status: running at {self.local_url}")
            self.start_button.setEnabled(True)
            if self.web_view is not None:
                self.web_view.setUrl(QUrl(self.local_url))
            return

        if not can_bind_port(self.port):
            old_url = self.local_url
            self.port = find_available_port(self.port + 1)
            self.local_url = local_url(self.port)
            save_desktop_config(model_id, self.installed_models, self.local_url)
            self.runtime_log.append(f"Port busy at {old_url}; switching to {self.local_url}.")

        self.status_label.setText("Status: starting...")
        self.start_button.setEnabled(False)
        self.server_worker = ServerWorker(model_id=model_id, port=self.port)
        self.server_worker.line.connect(self.runtime_log.append)
        self.server_worker.ready.connect(self.server_ready)
        self.server_worker.failed.connect(self.server_failed)
        self.server_worker.start()

    def server_ready(self):
        self.status_label.setText(f"Status: running at {self.local_url}")
        self.start_button.setEnabled(True)
        self.runtime_log.append("Crux web engine is ready.")
        if self.web_view is not None:
            self.web_view.setUrl(QUrl(self.local_url))

    def server_failed(self, message):
        self.status_label.setText("Status: failed")
        self.start_button.setEnabled(True)
        self.runtime_log.append(f"ERROR: {message}")
        QMessageBox.critical(self, "Crux engine failed", message)

    def stop_server(self):
        if self.server_worker:
            self.server_worker.stop()
            self.server_worker.quit()
            self.server_worker.wait(3000)
            self.server_worker = None
        self.status_label.setText("Status: stopped")
        self.runtime_log.append("Crux web engine stopped.")

    def closeEvent(self, event):
        self.stop_server()
        super().closeEvent(event)

    def apply_styles(self):
        self.setStyleSheet(
            """
            QWidget { background: #f1efe8; color: #090909; font-family: Inter, Arial; font-size: 14px; }
            QLabel { background: transparent; color: #090909; }
            QFrame#desktopTopBar { background: #fffef8; border: 1px solid #d8d1c4; border-radius: 8px; }
            QFrame#setupHero { background: #fffef8; border: 1px solid #0b0b0b; border-radius: 8px; }
            QFrame#setupHeroStats { background: #f7fff5; border: 1px solid #b8efbd; border-radius: 8px; }
            QLabel#setupEyebrow { color: #075c1c; font-family: Consolas; font-weight: 900; letter-spacing: 1px; font-size: 12px; }
            QLabel#title { font-size: 38px; font-weight: 900; padding: 0; }
            QLabel#subtitle { color: #5c6258; font-size: 15px; line-height: 1.55; }
            QLabel#setupStat { color: #075c1c; background: #ffffff; border: 1px solid #cbefce; border-radius: 6px; padding: 9px; font-family: Consolas; font-size: 12px; }
            QLabel#setupStatStrong { color: #090909; font-size: 18px; font-weight: 900; }
            QLabel#appTitle { background: transparent; border: 0; padding: 0 8px; font-size: 18px; font-weight: 900; min-width: 150px; }
            QLabel#sectionLabel { background: #090909; border: 1px solid #090909; border-radius: 6px; padding: 8px 12px; color: #ffffff; font-family: Consolas; font-weight: 900; text-transform: uppercase; margin-top: 8px; }
            QLabel#status { background: #f7fff5; border: 1px solid #b8efbd; border-radius: 7px; padding: 5px 10px; color: #075c1c; font-weight: 900; }
            QLabel#runtimeTitle { color: #075c1c; font-weight: 900; padding: 0 2px; }
            QFrame#runtimePanel, QFrame#engineCard { background: #fffef8; border: 1px solid #b8efbd; border-radius: 8px; }
            QFrame#modelCard { background: #fffef8; border: 1px solid #d8d1c4; border-radius: 8px; }
            QFrame#modelCard:hover { border-color: #04c432; }
            QRadioButton#modelRadio { color: #090909; font-weight: 900; font-size: 15px; }
            QRadioButton::indicator, QCheckBox::indicator { width: 16px; height: 16px; }
            QLabel#modelPurpose { color: #596157; font-size: 13px; }
            QLabel#modelCommand { color: #075c1c; background: #f4fff2; border: 1px solid #cbefce; border-radius: 5px; padding: 6px; font-family: Consolas; font-size: 11px; }
            QLabel#modelStatus { font-size: 12px; font-family: Consolas; }
            QCheckBox { color: #090909; padding: 6px 8px; font-weight: 700; }
            QPushButton { min-height: 30px; border-radius: 6px; padding: 0 14px; font-weight: 900; background: #ffffff; color: #090909; border: 1px solid #d8d1c4; }
            QPushButton#primaryButton { background: #064f18; color: #ffffff; border: 1px solid #064f18; }
            QPushButton#logsToggle { background: #f7fff5; color: #075c1c; border: 1px solid #b8efbd; min-width: 86px; }
            QPushButton:hover { border-color: #04c432; }
            QTextEdit { background: #fbfffb; color: #075c1c; border: 1px solid #b8efbd; border-radius: 8px; padding: 8px; font-family: Consolas; font-size: 11px; }
            QMenuBar { background: #fffef8; color: #090909; min-height: 30px; border-bottom: 1px solid #d8d1c4; }
            QMenuBar::item { padding: 7px 16px; background: transparent; font-weight: 800; }
            QMenuBar::item:selected { background: #f4fff2; color: #064f18; }
            """
        )


def self_test():
    errors = []
    web_dir = get_web_dir()
    for path in [APP_DIR, WEB_SOURCE_DIR, web_dir, CATALOG_PATH, web_dir / "app.py", web_dir / "templates" / "index.html"]:
        if not path.exists():
            errors.append(f"Missing {path}")
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if CATALOG_PATH.exists() else []
    if not any(item.get("recommended") and item["provider"] == "Ollama" for item in catalog):
        errors.append("No recommended Ollama model configured.")
    if not any(item["id"] == "ctgan" for item in catalog):
        errors.append("CTGAN engine is missing from catalog.")
    if QWebEngineView is None:
        errors.append("Qt WebEngine is unavailable.")
    if errors:
        print("SELF_TEST_FAILED")
        for error in errors:
            print(error)
        return 1
    detected = ", ".join(installed_ollama_models()) or "none"
    print("SELF_TEST_OK")
    print(f"APP_DIR={APP_DIR}")
    print(f"WEB_DIR={web_dir}")
    print(f"URL={LOCAL_URL}")
    print(f"AVAILABLE_PORT={find_available_port()}")
    print(f"OLLAMA_MODELS={detected}")
    return 0


def serve_web():
    import uvicorn

    config = load_desktop_config()
    if config.get("repair_model"):
        os.environ.setdefault("CRUX_OLLAMA_MODEL", config["repair_model"])

    web_dir = get_web_dir()
    os.chdir(web_dir)
    if str(web_dir) not in sys.path:
        sys.path.insert(0, str(web_dir))
    port = int(os.environ.get("CRUX_PORT", str(DEFAULT_PORT)))
    uvicorn.run("app:app", host=LOCAL_HOST, port=port, reload=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--serve-web", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if args.serve_web:
        serve_web()
        return
    app = QApplication(sys.argv)
    window = CruxDesktop()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
