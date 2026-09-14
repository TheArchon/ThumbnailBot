import asyncio

from pyrogram import enums, filters, types
from pyrogram.enums import ButtonStyle

from ArchonMusic import app, config, db, lang
from ArchonMusic.helpers import admin_check, buttons, utils


# ============================================================
# HELP COMMAND
# ============================================================

@app.on_message(
    filters.command(["help"])
    & filters.private
    & ~app.bl_users
)
@lang.language()
async def _help(_, m: types.Message):
    await m.reply_text(
        text=m.lang["help_menu"],
        reply_markup=buttons.help_markup(m.lang),
        quote=True,
    )


# ============================================================
# START COMMAND
# ============================================================

@app.on_message(filters.command(["start"]))
@lang.language()
async def start(_, message: types.Message):

    # --------------------------------------------------------
    # Blocked user check
    # --------------------------------------------------------
    if (
        message.from_user
        and message.from_user.id in app.bl_users
        and message.from_user.id not in db.notified
    ):
        return await message.reply_text(
            message.lang["bl_user_notify"]
        )

    # --------------------------------------------------------
    # /start help
    # --------------------------------------------------------
    if (
        len(message.command) > 1
        and message.command[1].lower() == "help"
    ):
        return await _help(_, message)

    # --------------------------------------------------------
    # Chat type
    # --------------------------------------------------------
    private = message.chat.type == enums.ChatType.PRIVATE

    # --------------------------------------------------------
    # Start text
    # --------------------------------------------------------
    if private:
        first_name = (
            message.from_user.first_name
            if message.from_user
            else "User"
        )

        _text = message.lang["start_pm"].format(
            first_name,
            app.name,
        )
    else:
        _text = message.lang["start_gp"].format(
            app.name
        )

    # --------------------------------------------------------
    # Start buttons
    # --------------------------------------------------------
    key = buttons.start_key(
        message.lang,
        private,
    )

    # --------------------------------------------------------
    # START IMAGE
    #
    # IMPORTANT:
    # Pyrogram version me reply_photo() ke andar
    # quote parameter supported nahi hai.
    # Isliye quote use nahi kiya gaya.
    # --------------------------------------------------------
    try:
        await message.reply_photo(
            photo=config.START_IMAGE,
            caption=_text,
            reply_markup=key,
        )

    except Exception as e:
        print(f"START IMAGE ERROR: {e}")

        # ----------------------------------------------------
        # Image fail hone par text fallback
        # ----------------------------------------------------
        try:
            await message.reply_text(
                text=_text,
                reply_markup=key,
            )
        except Exception as text_error:
            print(
                f"START TEXT ERROR: {text_error}"
            )

    # --------------------------------------------------------
    # PRIVATE USER DATABASE
    # --------------------------------------------------------
    if private:

        if await db.is_user(
            message.from_user.id
        ):
            return

        try:
            await utils.send_log(message)
        except Exception as e:
            print(
                f"USER LOG ERROR: {e}"
            )

        await db.add_user(
            message.from_user.id
        )

    # --------------------------------------------------------
    # GROUP DATABASE
    # --------------------------------------------------------
    else:

        if await db.is_chat(
            message.chat.id
        ):
            return

        try:
            await utils.send_log(
                message,
                True,
            )
        except Exception as e:
            print(
                f"CHAT LOG ERROR: {e}"
            )

        await db.add_chat(
            message.chat.id
        )


# ============================================================
# SETTINGS / PLAYMODE
# ============================================================

@app.on_message(
    filters.command(
        ["settings", "playmode"]
    )
    & filters.group
    & ~app.bl_users
)
@lang.language()
@admin_check
async def settings(_, message: types.Message):

    admin_only = await db.get_play_mode(
        message.chat.id
    )

    cmd_delete = await db.get_cmd_delete(
        message.chat.id
    )

    vclogger = await db.get_vclogger(
        message.chat.id
    )

    thumbnail = await db.get_thumb_mode(
        message.chat.id
    )

    autoplay = await db.get_autoplay(
        message.chat.id
    )

    _language = await db.get_lang(
        message.chat.id
    )

    await message.reply_text(
        text=message.lang[
            "start_settings"
        ].format(
            message.chat.title
        ),

        reply_markup=buttons.settings_markup(
            message.lang,
            admin_only,
            cmd_delete,
            vclogger,
            thumbnail,
            autoplay,
            _language,
            message.chat.id,
        ),

        quote=True,
    )


# ============================================================
# NEW CHAT MEMBER
# ============================================================

