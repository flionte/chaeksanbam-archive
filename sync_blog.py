import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import os
import re
import datetime
import html
import sys
import time
import argparse
import traceback
from bs4 import BeautifulSoup

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BLOG_ID = "flionte"
RSS_URL = f"https://rss.blog.naver.com/{BLOG_ID}.xml"
REPO_DIR = "."
IMAGES_DIR = os.path.join(REPO_DIR, "images")
STATE_FILE = os.path.join(REPO_DIR, "audit_state.json")
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
                        header = f.read(1000)
                        m_log = re.search(r'logNo:\s*"(\d+)"', header)
                        m_cat = re.search(r'category:\s*"([^"]*)"', header)
                        m_title = re.search(r'title:\s*"([^"]*)"', header)
                        m_date = re.search(r'date:\s*"([^"]*)"', header)
                        if m_log:
                            log_no = m_log.group(1)
                            cat = m_cat.group(1) if m_cat else os.path.basename(root)
                            title = m_title.group(1) if m_title else file[:-3]
                            pub_date = m_date.group(1) if m_date else ""
                            existing[log_no] = {
                                'path': fpath,
                                'category': clean_category(cat),
                                'title': title,
                                'date': pub_date
                            }
                except Exception:
                    pass
    return existing

def load_audit_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_audit_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save audit state: {e}")

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
        print(f"RSS fetch warning: {e}")
    return posts

def crawl_and_render_post(log_no, p_meta):
    url = f"https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={log_no}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            page_html = resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            print(f"[{log_no}] HTTP {e.code}: 게시글이 삭제되었거나 존재하지 않습니다.")
            return {'status': 'deleted_or_private', 'logNo': log_no}
        print(f"[{log_no}] HTTP {e.code}: {e}")
        return {'status': 'error', 'logNo': log_no}
    except Exception as e:
        print(f"[{log_no}] Failed to fetch post HTML: {e}")
        return {'status': 'error', 'logNo': log_no}

    soup = BeautifulSoup(page_html, 'html.parser')

    # Detect deleted or private posts
    container = soup.select_one('.se-main-container') or soup.select_one('#postViewArea')
    if not container or "삭제되었거나" in page_html or "비공개" in page_html or "존재하지 않는 게시글" in page_html:
        return {'status': 'deleted_or_private', 'logNo': log_no}

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
        'status': 'ok',
        'logNo': log_no,
        'title': clean_title,
        'category': cat_name,
        'date': pub_date,
        'md_content': full_md
    }

def save_or_update_post(res, existing_info=None):
    clean_cat = clean_category(res['category'])
    cat_dir = os.path.join(REPO_DIR, clean_cat)
    os.makedirs(cat_dir, exist_ok=True)
    date_prefix = parse_date_for_filename(res['date'])
    fname = f"{date_prefix}_{clean_filename(res['title'])}.md"
    new_fpath = os.path.join(cat_dir, fname)

    if existing_info and os.path.exists(existing_info['path']):
        old_path = existing_info['path']
        if os.path.normpath(old_path) != os.path.normpath(new_fpath):
            try:
                os.remove(old_path)
            except Exception:
                pass

    with open(new_fpath, "w", encoding="utf-8") as wf:
        wf.write(res['md_content'])

    return new_fpath

