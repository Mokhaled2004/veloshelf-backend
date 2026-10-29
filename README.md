Create and activate a Python virtual environment:

macOS / Linux:

Bash
python -m venv venv
source venv/bin/activate
Windows (PowerShell):

PowerShell
python -m venv venv
.\venv\Scripts\Activate.ps1
Install dependencies:

Bash
pip install -r requirements.txt
Configure your environment variables:
Create a .env file in the root of the veloshelf-backend directory with your database connection string:

Code snippet
DATABASE_URL=postgresql://your_neon_connection_string_here
REDIS_URL=redis://localhost:6379/0
How to Run the Code Daily
Activate the virtual environment:

Bash
# Windows PowerShell
.\venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate
Start the development server:

Bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
Verify it is running:

Health endpoint: http://127.0.0.1:8000/health

Interactive Swagger UI: http://127.0.0.1:8000/docs