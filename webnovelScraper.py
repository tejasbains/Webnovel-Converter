import requests
from bs4 import BeautifulSoup
from ebooklib import epub
from deep_translator import GoogleTranslator
from tqdm import tqdm
import time
import random
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# function to get html via requests
# function to get all links
# function to get text from link using beautifulsoup
# function to make epub out of text
# functoin to get cover
# function to translate

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/118.0.5993.118 Safari/537.36"})
BASE_URL = "https://novelfire.net/home"

def getInput():
    print("Scraper built for NovelFire.net")
    mainUrl = input("Enter main page ")
    tocUrl = mainUrl + "/chapter"
    fileName = input("Enter file name ")
    if not fileName.lower().endswith(".epub"):
        fileName += ".epub"
    title = input("Enter title of book ")
    author = input("Enter author of book ")
    toTranslate = input("Translate to english? (0 for no, 1 for yes) ")
    chapters = int(input("Enter desired chapters from start "))
    inputs = (mainUrl, tocUrl, fileName, title, author, toTranslate, chapters)
    return inputs

def safeGet(url, retries = 3):
    delay = 2
    for i in range(retries):
        try:
            message = SESSION.get(url, timeout=10)
            message.raise_for_status()
            return message.text
        except requests.RequestException as e:
            print(f"Error: failed to get {url}: {e} (retry {i+1}/{retries})")
            time.sleep(delay)
    return None

def translate(text, translator=None, chunk_size=4000, on_error=None):
    if not translator:
        return text
    translated_text = ""
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        try:
            translated_text += translator.translate(chunk)
        except Exception as e:
            message = f"Translation failed: {e}"
            if on_error:
                on_error(message)
            else:
                print(message)
            return text
        start = end
    return translated_text

def translate_field(text, translator, timeout=60, on_failure=None):
    """Translate a single field (chapter title or body) with a hard time bound.

    Each field is translated independently and bounded to `timeout` seconds. On
    failure or timeout the ORIGINAL untranslated text is returned so the job can
    continue, and a notice is emitted through `on_failure` (or printed).

    Returns a tuple of (result_text, translated_ok) where `translated_ok` is
    False when the original text was kept because translation failed or timed
    out. This flag is the path that lets a caller surface the failure as
    progress feedback later.
    """
    if not translator:
        return text, False

    notices = []
    # Run the (blocking) translation in a worker thread so we can enforce a
    # per-field time bound. On timeout we stop waiting and fall back to the
    # original text; the lingering worker is not awaited so it cannot block.
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(translate, text, translator, 4000, notices.append)
    try:
        result = future.result(timeout=timeout)
    except FuturesTimeoutError:
        notices.append(f"Translation timed out after {timeout} seconds")
        result = text
    except Exception as e:
        notices.append(f"Translation failed: {e}")
        result = text
    finally:
        executor.shutdown(wait=False)

    translated_ok = not notices
    for message in notices:
        if on_failure:
            on_failure(message)
        else:
            print(message)
    return result, translated_ok

def getInfo(toc, do_translate, translator, chapterCount, progress_callback=None):
    links = []
    titles = []
    chapters = []
    count = 1
    inBounds = True

    def notify(message):
        if progress_callback:
            progress_callback(message)
        else:
            print(message)

    print("getting chapter information...")
    pbar = tqdm(total=chapterCount, desc="Chapters", unit=" chap")
    while inBounds:
        url = f"{toc}-{count}"
        html = safeGet(url)
        if html is None:
            inBounds = False
        else:
            soup = BeautifulSoup(html, "html.parser")
            content = soup.select_one("#content")
            if content is None:
                inBounds = False
            else:
                titleTag = soup.select_one("span.chapter-title")
                if titleTag is not None:
                    textOfTitle = titleTag.get_text(strip=True)
                else:
                    textOfTitle = f"chapter {count}"
                chapterText = content.get_text("\n", strip=True)
                if do_translate:
                    # Translate title and body INDEPENDENTLY: a failure or
                    # timeout on one field must not prevent translating the
                    # other. Each field is bounded to 60 seconds and falls back
                    # to its original text on failure (Req 4.4, 4.5).
                    chapNum = count

                    def titleFailure(message, chapNum=chapNum):
                        notify(f"Chapter {chapNum} title translation failed, "
                               f"using original text: {message}")

                    def bodyFailure(message, chapNum=chapNum):
                        notify(f"Chapter {chapNum} body translation failed, "
                               f"using original text: {message}")

                    textOfTitle, _ = translate_field(
                        textOfTitle, translator, timeout=60, on_failure=titleFailure)
                    chapterText, _ = translate_field(
                        chapterText, translator, timeout=60, on_failure=bodyFailure)
                links.append(url)
                titles.append(textOfTitle)
                chapters.append(chapterText)
        count += 1
        if (count > chapterCount):
            inBounds = False
        pbar.update(1)
        time.sleep(random.uniform(0.1, 0.3))
    pbar.close()
    info = (links, titles, chapters)
    return info

