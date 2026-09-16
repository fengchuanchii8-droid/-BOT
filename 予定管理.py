import discord
from discord.ext import commands

import sqlite3
import re
import asyncio

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# ==================================================
# 設定
# ==================================================

TOKEN = "ここにBotのTOKEN"

PREFIX = "!"

# 日本時間
JST = ZoneInfo("Asia/Tokyo")

# SQLite
DB_NAME = "schedules.db"


# ==================================================
# Discord Bot
# ==================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents
)


# ==================================================
# 通知タスクを起こすためのイベント
# ==================================================

schedule_event = asyncio.Event()


# ==================================================
# データベース
# ==================================================

def get_db():

    return sqlite3.connect(
        DB_NAME
    )


def init_database():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            scheduled_time TEXT NOT NULL,
            message TEXT NOT NULL,
            user_ids TEXT NOT NULL,
            notified INTEGER NOT NULL DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


# ==================================================
# 時刻関係
# ==================================================

def now_jst():

    return datetime.now(JST)


def datetime_to_string(dt):

    return dt.astimezone(JST).isoformat()


def string_to_datetime(text):

    return datetime.fromisoformat(text)


# ==================================================
# Bot起動
# ==================================================

@bot.event
async def on_ready():

    print("--------------------------------")
    print(f"ログインしました: {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("--------------------------------")

    init_database()

    # 通知監視を開始
    if not notification_loop.is_running():
        notification_loop.start()


# ==================================================
# !予定
#
# !予定 9月20日 20時30分 TRPG開始 @A @B
# ==================================================

@bot.command()
async def 予定(
    ctx,
    month_day=None,
    time_text=None,
    *,
    rest=None
):

    # ------------------------------------------------
    # 入力チェック
    # ------------------------------------------------

    if (
        month_day is None
        or time_text is None
        or rest is None
    ):

        await ctx.send(
            "❌ 入力形式が正しくありません。\n\n"
            "使用例：\n"
            "`!予定 9月20日 20時30分 TRPG開始 @Aさん @Bさん`"
        )

        return

    # ------------------------------------------------
    # 日付
    # ------------------------------------------------

    date_match = re.fullmatch(
        r"(\d{1,2})月(\d{1,2})日",
        month_day
    )

    if not date_match:

        await ctx.send(
            "❌ 日付の形式が正しくありません。\n"
            "`9月20日` のように入力してください。"
        )

        return

    month = int(
        date_match.group(1)
    )

    day = int(
        date_match.group(2)
    )

    # ------------------------------------------------
    # 時刻
    # ------------------------------------------------

    time_match = re.fullmatch(
        r"(\d{1,2})時(\d{1,2})分",
        time_text
    )

    if not time_match:

        await ctx.send(
            "❌ 時刻の形式が正しくありません。\n"
            "`20時30分` のように入力してください。"
        )

        return

    hour = int(
        time_match.group(1)
    )

    minute = int(
        time_match.group(2)
    )

    # ------------------------------------------------
    # 時刻チェック
    # ------------------------------------------------

    if not 0 <= hour <= 23:

        await ctx.send(
            "❌ 時は0～23で入力してください。"
        )

        return

    if not 0 <= minute <= 59:

        await ctx.send(
            "❌ 分は0～59で入力してください。"
        )

        return

    # ------------------------------------------------
    # メンション取得
    # ------------------------------------------------

    mentioned_users = ctx.message.mentions

    if not mentioned_users:

        await ctx.send(
            "❌ 通知するユーザーを1人以上メンションしてください。\n\n"
            "例：\n"
            "`!予定 9月20日 20時30分 TRPG開始 @Aさん @Bさん`"
        )

        return

    # ------------------------------------------------
    # 予定内容からメンションを除去
    # ------------------------------------------------

    message = rest

    for user in mentioned_users:

        message = message.replace(
            user.mention,
            ""
        )

    message = message.strip()

    if not message:

        await ctx.send(
            "❌ 予定内容を入力してください。"
        )

        return

    # ------------------------------------------------
    # 日時作成
    # ------------------------------------------------

    now = now_jst()

    year = now.year

    try:

        scheduled_time = datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=JST
        )

    except ValueError:

        await ctx.send(
            "❌ 存在しない日付です。"
        )

        return

    # ------------------------------------------------
    # 既に過ぎている場合は翌年
    # ------------------------------------------------

    if scheduled_time <= now:

        try:

            scheduled_time = datetime(
                year + 1,
                month,
                day,
                hour,
                minute,
                tzinfo=JST
            )

        except ValueError:

            await ctx.send(
                "❌ 正しい日付を入力してください。"
            )

            return

    # ------------------------------------------------
    # 通知時刻
    # ------------------------------------------------

    notify_time = (
        scheduled_time
        - timedelta(hours=1)
    )

    # ------------------------------------------------
    # 通知時刻を既に過ぎている場合
    #
    # 予定の1時間前を過ぎてから登録した場合
    # すぐ通知する
    # ------------------------------------------------

    if now >= notify_time:

        notify_immediately = True

    else:

        notify_immediately = False

    # ------------------------------------------------
    # ユーザーID保存
    # ------------------------------------------------

    user_ids = ",".join(
        str(user.id)
        for user in mentioned_users
    )

    # ------------------------------------------------
    # DB保存
    # ------------------------------------------------

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO schedules
        (
            channel_id,
            guild_id,
            scheduled_time,
            message,
            user_ids,
            notified
        )
        VALUES (?, ?, ?, ?, ?, 0)
    """, (
        ctx.channel.id,
        ctx.guild.id,
        datetime_to_string(
            scheduled_time
        ),
        message,
        user_ids
    ))

    schedule_id = cursor.lastrowid

    conn.commit()
    conn.close()

    # ------------------------------------------------
    # 通知監視を起こす
    # ------------------------------------------------

    schedule_event.set()

    # ------------------------------------------------
    # 登録完了
    # ------------------------------------------------

    mentions = " ".join(
        user.mention
        for user in mentioned_users
    )

    await ctx.send(
        "✅ **予定を登録しました！**\n\n"
        f"ID：`{schedule_id}`\n"
        f"📅 {scheduled_time.strftime('%Y年%m月%d日 %H:%M')}\n"
        f"📝 {message}\n"
        f"👤 通知先：{mentions}\n\n"
        "🔔 1時間前に通知します。"
    )


# ==================================================
# !予定一覧
# ==================================================

@bot.command()
async def 予定一覧(ctx):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            scheduled_time,
            message,
            user_ids
        FROM schedules
        WHERE guild_id = ?
        AND notified = 0
        ORDER BY scheduled_time ASC
    """, (
        ctx.guild.id,
    ))

    rows = cursor.fetchall()

    conn.close()

    if not rows:

        await ctx.send(
            "📅 登録されている予定はありません。"
        )

        return

    text = "📅 **予定一覧**\n\n"

    for row in rows:

        schedule_id = row[0]

        scheduled_time = (
            string_to_datetime(row[1])
        )

        message = row[2]

        user_ids = row[3].split(",")

        mentions = " ".join(
            f"<@{user_id}>"
            for user_id in user_ids
        )

        text += (
            f"**ID：{schedule_id}**\n"
            f"📅 {scheduled_time.strftime('%Y/%m/%d %H:%M')}\n"
            f"📝 {message}\n"
            f"👤 {mentions}\n\n"
        )

    await ctx.send(text)


