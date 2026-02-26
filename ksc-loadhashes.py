#!/usr/bin/python
# -*- coding: utf-8 -*-

import sys
import os
import re
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QFileDialog, QCheckBox,
    QGroupBox, QMessageBox, QProgressBar, QComboBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QSplitter, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import urllib3
from KlAkOAPI.AdmServer import KlAkAdmServer
from KlAkOAPI.SrvView import KlAkSrvView
from KlAkOAPI.FileCategorizer2 import KlAkFileCategorizer2
from KlAkOAPI.Params import KlAkArray, paramArray, paramParams

# Отключаем предупреждения о самоподписанном сертификате
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CategoryLoaderWorker(QThread):
    """Отдельный поток для загрузки списка категорий"""
    categories_loaded = pyqtSignal(list)  # Сигнал с результатом
    error_occurred = pyqtSignal(str)  # Сигнал с ошибкой

    def __init__(self, server_url, username, password):
        super().__init__()
        self.server_url = server_url
        self.username = username
        self.password = password

    def run(self):
        try:
            # Подключение к серверу
            server = KlAkAdmServer.Create(self.server_url, self.username, self.password, verify=False)
            oSrvView = KlAkSrvView(server)

            # Запуск итератора для получения категорий
            wstrIteratorId = oSrvView.ResetIterator(
                "customcategories",
                "",
                KlAkArray(["id", "name"]),
                [],
                {},
                300
            ).OutPar("wstrIteratorId")

            try:
                # Получение количества записей
                count = oSrvView.GetRecordCount(wstrIteratorId).RetVal()
                if count == 0:
                    self.categories_loaded.emit([])
                    return

                # Получение всех записей
                records = oSrvView.GetRecordRange(wstrIteratorId, 0, count).OutPar("pRecords")
                categories = []

                # Извлечение имен категорий
                for item in records["KLCSP_ITERATOR_ARRAY"]:
                    if "id" in item and "name" in item:
                        categories.append(item["name"])

                self.categories_loaded.emit(categories)

            finally:
                oSrvView.ReleaseIterator(wstrIteratorId)

        except Exception as e:
            self.error_occurred.emit(f"Ошибка загрузки категорий: {str(e)}")


