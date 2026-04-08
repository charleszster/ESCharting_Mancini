# ES Trade Analyzer — Setup

## Prerequisites
- Python 3.11+
- Node.js 18+
- Git (https://git-scm.com)
- A Databento account and API key (https://databento.com)

## First-time setup

### 1. Clone the repo
```
git clone https://github.com/charleszster/ESCharting_Mancini.git
cd ESCharting_Mancini
```

### 2. Backend
```
cd backend
python -m venv venv
venv\Scripts\activate
pip install fastapi uvicorn pandas pyarrow openpyxl databento python-dotenv sqlalchemy
```

### 3. Environment
Edit the `.env` file in the project root and replace the placeholder:
```
DATABENTO_API_KEY=your_key_here
```

### 4. Frontend
```
cd frontend
npm install
```

### 5. First run — import historical CSV data
With the backend running, use the Settings panel to point the app at your
existing ES 1-minute CSV file. The app will convert it to Parquet automatically.
This is a one-time step.

## Running the app
```
# Terminal 1 (backend):
cd backend
venv\Scripts\activate
uvicorn main:app --reload

# Terminal 2 (frontend):
cd frontend
npm run dev
```

Then open http://localhost:5173 in your browser.

## Git workflow
After each session, commit your changes:
```
git add .
git commit -m "brief description of what was built"
git push
```

To roll back to a previous working state:
```
git log                          # find the commit hash you want
git checkout <hash> .            # restore files to that state
```