# ==================================================
# !予定削除
# ==================================================

@bot.command()
async def 予定削除(
    ctx,
    schedule_id=None
):

    if schedule_id is None:

        await ctx.send(
            "❌ 削除する予定のIDを指定してください。\n"
            "例：`!予定削除 3`"
        )

        return

    if not schedule_id.isdigit():

        await ctx.send(
            "❌ IDは数字で指定してください。"
        )

        return

    schedule_id = int(schedule_id)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id
        FROM schedules
        WHERE id = ?
        AND guild_id = ?
    """, (
        schedule_id,
        ctx.guild.id
    ))

    result = cursor.fetchone()

    if result is None:

        conn.close()

        await ctx.send(
            f"❌ ID `{schedule_id}` の予定がありません。"
        )

        return

    cursor.execute("""
        DELETE FROM schedules
        WHERE id = ?
        AND guild_id = ?
    """, (
        schedule_id,
        ctx.guild.id
    ))

    conn.commit()
    conn.close()

    # 通知待機を再計算
    schedule_event.set()

    await ctx.send(
        f"🗑️ ID `{schedule_id}` の予定を削除しました。"
    )


# ==================================================
# 次に通知する予定を取得
# ==================================================

def get_next_schedule():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            channel_id,
            scheduled_time,
            message,
            user_ids
        FROM schedules
        WHERE notified = 0
        ORDER BY scheduled_time ASC
        LIMIT 1
    """)

    row = cursor.fetchone()

    conn.close()

    return row


