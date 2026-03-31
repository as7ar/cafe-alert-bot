import 'dotenv/config'
import {
    Client,
    GatewayIntentBits,
    REST,
    Routes,
    SlashCommandBuilder,
    ChannelType,
    EmbedBuilder,
    TextBasedChannel
} from 'discord.js'
import { createClient } from '@supabase/supabase-js'
import fetch from 'node-fetch'

const client = new Client({
    intents: [GatewayIntentBits.Guilds]
})

const supabase = createClient(
    process.env.SUPABASE_URL!,
    process.env.SUPABASE_KEY!
)

let running = false

const commands = [
    new SlashCommandBuilder()
        .setName('카페알림')
        .setDescription('카페 알림 설정')
        .addChannelOption(opt =>
            opt.setName('채널')
                .setDescription('알림 채널')
                .addChannelTypes(ChannelType.GuildText)
                .setRequired(true)
        )
        .addIntegerOption(opt =>
            opt.setName('cafe_id')
                .setDescription('카페 ID')
                .setRequired(true)
        )
]

const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN!)

async function registerCommands() {
    await rest.put(
        Routes.applicationCommands(process.env.CLIENT_ID!),
        { body: commands }
    )
}

client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return

    if (interaction.commandName === '카페알림') {
        const channel = interaction.options.getChannel('채널')
        const cafeId = interaction.options.getInteger('cafe_id')
        const guildId = interaction.guildId!

        if (!channel || channel.type !== ChannelType.GuildText || !cafeId) {
            await interaction.reply({ content: '잘못된 입력', ephemeral: true })
            return
        }

        const { data: prev } = await supabase
            .from('cafe_config')
            .select('cafe_id')
            .eq('guild_id', guildId)
            .single()

        await supabase.from('cafe_config').upsert({
            guild_id: guildId,
            channel_id: channel.id,
            cafe_id: cafeId
        })

        if (!prev || prev.cafe_id !== cafeId) {
            await supabase.from('cafe_state').upsert({
                id: guildId,
                last_article_id: 0
            })
        }

        await interaction.reply({
            content: `설정됨: <#${channel.id}> / 카페ID: ${cafeId}`,
            ephemeral: true
        })
    }
})

async function fetchArticles(cafeId: number): Promise<any> {
    const url = `https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/${cafeId}/menus/0/articles?page=1&pageSize=15&sortBy=TIME&viewType=L`

    const res = await fetch(url, {
        headers: {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://cafe.naver.com/'
        }
    })

    return res.json()
}

async function mainTask() {
    if (running) return
    running = true

    try {
        const { data: configs } = await supabase.from('cafe_config').select('*')
        if (!configs) return

        const { data: states } = await supabase.from('cafe_state').select('*')
        const stateMap = Object.fromEntries(
            (states ?? []).map(s => [s.id, s.last_article_id])
        )

        for (const config of configs) {
            const { guild_id, cafe_id, channel_id } = config

            const json = await fetchArticles(cafe_id)
            const articles = json.result.articleList

            if (!articles) continue

            const lastId = stateMap[guild_id] ?? 0

            if (lastId === 0) {
                await supabase.from('cafe_state').upsert({
                    id: guild_id,
                    last_article_id: articles[0].item.articleId
                })
                continue
            }

            const newArticles = articles
                .map((a: any) => a.item)
                .filter((a: any) => a.articleId > lastId)
                .sort((a: any, b: any) => a.articleId - b.articleId)

            if (!newArticles.length) continue

            const channel = (
                client.channels.cache.get(channel_id) ??
                await client.channels.fetch(channel_id)
            ) as TextBasedChannel

            if (!channel) continue

            for (const a of newArticles) {
                const url = `https://cafe.naver.com/f-e/cafes/${a.cafeId}/articles/${a.articleId}`

                const embed = new EmbedBuilder()
                    .setTitle(`📌 ${a.menuName}`)
                    .setDescription(`**${a.subject}**\n[바로가기](${url})`)
                    .setColor(0x9FCB98)
                    .setFooter({ text: '네이버 카페' })

                if (a.representImage) {
                    embed.setImage(a.representImage)
                }

                try {
                    await channel.send({ embeds: [embed] })
                } catch (e) {
                    console.error('전송 실패', e)
                }
            }

            await supabase.from('cafe_state').upsert({
                id: guild_id,
                last_article_id: articles[0].item.articleId
            })
        }
    } finally {
        running = false
    }
}

client.once('ready', async () => {
    console.log('봇 준비됨')

    await registerCommands()

    setInterval(async () => {
        try {
            await mainTask()
        } catch (e) {
            console.error(e)
        }
    }, 10000)
})

client.login(process.env.DISCORD_TOKEN!)