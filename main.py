# -*- coding: utf-8 -*-

import re
import csv
from bs4 import BeautifulSoup, Comment

def parse_views(views_tag):
    """Преобразует строку просмотров (например, '4.2K') в число."""
    if not views_tag:
        return 0
    text = views_tag.get_text(strip=True)
    match = re.search(r'([\d.]+)([KkMm])?', text)
    if not match:
        return 0
    num_str = match.group(1)
    suffix = match.group(2)
    try:
        num = float(num_str)
        if suffix and suffix.lower() == 'k':
            num *= 1000
        elif suffix and suffix.lower() == 'm':
            num *= 1000000
        return int(num)
    except:
        return 0

def get_likes(block):
    """Универсальное извлечение количества лайков из блока."""
    # Сначала ищем span с классом PostBottomButtonReaction__label
    likes_span = block.find('span', class_='PostBottomButtonReaction__label')
    if likes_span:
        try:
            return int(likes_span.get_text(strip=True))
        except:
            pass
    # Затем ищем a с aria-label вида "6 Лайк"
    like_link = block.find('a', class_='PostBottomButton', attrs={'aria-label': re.compile(r'\d+')})
    if like_link:
        label = like_link.get('aria-label', '')
        match = re.search(r'(\d+)', label)
        if match:
            return int(match.group(1))
    return 0

def get_shares(block):
    """Количество репостов."""
    share_link = block.find('a', class_='PostBottomButton', href=re.compile(r'act=publish'))
    if share_link and share_link.has_attr('aria-label'):
        label = share_link['aria-label']
        match = re.search(r'(\d+)', label)
        if match:
            return int(match.group(1))
    return 0

def get_replies(block):
    """Количество ответов (комментариев к посту или к комментарию)."""
    replies_link = block.find('a', class_='_item_replies')
    if replies_link:
        if replies_link.has_attr('data-replies-count'):
            try:
                return int(replies_link['data-replies-count'])
            except:
                pass
        if replies_link.has_attr('aria-label'):
            label = replies_link['aria-label']
            match = re.search(r'(\d+)', label)
            if match:
                return int(match.group(1))
    return 0

def extract_item_data(block):
    """Извлекает данные из одного блока (комментарий или пост)."""
    item = {}

    # Определяем тип элемента по id блока
    block_id = block.get('id', '')
    if block_id.startswith('wall_reply-'):
        item['type'] = 'comment'
    elif block_id.startswith('wall-'):
        item['type'] = 'post'
    else:
        item['type'] = 'unknown'

    # --- Основная ссылка и дата ---
    date_link = block.find('a', class_='wi_date')
    if date_link:
        href = date_link.get('href', '')
        # Преобразуем мобильную ссылку в обычную
        item['link'] = href.replace('https://m.vk.com/', 'https://vk.com/')
        item['date'] = date_link.get_text(strip=True)
        # Извлекаем post_id из части wall-..._число
        match_post = re.search(r'wall-?\d+_(\d+)', href)
        item['post_id'] = match_post.group(1) if match_post else None
        # Для комментариев извлекаем reply_id
        if item['type'] == 'comment':
            match_reply = re.search(r'reply=(\d+)', href)
            item['reply_id'] = match_reply.group(1) if match_reply else None
        else:
            item['reply_id'] = None
    else:
        item['link'] = None
        item['date'] = None
        item['post_id'] = None
        item['reply_id'] = None

    # --- owner_id из атрибута data-post-id блока ---
    owner_id = None
    if block.has_attr('data-post-id'):
        data_post_id = block['data-post-id']
        # формат: -79244517_1714353 или -79244517_13771
        parts = data_post_id.split('_')
        if parts:
            owner_id = parts[0]  # может быть с минусом
    item['owner_id'] = owner_id

    # --- Автор (название группы или имя пользователя) ---
    author_div = block.find('div', class_='wi_author')
    if author_div:
        a_tag = author_div.find('a', class_='pi_author')
        if a_tag:
            item['user_name'] = a_tag.get_text(strip=True)
        else:
            item['user_name'] = None
    else:
        item['user_name'] = None

    # --- Текст с заменой упоминаний (только для комментариев, но можно и для постов) ---
    text_div = block.find('div', class_='pi_text')
    if text_div:
        for mention in text_div.find_all('a', class_='mem_link'):
            mention_id = mention.get('mention_id')
            if not mention_id:
                href = mention.get('href', '')
                match = re.search(r'/id(\d+)', href)
                if match:
                    mention_id = f"id{match.group(1)}"
                else:
                    continue
            mention_text = mention.get_text(strip=True)
            replacement = f"[{mention_id}|{mention_text}]"
            mention.replace_with(replacement)
        raw_text = text_div.get_text()
        item['text'] = ' '.join(raw_text.split())
    else:
        item['text'] = None

    # --- Для комментариев: ищем user_id (для постов это группа, не нужно) ---
    user_id = None
    if item['type'] == 'comment':
        # Способ 1: из ссылки pi_author
        if author_div:
            a_tag = author_div.find('a', class_='pi_author')
            if a_tag:
                href = a_tag.get('href', '')
                match = re.search(r'/id(\d+)', href)
                if match:
                    user_id = match.group(1)
        # Способ 2: из класса al_unew{ID}
        if not user_id:
            elem_with_alunew = block.find(class_=re.compile(r'al_unew\d+'))
            if elem_with_alunew:
                classes = elem_with_alunew.get('class', [])
                for cls in classes:
                    match = re.search(r'al_unew(\d+)', cls)
                    if match:
                        user_id = match.group(1)
                        break
        # Способ 3: из onclick у ImageStatus__status
        if not user_id:
            status_span = block.find('span', class_='ImageStatus__status')
            if status_span and status_span.has_attr('onclick'):
                onclick = status_span['onclick']
                match = re.search(r'user_id[:\s]*(\d+)', onclick)
                if match:
                    user_id = match.group(1)
        # Способ 4: из класса _unew{ID}
        if not user_id:
            elem_with_unew = block.find(class_=re.compile(r'_unew\d+'))
            if elem_with_unew:
                classes = elem_with_unew.get('class', [])
                for cls in classes:
                    match = re.search(r'_unew(\d+)', cls)
                    if match:
                        user_id = match.group(1)
                        break
    item['user_id'] = user_id

    # --- Ссылка на автора ---
    if item['type'] == 'comment' and user_id:
        item['author_link'] = f"https://vk.com/id{user_id}"
    elif item['type'] == 'post' and owner_id:
        # Для группы owner_id отрицательный
        try:
            owner_num = int(owner_id)
            if owner_num < 0:
                item['author_link'] = f"https://vk.com/club{abs(owner_num)}"
            else:
                item['author_link'] = f"https://vk.com/id{owner_num}"
        except:
            item['author_link'] = None
    else:
        item['author_link'] = None

    # --- Просмотры ---
    views_span = block.find('span', class_='wall_item_views')
    item['views'] = parse_views(views_span)

    # --- Лайки ---
    item['likes'] = get_likes(block)

    # --- Репосты ---
    item['shares'] = get_shares(block)

    # --- Комментарии (ответы) ---
    item['replies'] = get_replies(block)

    return item

