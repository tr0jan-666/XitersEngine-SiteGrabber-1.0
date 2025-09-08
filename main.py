import os
import re
import io
import zipfile
import asyncio
import aiofiles
import aiohttp
from urllib.parse import urlparse, urljoin, urldefrag
from bs4 import BeautifulSoup
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"
GUILD_ID = None
MAX_PAGES = 150
CONCURRENT = 8
TIMEOUT = 20
USER_AGENT = "CleanX-SiteGrabber/1.0"

def safe_path_for_url(base_folder: str, url: str, domain: str):
    parsed = urlparse(url)
    path = parsed.path
    if path.endswith("/") or path == "":
        filename = "index.html"
        dirpath = os.path.join(base_folder, parsed.netloc, parsed.path.lstrip("/"))
    else:
        dirpath = os.path.join(base_folder, parsed.netloc, os.path.dirname(parsed.path.lstrip("/")))
        filename = os.path.basename(parsed.path)
    if not os.path.splitext(filename)[1]:
        filename += ".html"
    os.makedirs(dirpath, exist_ok=True)
    filename = re.sub(r'[^A-Za-z0-9\-\._]', '_', filename)
    return os.path.join(dirpath, filename)

def sanitize_filename(name: str):
    return re.sub(r'[^A-Za-z0-9\-\._]', '_', name)

class SiteGrabber:
    def __init__(self, base_url: str, session: aiohttp.ClientSession, out_folder="sites"):
        self.base_url = base_url.rstrip("/")
        self.parsed_base = urlparse(self.base_url)
        self.base_domain = self.parsed_base.netloc
        self.session = session
        self.out_folder = out_folder
        self.seen_pages = set()
        self.seen_assets = set()
        self.to_visit = asyncio.Queue()
        self.to_visit.put_nowait(self.base_url)
        self.sem = asyncio.Semaphore(CONCURRENT)
        self.files_saved = []
        self.start_time = datetime.utcnow()

    def same_domain(self, url: str):
        p = urlparse(url)
        return (p.netloc == "" or p.netloc == self.base_domain)

    async def fetch(self, url: str):
        try:
            async with self.sem:
                async with self.session.get(url, timeout=TIMEOUT, allow_redirects=True) as resp:
                    if resp.status == 200:
                        content_type = resp.headers.get("Content-Type", "")
                        data = await resp.read()
                        return data, content_type
                    else:
                        return None, None
        except Exception:
            return None, None

    def absolutify(self, link: str, page_url: str):
        if not link:
            return None
        link, _ = urldefrag(link)
        return urljoin(page_url, link)

    async def save_file(self, fullpath: str, data: bytes):
        os.makedirs(os.path.dirname(fullpath), exist_ok=True)
        async with aiofiles.open(fullpath, "wb") as f:
            await f.write(data)
        self.files_saved.append(fullpath)

    async def handle_asset(self, asset_url: str, page_url: str):
        asset_url = self.absolutify(asset_url, page_url)
        if not asset_url:
            return
        if asset_url in self.seen_assets:
            return
        p = urlparse(asset_url)
        if p.netloc and p.netloc != self.base_domain:
            return
        self.seen_assets.add(asset_url)
        data, ctype = await self.fetch(asset_url)
        if data:
            rel_path = p.path.lstrip("/")
            if rel_path == "":
                rel_path = "resource"
            safe = os.path.join(self.out_folder, self.base_domain, rel_path)
            safe = sanitize_filename(safe)
            os.makedirs(os.path.dirname(safe), exist_ok=True)
            await self.save_file(safe, data)

    async def parse_and_queue(self, html_bytes: bytes, page_url: str):
        try:
            soup = BeautifulSoup(html_bytes, "html.parser")
        except Exception:
            return
        tags = []
        tags += [("img", "src"), ("script", "src"), ("link", "href"), ("source", "src"), ("video", "poster"), ("audio", "src")]
        tasks = []
        for tag, attr in tags:
            for t in soup.find_all(tag):
                link = t.get(attr)
                if not link:
                    continue
                link_abs = self.absolutify(link, page_url)
                if not link_abs:
                    continue
                parsed = urlparse(link_abs)
                if parsed.netloc == "" or parsed.netloc == self.base_domain:
                    tasks.append(self.handle_asset(link, page_url))
        for a in soup.find_all("a", href=True):
            href = a["href"]
            abs_href = self.absolutify(href, page_url)
            if not abs_href:
                continue
            parsed = urlparse(abs_href)
            if parsed.scheme not in ("http", "https"):
                continue
            if parsed.netloc == self.base_domain:
                abs_href, _ = urldefrag(abs_href)
                if abs_href not in self.seen_pages and self.to_visit.qsize() + len(self.seen_pages) < MAX_PAGES:
                    await self.to_visit.put(abs_href)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def save_page(self, page_url: str, content: bytes):
        fullpath = safe_path_for_url(self.out_folder, page_url, self.base_domain)
        await self.save_file(fullpath, content)

    async def run(self):
        workers = []
        for _ in range(CONCURRENT):
            workers.append(asyncio.create_task(self.worker()))
        await asyncio.gather(*workers)
        elapsed = (datetime.utcnow() - self.start_time).total_seconds()
        return {
            "files": self.files_saved,
            "elapsed": elapsed,
            "pages_count": len(self.seen_pages),
            "assets_count": len(self.seen_assets),
        }

    async def worker(self):
        while True:
            try:
                page = await asyncio.wait_for(self.to_visit.get(), timeout=1.0)
            except asyncio.TimeoutError:
                return
            if page in self.seen_pages:
                continue
            if len(self.seen_pages) >= MAX_PAGES:
                continue
            self.seen_pages.add(page)
            data, ctype = await self.fetch(page)
            if not data:
                continue
            await self.save_page(page, data)
            if ctype and "text/html" in ctype:
                await self.parse_and_queue(data, page)

