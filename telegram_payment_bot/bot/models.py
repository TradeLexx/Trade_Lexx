from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric, BigInteger, JSON
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    subscriptions = relationship("Subscription", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"

class Chat(Base):
    __tablename__ = 'chats'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id = Column(BigInteger, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    price_amount = Column(Numeric(10, 2), nullable=False)
    price_currency = Column(String(10), nullable=False)
    crypto_wallet_address = Column(String, nullable=True)
    crypto_network = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    subscriptions = relationship("Subscription", back_populates="chat")

    def __repr__(self):
        return f"<Chat(id={self.id}, telegram_chat_id={self.telegram_chat_id}, title='{self.title}')>"

class Subscription(Base):
    __tablename__ = 'subscriptions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False, index=True)
    start_date = Column(DateTime, nullable=False, default=func.now())
    end_date = Column(DateTime, nullable=False, index=True)
    status = Column(String(20), nullable=False, default='pending')  # e.g., 'pending_payment', 'active', 'expired', 'cancelled'
    payment_id = Column(String, nullable=True, unique=True)  # ID from payment gateway or transaction hash
    payment_details = Column(JSON, nullable=True) # Store temporary payment info, like generated address or invoice details
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="subscriptions")
    chat = relationship("Chat", back_populates="subscriptions")

    def __repr__(self):
        return f"<Subscription(id={self.id}, user_id={self.user_id}, chat_id={self.chat_id}, status='{self.status}')>"

class Admin(Base):
    __tablename__ = 'admins'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    is_super_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Admin(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"

# Example of how to create the engine and tables (optional, for testing or main script)
# if __name__ == '__main__':
#     # Replace with your actual database URL from config
#     DATABASE_URL = "sqlite:///./test_database.db" 
#     engine = create_engine(DATABASE_URL)
#     Base.metadata.create_all(engine)
#     print("Database tables created successfully.")
