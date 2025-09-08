import discord
from discord.ext import commands, tasks
import os
import aiohttp
import aiofiles
from bs4 import BeautifulSoup
import shutil
import zipfile
import datetime

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?", intents=intents)

notes = ["Extracting Sites | ?Zamel", "Stealing Sites | ?Zamel", "Made by Tr0jan | ?Zamel", "github.com/tr0jan-666/XitersEngine-SiteGrabber-1.0"]
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

async def fetch_site(url, folder):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            text = await response.text()
            soup = BeautifulSoup(text, "html.parser")
            index_path = os.path.join(folder, "index.html")
            async with aiofiles.open(index_path, "w", encoding="utf-8") as f:
                await f.write(str(soup))
            imgs = soup.find_all("img")
            img_folder = os.path.join(folder, "images")
            os.makedirs(img_folder, exist_ok=True)
            count = 0
            for img in imgs:
                src = img.get("src")
                if not src:
                    continue
                if src.startswith("http"):
                    img_url = src
                else:
                    img_url = url + src
                try:
                    async with session.get(img_url) as img_resp:
                        if img_resp.status == 200:
                            ext = os.path.splitext(src)[1]
                            img_path = os.path.join(img_folder, f"img{count}{ext}")
                            async with aiofiles.open(img_path, "wb") as f:
                                await f.write(await img_resp.read())
                            count += 1
                except:
                    pass
    return folder

@bot.command()
async def Zamel(ctx, url: str):
    folder = f"site_{ctx.message.id}"
    os.makedirs(folder, exist_ok=True)
    await fetch_site(url, folder)
    zip_name = f"Site_t7wa_by_CleanX_{ctx.message.id}.zip"
    with zipfile.ZipFile(zip_name, "w") as zipf:
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

bot.run("BOT TOKEN")
