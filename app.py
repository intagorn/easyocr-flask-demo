import os

# Temporary workaround for possible Windows/Anaconda OpenMP conflict.
# If your environment already works without this, you can remove it later.
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # python-dotenv is optional for deployment if environment variables are set by systemd.
    pass

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
