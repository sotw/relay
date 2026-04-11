import sys
import os
import platform
import subprocess
import shutil
import argparse
from urllib.parse import quote
from io import BytesIO

try:
    from PIL import Image, ImageSequence
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QLabel, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
                              QHeaderView, QMessageBox, QMenu)
from PyQt6.QtCore import Qt, QMimeData, QUrl, QPoint
from PyQt6.QtGui import QIcon, QPixmap, QImage, QGuiApplication, QDragEnterEvent, QDropEvent, QPainter, QColor, QDrag, QAction


class ImageGridClipboardApp(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.setWindowTitle("Image Grid Clipboard")
        self.image_paths = []
        self.video_paths = []
        self.image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
        self.video_extensions = {'.mp4', '.webm', '.avi', '.mov', '.mkv'}
        self.all_paths = []
        self.args = args
        self.folder_path = None
        
        self.setup_ui()
        self.setCentralWidget(self.central_widget)
        self.resize(800, 600)
        
        if args.folder:
            self.load_folder(args.folder)
    
    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        self.folder_label = QLabel("No folder selected")
        self.layout.addWidget(self.folder_label)
        
        self.select_button = QPushButton("Select Folder")
        self.select_button.clicked.connect(self.select_folder)
        
        self.button_row = QHBoxLayout()
        self.button_row.addWidget(self.folder_label, 1)
        self.button_row.addWidget(self.select_button)
        self.layout.addLayout(self.button_row)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Preview", "Filename", "Path", "Size"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.copy_image_to_clipboard)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        
        self.setAcceptDrops(True)
        self.table.setAcceptDrops(True)
        self.table.installEventFilter(self)
        
        self.layout.addWidget(self.table)
        
        self.statusBar().showMessage("Ready")
    
    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            self.load_folder(folder_path)
    
    def load_folder(self, folder_path):
        if not os.path.isdir(folder_path):
            QMessageBox.critical(self, "Error", f"Invalid folder: {folder_path}")
            return
        
        self.folder_path = folder_path
        self.folder_label.setText(folder_path)
        
        self.image_paths = []
        self.video_paths = []
        try:
            print(f"Scanning folder: {folder_path}")
            entries = list(os.scandir(folder_path))
            print(f"Found {len(entries)} entries")
            for entry in entries:
                try:
                    ext = os.path.splitext(entry.name.lower())[1]
                    if entry.is_file():
                        if ext in self.image_extensions:
                            self.image_paths.append(entry.path)
                        elif ext in self.video_extensions:
                            print(f"Found video: {entry.path}")
                            self.video_paths.append(entry.path)
                except Exception as e:
                    print(f"Error scanning {entry.path}: {e}")
        except PermissionError:
            QMessageBox.critical(self, "Error", f"Permission denied: {folder_path}")
            return
        except Exception as e:
            print(f"Error scanning folder: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error loading folder: {e}")
            return
        
        self.image_paths.sort()
        self.video_paths.sort()
        self.all_paths = self.image_paths + self.video_paths
        
        self.table.setRowCount(len(self.all_paths))
        
        for row, file_path in enumerate(self.all_paths):
            try:
                ext = os.path.splitext(file_path.lower())[1]
                
                if ext in self.video_extensions:
                    try:
                        pixmap = QPixmap(256, 256)
                        pixmap.fill(Qt.GlobalColor.transparent)
                        painter = QPainter(pixmap)
                        painter.fillRect(pixmap.rect(), QColor(60, 60, 60))
                        icon_size = 60
                        center_x = 128
                        center_y = 128
                        triangle = [
                            QPoint(center_x - icon_size//3, center_y - icon_size//2),
                            QPoint(center_x - icon_size//3, center_y + icon_size//2),
                            QPoint(center_x + icon_size//2, center_y)
                        ]
                        painter.setBrush(QColor(200, 200, 200))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawPolygon(triangle)
                        del painter
                        pixmap = pixmap.scaled(256, 256)
                        icon_item = QTableWidgetItem()
                        icon_item.setIcon(QIcon(pixmap))
                    except Exception as e:
                        print(f"Error creating video thumbnail: {e}")
                        icon_item = QTableWidgetItem("Video")
                    self.table.setItem(row, 0, icon_item)
                else:
                    pixmap = QPixmap(file_path)
                    scaled_pixmap = pixmap.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    
                    icon_item = QTableWidgetItem()
                    icon_item.setIcon(QIcon(scaled_pixmap))
                    self.table.setItem(row, 0, icon_item)
                
                filename = os.path.basename(file_path)
                self.table.setItem(row, 1, QTableWidgetItem(filename))
                self.table.setItem(row, 2, QTableWidgetItem(file_path))
                
                try:
                    file_size = os.path.getsize(file_path)
                    size_str = self.format_file_size(file_size)
                except OSError:
                    size_str = "Unknown"
                self.table.setItem(row, 3, QTableWidgetItem(size_str))
            except Exception as e:
                print(f"Error loading row {row} ({file_path}): {e}")
                self.table.setItem(row, 0, QTableWidgetItem("Error"))
        
        self.table.resizeRowsToContents()
        self.statusBar().showMessage(f"Loaded {len(self.image_paths)} images and {len(self.video_paths)} videos")
    
    def format_file_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def copy_image_to_clipboard(self, item):
        row = item.row()
        file_path = self.table.item(row, 2).text()
        
        if not os.path.exists(file_path):
            QMessageBox.critical(self, "Error", f"File not found: {file_path}")
            return
        
        ext = os.path.splitext(file_path.lower())[1]
        
        if ext in self.video_extensions or ext == '.gif':
            if not self.copy_file_reference_to_clipboard(file_path):
                QMessageBox.critical(self, "Error", f"Failed to copy file to clipboard")
                return
            self.statusBar().showMessage(f"Copied file! Cmd+V in Finder/Desktop to paste")
        else:
            if not self.copy_image_crossplatform(file_path):
                QMessageBox.critical(self, "Error", f"Failed to copy image to clipboard")
                return
            self.statusBar().showMessage(f"Copied to clipboard: {os.path.basename(file_path)}")
    
    def copy_image_crossplatform(self, image_path):
        ext = os.path.splitext(image_path.lower())[1]
        
        if ext in self.video_extensions:
            return self.copy_file_reference_to_clipboard(image_path)
        
        system = platform.system()
        
        if system == "Windows":
            return self._copy_to_windows_clipboard(image_path)
        elif system == "Darwin":
            return self._copy_to_macos_clipboard(image_path)
        else:
            return self._copy_to_linux_clipboard(image_path)
    
    def _copy_to_windows_clipboard(self, image_path):
        ext = os.path.splitext(image_path.lower())[1]
        
        if ext == '.gif' and HAS_PILLOW:
            return self._copy_gif_to_clipboard_windows(image_path)
        
        try:
            image = QImage(image_path)
            if image.isNull():
                return False
            
            clipboard = QGuiApplication.clipboard()
            clipboard.setImage(image)
            return True
        except Exception as e:
            print(f"Windows clipboard error: {e}")
            return self._copy_with_qt(image_path)
    
    def _copy_gif_to_clipboard_windows(self, image_path):
        try:
            with open(image_path, 'rb') as f:
                gif_data = f.read()
            
            clipboard = QGuiApplication.clipboard()
            mime_data = QMimeData()
            mime_data.setData('image/gif', gif_data)
            clipboard.setMimeData(mime_data)
            return True
        except Exception as e:
            print(f"Windows GIF clipboard error: {e}")
            return False
    
    def _copy_to_macos_clipboard(self, image_path):
        ext = os.path.splitext(image_path.lower())[1]
        
        if ext == '.gif':
            return self._copy_gif_to_clipboard_macos(image_path)
        
        try:
            abs_path = os.path.abspath(image_path)
            if ext in ['.png', '.jpg', '.jpeg', '.jpeg', '.tiff', '.bmp']:
                script = f'set the clipboard to (read (POSIX file "{abs_path}") as «class PNGf»)'
            else:
                script = f'set the clipboard to (POSIX file "{abs_path}")'
            
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return True
            print(f"osascript error: {result.stderr}")
        except Exception as e:
            print(f"macOS osascript error: {e}")
        
        return self._copy_with_qt(image_path)
    
    def _copy_gif_to_clipboard_macos(self, image_path):
        try:
            abs_path = os.path.abspath(image_path)
            script = f'tell app "Finder" to set the clipboard to (POSIX file "{abs_path}")'
            
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return True
                
            print(f"GIF copy error: {result.stderr}")
            return False
        except Exception as e:
            print(f"macOS GIF clipboard error: {e}")
            return False
    
    def _copy_to_linux_clipboard(self, image_path):
        try:
            if self._copy_with_qt(image_path):
                return True
            
            if shutil.which('xclip'):
                subprocess.run(
                    ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-i', image_path],
                    check=True
                )
                return True
            elif shutil.which('xsel'):
                subprocess.run(
                    ['xsel', '--clipboard', '--input'],
                    input=open(image_path, 'rb').read(),
                    check=True
                )
                return True
            
            return False
        except Exception as e:
            print(f"Linux clipboard error: {e}")
            return False
    
    def _copy_with_qt(self, image_path):
        try:
            image = QImage(image_path)
            if image.isNull():
                return False
            
            mime_data = QMimeData()
            mime_data.setImageData(image)
            
            clipboard = QGuiApplication.clipboard()
            clipboard.setMimeData(mime_data)
            return True
        except Exception as e:
            print(f"Qt clipboard error: {e}")
            return False
    
    def eventFilter(self, obj, event):
        if obj == self.table:
            if event.type() == event.Type.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif event.type() == event.Type.Drop:
                urls = event.mimeData().urls()
                if urls:
                    file_path = urls[0].toLocalFile()
                    if os.path.isfile(file_path):
                        ext = os.path.splitext(file_path.lower())[1]
                        if ext in self.image_extensions or ext in self.video_extensions:
                            folder = os.path.dirname(file_path)
                            if folder != self.folder_path:
                                self.load_folder(folder)
                return True
        return super().eventFilter(obj, event)
    
    def _start_drag(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        file_path = self.table.item(row, 2).text()
        
        if not os.path.exists(file_path):
            return
        
        abs_path = os.path.abspath(file_path)
        
        file_url = QUrl.fromLocalFile(abs_path)
        
        mime_data = QMimeData()
        mime_data.setUrls([file_url])
        
        mime_data.setData('text/uri-list', f"file://{quote(abs_path)}\n".encode())
        
        system = platform.system()
        if system == "Darwin":
            mime_data.setText(f"file://{quote(abs_path)}")
        elif system == "Linux":
            mime_data.setText(f"file://{quote(abs_path)}")
        
        drag = QDrag(self.table)
        drag.setMimeData(mime_data)
        
        item = self.table.item(row, 0)
        if item:
            pixmap = item.icon().pixmap(64, 64)
            if not pixmap.isNull():
                drag.setPixmap(pixmap)
                drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        
        drag.exec(Qt.DropAction.CopyAction)
        
        self.statusBar().showMessage(f"Drag ready! Drag to target app")
    
    def _show_context_menu(self, position):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        file_path = self.table.item(row, 2).text()
        
        menu = QMenu(self)
        
        copy_action = QAction("Copy to Clipboard", self)
        copy_action.triggered.connect(lambda: self._context_copy(row))
        menu.addAction(copy_action)
        
        drag_action = QAction("Drag to Target", self)
        drag_action.triggered.connect(lambda: self._context_drag(row))
        menu.addAction(drag_action)
        
        menu.exec(self.table.viewport().mapToGlobal(position))
    
    def _context_copy(self, row):
        item = self.table.item(row, 0)
        if item:
            self.copy_image_to_clipboard(item)
    
    def _context_drag(self, row):
        self._start_drag()
    
    def copy_file_reference_to_clipboard(self, file_path):
        system = platform.system()
        
        if system == "Windows":
            return self._copy_file_windows(file_path)
        elif system == "Darwin":
            return self._copy_file_macos(file_path)
        else:
            return self._copy_file_linux(file_path)
    
    def _copy_file_windows(self, file_path):
        try:
            subprocess.run(
                ['powershell', '-Command', f'Set-Clipboard -Path "{file_path}"'],
                check=True
            )
            return True
        except Exception as e:
            print(f"Windows file copy error: {e}")
            return False
    
    def _copy_file_macos(self, file_path):
        try:
            abs_path = os.path.abspath(file_path)
            print(f"Copying file to clipboard: {abs_path}")
            
            script = f'''
            tell application "Finder"
                set the clipboard to (POSIX file "{abs_path}")
            end tell
            '''
            
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"osascript error: {result.stderr}")
            
            clipboard_content = subprocess.run(
                ['osascript', '-e', 'clipboard info'],
                capture_output=True,
                text=True
            )
            print(f"Clipboard content: {clipboard_content.stdout}")
            
            return result.returncode == 0
        except Exception as e:
            print(f"macOS file copy error: {e}")
            return False
    
    def _copy_file_linux(self, file_path):
        try:
            file_uri = f"file://{quote(os.path.abspath(file_path))}"
            
            mime_data = QMimeData()
            mime_data.setText(file_uri)
            mime_data.setUrls([QUrl.fromLocalFile(file_path)])
            
            clipboard = QGuiApplication.clipboard()
            clipboard.setMimeData(mime_data)
            return True
        except Exception as e:
            print(f"Linux file copy error: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Image Grid Clipboard")
    parser.add_argument("folder", nargs="?", help="Path to folder containing images")
    parser.add_argument("-m", "--minimize", action="store_true", help="Start minimized")
    args = parser.parse_args()
    
    app = QApplication(sys.argv)
    window = ImageGridClipboardApp(args)
    
    if not args.minimize:
        window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
