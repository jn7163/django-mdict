# -*- coding: utf-8 -*-
import os
import re
import time
from itertools import chain

is_leven = False
try:
    import Levenshtein  # python-Levenshtein包

    is_leven = True
except ImportError as e:
    print('Levenshtein not support')
from django.db.utils import OperationalError
from nltk.data import path as nltk_path
from nltk.stem import WordNetLemmatizer
from spellchecker import SpellChecker

from base.base_func import print_log_info, DebugLevel
from base.base_constant import builtin_dic_prefix
from base.sys_utils import check_system
from mdict.models import MyMdictEntry, MyMdictItem
from mdict.serializers import mdxentry
from mysite.settings import BASE_DIR
from .init_utils import init_mdict_list
from .loop_search import loop_search_sug
from .mdict_config import get_config_con

if check_system() == 0:
    from .multiprocess_search import pool, multiprocess_search_mdx, multiprocess_search_sug, check_pool_recreate, \
        loop_create_model
else:
    from .multithread_search import thpool, multithread_search_mdx, multithread_search_sug, \
        check_threadpool_recreate, loop_create_thread_model

nltk_path.append(BASE_DIR + os.sep + 'media' + os.sep + 'nltk_data')
lemmatizer = WordNetLemmatizer()
lemmatizer.lemmatize('a')
# WordNetLemmatizer()第一次运行lemmatize()慢，需要初始化，将本地语料库调入内存，耗时1秒多，因此这里要预加载。


spell = SpellChecker(distance=1)
# 默认距离为2，比较慢，大概1.6秒左右，设置距离为1后，大约0.001秒左右。

builtin_dic_name = '内置词典'


def search(query, is_en, group):
    record_list = []
    query = query.strip()
    t2 = time.perf_counter()
    try:
        record_list = search_mdx_dic(query, record_list, group)
    except FileNotFoundError:
        print_log_info('mdx file not found, mdx search failed, need recache!', DebugLevel.error)
        init_mdict_list(True)
        record_list = search_mdx_dic(query, record_list, group)
        # 重新生成cache文件的代码
    except OperationalError as e:
        print(e)
        print_log_info('modify database failed!', DebugLevel.error)
        if check_system() == 0:
            loop_create_model()
        elif check_system() == 1:
            loop_create_thread_model()
        record_list = search_mdx_dic(query, record_list, group)

    merge_entry_enable = get_config_con('merge_entry_enable')
    builtin_dic_enable = get_config_con('builtin_dic_enable')
    spell_check = get_config_con('spell_check')
    lemmatize = get_config_con('lemmatize')

    t3 = time.perf_counter()
    if merge_entry_enable:
        record_list = merge_record(query, record_list)
    t4 = time.perf_counter()

    if builtin_dic_enable:
        record_list = search_bultin_dic(query, record_list, is_en)

    if lemmatize == 1:
        record_list = lemmatize_func(query, record_list, is_en)
    elif lemmatize == 2:
        if len(record_list) == 0:
            record_list = lemmatize_func(query, record_list, is_en)

    if spell_check == 1:
        record_list = key_spellcheck(query, record_list, is_en)
    elif spell_check == 2:
        if len(record_list) == 0:
            record_list = key_spellcheck(query, record_list, is_en)
    t5 = time.perf_counter()
    # print(round(t3 - t2, 4), round(t4 - t3, 4), round(t5 - t4, 4))
    # print(query, round(t5 - t2, 4))
    return record_list


def clear_duplication(record_list):
    # 查询coaling station,enwiki-p1指向fuelling station，enwiki-p3指向Fuelling station，最后是重复的词条，因此这里比较f_pk,f_p1,f_p2，如果相同，说明重复
    # 其2是简繁查询，有的词典自带简繁转化，因此查一遍简，再查一遍繁，合并，导致结果重复
    for i in range(len(record_list) - 1, -1, -1):
        mdx_i = record_list[i]
        i_pk = mdx_i.f_pk
        i_p1 = mdx_i.f_p1
        i_p2 = mdx_i.f_p2
        d_list = []
        if i_pk != -1:
            for j in range(len(record_list) - 1, -1, -1):
                mdx_j = record_list[j]
                j_pk = mdx_j.f_pk
                j_p1 = mdx_j.f_p1
                j_p2 = mdx_j.f_p2
                if i_pk == j_pk and i_p1 == j_p1 and i_p2 == j_p2:
                    d_list.append(j)
        if len(d_list) > 1:
            del record_list[i]
    return record_list


