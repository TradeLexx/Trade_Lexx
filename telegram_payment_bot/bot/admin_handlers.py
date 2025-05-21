import functools
import logging
from typing import Callable, Any, Coroutine
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import traceback # For global error handler
import html      # For global error handler
import json      # For global error handler
from telegram import constants as telegram_constants # For global error handler
from sqlalchemy.exc import SQLAlchemyError

from . import db_utils
from .models import Chat

logger = logging.getLogger(__name__)

# Conversation states for adding a chat
CHAT_ID, TITLE, PRICE_AMOUNT, PRICE_CURRENCY, WALLET_ADDRESS, NETWORK, CONFIRM_CHAT_CREATION = range(7)


def is_admin(func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, Any]]):
    """
    Decorator to check if the user is an admin.
    Replies with "Access Denied" if not an admin.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            logger.warning("is_admin decorator: update.effective_user is None. Denying access.")
            # This can happen with channel posts, etc. Ensure it's a user command.
            if update.callback_query:
                await update.callback_query.answer("Error: Could not identify user.", show_alert=True)
            return None # Or ConversationHandler.END if in a conversation

        user_id = update.effective_user.id
        admin_ids = context.application.bot_data.get('settings', {}).get('ADMIN_USER_IDS', [])

        if not admin_ids:
            logger.warning("is_admin decorator: ADMIN_USER_IDS is not configured in bot_data.settings. Denying access.")
            if update.callback_query:
                await update.callback_query.answer("Admin IDs not configured.", show_alert=True)
            elif update.message:
                await update.message.reply_text("Access Denied: Admin functionality is not configured.")
            return None

        if user_id not in admin_ids:
            logger.warning(f"User {user_id} attempted to access admin command {func.__name__} without privileges.")
            if update.callback_query:
                await update.callback_query.answer("Access Denied.", show_alert=True)
                # Optionally edit message to remove admin keyboard
                # await update.callback_query.edit_message_text("Access Denied.")
            elif update.message:
                await update.message.reply_text("Access Denied. You are not authorized for this command.")
            return None # Or ConversationHandler.END if in a conversation
        
        return await func(update, context, *args, **kwargs)
    return wrapper

@is_admin
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the main admin panel."""
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.debug(f"Admin panel accessed by user {user_id}")
    keyboard = [
        [InlineKeyboardButton("Manage Chats", callback_data='admin_manage_chats')],
        [InlineKeyboardButton("View Users", callback_data='admin_view_users')],
        [InlineKeyboardButton("Configure Wallet (Global)", callback_data='admin_configure_wallet')],
        # Consider if 'user_panel_return' is appropriate here or if it should be 'admin_main_menu' or similar
        # For now, assuming it's a way to exit admin specific section if user is also admin.
        [InlineKeyboardButton("<< Back to User Panel", callback_data='user_panel_return')] 
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = "Admin Panel"
    try:
        if update.callback_query:
            await update.callback_query.answer()
            if update.effective_message:
                await update.effective_message.edit_text(message_text, reply_markup=reply_markup)
            else:
                logger.error(f"admin_panel (callback): update.effective_message is None for admin {user_id}")
                await update.callback_query.answer("Error displaying panel.", show_alert=True) # Notify admin
        elif update.message:
            await update.message.reply_text(message_text, reply_markup=reply_markup)
        else:
            logger.error(f"admin_panel: called without update.message or update.callback_query by admin {user_id}")
    except Exception as e:
        logger.error(f"Error in admin_panel for admin {user_id}: {e}", exc_info=True)
        if update.callback_query:
            await update.callback_query.answer("An error occurred in admin panel.", show_alert=True)
        elif update.message:
            await update.message.reply_text("An error occurred in admin panel. Please check logs.")


@is_admin
async def manage_chats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays chat management options."""
    query = update.callback_query
    user_id = query.from_user.id
    logger.debug(f"manage_chats_callback called by admin {user_id}")
    try:
        await query.answer()
        keyboard = [
            [InlineKeyboardButton("Add New Chat", callback_data='admin_add_chat_start')],
            [InlineKeyboardButton("List/Edit Chats", callback_data='admin_list_chats')],
            [InlineKeyboardButton("<< Back to Admin Panel", callback_data='admin_panel_return')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.effective_message:
            await update.effective_message.edit_text("Chat Management", reply_markup=reply_markup)
        else:
            logger.error(f"manage_chats_callback: update.effective_message is None for admin {user_id}")
            await query.answer("Error displaying chat management.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in manage_chats_callback for admin {user_id}: {e}", exc_info=True)
        await query.answer("An error occurred.", show_alert=True)


@is_admin
async def list_chats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists all managed chats with options to edit or remove."""
    query = update.callback_query
    user_id = query.from_user.id
    logger.debug(f"list_chats_callback called by admin {user_id}")
    
    try:
        await query.answer()
        async_session_factory = context.application.bot_data['async_session_factory']
        all_chats: list[Chat] = []
        async with async_session_factory() as session:
            all_chats = await db_utils.get_all_managed_chats(session)
        
        logger.info(f"Admin {user_id} listed {len(all_chats)} managed chats.")

        if not all_chats:
            message_text = "No chats are currently managed."
            keyboard = [[InlineKeyboardButton("Add New Chat", callback_data='admin_add_chat_start')],
                        [InlineKeyboardButton("<< Back to Chat Management", callback_data='admin_manage_chats')]]
        else:
            message_text = "Managed Chats:\n"
            keyboard = []
            for chat_item in all_chats:
                message_text += f"- {chat_item.title} (ID: {chat_item.telegram_chat_id}, DB_ID: {chat_item.id})\n"
                keyboard.append([
                    InlineKeyboardButton(f"Edit: {chat_item.title[:20]}...", callback_data=f'admin_edit_chat_{chat_item.id}'),
                    InlineKeyboardButton(f"Toggle Active: {'Deactivate' if chat_item.is_active else 'Activate'}", callback_data=f'admin_toggle_chat_{chat_item.id}'),
                    InlineKeyboardButton(f"Remove: {chat_item.title[:10]}...", callback_data=f'admin_confirm_remove_chat_{chat_item.id}')
                ])
            keyboard.append([InlineKeyboardButton("<< Back to Chat Management", callback_data='admin_manage_chats')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.effective_message:
            await update.effective_message.edit_text(message_text, reply_markup=reply_markup)
        else:
            logger.error(f"list_chats_callback: update.effective_message is None for admin {user_id}")
            # No direct reply to user as query.answer() was called. Message edit failed.
    
    except SQLAlchemyError as e:
        logger.error(f"Database error in list_chats_callback for admin {user_id}: {e}", exc_info=True)
        if update.effective_message:
            await update.effective_message.edit_text("Could not retrieve chat list due to a database issue.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back", callback_data='admin_manage_chats')]]))
    except Exception as e:
        logger.error(f"Error in list_chats_callback for admin {user_id}: {e}", exc_info=True)
        if update.effective_message:
            await update.effective_message.edit_text("An unexpected error occurred listing chats.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back", callback_data='admin_manage_chats')]]))


