import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings # Assuming settings is loaded
from .models import Base
from . import handlers as user_handlers # Renamed to avoid confusion
from . import admin_handlers

# Set up basic logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    if not settings.TELEGRAM_BOT_TOKEN or not settings.DATABASE_URL:
        logger.error("CRITICAL: TELEGRAM_BOT_TOKEN or DATABASE_URL is not configured. Exiting.")
        return

    logger.info("Starting bot...")
    logger.info(f"Admin User IDs: {settings.ADMIN_USER_IDS}")

    engine = create_async_engine(str(settings.DATABASE_URL))
    async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables checked/created.")

    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Make session factory and settings available to handlers
    application.bot_data['async_session_factory'] = async_session_factory
    application.bot_data['settings'] = settings # Pass the full settings object
    logger.info("Async session factory and settings object added to bot_data.")

    # --- Global Error Handler ---
    application.add_error_handler(admin_handlers.error_handler) # Assuming error_handler is in admin_handlers or a common place
    logger.info("Global error handler registered.")

    # --- User Command Handlers ---
    application.add_handler(CommandHandler("start", user_handlers.start))
    application.add_handler(CommandHandler("help", user_handlers.help_command))
    application.add_handler(CommandHandler("panel", user_handlers.user_panel))
    logger.info("User command handlers for 'start', 'help', and 'panel' added.")

    # --- User Callback Query Handlers ---
    application.add_handler(CallbackQueryHandler(user_handlers.user_subscribe_callback, pattern='^user_subscribe$'))
    application.add_handler(CallbackQueryHandler(user_handlers.user_my_subscriptions_callback, pattern='^user_my_subscriptions$'))
    application.add_handler(CallbackQueryHandler(user_handlers.user_renew_callback, pattern='^user_renew$'))
    application.add_handler(CallbackQueryHandler(user_handlers.select_chat_callback, pattern=r'^select_chat_\d+$'))
    application.add_handler(CallbackQueryHandler(user_handlers.confirm_payment_callback, pattern=r'^confirm_payment_\d+$'))
    application.add_handler(CallbackQueryHandler(user_handlers.user_panel_return_callback, pattern='^user_panel_return$'))
    logger.info("User callback query handlers added.")

    # --- Admin Command Handler ---
    application.add_handler(CommandHandler("admin", admin_handlers.admin_panel))
    logger.info("Admin command handler for 'admin' added.")

    # --- Admin Callback Query Handlers ---
    application.add_handler(CallbackQueryHandler(admin_handlers.admin_panel_callback, pattern='^admin_panel_return$')) # For returning to admin panel
    application.add_handler(CallbackQueryHandler(admin_handlers.manage_chats_callback, pattern='^admin_manage_chats$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.list_chats_callback, pattern='^admin_list_chats$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.view_users_callback, pattern='^admin_view_users$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.configure_wallet_callback, pattern='^admin_configure_wallet$'))
    # Stubs for edit/remove chat - can be expanded later
    application.add_handler(CallbackQueryHandler(admin_handlers.edit_chat_callback, pattern=r'^admin_edit_chat_\d+$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.remove_chat_callback, pattern=r'^admin_remove_chat_\d+$'))
    logger.info("Admin callback query handlers added.")

    # --- Admin Conversation Handler for Adding Chat ---
    add_chat_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_handlers.add_chat_start_callback, pattern='^admin_add_chat_start$')],
        states={
            admin_handlers.CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.receive_chat_id)],
            admin_handlers.TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.receive_title)],
            admin_handlers.PRICE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.receive_price_amount)],
            admin_handlers.PRICE_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.receive_price_currency)],
            admin_handlers.WALLET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.receive_wallet_address)],
            admin_handlers.NETWORK: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.receive_network)],
            admin_handlers.CONFIRM_CHAT_CREATION: [
                CallbackQueryHandler(admin_handlers.confirm_create_chat_callback, pattern='^admin_confirm_create_chat$'),
                CallbackQueryHandler(admin_handlers.add_chat_start_callback, pattern='^admin_add_chat_start$'), # Re-start if "No"
                CallbackQueryHandler(admin_handlers.cancel_chat_creation, pattern='^admin_cancel_chat_creation$')
            ],
        },
        fallbacks=[
            CommandHandler('cancel', admin_handlers.cancel_chat_creation),
            CallbackQueryHandler(admin_handlers.cancel_chat_creation, pattern='^admin_cancel_chat_creation$'),
            MessageHandler(filters.COMMAND, admin_handlers.conv_fallback) # Catch other commands
        ],
        per_user=True, # Store conversation state per user
        per_chat=False # Not per chat, as admin commands are usually in DMs
    )
    application.add_handler(add_chat_conv_handler)
    logger.info("Admin conversation handler for adding chats added.")

    # Initialize and start APScheduler
    scheduler = AsyncIOScheduler(timezone="UTC") # TODO: Consider making timezone configurable via settings
    
    # Use settings for job scheduling if applicable (e.g. reminder days for query, or cron times)
    # For now, cron times are hardcoded, but reminder_days_ahead will be used by the job function itself.
    scheduler.add_job(user_handlers.send_renewal_reminders, 'cron', hour=9, minute=0, job_kwargs={'context': application}) # Example: daily at 9 AM UTC
    scheduler.add_job(user_handlers.process_expired_subscriptions, 'cron', hour=1, minute=0, job_kwargs={'context': application}) # Example: daily at 1 AM UTC
    
    scheduler.start()
    logger.info("APScheduler started with jobs for renewal reminders and expired subscriptions.")

    logger.info("Running bot application...")
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        logger.info("Bot is running. Press Ctrl-C to exit.")
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested...")
    except Exception as e:
        logger.error(f"Error running bot application: {e}", exc_info=True)
    finally:
        if application.updater and application.updater.running:
            await application.updater.stop()
        if application.running:
            await application.stop()
        if scheduler.running:
            scheduler.shutdown()
            logger.info("APScheduler shutdown.")
        await engine.dispose()
        logger.info("Database engine disposed.")
        logger.info("Bot stopped.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except RuntimeError as e:
        logger.error(f"Asyncio runtime error: {e}")
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}", exc_info=True)