def build_owner_link(item):
    """Формирует ссылку с учётом владельца (для группы или пользователя)."""
    if not item.get('owner_id') or not item.get('post_id'):
        return None
    owner = item['owner_id']
    post_id = item['post_id']
    reply_id = item.get('reply_id')
    try:
        owner_num = int(owner)
    except:
        return None
    if owner_num < 0:
        # группа
        club = abs(owner_num)
        base = f"https://vk.com/club{club}?w=wall{owner}_{post_id}"
    else:
        # пользователь
        base = f"https://vk.com/id{owner}?w=wall{owner}_{post_id}"
    if reply_id:
        return base + f"_r{reply_id}"
    else:
        return base

def parse_vk_data(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    result = {'total_entries': 0, 'items': []}
    seen_keys = set()  # для уникальности: (owner_id, post_id, reply_id) или ссылка

    # Общее количество записей (может относиться и к постам, и к комментариям)
    total_header = soup.find('h2', class_='slim_header_block_top')
    if total_header:
        text = total_header.get_text(strip=True)
        match = re.search(r'\d+', text)
        if match:
            result['total_entries'] = int(match.group())

    def add_item_if_unique(item):
        # Создаём ключ уникальности
        if item.get('type') == 'comment' and item.get('reply_id'):
            key = (item.get('owner_id'), item.get('post_id'), item.get('reply_id'))
        elif item.get('type') == 'post' and item.get('post_id'):
            key = (item.get('owner_id'), item.get('post_id'), None)
        else:
            key = item.get('link')  # fallback
        if key and key not in seen_keys:
            seen_keys.add(key)
            result['items'].append(item)

    # Обычные элементы (посты и комментарии)
    for block in soup.find_all('div', class_='wall_item'):
        item = extract_item_data(block)
        if item['type'] != 'unknown':
            add_item_if_unique(item)

    # Элементы из preload_data
    preload_div = soup.find('div', id='preload_data')
    if preload_div:
        for comment_node in preload_div.find_all(string=lambda text: isinstance(text, Comment)):
            comments_html = comment_node.strip()
            if comments_html:
                comments_soup = BeautifulSoup(comments_html, 'html.parser')
                for block in comments_soup.find_all('div', class_='wall_item'):
                    item = extract_item_data(block)
                    if item['type'] != 'unknown':
                        add_item_if_unique(item)

    return result

def save_to_csv(items, filename='govnyarka2.csv'):
    """Сохраняет список элементов (постов и комментариев) в CSV."""
    fieldnames = [
        'ССЫЛКА',
        'ССЫЛКА С УЧЁТОМ ВЛАДЕЛЬЦА',
        'АВТОР',
        'ССЫЛКА НА АВТОРА',
        'ДАТА И ВРЕМЯ',
        'ТЕКСТ',
        'ПРОСМОТРОВ',
        'ЛАЙКОВ',
        'РЕПОСТОВ',
        'КОММЕНТАРИЕВ'
    ]
    with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for it in items:
            row = {
                'ССЫЛКА': it.get('link', ''),
                'ССЫЛКА С УЧЁТОМ ВЛАДЕЛЬЦА': build_owner_link(it) or '',
                'АВТОР': it.get('user_name', ''),
                'ССЫЛКА НА АВТОРА': it.get('author_link', ''),
                'ДАТА И ВРЕМЯ': it.get('date', ''),
                'ТЕКСТ': it.get('text', ''),
                'ПРОСМОТРОВ': it.get('views', 0),
                'ЛАЙКОВ': it.get('likes', 0),
                'РЕПОСТОВ': it.get('shares', 0),
                'КОММЕНТАРИЕВ': it.get('replies', 0)
            }
            writer.writerow(row)

if __name__ == '__main__':
    import chardet
    with open('govnyarka2.html', 'rb') as f:
        raw_data = f.read()
        detected = chardet.detect(raw_data)
        encoding = detected.get('encoding', 'utf-8')
        print(f"Определена кодировка: {encoding}")
        html = raw_data.decode(encoding)

    data = parse_vk_data(html)
    print(f"Всего записей (по заголовку): {data['total_entries']}, уникальных элементов: {len(data['items'])}")

    save_to_csv(data['items'], 'govnyarka22.csv')
    print("Данные сохранены в govnyarka22.csv")