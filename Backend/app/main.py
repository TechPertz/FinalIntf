from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# from app.routes import audit, regulation_csv, regulation_pdf, sop
from app.routes import regulation_pdf
from app.routes import audit

app = FastAPI(
    title="GraphRAG API",
    description="API for GraphRAG application",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers with filename-based prefixes
app.include_router(audit.router, prefix="/api/audit")
# app.include_router(regulation_csv.router, prefix="/api/regulation-csv")
app.include_router(regulation_pdf.router, prefix="/api/regulation-pdf")
# app.include_router(sop.router, prefix="/api/sop")

@app.get("/")
async def root():
    return {"message": "Welcome to GraphRAG API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
