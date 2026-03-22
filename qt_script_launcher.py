import sys
import subprocess
import os
import threading
import logging
import time
import psutil
import argparse
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
                             QFileDialog, QMessageBox, QCheckBox, QSystemTrayIcon, QMenu,
                             QAbstractItemView)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QIcon, QAction, QColor, QPixmap

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class ScriptRunner(QThread):
    finished = pyqtSignal(str, int)
    error = pyqtSignal(str, str)
    started_process = pyqtSignal(str, int)  # Emit PID when process starts
    
    def __init__(self, script, interpreter, params, use_shell, script_dir):
        super().__init__()
        self.script = script
        self.interpreter = interpreter
        self.params = params
        self.use_shell = use_shell
        self.script_dir = script_dir
        self.process = None
    
    def run(self):
        try:
            if self.use_shell:
                # Build the command properly
                script_cmd = f'"{self.script}"'
                if self.params:
                    script_cmd += ' ' + ' '.join([f'"{p}"' for p in self.params])
                
                # The inner command to run in bash
                inner_cmd = f'cd "{self.script_dir}" && {self.interpreter[0]} {script_cmd}; echo "Press Enter to close..."; read'
                
                # Try cosmic-term first, then x-terminal-emulator
                found_term = None
                for term in ['cosmic-term', 'x-terminal-emulator', 'gnome-terminal', 'konsole', 'xfce4-terminal']:
                    try:
                        result = subprocess.run(['which', term], check=True, capture_output=True, text=True)
                        found_term = term
                        logging.debug(f"Found terminal: {term} at {result.stdout.strip()}")
                        break
                    except subprocess.CalledProcessError:
                        logging.debug(f"Terminal {term} not found")
                        continue
                
                if found_term:
                    if found_term == 'cosmic-term':
                        terminal_args = ['cosmic-term', '--', 'bash', '-c', inner_cmd]
                    else:
                        terminal_args = [found_term, '-e', f"bash -c '{inner_cmd}'"]

                    # Start the terminal
                    proc = subprocess.Popen(terminal_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    # Find the bash/python process running our script
                    time.sleep(0.5)
                    
                    script_pid = None
                    script_name = os.path.basename(self.script)
                    
                    for _ in range(10):  # Try for 5 seconds to find the process
                        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                            try:
                                name = p.info.get('name', '')
                                cmdline = p.info.get('cmdline')
                                if not cmdline:
                                    continue
                                cmdline_str = ' '.join(cmdline)
                                
                                # Check for Python or bash interpreter running our script
                                is_interpreter = name in ['python3', 'python', 'bash', 'sh']
                                has_script = self.script in cmdline_str or script_name in cmdline_str
                                
                                if is_interpreter and has_script:
                                    script_pid = p.info['pid']
                                    logging.debug(f"Found script process: PID={script_pid}, name={name}, cmdline={cmdline_str}")
                                    break
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                        if script_pid:
                            break
                        time.sleep(0.5)
                    
                    if not script_pid:
                        logging.debug("Could not find script process, using terminal PID")
                    
                    self.started_process.emit(self.script, script_pid if script_pid else proc.pid)
                    
                    # Poll until the script process is done
                    if script_pid:
                        while psutil.pid_exists(script_pid):
                            time.sleep(0.5)
                    
                    # Give terminal a moment to clean up
                    time.sleep(0.5)
                    proc.wait()
                    self.finished.emit(self.script, proc.returncode)
                    return
                else:
                    cmd = f'cosmic-term -- bash -c \'{inner_cmd}\''
                    logging.debug(f"No terminal found, using os.system fallback: {cmd}")
                    os.system(cmd + ' &')
                    self.finished.emit(self.script, 0)
                    return
            else:
                log_dir = os.path.join(os.path.dirname(__file__), 'logs')
                os.makedirs(log_dir, exist_ok=True)
                script_name = os.path.basename(self.script).replace('.', '_')
                stdout_file = os.path.join(log_dir, f"{script_name}_stdout.log")
                stderr_file = os.path.join(log_dir, f"{script_name}_stderr.log")
                
                with open(stdout_file, 'w') as stdout_f, open(stderr_file, 'w') as stderr_f:
                    self.process = subprocess.Popen(
                        self.interpreter + [self.script] + self.params,
                        stdout=stdout_f,
                        stderr=stderr_f,
                        cwd=self.script_dir
                    )
                    self.started_process.emit(self.script, self.process.pid)
                    self.process.wait()
                    return_code = self.process.returncode
                    self.finished.emit(self.script, return_code)
        except Exception as e:
            self.error.emit(self.script, str(e))

class ScriptLauncherApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Script Launcher")
        self.processes = {}
        self.pids = {}
        self.statuses = {}
        self.descriptions = {}
        self.shell_modes = {}
        self.parameters = {}
        self.threads = {}
        self.is_running = True
        self.is_minimizing = False
        
        parser = argparse.ArgumentParser(description="Script Launcher")
        parser.add_argument("file", nargs="?", help="Path to the .txt file to load")
        parser.add_argument("-m", "--minimize", action="store_true", help="Start minimized to system tray")
        self.args = parser.parse_args()
        
        self.settings = QSettings("ScriptLauncher", "ScriptLauncherApp")
        
        self.setup_ui()
        self.setup_system_tray()
        
        self.resize(900, 600)
        
        if self.args.minimize:
            self.hide()
        
        if self.args.file:
            self.load_file(self.args.file)
    
    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        self.file_label = QLabel("No file selected")
        self.layout.addWidget(self.file_label)
        
        self.select_button = QPushButton("Select Script File")
        self.select_button.clicked.connect(self.select_file)
        
        self.button_row = QHBoxLayout()
        self.button_row.addWidget(self.file_label, 1)
        self.button_row.addWidget(self.select_button)
        self.layout.addLayout(self.button_row)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Script Command", "Description", "Status", "Shell"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 60)
        self.table.itemDoubleClicked.connect(self.run_selected_on_double_click)
        self.layout.addWidget(self.table)
        
        self.button_frame = QWidget()
        self.button_layout = QHBoxLayout(self.button_frame)
        self.button_layout.setContentsMargins(0, 10, 0, 10)
        
        self.run_selected_button = QPushButton("Run Selected")
        self.run_selected_button.clicked.connect(self.run_selected)
        self.button_layout.addWidget(self.run_selected_button)
        
        self.stop_selected_button = QPushButton("Stop Selected")
        self.stop_selected_button.clicked.connect(self.stop_selected)
        self.button_layout.addWidget(self.stop_selected_button)
        
        self.run_all_button = QPushButton("Run All")
        self.run_all_button.clicked.connect(self.run_scripts)
        self.button_layout.addWidget(self.run_all_button)
        
        self.stop_all_button = QPushButton("Stop All")
        self.stop_all_button.clicked.connect(self.stop_scripts)
        self.button_layout.addWidget(self.stop_all_button)
        
        self.button_layout.addStretch()
        self.layout.addWidget(self.button_frame)
        
        self.statusBar().showMessage("Ready")
    
    def setup_system_tray(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(255, 255, 255))
        
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("Script Launcher")
        
        self.tray_menu = QMenu()
        
        self.show_action = QAction("Show", self)
        self.show_action.triggered.connect(self.restore_window)
        self.tray_menu.addAction(self.show_action)
        
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.quit_application)
        self.tray_menu.addAction(self.exit_action)
        
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()
        
        logging.debug("System tray icon initialized")
    
    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.restore_window()
    
    def update_tray_icon(self, file_path):
        base_name = os.path.splitext(file_path)[0]
        image_extensions = ['.png', '.jpg', '.jpeg', '.gif']
        image_path = None
        for ext in image_extensions:
            potential_path = base_name + ext
            if os.path.exists(potential_path):
                image_path = potential_path
                break
        
        if image_path:
            try:
                pixmap = QPixmap(image_path).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio)
                self.tray_icon.setIcon(QIcon(pixmap))
                logging.debug(f"Updated tray icon with {image_path}")
            except Exception as e:
                logging.error(f"Failed to load image {image_path}: {str(e)}")
    
    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "", "Text files (*.txt);;All files (*.*)"
        )
        if file_path:
            self.load_file(file_path)
    
    def load_file(self, file_path):
        if not os.path.isfile(file_path) or not file_path.lower().endswith('.txt'):
            logging.error(f"Invalid file path or not a .txt file: {file_path}")
            QMessageBox.critical(self, "Error", f"Invalid file path or not a .txt file: {file_path}")
            if self.args.minimize:
                self.quit_application()
            return
        
        self.file_label.setText(file_path)
        self.update_tray_icon(file_path)
        
        self.table.setRowCount(0)
        self.statuses.clear()
        self.descriptions.clear()
        self.shell_modes.clear()
        self.parameters.clear()
        
        try:
            with open(file_path, 'r') as file:
                lines = [line.strip() for line in file if line.strip()]
            
            row = 0
            for i in range(0, len(lines), 2):
                script_line = lines[i].split(maxsplit=1)
                script = script_line[0]
                params = script_line[1] if len(script_line) > 1 else ""
                description = lines[i + 1] if i + 1 < len(lines) else "No description"
                display_command = script + (" " + params if params else "")
                
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(display_command))
                self.table.setItem(row, 1, QTableWidgetItem(description))
                
                status_item = QTableWidgetItem("Stop")
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 2, status_item)
                
                checkbox = QCheckBox()
                checkbox.setStyleSheet("margin-left:auto; margin-right:auto;")
                checkbox.stateChanged.connect(lambda state, s=script: self.shell_toggled(s, state))
                self.table.setCellWidget(row, 3, checkbox)
                
                if os.path.exists(script):
                    self.statuses[script] = "Stop"
                else:
                    self.statuses[script] = "Invalid Path"
                    status_item.setText("Invalid Path")
                
                self.descriptions[script] = description
                self.shell_modes[script] = False
                self.parameters[script] = params.split() if params else []
                row += 1
            
            logging.debug(f"Loaded scripts from {file_path}")
        except Exception as e:
            self.file_label.setText(f"Error reading file: {str(e)}")
            logging.error(f"Error reading file {file_path}: {str(e)}")
    
    def shell_toggled(self, script, state):
        # state can be int (0, 1, 2) or Qt.CheckState
        if isinstance(state, int):
            self.shell_modes[script] = (state == 2)  # 2 = Checked
        else:
            self.shell_modes[script] = (state == Qt.CheckState.Checked)
        logging.debug(f"Toggled shell mode for {script}: {self.shell_modes[script]}")
    
    def get_script_interpreter(self, script_path):
        try:
            with open(script_path, 'r') as file:
                first_line = file.readline().strip()
                if first_line.startswith('#!/bin/bash'):
                    return ['/bin/bash']
                elif first_line.startswith('#!/bin/sh'):
                    return ['/bin/sh']
                elif first_line.startswith('#!/bin/zsh') or first_line.startswith('#!/usr/bin/zsh'):
                    return ['/bin/zsh']
                elif first_line.startswith('#!') and 'python' in first_line:
                    return [sys.executable, '-u']
        except Exception as e:
            logging.warning(f"Could not read shebang for {script_path}: {str(e)}")

        if script_path.lower().endswith('.py'):
            return [sys.executable, '-u']
        elif script_path.lower().endswith(('.sh', '.bash')):
            return ['/bin/bash']
        return [sys.executable, '-u']
    
    def run_scripts(self):
        logging.debug(f"Running all scripts. Current processes: {list(self.processes.keys())}")
        for script in self.statuses:
            if self.statuses[script] == "Stop" and os.path.exists(script):
                self.run_script(script)
    
    def run_selected(self):
        selected_rows = set(item.row() for item in self.table.selectedItems())
        for row in selected_rows:
            script = self.table.item(row, 0).text().split()[0]
            if self.statuses.get(script) == "Stop" and os.path.exists(script):
                self.run_script(script)
    
    def run_selected_on_double_click(self, item):
        row = item.row()
        script = self.table.item(row, 0).text().split()[0]
        if self.statuses.get(script) == "Stop" and os.path.exists(script):
            self.run_script(script)
    
    def run_script(self, script):
        try:
            self.update_status(script, "Running")
            interpreter = self.get_script_interpreter(script)
            params = self.parameters.get(script, [])
            use_shell = self.shell_modes.get(script, False)
            script_dir = os.path.dirname(os.path.abspath(script))
            
            thread = ScriptRunner(script, interpreter, params, use_shell, script_dir)
            thread.finished.connect(lambda s, rc: self.script_finished(s, rc))
            thread.error.connect(lambda s, e: self.script_error(s, e))
            thread.started_process.connect(self.on_process_started)
            thread.start()
            
            self.threads[script] = thread
            self.processes[script] = True
            logging.debug(f"Started script: {script}, Interpreter: {interpreter}, Params: {params}")
        except Exception as e:
            self.update_status(script, f"Stop (Error: {str(e)})")
            logging.error(f"Error running script {script}: {str(e)}")
    
    def on_process_started(self, script, pid):
        self.pids[script] = pid
        logging.debug(f"Process started for {script}, PID: {pid}")
    
    def script_finished(self, script, return_code):
        if return_code == 0 or return_code == -15:
            self.update_status(script, "Stop")
        else:
            self.update_status(script, f"Stop (Error: {return_code})")
        if script in self.processes:
            del self.processes[script]
        if script in self.threads:
            thread = self.threads[script]
            thread.wait()  # Wait for thread to finish before deleting
            del self.threads[script]
        if script in self.pids:
            del self.pids[script]
        logging.debug(f"Script {script} finished with return code {return_code}")
    
    def script_error(self, script, error):
        self.update_status(script, f"Stop (Error: {error})")
        if script in self.processes:
            del self.processes[script]
        if script in self.threads:
            del self.threads[script]
        if script in self.pids:
            del self.pids[script]
        logging.error(f"Error running script {script}: {error}")
    
    def stop_selected(self):
        selected_rows = set(item.row() for item in self.table.selectedItems())
        for row in selected_rows:
            script = self.table.item(row, 0).text().split()[0]
            if script in self.processes:
                self.stop_script(script)
    
    def stop_scripts(self):
        for script in list(self.processes.keys()):
            self.stop_script(script)
    
    def stop_script(self, script):
        logging.debug(f"Attempting to stop script: {script}")
        try:
            if script in self.pids:
                parent_pid = self.pids[script]
                try:
                    parent = psutil.Process(parent_pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        child.terminate()
                    parent.terminate()
                    gone, alive = psutil.wait_procs(children + [parent], timeout=3)
                    for p in alive:
                        p.kill()
                except psutil.NoSuchProcess:
                    pass
            
            if script in self.threads:
                thread = self.threads[script]
                thread.terminate()
                thread.wait()
            
            self.update_status(script, "Stop")
            if script in self.processes:
                del self.processes[script]
            if script in self.threads:
                del self.threads[script]
            if script in self.pids:
                del self.pids[script]
            logging.debug(f"Stopped script: {script}")
        except Exception as e:
            logging.error(f"Error stopping script {script}: {str(e)}")
            self.update_status(script, f"Stop (Error: {str(e)})")
    
    def update_status(self, script, status):
        self.statuses[script] = status
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().startswith(script):
                status_item = self.table.item(row, 2)
                if status_item:
                    status_item.setText(status)
                    status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                break
        logging.debug(f"Updated status for {script}: {status}")
    
    def closeEvent(self, event):
        if self.is_running and not self.is_minimizing:
            event.ignore()
            self.hide()
            logging.debug("Minimized to system tray")
        else:
            event.accept()
    
    def minimize_to_tray(self):
        if self.is_running and not self.is_minimizing:
            try:
                self.is_minimizing = True
                self.hide()
                logging.debug("Minimized to system tray")
            finally:
                self.is_minimizing = False
    
    def restore_window(self):
        try:
            logging.debug("Restoring window")
            self.show()
            self.activateWindow()
            self.raise_()
            if self.settings.contains("geometry"):
                self.restoreGeometry(self.settings.value("geometry"))
            logging.debug("Window restored successfully")
        except Exception as e:
            logging.error(f"Error restoring window: {str(e)}")
    
    def quit_application(self):
        try:
            self.is_running = False
            self.stop_scripts()
            self.settings.setValue("geometry", self.saveGeometry())
            self.tray_icon.hide()
            QApplication.quit()
            logging.debug("Application quit successfully")
        except Exception as e:
            logging.error(f"Error quitting application: {str(e)}")

HACKER_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0d0d0d;
    color: #00ff41;
}
QLabel {
    color: #00ff41;
    background-color: transparent;
}
QPushButton {
    background-color: #1a1a1a;
    color: #00ff41;
    border: 1px solid #00ff41;
    padding: 6px 12px;
    border-radius: 3px;
}
QPushButton:hover {
    background-color: #003b00;
    border: 2px solid #00ff41;
}
QPushButton:pressed {
    background-color: #004d00;
}
QTableWidget, QTableView {
    background-color: #0d0d0d;
    color: #00ff41;
    gridline-color: #003b00;
    border: 1px solid #00ff41;
    selection-background-color: #003b00;
    selection-color: #00ff41;
}
QHeaderView::section {
    background-color: #1a1a1a;
    color: #00ff41;
    border: 1px solid #00ff41;
    padding: 4px;
}
QScrollBar:vertical {
    background: #0d0d0d;
    width: 12px;
    border: 1px solid #003b00;
}
QScrollBar::handle:vertical {
    background: #003b00;
    min-height: 20px;
    border: 1px solid #00ff41;
}
QScrollBar::handle:vertical:hover {
    background: #004d00;
}
QScrollBar:horizontal {
    background: #0d0d0d;
    height: 12px;
    border: 1px solid #003b00;
}
QScrollBar::handle:horizontal {
    background: #003b00;
    min-width: 20px;
    border: 1px solid #00ff41;
}
QCheckBox {
    color: #00ff41;
    background-color: transparent;
}
QCheckBox::indicator {
    border: 1px solid #00ff41;
    background-color: #0d0d0d;
}
QCheckBox::indicator:checked {
    background-color: #00ff41;
    border-color: #00ff41;
}
QStatusBar {
    background-color: #0d0d0d;
    color: #00ff41;
    border-top: 1px solid #003b00;
}
QSystemTrayIcon {
    background-color: #0d0d0d;
}
QMenu {
    background-color: #1a1a1a;
    color: #00ff41;
    border: 1px solid #00ff41;
}
QMenu::item:selected {
    background-color: #003b00;
}
"""

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(HACKER_STYLESHEET)
    window = ScriptLauncherApp()
    
    if not window.args.minimize:
        window.show()
    
    sys.exit(app.exec())
