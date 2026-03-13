import argparse
import sys
import re

from KlAkOAPI.AdmServer import KlAkAdmServer
from KlAkOAPI.SrvView import KlAkSrvView
from KlAkOAPI.FileCategorizer2 import KlAkFileCategorizer2
from KlAkOAPI.Params import KlAkArray, paramArray, paramParams

parser = argparse.ArgumentParser(description='Чтение содержимого файла')
md5_pattern = re.compile(r'\b[a-fA-F0-9]{32}\b') # Паттер для поиска хэша md5
    
# Добавляем параметр -p (обязательный)
parser.add_argument(
    '-p', 
    '--path', 
    type=str, 
    required=False,
    help='Путь к файлу для чтения'
)

parser.add_argument(
    '-s', 
    '--server', 
    type=str, 
    required=False,
    help='IP адрес или сетевое имя сервера KSC'
)

parser.add_argument(
    '-c', 
    '--category', 
    type=str, 
    required=False,
    help='Название категории, которую необходимо '
)

args = parser.parse_args()

file_path = args.path # сохранение в переменную file_path путя до файла
server_addr = args.server # сохранение ip адреса сервера KSC

# чтение файла и запись в переменную content
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

md5_hashes = md5_pattern.findall(content)

expressions = [] # создали переменную, в которую будем сладывать объекты хэшей

for md5 in md5_hashes:
        expr = paramParams({
            "ex_type": 4,  # Тип "имя файла"
            "str": md5,     # Значение
            "str_op": 0     # Оператор (0 - равно)
        })
        expressions.append(expr)

server_url = "http://192.168.1.90"
username = "KLAdmin"
password = "31VB*hs!6%Qz"

server = KlAkAdmServer.Create(server_url, username, password, verify=False)

# Подключение к серверу
oSrvView = KlAkSrvView(server)
# Запускаем итератор для получения всех категорий
wstrIteratorId = oSrvView.ResetIterator(
    "customcategories",  # Таблица с пользовательскими категориями
    "",                   # Фильтр (пустой - все записи)
    KlAkArray(["id", "name"]),  # Поля, которые хотим получить
    [],                    # Параметры
    {},                    # Дополнительные настройки
    300                    # Размер пакета
).OutPar("wstrIteratorId")

def getCategoryId(oSrvView, wstrIteratorId):
    try:
    # Получаем количество записей
        count = oSrvView.GetRecordCount(wstrIteratorId).RetVal()
        if count == 0:
            return None
            
        # Получаем все записи
        records = oSrvView.GetRecordRange(wstrIteratorId, 0, count).OutPar("pRecords")
        
        # Ищем категорию с нужным именем
        for item in records["KLCSP_ITERATOR_ARRAY"]:
            if "id" in item and "name" in item:
                if item["name"].lower() == category_name.lower():
                    return item["id"]
        return None
    finally:
        # Важно освободить итератор
        oSrvView.ReleaseIterator(wstrIteratorId)


category_id = getCategoryId(oSrvView, wstrIteratorId)


# Подключение к серверу
fc = KlAkFileCategorizer2(server)

# try:
    # Получаем текущие данные категории
oCategoryData = fc.GetCategory(nCategoryId=category_id)
oCatProps = oCategoryData.respose_text["pCategory"]
        
    # Добавляем новые выражения в секцию включений
target_field = "inclusions"
current_list = oCatProps.get(target_field, [])
        
for expr in expressions:
    current_list.append(expr)
        
oCatProps[target_field] = current_list
        
    # # Убеждаемся, что CategoryFilter настроен правильно
    # if "CategoryFilter" not in oCatProps:
    #     oCatProps["CategoryFilter"] = paramParams({"MetadataFlag": 256})
    # else:
    #     cat_filter = oCatProps["CategoryFilter"]
    #     if "MetadataFlag" in cat_filter:
    #         current_flag = cat_filter["MetadataFlag"]
    #         if (current_flag & 256) == 0:
    #             cat_filter["MetadataFlag"] = current_flag | 256
    #     else:
    #         cat_filter["MetadataFlag"] = 256
        
    # Обновляем категорию
result = fc.UpdateCategory(nCategoryId=category_id, pCategory=oCatProps)
