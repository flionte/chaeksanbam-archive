import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import os
import re
import datetime
import html
import sys
import traceback
from bs4 import BeautifulSoup

BLOG_ID = "flionte"
RSS_URL = f"https://rss.blog.naver.com/{BLOG_ID}.xml"
REPO_DIR = "."
IMAGES_DIR = os.path.join(REPO_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': f'https://blog.naver.com/{BLOG_ID}'
}

def clean_filename(title):
    title = html.unescape(title)
    cleaned = re.sub(r'[\\/*?:"<>|]', '', title)
    cleaned = re.sub(r'\s+', '_', cleaned.strip())
    return cleaned[:60]

def clean_category(cat):
    if not cat:
        return "미분류"
    cat = html.unescape(cat).replace('\xa0', ' ').strip()
    cat = re.sub(r'[\\/*?:"<>|]', '', cat).strip()
    return cat or "미분류"

def parse_date_for_filename(date_str):
    m = re.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})', date_str)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m2 = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
    if m2:
        return f"{int(m2.group(1)):04d}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    return datetime.date.today().strftime("%Y-%m-%d")

def scan_existing_files():
    existing = {}
    for root, dirs, files in os.walk(REPO_DIR):
        if ".git" in root or ".github" in root or "images" in root:
            continue
        for file in files:
            if file.endswith(".md") and file != "README.md":
                fpath = os.path.join(root, file)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        header = f.read(800)
                        m_log = re.search(r'logNo:\s*"(\d+)"', header)
                        m_cat = re.search(r'category:\s*"([^"]*)"', header)
                        m_title = re.search(r'title:\s*"([^"]*)"', header)
                        if m_log:
                            log_no = m_log.group(1)
                            cat = m_cat.group(1) if m_cat else os.path.basename(root)
                            title = m_title.group(1) if m_title else file[:-3]
                            existing[log_no] = {
                                'path': fpath,
                                'category': clean_category(cat),
                                'title': title
                            }
                except Exception:
                    pass
    return existing

