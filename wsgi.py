try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from app import create_app

app = create_app()
