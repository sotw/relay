import sys
import subprocess
import os
import threading
import logging
import time
import re
import argparse
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
                             QFileDialog, QMessageBox, QScrollArea, QFrame, QSystemTrayIcon,
                             QMenu, QHeaderView)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QIcon, QAction, QPainter, QColor, QPixmap

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class URLLauncherXDGApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("xdg-open Launcher")
        self.descriptions = {}
        self.groups = {}
        self.treeviews = {}
        self.is_running = True
        self.is_minimizing = False
        
        parser = argparse.ArgumentParser(description="xdg-open Launcher")
        parser.add_argument("file", nargs="?", help="Path to the .txt file to load")
        parser.add_argument("-m", "--minimize", action="store_true", help="Start minimized to system tray")
        self.args = parser.parse_args()
        
        self.settings = QSettings("xdg-open Launcher", "URLLauncherXDGApp")
        
        self.setup_ui()
        self.setup_system_tray()
        
        self.setCentralWidget(self.central_widget)
        self.resize(800, 600)
        
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
        
        self.select_button = QPushButton("Select File")
        self.select_button.clicked.connect(self.select_file)
        
        self.button_row = QHBoxLayout()
        self.button_row.addWidget(self.file_label, 1)
        self.button_row.addWidget(self.select_button)
        self.layout.addLayout(self.button_row)
        
        self.notebook = QTabWidget()
        self.layout.addWidget(self.notebook)
        
        self.button_frame = QWidget()
        self.button_layout = QHBoxLayout(self.button_frame)
        self.button_layout.setContentsMargins(0, 10, 0, 10)
        
        self.run_selected_button = QPushButton("Open Selected")
        self.run_selected_button.clicked.connect(self.run_selected)
        self.button_layout.addWidget(self.run_selected_button)
        
        self.run_all_button = QPushButton("Open All in Tab")
        self.run_all_button.clicked.connect(self.run_paths)
        self.button_layout.addWidget(self.run_all_button)
        
        self.button_layout.addStretch()
        self.layout.addWidget(self.button_frame)
        
        self.statusBar().showMessage("Ready")
    
    def setup_system_tray(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(255, 255, 255))
        
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("xdg-open Launcher")
        
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
        
        for i in range(self.notebook.count()):
            self.notebook.removeTab(0)
        self.groups.clear()
        self.treeviews.clear()
        
        try:
            with open(file_path, 'r') as file:
                lines = [line.strip() for line in file if line.strip()]
            
            current_group = "Default"
            self.groups[current_group] = []
            
            for line in lines:
                if re.match(r'^\[.*\]$', line):
                    group_name = line[1:-1].strip()
                    if group_name and group_name not in self.groups:
                        self.groups[group_name] = []
                    current_group = group_name
                else:
                    self.groups[current_group].append(line)
            
            for group_name, group_lines in self.groups.items():
                tab_frame = QWidget()
                tab_layout = QVBoxLayout(tab_frame)
                
                scroll_area = QScrollArea()
                scroll_area.setWidgetResizable(True)
                scroll_area.setFrameShape(QFrame.Shape.NoFrame)
                
                table = QTableWidget()
                table.setColumnCount(2)
                table.setHorizontalHeaderLabels(["Path/URL", "Description"])
                table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
                table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
                table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                table.setRowCount(len(group_lines) // 2)
                
                for i in range(0, len(group_lines), 2):
                    row = i // 2
                    path = group_lines[i]
                    description = group_lines[i + 1] if i + 1 < len(group_lines) else "No description"
                    table.setItem(row, 0, QTableWidgetItem(path))
                    table.setItem(row, 1, QTableWidgetItem(description))
                    self.descriptions[path] = description
                
                table.itemDoubleClicked.connect(self.open_path_on_double_click)
                
                tab_layout.addWidget(table)
                self.notebook.addTab(tab_frame, group_name)
                self.treeviews[group_name] = table
            
            logging.debug(f"Loaded paths/URLs from {file_path} into groups: {list(self.groups.keys())}")
        except Exception as e:
            self.file_label.setText(f"Error reading file: {str(e)}")
            logging.error(f"Error reading file {file_path}: {str(e)}")
    
    def run_paths(self):
        current_index = self.notebook.currentIndex()
        if current_index < 0:
            logging.debug("No tab selected")
            return
        
        group_name = self.notebook.tabText(current_index)
        table = self.treeviews.get(group_name)
        if table:
            logging.debug(f"Opening all paths/URLs in tab: {group_name}")
            for row in range(table.rowCount()):
                path = table.item(row, 0).text()
                threading.Thread(target=self.run_path, args=(path,), daemon=True).start()
    
    def run_selected(self):
        current_index = self.notebook.currentIndex()
        if current_index < 0:
            logging.debug("No tab selected")
            return
        
        group_name = self.notebook.tabText(current_index)
        table = self.treeviews.get(group_name)
        if table:
            selected_rows = set(item.row() for item in table.selectedItems())
            logging.debug(f"Opening selected paths/URLs in tab {group_name}: {selected_rows}")
            for row in selected_rows:
                path = table.item(row, 0).text()
                threading.Thread(target=self.run_path, args=(path,), daemon=True).start()
    
    def open_path_on_double_click(self, item):
        table = item.tableWidget()
        row = item.row()
        path = table.item(row, 0).text()
        logging.debug(f"Double-clicked path/URL: {path}")
        threading.Thread(target=self.run_path, args=(path,), daemon=True).start()
    
    def run_path(self, path):
        try:
            process = subprocess.Popen(['xdg-open', path])
            logging.debug(f"Opened path/URL with xdg-open: {path}, PID: {process.pid}")
            time.sleep(1)
            if process.poll() is not None and process.returncode != 0:
                logging.error(f"xdg-open failed for {path}: Return code {process.returncode}")
                QMessageBox.critical(self, "Error", f"Failed to open {path}: xdg-open returned code {process.returncode}")
        except Exception as e:
            logging.error(f"Error opening path/URL {path}: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to open {path}: {str(e)}")
    
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
            self.settings.setValue("geometry", self.saveGeometry())
            self.tray_icon.hide()
            QApplication.quit()
            logging.debug("Application quit successfully")
        except Exception as e:
            logging.error(f"Error quitting application: {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = URLLauncherXDGApp()
    
    if not window.args.minimize:
        window.show()
    
    sys.exit(app.exec())
