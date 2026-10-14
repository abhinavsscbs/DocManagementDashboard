# DocManagementDashboard

Document-processing dashboard with a Flask backend and React/Vite frontend. It provides processing workflows for EY, PwC, IFRS, and combined knowledge sources, with configurable FAISS storage and CSV downloads.

## Layout

| Path | Purpose |
| --- | --- |
| `backend/app.py` | Flask application entry point |
| `backend/api/` | Processing and download routes |
| `backend/extractors/` | Source document extraction |
| `backend/services/` | Processing services |
| `backend/config.yaml` | Server, document, model, and index configuration |
| `frontend/` | React UI with Material UI components |
| `json_structure.txt` | Reference data structure |

## Local setup

Requires Python and Node.js/npm, along with the configured model and source files.

```bash
git clone https://github.com/abhinavsscbs/DocManagementDashboard.git
cd DocManagementDashboard
python -m venv .venv
# Activate .venv before continuing.
python -m pip install -r backend/requirements.txt
```

Review `backend/config.yaml`: configure server port and CORS origins, FAISS directories, document names, embedding model, and upload limits for your environment.

```bash
cd backend
python app.py
```

In a separate terminal, start the React UI:

```bash
cd frontend
npm install
npm run dev
```

Create a production UI build with `npm run build`.

## Usage

Open the frontend URL shown by Vite, select the relevant source-processing workflow, and supply its required inputs. Use the available CSV download after processing. The backend provides `GET /health` for a basic health check.