@app.on_message(
    filters.new_chat_members,
    group=7,
)
@lang.language()
async def _new_member(_, message: types.Message):

    # --------------------------------------------------------
    # Only supergroups
    # --------------------------------------------------------
    if (
        message.chat.type
        != enums.ChatType.SUPERGROUP
    ):
        return await message.chat.leave()

    await asyncio.sleep(3)

    # --------------------------------------------------------
    # Check every new member
    # --------------------------------------------------------
    for member in message.new_chat_members:

        # Bot is not the new member
        if member.id != app.id:
            continue

        # ----------------------------------------------------
        # Add group to database
        # ----------------------------------------------------
        try:
            await utils.send_log(
                message,
                True,
            )
        except Exception as e:
            print(
                f"GROUP LOG ERROR: {e}"
            )

        try:
            await db.add_chat(
                message.chat.id
            )
        except Exception as e:
            print(
                f"ADD CHAT ERROR: {e}"
            )

        # ----------------------------------------------------
        # Who added the bot
        # ----------------------------------------------------
        if message.from_user:
            adder = message.from_user.mention
        else:
            adder = "there"

        # ----------------------------------------------------
        # Group welcome text
        # ----------------------------------------------------
        _text = message.lang[
            "chat_added"
        ].format(
            adder,
            app.name,
            message.lang["support"],
        )

        # ----------------------------------------------------
        # Group welcome buttons
        # ----------------------------------------------------
        key = types.InlineKeyboardMarkup(
            [
                [
                    types.InlineKeyboardButton(
                        text=message.lang[
                            "add_me"
                        ],
                        url=(
                            f"https://t.me/"
                            f"{app.username}"
                            f"?startgroup=true"
                        ),
                        style=ButtonStyle.SUCCESS,
                    ),

                    types.InlineKeyboardButton(
                        text=message.lang[
                            "support"
                        ],
                        url=config.SUPPORT_CHAT,
                        style=ButtonStyle.PRIMARY,
                    ),
                ]
            ]
        )

        # ----------------------------------------------------
        # Send JPG welcome message
        # ----------------------------------------------------
        try:
            await app.send_photo(
                chat_id=message.chat.id,
                photo=config.START_IMAGE,
                caption=_text,
                reply_markup=key,
            )

        except Exception as e:

            print(
                f"GROUP START IMAGE ERROR: {e}"
            )

            # ------------------------------------------------
            # Fallback to text
            # ------------------------------------------------
            try:
                await app.send_message(
                    chat_id=message.chat.id,
                    text=_text,
                    reply_markup=key,
                )

            except Exception as text_error:

                print(
                    f"GROUP START TEXT ERROR: "
                    f"{text_error}"
                )


# ============================================================
# BOT LEFT GROUP
# ============================================================

@app.on_message(
    filters.left_chat_member,
    group=8,
)
async def _left_member(
    _,
    message: types.Message,
):

    if (
        message.left_chat_member
        and message.left_chat_member.id == app.id
    ):

        try:
            await utils.send_left_log(
                message.chat.id,
                message.chat.title,
                message.from_user,
            )
        except Exception as e:
            print(
                f"LEFT LOG ERROR: {e}"
            )

        try:
            await db.rm_chat(
                message.chat.id
            )
        except Exception as e:
            print(
                f"REMOVE CHAT ERROR: {e}"
            )


# ============================================================
# BOT CHAT MEMBER STATUS UPDATE
# ============================================================

@app.on_chat_member_updated()
async def _my_chat_member_updated(
    _,
    member: types.ChatMemberUpdated,
):

    # --------------------------------------------------------
    # Make sure old/new member exist
    # --------------------------------------------------------
    if (
        not member.old_chat_member
        or not member.new_chat_member
    ):
        return

    old_status = (
        member.old_chat_member.status
    )

    new_status = (
        member.new_chat_member.status
    )

    # --------------------------------------------------------
    # Bot was removed/banned
    # --------------------------------------------------------
    if (
        old_status
        in [
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
        ]

        and new_status
        in [
            enums.ChatMemberStatus.LEFT,
            enums.ChatMemberStatus.BANNED,
        ]
    ):

        # ----------------------------------------------------
        # Make sure affected user is our bot
        # ----------------------------------------------------
        if (
            member.new_chat_member.user
            and member.new_chat_member.user.id
            == app.id
        ):

            try:
                await utils.send_left_log(
                    member.chat.id,
                    member.chat.title,
                    member.from_user,
                )
            except Exception as e:
                print(
                    f"MEMBER UPDATE LOG ERROR: "
                    f"{e}"
                )

            try:
                await db.rm_chat(
                    member.chat.id
                )
            except Exception as e:
                print(
                    f"MEMBER UPDATE DB ERROR: "
                    f"{e}"
    )
