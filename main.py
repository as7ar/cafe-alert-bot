import asyncio
import aiohttp
import os
import json
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


async def fetch_menus(cafe_id: int):
    url = f"https://apis.naver.com/cafe-web/cafe-cafemain-api/v1.0/cafes/{cafe_id}/menus"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://cafe.naver.com/"
        }) as res:
            data = await res.json()
            return data["result"]["menus"]


async def fetch_articles(cafe_id: int, menu_id: int):
    url = f"https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/{cafe_id}/menus/{menu_id}/articles?page=1&pageSize=15&sortBy=TIME&viewType=L"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://cafe.naver.com/"
        }) as res:
            return await res.json()


class MenuView(discord.ui.View):
    def __init__(self, menus, guild_id):
        super().__init__(timeout=60)
        self.guild_id = guild_id

        for m in menus:
            if m.get("menuType") != "B":
                continue

            button = discord.ui.Button(
                label=m["name"],
                style=discord.ButtonStyle.secondary,
                custom_id=str(m["menuId"])
            )
            button.callback = self.toggle_menu
            self.add_item(button)

    async def toggle_menu(self, interaction: discord.Interaction):
        menu_id = int(interaction.data["custom_id"])
        guild_id = str(self.guild_id)

        res = supabase.table("cafe_config").select("selected_menus").eq("guild_id", guild_id).execute()
        selected = res.data[0].get("selected_menus") or []

        if menu_id in selected:
            selected.remove(menu_id)
        else:
            selected.append(menu_id)

        supabase.table("cafe_config").update({
            "selected_menus": selected
        }).eq("guild_id", guild_id).execute()

        await interaction.response.send_message(f"현재 선택된 메뉴: {selected}", ephemeral=True)


@tree.command(name="카페알림", description="카페 알림 설정")
async def cafe_alert(interaction: discord.Interaction, channel: discord.TextChannel, cafe_id: int):
    guild_id = str(interaction.guild_id)

    supabase.table("cafe_config").upsert({
        "guild_id": guild_id,
        "channel_id": str(channel.id),
        "cafe_id": cafe_id,
        "selected_menus": []
    }).execute()

    menus = await fetch_menus(cafe_id)

    await interaction.response.send_message(
        "메뉴 선택:",
        view=MenuView(menus, guild_id),
        ephemeral=True
    )
@tree.command(name="메뉴설정", description="메뉴 선택 변경")
async def menu_setting(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)

    res = supabase.table("cafe_config").select("*").eq("guild_id", guild_id).execute()

    if not res.data:
        await interaction.response.send_message("먼저 `/카페알림`으로 카페를 설정해주세요", ephemeral=True)
        return

    cafe_id = res.data[0]["cafe_id"]

    menus = await fetch_menus(cafe_id)

    await interaction.response.send_message(
        "메뉴 다시 선택:",
        view=MenuView(menus, guild_id),
        ephemeral=True
    )


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
            selected_menus = config.get("selected_menus") or []

            menu_ids = selected_menus if selected_menus else [0]

            last_id = state_map.get(guild_id, 0)
            new_articles_all = []

            for menu_id in menu_ids:
                json_data = await fetch_articles(cafe_id, menu_id)
                articles = json_data["result"]["articleList"]

                for a in articles:
                    item = a["item"]
                    if item["articleId"] > last_id:
                        new_articles_all.append(item)

            if not new_articles_all:
                continue

            new_articles_all.sort(key=lambda x: x["articleId"])

            channel = client.get_channel(int(config["channel_id"]))
            if not channel:
                try:
                    channel = await client.fetch_channel(int(config["channel_id"]))
                except:
                    continue

            for a in new_articles_all:
                url = f"https://cafe.naver.com/f-e/cafes/{a['cafeId']}/articles/{a['articleId']}"

                embed = discord.Embed(
                    title=f"📌 {a['menuName']}",
                    description=f"**{a['subject']}**\n[바로가기]({url})",
                    color=0x9FCB98
                )

                if a.get("representImage"):
                    embed.set_image(url=a["representImage"])

                embed.set_footer(text="네이버 카페")

                await channel.send(embed=embed)

            latest_id = max(a["articleId"] for a in new_articles_all)

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