def process_link(matched):
    return '<a class="badge badge-pill badge-primary" style="text-decoration:underline" href="entry://' + matched.group(
        1) + '">' + matched.group(1) + '</a>'


def process_link2(matched):
    return '<div class="badge badge-pill badge-warning" style="cursor:pointer;" onclick="elementDisplay(\'wrap_div\')">展开/折叠</div><div name="wrap_div" style="display:none">' + matched.group(
        1) + '</div>'


def search_bultin_dic_sug(query):
    r_list = search_builtin(query)
    a_list = []
    for r in r_list:
        a_list.append(r.mdict_entry)

    return a_list


sug_temp_list = []


def sug_callback(request, result):
    global mdx_temp_list
    sug_temp_list.clear()
    sug_temp_list.extend(result)


def search_mdx_sug(dic_pk, query, group, flag):
    global pool, thpool
    sug = []
    if check_system() == 0 and dic_pk == -1:
        cpunums = get_config_con('process_num')

        pool = check_pool_recreate(pool)

        q_list = ((i, query, group) for i in range(cpunums))
        record_list = pool.starmap(multiprocess_search_sug, q_list)
        for r in record_list:
            sug.extend(r)
    elif check_system() == 1 and dic_pk == -1:
        # sug.extend(loop_search_sug(dic_pk, query, flag, group))#for循环查询

        cpunums = get_config_con('process_num')

        thpool = check_threadpool_recreate(thpool)

        q_list = ((i, query, group) for i in range(cpunums))
        record_list = thpool.starmap(multithread_search_sug, q_list)
        for r in record_list:
            sug.extend(r)
    else:  # 单个词典的查询提示
        sug.extend(loop_search_sug(dic_pk, query, flag, group))

    return sug


def get_min_length(str1, str2):
    return len(str1) if len(str1) <= len(str2) else len(str2)


def get_mdict_content(mymdictentry):
    mymdictitem_set = mymdictentry.mymdictitem_set.all()
    mdict_content = list()

    if len(mymdictitem_set) == 1:
        mdict_content.append(
            "<div class='card-body mymdict_entry'><b>" + mymdictentry.mdict_entry + "</b><ol class='olnone'>")
    else:
        mdict_content.append(
            "<div class='card-body mymdict_entry'><b>" + mymdictentry.mdict_entry + "</b><ol class='olnum'>")

    for m in mymdictitem_set:
        item_entry = ''
        if m.item_entry is not None:
            item_entry = m.item_entry
        item_content = ''
        if m.item_content is not None:
            # 如果是自带的TextField，为了在html上显示，需要手动将\r\n替换成<br />，这里用了ckeditor，就不用替换了
            item_content = m.item_content
            item_content = re.sub(r'\[link\](.+?)\[/link\]', process_link, item_content)  # link标签，词条跳转
            item_content = re.sub(r'\[wrap\](.+?)\[/wrap\]', process_link2, item_content)  # wrap标签，折叠内容
            # 懒惰匹配写成r'\[link\](.+)?\[/link\]'是错误的
        if m.item_type is None:
            mdict_content.append('<li class="mymdict_item">')
            if m.item_entry is None:
                mdict_content.append('<div class="item_content">' + item_content + "</div></li>")
            else:
                mdict_content.append(item_entry + '<br /><div class="item_content">' + item_content + "</div></li>")
        else:
            mdict_content.append(
                "<li class='mymdict_item'>" + item_entry + "<span class='badge badge-pill badge-secondary'>"
                + m.item_type.mdict_type + "</span><br /><div class='item_content'>" + item_content + "</div></li>")

    mdict_content.append('</ol></div>')
    return mdict_content


def extract_bultin_dic_all(r_list):
    mdict = []
    mdx_entry = []
    r_list_len = len(r_list)
    mdict.append(builtin_dic_prefix)

    i = 1

    for r in r_list:
        mdx_entry.append(r.mdict_entry + '/')  # 将显示的词条名用斜杠分隔开

        mdict_content = get_mdict_content(r)

        if 1 <= i < r_list_len:
            mdict_content.append('<hr />')
        i += 1

        mdict.append(''.join(mdict_content))
    if r_list_len > 0:
        entry_t = ''.join(mdx_entry)
        entry_t = entry_t[:len(entry_t) - 1]  # 去掉entry后面的最后一个斜杠
        return mdxentry(builtin_dic_name, entry_t, ''.join(mdict), 0, -1, -1, -1, -1)
    else:
        return None


