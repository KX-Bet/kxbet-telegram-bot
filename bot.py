import asyncio
import logging
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch

API_ID = 33123682
API_HASH = "bbd457d7a0418081f059ab0b57c8357e"
BOT_TOKEN = "8597470926:AAFWfpbLfpzxI5qMr8TmmQYUzR4d9LNZnsc"

VIP_GROUP_ID = -1003732620791
DISCUSSION_GROUP_ID = -1003933285650
CHECK_INTERVAL = 300

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_all_members(client, group_id):
    members = set()
    try:
        entity = await client.get_entity(group_id)
        offset = 0
        limit = 100
        while True:
            participants = await client(GetParticipantsRequest(
                channel=entity,
                filter=ChannelParticipantsSearch(""),
                offset=offset,
                limit=limit,
                hash=0
            ))
            if not participants.users:
                break
            for user in participants.users:
                if not user.bot:
                    members.add(user.id)
            offset += len(participants.users)
            if offset >= participants.count:
                break
            await asyncio.sleep(0.5)
        logger.info(f"Groupe {group_id} : {len(members)} membres")
    except Exception as e:
        logger.error(f"Erreur: {e}")
    return members

async def kick_member(client, group_id, user_id):
    try:
        await client.kick_participant(group_id, user_id)
        logger.info(f"✅ Membre {user_id} expulsé")
    except Exception as e:
        logger.error(f"❌ Erreur expulsion {user_id}: {e}")

async def main():
    client = TelegramClient("bot_session", API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    logger.info(f"✅ Connecté : @{me.username}")

    while True:
        try:
            logger.info("🔍 Vérification en cours...")
            vip_members = await get_all_members(client, VIP_GROUP_ID)
            discussion_members = await get_all_members(client, DISCUSSION_GROUP_ID)
            logger.info(f"👑 VIP : {len(vip_members)} | 💬 Discussion : {len(discussion_members)}")
            to_kick = discussion_members - vip_members
            to_kick.discard(me.id)
            if to_kick:
                logger.info(f"⚠️ {len(to_kick)} membre(s) à expulser...")
                for user_id in to_kick:
                    await kick_member(client, DISCUSSION_GROUP_ID, user_id)
                    await asyncio.sleep(1)
            else:
                logger.info("✅ Groupes synchronisés !")
        except Exception as e:
            logger.error(f"Erreur: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

if name == "__main__":
    asyncio.run(main())