def getCover(url):
    print("Fetching cover image...")
    html = safeGet(url)
    if not html:
        print("Error: Could not fetch main page.")
        return None
    soup = BeautifulSoup(html, "html.parser")
    imgTag = soup.select_one("figure.cover img")
    if not imgTag:
        print("Error: No cover image tag found.")
        return None
    src = imgTag.get("data-src") or imgTag.get("data-original") or imgTag.get("src")
    if not src:
        print("Error: No valid image source found.")
        return None
    print(f"Found cover URL: {src}")
    try:
        imgData = SESSION.get(src, timeout=10).content
        print("Cover image downloaded successfully.")
        return imgData
    except requests.RequestException as e:
        print(f"Error: Failed to download cover: {e}")
        return None

def makeEpub(epubInfo, coverData, title, author, fileName, toTranslate):
    print("Building EPUB...")
    book = epub.EpubBook()
    book.set_title(title)
    if toTranslate:
        book.set_language("en")
    else:
        book.set_language("auto")
    book.add_author(author)
    book.add_metadata('DC', 'description', f'Downloaded from {BASE_URL}')

    if coverData:
        book.set_cover("cover.jpg", coverData)
        print("Cover added to EPUB")

    epubChapters = []
    for i, (chapTitle, text) in enumerate(epubInfo):
        chap = epub.EpubHtml(title=chapTitle, file_name=f"chap_{i}.xhtml")
        html_content = f"<h1>{chapTitle}</h1>\n"
        html_content += "<p>" + text.replace("\n", "<br/>") + "</p>"
        chap.content = html_content
        book.add_item(chap)
        epubChapters.append(chap)

    book.toc = tuple(epubChapters)
    book.spine = ["nav"] + epubChapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(fileName, book)
    print(f"EPUB saved as {fileName}")

def runScraper(mainUrl, fileName, title, author, toTranslate=False, chapterCount=10):
    tocUrl = mainUrl + "/chapter"
    if not fileName.lower().endswith(".epub"):
        fileName += ".epub"
    downloads_path = Path.home() / "Downloads"
    file_path = downloads_path / fileName
    if toTranslate:
        translator = GoogleTranslator(source="auto", target="en")
    else:
        translator = None
    info = getInfo(tocUrl, toTranslate, translator, chapterCount)
    epubInfo = list(zip(info[1], info[2]))
    coverData = getCover(mainUrl)
    makeEpub(epubInfo, coverData, title, author, str(file_path), toTranslate)

    return str(file_path)
if __name__ == "__main__":
    inputs = getInput()
    mainUrl = inputs[0]
    tocUrl = inputs[1]
    fileName = inputs[2]
    title = inputs[3]
    author = inputs[4]
    toTranslate = str(inputs[5]).strip() == "1"
    chapterCount = inputs[6]

    if toTranslate:
        translator = GoogleTranslator(source="auto", target="en")
    else:
        translator = None

    info = getInfo(tocUrl, toTranslate, translator, chapterCount)
    epubInfo = list(zip(info[1], info[2]))

    coverData = getCover(mainUrl)

    makeEpub(epubInfo, coverData, title, author, fileName, toTranslate)