def search_builtin(query):
    # 查询内置词典
    query = query.replace('《', '').replace('》', '').replace('(', '').replace(')', '').lower()

    q_list = query.split(' ')
    if len(q_list) == 1:
        q_list = query.split('-')

    r_list = MyMdictEntry.objects.none()
    entry_list = MyMdictItem.objects.none()
    reg = r'^(.){1,' + str(len(query) * 2) + r'}$'
    for q in q_list:
        if q != '':
            r_list = chain(r_list,
                           MyMdictEntry.objects.all().filter(mdict_entry__icontains=q).filter(mdict_entry__iregex=reg))
            entry_list = chain(entry_list,
                               MyMdictItem.objects.all().filter(item_entry__icontains=query).filter(
                                   item_entry__iregex=reg))
    entry_list = list(entry_list)
    r_list = list(r_list)

    if is_leven:
        for i in range(len(r_list) - 1, -1, -1):
            # Levenshtein包含大小写，因此要将两字符串都取小写再计算
            if Levenshtein.ratio(query, r_list[i].mdict_entry.lower()) < 0.85:
                del r_list[i]
        for e in entry_list:
            if e.item_mdict is not None:
                if Levenshtein.ratio(query, e.item_entry.lower()) >= 0.85:
                    r_list.append(e.item_mdict)
    else:
        for e in entry_list:
            if e.item_mdict is not None:
                r_list.append(e.item_mdict)

    # 去重
    for i in range(len(r_list) - 1, -1, -1):
        for j in range(i - 1, -1, -1):
            if r_list[i].mdict_entry == r_list[j].mdict_entry:
                del r_list[i]
                break
    return r_list


def search_bultin_dic(query, record_list, is_en):
    r_list = search_builtin(query)

    m_entry = extract_bultin_dic_all(r_list)
    if m_entry is not None:
        record_list.append(m_entry)
    return record_list


mdx_temp_list = []


def mdx_callback(request, result):
    global mdx_temp_list
    mdx_temp_list.clear()
    mdx_temp_list.extend(result)


def search_mdx_dic(query, record_list, group):
    global pool, thpool
    # 查询mdx词典
    if check_system() == 0:
        pool = check_pool_recreate(pool)
        cpunums = get_config_con('process_num')
        q_list = ((i, query, group) for i in range(cpunums))
        a_list = pool.starmap(multiprocess_search_mdx, q_list)
        for a in a_list:
            record_list.extend(a)

    else:
        # record_list = loop_search_mdx(record_list, query, group)#for循环查询

        thpool = check_threadpool_recreate(thpool)
        cpunums = get_config_con('process_num')
        q_list = ((i, query, group) for i in range(cpunums))
        a_list = thpool.starmap(multithread_search_mdx, q_list)
        for a in a_list:
            record_list.extend(a)

    return record_list


def key_spellcheck(query, record_list, is_en):
    # 拼写检查
    # 对只含字母，短横杠、撇号和空格的单词进行拼写检查
    if is_en:
        # 这里设置成自定义配置，是否开启拼写检查，始终开启拼写检查，仅当查询无结果时开启拼写检查，关闭拼写检查，推荐第二种设置。
        '''
        if len(record_list) > 0 and record_list[0].mdx_name == builtin_dic_name:
            c_list = spellcheck(query)
            for i in range(len(c_list) - 1, -1, -1):
                if c_list[i] == query.lower():
                    del c_list[i]
            if len(c_list) > 0:
                if len(c_list) > 9:
                    c_list = c_list[:9]
                mdxentry_t = record_list[0]
                mdict_content = list(mdxentry_t.mdx_record)
                mdict_content.append('<hr /><div>' + query + '拼写检查：</div>')
                for c in c_list:
                    mdict_content.append('<div><a href="entry://' + c + '">' + c + '</a></div>')
                mdxentry_t.mdx_record = ''.join(mdict_content)
                record_list.pop(0)
                record_list.append(mdxentry_t)
        '''
        c_list = spellcheck(query)
        for i in range(len(c_list) - 1, -1, -1):
            if c_list[i] == query.lower():
                del c_list[i]
        if len(c_list) > 0:
            if len(c_list) > 9:
                c_list = c_list[:9]
            mdict_content = ['<div>' + query + '拼写检查：</div>']
            for c in c_list:
                mdict_content.append('<div><a href="entry://' + c + '">' + c + '</a></div>')
            # record_list.insert(0, mdxentry(builtin_dic_name, query, ''.join(mdict_content), 20, -1, -1, -1))
            record_list.append(mdxentry(builtin_dic_name, query, ''.join(mdict_content), 20, -1, -1, -1, -1))
    return record_list


