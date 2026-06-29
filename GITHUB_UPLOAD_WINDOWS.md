# GITHUB_UPLOAD_WINDOWS.md

## Goal

Upload this Flask + EasyOCR project from Windows to GitHub so Codex can work on it.

Codex web/cloud works best with GitHub repositories. OpenAI docs say Codex web connects to GitHub repositories and can create pull requests from its work.

---

## Before you start

Install these on Windows:

1. Git for Windows  
   https://git-scm.com/download/win

2. Optional but recommended: GitHub Desktop  
   https://desktop.github.com/

3. Optional: VS Code  
   https://code.visualstudio.com/

---

## Option A: Command line method

Assume you extracted the ZIP to:

```text
C:\Users\intag\Desktop\webproject\easyocr_flask_demo
```

Open PowerShell.

Go to the folder:

```powershell
cd C:\Users\intag\Desktop\webproject\easyocr_flask_demo
```

Check files:

```powershell
dir
```

You should see:

```text
app.py
wsgi.py
requirements.txt
app
tools
README.md
CODEX_CONTEXT.md
GITHUB_UPLOAD_WINDOWS.md
```

Initialize Git:

```powershell
git init
```

Set your Git identity if needed:

```powershell
git config --global user.name "Your Name"
git config --global user.email "your-email@example.com"
```

Add files:

```powershell
git add .
```

Commit:

```powershell
git commit -m "Initial EasyOCR Flask demo for Codex"
```

Create a new GitHub repository from the GitHub website:

```text
https://github.com/new
```

Suggested repo name:

```text
easyocr-flask-demo
```

Recommended visibility:

```text
Private
```

Do not add README/license/gitignore from GitHub website because this project already includes them.

After creating the GitHub repo, GitHub will show commands. They will look like this:

```powershell
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/easyocr-flask-demo.git
git push -u origin main
```

Run those commands in PowerShell.

If Git asks you to sign in, follow the browser login.

---

## Option B: GitHub Desktop method

1. Open GitHub Desktop.
2. File -> Add local repository.
3. Choose your extracted folder:

```text
C:\Users\intag\Desktop\webproject\easyocr_flask_demo
```

4. If it asks to create repository, choose create.
5. Commit all files with message:

```text
Initial EasyOCR Flask demo for Codex
```

6. Click "Publish repository".
7. Choose private repository unless you intentionally want public.

---

## After upload: connect to Codex

1. Open ChatGPT/Codex.
2. Connect GitHub if not connected yet.
3. Select this repository.
4. Start a new Codex task.

Use this prompt:

```text
This is a Flask + EasyOCR demo for Thai bank-transfer slip OCR.

Please first read:
- README.md
- CODEX_CONTEXT.md
- app/services/generic_rule_ocr_service.py
- app/services/batch_job_service.py
- tools/process_zip_generic_rules.py

Important constraints:
- No database yet.
- Generic Rules OCR is the main extraction engine.
- QR and future LLM should be support/fallback only.
- Single-image OCR and batch OCR must use the same rule parser.
- Batch jobs are file-based under storage/jobs/.
- Keep changes small and safe.

Current known issue:
Batch processing currently runs inside Gunicorn. Large ZIP batches can hit Gunicorn timeout or worker SIGKILL. Temporary server fix is gunicorn --timeout 900. The better future direction is a separate worker service.

First task:
Add better progress/debug logging for batch jobs:
- Store current filename and index in job_status.json before each image.
- Store per-image start/end timestamps.
- Mark stale processing jobs as failed on startup.
- Do not add a database.
- Keep existing UI/API behavior.
```

---

## Files intentionally ignored by Git

The `.gitignore` excludes:

```text
venv/
__pycache__/
storage/
uploads/
results/
*.zip
.env
```

Do not upload real bank-slip images, customer data, generated job folders, or OCR results to GitHub.