def audit_single_post(log_no, existing_info, audit_state, p_meta=None):
    now_iso = datetime.datetime.now().isoformat()
    meta = p_meta or existing_info
    res = crawl_and_render_post(log_no, meta)

    if not res or res.get('status') == 'error':
        print(f"[{log_no}] 점검 일시 오류(네트워크) - 다음 주기에 재점검합니다.")
        return False

    if res.get('status') == 'deleted_or_private':
        print(f"[{log_no}] 네이버에서 삭제/비공개 감지됨: 기존 아카이브 파일 영구 보존")
        audit_state[log_no] = {
            'last_checked': now_iso,
            'status': 'naver_deleted_or_private'
        }
        return False

    if res.get('status') == 'ok':
        fpath = existing_info['path']
        content_changed = False

        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as rf:
                old_text = rf.read().replace('\r\n', '\n').strip()
            new_text = res['md_content'].replace('\r\n', '\n').strip()
            if old_text != new_text:
                content_changed = True
        else:
            content_changed = True

        audit_state[log_no] = {
            'last_checked': now_iso,
            'status': 'active'
        }

        if content_changed:
            new_path = save_or_update_post(res, existing_info)
            existing_info['path'] = new_path
            existing_info['category'] = res['category']
            existing_info['title'] = res['title']
            print(f"[{log_no}] [퇴고 반영 완료] {res['title']}")
            return True
        else:
            print(f"[{log_no}] [내용 일치/퇴고 없음] {existing_info['title']}")
            return False

    return False

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
> **GitHub Actions**를 통해 매일 자정 최신 글 퇴고 점검 및 매주 정오 과거 글 순환 롤링 점검이 자동으로 수행됩니다.

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
    parser = argparse.ArgumentParser(description="Naver Blog Sync & Dual Rolling Audit")
    parser.add_argument("--mode", choices=["daily", "weekly"], default="daily", help="Sync mode: daily or weekly")
    args = parser.parse_args()

    mode = args.mode
    print(f"=== Blog Sync & Audit Started [Mode: {mode.upper()}] ===")

    try:
        existing = scan_existing_files()
        print(f"Archived posts on disk: {len(existing)}")

        audit_state = load_audit_state()

        # Seed initial state for any posts not yet recorded in audit state
        for log_no in existing:
            if log_no not in audit_state:
                audit_state[log_no] = {
                    'last_checked': '2026-09-09T00:00:00',
                    'status': 'active'
                }

        updated = False

        if mode == "daily":
            # 1. Fetch RSS (fast, reliable, 1 request)
            online_posts = fetch_rss_feed()

            # 2. Check for newly published posts
            for p in online_posts:
                log_no = p['logNo']
                if log_no not in existing:
                    print(f"[새 글 발견] {log_no} - {p['title']}")
                    res = crawl_and_render_post(log_no, p)
                    if res and res.get('status') == 'ok':
                        new_path = save_or_update_post(res)
                        existing[log_no] = {'path': new_path, 'category': res['category'], 'title': res['title'], 'date': res['date']}
                        audit_state[log_no] = {
                            'last_checked': datetime.datetime.now().isoformat(),
                            'status': 'active'
                        }
                        updated = True
                else:
                    # Quick category change check via RSS
                    old_info = existing[log_no]
                    if p['category'] and p['category'] != old_info['category']:
                        old_path = old_info['path']
                        new_cat = p['category']
                        print(f"카테고리 이동 감지 ({log_no}): {old_info['category']} -> {new_cat}")
                        new_cat_dir = os.path.join(REPO_DIR, new_cat)
                        os.makedirs(new_cat_dir, exist_ok=True)
                        new_path = os.path.join(new_cat_dir, os.path.basename(old_path))
                        os.rename(old_path, new_path)
                        with open(new_path, "r", encoding="utf-8") as rf:
                            old_text = rf.read()
                        new_text = re.sub(r'category:\s*"[^"]*"', f'category: "{new_cat}"', old_text)
                        with open(new_path, "w", encoding="utf-8") as wf:
                            wf.write(new_text)
                        existing[log_no]['path'] = new_path
                        existing[log_no]['category'] = new_cat
                        updated = True

            # 3. Daily Audit: Check top 5 latest posts for any post revisions (퇴고)
            target_candidates = online_posts[:5] if online_posts else []
            if not target_candidates:
                # Fallback to 5 newest on disk by date if RSS is unavailable
                sorted_by_date = sorted(existing.keys(), key=lambda x: existing[x].get('date', ''), reverse=True)
                target_candidates = [{'logNo': k} for k in sorted_by_date[:5]]

            print(f"\n[Daily Audit] 최근 글 5개 퇴고 여부 점검 진행:")
            for p in target_candidates:
                log_no = p['logNo']
                if log_no in existing:
                    time.sleep(1.0)
                    changed = audit_single_post(log_no, existing[log_no], audit_state, p)
                    if changed:
                        updated = True

        elif mode == "weekly":
            # Weekly Audit: Pick 5 least-recently-checked posts (LRU rotation)
            def get_check_time(log_no):
                entry = audit_state.get(log_no, {})
                if isinstance(entry, dict):
                    return entry.get('last_checked', '1970-01-01T00:00:00')
                elif isinstance(entry, str):
                    return entry
                return '1970-01-01T00:00:00'

            candidates = list(existing.keys())
            candidates.sort(key=get_check_time)
            target_5 = candidates[:5]

            print(f"\n[Weekly Audit] 가장 오랫동안 미점검된 과거 글 5개 순환 점검 진행:")
            for log_no in target_5:
                last_time = get_check_time(log_no)
                print(f"점검 대상: {log_no} (마지막 점검: {last_time}) - {existing[log_no]['title']}")
                time.sleep(1.0)
                changed = audit_single_post(log_no, existing[log_no], audit_state)
                if changed:
                    updated = True

        # Clean up audit_state for any files no longer on disk
        audit_state = {k: v for k, v in audit_state.items() if k in existing}
        save_audit_state(audit_state)

        if updated:
            rebuild_readme()
            print("Sync completed: Changes applied and saved.")
        else:
            print("Sync completed: All inspected posts up to date. No content changes.")

    except Exception as e:
        print(f"Unexpected sync error: {e}")
        traceback.print_exc()
        sys.exit(0)

if __name__ == "__main__":
    main()