class KSCWorker(QThread):
    # Сигналы для обновления GUI
    log_message = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)  # success, message

    def __init__(self, server_url, username, password, category_name, data_file, trash_items_to_add):
        super().__init__()
        self.server_url = server_url
        self.username = username
        self.password = password
        self.category_name = category_name
        self.data_file = data_file
        self.trash_items_to_add = trash_items_to_add  # Список строк для добавления как имена файлов

    def log(self, message):
        self.log_message.emit(message)

    def find_category_id_by_name(self, server, name):
        try:
            oSrvView = KlAkSrvView(server)
            wstrIteratorId = oSrvView.ResetIterator(
                "customcategories",
                "",
                KlAkArray(["id", "name"]),
                [],
                {},
                300
            ).OutPar("wstrIteratorId")

            try:
                count = oSrvView.GetRecordCount(wstrIteratorId).RetVal()
                if count == 0:
                    return None

                records = oSrvView.GetRecordRange(wstrIteratorId, 0, count).OutPar("pRecords")
                for item in records["KLCSP_ITERATOR_ARRAY"]:
                    if "id" in item and "name" in item:
                        cat_id = item["id"]
                        cat_name = item["name"]
                        if cat_name.lower() == name.lower():
                            return cat_id
                return None
            finally:
                oSrvView.ReleaseIterator(wstrIteratorId)
        except Exception as e:
            self.log(f"❌ Ошибка поиска категории: {e}")
            return None

    def load_and_parse_data(self, filename):
        """Загружает и парсит данные из одного файла"""
        sha256_hashes = []
        other_items = []  # Для "хлама"

        try:
            with open(filename, "r", encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    # Проверка на SHA256 хэш (64 hex символа)
                    if re.match(r"^[a-fA-F0-9]{64}$", line):
                        sha256_hashes.append(line.lower())
                    # Остальное считаем "хламом"
                    else:
                        other_items.append(line)

            return sha256_hashes, other_items
        except FileNotFoundError:
            self.log(f"❌ Файл {filename} не найден")
            return [], []
        except Exception as e:
            self.log(f"❌ Ошибка чтения файла {filename}: {e}")
            return [], []

    def get_existing_items_in_category(self, fc, category_id):
        try:
            oCategoryData = fc.GetCategory(nCategoryId=category_id)
            oCatProps = oCategoryData.respose_text["pCategory"]

            existing_sha256 = set()
            existing_filenames = set()
            existing_filepaths = set()

            for field in ["inclusions", "exclusions"]:
                if field in oCatProps:
                    for item in oCatProps[field]:
                        if "value" in item:
                            value = item["value"]
                            if "str2" in value and value.get("ex_type") == 3:
                                existing_sha256.add(value["str2"].lower())
                            elif "str" in value and value.get("ex_type") == 4:
                                existing_filenames.add(value["str"])
                            elif "str" in value and value.get("ex_type") == 5:
                                existing_filepaths.add(value["str"])
            return existing_sha256, existing_filenames, existing_filepaths
        except Exception as e:
            self.log(f"❌ Ошибка получения существующих элементов: {e}")
            return set(), set(), set()

    def create_expressions(self, new_sha256_hashes, new_filenames, new_filepaths):
        expressions = []

        # SHA256 хэши
        for h in new_sha256_hashes:
            expr = paramParams({
                "ex_type": 3,
                "str2": h,
                "str_op": 0
            })
            expressions.append(expr)

        # Имена файлов
        for name in new_filenames:
            expr = paramParams({
                "ex_type": 4,
                "str": name,
                "str_op": 0
            })
            expressions.append(expr)

        # Пути к файлам (в данном случае не добавляем из "хлама", но оставляем логику)
        for path in new_filepaths:
            expr = paramParams({
                "ex_type": 5,
                "str": path,
                "str_op": 0
            })
            expressions.append(expr)

        return expressions

    def run(self):
        try:
            self.log("🌐 Подключение к KSC...")
            server = KlAkAdmServer.Create(self.server_url, self.username, self.password, verify=False)
            fc = KlAkFileCategorizer2(server)
            self.log("✅ Подключение установлено")

            # 1. Найти ID категории
            self.log(f"🔍 Поиск категории '{self.category_name}'...")
            category_id = self.find_category_id_by_name(server, self.category_name)
            if not category_id:
                self.finished_signal.emit(False, f"❌ Категория '{self.category_name}' не найдена")
                return

            self.log(f"✅ Категория найдена (ID: {category_id})")

            # 2. Загрузить и распарсить данные из файла
            self.log("📄 Чтение и парсинг данных из файла...")
            sha256_hashes, other_items = self.load_and_parse_data(self.data_file)

            self.log(f"✅ Загружено {len(sha256_hashes)} SHA256 хэшей")
            self.log(f"✅ Загружено {len(other_items)} элементов 'хлама'")

            # 3. Добавить выделенные элементы из "хлама" как имена файлов
            filenames_from_trash = self.trash_items_to_add
            self.log(f"➕ Будет добавлено {len(filenames_from_trash)} имен файлов из 'хлама'")

            if not (sha256_hashes or filenames_from_trash):
                self.finished_signal.emit(False, "❌ Нет корректных данных для добавления")
                return

            # 4. Получить существующие элементы
            self.log("🔄 Получение списка уже существующих элементов...")
            existing_sha256, existing_filenames, existing_filepaths = self.get_existing_items_in_category(fc,
                                                                                                          category_id)
            self.log(
                f"✅ Найдено {len(existing_sha256)} SHA256, {len(existing_filenames)} имен, {len(existing_filepaths)} путей")

            # 5. Отфильтровать дубликаты
            unique_new_sha256 = [h for h in sha256_hashes if h not in existing_sha256]
            unique_new_filenames = [name for name in filenames_from_trash if name not in existing_filenames]
            # Пути из "хлама" не добавляем

            total_new = len(unique_new_sha256) + len(unique_new_filenames)
            if total_new == 0:
                self.finished_signal.emit(False, "ℹ️ Все элементы из файла уже существуют в категории")
                return

            self.log(f"➕ Будет добавлено:")
            if unique_new_sha256:
                self.log(f"    - {len(unique_new_sha256)} новых SHA256 хэшей")
            if unique_new_filenames:
                self.log(f"    - {len(unique_new_filenames)} новых имен файлов")

            # 6. Создать выражения
            expressions = self.create_expressions(unique_new_sha256, unique_new_filenames, [])
            self.log(f"📦 Подготовлено {len(expressions)} выражений для добавления")

            # 7. Добавить в категорию
            self.log("📤 Добавление элементов в категорию...")
            oCategoryData = fc.GetCategory(nCategoryId=category_id)
            oCatProps = oCategoryData.respose_text["pCategory"]

            target_field = "inclusions"
            current_list = oCatProps.get(target_field, [])

            for expr in expressions:
                current_list.append(expr)

            oCatProps[target_field] = current_list

            # Установить CategoryFilter если нужно
            if "CategoryFilter" not in oCatProps:
                oCatProps["CategoryFilter"] = paramParams({"MetadataFlag": 256})
            else:
                cat_filter = oCatProps["CategoryFilter"]
                if "MetadataFlag" in cat_filter:
                    current_flag = cat_filter["MetadataFlag"]
                    if (current_flag & 256) == 0:
                        cat_filter["MetadataFlag"] = current_flag | 256
                else:
                    cat_filter["MetadataFlag"] = 256

            # Обновить категорию
            try:
                result = fc.UpdateCategory(nCategoryId=category_id, pCategory=oCatProps)
                if hasattr(result, 'respose_text') and 'PxgError' in result.respose_text:
                    error = result.respose_text['PxgError']
                    self.finished_signal.emit(False,
                                              f"❌ Ошибка: код={error.get('code')}, сообщение={error.get('message')}")
                else:
                    self.finished_signal.emit(True, "✅ Элементы успешно добавлены в категорию")
            except Exception as e:
                try:
                    error = result.Error()
                    self.finished_signal.emit(False,
                                              f"❌ Ошибка: код={error.get('code')}, сообщение={error.get('message')}")
                except:
                    self.finished_signal.emit(True, "✅ Элементы успешно добавлены в категорию")

        except Exception as e:
            self.finished_signal.emit(False, f"❌ Критическая ошибка: {str(e)}")


class KSCApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kaspersky Security Center - Загрузка данных")
        self.setGeometry(100, 100, 1000, 700)

        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Верхняя часть - подключение и выбор файла/категории
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)

        # Группа подключения
        connection_group = QGroupBox("Подключение к KSC")
        connection_layout = QFormLayout()

        self.server_input = QLineEdit("https://server-ip:13299")
        self.username_input = QLineEdit("username")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)

        connection_layout.addRow("Адрес сервера:", self.server_input)
        connection_layout.addRow("Логин:", self.username_input)
        connection_layout.addRow("Пароль:", self.password_input)

        connection_group.setLayout(connection_layout)
        top_layout.addWidget(connection_group)

        # Группа выбора категории
        category_group = QGroupBox("Категория")
        category_layout = QVBoxLayout()

        # Выпадающий список категорий
        self.category_combo = QComboBox()
        self.category_combo.addItem("Выберите категорию...")
        self.load_categories_button = QPushButton("Загрузить список категорий")
        self.load_categories_button.clicked.connect(self.load_categories)

        category_layout.addWidget(QLabel("Категория:"))
        category_layout.addWidget(self.category_combo)
        category_layout.addWidget(self.load_categories_button)

        category_group.setLayout(category_layout)
        top_layout.addWidget(category_group)

        # Группа выбора файла
        files_group = QGroupBox("Файл данных")
        files_layout = QFormLayout()

        self.data_file_input = QLineEdit()
        self.data_file_button = QPushButton("Выбрать...")
        self.data_file_button.clicked.connect(lambda: self.select_file(self.data_file_input, "Выбор файла с данными",
                                                                       "Текстовые файлы (*.txt);;Все файлы (*.*)"))

        data_file_layout = QHBoxLayout()
        data_file_layout.addWidget(self.data_file_input)
        data_file_layout.addWidget(self.data_file_button)
        files_layout.addRow("Файл с данными:", data_file_layout)

        # Пояснение к формату файла
        format_label = QLabel(
            "Формат файла:\n"
            "- SHA256 хэши (64 hex символа) будут добавлены автоматически\n"
            "- Остальные строки попадут в список 'хлама' для ручной обработки"
        )
        format_label.setWordWrap(True)
        files_layout.addRow(format_label)

        files_group.setLayout(files_layout)
        top_layout.addWidget(files_group)

        # Кнопка запуска анализа
        self.analyze_button = QPushButton("Анализировать файл")
        self.analyze_button.clicked.connect(self.analyze_file)
        top_layout.addWidget(self.analyze_button)

        # Нижняя часть - списки и управление
        bottom_widget = QFrame()
        bottom_widget.setFrameStyle(QFrame.StyledPanel)
        bottom_layout = QVBoxLayout(bottom_widget)

        # Список "хлама" с чекбоксами
        trash_group = QGroupBox("Элементы 'хлама' (не SHA256)")
        trash_layout = QVBoxLayout()

        # Кнопки управления списком
        trash_buttons_layout = QHBoxLayout()
        self.select_all_button = QPushButton("Выделить все")
        self.select_all_button.clicked.connect(self.select_all_trash)
        self.select_all_button.setEnabled(False)

        self.deselect_all_button = QPushButton("Снять выделение")
        self.deselect_all_button.clicked.connect(self.deselect_all_trash)
        self.deselect_all_button.setEnabled(False)

        self.delete_selected_button = QPushButton("Удалить выделенные")
        self.delete_selected_button.clicked.connect(self.delete_selected_trash)
        self.delete_selected_button.setEnabled(False)

        trash_buttons_layout.addWidget(self.select_all_button)
        trash_buttons_layout.addWidget(self.deselect_all_button)
        trash_buttons_layout.addWidget(self.delete_selected_button)
        trash_buttons_layout.addStretch()

        trash_layout.addLayout(trash_buttons_layout)

        # Список с чекбоксами
        self.trash_list = QListWidget()
        self.trash_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        trash_layout.addWidget(self.trash_list)

        trash_group.setLayout(trash_layout)
        bottom_layout.addWidget(trash_group)

        # Кнопка загрузки
        self.start_button = QPushButton("Загрузить данные в KSC")
        self.start_button.clicked.connect(self.start_upload)
        self.start_button.setEnabled(False)
        bottom_layout.addWidget(self.start_button)

        # Сплиттер для верхней и нижней частей
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_widget)
        splitter.setSizes([300, 400])  # Примерные размеры

        main_layout.addWidget(splitter)

        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Лог
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        main_layout.addWidget(QLabel("Лог:"))
        main_layout.addWidget(self.log_output)

        # Workers
        self.loader_worker = None
        self.upload_worker = None

        # Хранилище данных
        self.parsed_sha256 = []
        self.parsed_other = []

    def select_file(self, line_edit, title, filter_text):
        file_path, _ = QFileDialog.getOpenFileName(self, title, "", filter_text)
        if file_path:
            line_edit.setText(file_path)

    def log_message(self, message):
        self.log_output.append(message)

    def load_categories(self):
        # Проверка заполнения полей подключения
        if not self.server_input.text():
            QMessageBox.warning(self, "Ошибка", "Укажите адрес сервера")
            return

        if not self.username_input.text():
            QMessageBox.warning(self, "Ошибка", "Укажите логин")
            return

        if not self.password_input.text():
            QMessageBox.warning(self, "Ошибка", "Укажите пароль")
            return

        # Очищаем комбо-бокс и блокируем кнопку
        self.category_combo.clear()
        self.category_combo.addItem("Загрузка...")
        self.load_categories_button.setEnabled(False)

        # Создаем и запускаем worker для загрузки категорий
        self.loader_worker = CategoryLoaderWorker(
            self.server_input.text(),
            self.username_input.text(),
            self.password_input.text()
        )

        self.loader_worker.categories_loaded.connect(self.on_categories_loaded)
        self.loader_worker.error_occurred.connect(self.on_category_load_error)
        self.loader_worker.start()

    def on_categories_loaded(self, categories):
        # Обновляем комбо-бокс
        self.category_combo.clear()
        self.category_combo.addItem("Выберите категорию...")
        for category in categories:
            self.category_combo.addItem(category)

        self.load_categories_button.setEnabled(True)

        # Показываем сообщение, если категорий нет
        if not categories:
            QMessageBox.information(self, "Информация", "На сервере не найдено ни одной категории")

    def on_category_load_error(self, error_message):
        # Обновляем комбо-бокс
        self.category_combo.clear()
        self.category_combo.addItem("Выберите категорию...")
        self.load_categories_button.setEnabled(True)

        # Показываем сообщение об ошибке
        QMessageBox.critical(self, "Ошибка", error_message)

    def analyze_file(self):
        # Проверка наличия файла
        if not self.data_file_input.text():
            QMessageBox.warning(self, "Ошибка", "Выберите файл с данными")
            return

        # Проверка заполнения полей подключения (для будущего использования)
        if not self.server_input.text():
            QMessageBox.warning(self, "Ошибка", "Укажите адрес сервера")
            return

        if not self.username_input.text():
            QMessageBox.warning(self, "Ошибка", "Укажите логин")
            return

        if not self.password_input.text():
            QMessageBox.warning(self, "Ошибка", "Укажите пароль")
            return

        # Очищаем списки
        self.trash_list.clear()
        self.parsed_sha256 = []
        self.parsed_other = []

        # Очищаем лог
        self.log_output.clear()

        # Блокируем кнопку анализа
        self.analyze_button.setEnabled(False)

        try:
            # Загружаем и парсим данные
            self.log_message("📄 Начинаем анализ файла...")

            with open(self.data_file_input.text(), "r", encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    # Проверка на SHA256 хэш (64 hex символа)
                    if re.match(r"^[a-fA-F0-9]{64}$", line):
                        self.parsed_sha256.append(line.lower())
                    # Остальное считаем "хламом"
                    else:
                        self.parsed_other.append(line)

            self.log_message(f"✅ Анализ завершен:")
            self.log_message(f"    - Найдено {len(self.parsed_sha256)} SHA256 хэшей")
            self.log_message(f"    - Найдено {len(self.parsed_other)} элементов 'хлама'")

            # Заполняем список "хлама"
            for item in self.parsed_other:
                list_item = QListWidgetItem(item)
                list_item.setFlags(list_item.flags() | Qt.ItemIsUserCheckable)
                list_item.setCheckState(Qt.Unchecked)
                self.trash_list.addItem(list_item)

            # Активируем кнопки управления
            self.select_all_button.setEnabled(True)
            self.deselect_all_button.setEnabled(True)
            self.delete_selected_button.setEnabled(True)
            self.start_button.setEnabled(True)

            QMessageBox.information(self, "Анализ завершен",
                                    f"Файл проанализирован:\n"
                                    f"- SHA256 хэшей: {len(self.parsed_sha256)}\n"
                                    f"- Элементов 'хлама': {len(self.parsed_other)}")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка анализа файла: {str(e)}")
        finally:
            self.analyze_button.setEnabled(True)

    def select_all_trash(self):
        for i in range(self.trash_list.count()):
            item = self.trash_list.item(i)
            item.setCheckState(Qt.Checked)

    def deselect_all_trash(self):
        for i in range(self.trash_list.count()):
            item = self.trash_list.item(i)
            item.setCheckState(Qt.Unchecked)

    def delete_selected_trash(self):
        # Собираем индексы выделенных элементов (в обратном порядке для корректного удаления)
        selected_indexes = []
        for i in range(self.trash_list.count()):
            item = self.trash_list.item(i)
            if item.checkState() == Qt.Checked:
                selected_indexes.append(i)

        # Удаляем элементы
        for i in reversed(selected_indexes):
            self.trash_list.takeItem(i)

        self.log_message(f"🗑️ Удалено {len(selected_indexes)} элементов из списка 'хлама'")

    def start_upload(self):
        # Проверка выбора категории
        if self.category_combo.currentIndex() <= 0:
            QMessageBox.warning(self, "Ошибка", "Выберите категорию")
            return

        # Проверка наличия файла
        if not self.data_file_input.text():
            QMessageBox.warning(self, "Ошибка", "Выберите файл с данными")
            return

        # Собираем выделенные элементы из "хлама" для добавления как имена файлов
        trash_items_to_add = []
        for i in range(self.trash_list.count()):
            item = self.trash_list.item(i)
            if item.checkState() == Qt.Checked:
                trash_items_to_add.append(item.text())

        if not (self.parsed_sha256 or trash_items_to_add):
            QMessageBox.warning(self, "Ошибка", "Нет данных для загрузки (ни SHA256, ни выделенных элементов 'хлама')")
            return

        # Блокируем кнопки и показываем прогресс
        self.analyze_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.select_all_button.setEnabled(False)
        self.deselect_all_button.setEnabled(False)
        self.delete_selected_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Неопределенный прогресс

        # Очищаем лог
        self.log_output.clear()

        # Создаем и запускаем worker
        self.upload_worker = KSCWorker(
            self.server_input.text(),
            self.username_input.text(),
            self.password_input.text(),
            self.category_combo.currentText(),
            self.data_file_input.text(),
            trash_items_to_add  # Передаем выделенные элементы
        )

        self.upload_worker.log_message.connect(self.log_message)
        self.upload_worker.finished_signal.connect(self.on_worker_finished)
        self.upload_worker.start()

    def on_worker_finished(self, success, message):
        # Разблокируем кнопки и скрываем прогресс
        self.analyze_button.setEnabled(True)
        self.start_button.setEnabled(True)
        self.select_all_button.setEnabled(True)
        self.deselect_all_button.setEnabled(True)
        self.delete_selected_button.setEnabled(True)
        self.progress_bar.setVisible(False)

        # Показываем сообщение
        if success:
            QMessageBox.information(self, "Успех", message)
        else:
            QMessageBox.critical(self, "Ошибка", message)


def main():
    app = QApplication(sys.argv)
    window = KSCApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()