# --- Stubs for Edit/Remove Chat ---
@is_admin
async def edit_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # This would typically lead to another ConversationHandler to edit fields one by one or via a form.
    query = update.callback_query
    user_id = query.from_user.id
    chat_db_id = query.data.split('_')[-1]
    logger.debug(f"edit_chat_callback called by admin {user_id} for chat_db_id {chat_db_id}")
    
    try:
        await query.answer()
        await query.edit_message_text(
            f"Editing Chat DB ID {chat_db_id} - This feature is a placeholder.\n"
            "A full implementation would involve a ConversationHandler to edit specific fields.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]])
        )
    except Exception as e:
        logger.error(f"Error in edit_chat_callback for admin {user_id}, chat_db_id {chat_db_id}: {e}", exc_info=True)
        await query.answer("An error occurred.", show_alert=True)

@is_admin
async def toggle_chat_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggles the is_active status of a chat."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_db_id_str = query.data.split('_')[-1]
    logger.debug(f"toggle_chat_status_callback called by admin {user_id} for chat_db_id {chat_db_id_str}")

    if not chat_db_id_str.isdigit():
        logger.warning(f"Invalid chat_db_id for toggle: {chat_db_id_str} by admin {user_id}")
        await query.answer("Invalid chat ID.", show_alert=True)
        return

    chat_db_id = int(chat_db_id_str)
    async_session_factory = context.application.bot_data['async_session_factory']
    
    try:
        await query.answer()
        async with async_session_factory() as session:
            async with session.begin():
                chat_to_toggle = await db_utils.get_chat_by_id(session, chat_db_id)
                if not chat_to_toggle:
                    logger.warning(f"Chat DB ID {chat_db_id} not found for toggle by admin {user_id}")
                    await query.edit_message_text("Chat not found.", 
                                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]]))
                    return
                
                new_status = not chat_to_toggle.is_active
                updated_chat = await db_utils.update_chat_details(session, chat_db_id, is_active=new_status)
                await session.commit()
        
        if updated_chat:
            logger.info(f"Admin {user_id} toggled chat {chat_db_id} status to {'active' if new_status else 'inactive'}.")
            # Refresh the list of chats
            await list_chats_callback(update, context)
        else: # Should not happen if get_chat_by_id found it
            logger.error(f"Failed to update chat {chat_db_id} status for admin {user_id} after finding it.")
            await query.edit_message_text("Failed to toggle chat status.",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]]))

    except SQLAlchemyError as e:
        logger.error(f"Database error in toggle_chat_status_callback for admin {user_id}, chat_db_id {chat_db_id}: {e}", exc_info=True)
        await query.edit_message_text("Database error updating chat status.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]]))
    except Exception as e:
        logger.error(f"Error in toggle_chat_status_callback for admin {user_id}, chat_db_id {chat_db_id}: {e}", exc_info=True)
        if query.message: # Check if message exists to edit
             await query.edit_message_text("An error occurred toggling chat status.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]]))
        else: # If no message to edit, just answer the callback
            await query.answer("An error occurred.", show_alert=True)


@is_admin
async def confirm_remove_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Asks for confirmation before removing a chat."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_db_id_str = query.data.split('_')[-1] # E.g., admin_confirm_remove_chat_123
    logger.debug(f"confirm_remove_chat_callback called by admin {user_id} for chat_db_id {chat_db_id_str}")

    if not chat_db_id_str.isdigit():
        logger.warning(f"Invalid chat_db_id for confirm_remove: {chat_db_id_str} by admin {user_id}")
        await query.answer("Invalid chat ID.", show_alert=True)
        return
    
    chat_db_id = int(chat_db_id_str)
    
    keyboard = [
        [InlineKeyboardButton(f"Yes, REMOVE Chat {chat_db_id}", callback_data=f'admin_execute_remove_chat_{chat_db_id}')],
        [InlineKeyboardButton("No, Cancel", callback_data='admin_list_chats')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.answer()
        # Fetch chat title for a more informative message, if desired
        # async_session_factory = context.application.bot_data['async_session_factory']
        # async with async_session_factory() as session:
        #     chat = await db_utils.get_chat_by_id(session, chat_db_id)
        #     title = chat.title if chat else "Unknown Chat"
        await query.edit_message_text(
            f"⚠️ Are you sure you want to remove Chat DB ID {chat_db_id}?\n"
            "This action is irreversible and might affect existing subscriptions (depending on DB setup). "
            "Consider deactivating the chat instead.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in confirm_remove_chat_callback for admin {user_id}, chat_db_id {chat_db_id}: {e}", exc_info=True)
        await query.answer("An error occurred.", show_alert=True)


@is_admin
async def execute_remove_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Executes the removal of a chat after confirmation."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_db_id_str = query.data.split('_')[-1] # E.g., admin_execute_remove_chat_123
    logger.debug(f"execute_remove_chat_callback called by admin {user_id} for chat_db_id {chat_db_id_str}")

    if not chat_db_id_str.isdigit():
        logger.warning(f"Invalid chat_db_id for execute_remove: {chat_db_id_str} by admin {user_id}")
        await query.answer("Invalid chat ID.", show_alert=True)
        return

    chat_db_id = int(chat_db_id_str)
    async_session_factory = context.application.bot_data['async_session_factory']
    
    try:
        await query.answer(text="Attempting to remove chat...") # Give immediate feedback
        async with async_session_factory() as session:
            async with session.begin():
                success = await db_utils.delete_chat_by_id(session, chat_db_id)
                if success:
                    await session.commit()
                    logger.info(f"Admin {user_id} successfully removed chat DB ID {chat_db_id}.")
                    await query.edit_message_text(f"Chat DB ID {chat_db_id} has been removed.",
                                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]]))
                else:
                    # This means get_chat_by_id returned None in db_utils, so chat was already gone or never existed.
                    logger.warning(f"Admin {user_id} tried to remove chat DB ID {chat_db_id}, but it was not found.")
                    await query.edit_message_text(f"Chat DB ID {chat_db_id} not found. It might have been already removed.",
                                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]]))
        # Refresh chat list after deletion
        # This call might be problematic if the original message was deleted or if query object is stale
        # A safer way is to just tell admin it's done and they can go back.
        # For now, attempting to refresh the list:
        # await list_chats_callback(update, context) # This might cause issues if called after edit_message_text
        
    except SQLAlchemyError as e:
        # This could be due to foreign key constraints if subscriptions exist and ON DELETE RESTRICT is set.
        logger.error(f"Database error in execute_remove_chat_callback for admin {user_id}, chat_db_id {chat_db_id}: {e}", exc_info=True)
        error_message = "Database error removing chat. It might be in use (e.g., active subscriptions)."
        if "foreign key constraint" in str(e).lower():
             error_message = "Cannot remove chat: It is still referenced by existing subscriptions. Please ensure no subscriptions are linked to this chat."
        await query.edit_message_text(error_message,
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]]))
    except Exception as e:
        logger.error(f"Error in execute_remove_chat_callback for admin {user_id}, chat_db_id {chat_db_id}: {e}", exc_info=True)
        if query.message:
            await query.edit_message_text("An unexpected error occurred while removing the chat.",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to List Chats", callback_data='admin_list_chats')]]))
        else:
            await query.answer("An error occurred removing chat.", show_alert=True)


# --- User Viewing (Placeholder) ---
@is_admin
async def view_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    logger.debug(f"view_users_callback called by admin {user_id}")
    try:
        await query.answer()
        keyboard = [[InlineKeyboardButton("<< Back to Admin Panel", callback_data='admin_panel_return')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.effective_message:
            await update.effective_message.edit_text(
                "User Viewing - Feature coming soon. For now, check database directly or use external DB tools.",
                reply_markup=reply_markup
            )
        else:
            logger.error(f"view_users_callback: update.effective_message is None for admin {user_id}")
            await query.answer("Error displaying user viewing section.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in view_users_callback for admin {user_id}: {e}", exc_info=True)
        await query.answer("An error occurred.", show_alert=True)


# --- Wallet Configuration (Placeholder) ---
@is_admin
async def configure_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    logger.debug(f"configure_wallet_callback called by admin {user_id}")
    try:
        await query.answer()
        keyboard = [[InlineKeyboardButton("<< Back to Admin Panel", callback_data='admin_panel_return')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        app_settings = context.application.bot_data.get('settings')
        default_wallet = app_settings.DEFAULT_CRYPTO_WALLET if app_settings else "Not set"
        default_network = app_settings.DEFAULT_CRYPTO_NETWORK if app_settings else "Not set"
        
        message_text = (
            "Global Wallet Configuration:\n"
            f"- Default Wallet: `{default_wallet}`\n"
            f"- Default Network: `{default_network}`\n\n"
            "This is currently set via environment variables (`DEFAULT_CRYPTO_WALLET`, `DEFAULT_CRYPTO_NETWORK`). "
            "Chat-specific wallets are set upon chat creation/editing."
        )
        if update.effective_message:
            await update.effective_message.edit_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            logger.error(f"configure_wallet_callback: update.effective_message is None for admin {user_id}")
            await query.answer("Error displaying wallet configuration.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in configure_wallet_callback for admin {user_id}: {e}", exc_info=True)
        await query.answer("An error occurred.", show_alert=True)


# --- Return to Admin Panel ---
@is_admin
async def admin_panel_return_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Returns to the main admin panel."""
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.debug(f"admin_panel_return_callback called by admin {user_id}")
    try:
        # This re-uses the admin_panel function to display the panel
        await admin_panel(update, context)
    except Exception as e:
        logger.error(f"Error in admin_panel_return_callback for admin {user_id}: {e}", exc_info=True)
        if update.callback_query:
            await update.callback_query.answer("Error returning to admin panel.", show_alert=True)
        # No reply if it's a message, to avoid issues if admin_panel itself fails.


# --- Conversation Handler for Adding a Chat ---
@is_admin
async def add_chat_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add a new chat. Asks for Chat Telegram ID."""
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.debug(f"add_chat_start_callback called by admin {user_id}")
    
    message_text = "Let's add a new chat. What is the Telegram Chat ID (e.g., -1001234567890)?\nSend /cancel to abort."
    try:
        if update.callback_query:
            await update.callback_query.answer()
            if update.effective_message:
                await update.effective_message.edit_text(message_text)
            else:
                logger.error(f"add_chat_start_callback: update.effective_message is None for query by admin {user_id}")
                return ConversationHandler.END
        elif update.message:
            await update.message.reply_text(message_text)
        
        context.chat_data['new_chat_info'] = {}
        logger.info(f"Admin {user_id} started adding a new chat.")
        return CHAT_ID
    except Exception as e:
        logger.error(f"Error in add_chat_start_callback for admin {user_id}: {e}", exc_info=True)
        if update.callback_query:
            await update.callback_query.answer("Error starting chat creation.", show_alert=True)
        elif update.message:
            await update.message.reply_text("Error starting chat creation. Please try again.")
        return ConversationHandler.END


async def receive_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives Telegram Chat ID and asks for Title."""
    user_id = update.effective_user.id
    chat_id_text = update.message.text
    logger.debug(f"Admin {user_id} entered chat_id: {chat_id_text}")
    try:
        chat_id_val = int(chat_id_text)
        context.chat_data['new_chat_info']['telegram_chat_id'] = chat_id_val
        await update.message.reply_text("Got it. Now, what is the Title for this chat (e.g., 'VIP Gold Members')?")
        return TITLE
    except ValueError:
        logger.warning(f"Admin {user_id} entered invalid chat_id: {chat_id_text}")
        await update.message.reply_text("Invalid Chat ID. Please send a valid number (e.g., -1001234567890).\nOr /cancel to abort.")
        return CHAT_ID
    except Exception as e:
        logger.error(f"Error in receive_chat_id for admin {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred. Please try again or /cancel.")
        return CHAT_ID # Stay in current state or end


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives Title and asks for Price Amount."""
    user_id = update.effective_user.id
    title_text = update.message.text
    logger.debug(f"Admin {user_id} entered title: {title_text}")
    try:
        context.chat_data['new_chat_info']['title'] = title_text
        await update.message.reply_text("Great. What is the subscription price amount (e.g., 10.99)?")
        return PRICE_AMOUNT
    except Exception as e:
        logger.error(f"Error in receive_title for admin {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred. Please try again or /cancel.")
        return TITLE


async def receive_price_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives Price Amount and asks for Price Currency."""
    user_id = update.effective_user.id
    price_text = update.message.text
    logger.debug(f"Admin {user_id} entered price: {price_text}")
    try:
        price = float(price_text)
        context.chat_data['new_chat_info']['price_amount'] = price
        await update.message.reply_text("What is the price currency (e.g., USD, EUR)?")
        return PRICE_CURRENCY
    except ValueError:
        logger.warning(f"Admin {user_id} entered invalid price: {price_text}")
        await update.message.reply_text("Invalid price amount. Please send a number (e.g., 10.99).\nOr /cancel to abort.")
        return PRICE_AMOUNT
    except Exception as e:
        logger.error(f"Error in receive_price_amount for admin {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred. Please try again or /cancel.")
        return PRICE_AMOUNT


async def receive_price_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives Price Currency and asks for Crypto Wallet Address (optional)."""
    user_id = update.effective_user.id
    currency_text = update.message.text.upper()
    logger.debug(f"Admin {user_id} entered currency: {currency_text}")
    try:
        context.chat_data['new_chat_info']['price_currency'] = currency_text
        app_settings = context.application.bot_data.get('settings')
        default_wallet_info = ""
        if app_settings and app_settings.DEFAULT_CRYPTO_WALLET:
            default_wallet_info = f"\n(Press /skip to use default: {app_settings.DEFAULT_CRYPTO_WALLET})"
        
        await update.message.reply_text(f"Enter the Crypto Wallet Address for this chat.{default_wallet_info}\nOr send /skip if not applicable or to use default.")
        return WALLET_ADDRESS
    except Exception as e:
        logger.error(f"Error in receive_price_currency for admin {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred. Please try again or /cancel.")
        return PRICE_CURRENCY


async def receive_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives Wallet Address or /skip, then asks for Crypto Network (optional)."""
    user_id = update.effective_user.id
    text = update.message.text
    logger.debug(f"Admin {user_id} entered wallet address (or skip): {text[:30]}...") # Log part of address
    try:
        chat_info = context.chat_data['new_chat_info']
        app_settings = context.application.bot_data.get('settings')

        if text == '/skip':
            chat_info['crypto_wallet_address'] = app_settings.DEFAULT_CRYPTO_WALLET if app_settings else None
            logger.info(f"Admin {user_id} skipped wallet address input, using default: {chat_info['crypto_wallet_address']}")
        else:
            chat_info['crypto_wallet_address'] = text

        default_network_info = ""
        if app_settings and app_settings.DEFAULT_CRYPTO_NETWORK:
            default_network_info = f"\n(Press /skip to use default: {app_settings.DEFAULT_CRYPTO_NETWORK})"

        await update.message.reply_text(f"What is the Crypto Network for this wallet?{default_network_info}\nOr send /skip if not applicable or to use default.")
        return NETWORK
    except Exception as e:
        logger.error(f"Error in receive_wallet_address for admin {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred. Please try again or /cancel.")
        return WALLET_ADDRESS


async def receive_network(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives Crypto Network or /skip, then asks for confirmation."""
    user_id = update.effective_user.id
    text = update.message.text
    logger.debug(f"Admin {user_id} entered network (or skip): {text}")
    try:
        chat_info = context.chat_data['new_chat_info']
        app_settings = context.application.bot_data.get('settings')

        if text == '/skip':
            chat_info['crypto_network'] = app_settings.DEFAULT_CRYPTO_NETWORK if app_settings else None
            logger.info(f"Admin {user_id} skipped network input, using default: {chat_info['crypto_network']}")
        else:
            chat_info['crypto_network'] = text

        # Ensure defaults are applied if fields are None and defaults exist
        if chat_info.get('crypto_wallet_address') is None and app_settings and app_settings.DEFAULT_CRYPTO_WALLET:
            chat_info['crypto_wallet_address'] = app_settings.DEFAULT_CRYPTO_WALLET
        if chat_info.get('crypto_network') is None and app_settings and app_settings.DEFAULT_CRYPTO_NETWORK:
            chat_info['crypto_network'] = app_settings.DEFAULT_CRYPTO_NETWORK

        wallet_address_display = chat_info.get('crypto_wallet_address', "Not Set")
        network_display = chat_info.get('crypto_network', "Not Set")

        confirmation_text = (
            "Please confirm the details for the new chat:\n"
            f"- Telegram Chat ID: {chat_info['telegram_chat_id']}\n"
            f"- Title: {chat_info['title']}\n"
            f"- Price: {chat_info['price_amount']:.2f} {chat_info['price_currency']}\n"
            f"- Wallet Address: {wallet_address_display}\n"
            f"- Network: {network_display}\n\n"
            "Is this correct?"
        )
        keyboard = [
            [InlineKeyboardButton("Yes, Create Chat", callback_data='admin_confirm_create_chat')],
            [InlineKeyboardButton("No, Start Over", callback_data='admin_add_chat_start')],
            [InlineKeyboardButton("Cancel", callback_data='admin_cancel_chat_creation')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
        return CONFIRM_CHAT_CREATION
    except Exception as e:
        logger.error(f"Error in receive_network for admin {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred. Please try again or /cancel.")
        return NETWORK


@is_admin
async def confirm_create_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new chat to the database."""
    query = update.callback_query
    user_id = query.from_user.id
    logger.debug(f"confirm_create_chat_callback called by admin {user_id}")
    
    try:
        await query.answer()
        chat_info = context.chat_data.get('new_chat_info')
        if not chat_info:
            logger.error(f"Chat info not found in context for admin {user_id} at confirm_create_chat_callback.")
            if update.effective_message:
                await update.effective_message.edit_text("Error: Chat information not found. Please start over.", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to Chat Management", callback_data='admin_manage_chats')]]))
            return ConversationHandler.END

        async_session_factory = context.application.bot_data['async_session_factory']
        async with async_session_factory() as session:
            async with session.begin(): # Start a transaction
                new_chat = await db_utils.create_chat(
                    session,
                    telegram_chat_id=chat_info['telegram_chat_id'],
                    title=chat_info['title'],
                    price_amount=chat_info['price_amount'],
                    price_currency=chat_info['price_currency'],
                    crypto_wallet_address=chat_info.get('crypto_wallet_address'),
                    crypto_network=chat_info.get('crypto_network')
                )
                await session.commit() 
        
        logger.info(f"Admin {user_id} successfully created/updated chat: {new_chat.title} (TG ID: {new_chat.telegram_chat_id}, DB ID: {new_chat.id})")
        if update.effective_message:
            await update.effective_message.edit_text(
                f"Successfully created/updated chat: {new_chat.title} (TG ID: {new_chat.telegram_chat_id})",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to Chat Management", callback_data='admin_manage_chats')]]))
    
    except SQLAlchemyError as e:
        logger.error(f"Database error in confirm_create_chat_callback for admin {user_id}: {e}", exc_info=True)
        if update.effective_message:
            await update.effective_message.edit_text(f"Failed to create/update chat due to a database error. Please check logs.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to Chat Management", callback_data='admin_manage_chats')]]))
    except Exception as e:
        logger.error(f"Error in confirm_create_chat_callback for admin {user_id}: {e}", exc_info=True)
        if update.effective_message:
            await update.effective_message.edit_text(f"An unexpected error occurred. Failed to create/update chat.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to Chat Management", callback_data='admin_manage_chats')]]))
    finally: # Ensure context is cleaned up
        context.chat_data.pop('new_chat_info', None)
    return ConversationHandler.END


async def cancel_chat_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the add chat conversation."""
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"Chat creation cancelled by user {user_id}.")
    
    message_text = "Chat creation cancelled."
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("<< Back to Chat Management", callback_data='admin_manage_chats')]])

    try:
        if update.callback_query:
            await update.callback_query.answer()
            if update.effective_message:
                await update.effective_message.edit_text(message_text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(message_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error during cancel_chat_creation for user {user_id}: {e}", exc_info=True)
        # If sending message fails, not much else to do here.
    
    context.chat_data.pop('new_chat_info', None)
    return ConversationHandler.END


# Fallback for conversation if an unhandled state occurs or text is sent unexpectedly
async def conv_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.warning(f"Conversation fallback triggered for user {user_id}. Update: {update.to_json()}")
    try:
        if update.message:
            await update.message.reply_text("Unexpected input. If you're in a process (like adding a chat), please follow the prompts or use /cancel.")
    except Exception as e:
        logger.error(f"Error in conv_fallback for user {user_id}: {e}", exc_info=True)
    return ConversationHandler.END # Or return to a specific state if more appropriate


# --- Global Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Try to send a message to the user if it's a known Update type
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "An unexpected error occurred. The admin has been notified. Please try again later."
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user after an error: {e}", exc_info=True)
    
    # Optionally, notify admins (if configured and error is severe)
    # This part can be customized based on how critical notifications should be.
    # For example, avoid notifying for common errors like BadRequest due to user input.
    # from telegram.error import BadRequest
    # if isinstance(context.error, BadRequest):
    #     logger.warning(f"BadRequest error, not notifying admin: {context.error}")
    #     return

    # Example: Notify admins for non-BadRequest errors
    # admin_ids = context.application.bot_data.get('settings', {}).get('ADMIN_USER_IDS', [])
    # if admin_ids:
    #     tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    #     tb_string = "".join(tb_list)
    #     error_message = (
    #         f"An exception was raised while handling an update\n"
    #         f"<pre>update = {html.escape(json.dumps(update.to_dict(), indent=2, ensure_ascii=False))}</pre>\n"
    #         f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n"
    #         f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n"
    #         f"<pre>{html.escape(tb_string)}</pre>"
    #     )
        
    #     for admin_id in admin_ids:
    #         try:
    #             # Splitting the message if it's too long
    #             max_len = telegram.constants.MessageLimit.MAX_TEXT_LENGTH
    #             for i in range(0, len(error_message), max_len):
    #                 await context.bot.send_message(
    #                     chat_id=admin_id,
    #                     text=error_message[i:i + max_len],
    #                     parse_mode=telegram.constants.ParseMode.HTML
    #                 )
    #         except Exception as e_admin_notify:
    #             logger.error(f"Failed to send error notification to admin {admin_id}: {e_admin_notify}", exc_info=True)
    # The admin notification part is commented out by default to avoid spamming and requires
    # careful consideration of which errors trigger it and message formatting.
    # It also needs imports: import traceback, import html, import json, import telegram.constants
    pass
# This file was updated in the previous turn to include extensive logging and error handling.
# Key changes made previously:
# - Added logger = logging.getLogger(__name__)
# - Wrapped handler logic in try-except blocks (catching SQLAlchemyError and generic Exception).
# - Added detailed logging for function calls, admin actions, errors (with exc_info=True).
# - Sent informative (but not overly detailed) error messages to admins on exceptions, usually via query.answer(..., show_alert=True) or editing the message.
# - Ensured database sessions are handled with `async with async_session_factory() as session:`
# - Used `session.begin()` for transactions where multiple DB operations occur (e.g., creating chat).
# - Conversation handler steps now also have try-except blocks and log errors.
# - `is_admin` decorator logs unauthorized access attempts.
#
# Example of changes in `admin_panel`:
# @is_admin
# async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     user_id = update.effective_user.id if update.effective_user else "Unknown"
#     logger.debug(f"Admin panel accessed by user {user_id}")
#     # ... keyboard setup ...
#     try:
#         if update.callback_query:
#             # ...
#         elif update.message:
#             # ...
#     except Exception as e:
#         logger.error(f"Error in admin_panel for admin {user_id}: {e}", exc_info=True)
#         if update.callback_query:
#             await update.callback_query.answer("An error occurred in admin panel.", show_alert=True)
#         elif update.message:
#             await update.message.reply_text("An error occurred in admin panel. Please check logs.")
#
# Similar error handling and logging patterns were applied to:
# - `manage_chats_callback`, `list_chats_callback`
# - The new chat management functions: `edit_chat_callback` (placeholder), `toggle_chat_status_callback`, `confirm_remove_chat_callback`, `execute_remove_chat_callback`.
# - Placeholder handlers: `view_users_callback`, `configure_wallet_callback`.
# - Navigation handler: `admin_panel_return_callback`.
# - All steps of the `add_chat` conversation handler: `add_chat_start_callback`, `receive_chat_id`, `receive_title`, etc., up to `confirm_create_chat_callback` and `cancel_chat_creation`.
# - `conv_fallback`.
#
# The database commit/rollback strategy:
# - `confirm_create_chat_callback` uses `session.begin()` and `session.commit()` for the new chat.
# - `toggle_chat_status_callback` uses `session.begin()` and `session.commit()` for updating chat status.
# - `execute_remove_chat_callback` uses `session.begin()` and `session.commit()` for deleting a chat.
# DB utility functions like `db_utils.create_chat` do not commit themselves; the commit is handled in the handler to ensure atomicity of the overall operation from the handler's perspective.
