import datetime
import logging # Added
from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.exc import SQLAlchemyError # Added
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import User, Chat, Subscription

logger = logging.getLogger(__name__) # Added

async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User:
    """
    Retrieves a user by their Telegram ID. If the user does not exist, creates and returns a new user.
    """
    logger.debug(f"Attempting to get or create user with telegram_id: {telegram_id}")
    try:
        result = await session.execute(select(User).filter(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            logger.info(f"User with telegram_id {telegram_id} not found. Creating new user.")
            user = User(telegram_id=telegram_id)
            session.add(user)
            await session.commit() # Commit for new user creation
            await session.refresh(user)
            logger.info(f"Created and returned new user: {user.id} for telegram_id: {telegram_id}")
        else:
            logger.debug(f"Found existing user: {user.id} for telegram_id: {telegram_id}")
    except SQLAlchemyError as e:
        logger.error(f"Database error in get_user_by_telegram_id for telegram_id {telegram_id}: {e}", exc_info=True)
        await session.rollback() # Rollback on error during user creation attempt
        raise
    return user

async def create_subscription(session: AsyncSession, user_id: int, chat_id: int, duration_days: int, status: str = 'pending_payment', payment_id: Optional[str] = None, payment_details: Optional[dict] = None) -> Subscription:
    """
    Creates a new subscription for a user to a chat.
    """
    logger.debug(f"Attempting to create subscription for user_id {user_id} to chat_id {chat_id}")
    start_date = datetime.datetime.utcnow()
    end_date = start_date + datetime.timedelta(days=duration_days)
    
    new_subscription = Subscription(
        user_id=user_id,
        chat_id=chat_id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        payment_id=payment_id,
        payment_details=payment_details
    )
    try:
        session.add(new_subscription)
        # Commit is expected to be handled by the calling handler to group operations
        # await session.commit() 
        # await session.refresh(new_subscription)
        logger.info(f"Subscription object for user_id {user_id} to chat_id {chat_id} created and added to session.")
    except SQLAlchemyError as e:
        logger.error(f"Database error in create_subscription for user_id {user_id}, chat_id {chat_id}: {e}", exc_info=True)
        # Rollback should be handled by the calling handler
        raise
    return new_subscription

async def get_active_subscriptions(session: AsyncSession, user_telegram_id: int) -> List[Subscription]:
    """
    Fetches all active subscriptions for a given user by their Telegram ID.
    """
    logger.debug(f"Fetching active subscriptions for telegram_id: {user_telegram_id}")
    now = datetime.datetime.utcnow()
    try:
        result = await session.execute(
            select(Subscription)
            .join(User)
            .filter(User.telegram_id == user_telegram_id, Subscription.status == 'active', Subscription.end_date > now)
            .options(selectinload(Subscription.chat)) # Eager load chat details
        )
        subscriptions = result.scalars().all()
        logger.debug(f"Found {len(subscriptions)} active subscriptions for telegram_id: {user_telegram_id}")
        return subscriptions
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching active subscriptions for telegram_id {user_telegram_id}: {e}", exc_info=True)
        raise
    return result.scalars().all()

async def get_subscriptions_ending_soon(session: AsyncSession, days_ahead: int) -> List[Subscription]:
    """
    Fetches subscriptions that are active and ending within the specified number of days_ahead.
    """
    logger.debug(f"Fetching subscriptions ending in {days_ahead} days.")
    now = datetime.datetime.utcnow()
    target_date = now + datetime.timedelta(days=days_ahead)
    try:
        result = await session.execute(
            select(Subscription)
            .filter(Subscription.status == 'active', Subscription.end_date > now, Subscription.end_date <= target_date)
            .options(selectinload(Subscription.user), selectinload(Subscription.chat)) # Eager load user and chat
        )
        subscriptions = result.scalars().all()
        logger.debug(f"Found {len(subscriptions)} subscriptions ending by {target_date}.")
        return subscriptions
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching subscriptions ending soon: {e}", exc_info=True)
        raise
    return result.scalars().all()

async def get_expired_subscriptions(session: AsyncSession) -> List[Subscription]:
    """
    Fetches subscriptions that have passed their end_date and are still marked as 'active'.
    """
    logger.debug("Fetching expired subscriptions.")
    now = datetime.datetime.utcnow()
    try:
        result = await session.execute(
            select(Subscription)
            .filter(Subscription.status == 'active', Subscription.end_date <= now)
            .options(selectinload(Subscription.user), selectinload(Subscription.chat)) # Eager load user and chat
        )
        subscriptions = result.scalars().all()
        logger.debug(f"Found {len(subscriptions)} expired subscriptions.")
        return subscriptions
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching expired subscriptions: {e}", exc_info=True)
        raise
    return result.scalars().all()

async def update_subscription_status(session: AsyncSession, subscription_id: int, new_status: str) -> Optional[Subscription]:
    """
    Updates the status of a specific subscription.
    """
    logger.debug(f"Attempting to update subscription_id {subscription_id} to status '{new_status}'.")
    try:
        result = await session.execute(select(Subscription).filter(Subscription.id == subscription_id))
        subscription = result.scalar_one_or_none()
        if subscription:
            subscription.status = new_status
            # Commit is expected to be handled by the calling handler
            # await session.commit()
            # await session.refresh(subscription)
            logger.info(f"Subscription {subscription_id} status updated to '{new_status}' in session.")
            return subscription
        else:
            logger.warning(f"Subscription_id {subscription_id} not found for status update.")
            return None
    except SQLAlchemyError as e:
        logger.error(f"Database error updating status for subscription_id {subscription_id}: {e}", exc_info=True)
        # Rollback should be handled by the calling handler
        raise
    return None

async def get_chat_by_id(session: AsyncSession, chat_id: int) -> Optional[Chat]:
    """
    Retrieves a specific chat by its ID.
    """
    logger.debug(f"Fetching chat by id: {chat_id}.")
    try:
        result = await session.execute(select(Chat).filter(Chat.id == chat_id))
        chat = result.scalar_one_or_none()
        if chat:
            logger.debug(f"Chat {chat_id} found.")
        else:
            logger.debug(f"Chat {chat_id} not found.")
        return chat
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching chat by id {chat_id}: {e}", exc_info=True)
        raise
    return result.scalar_one_or_none()

async def get_all_managed_chats(session: AsyncSession) -> List[Chat]:
    """
    Retrieves all chats that are marked as active/managed by the bot.
    """
    logger.debug("Fetching all managed (active) chats.")
    try:
        result = await session.execute(select(Chat).filter(Chat.is_active == True))
        chats = result.scalars().all()
        logger.debug(f"Found {len(chats)} active chats.")
        return chats
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching all managed chats: {e}", exc_info=True)
        raise
    return result.scalars().all()

async def get_subscription_by_id(session: AsyncSession, subscription_id: int) -> Optional[Subscription]:
    """
    Retrieves a specific subscription by its ID.
    """
    logger.debug(f"Fetching subscription by id: {subscription_id}.")
    try:
        result = await session.execute(
            select(Subscription)
            .filter(Subscription.id == subscription_id)
            .options(selectinload(Subscription.chat), selectinload(Subscription.user)) # Eager load chat and user
        )
        subscription = result.scalar_one_or_none()
        if subscription:
            logger.debug(f"Subscription {subscription_id} found.")
        else:
            logger.debug(f"Subscription {subscription_id} not found.")
        return subscription
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching subscription by id {subscription_id}: {e}", exc_info=True)
        raise
    return result.scalar_one_or_none()


# --- Admin Specific Chat Management ---

async def create_chat(session: AsyncSession, telegram_chat_id: int, title: str, 
                      price_amount: float, price_currency: str, 
                      crypto_wallet_address: str, crypto_network: str, 
                      is_active: bool = True) -> Chat:
    """
    Creates a new managed chat.
    If a chat with the same telegram_chat_id exists, it will be updated.
    The caller is responsible for session.commit().
    """
    logger.debug(f"Attempting to create/update chat with telegram_chat_id: {telegram_chat_id}, title: {title}")
    try:
        # Check if chat with this telegram_chat_id already exists
        existing_chat_result = await session.execute(
            select(Chat).filter(Chat.telegram_chat_id == telegram_chat_id)
        )
        existing_chat = existing_chat_result.scalar_one_or_none()

        if existing_chat:
            logger.info(f"Chat with telegram_chat_id {telegram_chat_id} already exists (ID: {existing_chat.id}). Updating it.")
            existing_chat.title = title
            existing_chat.price_amount = price_amount
            existing_chat.price_currency = price_currency
            existing_chat.crypto_wallet_address = crypto_wallet_address
            existing_chat.crypto_network = crypto_network
            existing_chat.is_active = is_active
            chat = existing_chat
            # No session.add() needed as it's already persistent
        else:
            logger.info(f"Creating new chat with telegram_chat_id {telegram_chat_id}, title: {title}.")
            chat = Chat(
                telegram_chat_id=telegram_chat_id,
                title=title,
                price_amount=price_amount,
                price_currency=price_currency,
                crypto_wallet_address=crypto_wallet_address,
                crypto_network=crypto_network,
                is_active=is_active
            )
            session.add(chat)
        
        # Caller should commit and refresh if needed.
        # await session.flush() # To get ID before commit if needed, but usually handled by commit.
        logger.info(f"Chat object for telegram_chat_id {telegram_chat_id} prepared in session.")
        return chat
    except SQLAlchemyError as e:
        logger.error(f"Database error in create_chat for telegram_chat_id {telegram_chat_id}: {e}", exc_info=True)
        raise # Re-raise for the handler to manage transaction
    return chat


async def update_chat_details(session: AsyncSession, chat_id: int, **kwargs) -> Optional[Chat]:
    """
    Updates details for a specific chat by its primary key ID.
    kwargs can include: title, price_amount, price_currency, crypto_wallet_address, crypto_network, is_active.
    The caller is responsible for session.commit().
    """
    logger.debug(f"Attempting to update chat_id {chat_id} with details: {kwargs}")
    try:
        chat = await get_chat_by_id(session, chat_id) # get_chat_by_id uses primary key
        if chat:
            for key, value in kwargs.items():
                if hasattr(chat, key):
                    setattr(chat, key, value)
                    logger.debug(f"Set {key}={value} for chat_id {chat_id}")
                else:
                    logger.warning(f"Attempted to update non-existent attribute {key} for chat_id {chat_id}")
            logger.info(f"Chat {chat_id} details updated in session.")
            return chat
        else:
            logger.warning(f"Chat_id {chat_id} not found for update.")
            return None
    except SQLAlchemyError as e:
        logger.error(f"Database error updating chat_id {chat_id}: {e}", exc_info=True)
        raise
    return None

async def delete_chat_by_id(session: AsyncSession, chat_id: int) -> bool:
    """
    Deletes a chat by its primary key ID.
    Returns True if deletion was successful (or chat didn't exist), False on error.
    The caller is responsible for session.commit().
    Important: This is a destructive operation. Consider deactivating (is_active=False) instead.
    """
    logger.debug(f"Attempting to delete chat_id: {chat_id}")
    try:
        chat = await get_chat_by_id(session, chat_id)
        if chat:
            # Considerations for subscriptions are important here (e.g., RESTRICT, CASCADE, SET NULL)
            # This basic delete assumes such constraints are handled or not critical for this specific app logic,
            # or that the chat is typically deactivated first.
            await session.delete(chat)
            logger.info(f"Chat {chat_id} marked for deletion in session.")
            return True # Indicates deletion was attempted/successful on object level
        else:
            logger.warning(f"Chat_id {chat_id} not found for deletion.")
            return False # Chat not found
    except SQLAlchemyError as e:
        # This could catch errors like foreign key violations if RESTRICT is used
        logger.error(f"Database error deleting chat_id {chat_id}: {e}", exc_info=True)
        raise