def lemmatize_func(query, record_list, is_en):
    # 设置成自定义功能，全局启用原形推测，仅在查询无结果时启用原形推测，关闭原形推测，推荐第二种设置。
    words_list = []
    if is_en:
        words_list = lemmatize_word(query)

    words_list_len = len(words_list)
    mdict = []
    if words_list_len > 0:
        mdict.append('<div>' + query + '原形推测：</div>')
        for w in words_list:
            mdict.append(
                '<div><span class="badge badge-pill badge-light">' + w[1] + '</span><a href="entry://' + w[0] + '">' +
                w[0] + '</a></div>')

        # if len(record_list) == 0:
        record_list.append(mdxentry(builtin_dic_name, '', ''.join(mdict), 0, -1, -1, -1, -1))
        # else:
        #     if record_list[len(record_list) - 1].mdx_name == builtin_dic_name:
        #         b = record_list[len(record_list) - 1]
        #
        #         txt = b.mdx_record
        #         txt += '<hr />'
        #         txt += ''.join(mdict)
        #         b.mdx_record = txt
        #         del record_list[len(record_list) - 1]
        #         record_list.append(b)
        #     else:
        #         record_list.append(mdxentry(builtin_dic_name, '', ''.join(mdict), builtin_dic_pror, -1, -1, -1, -1))
    return record_list


def lemmatize_word(query):  # 使用nltk的WordNetLemmatizer()获得单词变体的原形
    query = query.lower()
    words_list = list()
    # n名词,a形容词,r副词,v动词
    words_list.append((lemmatizer.lemmatize(query, pos='n'), 'n.'))
    words_list.append((lemmatizer.lemmatize(query, pos='a'), 'adj.'))
    words_list.append((lemmatizer.lemmatize(query, pos='r'), 'adv.'))
    words_list.append((lemmatizer.lemmatize(query, pos='v'), 'v.'))
    r_list = []
    for w in words_list:
        if w[0] != query and not w[0] in r_list:
            r_list.append(w)

    return r_list


def spellcheck(query):  # 使用SpellChecker()来实现拼写检查
    misspelled = spell.unknown([query])
    c_list = []
    for word in misspelled:
        # Get the one `most likely` answer
        co = spell.correction(word)

        # Get a list of `likely` options
        ca = spell.candidates(word)
        c_list.extend(list(ca))
        if co not in c_list:
            c_list.insert(0, co)

    return c_list


def merge_record(query, record_list):
    # 多于4个的词条进行合并，主要是处理国家教育研究院双语词汇双向词典，该词典查variation有27个词条。
    # 长度小于500才合并，原因是英和中词典的a词条都合并起来，特别特别长，iframe展开时，台式机要卡住好长时间才能显示
    merge_entry_num = get_config_con('merge_entry_num')
    merge_entry_max_length = get_config_con('merge_entry_max_length')

    dic_dict = {}
    for i in range(len(record_list)):
        mdx_name = record_list[i].mdx_name
        mdx_record = record_list[i].mdx_record
        if len(mdx_record) < merge_entry_max_length:  # 这里暂时性的判断
            if mdx_name in dic_dict:
                dic_dict[mdx_name] += 1
            else:
                dic_dict[mdx_name] = 1

    dic_list = []

    for k, v in dic_dict.items():
        if v >= merge_entry_num:
            dic_list.append(k)

    t_list = []
    for dic in dic_list:
        record = ''
        pror = 1
        for i in range(len(record_list) - 1, -1, -1):
            mdx = record_list[i]
            if mdx.mdx_name == dic:
                record = mdx.mdx_record + record
                pror = mdx.mdx_pror
                del record_list[i]
        t_list.append(mdxentry(dic, query, record, pror, -1, -1, -1, -1))

    record_list.extend(t_list)
    return record_list