# ==================================================
# 通知
# ==================================================

async def send_notification(schedule):

    schedule_id = schedule[0]
    channel_id = schedule[1]

    scheduled_time = (
        string_to_datetime(schedule[2])
    )

    message = schedule[3]

    user_ids = schedule[4].split(",")

    # ------------------------------------------------
    # チャンネル取得
    # ------------------------------------------------

    channel = bot.get_channel(
        channel_id
    )

    if channel is None:

        try:

            channel = await bot.fetch_channel(
                channel_id
            )

        except (
            discord.NotFound,
            discord.HTTPException
        ):

            return

    # ------------------------------------------------
    # メンション
    # ------------------------------------------------

    mentions = " ".join(
        f"<@{user_id}>"
        for user_id in user_ids
    )

    # ------------------------------------------------
    # 通知
    # ------------------------------------------------

    await channel.send(
        f"🔔 **予定まであと1時間です！**\n\n"
        f"{mentions}\n\n"
        f"📅 {scheduled_time.strftime('%Y年%m月%d日 %H:%M')}\n"
        f"📝 {message}"
    )

    # ------------------------------------------------
    # 通知済みにする
    # ------------------------------------------------

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE schedules
        SET notified = 1
        WHERE id = ?
    """, (
        schedule_id,
    ))

    conn.commit()
    conn.close()


# ==================================================
# 通知監視
# ==================================================

async def wait_until_notify(
    schedule
):

    scheduled_time = (
        string_to_datetime(
            schedule[2]
        )
    )

    notify_time = (
        scheduled_time
        - timedelta(hours=1)
    )

    while True:

        now = now_jst()

        # --------------------------------------------
        # 通知時間になった
        # --------------------------------------------

        if now >= notify_time:

            await send_notification(
                schedule
            )

            return

        # --------------------------------------------
        # 残り時間
        # --------------------------------------------

        seconds = (
            notify_time - now
        ).total_seconds()

        # --------------------------------------------
        # 長時間待機
        #
        # 最大でも1時間ずつ寝る
        # --------------------------------------------

        wait_seconds = min(
            seconds,
            3600
        )

        try:

            await asyncio.wait_for(
                schedule_event.wait(),
                timeout=wait_seconds
            )

            # 新しい予定が登録・削除された
            schedule_event.clear()

            return

        except asyncio.TimeoutError:

            pass


# ==================================================
# 通知メインループ
# ==================================================

async def notification_worker():

    while True:

        # --------------------------------------------
        # 次の予定を取得
        # --------------------------------------------

        schedule = get_next_schedule()

        # --------------------------------------------
        # 予定がない
        # --------------------------------------------

        if schedule is None:

            schedule_event.clear()

            await schedule_event.wait()

            schedule_event.clear()

            continue

        # --------------------------------------------
        # 次の通知まで待つ
        # --------------------------------------------

        await wait_until_notify(
            schedule
        )


# ==================================================
# Bot起動時に通知Workerを開始
# ==================================================

@bot.event
async def setup_hook():

    init_database()

    bot.loop.create_task(
        notification_worker()
    )


# ==================================================
# エラー処理
# ==================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ 引数が足りません。\n\n"
            "例：\n"
            "`!予定 9月20日 20時30分 TRPG開始 @A @B`"
        )

        return

    print(
        f"エラー: {error}"
    )


# ==================================================
# Bot起動
# ==================================================

bot.run(TOKEN)