def fetch_rss_feed():
    posts = []
    try:
        req = urllib.request.Request(RSS_URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        for item in root.findall('.//item'):
            link = item.findtext('link') or ""
            guid = item.findtext('guid') or link
            m = re.search(r'/(\d+)', guid)
            if not m:
                continue
            log_no = m.group(1)
            title = html.unescape(item.findtext('title') or "Untitled").strip()
            cat = clean_category(item.findtext('category') or "미분류")
            pub_date = item.findtext('pubDate') or ""
            posts.append({
                'logNo': log_no,
                'title': title,
                'category': cat,
                'pubDate': pub_date,
                'url': f"https://blog.naver.com/{BLOG_ID}/{log_no}"
            })
        print(f"Fetched {len(posts)} posts from RSS feed.")
    except Exception as e:
        print(f"RSS fetch error: {e}")
    return posts

def crawl_and_render_post(log_no, p_meta):
    url = f"https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={log_no}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            page_html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"[{log_no}] Failed to fetch post HTML: {e}")
        return None

    soup = BeautifulSoup(page_html, 'html.parser')

    title_elem = soup.select_one('.se-title-text') or soup.select_one('.pcol1')
    raw_title = title_elem.get_text(strip=True) if title_elem else p_meta.get('title', '')
    clean_title = html.unescape(raw_title).strip()

    cat_elem = soup.select_one('.blog2_series a') or soup.select_one('.category_title') or soup.select_one('.link_category')
    raw_cat = cat_elem.get_text(strip=True) if cat_elem else ""
    cat_name = clean_category(raw_cat or p_meta.get('category', '미분류'))

    date_elem = soup.select_one('.se_publishDate') or soup.select_one('.blog_date') or soup.select_one('.se-pubDate')
    pub_date = date_elem.get_text(strip=True) if date_elem else p_meta.get('pubDate', '')

    tags = []
    m = re.search(r'tagNames\s*:\s*\'([^\']+)\'', page_html)
    if m and m.group(1):
        tags = [t.strip() for t in m.group(1).split(',') if t.strip()]
    tags = [t for t in tags if t not in ['취소', '확인', '네이버블로그', '책산밤 블로그']]

    container = soup.select_one('.se-main-container') or soup.select_one('#postViewArea')
    if not container:
        return None

    components = container.select('.se-component')
    md_body = []
    img_idx = 1

    for comp in components:
        classes = comp.get('class', [])

        if 'se-sectionTitle' in classes or 'se-title' in classes:
            t_text = html.unescape(comp.get_text(strip=True).replace('\u200b', ''))
            if t_text:
                md_body.append(f"\n## {t_text}\n")
            continue

        if 'se-quotation' in classes:
            q_text = html.unescape(comp.get_text('\n', strip=True).replace('\u200b', ''))
            if q_text:
                quoted = "\n".join(f"> {line}" for line in q_text.split('\n'))
                md_body.append(f"\n{quoted}\n")
            continue

        if 'se-image' in classes or comp.select_one('.se-image-resource'):
            img_tag = comp.select_one('img')
            if img_tag:
                src = img_tag.get('data-lazy-src') or img_tag.get('src')
                if src and not src.endswith('.gif') and 'data:image' not in src:
                    orig_url = src.split('?')[0]
                    high_res_url = f"{orig_url}?type=w966"

                    caption_elem = comp.select_one('.se-caption')
                    caption = html.unescape(caption_elem.get_text(strip=True).replace('\u200b', '')) if caption_elem else ""

                    ext = "png"
                    if ".jpg" in orig_url.lower() or ".jpeg" in orig_url.lower():
                        ext = "jpg"
                    img_filename = f"{log_no}_{img_idx}.{ext}"
                    img_path = os.path.join(IMAGES_DIR, img_filename)

                    if not os.path.exists(img_path):
                        try:
                            req_img = urllib.request.Request(high_res_url, headers=HEADERS)
                            with urllib.request.urlopen(req_img, timeout=10) as resp_img:
                                with open(img_path, 'wb') as f_img:
                                    f_img.write(resp_img.read())
                        except Exception:
                            try:
                                req_img = urllib.request.Request(orig_url, headers=HEADERS)
                                with urllib.request.urlopen(req_img, timeout=10) as resp_img:
                                    with open(img_path, 'wb') as f_img:
                                        f_img.write(resp_img.read())
                            except Exception as e:
                                print(f"[{log_no}] Failed img: {e}")

                    rel_path = f"../images/{img_filename}"
                    alt_text = caption or f"이미지 {img_idx}"
                    if caption:
                        md_body.append(f"\n![{alt_text}]({rel_path})\n*{caption}*\n")
                    else:
                        md_body.append(f"\n![{alt_text}]({rel_path})\n")
                    img_idx += 1
            continue

        if 'se-oglink' in classes:
            link_a = comp.select_one('a')
            if link_a and link_a.get('href'):
                href = link_a['href']
                t_elem = comp.select_one('.se-oglink-title') or comp.select_one('.se-oglink-summary')
                link_t = html.unescape(t_elem.get_text(strip=True)) if t_elem else href
                md_body.append(f"\n> 🔗 **[{link_t}]({href})**\n")
            continue

        if 'se-table' in classes:
            rows = comp.select('tr')
            for r_idx, row in enumerate(rows):
                cols = [html.unescape(c.get_text(strip=True).replace('\u200b', '')) for c in row.select('th, td')]
                md_body.append("| " + " | ".join(cols) + " |")
                if r_idx == 0:
                    md_body.append("| " + " | ".join(["---"] * len(cols)) + " |")
            md_body.append("")
            continue

        if 'se-text' in classes:
            p_tags = comp.select('.se-text-paragraph') or comp.select('p')
            for p in p_tags:
                raw_p_text = p.get_text()
                if not raw_p_text or raw_p_text.replace('\u200b', '').strip() == '':
                    md_body.append("")
                    continue

                html_str = str(p)
                p_text = html.unescape(raw_p_text.replace('\u200b', '').strip())

                is_large = any(fs in html_str for fs in ['se-fs-fs24', 'se-fs-fs28', 'se-fs-fs30', 'se-fs-fs32', 'font-size: 24', 'font-size: 28'])
                is_mid = any(fs in html_str for fs in ['se-fs-fs19', 'se-fs-fs20', 'se-fs-fs22', 'font-size: 19', 'font-size: 20'])

                spans = p.select('span')
                formatted = []
                for s in spans:
                    if not s.select('span'):
                        s_text = html.unescape(s.get_text().replace('\u200b', ''))
                        if not s_text:
                            continue
                        s_classes = s.get('class', [])
                        s_style = s.get('style', '')
                        is_bold = ('se-weight-bold' in s_classes or 'font-weight:bold' in s_style.replace(' ', '') or 'font-weight:700' in s_style.replace(' ', ''))
                        formatted.append(f"**{s_text}**" if is_bold else s_text)

                line_res = "".join(formatted).strip() if formatted else p_text

                if is_large:
                    clean_h = re.sub(r'^\*+|\*+$', '', line_res).strip()
                    md_body.append(f"\n## {clean_h}\n")
                elif is_mid:
                    clean_h = re.sub(r'^\*+|\*+$', '', line_res).strip()
                    md_body.append(f"\n### {clean_h}\n")
                else:
                    md_body.append(line_res + "  ")

    final_content = "\n".join(md_body)
    safe_title = clean_title.replace('"', '\\"')

    full_md = f"""---
title: "{safe_title}"
date: "{pub_date}"
category: "{cat_name}"
logNo: "{log_no}"
original_url: "https://blog.naver.com/{BLOG_ID}/{log_no}"
tags: {json.dumps(tags, ensure_ascii=False)}
---

# {clean_title}

{final_content}

---
*원문 출처: [https://blog.naver.com/{BLOG_ID}/{log_no}](https://blog.naver.com/{BLOG_ID}/{log_no})*
"""
    return {
        'logNo': log_no,
        'title': clean_title,
        'category': cat_name,
        'date': pub_date,
        'md_content': full_md
    }

def rebuild_readme():
    posts_data = []
    for root, dirs, files in os.walk(REPO_DIR):
        if ".git" in root or ".github" in root or "images" in root:
            continue
        for file in files:
            if file.endswith(".md") and file != "README.md":
                fpath = os.path.join(root, file)
                rel_path = os.path.relpath(fpath, REPO_DIR).replace("\\", "/")
                category = os.path.basename(root)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        text = f.read(1000)
                        title_m = re.search(r'title:\s*"([^"]+)"', text)
                        date_m = re.search(r'date:\s*"([^"]+)"', text)
                        url_m = re.search(r'original_url:\s*"([^"]+)"', text)
                        title = title_m.group(1) if title_m else file[:-3]
                        date = date_m.group(1) if date_m else ""
                        url = url_m.group(1) if url_m else ""
                        posts_data.append({
                            'category': category,
                            'title': title,
                            'date': date,
                            'rel_path': rel_path,
                            'url': url
                        })
                except Exception:
                    pass

    readme = f"""# 📚 책산밤 아카이브 (Chaeksanbam Archive)

> **"공상 해소"**  
> 네이버 블로그 [책산밤(flionte)](https://blog.naver.com/flionte)의 모든 글을 영구 보존하는 독립 마크다운 아카이브입니다.  
> **GitHub Actions**를 통해 네이버 블로그에 새 글이 작성되거나 카테고리가 변경되면 자동으로 동기화됩니다.

---

## 📊 아카이브 현황
- **총 게시글 수**: {len(posts_data)}편
- **네이버 블로그**: https://blog.naver.com/flionte
- **마지막 동기화**: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} (UTC)

---

## 📑 카테고리별 목차

"""
    categories_order = ["투자 이야기", "읽은 것들", "버핏 주주 서한", "투자 공부", "일상 이야기"]
    all_cats = list(dict.fromkeys(categories_order + [p['category'] for p in posts_data]))

    for cat in all_cats:
        cat_posts = [p for p in posts_data if p['category'] == cat]
        if not cat_posts:
            continue
        readme += f"### 📁 {cat} ({len(cat_posts)}편)\n\n"
        readme += "| 작성일 | 제목 | 원문 링크 |\n"
        readme += "| :--- | :--- | :--- |\n"
        for cp in cat_posts:
            encoded_path = urllib.parse.quote(cp['rel_path'])
            readme += f"| {cp['date']} | [{cp['title']}]({encoded_path}) | [네이버]({cp['url']}) |\n"
        readme += "\n"

    with open(os.path.join(REPO_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)
    print("README.md updated.")

def main():
    print("Starting lightweight blog sync...")
    try:
        existing = scan_existing_files()
        print(f"Existing archived posts: {len(existing)}")

        online_posts = fetch_rss_feed()
        if not online_posts:
            print("RSS feed empty or unavailable.")
            return

        updated = False

        for p in online_posts:
            log_no = p['logNo']

            if log_no not in existing:
                print(f"New post found: {log_no} - {p['title']}")
                res = crawl_and_render_post(log_no, p)
                if res:
                    cat_dir = os.path.join(REPO_DIR, res['category'])
                    os.makedirs(cat_dir, exist_ok=True)
                    date_prefix = parse_date_for_filename(res['date'])
                    fname = f"{date_prefix}_{clean_filename(res['title'])}.md"
                    fpath = os.path.join(cat_dir, fname)
                    with open(fpath, "w", encoding="utf-8") as wf:
                        wf.write(res['md_content'])
                    print(f"Saved new post: {fpath}")
                    existing[log_no] = {'path': fpath, 'category': res['category'], 'title': res['title']}
                    updated = True
            else:
                old_info = existing[log_no]
                if p['category'] and p['category'] != old_info['category']:
                    old_path = old_info['path']
                    new_category = p['category']
                    print(f"Category changed for {log_no} ({p['title']}): {old_info['category']} -> {new_category}")
                    new_cat_dir = os.path.join(REPO_DIR, new_category)
                    os.makedirs(new_cat_dir, exist_ok=True)
                    new_path = os.path.join(new_cat_dir, os.path.basename(old_path))
                    os.rename(old_path, new_path)
                    with open(new_path, "r", encoding="utf-8") as rf:
                        old_text = rf.read()
                    new_text = re.sub(r'category:\s*"[^"]*"', f'category: "{new_category}"', old_text)
                    with open(new_path, "w", encoding="utf-8") as wf:
                        wf.write(new_text)
                    existing[log_no] = {'path': new_path, 'category': new_category, 'title': old_info['title']}
                    updated = True

        if updated:
            rebuild_readme()
            print("Sync completed: updates found and applied.")
        else:
            print("Sync completed: all posts up to date. No network overhead.")

    except Exception as e:
        print(f"Unexpected sync error: {e}")
        traceback.print_exc()
        sys.exit(0)

if __name__ == "__main__":
    main()
