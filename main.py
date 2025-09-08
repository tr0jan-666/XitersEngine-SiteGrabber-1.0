import discord
from discord.ext import commands, tasks
import os
import aiohttp
import aiofiles
from bs4 import BeautifulSoup
import shutil
import zipfile
import datetime
import asyncio
import ssl
import certifi
from urllib.parse import urljoin, urlparse

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?", intents=intents)

notes = [
    "Extracting Sites | ?Zamel",
    "Stealing Sites | ?Zamel",
    "Made by Tr0jan | ?Zamel",
    "github.com/tr0jan-666/XitersEngine-SiteGrabber-1.0"
]
note_index = 0

@tasks.loop(seconds=3)
async def change_status():
    global note_index
    note = notes[note_index]
    activity = discord.Streaming(
        name=f"{note} ",
        url="https://twitch.tv/cleanx"
    )
    await bot.change_presence(activity=activity)
    note_index = (note_index + 1) % len(notes)

async def download_file(session, file_url, save_path):
    try:
        async with session.get(file_url) as resp:
            if resp.status == 200:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                async with aiofiles.open(save_path, 'wb') as f:
                    await f.write(await resp.read())
    except:
        pass

async def fetch_site(url, folder):
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url) as response:
            text = await response.text()
            soup = BeautifulSoup(text, "html.parser")
            index_path = os.path.join(folder, "index.html")
            os.makedirs(folder, exist_ok=True)
            async with aiofiles.open(index_path, "w", encoding="utf-8") as f:
                await f.write(str(soup))

            resources = []
            for tag, attr in [("img", "src"), ("script", "src"), ("link", "href"), ("source", "src"), ("video", "src"), ("audio", "src")]:
                for t in soup.find_all(tag):
                    link = t.get(attr)
                    if not link:
                        continue
                    abs_link = urljoin(url, link)
                    parsed = urlparse(abs_link)
                    path = os.path.join(folder, parsed.netloc, parsed.path.lstrip("/"))
                    resources.append((abs_link, path))

            tasks = [download_file(session, r[0], r[1]) for r in resources]
            if tasks:
                await asyncio.gather(*tasks)

@bot.command()
async def Zamel(ctx, url: str):
    folder = f"site_{ctx.message.id}"
    os.makedirs(folder, exist_ok=True)
    await fetch_site(url, folder)
    zip_name = f"Site_t7wa_by_CleanX_{ctx.message.id}.zip"
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder):
            for file in files:
                path = os.path.join(root, file)
                zipf.write(path, os.path.relpath(path, folder))
    stats = sum([len(files) for r, d, files in os.walk(folder)])
    shutil.rmtree(folder)
    embed = discord.Embed(
        title="📂 Site Extracted",
        description=f"Name: `{zip_name}`\nFiles: `{stats}`\nDate: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        color=0x00ffcc
    )
    file = discord.File(zip_name)
    await ctx.send(embed=embed, file=file)
    os.remove(zip_name)

@bot.event
async def on_ready():
    change_status.start()

bot.run("Bot token")
