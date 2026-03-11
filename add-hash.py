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

args = parser.parse_args()

file_path = args.path # сохранение в переменную file_path путя до файла
server_addr = args.server # сохранение ip адреса сервера KSC

# чтение файла и запись в переменную content
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

md5_hashes = md5_pattern.findall(content)


server_url = "http://192.168.1.90"
username = "KLAdmin"
password = "31VB*hs!6%Qz"

server = KlAkAdmServer.Create(server_url, username, password, verify=False)
fc = KlAkFileCategorizer2(server)