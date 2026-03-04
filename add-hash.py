import argparse
import sys

from KlAkOAPI.AdmServer import KlAkAdmServer
from KlAkOAPI.SrvView import KlAkSrvView
from KlAkOAPI.FileCategorizer2 import KlAkFileCategorizer2
from KlAkOAPI.Params import KlAkArray, paramArray, paramParams

parser = argparse.ArgumentParser(description='Чтение содержимого файла')
    
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

file_path = args.path
server_addr = args.server

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

hash_arr = content.split('\n')
print(hash_arr)

# Подключение к серверу KSC 
try:
    server = KlAkAdmServer.Create(server_addr, username, password, verify=False)
except Exception as e:
    print(f"Ошибка подключения к серверу: {e}")
    sys.exit()