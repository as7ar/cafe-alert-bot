import asyncio
import aiohttp
import os
from dotenv import load_dotenv
from supabase import create_client
import discord
from discord import app_commands

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

running = False


@tree.command(name="카페알림", description="카페 알림 설정")
@app_commands.describe(
    channel="알림 받을 채널",
    cafe_id="네이버 카페 ID"
)
async def cafe_alert(interaction: discord.Interaction, channel: discord.TextChannel, cafe_id: int):
    guild_id = str(interaction.guild_id)

    prev = supabase.table("cafe_config") \
        .select("cafe_id") \
        .eq("guild_id", guild_id) \
        .execute()

    prev_cafe_id = prev.data[0]["cafe_id"] if prev.data else None

    supabase.table("cafe_config").upsert({
        "guild_id": guild_id,
        "channel_id": str(channel.id),
        "cafe_id": cafe_id
    }).execute()

    if prev_cafe_id != cafe_id:
        supabase.table("cafe_state").upsert({
            "id": guild_id,
            "last_article_id": 0
        }).execute()

    await interaction.response.send_message(
        f"설정됨: {channel.mention} / 카페ID: {cafe_id}",
        ephemeral=True
    )


async def fetch_articles(cafe_id: int):
    url = f"https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/{cafe_id}/menus/0/articles?page=1&pageSize=15&sortBy=TIME&viewType=L"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://cafe.naver.com/"
        }) as res:
            return await res.json()


async def main_task():
    global running
    if running:
        return
    running = True

    try:
        configs = supabase.table("cafe_config").select("*").execute().data
        if not configs:
            return

        state_res = supabase.table("cafe_state").select("*").execute()
        state_map = {str(s["id"]): s["last_article_id"] for s in state_res.data}

        for config in configs:
            guild_id = config["guild_id"]
            cafe_id = config["cafe_id"]

            json_data = await fetch_articles(cafe_id)
            articles = json_data["result"]["articleList"]

            if not articles:
                continue

            last_id = state_map.get(guild_id, 0)

            if last_id == 0:
                supabase.table("cafe_state").upsert({
                    "id": guild_id,
                    "last_article_id": articles[0]["item"]["articleId"]
                }).execute()
                continue

            new_articles = [
                a["item"] for a in articles
                if a["item"]["articleId"] > last_id
            ]

            new_articles.sort(key=lambda x: x["articleId"])

            if not new_articles:
                continue

            channel = client.get_channel(int(config["channel_id"]))
            if not channel:
                try:
                    channel = await client.fetch_channel(int(config["channel_id"]))
                except:
                    continue

            for a in new_articles:
                url = f"https://cafe.naver.com/f-e/cafes/{a['cafeId']}/articles/{a['articleId']}"

                try:
                    embed = discord.Embed(
                        title=f"📌 {a['menuName']}",
                        description=f"**{a['subject']}**\n[바로가기]({url})",
                        color=0x9FCB98
                    )

                    if a.get("representImage"):
                        embed.set_image(url=a["representImage"])

                    embed.set_footer(text="네이버 카페")

                    await channel.send(embed=embed)
                except Exception as e:
                    print("디코 전송 실패", e)

            latest_id = articles[0]["item"]["articleId"]

            supabase.table("cafe_state").upsert({
                "id": guild_id,
                "last_article_id": latest_id
            }).execute()

    finally:
        running = False


@client.event
async def on_ready():
    print("봇 준비됨")

    await tree.sync()

    while True:
        try:
            await main_task()
        except Exception as e:
            print(e)

        await asyncio.sleep(10)


client.run(DISCORD_TOKEN)