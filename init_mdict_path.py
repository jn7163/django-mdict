import json
import os

tk_exist = False
try:
    import tkinter as tk
    from tkinter.filedialog import askdirectory

    tk_exist = True
except:
    print('tkinter not installed')

json_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mdict_path.json')
config = {'mdict_path': [], 'audio_path': []}

if tk_exist:
    root = tk.Tk()
    root.withdraw()  # 隐藏主界面

    _path = askdirectory()
    config = {'mdict_path': [_path]}
    print('mdict_path', _path)
    _path = askdirectory()
    # 如果用户关闭了选择框，那么返回值是什么？
    config.update({'audio_path': [_path]})
    print('audio_path', _path)


def write_json_file(con, file, mode='w'):
    with open(file, mode, encoding='utf-8') as f:
        json.dump(con, f, indent=4)


def process_list(path_list):
    for i in range(len(path_list) - 1, -1, -1):
        if path_list[i] == "":
            del path_list[i]
        elif not isinstance(path_list[i], str):
            del path_list[i]
    return path_list


if os.path.exists(json_file):
    temp = ''
    with open(json_file, 'r', encoding='utf-8') as f:
        temp = f.read()
    try:
        data = json.loads(temp)
        mdict_path_list = process_list(data['mdict_path'])
        audio_path_list = process_list(data['audio_path'])

        mdict_path_list.extend(process_list(config['mdict_path']))
        audio_path_list.extend(process_list(config['audio_path']))

        new_data = {'mdict_path': mdict_path_list, 'audio_path': audio_path_list}
        write_json_file(new_data, json_file)
    except:
        write_json_file(config, json_file)
else:
    write_json_file(config, json_file)