async def upload_to_mediafire(zip_path):
    async with aiohttp.ClientSession() as s:
        async with s.get("https://www.mediafire.com/") as r:
            text = await r.text()
        m = re.search(r'"uploadUrl":"(.*?)"', text)
        if not m:
            return None
        upload_url = m.group(1).replace("\\/", "/")
        data = aiohttp.FormData()
        data.add_field("Filedata", open(zip_path, "rb"), filename=os.path.basename(zip_path))
        async with s.post(upload_url, data=data) as r:
            uptext = await r.text()
        m2 = re.search(r'"quickkey":"(.*?)"', uptext)
        if not m2:
            return None
        quickkey = m2.group(1)
        return f"https://www.mediafire.com/file/{quickkey}"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
    except Exception as e:
        print("Sync failed:", e)

@bot.tree.command(name="7wy", description="Download a website project and zip it.")
@app_commands.describe(url="Website URL")
async def grab(interaction: discord.Interaction, url: str):
    await interaction.response.defer(thinking=True)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        await interaction.followup.send("Invalid URL")
        return
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        grabber = SiteGrabber(url, session)
        result = await grabber.run()
    base_folder = os.path.join("sites", grabber.base_domain)
    zipname = f"Site t7wa by CleanX - {sanitize_filename(grabber.base_domain)}.zip"
    zip_path = os.path.join("sites", zipname)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(base_folder):
            for f in files:
                full = os.path.join(root, f)
                arcname = os.path.relpath(full, os.path.join("sites"))
                zf.write(full, arcname)
    total_size = os.path.getsize(zip_path)
    file_count = len(result["files"])
    elapsed = result["elapsed"]
    pages = result["pages_count"]
    assets = result["assets_count"]
    embed = discord.Embed(title="Site Grab Complete", color=0x00ff99)
    embed.add_field(name="Domain", value=grabber.base_domain, inline=True)
    embed.add_field(name="Pages", value=str(pages), inline=True)
    embed.add_field(name="Assets", value=str(assets), inline=True)
    embed.add_field(name="Files", value=str(file_count), inline=True)
    embed.add_field(name="Zip size", value=f"{total_size/1024/1024:.2f} MB", inline=True)
    embed.add_field(name="Elapsed", value=f"{elapsed:.1f}s", inline=True)
    embed.set_footer(text=f"Site t7wa by CleanX • {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    MAX_UPLOAD = 8 * 1024 * 1024
    if total_size <= MAX_UPLOAD:
        with open(zip_path, "rb") as fh:
            discord_file = discord.File(fh, filename=zipname)
            await interaction.followup.send(embed=embed, file=discord_file)
    else:
        link = await upload_to_mediafire(zip_path)
        if link:
            await interaction.followup.send(embed=embed, content=f"Uploaded to MediaFire: {link}")
        else:
            await interaction.followup.send(embed=embed, content="Zip too big and upload failed.")

if __name__ == "__main__":
    os.makedirs("sites", exist_ok=True)
    bot.run(TOKEN)
