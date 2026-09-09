import urllib.request
import urllib.parse
import json
import os
import re
import datetime
from bs4 import BeautifulSoup

BLOG_ID = "flionte"

def clean_filename(title):
    cleaned = re.sub(r'[\\/*?:"<>|]', '', title)
    cleaned = re.sub(r'\s+', '_', cleaned.strip())
    return cleaned[:60]

def clean_category(cat):
    if not cat:
        return "미분류"
    cat = cat.replace('\xa0', ' ').strip()
    cat = re.sub(r'[\\/*?:"<>|]', '', cat).strip()
    return cat or "미분류"

def parse_date_for_filename(date_str):
    m = re.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})', date_str)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if "전" in date_str:
        return datetime.date.today().strftime("%Y-%m-%d")
    return "undated"

def scan_existing_files():
    # Maps logNo to file_path
    existing = {}
    for root, dirs, files in os.walk("."):
        if ".git" in root or ".github" in root:
            continue
        for file in files:
            if file.endswith(".md") and file != "README.md":
                fpath = os.path.join(root, file)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        header = f.read(500)
                        m = re.search(r'logNo:\s*"(\d+)"', header)
                        if m:
                            existing[m.group(1)] = fpath
                except Exception:
                    pass
    return existing

def fetch_post_list():
    posts = []
    page = 1
    total_count = None
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    while True:
        url = f'https://blog.naver.com/PostTitleListAsync.naver?blogId={BLOG_ID}&viewdate=&currentPage={page}&categoryNo=0&parentCategoryNo=0&countPerPage=30'
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read()
            text = raw.decode('utf-8', errors='replace')
            cleaned_text = re.sub(r"\\'", "'", text)
            data = json.loads(cleaned_text, strict=False)
            if total_count is None:
                total_count = int(data.get('totalCount', 0))
            cur_posts = data.get('postList', [])
            if not cur_posts:
                break
            for p in cur_posts:
                posts.append({
                    'logNo': p.get('logNo'),
                    'title': urllib.parse.unquote_plus(p.get('title', '')),
                    'logdate': p.get('logdate', ''),
                    'url': f"https://blog.naver.com/{BLOG_ID}/{p.get('logNo')}"
                })
            if len(posts) >= total_count:
                break
            page += 1
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break
    return posts

def crawl_post_content(log_no):
    url = f"https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={log_no}"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': f'https://blog.naver.com/{BLOG_ID}'
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        soup = BeautifulSoup(html, 'html.parser')
        
        cat_elem = soup.select_one('.blog2_series a') or soup.select_one('.category_title') or soup.select_one('.link_category')
        category = clean_category(cat_elem.get_text(strip=True) if cat_elem else "")
        
        tags = [t.get_text(strip=True) for t in soup.select('.item_tag')]
        if not tags:
            tags = [t.get_text(strip=True) for t in soup.select('.wrap_tag a')]
            
        container = soup.select_one('.se-main-container') or soup.select_one('#postViewArea')
        content_text = ""
        if container:
            content_text = container.get_text('\n', strip=True).replace('\u200b', '')
            
        date_elem = soup.select_one('.se_publishDate') or soup.select_one('.blog_date') or soup.select_one('.se-pubDate')
        publish_date = date_elem.get_text(strip=True) if date_elem else ""
        
        return category, tags, content_text, publish_date
    except Exception as e:
        print(f"Error crawling {log_no}: {e}")
        return None, None, None, None

def rebuild_readme():
    posts_data = []
    for root, dirs, files in os.walk("."):
        if ".git" in root or ".github" in root:
            continue
        for file in files:
            if file.endswith(".md") and file != "README.md":
                fpath = os.path.join(root, file)
                rel_path = os.path.relpath(fpath, ".").replace("\\", "/")
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
        
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme)
    print("README.md updated.")

def main():
    print("Starting blog sync...")
    existing = scan_existing_files()
    print(f"Existing archived posts: {len(existing)}")
    
    online_posts = fetch_post_list()
    print(f"Online posts count: {len(online_posts)}")
    
    updated = False
    for p in online_posts:
        log_no = p['logNo']
        
        # 1. New Post
        if log_no not in existing:
            print(f"Found new post: {log_no} - {p['title']}")
            category, tags, content, pub_date = crawl_post_content(log_no)
            if not content:
                continue
            cat_dir = category
            os.makedirs(cat_dir, exist_ok=True)
            date_prefix = parse_date_for_filename(pub_date or p['logdate'])
            filename = f"{date_prefix}_{clean_filename(p['title'])}.md"
            target_path = os.path.join(cat_dir, filename)
            
            tags_str = json.dumps(tags, ensure_ascii=False)
            md_text = f"""---
title: "{p['title'].replace('"', '\\"')}"
date: "{pub_date or p['logdate']}"
category: "{category}"
logNo: "{log_no}"
original_url: "{p['url']}"
tags: {tags_str}
---

# {p['title']}

{content}

---
*원문 출처: [{p['url']}]({p['url']})*
"""
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(md_text)
            print(f"Saved: {target_path}")
            existing[log_no] = target_path
            updated = True
        else:
            # 2. Check if category changed
            old_path = existing[log_no]
            old_cat = os.path.basename(os.path.dirname(old_path))
            # Quick check from online
            category, tags, content, pub_date = crawl_post_content(log_no)
            if category and category != old_cat:
                print(f"Category changed for {log_no} ({p['title']}): {old_cat} -> {category}")
                new_cat_dir = category
                os.makedirs(new_cat_dir, exist_ok=True)
                new_path = os.path.join(new_cat_dir, os.path.basename(old_path))
                os.rename(old_path, new_path)
                # update category in frontmatter
                with open(new_path, "r", encoding="utf-8") as rf:
                    old_text = rf.read()
                new_text = re.sub(r'category:\s*"[^"]*"', f'category: "{category}"', old_text)
                with open(new_path, "w", encoding="utf-8") as wf:
                    wf.write(new_text)
                existing[log_no] = new_path
                updated = True
                
    if updated:
        rebuild_readme()
        print("Sync complete with changes.")
    else:
        print("Sync complete. Everything up to date.")

if __name__ == "__main__":
    main()
