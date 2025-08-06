from fastapi import FastAPI, File, UploadFile, Form, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from context import RAGPipeline, get_emb, RAGIndexer
import pathlib
import os
from utils import get_db
from platformdirs import user_data_dir
from datetime import datetime
from dotenv import load_dotenv

app = FastAPI()

data_dir = user_data_dir("Demo", "ChatDemo")
os.makedirs(data_dir, exist_ok=True)

DATA_DIR = pathlib.Path(data_dir)

env_path = pathlib.Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

URL_RAG = os.getenv('URL_RAG', 'url')
API_KEY_RAG = os.getenv('API_KEY_RAG', 'dummy')
INDEX_RAG = os.getenv('INDEX_RAG', 'docs')

package_dir = pathlib.Path(__file__).parent.absolute()
static_dir = os.path.join(package_dir, "static")
templates_dir = os.path.join(package_dir, "templates")
templates = Jinja2Templates(directory=templates_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

## APIs
@app.post("/add-rag")
async def upload_file_rag(
    file: UploadFile = File(...),
    type_doc: str     = Form(...)
):
    # Solo aceptamos .pdf, .excel, .docx y type_doc consistente
    suffix = pathlib.Path(file.filename).suffix.lower()
    valid = {".pdf":"pdf", ".xlsx":"excel", ".xls":"excel", ".docx":"word"}
    if suffix not in valid or valid[suffix] != type_doc:
        return JSONResponse(
            status_code=400,
            content={"error": f"Solo {', '.join(valid.keys())} con type_doc {list(set(valid.values()))}"}
        )

    target_path = DATA_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    try:
        contents = await file.read()
        with open(target_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"No se pudo leer o escribir el archivo: {e}"}
        )

    r = RAGIndexer(embedding_func=get_emb, host=URL_RAG, 
            api_key_rag=API_KEY_RAG, index_rag=INDEX_RAG)

    try:
        await r.indexdocs(target_path, type_doc=type_doc)

        def _save_doc(path: str, doc_type: str):
            with get_db() as db:
                db.execute(
                    "INSERT INTO docs (path, doc_type) VALUES (?, ?);",
                    str(path),
                    doc_type
                )
                db.commit()

        await run_in_threadpool(_save_doc, target_path, type_doc)

        return {"state": "success"}
    except Exception as e:
        print(f"Error interno al procesar el archivo: {e}")
        return JSONResponse(status_code=500, content={"error": f"Error interno: {e}"})

@app.websocket("/chat")
async def query(websocket: WebSocket):

    await websocket.accept()
    try:
        while True:

            data = await websocket.receive_json()
            query_text = data.get("query", "").strip()
            raw_top_k = data.get("top_k", 5)
            if isinstance(raw_top_k, str):
                raw_top_k = raw_top_k.strip()
            try:
                top_k = int(raw_top_k)
            except (ValueError, TypeError):
                top_k = 5  
            type_sys = data.get("type_sys", "Assistant")
            print(type_sys)
            if not query_text:
                await websocket.send_text("[Error] Query vacío.")
                continue

            r = RAGPipeline(query=query_text, embedding_func=get_emb, model="gpt-4.1", host=URL_RAG, 
                api_key_rag=API_KEY_RAG, index_rag=INDEX_RAG)

            async def send_delta(delta_text: str):
                await websocket.send_text(delta_text)
            
            await r.answer(func=send_delta, top_k=top_k)

            await websocket.close()
            break

    except WebSocketDisconnect:
        print("Cliente desconectado.")

@app.get("/getdocs")
async def get_docs_rout():
    try:
        def _list_docs():
            with get_db() as db:
                rows = db.fetch_all(
                    "SELECT id, path, doc_type, created_at FROM docs ORDER BY created_at DESC;"
                )

                keys = ["id", "path", "doc_type", "created_at"]
                docs = []
                for r in rows:
                    doc = dict(zip(keys, r))
                    if isinstance(doc["created_at"], datetime):
                        doc["created_at"] = doc["created_at"].isoformat()
                    docs.append(doc)
                return docs

        docs = await run_in_threadpool(_list_docs)

        return JSONResponse(
            status_code=200,
            content={"docs": docs}
        )

    except Exception as e:
        print(f"Error interno al recuperar los archivos: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error interno al recuperar los archivos: {e}"}
        )

@app.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/upload", response_class=HTMLResponse)
async def upload(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

if __name__=="__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5600)